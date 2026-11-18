"""The refill of the candidate queue (`kb/discover.py`; `docs/specs/population.md`, "Discovery"), and the command that shows what it would do.

No test opens a socket, starts a process or reads the owner's library or config: the sources are fakes or the real source modules with a fake
`get`, the clock and the sleep are fakes, the queue and every file are in a temporary folder, and the command runs in this process against a
config folder that the test makes."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_srcopenalex import fixture as openalex_fixture
from engine.tests.test_srcopenalex import ok

from kb import KbError, __main__ as cli, crawlqueries, crawlqueue, crawltopics, discover, srcarxiv, srcopenalex

NOW = "2026-11-16T10:00:00Z"
LATER = "2026-11-17T10:00:00Z"
FIXTURES = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawl"
TOPICS = [("Control theory", 10, "core"), ("Signal processing", 10, "core"), ("Category theory", 5, "exploratory"), ("SystemVerilog", 1, "low")]
HOSTS = lambda host: ".".join(host.split(".")[-2:])  # noqa: E731  a stand-in for webaddr.site_of
KW = {"canon_address": lambda a: a, "site_of": HOSTS}


def candidate(address, source="openalex", **kw):
    return dict({"address": address, "source": source, "found_from": "q", "depth": 0}, **kw)


class Source:
    """A fake source: `search` answers from a function of the query, and every call is kept."""

    def __init__(self, name, rows=None, refuse=None, for_day=True):
        self.name, self.rows, self.refuse, self.for_day = name, rows or (lambda q: []), refuse, for_day
        self.searches, self.wanders = [], []

    def search(self, query, get, limit, *more):
        self.searches.append((query, limit))
        if self.refuse:
            raise srcopenalex.SourceRefused(self.refuse, for_day=self.for_day)
        return {"candidates": [dict(c, found_from=query) for c in self.rows(query)], "rejected": []}

    def wander(self, kept, get, per_work, max_depth, seen=()):
        self.wanders.append((list(kept), per_work, max_depth, set(seen)))
        return {"candidates": [], "rejected": []}


def rows_for(source, n=3):
    def rows(query):
        stem = "".join(c for c in query.lower() if c.isalnum())
        return [candidate(f"https://{source}.example.org/{stem}/{i}", "web-search" if source == "web" else source) for i in range(n)]
    return rows


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, step, outcome, **fields):
        self.lines.append((step, outcome, fields))

    def of(self, step, outcome=None):
        return [f for s, o, f in self.lines if s == step and (outcome is None or o == outcome)]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = crawlqueue.connect(self.tmp.name)
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.log = Log()

    def sources(self, openalex=None, arxiv=None, wikipedia=None):
        return {"openalex": openalex or Source("openalex", rows_for("openalex")), "arxiv": arxiv or Source("arxiv", rows_for("arxiv")),
                "wikipedia": wikipedia or Source("wikipedia", rows_for("wikipedia"))}

    def crowded(self, total, name="openalex", extra=5):
        """A source that, on its first answer, finds the queue filled to `total` by another writer, and then gives new rows."""
        done = []

        def rows(query):
            if not done:
                done.append(1)
                for i in range(total):
                    crawlqueue.enqueue(self.conn, candidate(f"https://writer{i}.example.net/x"), limits={"queued_total": 10**6, "queued_per_domain": 10**6},
                                       now=NOW, **KW)
            return [candidate(f"https://{name}.example.org/new{i}") for i in range(extra)]

        return Source(name, rows)

    def fill(self, plan=None, topics=None, now=NOW, sources=None, **kw):
        kw.setdefault("get", lambda url, headers=None, timeout=None: (_ for _ in ()).throw(AssertionError("a real request")))
        kw.setdefault("clock", self.clock)
        kw.setdefault("sleep", self.clock.sleep)
        kw.setdefault("log", self.log)
        return discover.fill(self.conn, plan or {}, TOPICS if topics is None else topics, now=now,
                             sources=self.sources() if sources is None else sources, **KW, **kw)

    def rows(self, where=""):
        self.conn.row_factory = None
        return self.conn.execute(f"SELECT address, source, topic, weight, depth, found_from, status, reason FROM candidates {where} ORDER BY id").fetchall()

    def counters(self):
        return dict(((d, k), n) for d, k, n in self.conn.execute("SELECT day, key, n FROM counters"))


class PlanTest(unittest.TestCase):
    def test_every_key_has_the_default_the_spec_gives(self):
        self.assertEqual(discover.normalize_plan({}), {
            "queued_total": 20000, "queued_per_domain": 50, "queue_low": 100, "discover_target": 200, "queries_per_topic": 3,
            "wander_share": 0.2, "wander_depth": 2, "wander_per_work": 5, "openalex": True, "openalex_key": False, "arxiv": True, "wikipedia": True,
            "web_search": False, "web_search_engine": "duckduckgo", "gap_openalex_s": 1, "gap_arxiv_s": 3, "gap_wikipedia_s": 1, "gap_web_search_s": 30,
            "web_search_per_day": 20})

    def test_a_value_given_replaces_the_default_and_the_rest_stay(self):
        got = discover.normalize_plan({"queue_low": 5, "wikipedia": False, "wander_share": 0.5, "gap_arxiv_s": 10})
        self.assertEqual((got["queue_low"], got["wikipedia"], got["wander_share"], got["gap_arxiv_s"], got["arxiv"]), (5, False, 0.5, 10, True))

    def test_a_key_that_is_not_one_of_the_plan_is_refused_by_name(self):
        for key in ("fetches_per_day", "batch", "colour", "", None, 5):
            with self.subTest(key=key):
                with self.assertRaises(KbError):
                    discover.normalize_plan({key: 1})

    def test_values_of_the_wrong_kind_or_out_of_range_are_refused(self):
        bad = {"queued_total": (0, -1, 1.5, True, "5", 10**7), "queued_per_domain": (0, True, 10**6), "queue_low": (-1, 1.5, True, 10**7),
               "discover_target": (0, 2001, True), "queries_per_topic": (0, 11, True), "wander_share": (-0.1, 1.1, "0.5", True, float("nan")),
               "wander_depth": (-1, 11, 1.5, True), "wander_per_work": (0, 21, True), "openalex": (1, "on", None), "web_search": (0, "yes"),
               "gap_openalex_s": (-1, 3601, "1", True, float("inf")), "gap_arxiv_s": (-0.5, 3601), "web_search_per_day": (-1, 1001, True)}
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(KbError):
                        discover.normalize_plan({key: value})

    def test_the_edges_are_taken(self):
        discover.normalize_plan({"queue_low": 0, "discover_target": 2000, "queries_per_topic": 10, "wander_share": 0, "wander_depth": 0,
                                 "wander_per_work": 20, "gap_openalex_s": 0, "gap_arxiv_s": 3600, "web_search_per_day": 0})
        discover.normalize_plan({"wander_share": 1})
        discover.normalize_plan({"wander_share": 1.0})

    def test_the_plan_must_be_a_dictionary(self):
        for plan in (None, [], "x", 5):
            with self.assertRaises(KbError):
                discover.normalize_plan(plan)


class PlanEdgeTest(unittest.TestCase):
    def test_each_number_is_taken_at_its_edges_and_not_one_beyond(self):
        edges = {"queued_total": (1, 10**6), "queued_per_domain": (1, 10**5), "queue_low": (0, 10**6), "discover_target": (1, 2000),
                 "queries_per_topic": (1, 10), "wander_depth": (0, 10), "wander_per_work": (1, 20), "web_search_per_day": (0, 1000),
                 "gap_openalex_s": (0, 3600), "gap_arxiv_s": (0, 3600), "gap_wikipedia_s": (0, 3600), "gap_web_search_s": (0, 3600),
                 "wander_share": (0, 1)}
        for key, (low, high) in edges.items():
            with self.subTest(key=key):
                self.assertEqual(discover.normalize_plan({key: low})[key], low)
                self.assertEqual(discover.normalize_plan({key: high})[key], high)
                for outside in (low - 1, high + 1):
                    with self.assertRaises(KbError):
                        discover.normalize_plan({key: outside})

    def test_a_fraction_is_taken_where_a_number_of_seconds_or_a_share_is_and_not_where_a_count_is(self):
        self.assertEqual(discover.normalize_plan({"gap_wikipedia_s": 0.5})["gap_wikipedia_s"], 0.5)
        self.assertEqual(discover.normalize_plan({"wander_share": 0.25})["wander_share"], 0.25)
        for key in ("queue_low", "discover_target", "wander_per_work", "web_search_per_day"):
            with self.assertRaises(KbError):
                discover.normalize_plan({key: 2.5})


class UnitTest(unittest.TestCase):
    def test_the_picks_are_taken_one_topic_at_a_time_in_turn(self):
        self.assertEqual(discover._in_turn([2, 1, 0, 3]), [0, 1, 3, 0, 3, 3])
        self.assertEqual(discover._in_turn([]), [])
        self.assertEqual(discover._in_turn([0, 0]), [])
        self.assertEqual(discover._in_turn([3]), [0, 0, 0])

    def test_the_target_is_split_by_the_wander_share_and_the_room_the_queue_has(self):
        plan = discover.normalize_plan({"discover_target": 30, "wander_share": 0.2})
        self.assertEqual(discover._parts(plan), (24, 6))
        self.assertEqual(discover._parts(dict(plan, queued_total=25), queued=15), (8, 2))  # room for ten rows
        self.assertEqual(discover._parts(dict(plan, queued_total=10), queued=15), (0, 0))  # none
        self.assertEqual(discover._parts(dict(plan, wander_share=1), queued=0), (0, 30))
        self.assertEqual(discover._parts(dict(plan, wander_share=0), queued=0), (30, 0))
        self.assertEqual(discover._parts(dict(plan, discover_target=11, wander_share=0.5)), (6, 5))  # the wander part is rounded down

    def test_the_number_of_picks_is_the_topic_part_over_ten_at_least_one_and_at_most_fifty(self):
        day = discover.date_of(NOW)
        plan = discover.normalize_plan({})
        for part, want in ((1, 1), (10, 1), (11, 2), (15, 2), (30, 3), (499, 50), (500, 50), (501, 50), (2000, 50)):
            with self.subTest(part=part):
                self.assertEqual(len(discover._picks(plan, TOPICS, part, day)), want)
        self.assertEqual(discover._picks(plan, TOPICS, 0, day), [])
        self.assertEqual(discover._picks(plan, [], 30, day), [])

    def test_the_picks_are_those_of_the_days_quota(self):
        day = discover.date_of(NOW)
        plan = discover.normalize_plan({})
        quota = crawltopics.quota(TOPICS, 3, (day - discover.datetime.date(1970, 1, 1)).days)
        self.assertEqual(discover._picks(plan, TOPICS, 30, day), discover._in_turn(quota))
        many = [(f"Topic {i}", 1, "s") for i in range(5)]
        days = (day - discover.datetime.date(1970, 1, 1)).days
        self.assertEqual(discover._picks(plan, many, 300, day), discover._in_turn(crawltopics.quota(many, 30, days)))  # 30 picks for 300 rows

    def test_a_time_is_a_utc_time_with_a_date_that_exists(self):
        self.assertEqual(discover.date_of("2026-11-16T10:00:00Z").isoformat(), "2026-11-16")
        for bad in ("2026-11-16", "2026-11-16T10:00:00", "2026-11-16T10:00:00+00:00", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "", None, 5,
                    "2026-11-16T10:00:00Z ", " 2026-11-16T10:00:00Z", "26-11-16T10:00:00Z"):
            with self.subTest(now=bad):
                with self.assertRaises(KbError):
                    discover.date_of(bad)


class GapTest(unittest.TestCase):
    def test_the_gap_is_slept_whole_after_a_request_at_once_and_in_part_after_a_while_and_never_longer_than_itself(self):
        clock = Clock()
        gap = discover._Gap(2.0, clock, clock.sleep)
        gap.wait()
        self.assertEqual(clock.slept, [])
        gap.wait()
        self.assertEqual(clock.slept, [2.0])
        clock.now += 0.5
        gap.wait()
        self.assertEqual(clock.slept, [2.0, 1.5])
        clock.now += 2.0
        gap.wait()
        self.assertEqual(clock.slept, [2.0, 1.5])
        clock.now -= 500.0
        gap.wait()
        self.assertEqual(clock.slept, [2.0, 1.5, 2.0])

    def test_a_wait_that_slept_is_the_start_of_the_next_gap_and_a_gap_of_nothing_never_sleeps(self):
        clock = Clock()
        gap = discover._Gap(2.0, clock, clock.sleep)
        for _ in range(4):
            gap.wait()
        self.assertEqual(clock.slept, [2.0, 2.0, 2.0])
        none = discover._Gap(0, clock, clock.sleep)
        for _ in range(3):
            none.wait()
        self.assertEqual(len(clock.slept), 3)

    def test_the_get_that_is_paced_waits_first_and_passes_the_address_the_headers_and_the_timeout_on(self):
        clock, seen = Clock(), []
        gap = discover._Gap(3.0, clock, clock.sleep)

        def get(url, headers=None, timeout=None):
            seen.append((url, headers, timeout, clock.now))
            return 200, {}, b"x"

        paced = discover._paced(get, gap)
        self.assertEqual(paced("https://a.example/", headers={"X": "1"}, timeout=7), (200, {}, b"x"))
        paced("https://b.example/")
        self.assertEqual(seen, [("https://a.example/", {"X": "1"}, 7, 1000.0), ("https://b.example/", None, None, 1003.0)])


class ReadPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text, name="plan.txt", raw=False):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb" if raw else "w", **({} if raw else {"encoding": "utf-8"})) as f:
            f.write(text)
        return path

    def test_the_form_of_the_spec_is_read_and_the_keys_this_plan_does_not_use_are_left_alone(self):
        got = discover.read_plan(self.write("""
