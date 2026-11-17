"""The per-day rules of the unattended crawl, shown across several simulated days (`docs/specs/population.md`, "The crawl plan" and "Safeguards"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

`test_crawlchain` runs the whole chain in one day at a time; the unit tests of `crawlstate` and `crawlguard` run each rule on its own. These tests run **the real `crawlrun.run` chain**, as `crawlrun.default_steps`
assembles it, on one temporary library **over three or four days**: the injected `now` is moved forward between the runs, with several runs a day, and every rule is shown by what the log, the queue, the counters
and the readers (`crawlstatus.status`, `crawlreport.build`) say after each run.

It reuses the fixtures of `test_crawlchain` (`Chain`: the library, the fake page server, the approved plan, the real steps and the fakes of the scan, the converter, the index and the models, and the injected clock).
The one change is that a run is given an `entry_probe`, so that a model entry found down can be followed from run to run. Every outside thing is a fake, as there: the pages come from the loopback server
of `test_webclient` through the real shared client and the real capture; **the card step is a small fake** that uses `crawlstate.reserve_card` (`Chain.card_step`); the scan, the converter, the index, the embedding
and chat models and the lists are fakes; the model probe and the free space are injected. No request leaves the machine, no model is called, nothing reads the owner's config, plan, key, library or shelves, and nothing
sleeps. Run them with `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawldays`."""
import datetime
import os
import re
from urllib.parse import urlsplit

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests import test_crawlchain as chain
from engine.tests.test_webclient import redirect, reply

from kb import crawlbooks, crawlfetch, crawlguard, crawlplan, crawlreport, crawlrun, crawlstate, crawlstatus, store

UTC = datetime.timezone.utc
DAYS = {1: "2026-11-16", 2: "2026-11-17", 3: "2026-11-18", 4: "2026-11-19"}
# the plan of `test_crawlchain`, with the breaker out of the way (a failed fetch is the subject of some tests, and three in a row would trip it), and the keys these tests set
BASE = (chain.PLAN_TEXT.replace("consecutive_failures = 3", "consecutive_failures = 1000")
        .replace("model_down_minutes = 30\n", "model_down_minutes = 30\nwindow = 1000\ndomain_refusals = 3\n"))


def at(day, hour=9, minute=0):
    """A moment of the simulated day 1 (2026-11-16), 2, 3 or 4, in UTC."""
    return datetime.datetime(2026, 11, 15 + day, hour, minute, tzinfo=UTC)


def days_plan(**keys):
    """The text of a plan with these keys set (each key must be one the base text has)."""
    text = BASE
    for key, value in keys.items():
        text, found = re.subn(rf"(?m)^{key} = .*$", f"{key} = {value}", text)
        assert found == 1, key
    return text


class Days(chain.Chain):
    """`Chain`, with the helpers of a test that goes over several days."""

    def setUp(self):
        super().setUp()
        self.entry_answers, self.entry_calls = {}, []                               # task -> whether the entry answers (default: it does); the tasks asked
        self.titles = {}

    # -- the run
    def entry_probe(self, cfg, task):
        self.entry_calls.append(task)
        return self.entry_answers.get(task, True)

    def go(self, now=None, steps=None, dry_run=False, probe=None, statvfs=None, prefix=None):
        """`Chain.go`, and the `entry_probe` of this test."""
        if now is not None:
            self.now = now
        self.out, self.err = [], []
        return crawlrun.run(self.cfg_crawl, dry_run=dry_run, now=self.now, say=self.out.append, warn=self.err.append, kb_root=self.kb_tree, statvfs=statvfs or chain.roomy, probe=probe or self.probe,
                            steps=None if dry_run else (steps if steps is not None else self.steps()), pycache_prefix=prefix or self.prefix, entry_probe=self.entry_probe)

    def run_at(self, day, hour=9, minute=0, steps=None):
        return self.go(now=at(day, hour, minute), steps=steps)

    def plan_of(self, **keys):
        self.set_plan(days_plan(**keys))

    # -- the candidates
    def candidate(self, path, host, target="gene-editing"):
        """A queued candidate whose page the fake server serves; returns its row's number."""
        ident, title = self.add(path, host=host, target=target)
        self.titles[path] = title
        return ident

    def serves(self, path):
        """The page of `path` is served (it was refused before)."""
        self.srv.routes[path] = reply(200, body=chain.page(self.titles[path], chain.PROSE * 2))

    def refuses(self, path, status=403):
        self.srv.routes[path] = reply(status, body=b"no")

    def redirecting(self, path, host, target, refused=False):
        """A candidate whose address redirects to `target` (a full address): the page is at the end; `refused` makes the end answer 403."""
        ident, title = self.add(path, host=host, route=False)
        self.host_dns(urlsplit(target).hostname)
        self.srv.routes[path] = redirect(target)
        end = urlsplit(target).path
        self.titles[end] = title
        if refused:
            self.refuses(end)
        else:
            self.serves(end)
        return ident

    def hop(self, here, there):
        """`here` (a full address) redirects to `there`."""
        self.host_dns(urlsplit(here).hostname)
        self.host_dns(urlsplit(there).hostname)
        self.srv.routes[urlsplit(here).path] = redirect(there)

    # -- what a test reads
    def counter(self, day, key):
        return self.counters().get((DAYS[day], key), 0)

    def day_counters(self, day):
        return {key: n for (found, key), n in self.counters().items() if found == DAYS[day]}

    def state_of(self, ident):
        row = self.row(ident)
        return row["status"], row["tries"]

    def last_fetch_reasons(self):
        return [l["reason"] for l in self.last_run() if l["step"] == "fetch" and l["outcome"] == "skipped"]

    def statuses(self, idents):
        return [self.row(i)["status"] for i in idents]

    def reshelved(self, ident):
        return len(self.events(self.book_of(ident), "reshelved"))


