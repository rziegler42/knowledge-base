"""A soak of the unattended crawl: the real `crawlrun.run` with the real steps, over simulated days, one test method for each point, each on its own temporary library (`kb/crawlrun.py`; the plans
`2026-11-16-run-the-steps-of-the-unattended-crawl`, `2026-11-17-see-when-a-model-of-the-unattended-crawl-is-down` and the plans of the small gaps; `docs/specs/population.md`, "The crawl plan" and "Safeguards").

`test_crawlchain` runs the whole chain once, `test_crawldays` over three or four days. Here the injected clock is moved from run to run over days, as `crawlrun.default_steps` assembles the steps, and what the log, the queue, the counters,
the guard files and the library say is checked after every run. The plan is the soak's: `fetches_per_day 400`, `cards_per_day 400`, `filed_total 4500`, `batch 6`, `per_domain_per_day 150`, `queued_per_domain 400`, `queue_low 300`,
`discover_target 800`, `model_down_minutes 720`, `consecutive_failures 40`, `failure_share 0.8`, `window 40`, the moves off. (One class uses `cards_per_day 20`.)

**The methods** (each can be run alone: `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlsoak.TheModels.test_<name>`):
`TheCeilings` (a day of 96 runs), `TheCardCeiling` (a low `cards_per_day`), `TheModels` (an entry down 8 and 13 hours, the card embedding down 8 and 13 hours), `TheNetwork` (a short run of failures, the share rule, the run of 40), `TheKills` (a run
killed at each step), `TheStalledAndThePutOffHop` (a row left `fetching`, a hop put off at its limit), `TheLists` (the 12-hour refresh, a failed download), `TheFiledTotal` (4,500 books filed), `TheLongSpan` (the topics' turns, the sizes,
the owner's own books, over four days of a little over 1,000 fetches). Run the whole file with `-v --durations 0` to see the time of each.

**The cadence.** The real agent starts a run every 900 seconds (96 a day) and a run's budget is `RUN_SECONDS`. A run costs time in proportion to the crawl books in the library (the steps read every one of them, several times), so
a day of 96 runs is made once (`TheCeilings`); the windows in which a model is down are run **every hour**, which keeps the 720-minute rule exactly (the rule is on the clock and not on the number of runs: a run at 720 minutes exactly,
and one a minute after, are made); the outages are run every 15 minutes because their rules count fetches, not time.

**What stands in for the real thing** (all of it, as in `test_crawlchain` and `test_crawldays`, which this file reuses): the pages and hosts (the loopback server of `test_webclient` through the real shared client and the real capture);
the lists downloader (`test_crawllists.Fetch`); the sources of the refill (`Feed`: every search finds new addresses whose pages the fake server serves; the queue rows of the flood and of the hop are put in by SQL through
`Chain.add`, with a weight of 999,999 that takes the first turns of the day); the scan, the converter and the index (`test_crawlsteps`); the embedding and the chat models (the hooks of `test_placement`: the chat model is never asked, the
moves being off); **a model failure is a `KbError` ("the embedding model does not answer") raised by the embedding hook, and the entry probes and the card-embedding probe are injected functions**, so nothing shows how the real bridge fails;
**a network outage is an empty name table (no name resolves)**, so nothing shows a refused connection or a timeout; **the card step is the small fake of `test_crawlchain`**, not `crawlcards.step`; the free space is
injected; `shelfvectors.DEFAULT_SCHEMA` is patched and `weblists.MIN_ENTRIES` is lowered; **`os.fsync` does nothing** (a death here is an exception in the process, so what a disk keeps after a power cut is not shown; the writes of the
library, the guard files and the log are not synced, and on a disk where a sync is slow they were most of the run's system time). The visits of redirects to one site are made with the real `crawlstate.charge_hop`, and the books of the earlier weeks of `TheFiledTotal` are made with the real
`crawlbooks` functions. **The timestamps that the store puts on a book and its events come from the fixture's tick counter (seconds after 2026-11-16 12:00 UTC, counting calls), not from the simulated days**; the log lines, the queue rows, the
counters, the guard files and the breaker use the simulated clock, and nothing here shows what a book's own timestamps say. No request leaves the machine, no model is called, nothing reads the owner's config, plan, key, library or
shelves, and nothing sleeps.

**Two rules that the plan's numbers order.** With `failure_share 0.8` of a `window` of 40 (32), a full window of earlier successes trips the breaker at the **32nd** failure in a row, as `failure_share`, before `consecutive_failures 40` can: the run of
40 trips first only when the history is not full (a library at the start, or just after `crawlguard.clear`, which makes it empty). `TheNetwork` shows both, and a run of 30 that trips neither.

**What this file does not cover.** The first download of the public lists (a run with no copy is refused: `test_crawlchain`); the stop file and the run's time budget (`test_crawlchain`); a site's refusals (`test_crawldays`); a death before a page's payload is filed.
**The numbers of `TheLongSpan` (the sizes, the thresholds of the topics' share) were measured on this data on one machine and are fitted to it**; they are bounds with a margin, and a change of the fakes or of the plan's numbers moves them.

Run it with `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlsoak` (the other two files need the shell's umask to be 022, and this one does not)."""
import collections
import datetime
import json
import os
import unittest
from unittest import mock
from urllib.parse import urlsplit

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
FLOOD = 160                                             # candidates of one site, queued for the day of 96 runs
LIMIT = 150                                             # the plan's per_domain_per_day
RUN_MINUTES = 15
EDGE = "edge.test"                                      # the site that redirects lead to
FILED_TOTAL, BATCH = 4500, 6
SEED_RUN = "earlier-run"
PUT_OFF = "the site it leads to is at its limit for the day"


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
    """The library, the fakes and the helpers; it has no test of its own."""

    plan_text = PLAN_TEXT
    FLAKY = 0                                                  # every FLAKY-th page found always answers 500 (none, but in `TheLongSpan`: a few early failures would count in the small libraries' windows of 40)

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o077))        # before the library is made: the index folder must be one that only we can write, whatever the shell's umask
        super().setUp()
        patch = mock.patch.object(os, "fsync", lambda fd: None)                    # see the docstring: the syncs to the disk are not made
        patch.start()
        self.addCleanup(patch.stop)
        self.emb_up, self.outage, self.known = True, False, set()
        self.serial, self.flaky, self.repeatable = 0, set(), set()
        self.offsets, self.tally, self.reasons = {}, collections.Counter(), collections.Counter()
        self.order_ids, self.runs, self.lists_runs, self.fetch_days, self.captured = [], [], [], [], []
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

    def capture(self, library, ident, address, **kw):
        result = super().capture(library, ident, address, **kw)
        self.captured.append((urlsplit(address).path, result["status"]))          # (a capture that dies in its hook is not here)
        return result

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
            if self.FLAKY and k % self.FLAKY == 9:                          # a page that always answers 500: three tries, then the row is failed
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

    def hourly(self, day, start, stop):
        return self.every(day, start, stop, 60)

    def quiet(self, day, hours=(0, 6, 12, 18)):
        """Runs at these hours of the day."""
        return [self.play(at(day, hour)) for hour in hours]

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
            if line["step"] in ("fetch", "run_end", "refuse", "breaker", "stop", "propose", "card") and line["reason"]:
                self.reasons[(line["step"], line["outcome"], line["reason"])] += 1
        return new

    def db(self):
        """One read connection to the queue for the helpers of this file (they were opening one at each call)."""
        if getattr(self, "_db", None) is None:
            self._db = crawlqueue.connect(self.index)
            self.addCleanup(self._db.close)
        return self._db

    def count(self, sql, *args):
        return self.db().execute(sql, args).fetchone()[0]

    def counters(self):
        return {(day, key): n for day, key, n in self.db().execute("SELECT day, key, n FROM counters").fetchall()}

    def counters_of(self, day=None):
        found = self.counters()
        return found if day is None else {key: n for (found_day, key), n in found.items() if found_day == day}

    def after(self, code):
        """What holds after every run (and after one that was killed, `code` None): the run took no more than the batch; no ceiling of any day is passed; the counters of a day that is over are as they were."""
        plan = self.plan
        new = self.read_log()
        fetches = [l for l in new if l["step"] == "fetch" and l["candidate"] is not None]
        self.assertLessEqual(len(fetches), plan["batch"], self.now)
        self.order_ids += [l["candidate"] for l in fetches]
        self.fetch_days += [(self.now.date().isoformat(), l["candidate"]) for l in fetches]
        self.filed_seen += sum(1 for l in new if l["step"] == "capture" and l["outcome"] == "ok")
        self.assertLessEqual(self.filed_seen + self.seeded, plan["filed_total"], self.now)
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
            limit = plan["fetches_per_day"] if key == "fetch" else plan["cards_per_day"] if key == "card" else plan["per_domain_per_day"] if key.startswith(("fetch:", "hop:")) else None
            if limit is not None:
                self.assertLessEqual(n, limit, f"the counter {key} of the day {day} is over its ceiling")
        self.snapshot = found
        self.runs.append((self.now, code))
        self.max_queued = max(self.max_queued, self.count("SELECT COUNT(*) FROM candidates WHERE status = 'queued'"))

    # -- what a method reads
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
        return [e["id"] for e in self.crawl_scan().entries if e["state"] == "active" and not any(isinstance(x, dict) and x.get("event") in ("crawl_judged", *crawlbooks.TERMINAL) for x in e["events"])]

    def no_duplicate_fetch(self):
        again = {p: c for p, c in collections.Counter(self.requests()).items() if c > 1 and p not in self.repeatable}
        self.assertEqual(again, {}, "a page that was served was fetched again")

    def refused_runs_change_nothing(self, times, code):
        """Each of these runs ends with `code`, and none makes a request, takes a candidate or changes a counter."""
        before = (len(self.requests()), self.rows(), self.counters())
        for now in times:
            self.assertEqual(self.play(now), code, now)
        self.assertEqual((len(self.requests()), self.rows(), self.counters()), before)

    def failed_fetches(self):
        return self.tally[("fetch", "failed")]

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

    def seed_filed(self, count):
        """Books of earlier weeks, as small as the point allows: a book of the crawl, found and left on default (`crawl_unplaced`, which is terminal, so no step takes it up), and no more."""
        for n in range(count):
            book = self.store.create_book(title=f"Earlier {n:05d}", kind="webpage", auto_filed=True)
            crawlbooks.record_found(self.store, book, candidate=900_000 + n, source="openalex", found_from=None, topic="alpha", run=SEED_RUN, plan_digest=self.digest)
            crawlbooks.record_unplaced(self.store, book, "an earlier book")
        self.seeded += count

    def fingerprint(self):
        """Everything that grows when the crawl takes in a book."""
        scan = self.crawl_scan()
        return {"books": len(self.store.list_books()), "filed": crawlbooks.filed_count(self.store, scan), "events": sum(len(e["events"]) for e in scan.entries), "requests": len(self.requests()),
                "tried": self.count("SELECT COUNT(*) FROM candidates WHERE tries > 0"), "fetched": self.count("SELECT COALESCE(SUM(n), 0) FROM counters WHERE key = 'fetch'"), "rows": self.count("SELECT COUNT(*) FROM candidates")}

    def hopper_and_charge(self):
        """A candidate whose redirect leads to a site that is at its limit for the day (made so with the real counter)."""
        self.hopper, title = self.add("/doi/limit", host="doi.test", route=False, topic="doi", weight=999_999)         # (the weight makes it the first row taken, each time it is due)
        self.host_dns(EDGE)
        self.srv.routes["/doi/limit"] = days.redirect(f"http://{EDGE}/paper")
        self.srv.routes["/paper"] = chain.reply(200, body=chain.page(title))
        self.repeatable.add("/doi/limit")
        conn = self.conn()
        for _ in range(LIMIT):
            self.assertEqual(crawlstate.charge_hop(conn, self.plan, at(1, 0, 0), EDGE), "")

    def flood(self):
        """One site with more candidates than its limit."""
        for n in range(FLOOD):
            self.add(f"/press/{n:03d}", host="press.test", topic="press", weight=999_999, target="gene-editing")


