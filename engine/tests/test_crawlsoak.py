"""A soak of the unattended crawl: fourteen simulated days on one temporary library (`kb/crawlrun.py`, the plans `2026-11-16-run-the-steps-of-the-unattended-crawl`, `2026-11-17-see-when-a-model-of-the-unattended-crawl-is-down`
and the plans of the small gaps; `docs/specs/population.md`, "The crawl plan" and "Safeguards").

`test_crawlchain` runs the whole chain once, `test_crawldays` runs it over three or four days. This file runs **the real `crawlrun.run` with the real steps** as `crawlrun.default_steps` assembles them, on one library, over **fourteen
days** (2026-11-16 to 2026-11-29, in UTC), with the injected clock moved from run to run, and shows by what the log, the queue, the counters, the guard files and the library say that the crawl keeps its limits over a long span.
The plan is the one of the soak: `fetches_per_day 400`, `cards_per_day 400`, `filed_total 4500`, `batch 6`, `per_domain_per_day 150`, `queued_per_domain 400`, `queue_low 300`, `discover_target 800`, `model_down_minutes 720`,
`consecutive_failures 40`, `failure_share 0.8`, `window 40`, and the moves off.

**The cadence.** The real agent starts a run every 900 seconds (96 a day), and each run's budget is `RUN_SECONDS`. A run costs time in proportion to the books in the library (the steps read every crawl book several times), so the file
runs every 15 minutes **only on the days and hours that carry a check that needs it** (day 1, which reaches the day's ceilings, and the windows in which a model is down or the network is out, which are measured in hours), and on the
other days it runs **four times a day** (00:00, 06:00, 12:00 and 18:00: the lists come due every second run). The file takes a few minutes.

**The days.** 1: the ceilings (a flood of one site, a redirect to a site at its limit). 2: the model entry of the judgement's embedding (`place-embed`; the chat entry is never asked, the moves being off) down for 13 hours: the breaker trips. 3: the same entry down for 8 hours: it does not.
4: the card embedding down for 8 hours. 5: the card embedding down for 13 hours. 6: the network out (a short outage, then one that trips on the share of failures, then one that trips on the run of failures). 7: a run killed
at each step. 8 to 9: quiet days, and a lists download that fails for a day. 10: `filed_total` is reached (the library is given the books of the earlier weeks, for a library of 4,500 books is too slow to fill by runs). 11 to 14:
nothing more can be fetched.

**What stands in for the real thing** (each is named here and in the report of the commit that adds this file): the pages and their hosts (the loopback server of `test_webclient` through the real shared client and the real
capture, as in `test_crawlchain`), the lists downloader (`test_crawllists.Fetch`), the sources of the refill (`Feed`: every search finds new addresses whose pages the fake server serves), the scan, the converter and the index
(`test_crawlsteps`), the embedding model and the chat model (the hooks of `test_placement`), the free space, the model probes and the model entries' probes (injected), **the card step (the small fake of `test_crawlchain`)**,
and the day-1 count of redirected visits to one site, which is made with the real `crawlstate.charge_hop` and the books of the earlier weeks, which are made with the real `crawlbooks` functions. The moves are off (the plan says so), so
the chat model is never asked and no book is moved. No request leaves the machine, no model is called, nothing reads the owner's config, plan, key, library or shelves, and nothing sleeps.

Run it with `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlsoak` (the other files of the chain and the days tests need the shell's umask to be 022)."""
import collections
import datetime
import json
import os
import re
import unittest

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests import test_crawlchain as chain
from engine.tests import test_crawldays as days
from engine.tests.test_crawllists import PHISH_URL, Fetch
from engine.tests.test_discover import Source, candidate

from kb import KbError, card, crawlbooks, crawlguard, crawllists, crawllog, crawlmove, crawlqueue, crawlrefill, crawlstate, crawlsteps, webclient

UTC = datetime.timezone.utc
at = days.at
PLAN_TEXT = """[limits]
batch = 6
fetches_per_day = 400
filed_total = 4500
per_domain_per_day = 150
cards_per_day = 400
retries = 3
timezone = UTC
queued_per_domain = 400
queue_low = 300
discover_target = 800
[pacing]
min_gap_s = 0
jitter = 0
[breaker]
consecutive_failures = 40
failure_share = 0.8
window = 40
model_down_minutes = 720
domain_refusals = 3
[judge]
threshold = 0.9
min_chars = 400
[moves]
model_pick = off
[sources]
arxiv = off
"""
TOPICS = {"alpha": 10, "bravo": 10, "charlie": 10, "delta": 10, "echo": 5, "foxtrot": 5, "golf": 5, "hotel": 1, "india": 1}
TOPICS_TEXT = "[core weight=10]\nalpha\nbravo\ncharlie\ndelta\n[wide weight=5]\necho\nfoxtrot\ngolf\n[low weight=1]\nhotel\nindia\n"
HOSTS = [f"site{n}.test" for n in range(8)]
PER_SEARCH = 3                                          # new addresses that one search of a fake source finds
FLOOD = 160                                             # candidates of one site, queued on day 1
LIMIT = 150                                             # the plan's per_domain_per_day
RUN_MINUTES = 15
EDGE = "edge.test"                                      # the site that redirects lead to on day 1
FETCH_DAY, CARD_DAY, FILED_TOTAL, BATCH = 400, 400, 4500, 6
ISSUE_LIMIT = "failed 3 times: the site it leads to is at its limit for the day"
SPAN = 14