class FetchesPerDay(Days):
    def test_at_the_ceiling_no_new_candidate_is_fetched_later_runs_of_the_day_finish_earlier_work_and_the_next_day_starts_with_a_fresh_count(self):
        self.plan_of(fetches_per_day=3, batch=4)
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(6)]                    # six sites: no per-domain limit is near
        unfinished = self.steps(judge=chain.no_step, cards=chain.no_step, move=chain.no_step)
        self.assertEqual(self.run_at(1, 9, 0, steps=unfinished), 0)                         # three are fetched (the ceiling), and the books wait for the judge, the card and the move
        self.assertEqual(self.statuses(ids), ["kept"] * 3 + ["queued"] * 3)
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2"])
        self.assertEqual(self.counter(1, "fetch"), 3)
        self.assertEqual(self.last_fetch_reasons(), ["fetches_per_day reached: no new candidates today"])
        self.assertEqual([self.reshelved(i) for i in ids[:3]], [0, 0, 0])
        self.assertEqual(self.go(now=at(1, 15, 0)), 0)                                      # the same day: the ceiling holds, and the earlier work is finished
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2"])
        self.assertEqual(self.counter(1, "fetch"), 3)
        self.assertEqual(self.statuses(ids), ["kept"] * 3 + ["queued"] * 3)
        self.assertEqual(self.last_fetch_reasons(), ["fetches_per_day reached (3 of 3): no new candidates", "fetches_per_day reached: no new candidates today"])
        self.assertEqual([self.reshelved(i) for i in ids[:3]], [1, 1, 1])                   # judged, carded and moved by the run after the ceiling
        self.assertEqual(self.go(now=at(1, 23, 59)), 0)
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2"])
        self.now = at(2, 0, 5)
        self.assertEqual(self.used()["fetch"], (0, 3))                                      # the next day starts with a fresh count
        self.assertEqual(self.go(), 0)
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2", "/p3", "/p4", "/p5"])
        self.assertEqual(self.statuses(ids), ["kept"] * 6)
        self.assertEqual((self.counter(1, "fetch"), self.counter(2, "fetch")), (3, 3))
        self.assertEqual([self.reshelved(i) for i in ids], [1] * 6)
        self.assert_within_ceilings()

    def test_the_ceiling_is_the_day_of_the_clock_and_not_the_number_of_runs(self):
        self.plan_of(fetches_per_day=2, batch=1)                                            # one candidate a run: each run takes one until the day's two are used
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(5)]
        for day in (1, 2, 3):
            for hour in (6, 12, 18):
                self.assertEqual(self.run_at(day, hour), 0)
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2", "/p3", "/p4"])
        self.assertEqual((self.counter(1, "fetch"), self.counter(2, "fetch"), self.counter(3, "fetch")), (2, 2, 1))       # 2 + 2 + 1: the queue ran out on the third day
        self.assertEqual(self.statuses(ids), ["kept"] * 5)
        self.assertEqual(len([l for l in self.lines() if l["step"] == "run_start"]), 9)