# the plan
[limits]
fetches_per_day = 20        # candidate fetches started per local day
queue_low = 50
discover_target = 120       # rows one refill adds
queued_total = 5000
queued_per_domain = 40
queries_per_topic = 2
timezone = local
[pacing]
min_gap_s = 8
[sources]
openalex = on
arxiv = off
wikipedia = on
web_search = off            # duckduckgo to use it
wander_share = 0.25
wander_depth = 1
wander_per_work = 4
gap_openalex_s = 2
gap_arxiv_s = 5
gap_wikipedia_s = 1.5
gap_web_search_s = 60
web_search_per_day = 10
[lists]
phishing_domains = on
[files]
topics = ~/.config/knowledge-base/crawl-topics.txt
"""))
        self.assertEqual(got, {"queue_low": 50, "discover_target": 120, "queued_total": 5000, "queued_per_domain": 40, "queries_per_topic": 2,
                               "openalex": True, "arxiv": False, "wikipedia": True, "web_search": False, "wander_share": 0.25, "wander_depth": 1,
                               "wander_per_work": 4, "gap_openalex_s": 2, "gap_arxiv_s": 5, "gap_wikipedia_s": 1.5, "gap_web_search_s": 60,
                               "web_search_per_day": 10})

    def test_a_file_with_none_of_the_keys_gives_no_value_and_so_the_defaults(self):
        self.assertEqual(discover.read_plan(self.write("# nothing\n[limits]\nbatch = 8\n")), {})
        self.assertEqual(discover.normalize_plan(discover.read_plan(self.write(""))), discover.normalize_plan({}))

    def test_web_search_is_on_when_it_names_duckduckgo_and_off_when_it_says_off(self):
        for text, want in (("duckduckgo", True), ("DuckDuckGo", True), ("on", True), ("off", False), ("OFF", False)):
            with self.subTest(text=text):
                self.assertEqual(discover.read_plan(self.write(f"[sources]\nweb_search = {text}\n"))["web_search"], want)
        for text in ("bing", "", "yes", "1"):
            with self.subTest(text=text):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(f"[sources]\nweb_search = {text}\n"))

    def test_a_hash_starts_a_comment_anywhere_in_a_plan_line(self):
        self.assertEqual(discover.read_plan(self.write("[limits]\nqueue_low = 7 # seven\n# queue_low = 99\n")), {"queue_low": 7})

    def test_a_malformed_line_is_refused_and_names_the_line_without_quoting_it(self):
        for text in ("queue_low = 5\n", "[limits\nqueue_low = 5\n", "[limits]\nqueue_low 5\n", "[limits]\nqueue_low = \n", "[limits]\n= 5\n",
                     "[limits]\nqueue_low = 5 6\n", "[limits]\nqueue_low = five\n", "[limits]\nqueue_low = 5\nqueue_low = 6\n", "[ limits ]\n",
                     "[limits]\nqueue_low == 5\n", "[limits]\nqueue_low = 1.5\n", "[limits]\nqueue_low = -1\n", "[sources]\nopenalex = maybe\n"):
            with self.subTest(text=text):
                with self.assertRaises(KbError) as cm:
                    discover.read_plan(self.write(text))
                self.assertIn("line", str(cm.exception))
                self.assertNotIn("five", str(cm.exception))

    def test_the_same_key_in_two_sections_is_not_a_repeat_and_duckduckgo_is_a_value_for_web_search_only(self):
        self.assertEqual(discover.read_plan(self.write("[a]\nname = 1\n[b]\nname = 2\n")), {})
        for key in ("openalex", "arxiv", "wikipedia"):
            with self.subTest(key=key):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(f"[sources]\n{key} = duckduckgo\n"))

    def test_lines_may_be_indented_and_have_spaces_after_them(self):
        self.assertEqual(discover.read_plan(self.write("\t[limits]  \n  queue_low = 5   \n\t\tdiscover_target=40\t\n")),
                         {"queue_low": 5, "discover_target": 40})

    def test_a_line_that_is_more_than_a_section_is_refused_and_so_is_a_key_before_any_section(self):
        for text in ("[limits] extra\nqueue_low = 5\n", "[limits]x\n", "name = 1\n", "# a comment\nhold_kinds =\n", "queue_low = 5\n[limits]\n"):
            with self.subTest(text=text):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(text))

    def test_a_run_of_thousands_of_digits_is_a_refusal_and_not_an_error_of_the_interpreter(self):
        for section, text in (("limits", "queue_low = " + "9" * 5000), ("sources", "wander_share = 0." + "9" * 5000),
                              ("sources", "gap_arxiv_s = " + "9" * 5000 + ".5"), ("limits", "discover_target = " + "1" * 4301),
                              ("sources", "gap_arxiv_s = " + "9" * 5000), ("limits", "queue_low = 1234567890"),
                              ("sources", "wander_share = 0.1234567890123456")):
            with self.subTest(text=text[:30]):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(f"[{section}]\n{text}\n"))
        self.assertEqual(discover.read_plan(self.write("[limits]\nqueue_low = 123456789\n[sources]\nwander_share = 0.123456789012345\n")),
                         {"queue_low": 123456789, "wander_share": 0.123456789012345})

    def test_a_number_that_is_not_a_plain_number_is_refused(self):
        for text in ("wander_share = 0.5abc", "wander_share = 1.2.3", "wander_share = .", "wander_share = .5", "wander_share = 5.", "gap_arxiv_s = 3s",
                     "gap_arxiv_s = 3 s", "gap_arxiv_s = --3", "gap_arxiv_s = 1e3", "gap_arxiv_s = 0x10"):
            with self.subTest(text=text):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(f"[sources]\n{text}\n"))
        self.assertEqual(discover.read_plan(self.write("[sources]\nwander_share = 0.5\ngap_arxiv_s = 3\ngap_wikipedia_s = 0.25\n")),
                         {"wander_share": 0.5, "gap_arxiv_s": 3, "gap_wikipedia_s": 0.25})

    def test_a_key_of_the_plan_in_another_section_is_refused(self):
        with self.assertRaises(KbError):
            discover.read_plan(self.write("[sources]\nqueue_low = 5\n"))
        with self.assertRaises(KbError):
            discover.read_plan(self.write("[limits]\nopenalex = on\n"))

    def test_the_file_is_read_as_the_topics_file_is_read(self):
        folder = self.tmp.name
        real = self.write("[limits]\nqueue_low = 5\n")
        os.symlink(real, os.path.join(folder, "link.txt"))
        os.mkdir(os.path.join(folder, "dir"))
        os.mkfifo(os.path.join(folder, "pipe"))
        for name in ("link.txt", "dir", "pipe", "missing.txt"):
            with self.subTest(name=name):
                with self.assertRaises(KbError):
                    discover.read_plan(os.path.join(folder, name))
        for body in (b"[limits]\nqueue_low = 5\n" + b"#" * (256 * 1024), b"[limits]\nqueue_low = \xff\n", b"[limits]\nqueue_low = 5\x00\n"):
            with self.subTest(body=body[:20]):
                with self.assertRaises(KbError):
                    discover.read_plan(self.write(body, raw=True))
        for path in (None, 5, "", b"x"):
            with self.assertRaises(KbError):
                discover.read_plan(path)

    def test_the_values_read_are_what_the_plan_takes(self):
        got = discover.normalize_plan(discover.read_plan(self.write("[limits]\nqueue_low = 0\n[sources]\nwander_share = 1\ngap_arxiv_s = 3\n")))
        self.assertEqual((got["queue_low"], got["wander_share"], got["gap_arxiv_s"]), (0, 1, 3))


class FillTest(Case):
    def test_a_queue_that_holds_the_low_water_mark_or_more_is_not_refilled_and_no_request_is_made(self):
        sources = self.sources()
        for i in range(5):
            crawlqueue.enqueue(self.conn, candidate(f"https://seed{i}.example.org/x"), limits={"queued_total": 100, "queued_per_domain": 100},
                               now=NOW, **KW)
        got = self.fill({"queue_low": 5}, sources=sources)
        self.assertEqual(got["added"], 0)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])
        self.assertEqual(self.log.of("discover", "skipped")[0]["reason"], "the queue holds enough")
        self.assertGreater(self.fill({"queue_low": 6}, sources=self.sources())["added"], 0)

    def test_a_queue_below_the_mark_is_filled_with_rows_that_have_the_topic_and_its_weight(self):
        got = self.fill({"queue_low": 100, "discover_target": 40, "wander_share": 0.0})
        self.assertGreater(got["added"], 0)
        self.assertLessEqual(got["added"], 40)
        for address, source, topic, weight, depth, found_from, status, reason in self.rows():
            self.assertEqual(status, "queued")
            self.assertIn((topic, weight), [(t, w) for t, w, _ in TOPICS])
            self.assertEqual(depth, 0)
        self.assertEqual(len({r[2] for r in self.rows()}) > 1, True)

    def test_it_adds_no_more_than_the_target_and_none_past_the_caps(self):
        self.assertLessEqual(self.fill({"discover_target": 7, "wander_share": 0.0})["added"], 7)
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            got = discover.fill(conn, {"queued_total": 4, "wander_share": 0.0}, TOPICS, now=NOW, get=lambda *a, **k: None,
                                sources=self.sources(), clock=self.clock, sleep=self.clock.sleep, **KW)
            self.assertEqual(got["added"], 4)  # the room that the cap leaves is the refill's budget
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 4)

    def test_a_domain_at_its_cap_leaves_the_row_and_the_refill_goes_on_with_the_other_sources_and_domains(self):
        many = Source("openalex", lambda q: [candidate(f"https://same.example.org/{i}") for i in range(10)])
        other = Source("arxiv", lambda q: [candidate(f"https://other.example.net/{q.replace(' ', '')}/{i}", "arxiv") for i in range(2)])
        wiki = Source("wikipedia")
        got = self.fill({"queued_per_domain": 3, "wander_share": 0.0, "discover_target": 40}, sources=self.sources(openalex=many, arxiv=other, wikipedia=wiki))
        self.assertFalse(got["capped"])
        self.assertEqual(len(self.rows("WHERE address LIKE 'https://same.example.org/%'")), 3)  # the domain's cap
        self.assertEqual(len(self.rows("WHERE address LIKE 'https://other.example.net/%'")), 3)  # another domain was asked, and has its own cap
        self.assertTrue(wiki.searches)
        self.assertGreater(got["skipped"], 0)
        self.assertEqual(got["skipped"], len(self.log.of("enqueue", "skipped")))  # every row left is counted, and said
        self.assertIn("domain cap", [f["reason"] for f in self.log.of("enqueue", "skipped")])
        self.assertNotIn("capped", [f["reason"] for f in self.log.of("enqueue", "skipped")])

    def test_the_topic_part_and_the_wander_part_are_the_target_split_by_wander_share(self):
        sources = self.sources()
        got = self.fill({"discover_target": 30, "wander_share": 0.2, "queries_per_topic": 1}, sources=sources)
        self.assertLessEqual(got["added"], 30 - 6)  # the wander part (6) is for the kept works, and there are none
        self.assertEqual(sources["openalex"].wanders, [])

    def test_each_pick_asks_each_source_that_is_on_once_in_the_order_openalex_arxiv_wikipedia(self):
        order = []

        class Ordered(Source):
            def search(self, query, get, limit, *more):
                order.append((self.name, query))
                return super().search(query, get, limit, *more)

        sources = {n: Ordered(n, rows_for(n, 1)) for n in ("openalex", "arxiv", "wikipedia")}
        self.fill({"discover_target": 3, "wander_share": 0.0, "queries_per_topic": 1}, sources=sources)
        names = [n for n, _ in order]
        self.assertEqual(names[:3], ["openalex", "arxiv", "wikipedia"])
        self.assertEqual(len({q for _, q in order[:3]}), 1)  # the three sources are asked the same query
        self.assertEqual(names, ["openalex", "arxiv", "wikipedia"] * (len(names) // 3))

    def test_a_source_that_the_plan_turns_off_is_never_asked_and_with_every_source_off_nothing_is_asked(self):
        sources = self.sources()
        self.fill({"arxiv": False}, sources=sources)
        self.assertEqual(sources["arxiv"].searches, [])
        self.assertTrue(sources["openalex"].searches and sources["wikipedia"].searches)
        sources = self.sources()
        got = self.fill({"openalex": False, "arxiv": False, "wikipedia": False, "web_search": False}, sources=sources)
        self.assertEqual(got["added"], 0)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])

    def test_the_queries_are_the_topics_own_without_a_model_and_the_models_with_one(self):
        sources = self.sources()
        self.fill({"discover_target": 6, "wander_share": 0.0, "queries_per_topic": 2}, sources=sources)
        asked = {q for q, _ in sources["openalex"].searches}
        self.assertTrue(asked <= {t for t, _, _ in TOPICS} | {f"{t} {v}" for t, _, _ in TOPICS for v in ("survey", "introduction")})
        calls = []

        def chat(prompt):
            calls.append(prompt)
            return "model query one\nmodel query two"

        sources = self.sources()
        self.fill({"discover_target": 6, "wander_share": 0.0, "queries_per_topic": 2}, sources=sources, chat=chat, cache={})
        self.assertTrue(calls)
        self.assertTrue({q for q, _ in sources["openalex"].searches} <= {"model query one", "model query two"})

    def test_a_cache_given_keeps_the_model_from_being_asked_again(self):
        calls, cache = [], {}

        def chat(prompt):
            calls.append(prompt)
            return "model query one\nmodel query two"

        self.fill({"discover_target": 6, "wander_share": 0.0}, chat=chat, cache=cache)
        first = len(calls)
        self.assertGreater(first, 0)
        self.fill({"discover_target": 6, "wander_share": 0.0}, chat=chat, cache=cache)
        self.assertEqual(len(calls), first)

    def test_the_topics_that_are_asked_are_those_of_the_days_quota_and_the_days_differ(self):
        spread = [(f"Topic {i}", 1, "s") for i in range(40)]
        asked = {}
        for day in ("2026-11-16", "2026-11-17", "2026-11-18"):
            sources = self.sources()
            self.fill({"discover_target": 20, "wander_share": 0.0, "queries_per_topic": 1, "queue_low": 10**5}, topics=spread, now=day + "T10:00:00Z",
                      sources=sources)
            asked[day] = {q for q, _ in sources["openalex"].searches}
        self.assertEqual(len({frozenset(v) for v in asked.values()}), 3)
        days = (discover.date_of("2026-11-17T10:00:00Z") - discover.date_of("2026-11-16T10:00:00Z")).days
        self.assertEqual(days, 1)

    def test_the_picks_are_taken_in_turn_so_that_a_refill_that_stops_early_has_reached_many_topics(self):
        sources = self.sources()
        self.fill({"discover_target": 12, "wander_share": 0.0, "queries_per_topic": 1}, sources=sources)
        self.assertGreater(len({q for q, _ in sources["openalex"].searches}), 1)

    def test_rows_that_are_blocked_are_recorded_as_blocked_and_never_queued(self):
        def is_blocked(address):
            return "owner" if "openalex.example.org" in address else None

        got = self.fill({"discover_target": 20, "wander_share": 0.0}, is_blocked=is_blocked)
        self.assertGreater(got["blocked"], 0)
        self.assertEqual({r[7] for r in self.rows("WHERE status = 'blocked'")}, {"owner"})
        self.assertFalse([r for r in self.rows("WHERE status = 'queued'") if "openalex.example.org" in r[0]])
        self.assertEqual(len(self.log.of("block", "blocked")), got["blocked"])

    def test_a_reason_that_is_not_one_the_queue_takes_is_a_fault_and_is_not_swallowed(self):
        for reason in ("any old reason", "", "list:", 5):
            with self.subTest(reason=reason):
                with self.assertRaises(KbError):
                    self.fill({"discover_target": 20, "wander_share": 0.0}, is_blocked=lambda a, r=reason: r)

    def test_a_work_whose_only_text_is_a_pdf_is_recorded_as_rejected_for_its_type(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [], "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        got = self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.sources(openalex=source, arxiv=Source("arxiv"),
                                                                                         wikipedia=Source("wikipedia")))
        self.assertEqual(got["rejected"], 1)
        self.assertEqual(self.rows("WHERE status = 'rejected'")[0][7], "type")

    def pdf_source(self, *addresses):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [], "rejected": [candidate(a) for a in addresses]}
        return self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia"))

    def test_with_pdfs_on_a_work_whose_only_text_is_a_pdf_is_queued_as_a_candidate_and_not_rejected(self):
        got = self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.pdf_source("https://repo.example.edu/a.pdf", "https://repo.example.edu/b"), pdfs=True)
        self.assertEqual((got["added"], got["rejected"]), (2, 0))
        self.assertEqual([(r[0], r[6], r[7]) for r in self.rows()], [("https://repo.example.edu/a.pdf", "queued", None), ("https://repo.example.edu/b", "queued", None)])
        self.assertEqual((len(self.log.of("enqueue", "ok")), self.log.of("enqueue", "rejected")), (2, []))

    def test_with_pdfs_off_the_same_works_are_rejected_for_their_type_as_before(self):
        for kw in ({}, {"pdfs": False}):
            with self.subTest(kw):
                self.setUp()
                got = self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.pdf_source("https://repo.example.edu/a.pdf"), **kw)
                self.assertEqual((got["added"], got["rejected"]), (0, 1))
                self.assertEqual([(r[6], r[7]) for r in self.rows()], [("rejected", "type")])

    def test_a_pdf_work_that_the_owner_or_a_list_blocks_is_blocked_and_one_at_a_site_over_its_cap_is_left_out(self):
        got = self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.pdf_source("https://repo.example.edu/a.pdf"), pdfs=True, is_blocked=lambda address: "owner")
        self.assertEqual((got["added"], got["blocked"], got["rejected"]), (0, 1, 0))
        self.setUp()
        got = self.fill({"discover_target": 5, "wander_share": 0.0, "queued_per_domain": 1}, sources=self.pdf_source("https://repo.example.edu/a.pdf", "https://repo.example.edu/b.pdf"), pdfs=True)
        self.assertEqual((got["added"], got["skipped"], got["rejected"]), (1, 1, 0))

    def test_a_row_found_again_is_skipped_and_changes_nothing(self):
        self.fill({"discover_target": 10, "wander_share": 0.0})
        before = self.rows()
        got = self.fill({"discover_target": 10, "wander_share": 0.0, "queue_low": 10**5})
        self.assertEqual(got["added"], 0)
        self.assertEqual(self.rows(), before)
        self.assertTrue(self.log.of("enqueue", "skipped"))

    def test_a_second_refill_in_the_same_day_adds_nothing_the_first_would_not(self):
        plan = {"discover_target": 200, "wander_share": 0.0, "queue_low": 10**5}  # a target that the sources do not reach, so that nothing is cut off
        self.fill(plan)
        first = self.rows()
        self.assertGreater(len(first), 10)
        self.assertLess(len(first), 200)
        self.assertEqual(self.fill(plan)["added"], 0)
        self.assertEqual(self.rows(), first)

    def test_a_refill_that_stopped_at_its_target_leaves_the_rest_for_the_next_one(self):
        plan = {"discover_target": 15, "wander_share": 0.0, "queue_low": 10**5}
        self.assertEqual(self.fill(plan)["added"], 15)
        again = self.fill(plan)["added"]
        self.assertGreater(again, 0)  # the rows that the first target cut off
        self.assertLessEqual(again, 15)

    def test_every_row_it_adds_is_one_the_queue_would_take(self):
        self.fill({"discover_target": 30, "wander_share": 0.0})
        for address, source, topic, weight, depth, found_from, status, reason in self.rows():
            self.assertRegex(address, r"^https://[a-z]+\.example\.org/")
            self.assertIn(source, ("openalex", "arxiv", "wikipedia"))
            self.assertTrue(found_from)


class FillMoreTest(Case):
    def test_each_request_asks_for_ten_works_and_the_requests_are_counted(self):
        sources = self.sources()
        got = self.fill({"discover_target": 30, "wander_share": 0.0}, sources=sources)
        for name, source in sources.items():
            self.assertEqual({limit for _, limit in source.searches}, {10})
            self.assertEqual(got["requests"][name], len(source.searches))

    def test_a_refill_makes_at_most_fifty_picks_whatever_the_target(self):
        sources = self.sources()
        self.fill({"discover_target": 2000, "wander_share": 0.0, "queue_low": 10**6, "queued_per_domain": 10**5}, sources=sources)
        self.assertEqual(len(sources["openalex"].searches), 50)

    def test_the_budget_is_the_room_the_queue_has_and_no_more(self):
        for i in range(5):
            crawlqueue.enqueue(self.conn, candidate(f"https://seed{i}.example.org/x"), limits={"queued_total": 100, "queued_per_domain": 100}, now=NOW, **KW)
        got = self.fill({"discover_target": 100, "wander_share": 0.0, "queued_total": 8, "queue_low": 100})
        self.assertEqual(got["added"], 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 8)

    def test_arxiv_is_given_the_get_itself_and_the_others_a_paced_one(self):
        seen = {}

        class Keeping(Source):
            def search(inner, query, get, limit, *more):
                seen.setdefault(inner.name, get)
                return super().search(query, get, limit, *more)

        def get(url, headers=None, timeout=None):
            return 200, {}, b"{}"

        sources = {n: Keeping(n, rows_for(n)) for n in ("openalex", "arxiv", "wikipedia")}
        self.fill({"discover_target": 10, "wander_share": 0.0}, sources=sources, get=get)
        self.assertIs(seen["arxiv"], get)
        self.assertIsNot(seen["openalex"], get)
        self.assertIsNot(seen["wikipedia"], get)

    def test_a_topic_that_is_picked_more_than_once_goes_through_its_queries_in_turn(self):
        sources = self.sources()
        self.fill({"discover_target": 30, "wander_share": 0.0, "queries_per_topic": 3}, topics=[("Control theory", 1, "core")], sources=sources)
        self.assertEqual([q for q, _ in sources["openalex"].searches], ["Control theory", "Control theory survey", "Control theory introduction"])

    def test_a_row_that_is_blocked_twice_or_rejected_twice_is_a_skip_the_second_time(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [candidate("https://bad.example.org/a")],
                                                   "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        sources = self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia"))
        plan = {"discover_target": 10, "wander_share": 0.0, "queue_low": 10**5}
        self.fill(plan, sources=sources, is_blocked=lambda a: "owner" if "bad.example.org" in a else None)
        got = self.fill(plan, sources=sources, is_blocked=lambda a: "owner" if "bad.example.org" in a else None)
        self.assertEqual((got["blocked"], got["rejected"], got["added"], got["skipped"]), (0, 0, 0, 2))
        self.assertTrue(self.log.of("block", "skipped"))
        self.assertTrue(self.log.of("enqueue", "skipped"))
        self.assertEqual([r[6] for r in self.rows()], ["blocked", "rejected"])

    def test_a_refill_that_hit_a_cap_walks_nowhere(self):
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                          "VALUES ('k', 'https://k.example.org/1', 'openalex', 'openalex:W1', 0, 'kept', 'n', 'n')")
        many = self.crowded(40)
        many.wander = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a walk after a cap"))
        got = self.fill({"discover_target": 100, "wander_share": 0.5, "queued_total": 40, "queue_low": 10**5},
                        sources=self.sources(openalex=many, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertTrue(got["capped"])

    def test_the_works_walked_are_counted_and_a_walk_that_found_nothing_is_still_a_walk(self):
        for n in (1, 2):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                              "VALUES (?, ?, 'openalex', ?, 0, 'kept', 'n', 'n')", (f"k{n}", f"https://k.example.org/{n}", f"openalex:W{n}"))
        got = self.fill({"discover_target": 50, "wander_share": 0.5, "queue_low": 10**5}, sources=self.sources())
        self.assertEqual(got["walked"], 2)

    def test_what_the_caller_gives_is_checked_before_anything_is_asked(self):
        sources = self.sources()
        for kw in ({"arxiv_pacer": object()}, {"sources": {"bing": Source("bing")}}, {"sources": {"arxiv": object()}},
                   {"sources": {"openalex": SimpleNamespace(search=lambda *a: None)}}, {"sources": {"wikipedia": SimpleNamespace(search=5)}}):
            with self.subTest(kw=kw):
                with self.assertRaises(KbError):
                    self.fill({}, sources=kw.pop("sources", sources), **kw)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])

class FillFurtherTest(Case):
    def test_a_row_is_stamped_with_the_time_of_the_refill_whatever_its_status(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [candidate("https://a.example.org/1"), candidate("https://bad.example.org/1")],
                                                   "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        self.fill({"discover_target": 10, "wander_share": 0.0}, sources=self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")),
                  is_blocked=lambda a: "owner" if "bad.example.org" in a else None)
        stamps = self.conn.execute("SELECT status, added, updated FROM candidates ORDER BY id").fetchall()
        self.assertEqual({s for s, _, _ in stamps}, {"queued", "blocked", "rejected"})
        self.assertEqual({(a, u) for _, a, u in stamps}, {(NOW, NOW)})

    def test_a_blocked_row_is_never_also_offered_to_the_queue(self):
        got = self.fill({"discover_target": 20, "wander_share": 0.0}, is_blocked=lambda a: "owner" if "openalex.example.org" in a else None)
        self.assertEqual(got["skipped"], 0)
        self.assertFalse([f["candidate"] for f in self.log.of("enqueue") if "openalex.example.org" in f["candidate"]])

    def test_a_rejected_row_is_said_with_its_reason(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [], "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertEqual([(f["candidate"], f["reason"]) for f in self.log.of("enqueue", "rejected")], [("https://repo.example.edu/a.pdf", "type")])

    def test_a_request_is_said_with_the_number_of_works_it_gave_the_candidates_and_the_rejected_together(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [candidate("https://a.example.org/1"), candidate("https://a.example.org/2")],
                                                   "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertEqual({f["n"] for f in self.log.of("discover", "ok") if f["source"] == "openalex"}, {3})

    def test_a_row_found_again_is_counted_as_skipped(self):
        self.fill({"discover_target": 10, "wander_share": 0.0})
        before = len(self.log.of("enqueue", "skipped"))
        got = self.fill({"discover_target": 10, "wander_share": 0.0, "queue_low": 10**5})
        self.assertGreater(got["skipped"], 0)
        self.assertEqual(got["skipped"], len(self.log.of("enqueue", "skipped")) - before)

    def test_a_full_queue_is_said_and_counted_once_and_nothing_is_offered_after_it(self):
        got = self.fill({"queued_total": 40, "wander_share": 0.0}, sources=self.sources(openalex=self.crowded(40), arxiv=Source("arxiv"),
                                                                                       wikipedia=Source("wikipedia")))
        self.assertEqual([f["reason"] for f in self.log.of("enqueue", "skipped")], ["capped"])
        self.assertEqual((got["skipped"], got["capped"]), (1, True))

    def test_a_row_rejected_for_its_type_is_recorded_once_the_target_is_reached_and_a_queued_row_is_not(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: {"candidates": [candidate(f"https://c{i}.example{i}.org/a") for i in range(20)],
                                                   "rejected": [candidate("https://repo.example.edu/a.pdf")]}
        got = self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.sources(openalex=source, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertEqual((got["added"], got["rejected"]), (5, 1))

    def test_once_the_target_or_a_cap_is_reached_the_sources_after_it_are_not_asked(self):
        def big(q):
            return [candidate(f"https://same.example.org/{q.replace(' ', '')}/{i}") for i in range(20)]

        arxiv, wiki = Source("arxiv"), Source("wikipedia")
        self.fill({"discover_target": 10, "wander_share": 0.0}, sources=self.sources(openalex=Source("openalex", big), arxiv=arxiv, wikipedia=wiki))
        self.assertEqual((arxiv.searches, wiki.searches), ([], []))  # the target was met by the first source
        arxiv, wiki = Source("arxiv"), Source("wikipedia")
        self.fill({"discover_target": 100, "wander_share": 0.0, "queued_total": 40, "queue_low": 10**5, "queued_per_domain": 10**5},
                  sources=self.sources(openalex=self.crowded(40), arxiv=arxiv, wikipedia=wiki))
        self.assertEqual((arxiv.searches, wiki.searches), ([], []))  # and a full queue, by the first

    def test_a_model_is_not_asked_for_queries_that_no_source_would_get(self):
        calls = []
        self.fill({"openalex": False, "arxiv": False, "wikipedia": False}, chat=lambda p: calls.append(p) or "model query")
        self.assertEqual(calls, [])

    def test_a_model_is_not_asked_for_picks_after_the_target_was_met(self):
        calls = []

        def chat(prompt):
            calls.append(prompt)
            return "model query one\nmodel query two"

        spread = [(f"Topic {i}", 1, "s") for i in range(30)]
        big = Source("openalex", lambda q: [candidate(f"https://openalex.example.org/{i}") for i in range(20)])
        self.fill({"discover_target": 15, "wander_share": 0.0, "queries_per_topic": 2}, topics=spread, chat=chat, cache={},
                  sources=self.sources(openalex=big, arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertEqual(len(calls), 1)

    def test_a_model_is_not_asked_for_picks_after_a_cap_was_hit(self):
        calls = []

        def chat(prompt):
            calls.append(prompt)
            return "model query one\nmodel query two"

        spread = [(f"Topic {i}", 1, "s") for i in range(30)]
        got = self.fill({"discover_target": 200, "wander_share": 0.0, "queued_total": 40, "queued_per_domain": 10**5, "queries_per_topic": 2}, topics=spread,
                        chat=chat, cache={}, sources=self.sources(openalex=self.crowded(40), arxiv=Source("arxiv"), wikipedia=Source("wikipedia")))
        self.assertTrue(got["capped"])
        self.assertEqual(len(calls), 1)

    def test_a_low_water_mark_of_nothing_means_the_queue_is_never_refilled(self):
        sources = self.sources()
        got = self.fill({"queue_low": 0}, sources=sources)
        self.assertEqual(got["added"], 0)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])

    def test_the_number_of_queries_a_topic_has_is_the_plans(self):
        sources = self.sources()
        self.fill({"discover_target": 100, "wander_share": 0.0, "queries_per_topic": 1, "queue_low": 10**5}, sources=sources)
        self.assertTrue({q for q, _ in sources["openalex"].searches} <= {t for t, _, _ in TOPICS})


class Asking(Source):
    """A source that calls the `get` it is given, once for each search, and keeps what it got."""

    def __init__(self, name, rows=None):
        super().__init__(name, rows)
        self.got = []

    def search(self, query, get, limit, *more):
        self.got.append(get("https://api.example.org/" + self.name))
        return super().search(query, get, limit, *more)


class GetsTest(Case):
    def test_a_source_with_a_get_of_its_own_is_asked_through_it_and_the_others_through_the_shared_one(self):
        sources = {"openalex": Asking("openalex", rows_for("openalex")), "arxiv": Asking("arxiv", rows_for("arxiv")), "wikipedia": Asking("wikipedia", rows_for("wikipedia"))}
        shared = lambda url, headers=None, timeout=None: ("shared", url)  # noqa: E731
        own = lambda url, headers=None, timeout=None: ("own", url)  # noqa: E731
        self.fill({"discover_target": 20, "wander_share": 0.0, "queue_low": 10**5}, sources=sources, get=shared, gets={"openalex": own})
        self.assertTrue(sources["openalex"].got and {g[0] for g in sources["openalex"].got} == {"own"})
        for name in ("arxiv", "wikipedia"):
            self.assertTrue(sources[name].got and {g[0] for g in sources[name].got} == {"shared"}, name)

    def test_no_gets_is_the_shared_get_for_everyone(self):
        sources = {"openalex": Asking("openalex", rows_for("openalex")), "arxiv": Asking("arxiv"), "wikipedia": Asking("wikipedia")}
        shared = lambda url, headers=None, timeout=None: ("shared", url)  # noqa: E731
        self.fill({"discover_target": 20, "wander_share": 0.0, "queue_low": 10**5}, sources=sources, get=shared)
        self.assertEqual({g[0] for name in sources for g in sources[name].got}, {"shared"})

    def test_a_get_of_none_for_a_source_means_the_shared_one_and_a_get_for_a_source_that_is_not_asked_is_not_used(self):
        sources = {"openalex": Asking("openalex", rows_for("openalex")), "arxiv": Asking("arxiv", rows_for("arxiv"))}
        shared = lambda url, headers=None, timeout=None: ("shared", url)  # noqa: E731
        own = lambda url, headers=None, timeout=None: ("own", url)  # noqa: E731
        self.fill({"discover_target": 20, "wander_share": 0.0, "queue_low": 10**5, "wikipedia": False}, sources=sources, get=shared,
                  gets={"openalex": None, "arxiv": None, "wikipedia": own})
        self.assertEqual({g[0] for name in sources for g in sources[name].got}, {"shared"})


class WebSearchEngineTest(Case):
    """`web_search_engine` chooses the adapter: DuckDuckGo's page through the shared `get`, or LangSearch through the `post` that the caller gives for `web_search`."""
    DDG = (b'<html><body><div id="links" class="results"><div class="result web-result"><h2 class="result__title">'
           b'<a rel="nofollow" class="result__a" href="https://ddg.example/a">t</a></h2></div></div></body></html>')
    PLAN = {"openalex": False, "arxiv": False, "wikipedia": False, "web_search": True, "wander_share": 0.0, "queue_low": 10**5, "discover_target": 100}

    @staticmethod
    def answer(*urls):
        return (200, {"content-type": "application/json"}, json.dumps({"code": 200, "data": {"webPages": {"value": [{"url": u} for u in urls]}}}).encode())

    def test_langsearch_is_asked_through_the_post_for_web_search_and_the_shared_get_is_never_used(self):
        calls = []

        def post(body):
            calls.append(body)
            return self.answer("https://ls.example/p")

        def shared(*args, **kw):
            raise AssertionError("the shared get")

        got = self.fill(dict(self.PLAN, web_search_engine="langsearch"), sources={}, get=shared, gets={"web_search": post})
        self.assertTrue(calls)
        for body in calls:
            self.assertEqual(set(body), {"query", "count"})
        rows = self.rows("WHERE source = 'web-search'")
        self.assertEqual({r[0] for r in rows}, {"https://ls.example/p"})
        self.assertEqual({r[6] for r in rows}, {"queued"})
        self.assertEqual(got["requests"]["web_search"], len(calls))

    def test_duckduckgo_is_asked_through_the_shared_get_by_default_and_when_the_plan_says_so(self):
        for plan in (dict(self.PLAN), dict(self.PLAN, web_search_engine="duckduckgo")):
            with self.subTest(plan=sorted(plan)):
                self.setUp()
                urls = []

                def shared(url, headers=None, timeout=None):
                    urls.append(url)
                    return 200, {"content-type": "text/html"}, self.DDG

                self.fill(plan, sources={}, get=shared)
                self.assertTrue(urls and all(u.startswith("https://html.duckduckgo.com/") for u in urls))
                self.assertEqual({r[0] for r in self.rows("WHERE source = 'web-search'")}, {"https://ddg.example/a"})

    def test_the_daily_number_of_queries_is_the_same_for_either_engine(self):
        calls = []

        def post(body):
            calls.append(body)
            return self.answer()

        self.fill(dict(self.PLAN, web_search_engine="langsearch", web_search_per_day=2), sources={}, gets={"web_search": post})
        self.assertEqual(len(calls), 2)
        self.fill(dict(self.PLAN, web_search_engine="langsearch", web_search_per_day=2), sources={}, gets={"web_search": post})
        self.assertEqual(len(calls), 2)   # the day's two are spent: nothing more is asked
        self.assertEqual(self.counters()[("2026-11-16", "web_search_queries")], 2)

    def test_a_refusal_of_langsearch_is_the_search_off_for_the_day_with_its_reason(self):
        def post(body):
            raise srcopenalex.SourceRefused("the LangSearch key file is refused: the key file must have mode 600")

        got = self.fill(dict(self.PLAN, web_search_engine="langsearch"), sources={}, gets={"web_search": post})
        self.assertEqual(list(got["refused"]), ["web_search"])
        self.assertIn("the LangSearch key file is refused", got["refused"]["web_search"])
        self.assertIn(("2026-11-16", "source_off:web_search"), self.counters())

    def test_the_plan_reader_of_a_refill_refuses_duckduckgo_for_the_search_with_the_engine_langsearch_too(self):
        for text in ("[sources]\nweb_search = duckduckgo\nweb_search_engine = langsearch\n", "[sources]\nweb_search_engine = langsearch\nweb_search = duckduckgo\n"):
            with self.subTest(text):
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "plan.txt"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(KbError) as caught:
                        discover.read_plan(str(path))
                    self.assertIn("line 3", str(caught.exception))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plan.txt"
            path.write_text("[sources]\nweb_search = on\nweb_search_engine = langsearch\n", encoding="utf-8")
            self.assertEqual(discover.read_plan(str(path)), {"web_search": True, "web_search_engine": "langsearch"})

    def test_the_engine_is_one_of_the_two_words_in_the_plan_of_a_refill(self):
        self.assertEqual(discover.normalize_plan({"web_search_engine": "langsearch"})["web_search_engine"], "langsearch")
        for bad in ("bing", "LangSearch", "", None, True, 5, ["langsearch"]):
            with self.subTest(repr(bad)):
                with self.assertRaises(KbError):
                    discover.normalize_plan({"web_search_engine": bad})

    def test_a_post_with_one_argument_is_paced_like_a_get_with_three(self):
        calls = []

        def post(body):
            calls.append(len(self.clock.slept))
            return self.answer()

        self.fill(dict(self.PLAN, web_search_engine="langsearch", web_search_per_day=3, gap_web_search_s=30), sources={}, gets={"web_search": post})
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.clock.slept, [30, 30])   # before the second and the third, not before the first