class TheCeilings(Soak):
    def test_a_day_of_96_runs_reaches_the_ceilings_and_passes_none_and_a_finished_days_counters_never_change(self):
        """The real agent's day: a run every 15 minutes. The day's fetches, the site's own fetches (one site with more candidates than its limit) and the visits to a site by redirects reach their ceilings and are not passed;
        the cards stay within theirs; a day that is over keeps its counters when the next day's runs go on."""
        self.flood()
        self.hopper_and_charge()
        for now in self.every(1, (0, 0), (24, 0)):
            self.assertEqual(self.play(now), 0, now)
        today = self.counters_of("2026-11-16")
        self.assertEqual((today["fetch"], today["fetch:press.test"], today[f"hop:{EDGE}"]), (400, LIMIT, LIMIT))       # three ceilings were reached, and none was passed (`after` checked every run)
        self.assertLessEqual(today["card"], 400)
        self.assertEqual(len(self.runs), 96)
        self.assertIn(("fetch", "skipped", "fetches_per_day reached: no new candidates today"), {(s, o, r) for s, o, r in self.reasons})
        press = [r for r in self.rows() if r["topic"] == "press"]
        self.assertEqual(sorted(collections.Counter(r["status"] for r in press).items()), [("kept", LIMIT), ("queued", FLOOD - LIMIT)])       # the 150 within the limit, the rest waiting for the next day
        self.assertNotIn("/paper", self.requests())                                                          # the redirect to the site at its limit was never followed
        self.assert_nothing_half_made()
        self.no_duplicate_fetch()
        for now in (at(2, 0, 0), at(2, 12, 0)):                                                              # the next day: a fresh count, and the first day as it was
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.counters_of("2026-11-16"), today)
        self.assertEqual(self.closed["2026-11-16"], today)
        self.assertEqual(self.counters_of("2026-11-17")["fetch"], 2 * BATCH)
        self.assertEqual(self.counters_of("2026-11-17")["fetch:press.test"], FLOOD - LIMIT)                  # the rest of the flood is taken on the new day, up to the limit again