class PerDomainPerDay(Days):
    def test_a_site_at_its_limit_is_skipped_for_the_day_while_other_sites_go_on_and_it_is_available_the_next_day(self):
        self.plan_of(per_domain_per_day=2, batch=8)
        own = [self.candidate(f"/a{n}", "s.test") for n in range(4)]
        other = self.candidate("/o0", "o.test")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.statuses(own), ["kept", "kept", "queued", "queued"])
        self.assertEqual(self.state_of(other), ("kept", 1))                                 # the other site is taken after the two of the limit
        self.assertEqual(self.requests(), ["/a0", "/a1", "/o0"])
        self.assertEqual(self.day_counters(1), {"fetch": 3, "fetch:s.test": 2, "fetch:o.test": 1, "card": 3})
        self.assertEqual(self.last_fetch_reasons(), [crawlfetch.WHY_ENDED["nothing_queued"]])
        self.assertEqual(self.go(now=at(1, 20)), 0)                                         # later the same day: still skipped, and nothing is asked of the site
        self.assertEqual(self.requests(), ["/a0", "/a1", "/o0"])
        self.assertEqual((self.state_of(own[2]), self.state_of(own[3])), (("queued", 0), ("queued", 0)))
        self.assertEqual(self.go(now=at(2, 0, 10)), 0)                                      # the next day the site has its units again
        self.assertEqual(self.statuses(own), ["kept"] * 4)
        self.assertEqual(self.requests(), ["/a0", "/a1", "/o0", "/a2", "/a3"])
        self.assertEqual((self.counter(2, "fetch:s.test"), self.counter(2, "fetch")), (2, 2))
        self.assertEqual(self.counter(1, "fetch:s.test"), 2)                                # the finished day is as it was

    def test_the_hops_of_a_site_have_their_own_count_which_is_refused_at_the_limit_and_is_fresh_the_next_day(self):
        self.plan_of(per_domain_per_day=1, batch=8)
        first = self.redirecting("/r0", "r0.test", "http://victim.test/page0")
        second = self.redirecting("/r1", "r1.test", "http://victim.test/page1")
        own = self.candidate("/own", "victim.test")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual((self.state_of(first), self.state_of(own)), (("kept", 1), ("kept", 1)))
        row = self.row(second)                                                              # a hop to a site at its limit is put off, not failed
        self.assertEqual((row["status"], row["tries"], row["reason"], row["next_try"]), ("queued", 1, "the site it leads to is at its limit for the day", "2026-11-16T10:00:00Z"))
        self.assertEqual((self.counter(1, "hop:victim.test"), self.counter(1, "fetch:victim.test")), (1, 1))        # the hop is counted apart from the site's own candidate
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [True, True])                               # a put-off hop is nothing for the breaker
        self.assertEqual(self.requests().count("/page1"), 0)
        self.assertEqual(self.counter(1, "fetch:r1.test"), 1)                               # the try that was put off used a unit of the redirector's own site
        self.assertEqual(self.go(now=at(1, 11)), 0)                                         # later the same day: that site is at its limit, so the candidate is not taken, and the hop count does not move
        self.assertEqual((self.state_of(second), self.counter(1, "hop:victim.test")), (("queued", 1), 1))
        self.assertEqual(self.requests().count("/page1"), 0)
        self.assertEqual(self.go(now=at(2, 0, 30)), 0)                                      # the next day the site's hops are counted afresh
        self.assertEqual(self.state_of(second), ("kept", 2))
        self.assertEqual((self.counter(2, "hop:victim.test"), self.counter(1, "hop:victim.test")), (1, 1))
        self.assertEqual(self.requests().count("/page1"), 1)

    def test_a_hop_to_a_site_whose_own_candidates_used_its_limit_is_refused_and_is_taken_the_next_day(self):
        self.plan_of(per_domain_per_day=1, batch=8)
        own = self.candidate("/own", "victim.test")                                         # the site's own candidate is first and uses its unit of the day
        hopper = self.redirecting("/r0", "r0.test", "http://victim.test/page0")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.state_of(own), ("kept", 1))
        self.assertEqual(self.state_of(hopper), ("queued", 1))
        self.assertEqual(self.row(hopper)["reason"], "the site it leads to is at its limit for the day")
        self.assertEqual((self.counter(1, "fetch:victim.test"), self.counter(1, "hop:victim.test")), (1, 0))
        self.assertEqual(self.go(now=at(2, 9)), 0)
        self.assertEqual(self.state_of(hopper), ("kept", 2))
        self.assertEqual((self.counter(2, "hop:victim.test"), self.counter(2, "fetch:victim.test")), (1, 0))

    def test_a_candidate_counts_a_site_once_however_many_requests_it_makes_there(self):
        self.plan_of(per_domain_per_day=1, batch=8)
        self.hop("http://victim.test/m1", "http://www.victim.test/m2")
        self.hop("http://www.victim.test/m2", "http://victim.test/page")
        self.hop("http://victim.test/n1", "http://www.victim.test/n2")
        self.hop("http://www.victim.test/n2", "http://victim.test/page2")
        first = self.redirecting("/r0", "r0.test", "http://victim.test/page")
        self.srv.routes["/r0"] = redirect("http://victim.test/m1")
        second = self.redirecting("/r1", "r1.test", "http://victim.test/page2")
        self.srv.routes["/r1"] = redirect("http://victim.test/n1")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.state_of(first), ("kept", 1))                                 # three requests to the site: one unit
        self.assertEqual([p for p in self.requests() if p in ("/m1", "/m2", "/page")], ["/m1", "/m2", "/page"])
        self.assertEqual(self.counter(1, "hop:victim.test"), 1)
        self.assertEqual(self.state_of(second), ("queued", 1))                              # and the limit of one was used by it
        self.assertEqual(self.go(now=at(2, 9)), 0)
        self.assertEqual(self.state_of(second), ("kept", 2))
        self.assertEqual([p for p in self.requests() if p in ("/n1", "/n2", "/page2")], ["/n1", "/n2", "/page2"])
        self.assertEqual((self.counter(1, "hop:victim.test"), self.counter(2, "hop:victim.test")), (1, 1))