class RefusalTest(Case):
    def test_a_source_that_refuses_is_off_for_the_rest_of_the_day_and_the_others_go_on(self):
        sources = self.sources(arxiv=Source("arxiv", refuse="status 429"))
        got = self.fill({"discover_target": 20, "wander_share": 0.0, "queue_low": 10**5}, sources=sources)
        self.assertEqual(len(sources["arxiv"].searches), 1)  # asked once, refused, not asked again
        self.assertGreater(len(sources["openalex"].searches), 1)
        self.assertGreater(len(sources["wikipedia"].searches), 1)
        self.assertEqual(got["refused"], {"arxiv": "status 429"})
        self.assertEqual(got["off"], ["arxiv"])
        self.assertEqual(self.counters()[("2026-11-16", "source_off:arxiv")], 1)
        self.assertEqual(self.log.of("discover", "refused")[0]["source"], "arxiv")
        self.assertEqual(self.log.of("discover", "refused")[0]["reason"], "status 429")

    def test_a_refusal_for_this_refill_only_stops_the_source_for_the_refill_and_writes_no_count_of_the_day(self):
        sources = self.sources(arxiv=Source("arxiv", refuse="status 429 (remaining 5, retry-after 2)", for_day=False))
        got = self.fill({"discover_target": 20, "wander_share": 0.0, "queue_low": 10**5}, sources=sources)
        self.assertEqual(len(sources["arxiv"].searches), 1)  # asked once, refused, not asked again in this refill
        self.assertGreater(len(sources["openalex"].searches), 1)
        self.assertGreater(len(sources["wikipedia"].searches), 1)
        self.assertEqual(got["refused"], {"arxiv": "status 429 (remaining 5, retry-after 2)"})
        self.assertEqual(got["off"], ["arxiv"])
        self.assertNotIn(("2026-11-16", "source_off:arxiv"), self.counters())
        line, = self.log.of("discover", "refused")
        self.assertEqual((line["source"], line["reason"]), ("arxiv", "status 429 (remaining 5, retry-after 2)"))

    def test_a_source_refused_for_one_refill_is_asked_again_by_the_next_refill_of_the_same_day(self):
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=self.sources(arxiv=Source("arxiv", refuse="status 429", for_day=False)))
        later = self.sources()
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=later)
        self.assertGreater(len(later["arxiv"].searches), 0)
        self.assertNotIn("arxiv", [f["source"] for f in self.log.of("discover", "skipped") if f.get("source")])

    def test_a_refusal_on_each_of_two_days_is_counted_for_each_day_alone(self):
        for now in (NOW, LATER):
            self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=self.sources(arxiv=Source("arxiv", refuse="status 429")),
                      now=now)
        counters = self.counters()
        self.assertEqual((counters[("2026-11-16", "source_off:arxiv")], counters[("2026-11-17", "source_off:arxiv")]), (1, 1))

    def test_a_source_that_the_plan_turns_off_says_nothing_even_when_it_is_off_for_the_day(self):
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=self.sources(arxiv=Source("arxiv", refuse="status 429")))
        self.log.lines.clear()
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5, "arxiv": False})
        self.assertNotIn("arxiv", [f.get("source") for f in self.log.of("discover", "skipped")])

    def test_a_source_that_the_plan_leaves_off_says_nothing_and_the_web_search_engine_is_left_off_by_default(self):
        self.fill({"discover_target": 5, "wander_share": 0.0}, sources=self.sources())
        self.assertEqual(self.log.of("discover", "skipped"), [])
        self.assertNotIn("web_search", [f.get("source") for _, _, f in self.log.lines])

    def test_it_stays_off_in_a_later_refill_of_the_same_day_and_is_asked_again_the_next_day(self):
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=self.sources(arxiv=Source("arxiv", refuse="status 429")))
        later = self.sources()
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=later)
        self.assertEqual(later["arxiv"].searches, [])
        self.assertIn("arxiv", [f["source"] for f in self.log.of("discover", "skipped")])
        nextday = self.sources()
        self.fill({"discover_target": 5, "wander_share": 0.0, "queue_low": 10**5}, sources=nextday, now=LATER)
        self.assertTrue(nextday["arxiv"].searches)

    def test_every_source_refusing_ends_the_refill_with_what_there_is(self):
        refusing = {n: Source(n, refuse="status 403") for n in ("openalex", "arxiv", "wikipedia")}
        got = self.fill({"wander_share": 0.0}, sources=refusing)
        self.assertEqual((got["added"], sorted(got["refused"])), (0, ["arxiv", "openalex", "wikipedia"]))
        self.assertEqual([len(s.searches) for s in refusing.values()], [1, 1, 1])

    def test_the_refusal_is_the_one_every_source_raises_and_a_fault_of_the_caller_is_not_one(self):
        source = Source("openalex")
        source.search = lambda q, get, limit, *m: (_ for _ in ()).throw(KbError("a fault of the caller"))
        with self.assertRaises(KbError):
            self.fill({"wander_share": 0.0}, sources=self.sources(openalex=source))
        self.assertEqual(self.counters(), {})

    def test_a_refusal_of_each_of_the_real_source_modules_is_caught_and_named(self):
        for name, module in (("arxiv", srcarxiv), ("openalex", srcopenalex), ("wikipedia", __import__("kb.srcwikipedia", fromlist=["x"]))):
            with self.subTest(source=name):
                self.setUp()
                get = lambda url, headers=None, timeout=None: (429, {}, b"")  # noqa: E731
                sources = {"openalex": srcopenalex, "arxiv": srcarxiv, "wikipedia": __import__("kb.srcwikipedia", fromlist=["x"])}
                got = discover.fill(self.conn, {"wander_share": 0.0, "openalex": name == "openalex", "arxiv": name == "arxiv",
                                                "wikipedia": name == "wikipedia"}, TOPICS, now=NOW, get=get, sources=sources, clock=self.clock,
                                    sleep=self.clock.sleep, **KW)
                self.assertEqual(list(got["refused"]), [name])
                self.assertTrue(got["refused"][name].startswith("status 429"))

    def test_a_429_with_budget_left_ends_only_the_refill_of_openalex_through_the_real_modules_and_of_no_other_source(self):
        for name in ("openalex", "arxiv", "wikipedia"):
            with self.subTest(source=name):
                self.setUp()
                get = lambda url, headers=None, timeout=None: (429, {"x-ratelimit-remaining": "5", "retry-after": "2"}, b"")  # noqa: E731
                sources = {"openalex": srcopenalex, "arxiv": srcarxiv, "wikipedia": __import__("kb.srcwikipedia", fromlist=["x"])}
                got = discover.fill(self.conn, {"wander_share": 0.0, "openalex": name == "openalex", "arxiv": name == "arxiv",
                                                "wikipedia": name == "wikipedia"}, TOPICS, now=NOW, get=get, sources=sources, clock=self.clock,
                                    sleep=self.clock.sleep, **KW)
                self.assertEqual(list(got["refused"]), [name])
                counted = ("2026-11-16", f"source_off:{name}") in self.counters()
                self.assertEqual(counted, name != "openalex")  # OpenAlex's is written for no day; the others stay for the day whatever the header says
                if name == "openalex":
                    self.assertEqual(got["refused"][name], "status 429 (remaining 5, retry-after 2)")