class LowCards(Soak):
    plan_text = PLAN_TEXT.replace("cards_per_day = 400", "cards_per_day = 20")


class TheCardCeiling(LowCards):
    def test_a_low_cards_per_day_is_reached_and_not_passed_and_the_waiting_books_are_carded_the_next_day_oldest_first(self):
        """With `cards_per_day 400` the ceiling cannot bind (a book is carded after it is fetched and judged, and the day's fetches are 400 at most), so the soak's own plan shows only that it is not passed. Here it is 20."""
        for now in self.hourly(1, (0, 0), (10, 0)):
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.counters_of("2026-11-16")["card"], 20)                                         # reached, and never 21 (`after` checked every run)
        self.assertGreater(self.reasons[("card", "skipped", "cards_per_day reached")], 0)
        waiting = [e["id"] for e in self.crawl_scan().entries if any(x.get("event") == "crawl_judged" and x.get("ok") is True for x in e["events"])
                   and not card.generations(self.store, e["id"], self.store.read_book(e["id"])["current_version"])]
        self.assertGreater(len(waiting), 10)
        carded = [b for kind, b in self.order if kind == "card"]
        self.assertEqual(len(carded), 20)
        for now in (at(2, 0, 0), at(2, 6, 0)):
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.counters_of("2026-11-17")["card"], 20)
        self.assertEqual(self.counters_of("2026-11-16")["card"], 20)                                         # the first day as it was
        all_carded = [b for kind, b in self.order if kind == "card"]
        self.assertEqual(all_carded[:20], carded)
        self.assertEqual(all_carded[20:40], waiting[:20])                                                    # the next day's cards go to the books that waited longest
        self.assertEqual(len(set(all_carded)), len(all_carded))                                              # none is carded twice