class Feed(Source):
    """A fake source of the refill: each search finds `PER_SEARCH` addresses that no search found before, on the sites of `HOSTS`, and the fake server serves their pages."""

    def __init__(self, name, case, source):
        super().__init__(name, rows=lambda query: case.found(source, query))


class Stamped(Fetch):
    """The fake downloader of the lists, which also keeps the time of each call and whether the address was one that a test made fail."""

    def __init__(self, case):
        super().__init__()
        self.case, self.stamps, self.failing = case, [], set()

    def __call__(self, url, **kw):
        self.stamps.append((url, self.case.now, url in self.failing))
        return super().__call__(url, **kw)


class Soak(days.Days):
    plan_text = PLAN_TEXT

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o077))        # before the library is made: the index folder must be one that only we can write, whatever the shell's umask
        super().setUp()
        self.emb_up, self.outage, self.known = True, False, set()
        self.serial, self.flaky, self.repeatable = 0, set(), set()
        self.offsets, self.tally, self.reasons = {}, collections.Counter(), collections.Counter()
        self.order_ids, self.runs, self.lists_runs, self.fetch_days = [], [], [], []
        self.snapshot, self.filed_seen, self.seeded = {}, 0, 0
        self.closed, self.current_day, self.max_queued = {}, None, 0
        self.last = []
        replies = self.lists.replies
        self.lists = Stamped(self)
        self.lists.replies.update(replies)
        self.phish_reply = replies[PHISH_URL]
        self.sources = {"openalex": Feed("openalex", self, "openalex"), "wikipedia": Feed("wikipedia", self, "wikipedia"), "arxiv": Source("arxiv"), "web_search": Source("web")}

    # -- the plan: the topics of the soak (many, with three weights)
    def set_plan(self, text):
        topics, allow = self.put("topics.txt", TOPICS_TEXT), self.put("allow.txt", "")
        self.plan_path = self.put("plan.txt", text + f"[files]\ntopics = {topics}\nallow = {allow}\nblacklist = {os.path.join(self.files, 'black.txt')}\n")
        digest = chain.crawlapprove.approve(self.index, self.cfg_crawl, self.plan_path, kb_root=self.kb_tree)[1]
        chain.crawlapprove.approve(self.index, self.cfg_crawl, self.plan_path, digest=digest, kb_root=self.kb_tree, is_tty=lambda: True, say=lambda s: None, now=chain.NOW)
        approved = chain.crawlapprove.load_approved(self.index, self.cfg_crawl, kb_root=self.kb_tree)
        self.digest, self.plan = approved["digest"], approved["plan"]

    # -- the fakes that this file changes
    def host_dns(self, host):
        self.known.add(host)
        if not self.outage:
            super().host_dns(host)

    def set_outage(self, on):
        """The network is out: no name resolves. When it is back every name that was made resolves again."""
        self.outage = on
        if on:
            self.saved_dns, self.dns = self.dns, {}
        else:
            self.dns = self.saved_dns
            for host in self.known:
                self.dns.setdefault(host, ["93.184.216.34"])

    def hook(self, name, *args):
        if name == "embed" and not self.emb_up:
            raise KbError("the embedding model does not answer")
        super().hook(name, *args)

    def entry_probe(self, cfg, task):
        self.entry_calls.append(task)
        return self.emb_up if task == "place-embed" else True

    def steps(self, without=(), **over):
        """The real steps with the fakes, and a judge whose probe asks the entry of its own model (the card embedding of the run's start is the other probe, `self.up`)."""
        if "judge" not in without:
            over.setdefault("judge", crawlsteps.make_judge_step(embed=self.embed_hooked, statvfs=chain.roomy, probe=self.entry_probe))
        lists = crawllists.make_step(fetch=self.lists, key_path=os.path.join(self.files, "no.key"))
        refill = crawlrefill.make_step(fetch=self.lists, sources=self.sources)

        def first(ctx):
            self.hook("lists")
            self.ctx = ctx
            return lists(ctx)

        def again(ctx):
            self.hook("refill")
            return refill(ctx)

        over.setdefault("lists", first)
        over.setdefault("refill", again)
        return super().steps(without, **over)

    # -- the candidates: a page for every address that a source finds, with a few kinds that go another way
    def found(self, source, query):
        rows = []
        for _ in range(PER_SEARCH):
            self.serial += 1
            k = self.serial
            host, path, title = HOSTS[k % len(HOSTS)], f"/s{k:06d}", f"Soak {k:06d}"
            self.host_dns(host)
            self.targets[title] = "gene-editing"
            if k % 47 == 9:                                                 # a page that always answers 500: three tries, then the row is failed
                self.srv.routes[path] = chain.reply(500, body=b"broken")
                self.flaky.add(path)
                self.repeatable.add(path)
            else:
                self.srv.routes[path] = chain.reply(200, body=chain.page(title))
            if k % 41 == 3:
                self.scan_kinds[path] = ["javascript"]                       # the scan holds it
            if k % 29 == 5:
                self.weak.add(title)                                         # the judge's best match is far under the threshold
            rows.append(candidate(f"http://{host}{path}", source))
        return rows

    # -- the clock
    def every(self, day, start, stop, minutes=RUN_MINUTES):
        """The times of the day from `start` up to, and not including, `stop` (hour, minute), every `minutes`."""
        moment, end = at(day, *start), (at(day + 1, 0, 0) if stop == (24, 0) else at(day, *stop))
        while moment < end:
            yield moment
            moment += datetime.timedelta(minutes=minutes)

    def quiet(self, day, hours=(0, 6, 12, 18), steps=None):
        """A day that carries no check of its own: four runs."""
        return [self.play(at(day, hour), steps=steps) for hour in hours]

    # -- one run, and what every run must leave true
    def play(self, now, **kw):
        code = self.go(now=now, **kw)
        self.after(code)
        return code

    def read_log(self):
        folder = os.path.join(self.index, "crawl", "log")
        new = []
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            with open(os.path.join(folder, name), "rb") as f:
                f.seek(self.offsets.get(name, 0))
                data = f.read()
            end = data.rfind(b"\n") + 1
            self.offsets[name] = self.offsets.get(name, 0) + end
            new += [json.loads(line) for line in data[:end].decode("utf-8").splitlines()]
        self.last = new
        for line in new:
            self.tally[(line["step"], line["outcome"])] += 1
            if line["step"] in ("fetch", "run_end", "refuse", "breaker", "stop", "propose") and line["reason"]:
                self.reasons[(line["step"], line["outcome"], line["reason"])] += 1
        return new

    def count(self, sql, *args):
        conn = crawlqueue.connect(self.index)
        try:
            return conn.execute(sql, args).fetchone()[0]
        finally:
            conn.close()

    def counters_of(self, day=None):
        found = self.counters()
        return found if day is None else {key: n for (found_day, key), n in found.items() if found_day == day}

    def after(self, code):
        """What holds after every run (and after one that was killed, `code` None): the run took no more than the batch; no ceiling of any day is passed; the counters of a day that is over are as they were."""
        new = self.read_log()
        fetches = [l for l in new if l["step"] == "fetch" and l["candidate"] is not None]
        self.assertLessEqual(len(fetches), BATCH, self.now)
        self.order_ids += [l["candidate"] for l in fetches]
        self.fetch_days += [(self.now.date().isoformat(), l["candidate"]) for l in fetches]
        self.filed_seen += sum(1 for l in new if l["step"] == "capture" and l["outcome"] == "ok")
        self.assertLessEqual(self.filed_seen + self.seeded, FILED_TOTAL, self.now)
        if any(l["step"] == "list_update" for l in new):
            self.lists_runs.append(self.now)
        today, found = self.now.date().isoformat(), self.counters()
        if self.current_day not in (None, today):
            self.closed[self.current_day] = {key: n for (day, key), n in self.snapshot.items() if day == self.current_day}          # the last that was seen of a day that is over
        self.current_day = today
        for (day, key), n in found.items():
            before = self.snapshot.get((day, key), 0)
            self.assertGreaterEqual(n, before, (day, key))
            if day != today:
                self.assertEqual(n, before, f"the counter {key} of the day {day}, which is over, changed")
            limit = FETCH_DAY if key == "fetch" else CARD_DAY if key == "card" else LIMIT if key.startswith(("fetch:", "hop:")) else None
            if limit is not None:
                self.assertLessEqual(n, limit, f"the counter {key} of the day {day} is over its ceiling")
        self.snapshot = found
        self.runs.append((self.now, code))
        self.max_queued = max(self.max_queued, self.count("SELECT COUNT(*) FROM candidates WHERE status = 'queued'"))

    # -- what a phase reads
    def entries_down(self):
        return crawlguard.load_state(self.index)[0]["entries_down"]

    def breaker(self):
        return crawlguard.read_breaker(self.index)

    def clear_breaker(self, now):
        self.now = now
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=now)

    def judged(self):
        return self.tally[("judge", "ok")] + self.tally[("judge", "rejected")]

    def crawl_scan(self):
        return crawlbooks.scan_crawl_books(self.store)

    def step_failed(self):
        return sum(1 for e in self.crawl_scan().entries for x in e["events"] if isinstance(x, dict) and x.get("event") == "crawl_step_failed")

    def unjudged(self):
        return [e["id"] for e in self.crawl_scan().entries if e["state"] == "active" and not any(isinstance(x, dict) and x.get("event") in ("crawl_judged", "crawl_held", "crawl_rejected") for x in e["events"])]

    def no_duplicate_fetch(self):
        again = {p: c for p, c in collections.Counter(self.requests()).items() if c > 1 and p not in self.repeatable}
        self.assertEqual(again, {}, "a page that was served was fetched again")

    def refused_runs_change_nothing(self, times, code):
        """Each of these runs ends with `code`, and none makes a request, takes a candidate or changes a counter."""
        before = (len(self.requests()), self.rows(), self.counters())
        for now in times:
            self.assertEqual(self.play(now), code, now)
        self.assertEqual((len(self.requests()), self.rows(), self.counters()), before)

    # ----------------------------------------------------------------------------------------------- the days
    def owners_books(self):
        """Books of the owner's own, on the default shelf and on another, with a card and without one."""
        books = [self.book_with(f"Owner with a card {n}")[0] for n in range(5)] + [self.store.create_book(title=f"Owner without a card {n}", kind="preprint") for n in range(5)]
        books += [self.store.create_book(title="Owner on a shelf", kind="preprint", shelf="cloning")]
        return books

    def owners_state(self, books):
        """Everything the library holds about these books: the record, the events and the cards."""
        out = {}
        for book in books:
            root = self.store.read_book(book)
            version = root.get("current_version")
            out[book] = (root, self.store.read_events(book), len(card.generations(self.store, book, version)) if version else 0)
        return out

    def day_1_the_ceilings(self):
        for n in range(FLOOD):                                              # one site with more candidates than its limit
            self.add(f"/press/{n:03d}", host="press.test", topic="press", weight=999_999, target="gene-editing")
        self.hopper = self.redirecting("/doi/limit", "doi.test", f"http://{EDGE}/paper")        # a redirect to a site that is at its limit (made so below)
        self.repeatable.add("/doi/limit")
        conn = self.conn()
        for _ in range(LIMIT):                                              # the day's visits to the edge site by redirects, made with the real counter
            self.assertEqual(crawlstate.charge_hop(conn, self.plan, at(1, 0, 0), EDGE), "")
        for now in self.every(1, (0, 0), (24, 0)):
            self.assertEqual(self.play(now), 0, now)
        today = self.counters_of("2026-11-16")
        self.assertEqual((today["fetch"], today["fetch:press.test"], today[f"hop:{EDGE}"]), (FETCH_DAY, LIMIT, LIMIT))       # three ceilings were reached, and none was passed
        self.assertLessEqual(today["card"], CARD_DAY)
        self.assertEqual(len(self.runs), 96)
        self.assertIn(("fetch", "skipped", "fetches_per_day reached: no new candidates today"), {(s, o, r) for s, o, r in self.reasons})
        press = [r for r in self.rows() if r["topic"] == "press"]
        self.assertEqual(sorted(collections.Counter(r["status"] for r in press).items()), [("kept", LIMIT), ("queued", FLOOD - LIMIT)])       # the 150 within the limit, the rest waiting for the next day
        # A candidate whose redirect leads to a site that is at its limit: **the current behaviour** is that each try is counted, the row waits 1 and then 6 hours, and at `retries` it is failed. (The owner may want a put-off
        # hop not to count as a try: it is a limit of the day and not a fault of the candidate. This test shows what is, and would change with that.)
        row = self.row(self.hopper)
        self.assertEqual((row["status"], row["tries"], row["reason"], row["book_id"]), ("failed", 3, ISSUE_LIMIT, None))
        self.assertEqual(self.requests().count("/doi/limit"), 3)
        self.assertNotIn("/paper", self.requests())
        self.assertEqual(self.counters_of("2026-11-16")["fetch:doi.test"], 3)         # each try took a unit of the redirector's own site
        self.assert_nothing_half_made()
        self.no_duplicate_fetch()

    def day_2_a_model_entry_down_for_13_hours(self):
        """The entry of the judgement's embedding stops answering at 02:00 and answers again at 15:00; the runs go on and cost no book a try until the entry has been down for over `model_down_minutes`, and then the breaker trips."""
        for now in self.every(2, (0, 0), (2, 0), 60):
            self.assertEqual(self.play(now), 0)
        self.emb_up = False
        judged, down = self.judged(), {"emb": "2026-11-17T02:00:00Z"}
        for now in self.every(2, (2, 0), (14, 1)):                          # to 14:00, which is down for exactly 720 minutes
            self.assertEqual(self.play(now), 0, now)
            self.assertEqual(self.entries_down(), down, now)                 # the clock keeps its first time, run after run
            self.assertFalse(self.breaker()["tripped"], now)
        self.assertEqual(self.judged(), judged)                              # nothing was judged while the entry was down, and the runs went on fetching
        self.assertEqual(self.step_failed(), 0)                              # no book was charged a try for it
        self.assertGreater(len(self.unjudged()), 100)
        sent, fetched = len(self.requests()), self.counters_of("2026-11-17")["fetch"]
        self.assertEqual(self.play(at(2, 14, 15)), 4)                        # a quarter of an hour longer than the limit
        self.assertEqual([l["step"] for l in self.last if l["step"] in ("run_start", "fetch")], [])        # the trip was made by the probe at the start of the run, before any step: nothing was begun,
        self.assertEqual((len(self.requests()), self.counters_of("2026-11-17")["fetch"]), (sent, fetched))   # fetched or counted
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn("the model entry emb has not answered for over 720 minutes", breaker["reason"])
        asked, requests = len(self.entry_calls), len(self.requests())
        self.refused_runs_change_nothing(self.every(2, (14, 30), (15, 0)), 4)
        self.emb_up = True                                                    # the model is back, and the runs are refused until the owner clears the breaker
        self.refused_runs_change_nothing(self.every(2, (15, 0), (16, 0)), 4)
        self.assertEqual((len(self.entry_calls), len(self.requests())), (asked, requests))            # not even a probe was made
        self.assertEqual(self.step_failed(), 0)
        self.clear_breaker(at(2, 16, 0))
        self.assertEqual(self.play(at(2, 16, 15)), 0)
        self.assertEqual((self.entries_down(), self.unjudged()), ({}, []))                            # the waiting books were judged by the first run
        self.assertEqual(self.step_failed(), 0)
        self.assert_nothing_half_made()
        self.quiet(2, hours=(20,))

    def day_3_a_model_entry_down_for_8_hours(self):
        """The same entry is down from 08:00 to 16:00: the breaker does not trip, no book is charged a try, and the books that waited are judged when it answers."""
        self.quiet(3, hours=(0, 6))
        self.emb_up = False
        judged, failed, down = self.judged(), self.step_failed(), {"emb": "2026-11-18T08:00:00Z"}
        for now in self.every(3, (8, 0), (16, 0)):
            self.assertEqual(self.play(now), 0, now)
            self.assertEqual(self.entries_down(), down, now)
            self.assertFalse(self.breaker()["tripped"], now)
        self.assertEqual((self.judged(), self.step_failed()), (judged, failed))
        waiting = len(self.unjudged())
        self.assertGreaterEqual(waiting, 100)
        self.emb_up = True
        self.assertEqual(self.play(at(3, 16, 0)), 0)
        self.assertEqual((self.entries_down(), self.unjudged()), ({}, []))
        self.assertGreaterEqual(self.judged(), judged + waiting)
        self.assertEqual(self.step_failed(), failed)
        self.assertGreater(self.reasons[("breaker", "ok", "the model entry emb answers again")], 0)
        self.quiet(3, hours=(18,))

    def day_4_the_card_embedding_down_for_8_hours(self):
        """The card embedding is the probe at the start of a run: a run is refused (exit 3) while it is down, and the clock keeps its first time; it trips at no time within the limit."""
        self.quiet(4, hours=(0, 3))
        self.up = False
        probes = self.probes
        self.refused_runs_change_nothing(self.every(4, (6, 0), (14, 0)), 3)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-19T06:00:00Z")
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(self.probes - probes, 32)                           # one probe in each run, and nothing else was asked of any model
        self.assertIn("the model server does not answer", self.err[-1])
        self.up = True
        self.assertEqual(self.play(at(4, 14, 0)), 0)
        self.assertIsNone(crawlguard.load_state(self.index)[0]["model_down_since"])
        self.quiet(4, hours=(18,))

    def day_5_the_card_embedding_down_for_13_hours(self):
        self.quiet(5, hours=(0,))
        self.up = False
        for now in self.every(5, (2, 0), (14, 1)):
            self.assertEqual(self.play(now), 3, now)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-20T02:00:00Z")
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(self.play(at(5, 14, 15)), 4)
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn("the model server has not answered for over 720 minutes", breaker["reason"])
        probes = self.probes
        self.refused_runs_change_nothing(self.every(5, (14, 30), (15, 0)), 4)
        self.up = True
        self.refused_runs_change_nothing(self.every(5, (15, 0), (16, 15)), 4)
        self.assertEqual(self.probes, probes)                                 # refused before the probe
        self.clear_breaker(at(5, 16, 15))
        self.assertEqual(self.play(at(5, 16, 30)), 0)
        self.assertIsNone(crawlguard.load_state(self.index)[0]["model_down_since"])
        self.quiet(5, hours=(20,))

    def failed_fetches(self):
        return self.tally[("fetch", "failed")]

    def day_6_the_network_out(self):
        """No name resolves, so every fetch fails. **With the soak's plan the share rule comes first:** `failure_share 0.8` of a `window` of 40 is 32, so a full window of earlier successes trips at the 32nd failure in a row,
        whatever `consecutive_failures` says; the run of 40 can only trip when the history is not full (after a clear, which makes it empty). Both are shown, after one outage that is too short for either."""
        for now in self.every(6, (8, 0), (10, 0)):                            # a history of 48 fetches that worked
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"][-40:].count(False), 0)
        self.set_outage(True)
        before = self.failed_fetches()
        for now in self.every(6, (10, 0), (11, 15)):                          # five runs: 30 failures in a row
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.failed_fetches() - before, 30)
        self.assertFalse(self.breaker()["tripped"])
        self.set_outage(False)
        for now in self.every(6, (11, 15), (13, 15)):                         # the fetches work again: the window is cleared of the failures by 48 more
            self.assertEqual(self.play(now), 0, now)
        self.assertFalse(self.breaker()["tripped"])
        self.set_outage(True)
        before = self.failed_fetches()
        times = list(self.every(6, (13, 15), (15, 0)))
        codes = [self.play(now) for now in times]
        self.assertEqual(codes[:5], [0] * 5)
        self.assertEqual(codes[5], 4)                                         # the 6th run: the 32nd failure in a row, with the window full
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "failure_share"))
        self.assertIn("32 of the last 40 fetches failed", breaker["reason"])
        self.assertIn(self.failed_fetches() - before, (31, 32))               # (a failed page of the earlier days may still be in the window)
        self.assertTrue(all(code == 4 for code in codes[5:]))
        self.set_outage(False)
        self.refused_runs_change_nothing(self.every(6, (15, 0), (15, 30)), 4)
        self.clear_breaker(at(6, 15, 30))
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [])                             # a clear is a fresh start
        self.set_outage(True)
        before = self.failed_fetches()
        times = list(self.every(6, (15, 45), (17, 30)))
        codes = [self.play(now) for now in times]
        self.assertEqual(codes[:6], [0] * 6)
        self.assertEqual(codes[6], 4)                                         # 36 failures in six runs, and the 40th in the seventh
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"], breaker["reason"]), (True, "consecutive_failures", "40 fetches in a row failed"))
        self.assertEqual(self.failed_fetches() - before, 40)
        self.set_outage(False)
        self.refused_runs_change_nothing(self.every(6, (17, 30), (18, 0)), 4)
        self.clear_breaker(at(6, 18, 0))
        self.assertEqual(self.play(at(6, 18, 15)), 0)
        self.assertGreater(self.counters_of("2026-11-21")["fetch"], 150)
        self.quiet(6, hours=(21,))

    KILLS = ("lists", "refill", "capture", "scan", "convert", "index", "embed", "card")

    def day_7_a_run_killed_at_each_step(self):
        """A death at each point of a run (the fetch's own capture, the scan, the convert, the index, the judge's model call and the card are the fakes of `test_crawlchain`; the lists and the refill are the two points before them), one an hour, and
        the next run, half an hour after, finishes what it left."""
        self.stalled = None
        for n, point in enumerate(self.KILLS):
            self.die_at(point)
            then = at(7, 6 + n, 0)
            with self.assertRaises(chain.Boom):
                self.go(now=then)
            self.after(None)
            crawlguard.acquire_run_lock(self.index, now=then).release()        # the lock was let go
            dead = [(r["id"], r["tries"]) for r in self.rows() if r["status"] == "fetching"]       # the row of a fetch that was going when the run died is left `fetching`
            self.assertEqual(len(dead), 1 if point == "capture" else 0, point)
            self.assertEqual(self.play(at(7, 6 + n, 31)), 0, point)
            self.assert_nothing_half_made()
            self.no_duplicate_fetch()
            stalled = [l for l in self.last if l["step"] == "fail"]
            if point == "capture":
                self.assertEqual([(l["outcome"], l["reason"]) for l in stalled], [("ok", "1 stalled rows queued again, 0 given up")])      # the row of the dead fetch is queued again, and tried again after its wait
                row = self.row(dead[0][0])
                self.assertEqual((row["status"], row["tries"], row["reason"], row["book_id"]), ("queued", dead[0][1], "stalled for over 30 minutes", None))
                self.stalled = row["id"]
            else:
                self.assertEqual(stalled, [])
            self.assertEqual(self.unjudged(), [], point)
        self.quiet(7, hours=(16, 20))

    def day_8_a_quiet_day(self):
        self.quiet(8)

    def day_9_the_lists_download_failing(self):
        """The public lists are due every 12 hours. A download that fails does not stop a run while the last copy stands: the runs go on and fetch, and ask again at the next run."""
        self.lists.failing = {PHISH_URL}
        self.lists.replies[PHISH_URL] = webclient.FetchError("the list server does not answer")
        before = self.tally[("list_update", "failed")]
        fetched = self.counters_of("2026-11-24").get("fetch", 0)
        for code in self.quiet(9, hours=(0, 6, 12, 18)):
            self.assertEqual(code, 0)
        self.assertGreaterEqual(self.tally[("list_update", "failed")] - before, 3)              # asked at each run that found it due, and failed
        self.assertEqual(self.counters_of("2026-11-24")["fetch"] - fetched, 4 * BATCH)           # and every run fetched its batch
        self.lists.failing = set()
        self.lists.replies[PHISH_URL] = self.phish_reply

    def fingerprint(self):
        """Everything that grows when the crawl takes in a book."""
        scan = self.crawl_scan()
        return {"books": len(self.store.list_books()), "filed": crawlbooks.filed_count(self.store, scan), "events": sum(len(e["events"]) for e in scan.entries), "requests": len(self.requests()),
                "tried": self.count("SELECT COUNT(*) FROM candidates WHERE tries > 0"), "fetched": self.count("SELECT COALESCE(SUM(n), 0) FROM counters WHERE key = 'fetch'"), "rows": self.count("SELECT COUNT(*) FROM candidates")}

    def day_10_filed_total(self):
        """The library is given the books of the earlier weeks, up to nine short of `filed_total`: the first run takes six, the next takes three and stops at 4,500, and nothing is taken after."""
        self.play(at(10, 0, 0))
        have = crawlbooks.filed_count(self.store)
        for n in range(FILED_TOTAL - 9 - have):
            book = self.store.create_book(title=f"Earlier {n:05d}", kind="webpage", auto_filed=True)
            crawlbooks.record_found(self.store, book, candidate=900_000 + n, source="openalex", found_from=None, topic="alpha", run="earlier-run", plan_digest=self.digest)
            crawlbooks.record_judged(self.store, book, 0.3, "cloning", False)
            crawlbooks.weed(self.store, book, "judged out", 0.3, "judge")
            self.seeded += 1
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL - 9)
        self.assertEqual(self.play(at(10, 6, 0)), 0)
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL - 3)
        self.assertEqual(self.play(at(10, 6, 15)), 0)
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL)       # the third book of the second run was the 4,500th
        self.assertIn(("fetch", "skipped", "filed_total reached: no new books"), {(s, o, r) for s, o, r in self.reasons})
        self.assertEqual(self.play(at(10, 6, 30)), 0)                            # the run that finishes the last books
        done = self.fingerprint()
        self.assertEqual(done["filed"], FILED_TOTAL)
        self.play(at(10, 12, 0))
        self.play(at(10, 18, 0))
        self.assertEqual(self.fingerprint(), done)
        self.assertEqual(self.unjudged(), [])
        self.frozen = done

    def days_11_to_14_nothing_more_is_taken(self):
        for day in range(11, SPAN + 1):
            fetched = self.counters_of(f"2026-11-{15 + day}").get("fetch", 0)
            self.assertEqual(fetched, 0)
            self.quiet(day, hours=(0, 12))
            self.assertEqual(self.fingerprint(), self.frozen)                     # no book, no event, no request, no candidate tried, no fetch counted
            self.assertEqual(self.counters_of(f"2026-11-{15 + day}").get("fetch", 0), 0)
        self.assertEqual([c for _t, c in self.runs[-8:]], [0] * 8)

    # ----------------------------------------------------------------------------------------------- what the whole span shows
    def audit_the_ceilings(self):
        """No ceiling of any day was passed (each run was checked as it ended); the counters of every day that is over are as they were when it ended; the days' fetches are the ones the days could take."""
        for day, last in self.closed.items():
            self.assertEqual(self.counters_of(day), last, day)
        self.assertEqual(len(self.closed), SPAN - 1)
        found = self.counters()
        fetch = {day: n for (day, key), n in sorted(found.items()) if key == "fetch"}
        self.assertEqual(max(fetch.values()), FETCH_DAY)
        self.assertEqual([day for day, n in fetch.items() if n == FETCH_DAY], ["2026-11-16"])                  # only the day of 96 runs reached it
        self.assertEqual({day: n for day, n in fetch.items() if day > "2026-11-25"}, {})                      # and nothing was fetched after `filed_total`
        for (day, key), n in found.items():
            if key.startswith(("fetch:", "hop:")):
                self.assertLessEqual(n, LIMIT, (day, key))
            if key == "card":
                self.assertLessEqual(n, CARD_DAY, day)
        self.assertEqual((found[("2026-11-16", "fetch:press.test")], found[("2026-11-16", f"hop:{EDGE}")]), (LIMIT, LIMIT))
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL)

    def audit_the_topics(self):
        """The turns of the topics follow their weights over the span, and no topic is left behind."""
        rows = self.rows()
        tried = collections.Counter(r["topic"] for r in rows if r["tries"] > 0)
        per_weight = {topic: tried[topic] / weight for topic, weight in TOPICS.items()}
        mean = sum(per_weight.values()) / len(per_weight)
        for topic, value in per_weight.items():
            self.assertTrue(0.9 * mean <= value <= 1.1 * mean, (topic, tried[topic], per_weight))
        self.assertTrue(1.9 <= tried["alpha"] / tried["echo"] <= 2.1, (tried["alpha"], tried["echo"]))          # a topic of weight 10 and one of weight 5, two to one
        self.assertTrue(1.9 <= tried["bravo"] / tried["golf"] <= 2.1)
        topic_of = {r["id"]: r["topic"] for r in rows}
        first = {topic: min(day for day, i in self.fetch_days if topic_of[i] == topic) for topic in TOPICS}
        self.assertLessEqual(set(first.values()), {"2026-11-16", "2026-11-17"})                               # every topic had its first turn within two days (the weight-1 topics find a row only when a refill brings one)
        self.assertEqual({t for day, i in self.fetch_days if day == "2026-11-16" for t in [topic_of[i]] if t in TOPICS}, set(TOPICS) - {"india"})
        left = collections.Counter(r["topic"] for r in rows if r["status"] == "queued" and r["topic"] in TOPICS)
        for topic, weight in TOPICS.items():                                                                  # and none piled up unfetched: what is left of a topic is in proportion to its weight
            self.assertTrue(left[topic] / weight <= 1.5 * max(left[t] / w for t, w in TOPICS.items() if w >= 5) + 6, (topic, left))
        press = [r for r in rows if r["topic"] == "press"]
        self.assertEqual(collections.Counter(r["status"] for r in press), {"kept": FLOOD})                      # the flood of day 1 was taken in the end, a site's limit at a time

    def audit_the_lists(self):
        """The public lists are asked for at the first run that finds them 12 hours old, and again at each run while the last download failed; a failed download stopped no run."""
        for url in (PHISH_URL, chain.PSL_URL):
            stamps = [(t, failed) for u, t, failed in self.lists.stamps if u == url]
            attempts, failed_at = {t for t, _ in stamps}, {t for t, failed in stamps if failed}
            last, good = None, []
            for t in self.lists_runs:
                due = last is None or t - last >= datetime.timedelta(hours=12)
                self.assertEqual(t in attempts, due, (url, t))
                if t in attempts and t not in failed_at:
                    last = t
                    good.append(t)
            self.assertTrue(all(b - a >= datetime.timedelta(hours=12) for a, b in zip(good, good[1:])))
            self.assertTrue(22 <= len(good) <= 28, len(good))                                                  # about every 12 hours over 14 days, less the hours in which runs were refused
        self.assertEqual(len([1 for _u, _t, failed in self.lists.stamps if failed]), 4)                       # the day the download failed: four runs asked and failed
        self.assertEqual(self.tally[("list_update", "failed")], 4)

    def audit_the_sizes(self):
        """The files that a long span could grow are bounded, and the numbers are these."""
        folder = os.path.join(self.index, "crawl")
        logs = {name: os.path.getsize(os.path.join(folder, "log", name)) for name in os.listdir(os.path.join(folder, "log"))}
        self.assertEqual(len(logs), SPAN)                                                                      # one file a day
        self.assertLessEqual(max(logs.values()), 1_100_000)                                                    # the day of 96 runs and 400 fetches (958 KB when it was measured)
        self.assertLessEqual(sum(logs.values()), 3_200_000)                                                    # (2.85 MB over the span)
        quiet = [size for name, size in sorted(logs.items()) if name > "crawl-2026-11-25.jsonl"]
        self.assertTrue(len(quiet) == 4 and max(quiet) <= 8_000, quiet)                                       # a day on which nothing can be taken: two runs, a few lines each
        for name in logs:
            with open(os.path.join(folder, "log", name), "rb") as f:
                self.assertLessEqual(max(len(line) for line in f), crawllog.LINE_MAX)                       # a line is never longer than the log's own bound
        self.assertLessEqual(set(os.listdir(folder)), {"approved", "breaker.json", "guard.json", "lists", "log", "query-cache.json"})
        guard = os.path.join(folder, "guard.json")
        self.assertLessEqual(os.path.getsize(guard), 400)                                                      # (301 bytes)
        state = crawlguard.load_state(self.index)[0]
        self.assertEqual((len(state["history"]), state["entries_down"], state["model_down_since"]), (40, {}, None))      # the history is the last 40 fetches and no more
        self.assertLessEqual(os.path.getsize(os.path.join(folder, "breaker.json")), 200)
        per_day = collections.Counter(day for day, _key in self.counters())
        self.assertLessEqual(max(per_day.values()), 15)                                                        # the counters of a day: the day's two, a few sites, a refusal at most
        self.assertLessEqual(len(self.counters()), 120)
        self.assertLessEqual(self.max_queued, self.plan["queue_low"] - 1 + self.plan["discover_target"])       # a refill is made below `queue_low` and adds no more than `discover_target`
        self.assertLessEqual(self.count("SELECT MAX(c) FROM (SELECT COUNT(*) c FROM candidates WHERE status = 'queued' GROUP BY domain)"), self.plan["queued_per_domain"])
        self.assertLessEqual(self.count("SELECT COUNT(*) FROM candidates"), 2_000)                             # (1,661)
        self.assertEqual(self.count("SELECT COUNT(*) FROM candidates WHERE status = 'fetching'"), 0)

    def audit_the_books(self, owners, before):
        """The books stay on default and none is moved, no model of the chat kind was asked, and the owner's own books are as they were."""
        names = collections.Counter(e["event"] for entry in self.crawl_scan().entries for e in entry["events"] if isinstance(e, dict))
        for name in ("reshelved", "placement_proposed", "crawl_unplaced"):
            self.assertEqual(names[name], 0, name)
        self.assertEqual({self.shelf(book) for book in self.crawl_books_all()}, {"default"})
        self.assertEqual((self.prompts, [o for o in self.order if o[0] == "chat"]), ([], []))
        self.assertGreater(self.reasons[("propose", "skipped", crawlmove.MOVES_OFF)], 300)                      # the move step said so at each of its turns
        self.assertGreater(names["crawl_judged"], 1_100)
        self.assertEqual(self.owners_state(owners), before)
        self.assertEqual(self.store.read_book(owners[-1])["shelf"], "cloning")
        self.assertEqual(self.stalled_book_state(), "kept")

    def stalled_book_state(self):
        """The row of the fetch that was killed on day 7 was tried again after its wait and kept, and its page was asked for once."""
        row = self.row(self.stalled)
        self.assertEqual(self.requests().count(re.sub(r"^http://[^/]+", "", row["address"])), 1)
        return row["status"]

    def test_fourteen_simulated_days_on_one_library(self):
        owners = self.owners_books()
        before = self.owners_state(owners)
        self.day_1_the_ceilings()
        self.day_2_a_model_entry_down_for_13_hours()
        self.day_3_a_model_entry_down_for_8_hours()
        self.day_4_the_card_embedding_down_for_8_hours()
        self.day_5_the_card_embedding_down_for_13_hours()
        self.day_6_the_network_out()
        self.day_7_a_run_killed_at_each_step()
        self.day_8_a_quiet_day()
        self.day_9_the_lists_download_failing()
        self.day_10_filed_total()
        self.days_11_to_14_nothing_more_is_taken()
        self.assertEqual(self.runs[-1][0].date(), datetime.date(2026, 11, 29))
        self.audit_the_ceilings()
        self.audit_the_topics()
        self.audit_the_lists()
        self.audit_the_sizes()
        self.audit_the_books(owners, before)
        self.assert_nothing_half_made()
        self.no_duplicate_fetch()


if __name__ == "__main__":
    unittest.main()