class DomainRefusals(Days):
    def test_three_refusals_by_one_site_stop_it_for_the_day_other_sites_go_on_and_it_is_taken_again_the_next_day(self):
        self.plan_of(batch=8, per_domain_per_day=50)
        refused = [self.candidate(f"/c{n}", "s.test") for n in range(3)]
        for n in range(3):
            self.refuses(f"/c{n}")
        fourth = self.candidate("/c3", "s.test")
        other = self.candidate("/t0", "t.test")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.counter(1, "refusal:s.test"), 3)
        self.assertEqual([self.state_of(i) for i in refused], [("queued", 1)] * 3)
        self.assertEqual({self.row(i)["next_try"] for i in refused}, {"2026-11-17T09:00:00Z"})      # a refusal waits a day
        self.assertEqual((self.state_of(fourth), self.state_of(other)), (("queued", 0), ("kept", 1)))   # the site is stopped before its fourth; the other site goes on
        self.assertEqual(self.requests(), ["/c0", "/c1", "/c2", "/t0"])
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [True])                       # a refusal is not a failure for the breaker
        self.assertEqual(self.go(now=at(1, 21)), 0)                                         # later the same day the site is still stopped
        self.assertEqual(self.requests(), ["/c0", "/c1", "/c2", "/t0"])
        self.assertEqual(self.counter(1, "refusal:s.test"), 3)
        self.assertEqual(self.go(now=at(2, 0, 30)), 0)                                      # the next day it is taken again: the fourth candidate goes first, the refused wait for their day
        self.assertEqual(self.state_of(fourth), ("kept", 1))
        self.assertEqual(self.counter(2, "refusal:s.test"), 0)
        self.assertEqual(self.requests(), ["/c0", "/c1", "/c2", "/t0", "/c3"])
        for n in range(3):
            self.serves(f"/c{n}")
        self.assertEqual(self.go(now=at(2, 9, 0)), 0)                                       # at their time they are taken, and now the site lets them in
        self.assertEqual(self.statuses(refused), ["kept"] * 3)
        self.assertEqual(self.counter(1, "refusal:s.test"), 3)                              # the finished day is as it was
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [True] * 5)

    def test_a_refusal_after_a_redirect_is_counted_against_the_site_that_answered_and_not_the_resolver(self):
        self.plan_of(batch=8, per_domain_per_day=50)
        refused = [self.redirecting(f"/r{n}", "resolver.test", f"http://pub.test/p{n}", refused=True) for n in range(3)]
        later = self.redirecting("/r3", "resolver.test", "http://pub.test/p3")                 # a fourth candidate of the resolver, for the same publisher
        elsewhere = self.redirecting("/r4", "resolver.test", "http://ok.test/q")                # and a fifth, for a publisher that answers
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual((self.counter(1, "refusal:pub.test"), self.counter(1, "refusal:resolver.test")), (3, 0))
        self.assertEqual([self.state_of(i) for i in refused], [("queued", 1)] * 3)
        self.assertEqual(self.state_of(later), ("queued", 1))                               # the publisher is stopped: this one is put off, not failed
        self.assertEqual(self.row(later)["reason"], "the site it leads to is stopped for the day")
        self.assertEqual(self.state_of(elsewhere), ("kept", 1))                             # the resolver itself is not stopped by what its publishers do
        self.assertEqual(self.counter(1, "fetch:resolver.test"), 5)
        self.assertNotIn("/p3", self.requests())
        self.assertEqual(self.go(now=at(2, 0, 30)), 0)                                      # the next day the publisher is available again
        self.assertEqual(self.state_of(later), ("kept", 2))
        self.assertEqual((self.counter(2, "refusal:pub.test"), self.counter(2, "hop:pub.test")), (0, 1))
        self.assertEqual(self.counter(1, "refusal:pub.test"), 3)
        self.assertEqual(self.counter(2, "refusal:resolver.test"), 0)