class TheModels(Soak):
    def test_a_model_entry_down_for_8_hours_costs_no_book_a_try_and_trips_nothing_and_the_waiting_books_are_judged_when_it_answers(self):
        """The entry of the judgement's embedding (`place-embed`; the chat entry is never asked, the moves being off) stops answering at 08:00 and answers again at 16:00: down for 480 minutes, under the limit of 720."""
        self.quiet(1, hours=(0, 6))
        self.emb_up = False
        judged, failed, down = self.judged(), self.step_failed(), {"emb": "2026-11-16T08:00:00Z"}
        for now in self.hourly(1, (8, 0), (16, 0)):
            self.assertEqual(self.play(now), 0, now)
            self.assertEqual(self.entries_down(), down, now)                                                 # the clock keeps its first time, run after run
            self.assertFalse(self.breaker()["tripped"], now)
        self.assertEqual((self.judged(), self.step_failed()), (judged, failed))                              # nothing was judged, and no book was charged a try
        waiting = len(self.unjudged())
        self.assertGreaterEqual(waiting, 40)
        self.emb_up = True
        self.assertEqual(self.play(at(1, 16, 0)), 0)
        self.assertEqual((self.entries_down(), self.unjudged()), ({}, []))
        self.assertGreaterEqual(self.judged(), judged + waiting)
        self.assertEqual(self.step_failed(), failed)
        self.assertGreater(self.reasons[("breaker", "ok", "the model entry emb answers again")], 0)
        self.assertEqual({r["tries"] for r in self.rows() if r["status"] == "kept"}, {1})                    # every kept candidate was taken once

    def test_a_model_entry_down_for_13_hours_trips_at_the_limit_and_the_runs_are_refused_until_the_owner_clears(self):
        self.quiet(1, hours=(0, 1))
        self.emb_up = False
        judged, down = self.judged(), {"emb": "2026-11-16T02:00:00Z"}
        for now in self.hourly(1, (2, 0), (14, 1)):                                                          # to 14:00, which is down for exactly 720 minutes
            self.assertEqual(self.play(now), 0, now)
            self.assertEqual(self.entries_down(), down, now)
            self.assertFalse(self.breaker()["tripped"], now)
        self.assertEqual((self.judged(), self.step_failed()), (judged, 0))
        self.assertGreater(len(self.unjudged()), 60)
        sent, fetched = len(self.requests()), self.counters_of("2026-11-16")["fetch"]
        self.assertEqual(self.play(at(1, 14, 1)), 4)                                                         # a minute longer than the limit
        self.assertEqual([l["step"] for l in self.last if l["step"] in ("run_start", "fetch")], [])          # the trip was made by the probe at the start of the run, before any step: nothing was begun,
        self.assertEqual((len(self.requests()), self.counters_of("2026-11-16")["fetch"]), (sent, fetched))   # fetched or counted
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn("the model entry emb has not answered for over 720 minutes", breaker["reason"])
        asked = len(self.entry_calls)
        self.refused_runs_change_nothing([at(1, 14, 30)], 4)
        self.emb_up = True                                                                                   # the model is back, and the runs are refused until the owner clears the breaker
        self.refused_runs_change_nothing(self.hourly(1, (15, 0), (17, 0)), 4)
        self.assertEqual(len(self.entry_calls), asked)                                                       # not even a probe was made
        self.assertEqual(self.step_failed(), 0)
        self.clear_breaker(at(1, 17, 0))
        self.assertEqual(self.play(at(1, 18, 0)), 0)
        self.assertEqual((self.entries_down(), self.unjudged()), ({}, []))                                   # the waiting books were judged by the first run
        self.assertEqual(self.step_failed(), 0)
        self.assert_nothing_half_made()

    def test_the_card_embedding_down_for_8_hours_refuses_each_run_with_exit_3_and_trips_nothing(self):
        """The card embedding is the probe at the start of a run."""
        self.quiet(1, hours=(0, 3))
        self.up = False
        probes = self.probes
        self.refused_runs_change_nothing(self.hourly(1, (6, 0), (14, 0)), 3)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-16T06:00:00Z")
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(self.probes - probes, 8)                                                            # one probe in each run, and nothing else was asked of any model
        self.assertIn("the model server does not answer", self.err[-1])
        self.up = True
        self.assertEqual(self.play(at(1, 14, 0)), 0)
        self.assertIsNone(crawlguard.load_state(self.index)[0]["model_down_since"])

    def test_the_card_embedding_down_for_13_hours_trips_at_the_limit_and_the_runs_are_refused_until_the_owner_clears(self):
        self.quiet(1, hours=(0,))
        self.up = False
        for now in self.hourly(1, (2, 0), (14, 1)):                                                          # to 14:00: 720 minutes exactly
            self.assertEqual(self.play(now), 3, now)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-16T02:00:00Z")
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(self.play(at(1, 14, 1)), 4)
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn("the model server has not answered for over 720 minutes", breaker["reason"])
        probes = self.probes
        self.up = True
        self.refused_runs_change_nothing(self.hourly(1, (15, 0), (17, 0)), 4)
        self.assertEqual(self.probes, probes)                                                                # refused before the probe
        self.clear_breaker(at(1, 17, 0))
        self.assertEqual(self.play(at(1, 18, 0)), 0)
        self.assertIsNone(crawlguard.load_state(self.index)[0]["model_down_since"])