class WanderTest(Case):
    def keep(self, number, depth=0, source="openalex"):
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                          "VALUES (?, ?, ?, ?, ?, 'kept', 'n', 'n')", (f"https://k.example.org/{number}", f"https://k.example.org/{number}", source,
                                                                        f"openalex:W{number}", depth))

    def wanderer(self, found=None):
        source = Source("openalex")
        source.wander = lambda kept, get, per_work, max_depth, seen=(): (source.wanders.append((list(kept), per_work, max_depth, set(seen))),
                                                                          found or {"candidates": [], "rejected": []})[1]
        return source

    def test_kept_works_are_walked_from_one_level_at_a_time_with_the_plans_numbers(self):
        for n in (1, 2, 3):
            self.keep(n)
        source = self.wanderer()
        self.fill({"discover_target": 100, "wander_share": 0.5, "wander_per_work": 5, "wander_depth": 2, "queue_low": 10**5},
                  sources=self.sources(openalex=source))
        (kept, per_work, depth, seen), = source.wanders
        self.assertEqual((kept, per_work, depth), ([("openalex:W1", 0), ("openalex:W2", 0), ("openalex:W3", 0)], 5, 2))
        self.assertEqual(seen, {"openalex:W1", "openalex:W2", "openalex:W3"})

    def test_no_more_kept_works_are_walked_than_the_wander_part_can_hold(self):
        for n in range(1, 31):
            self.keep(n)
        source = self.wanderer()
        self.fill({"discover_target": 20, "wander_share": 0.5, "wander_per_work": 5, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(len(source.wanders[0][0]), 2)  # a wander part of 10 rows, 5 from each kept work

    def test_a_kept_work_is_walked_once_and_the_next_refill_goes_on_with_the_next(self):
        for n in range(1, 7):
            self.keep(n)
        source = self.wanderer()
        plan = {"discover_target": 20, "wander_share": 0.5, "wander_per_work": 5, "queue_low": 10**5}
        self.fill(plan, sources=self.sources(openalex=source))
        self.fill(plan, sources=self.sources(openalex=source))
        self.fill(plan, sources=self.sources(openalex=source))
        walked = [[k[0] for k in w[0]] for w in source.wanders]
        self.assertEqual(walked, [["openalex:W1", "openalex:W2"], ["openalex:W3", "openalex:W4"], ["openalex:W5", "openalex:W6"]])
        self.fill(plan, sources=self.sources(openalex=source))
        self.assertEqual(len(source.wanders), 3)  # nothing is left to walk from, and no request is made
        self.assertEqual(self.counters()[("permanent", "walked:W1")], 1)

    def test_what_is_found_is_queued_one_level_deeper_with_no_topic_and_the_source_of_the_work(self):
        self.keep(1)
        found = {"candidates": [candidate("https://w.example.org/a", found_from="openalex:W1", depth=1, source_id="openalex:W2000001")],
                 "rejected": [candidate("https://w.example.org/b.pdf", found_from="openalex:W1", depth=1)]}
        self.fill({"discover_target": 50, "wander_share": 1.0, "queue_low": 10**5}, sources=self.sources(openalex=self.wanderer(found)))
        row = self.rows("WHERE address = 'https://w.example.org/a'")[0]
        self.assertEqual((row[2], row[3], row[4], row[5], row[6]), (None, None, 1, "openalex:W1", "queued"))
        self.assertEqual(self.rows("WHERE address = 'https://w.example.org/b.pdf'")[0][6:], ("rejected", "type"))

    def test_a_work_of_another_source_or_at_the_depth_limit_is_not_walked_from(self):
        self.keep(1, depth=2)
        self.keep(2, source="arxiv")
        source = self.wanderer()
        self.fill({"discover_target": 50, "wander_share": 0.5, "wander_depth": 2, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(source.wanders, [])

    def test_with_the_source_off_or_refused_nothing_is_walked(self):
        self.keep(1)
        source = self.wanderer()
        self.fill({"discover_target": 50, "wander_share": 0.5, "openalex": False, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(source.wanders, [])

    def test_a_refusal_during_a_walk_keeps_what_was_found_and_does_not_mark_the_work_as_walked(self):
        self.keep(1)
        partial = {"candidates": [candidate("https://w.example.org/p", found_from="openalex:W1", depth=1)], "rejected": []}
        source = Source("openalex")

        def wander(kept, get, per_work, max_depth, seen=()):
            error = srcopenalex.SourceRefused("status 429")
            error.partial = partial
            raise error

        source.wander = wander
        got = self.fill({"discover_target": 50, "wander_share": 1.0, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(got["added"], 1)
        self.assertEqual(got["refused"], {"openalex": "status 429"})
        self.assertNotIn(("permanent", "walked:W1"), self.counters())
        self.assertIn(("2026-11-16", "source_off:openalex"), self.counters())

    def test_a_refusal_for_this_refill_during_a_walk_keeps_the_rows_leaves_the_work_to_walk_again_and_writes_no_count_of_the_day(self):
        self.keep(1)
        partial = {"candidates": [candidate("https://w.example.org/q", found_from="openalex:W1", depth=1)], "rejected": []}
        source = Source("openalex")

        def wander(kept, get, per_work, max_depth, seen=()):
            error = srcopenalex.SourceRefused("status 429 (remaining 4, retry-after none)", for_day=False)
            error.partial = partial
            raise error

        source.wander = wander
        got = self.fill({"discover_target": 50, "wander_share": 1.0, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(got["added"], 1)
        self.assertEqual(got["refused"], {"openalex": "status 429 (remaining 4, retry-after none)"})
        self.assertNotIn(("permanent", "walked:W1"), self.counters())
        self.assertNotIn(("2026-11-16", "source_off:openalex"), self.counters())

    def test_the_walk_is_counted_as_a_request_and_said_in_the_log(self):
        self.keep(1)
        got = self.fill({"discover_target": 20, "wander_share": 1.0, "queue_low": 10**5}, sources=self.sources(openalex=self.wanderer()))
        self.assertEqual(got["requests"], {"openalex": 1})
        self.assertEqual([f["source"] for f in self.log.of("discover", "ok")], ["openalex"])

    def test_the_walk_is_given_the_plans_works_per_kept_work_and_depth_and_every_kept_work_as_seen(self):
        for n in range(1, 31):
            self.keep(n)
        source = self.wanderer()
        self.fill({"discover_target": 40, "wander_share": 0.5, "wander_per_work": 4, "wander_depth": 1, "queue_low": 10**5},
                  sources=self.sources(openalex=source))
        (kept, per_work, depth, seen), = source.wanders
        self.assertEqual((per_work, depth, len(kept), len(seen)), (4, 1, 5, 30))  # a wander part of 20 rows: five works of four

    def test_after_openalex_refused_in_the_topic_phase_nothing_is_walked(self):
        self.keep(1)
        source = self.wanderer()
        source.refuse = "status 429"
        got = self.fill({"discover_target": 40, "wander_share": 0.5, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual(got["off"], ["openalex"])
        self.assertEqual(source.wanders, [])

    def test_the_number_of_kept_works_walked_is_the_wander_part_over_the_works_per_work_rounded_down(self):
        for n in range(1, 31):
            self.keep(n)
        source = self.wanderer()
        self.fill({"discover_target": 20, "wander_share": 0.6, "wander_per_work": 5, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual([len(w[0]) for w in source.wanders], [2])  # a wander part of 12 rows: two works of five, and two rows are left

    def test_a_wander_part_smaller_than_one_works_share_still_walks_one_work(self):
        for n in (1, 2, 3):
            self.keep(n)
        source = self.wanderer()
        self.fill({"discover_target": 10, "wander_share": 0.3, "wander_per_work": 5, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual([len(w[0]) for w in source.wanders], [1])

    def test_a_walk_adds_no_more_than_its_share_and_a_work_with_rows_left_over_is_walked_again_until_none_is(self):
        self.keep(1)
        rows = [candidate(f"https://w{i}.example{i}.org/a", found_from="openalex:W1", depth=1) for i in range(5)]
        source = self.wanderer({"candidates": rows, "rejected": []})
        plan = {"discover_target": 5, "wander_share": 0.4, "wander_per_work": 5, "queue_low": 10**5}  # a share of two rows, and no topics
        added = []
        for _ in range(3):
            added.append(self.fill(plan, topics=[], sources=self.sources(openalex=source)))
        self.assertEqual([g["added"] for g in added], [2, 2, 1])  # five rows, two at a time; the rows taken before are found again and skipped
        self.assertEqual([g["walked"] for g in added], [0, 0, 1])
        self.assertEqual(self.counters()[("permanent", "walked:W1")], 1)
        self.assertEqual(len(source.wanders), 3)
        self.assertEqual(len(self.rows("WHERE status = 'queued'")), 5)

    def test_of_two_works_walked_together_the_one_with_rows_left_over_is_walked_again_and_the_other_is_not(self):
        self.keep(1)
        self.keep(2)
        rows = [candidate("https://one.example1.org/a", found_from="openalex:W1", depth=1)]
        rows += [candidate(f"https://two{i}.example{i}.org/a", found_from="openalex:W2", depth=1) for i in range(3)]
        source = self.wanderer({"candidates": rows, "rejected": []})
        got = self.fill({"discover_target": 3, "wander_share": 0.67, "wander_per_work": 1, "queue_low": 10**5}, topics=[], sources=self.sources(openalex=source))
        self.assertEqual(got["added"], 2)  # a share of two rows: the one row of the first work, and the first of the three of the second
        self.assertEqual(got["walked"], 1)
        self.assertEqual(self.counters().get(("permanent", "walked:W1")), 1)
        self.assertNotIn(("permanent", "walked:W2"), self.counters())

    def test_a_walk_after_a_topic_phase_that_added_rows_still_takes_its_own_share(self):
        self.keep(1)
        found = {"candidates": [candidate(f"https://w{i}.example{i}.net/a", found_from="openalex:W1", depth=1) for i in range(2)], "rejected": []}
        got = self.fill({"discover_target": 20, "wander_share": 0.2, "wander_per_work": 5, "queue_low": 10**5}, sources=self.sources(openalex=self.wanderer(found)))
        self.assertEqual(len(self.rows("WHERE topic IS NOT NULL")), 12)  # the topic rows (more than the walk's share of four)
        self.assertEqual(len(self.rows("WHERE topic IS NULL AND status = 'queued'")), 2)  # and the two rows of the walk, on top of them
        self.assertEqual((got["added"], got["walked"]), (14, 1))

    def test_a_row_rejected_for_its_type_takes_no_room_so_it_is_recorded_and_does_not_keep_a_work_from_being_walked_for_good(self):
        self.keep(1)
        found = {"candidates": [candidate("https://w.example1.org/a", found_from="openalex:W1", depth=1)],
                 "rejected": [candidate("https://repo.example.edu/a.pdf", found_from="openalex:W1", depth=1)]}
        got = self.fill({"discover_target": 5, "wander_share": 0.2, "wander_per_work": 5, "queue_low": 10**5}, topics=[],
                        sources=self.sources(openalex=self.wanderer(found)))
        self.assertEqual((got["added"], got["rejected"]), (1, 1))  # a share of one row: the candidate takes it, the rejected row takes none
        self.assertEqual(got["walked"], 1)

    def test_a_full_queue_during_the_walk_leaves_the_work_to_be_walked_again(self):
        self.keep(1)

        def wander(kept, get, per_work, max_depth, seen=()):
            for i in range(40):
                crawlqueue.enqueue(self.conn, candidate(f"https://writer{i}.example.net/x"), limits={"queued_total": 10**6, "queued_per_domain": 10**6},
                                   now=NOW, **KW)
            return {"candidates": [candidate("https://w.example.org/a", found_from="openalex:W1", depth=1)], "rejected": []}

        source = Source("openalex")
        source.wander = wander
        got = self.fill({"discover_target": 100, "wander_share": 1.0, "queued_total": 40, "queue_low": 10**5}, topics=[], sources=self.sources(openalex=source))
        self.assertTrue(got["capped"])
        self.assertEqual(got["walked"], 0)
        self.assertNotIn(("permanent", "walked:W1"), self.counters())

    def test_a_refusal_is_recorded_before_what_was_found_before_it_is_stored(self):
        self.keep(1)

        def wander(kept, get, per_work, max_depth, seen=()):
            error = srcopenalex.SourceRefused("status 429")
            error.partial = {"candidates": [dict(candidate("https://w.example.org/a"), source="nonsense")], "rejected": []}
            raise error

        source = Source("openalex")
        source.wander = wander
        with self.assertRaises(KbError):  # the row is not one the queue takes: a fault of the source, which is not swallowed
            self.fill({"discover_target": 50, "wander_share": 1.0, "queue_low": 10**5}, topics=[], sources=self.sources(openalex=source))
        self.assertEqual(self.counters()[("2026-11-16", "source_off:openalex")], 1)

    def test_a_work_kept_twice_is_walked_from_once(self):
        for key in ("k1", "k2"):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                              "VALUES (?, ?, 'openalex', 'openalex:W1', 0, 'kept', 'n', 'n')", (key, f"https://k.example.org/{key}"))
        source = self.wanderer()
        self.fill({"discover_target": 50, "wander_share": 0.5, "wander_per_work": 5, "queue_low": 10**5}, sources=self.sources(openalex=source))
        self.assertEqual([w[0] for w in source.wanders], [[("openalex:W1", 0)]])

    def test_a_wander_share_of_nothing_walks_nowhere(self):
        self.keep(1)
        source = self.wanderer()
        self.fill({"discover_target": 50, "wander_share": 0.0}, sources=self.sources(openalex=source))
        self.assertEqual(source.wanders, [])


class NoChangeTest(Case):
    def test_a_refill_only_inserts_rows_and_only_changes_counters_whatever_the_sources_answer(self):
        self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                          "VALUES ('k', 'https://k.example.org/1', 'openalex', 'openalex:W1', 0, 'kept', 'n', 'n')")
        found = {"candidates": [candidate("https://w.example.org/a", found_from="openalex:W1", depth=1)],
                 "rejected": [candidate("https://repo.example.edu/a.pdf", found_from="openalex:W1", depth=1)]}
        walker = Source("openalex", rows_for("openalex"))
        walker.wander = lambda *a, **k: found
        statements = []
        self.conn.set_trace_callback(statements.append)
        self.fill({"discover_target": 60, "wander_share": 0.5, "queue_low": 10**5}, sources=self.sources(openalex=walker, arxiv=Source("arxiv", refuse="status 429")),
                  is_blocked=lambda a: "owner" if "wikipedia.example.org/" in a and a.endswith("/1") else None)
        self.fill({"discover_target": 60, "wander_share": 0.5, "queue_low": 10**5}, sources=self.sources(openalex=walker), is_blocked=lambda a: None)
        self.conn.set_trace_callback(None)
        changes = [" ".join(s.lower().split()) for s in statements if " ".join(s.lower().split()).startswith(("update", "delete", "drop", "alter", "replace",
                                                                                                               "insert or replace"))]
        self.assertTrue(changes)
        for sql in changes:
            self.assertTrue(sql.startswith("update counters set n = n + 1 where day"), sql)  # the one change there is, and it is on counters
        self.assertFalse([s for s in statements if "candidates" in s.lower() and not s.lower().lstrip().startswith(("select", "insert"))])

    def test_the_kept_rows_and_every_row_there_was_are_as_they_were_after_a_refill(self):
        for n in (1, 2):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, reason, book_id, tries, added, updated) "
                              "VALUES (?, ?, 'openalex', ?, 0, 'kept', 'r', 'book', 2, 'then', 'then')", (f"k{n}", f"https://k.example.org/{n}", f"openalex:W{n}"))
        before = self.rows()
        self.fill({"discover_target": 30, "wander_share": 0.5, "queue_low": 10**5})
        after = self.rows()
        self.assertEqual(after[:len(before)], before)
        self.assertGreater(len(after), len(before))


class PaceTest(Case):
    def test_the_gap_of_a_source_is_slept_between_two_requests_to_it_and_not_before_the_first(self):
        class Asking(Source):
            def search(inner, query, get, limit, *more):
                get(f"https://api.example.org/{inner.name}")  # the request, made through the get that the refill paces
                return super().search(query, get, limit, *more)

        times = {"openalex": [], "wikipedia": []}

        def get(url, headers=None, timeout=None):
            times[url.rsplit("/", 1)[1]].append(self.clock.now)
            return 200, {}, b"{}"

        sources = {"openalex": Asking("openalex"), "arxiv": Source("arxiv"), "wikipedia": Asking("wikipedia")}
        self.fill({"discover_target": 30, "wander_share": 0.0, "gap_openalex_s": 2, "gap_wikipedia_s": 5, "arxiv": False}, sources=sources, get=get)
        for name, gap in (("openalex", 2.0), ("wikipedia", 5.0)):
            seen = times[name]
            self.assertGreaterEqual(len(seen), 3, name)
            self.assertTrue(all(b - a >= gap for a, b in zip(seen, seen[1:])), (name, seen))
        self.assertEqual((times["openalex"][0], times["wikipedia"][0]), (1000.0, 1000.0))  # the first request to a source waited for nothing

    def test_wikipedias_pause_is_kept_between_its_requests(self):
        events = []

        def get(url, headers=None, timeout=None):
            events.append(("get", url, self.clock.now))
            return 200, {}, open(FIXTURES / "wikipedia_empty.json", "rb").read()

        from kb import srcwikipedia
        sources = {"openalex": Source("openalex"), "arxiv": Source("arxiv"), "wikipedia": srcwikipedia}
        self.fill({"discover_target": 30, "wander_share": 0.0, "openalex": False, "arxiv": False, "gap_wikipedia_s": 4, "queue_low": 10**5},
                  sources=sources, get=get)
        times = [t for _, _, t in events]
        self.assertGreaterEqual(len(times), 3)
        self.assertTrue(all(b - a >= 4.0 for a, b in zip(times, times[1:])), times)

    def test_openalexs_pause_is_kept_between_the_three_requests_of_a_walk_too(self):
        for n in (1,):
            self.conn.execute("INSERT INTO candidates (identity_key, address, source, source_id, depth, status, added, updated) "
                              "VALUES ('k', 'https://k.example.org/1', 'openalex', 'openalex:W1000001', 0, 'kept', 'n', 'n')")
        times = []

        def get(url, headers=None, timeout=None):
            times.append(self.clock.now)
            if "/works/W1000001" in url:
                return ok(openalex_fixture("openalex_work_refs.json"))
            if "cites%3A" in url or "cites:" in url:
                return ok(openalex_fixture("openalex_citing.json"))
            return ok(openalex_fixture("openalex_refs_batch.json"))

        sources = {"openalex": srcopenalex, "arxiv": Source("arxiv"), "wikipedia": Source("wikipedia")}
        self.fill({"discover_target": 100, "wander_share": 1.0, "gap_openalex_s": 1.5, "arxiv": False, "wikipedia": False, "queue_low": 10**5},
                  sources=sources, get=get)
        self.assertEqual(len(times), 3)
        self.assertTrue(all(b - a >= 1.5 for a, b in zip(times, times[1:])), times)

    def test_arxiv_is_asked_through_the_pacer_that_was_given_and_never_wrapped_a_second_time(self):
        calls = []

        class Pace:
            def wait(self):
                calls.append("wait")

        class Arxiv(Source):
            def search(self, query, get, limit, pacer):
                calls.append(pacer)
                return super().search(query, get, limit)

        pace = Pace()
        self.fill({"discover_target": 5, "wander_share": 0.0, "openalex": False, "wikipedia": False}, sources=self.sources(arxiv=Arxiv("arxiv")),
                  arxiv_pacer=pace)
        self.assertTrue(calls and all(c is pace for c in calls))
        self.assertEqual(self.clock.slept, [])

    def test_without_a_pacer_given_arxiv_gets_one_that_keeps_three_seconds_at_the_least(self):
        seen = []

        class Arxiv(Source):
            def search(self, query, get, limit, pacer):
                seen.append(pacer)
                pacer.wait()
                return super().search(query, get, limit)

        self.fill({"discover_target": 20, "wander_share": 0.0, "openalex": False, "wikipedia": False, "gap_arxiv_s": 1}, sources=self.sources(arxiv=Arxiv("arxiv")))
        self.assertIsInstance(seen[0], srcarxiv.Pacer)
        self.assertTrue(all(s >= 3.0 for s in self.clock.slept), self.clock.slept)
        self.assertEqual(len({id(p) for p in seen}), 1)  # one pacer for the whole refill

    def test_a_longer_plan_gap_for_arxiv_is_the_pacers(self):
        seen = []

        class Arxiv(Source):
            def search(self, query, get, limit, pacer):
                seen.append(pacer)
                return super().search(query, get, limit)

        self.fill({"discover_target": 5, "wander_share": 0.0, "openalex": False, "wikipedia": False, "gap_arxiv_s": 9}, sources=self.sources(arxiv=Arxiv("arxiv")))
        self.assertEqual(seen[0].gap, 9)


class WebSearchTest(Case):
    def test_web_search_is_asked_last_only_when_the_plan_switches_it_on_and_up_to_its_daily_number(self):
        web = Source("web_search", rows_for("web"))
        sources = dict(self.sources(), web_search=web)
        self.fill({"discover_target": 100, "wander_share": 0.0, "web_search": True, "web_search_per_day": 2, "queue_low": 10**5}, sources=sources)
        self.assertEqual(len(web.searches), 2)
        self.assertEqual(self.counters()[("2026-11-16", "web_search_queries")], 2)
        more = Source("web_search", rows_for("web"))
        self.fill({"discover_target": 100, "wander_share": 0.0, "web_search": True, "web_search_per_day": 2, "queue_low": 10**5},
                  sources=dict(self.sources(), web_search=more))
        self.assertEqual(more.searches, [])
        self.assertIn("the daily number of queries is reached", [f.get("reason") for f in self.log.of("discover", "skipped")])
        again = Source("web_search", rows_for("web"))
        self.fill({"discover_target": 100, "wander_share": 0.0, "web_search": True, "web_search_per_day": 2, "queue_low": 10**5}, now=LATER,
                  sources=dict(self.sources(), web_search=again))
        self.assertEqual(len(again.searches), 2)

    def test_web_search_off_is_never_asked_even_when_a_module_is_there(self):
        web = Source("web_search", rows_for("web"))
        self.fill({"discover_target": 20, "wander_share": 0.0}, sources=dict(self.sources(), web_search=web))
        self.assertEqual(web.searches, [])

    def engine_page(self, name="ddg_results.html", status=200, urls=None):
        def get(url, headers=None, timeout=None):
            if urls is not None:
                urls.append(url)
            return status, {"content-type": "text/html; charset=utf-8"}, (FIXTURES / name).read_bytes()

        return get

    def test_the_real_module_is_the_default_and_its_pages_are_queued_as_web_search_rows(self):
        urls = []
        got = self.fill({"discover_target": 20, "wander_share": 0.0, "web_search": True, "openalex": False, "arxiv": False, "wikipedia": False},
                        sources={}, get=self.engine_page(urls=urls))
        self.assertTrue(urls and all(u.startswith("https://html.duckduckgo.com/html/?q=") for u in urls))
        rows = self.rows()
        self.assertEqual({r[1] for r in rows}, {"web-search"})
        self.assertIn("https://example.org/control/theory", [r[0] for r in rows])
        self.assertGreater(got["added"], 0)
        self.assertEqual(self.counters()[("2026-11-16", "web_search_queries")], len(urls))

    def test_a_page_that_asks_for_a_challenge_turns_the_engine_off_for_the_day_and_is_not_asked_again(self):
        urls = []
        plan = {"discover_target": 20, "wander_share": 0.0, "web_search": True, "openalex": False, "arxiv": False, "wikipedia": False, "queue_low": 10**5}
        got = self.fill(plan, sources={}, get=self.engine_page("ddg_challenge.html", urls=urls))
        self.assertEqual(len(urls), 1)
        self.assertEqual(list(got["refused"]), ["web_search"])
        self.assertEqual(self.counters()[("2026-11-16", "source_off:web_search")], 1)
        self.fill(plan, sources={}, get=self.engine_page("ddg_results.html", urls=urls))
        self.assertEqual(len(urls), 1)  # off for the rest of the day
        self.fill(plan, sources={}, get=self.engine_page("ddg_results.html", urls=urls), now=LATER)
        self.assertGreater(len(urls), 1)  # asked again the next day

    def test_with_the_plan_leaving_web_search_off_the_engine_is_never_asked(self):
        urls = []
        self.fill({"discover_target": 20, "wander_share": 0.0}, sources={"openalex": Source("openalex"), "arxiv": Source("arxiv"), "wikipedia": Source("wikipedia")},
                  get=self.engine_page(urls=urls))
        self.assertEqual(urls, [])

    def test_the_engine_is_asked_last_after_the_other_sources_of_a_pick(self):
        order = []

        class Ordered(Source):
            def search(self, query, get, limit, *more):
                order.append(self.name)
                return super().search(query, get, limit, *more)

        sources = {n: Ordered(n, rows_for(n, 1)) for n in ("openalex", "arxiv", "wikipedia", "web_search")}
        sources["web_search"].rows = rows_for("web", 1)
        self.fill({"discover_target": 4, "wander_share": 0.0, "queries_per_topic": 1, "web_search": True}, sources=sources)
        self.assertEqual(order[:4], ["openalex", "arxiv", "wikipedia", "web_search"])

    def test_a_per_day_number_of_nothing_asks_nothing(self):
        web = Source("web_search", rows_for("web"))
        self.fill({"discover_target": 20, "wander_share": 0.0, "web_search": True, "web_search_per_day": 0}, sources=dict(self.sources(), web_search=web))
        self.assertEqual(web.searches, [])


class LogTest(Case):
    def test_the_steps_and_outcomes_are_those_of_the_spec_and_each_row_has_its_line(self):
        self.fill({"discover_target": 10, "wander_share": 0.0}, is_blocked=lambda a: "owner" if "arxiv.example.org" in a else None)
        steps = {s for s, _, _ in self.log.lines}
        outcomes = {o for _, o, _ in self.log.lines}
        self.assertTrue(steps <= {"discover", "enqueue", "block"}, steps)
        self.assertTrue(outcomes <= {"ok", "skipped", "rejected", "failed", "blocked", "held", "refused", "tripped"}, outcomes)
        rows = self.rows()
        self.assertEqual(len(self.log.of("enqueue", "ok")) + len(self.log.of("block", "blocked")), len(rows))
        self.assertTrue(self.log.of("discover", "ok"))

    def test_a_line_names_the_row_by_address_and_never_holds_a_query_or_a_key(self):
        self.fill({"discover_target": 10, "wander_share": 0.0})
        for step, outcome, fields in self.log.lines:
            self.assertNotIn("query", fields)
            self.assertNotIn("found_from", fields)
        self.assertTrue(all("candidate" in f for f in self.log.of("enqueue")))

    def test_with_no_log_nothing_is_logged_and_nothing_fails(self):
        self.assertGreater(self.fill({"discover_target": 5, "wander_share": 0.0}, log=None)["added"], 0)

    def test_a_log_that_fails_is_not_swallowed(self):
        def broken(step, outcome, **fields):
            raise OSError("the log is full")

        with self.assertRaises(OSError):
            self.fill({"discover_target": 5, "wander_share": 0.0}, log=broken)


class IntegrationTest(Case):
    def test_the_real_source_modules_with_a_fake_get_fill_the_queue_from_the_fixtures(self):
        urls = []

        def get(url, headers=None, timeout=None):
            urls.append(url)
            if "api.openalex.org" in url:
                return ok(openalex_fixture("openalex_search.json"))
            if "export.arxiv.org" in url:
                return 200, {"content-type": "application/atom+xml"}, (FIXTURES / "arxiv_search.xml").read_bytes()
            return ok((FIXTURES / "wikipedia_search.json").read_bytes())

        from kb import srcwikipedia
        sources = {"openalex": srcopenalex, "arxiv": srcarxiv, "wikipedia": srcwikipedia}
        got = self.fill({"discover_target": 30, "wander_share": 0.0, "queries_per_topic": 1}, sources=sources, get=get)
        self.assertGreater(got["added"], 5)
        hosts = {u.split("/")[2] for u in urls}
        self.assertEqual(hosts, {"api.openalex.org", "export.arxiv.org", "en.wikipedia.org"})
        by_source = {r[1] for r in self.rows()}
        self.assertEqual(by_source, {"openalex", "arxiv", "wikipedia"})
        self.assertTrue(any(r[0] == "https://arxiv.org/abs/2401.00001" for r in self.rows()))
        self.assertEqual(self.rows("WHERE status = 'rejected'")[0][7], "type")  # the PDF-only work of the search fixture

    def test_a_topic_weight_the_topics_file_takes_is_one_the_queue_takes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "topics.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[core weight=999999]\nControl theory\n")
            topics = crawltopics.read_topics(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write("[core weight=1000000]\nControl theory\n")
            with self.assertRaises(KbError):
                crawltopics.read_topics(path)
        got = self.fill({"discover_target": 5, "wander_share": 0.0}, topics=topics)
        self.assertGreater(got["added"], 0)
        self.assertEqual({r[3] for r in self.rows()}, {999999})

    def test_with_no_address_functions_given_and_none_built_the_refill_refuses_and_says_so(self):
        try:
            import kb.webaddr  # noqa: F401
        except ImportError:
            with self.assertRaises(KbError) as cm:
                discover.fill(self.conn, {"wander_share": 0.0}, TOPICS, now=NOW, get=lambda *a, **k: None, sources=self.sources(),
                              clock=self.clock, sleep=self.clock.sleep)
            self.assertIn("webaddr", str(cm.exception))

    def test_the_arguments_are_checked_before_anything_is_asked(self):
        sources = self.sources()
        for kw in ({"now": "2026-11-16"}, {"now": None}, {"now": "2026-13-45T10:00:00Z"}, {"get": "not a function"}, {"chat": "not a function"},
                   {"sources": []}, {"sources": {"openalex": 5}}, {"log": "not a function"}, {"cache": []}, {"is_blocked": "x"},
                   {"clock": 5}, {"sleep": None}):
            with self.subTest(kw=kw):
                call = dict(plan={}, topics=TOPICS, now=NOW, get=lambda *a, **k: None, sources=sources, **KW)
                call.update(kw)
                with self.assertRaises(KbError):
                    discover.fill(self.conn, call.pop("plan"), call.pop("topics"), **call)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])

    def test_no_topics_asks_no_topic_query_and_only_walks(self):
        sources = self.sources()
        got = self.fill({"discover_target": 20}, topics=[], sources=sources)
        self.assertEqual(got["added"], 0)
        self.assertEqual([s.searches for s in sources.values()], [[], [], []])


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name
        self.plan = os.path.join(self.folder, "plan.txt")
        self.topics = os.path.join(self.folder, "topics.txt")
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write("[limits]\nqueue_low = 100\ndiscover_target = 40\nqueries_per_topic = 2\n[sources]\nwander_share = 0.25\nweb_search = off\n")
        with open(self.topics, "w", encoding="utf-8") as f:
            f.write("[core weight=10]\nControl theory\nSignal processing\n[low weight=1]\nSystemVerilog\n")
        self.config = os.path.join(self.folder, "config")
        os.mkdir(self.config, 0o700)
        self.env = mock.patch.dict(os.environ, {"KB_CONFIG_DIR": self.config})
        self.env.start()
        self.addCleanup(self.env.stop)

    def put_config(self, **cfg):
        path = os.path.join(self.config, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.chmod(path, 0o600)

    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["crawl-discover", *args])
        return code, out.getvalue(), err.getvalue()

    def tree(self):
        found = {}
        for root, _, files in os.walk(self.folder):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    found[path] = (f.read(), os.stat(path).st_mtime_ns)
        return found

    def test_check_prints_what_a_refill_would_send_and_sends_and_writes_nothing(self):
        before = self.tree()
        with mock.patch("socket.socket.connect", side_effect=AssertionError("a connection")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("a connection")), \
                mock.patch.object(discover, "fill", side_effect=AssertionError("a refill")):
            code, out, err = self.run_command(self.plan, self.topics, "--check")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.tree(), before)
        got = json.loads(out)
        self.assertEqual((got["check"], got["sends"], got["writes"]), (True, "nothing", "nothing"))
        self.assertEqual(got["topics"], 3)
        self.assertEqual(sorted(s for s, v in got["sources"].items() if v["on"]), ["arxiv", "openalex", "wikipedia"])
        self.assertFalse(got["sources"]["web_search"]["on"])
        self.assertEqual(got["plan"]["queue_low"], 100)
        self.assertEqual(got["model"], {"configured": False, "would_call": False, "calls": 0, "why": "there is no config that sets crawl-query"})

    def test_check_gives_the_number_of_queries_each_source_would_get_and_the_queries_when_no_model_makes_them(self):
        code, out, err = self.run_command(self.plan, self.topics, "--check")
        got = json.loads(out)
        picks = got["picks"]
        self.assertEqual(picks, 3)  # a topic part of 30 rows, ten to a request
        for name in ("openalex", "arxiv", "wikipedia"):
            self.assertEqual(got["sources"][name]["requests"], picks)
            self.assertEqual(len(got["sources"][name]["queries"]), picks)
        self.assertEqual(got["sources"]["openalex"]["queries"], got["sources"]["arxiv"]["queries"])
        self.assertTrue(set(got["sources"]["openalex"]["queries"]) <= {"Control theory", "Control theory survey", "Signal processing",
                                                                         "Signal processing survey", "SystemVerilog", "SystemVerilog survey"})
        self.assertEqual(got["sources"]["web_search"]["requests"], 0)
        self.assertEqual(got["wander"]["kept_works_at_most"], 2)  # a wander part of 10 rows, five from each work, three requests each

    def test_check_says_a_model_would_be_called_when_the_config_sets_crawl_query_and_makes_no_call(self):
        self.put_config(models_on=True, models={"local": {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}}, tasks={"crawl-query": "local"})
        code, out, err = self.run_command(self.plan, self.topics, "--check")
        got = json.loads(out)
        self.assertEqual(code, 0, err)
        self.assertEqual((got["model"]["configured"], got["model"]["would_call"]), (True, True))
        self.assertGreaterEqual(got["model"]["calls"], 1)
        self.assertLessEqual(got["model"]["calls"], 3)
        self.assertIsNone(got["sources"]["openalex"]["queries"])  # the model makes them, when it is asked
        self.assertNotIn("srv", out)
        self.assertNotIn("m1:latest", out)

    def test_check_with_model_work_off_or_the_task_unset_would_call_no_model(self):
        self.put_config(models_on=False, models={"local": {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}}, tasks={"crawl-query": "local"})
        self.assertFalse(json.loads(self.run_command(self.plan, self.topics, "--check")[1])["model"]["would_call"])
        self.put_config(models_on=True, models={"local": {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}}, tasks={})
        self.assertFalse(json.loads(self.run_command(self.plan, self.topics, "--check")[1])["model"]["would_call"])

    def test_check_with_every_source_off_says_it_would_send_nothing(self):
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write("[sources]\nopenalex = off\narxiv = off\nwikipedia = off\n")
        got = json.loads(self.run_command(self.plan, self.topics, "--check")[1])
        self.assertEqual([v["requests"] for v in got["sources"].values()], [0, 0, 0, 0])

    def test_without_check_the_command_is_refused_with_the_reason_and_does_nothing(self):
        before = self.tree()
        code, out, err = self.run_command(self.plan, self.topics)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("refused", err)
        self.assertIn("owner", err)
        self.assertEqual(self.tree(), before)

    def test_a_plan_or_topics_file_that_is_wrong_is_a_refusal_and_not_a_traceback(self):
        for args in ((os.path.join(self.folder, "no-plan.txt"), self.topics), (self.plan, os.path.join(self.folder, "no-topics.txt"))):
            code, out, err = self.run_command(*args, "--check")
            self.assertEqual((code, out), (2, ""))
            self.assertIn("refused", err)
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write("[limits]\nqueue_low = lots\n")
        self.assertEqual(self.run_command(self.plan, self.topics, "--check")[0], 2)

    def test_check_says_why_there_is_no_model_and_does_not_fail_on_a_config_that_does_not_say(self):
        entry = {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}
        for cfg, why in ((dict(models_on=False, models={"local": entry}, tasks={"crawl-query": "local"}), "model work is off in the config"),
                         (dict(models_on=True, models={"local": entry}, tasks={}), "tasks.crawl-query is not set in the config")):
            with self.subTest(why=why):
                self.put_config(**cfg)
                model = json.loads(self.run_command(self.plan, self.topics, "--check")[1])["model"]
                self.assertEqual((model["would_call"], model["why"]), (False, why))
        self.put_config(models_on=True, models={"local": entry}, tasks={"crawl-query": "nowhere"})
        code, out, err = self.run_command(self.plan, self.topics, "--check")
        model = json.loads(out)["model"]
        self.assertEqual(code, 0, err)
        self.assertEqual((model["configured"], model["would_call"]), (False, False))
        self.assertTrue(model["why"].startswith("the config does not say"))

    def test_check_of_a_given_moment_and_of_the_moment_it_is_run(self):
        self.assertEqual(discover.check(self.plan, self.topics, now="2031-05-05T10:00:00Z")["day"], "2031-05-05")
        before = discover.datetime.datetime.now(discover.datetime.timezone.utc).date().isoformat()
        got = discover.check(self.plan, self.topics)["day"]
        after = discover.datetime.datetime.now(discover.datetime.timezone.utc).date().isoformat()
        self.assertIn(got, {before, after})

    def test_check_with_one_topic_goes_through_the_queries_in_turn_and_would_call_a_model_once(self):
        with open(self.topics, "w", encoding="utf-8") as f:
            f.write("[core weight=10]\nControl theory\n")
        got = json.loads(self.run_command(self.plan, self.topics, "--check")[1])
        self.assertEqual(got["sources"]["openalex"]["queries"], ["Control theory", "Control theory survey", "Control theory"])
        self.put_config(models_on=True, models={"local": {"bridge": "ask-ollama", "server": "srv", "model": "m1:latest"}}, tasks={"crawl-query": "local"})
        self.assertEqual(json.loads(self.run_command(self.plan, self.topics, "--check")[1])["model"]["calls"], 1)

    def test_check_says_the_search_engine_is_off_unless_the_plan_switches_it_on_and_then_asks_it_up_to_its_daily_number(self):
        off = json.loads(self.run_command(self.plan, self.topics, "--check")[1])["sources"]
        self.assertEqual((off["web_search"]["on"], off["web_search"]["requests"], off["web_search"]["queries"]), (False, 0, []))
        with open(self.plan, "w", encoding="utf-8") as f:
            f.write("[sources]\nweb_search = duckduckgo\nweb_search_per_day = 2\n")
        got = json.loads(self.run_command(self.plan, self.topics, "--check")[1])["sources"]
        self.assertEqual((got["web_search"]["on"], got["web_search"]["requests"]), (True, 2))
        self.assertEqual(got["web_search"]["queries"], got["openalex"]["queries"][:2])
        self.assertGreater(got["openalex"]["requests"], 2)
        self.assertNotIn("built", got["web_search"])

    def test_check_gives_each_sources_gap_from_the_plan_or_the_default(self):
        got = json.loads(self.run_command(self.plan, self.topics, "--check")[1])["sources"]
        self.assertEqual({n: v["gap_s"] for n, v in got.items()}, {"openalex": 1, "arxiv": 3, "wikipedia": 1, "web_search": 30})

    def test_check_gives_the_wander_figures_of_the_plan(self):
        cases = (("[limits]\ndiscover_target = 40\n[sources]\nwander_share = 0.25\n", (True, 10, 2)),
                 ("[limits]\ndiscover_target = 10\n[sources]\nwander_share = 0.3\n", (True, 3, 1)),
                 ("[limits]\ndiscover_target = 40\n[sources]\nwander_share = 0\n", (False, 0, 0)),
                 ("[limits]\ndiscover_target = 40\n[sources]\nwander_share = 0.25\nopenalex = off\n", (False, 10, 0)))
        for text, (on, rows, works) in cases:
            with self.subTest(text=text):
                with open(self.plan, "w", encoding="utf-8") as f:
                    f.write(text)
                wander = json.loads(self.run_command(self.plan, self.topics, "--check")[1])["wander"]
                self.assertEqual((wander["on"], wander["rows"], wander["kept_works_at_most"]), (on, rows, works))
        self.assertEqual((wander["per_work"], wander["depth"], wander["requests_per_kept_work"]), (5, 2, 3))

    def test_the_command_is_listed_and_takes_a_plan_a_topics_file_and_check(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(["crawl-discover", "--help"])
        self.assertIn("--check", out.getvalue())
        self.assertIn("plan", out.getvalue())


if __name__ == "__main__":
    unittest.main()