class CardsPerDay(Days):
    def test_books_judged_in_wait_for_their_card_when_the_ceiling_is_reached_and_are_carded_the_next_day_oldest_first(self):
        self.plan_of(cards_per_day=2, batch=5)
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(5)]
        self.assertEqual(self.run_at(1, 9), 0)
        books = [self.book_of(i) for i in ids]
        self.assertEqual([len(self.events(b, "crawl_judged")) for b in books], [1] * 5)       # all five are filed and judged in
        self.assertEqual([self.reshelved(i) for i in ids], [1, 1, 0, 0, 0])                 # the two oldest are carded and moved
        self.assertEqual([l["reason"] for l in self.last_run() if l["step"] == "card" and l["outcome"] == "skipped"], ["cards_per_day reached"])      # the card step of the earlier work found no book waiting; the one after the fetch reached the ceiling
        self.assertEqual(self.counter(1, "card"), 2)
        self.assertEqual(self.go(now=at(1, 20)), 0)                                         # the same day: the ceiling holds
        self.assertEqual((self.counter(1, "card"), [self.reshelved(i) for i in ids]), (2, [1, 1, 0, 0, 0]))
        self.assertEqual(self.go(now=at(2, 9)), 0)
        self.assertEqual([self.reshelved(i) for i in ids], [1, 1, 1, 1, 0])                 # the next day the next two, in the order the books were filed
        self.assertEqual((self.counter(2, "card"), self.counter(1, "card")), (2, 2))
        self.assertEqual(self.go(now=at(3, 9)), 0)
        self.assertEqual([self.reshelved(i) for i in ids], [1] * 5)
        self.assertEqual((self.counter(3, "card"), self.counter(2, "card")), (1, 2))
        self.assertEqual([b for kind, b in self.order if kind == "card"], books)             # oldest first, one card each, across the three days
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2", "/p3", "/p4"])              # and nothing was fetched again for it


class FiledTotal(Days):
    def test_the_total_of_books_filed_never_resets_with_the_days(self):
        self.plan_of(filed_total=3, batch=8, fetches_per_day=20)
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(6)]
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.statuses(ids), ["kept"] * 3 + ["queued"] * 3)
        self.assertEqual(self.last_fetch_reasons(), ["filed_total reached: no new books"])
        self.assertEqual(crawlbooks.filed_count(self.store), 3)
        for day in (2, 3, 4):
            self.now = at(day, 0, 5)
            self.assertEqual(self.used()["fetch"], (0, 20))                                 # the day's count is fresh and its ceiling is far
            self.assertEqual(self.go(), 0)
            self.assertEqual(self.go(now=at(day, 15)), 0)
            self.assertEqual(self.last_fetch_reasons(), ["filed_total reached: no new books"])
            self.assertEqual(crawlbooks.filed_count(self.store), 3)                         # but no new book is filed
            self.assertEqual(self.counter(day, "fetch"), 0)
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2"])
        self.assertEqual(self.statuses(ids), ["kept"] * 3 + ["queued"] * 3)
        self.assertEqual([self.reshelved(i) for i in ids[:3]], [1, 1, 1])                   # the books it holds are still finished

    def test_a_book_filed_on_a_later_day_counts_with_those_of_the_days_before(self):
        self.plan_of(filed_total=4, batch=2, fetches_per_day=20)
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(6)]
        for day, filed in ((1, 2), (2, 4), (3, 4)):                                         # a run takes at most its batch of two; the third day's run finds the total used
            self.assertEqual(self.run_at(day, 9), 0)
            self.assertEqual(crawlbooks.filed_count(self.store), filed)
        self.assertEqual(self.statuses(ids), ["kept"] * 4 + ["queued"] * 2)
        self.assertEqual((self.counter(1, "fetch"), self.counter(2, "fetch"), self.counter(3, "fetch")), (2, 2, 0))
        self.assertEqual(self.last_fetch_reasons(), ["filed_total reached: no new books"])