class TheNetwork(Soak):
    def test_a_run_of_failures_shorter_than_the_limit_trips_nothing(self):
        for now in self.every(1, (0, 0), (2, 0)):                                                            # a history of 48 fetches that worked
            self.assertEqual(self.play(now), 0, now)
        self.set_outage(True)
        before = self.failed_fetches()
        for now in self.every(1, (2, 0), (3, 15)):                                                           # five runs: 30 failures in a row (the window of 40 holds 30 of them: 0.75, under 0.8)
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.failed_fetches() - before, 30)
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"].count(False), 30)
        self.set_outage(False)
        for now in self.every(1, (3, 15), (5, 15)):
            self.assertEqual(self.play(now), 0, now)
        self.assertFalse(self.breaker()["tripped"])
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"].count(False), 0)                    # the failures have left the window

    def test_an_outage_that_finds_the_window_full_trips_the_share_rule_at_the_32nd_failure_and_stays_tripped_until_the_owner_clears(self):
        for now in self.every(1, (0, 0), (2, 0)):
            self.assertEqual(self.play(now), 0, now)
        self.set_outage(True)
        before = self.failed_fetches()
        times = list(self.every(1, (2, 0), (4, 0)))
        codes = [self.play(now) for now in times]
        self.assertEqual(codes[:5], [0] * 5)
        self.assertEqual(codes[5], 4)                                                                        # the 6th run: the 32nd failure in a row, with the window full
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "failure_share"))
        self.assertIn("32 of the last 40 fetches failed", breaker["reason"])
        self.assertIn(self.failed_fetches() - before, (31, 32))                                              # (a failed page of the earlier runs may still be in the window)
        self.assertTrue(all(code == 4 for code in codes[5:]))                                                # and every later run was refused
        self.set_outage(False)
        self.refused_runs_change_nothing(self.every(1, (4, 0), (4, 30)), 4)
        self.clear_breaker(at(1, 4, 30))
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [])                                # a clear is a fresh start
        self.assertEqual(self.play(at(1, 4, 45)), 0)

    def test_an_outage_that_finds_the_history_empty_trips_on_the_run_of_40_at_the_40th_failure(self):
        """A library at its start, or one that was just cleared, has no history: the share rule needs a full window, and the run of 40 comes first."""
        self.set_outage(True)
        before = self.failed_fetches()
        times = list(self.every(1, (0, 0), (2, 0)))
        codes = [self.play(now) for now in times]
        self.assertEqual(codes[:6], [0] * 6)
        self.assertEqual(codes[6], 4)                                                                        # 36 failures in six runs, and the 40th in the seventh
        breaker = self.breaker()
        self.assertEqual((breaker["tripped"], breaker["kind"], breaker["reason"]), (True, "consecutive_failures", "40 fetches in a row failed"))
        self.assertEqual(self.failed_fetches() - before, 40)
        self.assertTrue(all(code == 4 for code in codes[6:]))
        self.set_outage(False)
        self.clear_breaker(at(1, 2, 0))
        self.assertEqual(self.play(at(1, 2, 15)), 0)


class TheKills(Soak):
    KILLS = ("lists", "refill", "capture", "scan", "convert", "index", "embed", "card")

    def test_a_run_killed_at_each_step_is_finished_by_the_next_with_nothing_fetched_twice_nothing_half_made_and_no_ceiling_passed(self):
        """A death at each point of a run (the fetch's own capture, the scan, the convert, the index, the judge's model call and the card are the fakes of `test_crawlchain`; the lists and the refill are the two points before them), one an hour, and
        the next run, half an hour after, finishes what it left."""
        self.quiet(1, hours=(0,))
        for n, point in enumerate(self.KILLS):
            self.die_at(point)
            then = at(1, 2 + n, 0)
            with self.assertRaises(chain.Boom):
                self.go(now=then)
            self.after(None)
            crawlguard.acquire_run_lock(self.index, now=then).release()                                      # the lock was let go
            dead = [r["id"] for r in self.rows() if r["status"] == "fetching"]                              # the row of a fetch that was going when the run died is left `fetching`
            self.assertEqual(len(dead), 1 if point == "capture" else 0, point)
            self.assertEqual(self.play(at(1, 2 + n, 31)), 0, point)
            if n < self.KILLS.index("capture"):                                                             # (from the dead capture on, its book is an active orphan until its row is tried again after its wait: see the end, and `TheStalledAndThePutOffHop`)
                self.assert_nothing_half_made()
            self.assertEqual(self.unjudged(), [], point)
            self.no_duplicate_fetch()
            self.assertFalse(self.breaker()["tripped"])
        for n in range(10):                                                                                  # the row of the dead capture is tried again, and then nothing is half made
            if not [b for b in self.crawl_books_all() if "crawl_found" not in self.names(b) and self.store.read_book(b)["state"] == "active"]:
                break
            self.assertEqual(self.play(at(1, 12 + n, 31)), 0)
        self.assert_nothing_half_made()
        self.assertEqual(self.unjudged(), [])
        scan = self.crawl_scan()
        again = [c for c, n in collections.Counter(e["found"]["candidate"] for e in scan.entries).items() if n > 1]
        self.assertEqual(again, [])                                                                          # no candidate was filed as two books


class TheStalledAndThePutOffHop(Soak):
    def test_a_row_left_fetching_by_a_dead_run_is_queued_again_and_tried_again_and_its_page_is_not_fetched_twice(self):
        """Why "nothing fetched twice" holds for a run killed after its capture: the capture had filed the book (an active book with its payload, and no `crawl_found`) before it died. The retry's capture finds that book through the
        library's own identity check and answers `held` (a book that is there and whose page is fetched: `capture_url.capture` returns before it asks the server), so the page is not asked of the server again, and the retry adopts the book
        (it gets its one `crawl_found`). The test shows each part."""
        self.quiet(1, hours=(0,))
        self.die_at("capture")
        with self.assertRaises(chain.Boom):
            self.go(now=at(1, 1, 0))
        self.after(None)
        (dead,) = [r for r in self.rows() if r["status"] == "fetching"]
        path = urlsplit(dead["address"]).path
        (orphan,) = [b for b in self.crawl_books_all() if "crawl_found" not in self.names(b)]
        self.assertEqual(self.store.read_book(orphan)["state"], "active")
        self.assertEqual(self.requests().count(path), 1)                                                     # the dead run asked for the page once
        self.assertEqual(self.play(at(1, 1, 31)), 0)
        self.assertEqual([(l["outcome"], l["reason"]) for l in self.last if l["step"] == "fail"], [("ok", "1 stalled rows queued again, 0 given up")])
        row = self.row(dead["id"])
        self.assertEqual((row["status"], row["tries"], row["reason"], row["book_id"]), ("queued", dead["tries"], "stalled for over 30 minutes", None))
        self.assertEqual(row["next_try"], "2026-11-16T02:31:00Z")                                            # one hour after the sweep
        self.assertNotIn(path, [p for p, _s in self.captured])
        for n in range(10):                                                                                  # tried again, at the run of its turn after its wait
            self.assertEqual(self.play(at(1, 2 + n, 31)), 0)
            if self.row(dead["id"])["status"] == "kept":
                break
        row = self.row(dead["id"])
        self.assertEqual((row["status"], row["book_id"]), ("kept", orphan))                                  # it adopted the book that the dead run had filed
        self.assertEqual(self.requests().count(path), 1)                                                     # and the server was not asked again
        self.assertEqual([s for p, s in self.captured if p == path], ["held"])                               # because the library's identity check found the book, with its page fetched
        self.assertEqual(len(self.events(orphan, "crawl_found")), 1)
        self.assert_nothing_half_made()
        self.no_duplicate_fetch()

    def test_a_hop_put_off_at_its_limit_counts_a_try_waits_a_day_charges_no_site_and_is_taken_the_next_day(self):
        """**The behaviour since the put-off hop was made to wait a day:** a candidate whose redirect leads to a site that is at its limit for the day is put off; its try is **counted** (`tries` 1, and the unit that `reserve` took for the
        redirector's own page stays), it **waits 24 hours** (the limited site's day will have ended), **no site is charged** (no refusal is counted for the redirector or for the site it led to), and on the next day, when the
        site's hop count is fresh, it is taken and kept. (Before, it waited 1 and then 6 hours and was failed at `retries` inside the day.) A change of any of these must change this test."""
        self.hopper_and_charge()
        for now in self.hourly(1, (0, 0), (24, 0)):
            self.assertEqual(self.play(now), 0, now)
        row = self.row(self.hopper)
        self.assertEqual((row["status"], row["tries"], row["reason"], row["book_id"]), ("queued", 1, PUT_OFF, None))
        self.assertEqual(row["next_try"], "2026-11-17T00:00:00Z")                                            # a day after the try
        self.assertEqual(self.requests().count("/doi/limit"), 1)                                             # one try the whole day: it was not asked again at the hours after
        self.assertNotIn("/paper", self.requests())
        today = self.counters_of("2026-11-16")
        self.assertEqual((today["fetch:doi.test"], today[f"hop:{EDGE}"]), (1, LIMIT))                       # the unit of its own page was taken, and no hop of the limited site was
        self.assertEqual([key for key in today if key.startswith("refusal:")], [])                           # no site was charged a refusal
        self.assertEqual(self.play(at(2, 0, 0)), 0)
        row = self.row(self.hopper)
        self.assertEqual((row["status"], row["tries"]), ("kept", 2))                                         # taken on the next day, and kept
        self.assertIsNotNone(row["book_id"])
        self.assertEqual(self.requests().count("/paper"), 1)
        self.assertEqual(self.counters_of("2026-11-17")[f"hop:{EDGE}"], 1)                                   # that day's count of the site, fresh
        self.assertEqual(self.counters_of("2026-11-16"), today)                                              # and the first day as it was