class TheWaitOfAFailedTry(Days):
    def test_a_failed_try_waits_one_then_six_then_twenty_four_hours_across_the_day_boundary_and_at_retries_it_is_failed(self):
        self.plan_of(retries=4)
        ident = self.candidate("/f0", "a.test")
        self.srv.routes["/f0"] = reply(500, body=b"broken")
        self.assertEqual(self.run_at(1, 22, 30), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"], row["reason"]), ("queued", 1, "2026-11-16T23:30:00Z", "HTTP 500"))      # the first wait is an hour
        self.assertEqual(self.go(now=at(1, 23, 0)), 0)                                      # not yet
        self.assertEqual((self.state_of(ident), len(self.requests())), (("queued", 1), 1))
        self.assertEqual(self.go(now=at(1, 23, 30)), 0)                                     # at its time exactly it is taken
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"]), ("queued", 2, "2026-11-17T05:30:00Z"))              # the second wait is six hours, over the midnight
        self.assertEqual(self.go(now=at(2, 5, 29)), 0)
        self.assertEqual((self.state_of(ident), len(self.requests())), (("queued", 2), 2))
        self.assertEqual(self.go(now=at(2, 5, 30)), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"]), ("queued", 3, "2026-11-18T05:30:00Z"))              # the third wait is twenty-four hours
        self.assertEqual(self.go(now=at(3, 5, 29)), 0)
        self.assertEqual((self.state_of(ident), len(self.requests())), (("queued", 3), 3))
        self.assertEqual(self.go(now=at(3, 5, 30)), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"], row["reason"]), ("failed", 4, None, "failed 4 times: HTTP 500"))     # at `retries` it is failed, and final
        self.assertEqual(self.go(now=at(4, 9)), 0)
        self.assertEqual((self.state_of(ident), len(self.requests())), (("failed", 4), 4))
        self.assertEqual([self.counter(day, "fetch") for day in (1, 2, 3, 4)], [2, 1, 1, 0])         # each try is a unit of the day it was made in
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [False] * 4)               # (the breaker is set out of the way for this test)
        self.assertEqual([self.store.read_book(b)["state"] for b in self.crawl_books_all()], ["weeded"])      # the book that the failed captures made is not active, and is not counted as filed
        self.assertEqual(crawlbooks.filed_count(self.store), 0)

    def test_a_refusal_waits_a_day_whatever_the_try_and_is_failed_at_retries(self):
        self.plan_of(retries=3)
        ident = self.candidate("/g0", "b.test")
        self.refuses("/g0")
        self.assertEqual(self.run_at(1, 10), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"]), ("queued", 1, "2026-11-17T10:00:00Z"))      # a day, where a failure waits an hour
        self.assertEqual(self.go(now=at(2, 9, 59)), 0)
        self.assertEqual((self.state_of(ident), len(self.requests())), (("queued", 1), 1))
        self.assertEqual(self.go(now=at(2, 10)), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"]), ("queued", 2, "2026-11-18T10:00:00Z"))      # a day again, where a second failure waits six hours
        self.assertEqual(self.go(now=at(3, 10)), 0)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"], row["reason"]), ("failed", 3, None, "failed 3 times: the site refused (HTTP 403)"))
        self.assertEqual([self.counter(day, "refusal:b.test") for day in (1, 2, 3)], [1, 1, 1])


class TheDownClocks(Days):
    LIMIT = 2000                                                                            # model_down_minutes: 33 hours and 20 minutes, so that the clocks run over days

    def test_the_clock_of_a_model_entry_persists_across_runs_and_days_and_trips_the_breaker_when_the_entry_has_been_down_longer_than_the_limit(self):
        self.plan_of(model_down_minutes=self.LIMIT, batch=1)
        first, second = self.candidate("/p0", "s0.test"), self.candidate("/p1", "s1.test")
        self.assertIsNone(crawlguard.record_entry(self.index, "chat", False, at(1, 22), self.plan))     # what a step does when its model call failed: the clock starts
        self.assertEqual(crawlguard.load_state(self.index)[0]["entries_down"], {"chat": "2026-11-16T22:00:00Z"})
        self.entry_answers["place"] = False                                                 # the entry named `chat` is the one of the `place` task, and it does not answer
        quiet = lambda day, hour, minute=0: self.go(now=at(day, hour, minute), steps=self.steps(move=chain.no_step))      # (a proposal that the chat model answers would clear its clock: the move is left out of these runs)
        self.assertEqual(quiet(2, 8), 0)                                                    # ten hours: the run goes on, the entry is asked, and the clock keeps its first time
        self.assertEqual((self.entry_calls, self.state_of(first)), (["place"], ("kept", 1)))
        self.assertEqual(crawlguard.load_state(self.index)[0]["entries_down"], {"chat": "2026-11-16T22:00:00Z"})
        self.assertIn(("failed", "the model entry chat has not answered since 2026-11-16T22:00:00Z"), [(l["outcome"], l["reason"]) for l in self.last_run() if l["step"] == "breaker"])
        self.assertEqual(quiet(3, 6), 0)                                                    # a day and a half later: the same clock, still within the limit
        self.assertEqual((self.entry_calls, self.state_of(second)), (["place", "place"], ("kept", 1)))
        self.assertEqual(quiet(3, 7, 20), 0)                                                # down for exactly the limit: not yet longer than it
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(quiet(3, 7, 21), 4)                                                # a minute longer: the breaker trips, in the run that asked
        breaker = crawlguard.read_breaker(self.index)
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertIn(f"the model entry chat has not answered for over {self.LIMIT} minutes", breaker["reason"])
        self.entry_calls.clear()
        self.assertEqual(quiet(3, 7, 30), 4)                                                # and the runs after it are refused before any probe
        self.assertEqual(self.entry_calls, [])
        self.assertEqual(self.requests(), ["/p0", "/p1"])

    def test_the_clock_of_the_card_embedding_persists_across_days_and_a_clear_goes_on_with_the_counters_of_the_day_as_they_were(self):
        self.plan_of(model_down_minutes=self.LIMIT)
        self.candidate("/p0", "s0.test")
        self.up = False
        self.assertEqual(self.run_at(1, 22), 3)                                             # refused: the clock starts
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-16T22:00:00Z")
        self.assertEqual(self.run_at(2, 8), 3)
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], "2026-11-16T22:00:00Z")      # it is the first time that stands, from run to run and from day to day
        self.assertEqual(self.run_at(3, 7, 20), 3)
        self.assertEqual(self.run_at(3, 7, 21), 4)
        breaker = crawlguard.read_breaker(self.index)
        self.assertEqual((breaker["tripped"], breaker["kind"]), (True, "model_down"))
        self.assertEqual(self.requests(), [])                                               # nothing was fetched while the models were down
        self.up = True
        self.assertEqual(self.run_at(3, 7, 30), 4)                                          # the models answer again, but the breaker holds until it is cleared
        self.assertEqual(self.requests(), [])
        self.now = at(3, 7, 40)
        for _ in range(3):                                                                  # a site that has been refused three times today
            crawlstate.note_refusal(self.conn(), self.plan, self.now, "x.test")
        before = self.counters()
        self.assertEqual(before[(DAYS[3], "refusal:x.test")], 3)
        crawlguard.clear(self.index, yes=True, is_tty=lambda: True, now=self.now)
        self.assertFalse(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(self.counters(), before)                                           # the clear does not reset the day's counters
        refusals = crawlguard.refusals_today(self.conn(), self.plan, self.now)
        self.assertTrue(crawlguard.site_stopped(refusals, "x.test", self.plan))             # nor lets a site that was stopped for the day back in
        self.assertEqual(crawlguard.load_state(self.index)[0]["model_down_since"], None)    # (a clear is a fresh start of the guards' own clocks)
        self.assertEqual(self.run_at(3, 8), 0)
        self.assertEqual(self.requests(), ["/p0"])
        self.assertEqual(self.counter(3, "fetch"), 1)
        self.assertEqual(self.counter(3, "refusal:x.test"), 3)


class TheDay(Days):
    """The day is the plan's zone: `timezone` names it, and a run belongs to the day of its time in that zone."""

    def test_with_the_zone_of_tokyo_a_run_at_2359_and_one_at_0001_local_belong_to_different_days(self):
        self.plan_of(timezone="Asia/Tokyo", fetches_per_day=1, batch=4)
        ids = [self.candidate(f"/p{n}", f"s{n}.test") for n in range(3)]
        self.assertEqual(self.run_at(1, 14, 59), 0)                                         # 23:59 on 2026-11-16 in Tokyo
        self.assertEqual((self.requests(), self.day_counters(1).get("fetch")), (["/p0"], 1))
        self.assertEqual(self.run_at(1, 15, 1), 0)                                          # 00:01 on 2026-11-17 in Tokyo, two minutes later and the same day in UTC: a new day with a fresh count
        self.assertEqual(self.requests(), ["/p0", "/p1"])
        self.assertEqual((self.counter(1, "fetch"), self.counter(2, "fetch")), (1, 1))
        self.assertEqual(self.go(now=at(1, 20)), 0)                                         # 05:00 in Tokyo: the same day as 00:01, whose count is used
        self.assertEqual(self.requests(), ["/p0", "/p1"])
        self.assertEqual(self.go(now=at(2, 14, 59)), 0)                                     # 23:59 in Tokyo on the 17th
        self.assertEqual(self.requests(), ["/p0", "/p1"])
        self.assertEqual(self.go(now=at(2, 15, 1)), 0)                                      # 00:01 on the 18th
        self.assertEqual(self.requests(), ["/p0", "/p1", "/p2"])
        self.assertEqual(self.counters(), {(DAYS[1], "fetch"): 1, (DAYS[1], "fetch:s0.test"): 1, (DAYS[2], "fetch"): 1, (DAYS[2], "fetch:s1.test"): 1, (DAYS[3], "fetch"): 1, (DAYS[3], "fetch:s2.test"): 1,
                                                (DAYS[1], "card"): 1, (DAYS[2], "card"): 1, (DAYS[3], "card"): 1})
        self.assertEqual(self.statuses(ids), ["kept"] * 3)

    def test_with_the_zone_of_utc_the_same_two_runs_belong_to_one_day(self):
        self.plan_of(fetches_per_day=1, batch=4)
        self.candidate("/p0", "s0.test")
        self.candidate("/p1", "s1.test")
        self.assertEqual(self.run_at(1, 14, 59), 0)
        self.assertEqual(self.run_at(1, 15, 1), 0)
        self.assertEqual((self.requests(), self.counter(1, "fetch"), self.counter(2, "fetch")), (["/p0"], 1, 0))     # the second run found the ceiling used
        self.assertEqual(self.go(now=at(2, 0, 1)), 0)                                       # and the first minute of the next UTC day has a fresh count
        self.assertEqual(self.requests(), ["/p0", "/p1"])


class AFinishedDay(Days):
    def read_status(self, now):
        return crawlstatus.status(self.index, self.bulk, read_plan=crawlplan.read_plan, store=store.Store.open(write=False), now=now, statvfs=chain.roomy)

    def report(self, day):
        return crawlreport.build(self.index, datetime.date.fromisoformat(DAYS[day]), "UTC", self.now, store=store.Store.open(write=False))

    def facts(self, day):
        """What the readers say of `day`: the counters against the ceilings and the runs of the status as of the end of that day, and the day's report in numbers."""
        status = self.read_status(at(day, 23, 59))
        counters = status["queue"]["counters"]
        report = self.report(day)
        return {"fetch": (counters["fetch"]["n"], counters["fetch"]["limit"]), "card": counters["card"]["n"], "started": status["runs_today"]["started"], "ended": status["runs_today"]["ended"],
                "fetched": report["counts"]["fetched"], "kept": report["counts"]["kept"], "runs": (report["runs"]["started"], report["runs"]["ended"])}

    def test_the_counters_of_a_finished_day_never_change_when_later_days_run_and_the_readers_read_the_day_they_are_asked_for(self):
        self.plan_of(batch=2, cards_per_day=3)
        for n in range(8):
            self.candidate(f"/p{n}", f"s{n}.test")
        log_of_day_1 = os.path.join(self.index, "crawl", "log", "crawl-2026-11-16.jsonl")
        self.assertEqual(self.run_at(1, 9), 0)
        self.assertEqual(self.go(now=at(1, 18)), 0)
        counters_1, lines_1, facts_1 = self.day_counters(1), chain.jsonl(log_of_day_1), self.facts(1)
        self.assertEqual((counters_1["fetch"], counters_1["card"]), (4, 3))
        self.assertEqual(facts_1, {"fetch": (4, 20), "card": 3, "started": 2, "ended": 2, "fetched": 4, "kept": 4, "runs": (2, 2)})
        self.assertEqual(self.run_at(2, 9), 0)
        counters_2, facts_2 = self.day_counters(2), self.facts(2)
        self.assertEqual(self.run_at(3, 9), 0)
        self.assertEqual(self.go(now=at(3, 18)), 0)
        self.assertEqual(self.go(now=at(4, 9)), 0)
        self.assertEqual(self.day_counters(1), counters_1)                                  # the counters of the days that finished are as they were
        self.assertEqual(self.day_counters(2), counters_2)
        self.assertEqual(chain.jsonl(log_of_day_1), lines_1)                                # and so is the log of the first day
        self.assertEqual(self.facts(1), facts_1)                                            # the readers, asked for an earlier day, read that day
        self.assertEqual(self.facts(2), facts_2)
        self.assertEqual(facts_2["fetch"], (2, 20))
        self.assertNotEqual(self.facts(3), facts_1)
        self.assertEqual(self.facts(3)["fetch"], (2, 20))                                   # (the eight candidates: four on the first day, two on each of the next two, and the fourth day found none)
        self.assertEqual(self.facts(4)["fetch"], (0, 20))
        self.assertEqual(len(self.requests()), 8)
        self.assert_within_ceilings()