class TheLists(Soak):
    def test_the_lists_are_asked_for_at_the_first_run_after_12_hours_and_a_failed_download_stops_no_run(self):
        """The public lists are due every 12 hours; a download that fails does not stop a run while the last copy stands (the runs go on and fetch), and is asked again at each later run until one works. (The first download ever, with
        no copy, is `test_crawlchain`'s: the run is refused.)"""
        for now in self.every(1, (0, 0), (24, 0), 120):
            self.assertEqual(self.play(now), 0, now)
        self.lists.failing = {PHISH_URL}
        self.lists.replies[PHISH_URL] = webclient.FetchError("the list server does not answer")
        fetched = self.counters_of("2026-11-17").get("fetch", 0)
        for now in self.every(2, (0, 0), (24, 0), 120):
            self.assertEqual(self.play(now), 0, now)
        self.assertEqual(self.tally[("list_update", "failed")], 12)                                          # asked at each of the day's 12 runs (it was due at all of them), and failed
        self.assertEqual(self.counters_of("2026-11-17")["fetch"] - fetched, 12 * BATCH)                      # and every run fetched its batch
        self.lists.failing = set()
        self.lists.replies[PHISH_URL] = self.phish_reply
        for now in self.every(3, (0, 0), (24, 0), 120):
            self.assertEqual(self.play(now), 0, now)
        for url in (PHISH_URL, chain.PSL_URL):
            stamps = [(t, failed) for u, t, failed in self.lists.stamps if u == url]
            attempts, failed_at = {t for t, _ in stamps}, {t for t, failed in stamps if failed}
            last, good = None, []
            for t in self.lists_runs:
                due = last is None or t - last >= datetime.timedelta(hours=12)
                self.assertEqual(t in attempts, due, (url, t))                                               # asked at the run that finds it due, and at no other
                if t in attempts and t not in failed_at:
                    last = t
                    good.append(t)
            self.assertTrue(all(b - a >= datetime.timedelta(hours=12) for a, b in zip(good, good[1:])))
            self.assertEqual(len(good), 4 if url == PHISH_URL else 6, (url, good))                           # twice a day: but none of the list that failed on the day it failed
        self.assertEqual(len([1 for _u, _t, failed in self.lists.stamps if failed]), self.tally[("list_update", "failed")])


class TheFiledTotal(Soak):
    def test_filed_total_stops_fetching_at_4500_and_nothing_else_grows_after_it(self):
        """The library is given the books of the earlier weeks up to nine short of `filed_total`, as small as the point allows (found, and left on default): the first run takes six, the next takes three and stops at 4,500, and nothing
        is taken on the days after."""
        self.play(at(1, 0, 0))
        self.seed_filed(FILED_TOTAL - 9 - crawlbooks.filed_count(self.store))
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL - 9)
        self.assertEqual(self.play(at(1, 6, 0)), 0)
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL - 3)
        self.assertEqual(self.play(at(1, 6, 15)), 0)
        self.assertEqual(crawlbooks.filed_count(self.store), FILED_TOTAL)                                    # the third book of the second run was the 4,500th
        self.assertIn(("fetch", "skipped", "filed_total reached: no new books"), {(s, o, r) for s, o, r in self.reasons})
        self.assertEqual(self.play(at(1, 6, 30)), 0)                                                         # the run that finishes the last books
        done = self.fingerprint()
        self.assertEqual(done["filed"], FILED_TOTAL)
        self.assertEqual(self.unjudged(), [])
        fetched = self.counters_of("2026-11-16")["fetch"]
        for day in (2, 3, 4):
            self.assertEqual(self.play(at(day, 12, 0)), 0)
            self.assertEqual(self.fingerprint(), done)                                                       # no book, no event, no request, no candidate tried, no fetch counted
            self.assertEqual(self.counters_of(f"2026-11-{15 + day}").get("fetch", 0), 0)
        self.assertEqual(self.counters_of("2026-11-16")["fetch"], fetched)


class TheLongSpan(Soak):
    DAYS = 4
    FLAKY = 47

    def test_the_topics_get_their_turns_in_proportion_to_their_weights_the_files_stay_bounded_and_the_owners_books_are_untouched(self):
        """Four days of a run every 20 minutes from 00:00 to 14:00 (42 runs, about 250 fetches a day, a little over 1,000 in all), with the owner's own books in the library. Slow: the steps read every crawl book several times."""
        owners = self.owners_books()
        before = self.owners_state(owners)
        for day in range(1, self.DAYS + 1):
            for now in self.every(day, (0, 0), (14, 0), 20):
                self.assertEqual(self.play(now), 0, now)
        self.assertEqual(len(self.runs), 42 * self.DAYS)
        for day, last in self.closed.items():
            self.assertEqual(self.counters_of(day), last, day)                                               # a day that is over was not changed by the days after it
        self.audit_the_topics()
        self.audit_the_sizes()
        self.audit_the_books(owners, before)
        self.assert_nothing_half_made()
        self.no_duplicate_fetch()

    def audit_the_topics(self):
        """The turns follow the weights. **The thresholds are fitted to one measured run** (alpha to delta 170 tries a topic, echo to golf 85, hotel and india 17, out of 252 fetches a day for four days; what was left in the queue was in the same proportion): each topic's tries per unit of weight is within 10% of the mean of the others', a topic of weight 10 and one of weight 5 are between 1.9 to 1 and 2.1 to 1, and no topic has more than twice (and 3
        rows) of what the others leave unfetched for their weight."""
        rows = self.rows()
        tried = collections.Counter(r["topic"] for r in rows if r["tries"] > 0)
        per_weight = {topic: tried[topic] / weight for topic, weight in TOPICS.items()}
        for topic, value in per_weight.items():
            others = [v for t, v in per_weight.items() if t != topic]
            mean = sum(others) / len(others)
            self.assertTrue(0.9 * mean <= value <= 1.1 * mean, (topic, tried, per_weight))                  # each against the others, not against a mean that holds itself
        self.assertTrue(1.9 <= tried["alpha"] / tried["echo"] <= 2.1, (tried["alpha"], tried["echo"]))      # a topic of weight 10 and one of weight 5, two to one
        self.assertTrue(1.9 <= tried["bravo"] / tried["golf"] <= 2.1)
        self.assertGreater(tried["hotel"] + tried["india"], 10)                                              # the weight-1 topics were served, from the rows that a refill brought them
        left = collections.Counter(r["topic"] for r in rows if r["status"] == "queued" and r["topic"] in TOPICS)
        for topic, weight in TOPICS.items():                                                                 # none piled up unfetched: what is left of a topic, for its weight, against the others'
            others = sorted(left[t] / w for t, w in TOPICS.items() if t != topic)
            median = others[len(others) // 2]
            self.assertLessEqual(left[topic] / weight, 2 * median + 3, (topic, left))
        topic_of = {r["id"]: r["topic"] for r in rows}
        first = {topic: min(day for day, i in self.fetch_days if topic_of[i] == topic) for topic in TOPICS}
        self.assertLessEqual(set(first.values()), {"2026-11-16", "2026-11-17"})                              # every topic had its first turn within two days (a weight-1 topic finds a row only when a refill brings one)

    def audit_the_sizes(self):
        """The files that a long span could grow are bounded. **The numbers are measured on this data** (a day of 42 runs and 252 fetches: a log of 0.52 to 0.59 MB, 2.15 MB for the four days; 892 books judged; 40 counters; at most 593 rows queued;
        1,500 rows), with a margin, and move with the fakes."""
        folder = os.path.join(self.index, "crawl")
        logs = {name: os.path.getsize(os.path.join(folder, "log", name)) for name in os.listdir(os.path.join(folder, "log"))}
        self.assertEqual(len(logs), self.DAYS)                                                               # one file a day
        self.assertLessEqual(max(logs.values()), MAX_LOG_DAY)
        self.assertLessEqual(sum(logs.values()), MAX_LOG_SPAN)
        for name in logs:
            with open(os.path.join(folder, "log", name), "rb") as f:
                self.assertLessEqual(max(len(line) for line in f), crawllog.LINE_MAX)                       # a line is never longer than the log's own bound
        self.assertLessEqual(set(os.listdir(folder)), {"approved", "breaker.json", "guard.json", "lists", "log", "query-cache.json"})
        self.assertLessEqual(os.path.getsize(os.path.join(folder, "guard.json")), 400)
        state = crawlguard.load_state(self.index)[0]
        self.assertEqual((len(state["history"]), state["entries_down"], state["model_down_since"]), (40, {}, None))      # the history is the last 40 fetches and no more
        self.assertLessEqual(os.path.getsize(os.path.join(folder, "breaker.json")), 200)
        per_day = collections.Counter(day for day, _key in self.counters())
        self.assertLessEqual(max(per_day.values()), 15)                                                      # the counters of a day: the day's two, a few sites
        self.assertLessEqual(len(self.counters()), 15 * self.DAYS)
        self.assertLessEqual(self.max_queued, self.plan["queue_low"] - 1 + self.plan["discover_target"])     # a refill is made below `queue_low` and adds no more than `discover_target`
        self.assertLessEqual(self.count("SELECT MAX(c) FROM (SELECT COUNT(*) c FROM candidates WHERE status = 'queued' GROUP BY domain)"), self.plan["queued_per_domain"])
        self.assertLessEqual(self.count("SELECT COUNT(*) FROM candidates"), 2_000)
        self.assertEqual(self.count("SELECT COUNT(*) FROM candidates WHERE status = 'fetching'"), 0)

    def audit_the_books(self, owners, before):
        """The books stay on default and none is moved, no model of the chat kind was asked, and the owner's own books are as they were."""
        entries = self.crawl_scan().entries
        names = collections.Counter(e["event"] for entry in entries for e in entry["events"] if isinstance(e, dict))
        for name in ("reshelved", "placement_proposed", "crawl_unplaced"):
            self.assertEqual(names[name], 0, name)
        self.assertEqual({self.shelf(book) for book in self.crawl_books_all()}, {"default"})
        self.assertEqual((self.prompts, [o for o in self.order if o[0] == "chat"]), ([], []))
        self.assertGreater(self.reasons[("propose", "skipped", crawlmove.MOVES_OFF)], 100)                   # the move step said so at each of its turns
        judged = sum(1 for entry in entries if entry["found"].get("run") != SEED_RUN for e in entry["events"] if isinstance(e, dict) and e.get("event") == "crawl_judged")
        self.assertGreater(judged, MIN_JUDGED)                                                               # (the books that were given as seeds, if any, are not counted; there are none here)
        self.assertEqual(self.owners_state(owners), before)
        self.assertEqual(self.store.read_book(owners[-1])["shelf"], "cloning")


MAX_LOG_DAY, MAX_LOG_SPAN, MIN_JUDGED = 900_000, 3_000_000, 800                # bounds with a margin over what `TheLongSpan` measured on this data (593 KB, 2.15 MB, 892)


if __name__ == "__main__":
    unittest.main()
