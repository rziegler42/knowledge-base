"""The ceilings, the counters and the changes of a candidate row (`kb/crawlstate.py`, Increment E of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

`crawlstate` is the only module that changes the state of a row of `candidates.sqlite` and the only one that writes its counters. Every test runs against a temporary queue made by `crawlqueue.connect`, with a clock it
passes in; a crash is a failure injected before each statement. Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlstate engine.tests.test_crawlqueue`."""
import datetime
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing

from engine.tests import ENGINE_DIR

from kb import KbError, crawlplan, crawlqueue, crawlstate

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


def plan(**changes):
    out = crawlplan.defaults()
    out.update(timezone="UTC", fetches_per_day=100, per_domain_per_day=100, batch=100, cards_per_day=100, retries=3, domain_refusals=3)
    out.update(changes)
    return out


def stamp(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Failing:
    """A connection that fails once, before its n-th statement, and otherwise passes everything to the real one."""

    def __init__(self, conn, fail_at):
        self.conn, self.fail_at, self.calls, self.failed = conn, fail_at, 0, False

    def execute(self, *args):
        self.calls += 1
        if self.calls == self.fail_at and not self.failed:
            self.failed = True
            raise sqlite3.OperationalError("injected failure")
        return self.conn.execute(*args)

    def __getattr__(self, name):
        return getattr(self.conn, name)


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = os.path.realpath(self._tmp.name)
        self.conn = crawlqueue.connect(self.folder)
        self.addCleanup(self.conn.close)
        self.plan = plan()

    def other(self):
        conn = crawlqueue.connect(self.folder)
        self.addCleanup(conn.close)
        return conn

    def add(self, name, domain="a.example", weight=1, added="2026-11-16T10:00:00Z", depth=0, status="queued", tries=0, next_try=None, updated=None, run_id=None):
        self.conn.execute("INSERT INTO candidates(identity_key, address, source, domain, weight, depth, status, tries, next_try, run_id, added, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (name, f"https://{domain}/{name}", "openalex", domain, weight, depth, status, tries, next_try, run_id, added, updated or added))
        return self.conn.execute("SELECT id FROM candidates WHERE identity_key = ?", (name,)).fetchone()[0]

    def row(self, ident):
        cur = self.conn.execute("SELECT * FROM candidates WHERE id = ?", (ident,))
        return dict(zip([d[0] for d in cur.description], cur.fetchone()))

    def counters(self):
        return dict(((day, key), n) for day, key, n in self.conn.execute("SELECT day, key, n FROM counters"))

    def table(self):
        return self.conn.execute("SELECT * FROM candidates ORDER BY id").fetchall(), self.conn.execute("SELECT * FROM counters ORDER BY day, key").fetchall()

    def reserve(self, now=NOW, run="run-1", **kw):
        kw.setdefault("filed", 0)
        return crawlstate.reserve(self.conn, self.plan, now, run, **kw)


class Order(Case):
    def test_higher_weight_first_then_oldest_then_lower_depth_then_the_first_found(self):
        a = self.add("a", weight=1, added="2026-11-16T08:00:00Z")
        b = self.add("b", weight=5, added="2026-11-16T09:00:00Z")
        c = self.add("c", weight=5, added="2026-11-16T07:00:00Z", depth=2)
        d = self.add("d", weight=5, added="2026-11-16T07:00:00Z", depth=1)
        e = self.add("e", weight=5, added="2026-11-16T07:00:00Z", depth=1)
        w = self.add("w", weight=None, added="2026-11-16T01:00:00Z")
        order = [self.reserve()[0]["id"] for _ in range(6)]
        self.assertEqual(order, [d, e, c, b, a, w])
        self.assertEqual(self.reserve(), (None, "nothing_queued"))

    def test_a_wandered_candidate_counts_as_weight_zero_and_ties_with_it_by_age(self):
        zero = self.add("zero", weight=0, added="2026-11-16T10:00:00Z")
        wandered = self.add("wandered", weight=None, added="2026-11-16T09:00:00Z")
        self.assertEqual([self.reserve()[0]["id"], self.reserve()[0]["id"]], [wandered, zero])

    def test_only_queued_rows_are_taken_and_a_row_waits_for_its_next_try(self):
        for status in ("fetching", "kept", "rejected", "failed", "blocked"):
            self.add(status, status=status)
        later = self.add("later", next_try="2026-11-16T12:00:01Z")
        self.assertEqual(self.reserve(), (None, "nothing_queued"))
        ready = self.add("ready", next_try="2026-11-16T12:00:00Z")
        self.assertEqual(self.reserve()[0]["id"], ready)
        self.assertEqual(self.reserve(), (None, "nothing_queued"))
        self.assertEqual(self.reserve(now=NOW + datetime.timedelta(seconds=1))[0]["id"], later)

    def test_a_row_with_no_site_is_not_taken_because_it_cannot_be_paced(self):
        self.conn.execute("INSERT INTO candidates(identity_key, address, source, status, added, updated) VALUES ('x', 'https://x.example/', 'openalex', 'queued', ?, ?)", ("2026-11-16T10:00:00Z",) * 2)
        self.assertEqual(self.reserve(), (None, "nothing_queued"))


class Reserve(Case):
    def test_it_marks_the_row_fetching_adds_a_try_and_one_to_both_counters_in_one_step(self):
        ident = self.add("a")
        row, why = self.reserve(run="run-7")
        self.assertEqual(why, "")
        self.assertEqual((row["id"], row["status"], row["tries"], row["run_id"], row["updated"], row["address"]), (ident, "fetching", 1, "run-7", "2026-11-16T12:00:00Z", "https://a.example/a"))
        self.assertEqual(self.row(ident)["status"], "fetching")
        self.assertEqual(self.counters(), {("2026-11-16", "fetch"): 1, ("2026-11-16", "fetch:a.example"): 1})
        self.add("b", domain="b.example")
        self.reserve()
        self.assertEqual(self.counters(), {("2026-11-16", "fetch"): 2, ("2026-11-16", "fetch:a.example"): 1, ("2026-11-16", "fetch:b.example"): 1})

    def test_fetches_per_day_is_a_ceiling_that_ends_with_the_day(self):
        self.plan = plan(fetches_per_day=2)
        for name in "abcd":
            self.add(name, domain=f"{name}.example")
        self.assertIsNotNone(self.reserve()[0])
        self.assertIsNotNone(self.reserve()[0])
        self.assertEqual(self.reserve(), (None, "fetches_per_day"))
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 2)
        self.assertIsNotNone(self.reserve(now=NOW + datetime.timedelta(days=1))[0])

    def test_a_site_at_its_cap_is_skipped_and_not_blocked_and_other_sites_go_on(self):
        self.plan = plan(per_domain_per_day=1)
        first = self.add("a1", domain="a.example", weight=9)
        second = self.add("a2", domain="a.example", weight=9)
        other = self.add("b1", domain="b.example", weight=1)
        self.assertEqual(self.reserve()[0]["id"], first)
        self.assertEqual(self.reserve()[0]["id"], other)
        self.assertEqual(self.reserve(), (None, "nothing_queued"))
        self.assertEqual(self.row(second)["status"], "queued")
        self.assertEqual(self.reserve(now=NOW + datetime.timedelta(days=1))[0]["id"], second)

    def test_a_site_stopped_for_the_day_is_skipped_and_other_sites_are_still_taken(self):
        self.plan = plan(domain_refusals=2)
        self.conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'refusal:bad.example', 2)")
        self.conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'refusal:near.example', 1)")
        bad = self.add("bad", domain="bad.example", weight=9)
        near = self.add("near", domain="near.example", weight=5)
        good = self.add("good", domain="good.example", weight=1)
        self.assertEqual(self.reserve()[0]["id"], near)
        self.assertEqual(self.reserve()[0]["id"], good)
        self.assertEqual(self.reserve(), (None, "nothing_queued"))
        self.assertEqual(self.row(bad)["status"], "queued")
        self.assertEqual(self.row(bad)["tries"], 0)
        self.assertEqual(self.reserve(now=NOW + datetime.timedelta(days=1))[0]["id"], bad)

    def test_the_batch_limits_the_rows_one_run_takes_and_another_run_takes_its_own(self):
        self.plan = plan(batch=2)
        for name in "abcde":
            self.add(name, domain=f"{name}.example")
        self.assertIsNotNone(self.reserve(run="r1")[0])
        self.assertIsNotNone(self.reserve(run="r1")[0])
        self.assertEqual(self.reserve(run="r1"), (None, "batch"))
        self.assertIsNotNone(self.reserve(run="r2")[0])
        self.assertEqual(self.reserve(run="r1"), (None, "batch"))

    def test_the_total_filed_ceiling_given_by_the_caller_stops_new_fetches(self):
        self.plan = plan(filed_total=5)
        self.add("a")
        self.assertEqual(self.reserve(filed=5), (None, "filed_total"))
        self.assertEqual(self.reserve(filed=99), (None, "filed_total"))
        self.assertEqual(self.row(1)["status"], "queued")
        self.assertIsNotNone(self.reserve(filed=4)[0])

    def test_the_order_of_the_ceilings_is_the_fetch_then_filed_then_batch_then_nothing(self):
        self.plan = plan(fetches_per_day=1, batch=1, filed_total=1)
        self.add("a")
        self.assertEqual(self.reserve(filed=1), (None, "filed_total"))
        self.assertIsNotNone(self.reserve(filed=0)[0])
        self.assertEqual(self.reserve(filed=1)[1], "fetches_per_day")
        self.assertEqual(self.reserve(filed=0)[1], "fetches_per_day")

    def test_the_day_is_the_plans_day_at_midnight_in_a_zone_with_a_change_of_clock(self):
        self.plan = plan(timezone="America/New_York", fetches_per_day=1)
        self.add("a", domain="a.example")
        self.add("b", domain="b.example")
        self.add("c", domain="c.example")
        late = datetime.datetime(2026, 11, 2, 4, 59, 59, tzinfo=UTC)               # 23:59:59 on the 1st, after the clocks went back
        self.assertIsNotNone(self.reserve(now=late)[0])
        self.assertEqual(self.reserve(now=late)[1], "fetches_per_day")
        self.assertEqual(self.reserve(now=datetime.datetime(2026, 11, 1, 6, 30, tzinfo=UTC))[1], "fetches_per_day")     # 01:30 EST: still the 1st
        self.assertIsNotNone(self.reserve(now=datetime.datetime(2026, 11, 2, 5, 0, 0, tzinfo=UTC))[0])                 # 00:00 on the 2nd
        self.assertEqual(sorted(day for day, key in self.counters() if key == "fetch"), ["2026-11-01", "2026-11-02"])

    def test_a_clock_set_back_counts_in_the_day_it_shows_and_does_not_lose_a_count(self):
        self.plan = plan(fetches_per_day=2)
        for name in "abc":
            self.add(name, domain=f"{name}.example")
        self.assertIsNotNone(self.reserve(now=NOW)[0])
        self.assertIsNotNone(self.reserve(now=NOW - datetime.timedelta(days=1))[0])        # yesterday's own count
        self.assertEqual(self.counters()[("2026-11-15", "fetch")], 1)
        self.assertIsNotNone(self.reserve(now=NOW)[0])
        self.assertEqual(self.reserve(now=NOW)[1], "fetches_per_day")
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 2)

    def test_a_time_without_a_zone_a_bad_run_name_or_a_bad_plan_is_refused_and_changes_nothing(self):
        self.add("a")
        before = self.table()
        with self.assertRaises(KbError):
            crawlstate.reserve(self.conn, self.plan, datetime.datetime(2026, 11, 16, 12), "r", 0)
        for run in ("", "a b", None, 5, "x" * 65):
            with self.assertRaises(KbError):
                crawlstate.reserve(self.conn, self.plan, NOW, run, 0)
        for bad in (None, {}, [], dict(self.plan, batch="8"), dict(self.plan, batch=True), dict(self.plan, batch=0), dict(self.plan, fetches_per_day=-1), dict(self.plan, timezone=5)):
            with self.assertRaises(KbError):
                crawlstate.reserve(self.conn, bad, NOW, "r", 0)
        for filed in (None, -1, True, "5", 1.5):
            with self.assertRaises(KbError):
                crawlstate.reserve(self.conn, self.plan, NOW, "r", filed=filed)
        self.assertEqual(self.table(), before)
        self.assertFalse(self.conn.in_transaction)

    def test_a_failure_before_any_statement_leaves_all_of_it_or_none_of_it(self):
        self.add("a")
        self.add("b", domain="b.example")
        before = self.table()
        probe = Failing(self.conn, 10**6)
        self.assertIsNotNone(crawlstate.reserve(probe, self.plan, NOW, "r", 0)[0])
        statements = probe.calls
        self.assertGreaterEqual(statements, 5)
        self.conn.execute("UPDATE candidates SET status = 'queued', tries = 0, run_id = NULL, updated = added")
        self.conn.execute("DELETE FROM counters")
        self.assertEqual(self.table(), before)
        for n in range(1, statements + 1):
            failing = Failing(self.conn, n)
            with self.subTest(statement=n):
                with self.assertRaises(sqlite3.OperationalError):
                    crawlstate.reserve(failing, self.plan, NOW, "r", 0)
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(self.table(), before)
        done = Failing(self.conn, 10**6)
        self.assertIsNotNone(crawlstate.reserve(done, self.plan, NOW, "r", 0)[0])
        self.assertEqual(self.counters(), {("2026-11-16", "fetch"): 1, ("2026-11-16", "fetch:a.example"): 1})

    def test_two_connections_racing_for_one_row_get_it_once(self):
        self.add("only")
        second = self.other()
        first_row, _ = self.reserve(run="r1")
        again, why = crawlstate.reserve(second, self.plan, NOW, "r2", 0)
        self.assertIsNotNone(first_row)
        self.assertEqual((again, why), (None, "nothing_queued"))
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 1)

    def test_threads_racing_over_many_rows_take_each_row_once_and_count_each_once(self):
        for i in range(12):
            self.add(f"r{i}", domain=f"s{i}.example", weight=i)
        results, errors = [], []
        barrier = threading.Barrier(4)

        def work(name):
            conn = crawlqueue.connect(self.folder)
            try:
                barrier.wait()
                while True:
                    row, why = crawlstate.reserve(conn, self.plan, NOW, name, 0)
                    if row is None:
                        break
                    results.append(row["id"])
            except BaseException as e:           # noqa: BLE001
                errors.append(e)
            finally:
                conn.close()

        threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), list(range(1, 13)))
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 12)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT tries FROM candidates")], [1] * 12)


class Stale(Case):
    def test_a_row_fetching_for_over_30_minutes_goes_back_to_queued_as_a_try_and_the_count_stays(self):
        old = self.add("old", status="fetching", tries=1, updated="2026-11-16T11:29:59Z", run_id="r0")
        edge = self.add("edge", domain="b.example", status="fetching", tries=1, updated="2026-11-16T11:30:00Z")
        fresh = self.add("fresh", domain="c.example", status="fetching", tries=1, updated="2026-11-16T11:45:00Z")
        self.conn.execute("INSERT INTO counters(day, key, n) VALUES ('2026-11-16', 'fetch', 3)")
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, NOW), {"requeued": 1, "failed": 0})
        got = self.row(old)
        self.assertEqual((got["status"], got["tries"], got["next_try"], got["updated"]), ("queued", 1, "2026-11-16T13:00:00Z", "2026-11-16T12:00:00Z"))
        self.assertIn("stalled", got["reason"])
        self.assertEqual(self.row(edge)["status"], "fetching")                    # exactly 30 minutes is not over it
        self.assertEqual(self.row(fresh)["status"], "fetching")
        self.assertEqual(self.counters(), {("2026-11-16", "fetch"): 3})
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, NOW + datetime.timedelta(seconds=1))["requeued"], 1)

    def test_a_row_that_has_reached_its_tries_is_failed_with_a_reason_and_not_queued_again(self):
        gone = self.add("gone", status="fetching", tries=3, updated="2026-11-16T10:00:00Z")
        under = self.add("under", domain="b.example", status="fetching", tries=2, updated="2026-11-16T10:00:00Z")
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, NOW), {"requeued": 1, "failed": 1})
        got = self.row(gone)
        self.assertEqual((got["status"], got["next_try"]), ("failed", None))
        self.assertIn("3", got["reason"])
        self.assertEqual(self.row(under)["status"], "queued")
        self.assertEqual(self.row(under)["next_try"], "2026-11-16T18:00:00Z")      # the second try waits 6 hours

    def test_the_wait_grows_with_the_tries_and_other_rows_are_left_alone(self):
        self.plan = plan(retries=10)
        ids = [self.add(f"t{n}", domain=f"s{n}.example", status="fetching", tries=n, updated="2026-11-16T09:00:00Z") for n in (1, 2, 3, 4)]
        other = [self.add(s, domain=f"{s}.example", status=s, tries=1, updated="2026-11-16T09:00:00Z") for s in ("queued", "kept", "rejected", "failed", "blocked")]
        before = [self.row(i) for i in other]
        crawlstate.requeue_stale(self.conn, self.plan, NOW)
        self.assertEqual([self.row(i)["next_try"] for i in ids], ["2026-11-16T13:00:00Z", "2026-11-16T18:00:00Z", "2026-11-17T12:00:00Z", "2026-11-17T12:00:00Z"])
        self.assertEqual([self.row(i) for i in other], before)

    def test_a_failure_part_way_leaves_every_row_as_it_was(self):
        for n in range(3):
            self.add(f"s{n}", domain=f"s{n}.example", status="fetching", tries=1, updated="2026-11-16T09:00:00Z")
        before = self.table()
        probe = Failing(self.conn, 10**6)
        crawlstate.requeue_stale(probe, self.plan, NOW)
        statements = probe.calls
        self.conn.execute("UPDATE candidates SET status = 'fetching', next_try = NULL, reason = NULL, updated = '2026-11-16T09:00:00Z'")
        self.assertEqual(self.table(), before)
        for n in range(1, statements + 1):
            with self.subTest(statement=n):
                with self.assertRaises(sqlite3.OperationalError):
                    crawlstate.requeue_stale(Failing(self.conn, n), self.plan, NOW)
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(self.table(), before)


class Finish(Case):
    def fetching(self, **kw):
        kw.setdefault("tries", 1)
        return self.add("x", status="fetching", **kw)

    def finish(self, ident, status, reason="", book_id=None, now=NOW, **kw):
        return crawlstate.finish(self.conn, self.plan, ident, status, reason, book_id, now, **kw)

    def test_kept_needs_a_book_and_sets_it_and_only_a_fetching_row_is_finished(self):
        ident = self.fetching()
        with self.assertRaises(KbError):
            self.finish(ident, "kept")
        with self.assertRaises(KbError):
            self.finish(ident, "kept", book_id=5)
        self.assertEqual(self.row(ident)["status"], "fetching")
        self.finish(ident, "kept", "a book", "book-1")
        got = self.row(ident)
        self.assertEqual((got["status"], got["book_id"], got["reason"], got["updated"]), ("kept", "book-1", "a book", "2026-11-16T12:00:00Z"))
        for status in ("kept", "rejected", "failed"):
            with self.assertRaises(KbError):
                self.finish(ident, status, "again", "book-2")
        self.assertEqual(self.row(ident)["book_id"], "book-1")

    def test_rejected_is_final_and_may_carry_the_book_of_a_duplicate(self):
        ident = self.fetching()
        self.finish(ident, "rejected", "already held", "book-9")
        got = self.row(ident)
        self.assertEqual((got["status"], got["reason"], got["book_id"], got["next_try"]), ("rejected", "already held", "book-9", None))
        other = self.add("y", domain="b.example", status="fetching", tries=1)
        self.finish(other, "rejected", "not about the topic")
        self.assertIsNone(self.row(other)["book_id"])

    def test_a_failed_try_waits_1_then_6_then_24_hours_and_the_last_try_is_final(self):
        for tries, wait in ((1, "2026-11-16T13:00:00Z"), (2, "2026-11-16T18:00:00Z")):
            ident = self.add(f"t{tries}", domain=f"s{tries}.example", status="fetching", tries=tries)
            self.finish(ident, "failed", "timed out")
            got = self.row(ident)
            self.assertEqual((got["status"], got["next_try"], got["reason"]), ("queued", wait, "timed out"))
        self.plan = plan(retries=5)
        ident = self.add("t3", domain="s3.example", status="fetching", tries=3)
        self.finish(ident, "failed", "timed out")
        self.assertEqual(self.row(ident)["next_try"], "2026-11-17T12:00:00Z")
        ident = self.add("t4", domain="s4.example", status="fetching", tries=4)
        self.finish(ident, "failed", "timed out")
        self.assertEqual(self.row(ident)["next_try"], "2026-11-17T12:00:00Z")
        self.plan = plan(retries=3)
        last = self.add("last", domain="s5.example", status="fetching", tries=3)
        self.finish(last, "failed", "timed out")
        got = self.row(last)
        self.assertEqual((got["status"], got["next_try"]), ("failed", None))
        self.assertIn("failed 3 times", got["reason"])
        self.assertIn("timed out", got["reason"])
        once = self.add("once", domain="s6.example", status="fetching", tries=1)
        self.plan = plan(retries=1)
        self.finish(once, "failed", "no")
        self.assertEqual(self.row(once)["status"], "failed")

    def test_a_failed_fetch_keeps_its_count_and_a_refusal_waits_a_day_and_counts_for_the_site(self):
        self.reserve_one = self.add("a", status="queued")
        row, _ = self.reserve()
        self.finish(row["id"], "failed", "timed out")
        self.assertEqual(self.counters(), {("2026-11-16", "fetch"): 1, ("2026-11-16", "fetch:a.example"): 1})
        other = self.add("b", domain="b.example", status="fetching", tries=1)
        self.finish(other, "failed", "403", refusal=True)
        got = self.row(other)
        self.assertEqual((got["status"], got["next_try"]), ("queued", "2026-11-17T12:00:00Z"))
        self.assertEqual(self.counters()[("2026-11-16", "refusal:b.example")], 1)
        third = self.add("c", domain="b.example", status="fetching", tries=1)
        self.finish(third, "failed", "429", refusal=True)
        self.assertEqual(self.counters()[("2026-11-16", "refusal:b.example")], 2)

    def test_a_refusal_with_no_tries_left_is_final_and_still_counts(self):
        self.plan = plan(retries=1)
        ident = self.fetching()
        self.finish(ident, "failed", "403", refusal=True)
        self.assertEqual(self.row(ident)["status"], "failed")
        self.assertEqual(self.counters()[("2026-11-16", "refusal:a.example")], 1)

    def test_other_statuses_unknown_rows_and_rows_that_are_not_fetching_are_refused_and_change_nothing(self):
        ident = self.fetching()
        before = self.table()
        for status in ("queued", "fetching", "blocked", "done", "", None, 5, "KEPT"):
            with self.subTest(status=status):
                with self.assertRaises(KbError):
                    self.finish(ident, status, "x", "b")
        for bad in (99999, None, "1", True):
            with self.assertRaises(KbError):
                self.finish(bad, "rejected", "x")
        for status in ("queued", "kept", "rejected", "failed", "blocked"):
            other = self.add(f"o-{status}", domain=f"{status}.example", status=status)
            with self.assertRaises(KbError):
                self.finish(other, "rejected", "x")
        self.assertEqual(self.row(ident)["status"], "fetching")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM counters").fetchone()[0], 0)
        del before

    def test_only_the_run_that_took_the_row_can_finish_it_when_it_says_which_run_it_is(self):
        row_id = self.add("a")
        self.reserve(run="run-a")
        crawlstate.requeue_stale(self.conn, self.plan, NOW + datetime.timedelta(hours=1))                # run A is given up on
        later = NOW + datetime.timedelta(hours=3)
        self.reserve(now=later, run="run-b")                                                              # run B takes it
        with self.assertRaises(KbError):
            crawlstate.finish(self.conn, self.plan, row_id, "kept", "late", "book-1", later, run="run-a")
        self.assertEqual(self.row(row_id)["status"], "fetching")
        crawlstate.finish(self.conn, self.plan, row_id, "kept", "ok", "book-1", later, run="run-b")
        self.assertEqual(self.row(row_id)["status"], "kept")

    def test_a_domain_that_is_not_a_site_is_not_paced_taken_or_counted(self):
        for name, domain in (("empty", ""), ("upper", "Bad.Example"), ("space", "a b"), ("colon", "refusal:x")):
            self.add(name, domain=domain)
        self.assertEqual(self.reserve(), (None, "nothing_queued"))
        self.assertEqual(self.counters(), {})
        odd = self.add("odd", domain="Odd.Example", status="fetching", tries=1)
        self.finish(odd, "failed", "403", refusal=True)
        self.assertEqual(self.counters(), {})

    def test_a_failure_part_way_leaves_the_row_and_the_counter_as_they_were(self):
        ident = self.fetching()
        before = self.table()
        probe = Failing(self.conn, 10**6)
        crawlstate.finish(probe, self.plan, ident, "failed", "403", None, NOW, refusal=True)
        statements = probe.calls
        self.conn.execute("UPDATE candidates SET status = 'fetching', next_try = NULL, reason = NULL, updated = added")
        self.conn.execute("DELETE FROM counters")
        self.assertEqual(self.table(), before)
        for n in range(1, statements + 1):
            with self.subTest(statement=n):
                with self.assertRaises(sqlite3.OperationalError):
                    crawlstate.finish(Failing(self.conn, n), self.plan, ident, "failed", "403", None, NOW, refusal=True)
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(self.table(), before)

    def test_reasons_and_book_names_are_cleaned_and_cut(self):
        ident = self.fetching()
        self.finish(ident, "rejected", "a\x1b[31m red\r\nline‮ " + "zz " * 200, "bk\x00" + "b" * 200)
        got = self.row(ident)
        self.assertLessEqual(len(got["reason"]), 300)
        self.assertTrue(got["reason"].startswith("a[31m red line zz"))
        self.assertNotIn("\x1b", got["reason"])
        self.assertNotIn("‮", got["reason"])
        self.assertEqual(len(got["book_id"]), 120)
        self.assertFalse(any(ord(c) < 32 for c in got["book_id"]))
        other = self.add("o", domain="b.example", status="fetching", tries=1)
        self.finish(other, "rejected", 12345)
        self.assertEqual(self.row(other)["reason"], "12345")
        third = self.add("p", domain="c.example", status="fetching", tries=1)
        self.finish(third, "rejected", None)
        self.assertIsNone(self.row(third)["reason"])

    def test_a_book_name_that_is_empty_once_cleaned_is_not_a_book(self):
        ident = self.fetching()
        for bad in ("", "  ", "\x00\x07", "‮"):
            with self.assertRaises(KbError):
                self.finish(ident, "kept", "", bad)


class Checks(Case):
    def test_a_time_in_a_zone_with_a_change_of_clock_is_added_to_as_elapsed_time(self):
        import zoneinfo
        ny = zoneinfo.ZoneInfo("America/New_York")
        start = datetime.datetime(2026, 11, 1, 0, 30, tzinfo=ny)                    # 04:30Z, the night the clocks go back
        self.assertEqual(start.astimezone(UTC).strftime("%H:%M"), "04:30")
        ident = self.add("a", status="fetching", tries=2)
        crawlstate.finish(self.conn, self.plan, ident, "failed", "x", None, start)
        self.assertEqual(self.row(ident)["next_try"], "2026-11-01T10:30:00Z")        # 6 hours later, not 11:30Z
        stale = self.add("s", domain="s.example", status="fetching", tries=1, updated="2026-11-01T06:00:00Z")
        early = datetime.datetime(2026, 11, 1, 2, 31, tzinfo=ny)                    # 07:31Z: over 30 minutes after 06:00Z
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, early)["requeued"], 1)
        self.assertEqual(self.row(stale)["status"], "queued")
        fresh = self.add("f", domain="f.example", status="fetching", tries=1, updated="2026-11-01T07:00:00Z")
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, datetime.datetime(2026, 11, 1, 2, 29, tzinfo=ny))["requeued"], 0)      # 07:29Z
        self.assertEqual(self.row(fresh)["status"], "fetching")

    def test_the_stale_limit_is_30_elapsed_minutes_even_across_the_change_of_clock(self):
        import zoneinfo
        ny = zoneinfo.ZoneInfo("America/New_York")
        now = datetime.datetime(2026, 11, 1, 1, 10, tzinfo=ny, fold=1)              # 06:10Z, the second 01:10 of the night
        self.assertEqual(now.astimezone(UTC).strftime("%H:%M"), "06:10")
        over = self.add("over", status="fetching", tries=1, updated="2026-11-01T05:39:00Z")      # 31 minutes before
        under = self.add("under", domain="u.example", status="fetching", tries=1, updated="2026-11-01T05:41:00Z")
        self.assertEqual(crawlstate.requeue_stale(self.conn, self.plan, now)["requeued"], 1)
        self.assertEqual((self.row(over)["status"], self.row(under)["status"]), ("queued", "fetching"))

    def test_a_transaction_the_caller_has_open_is_not_broken_by_an_operation(self):
        self.add("a")
        self.conn.execute("BEGIN")
        with self.assertRaises(sqlite3.OperationalError):
            self.reserve()
        self.assertTrue(self.conn.in_transaction)                                    # the caller's own transaction is still open
        self.conn.execute("ROLLBACK")
        self.assertIsNotNone(self.reserve()[0])

    def test_a_time_without_a_zone_is_refused_by_every_operation_and_changes_nothing(self):
        naive = datetime.datetime(2026, 11, 16, 12)
        ident = self.add("a")
        fetching = self.add("f", domain="f.example", status="fetching", tries=1, updated="2026-11-16T08:00:00Z")
        before = self.table()
        for call in (lambda: crawlstate.block(self.conn, ident, "x", naive), lambda: crawlstate.requeue_stale(self.conn, self.plan, naive),
                     lambda: crawlstate.finish(self.conn, self.plan, fetching, "rejected", "x", None, naive), lambda: crawlstate.reserve_card(self.conn, self.plan, naive),
                     lambda: crawlstate.note_refusal(self.conn, self.plan, naive, "a.example"), lambda: crawlstate.ceilings(self.conn, self.plan, naive)):
            with self.assertRaises(KbError):
                call()
        self.assertEqual(self.table(), before)

    def test_a_plan_that_is_not_a_table_of_whole_numbers_is_refused_by_every_operation(self):
        ident = self.add("f", status="fetching", tries=1)
        for call in (lambda: crawlstate.finish(self.conn, None, ident, "failed", "x", None, NOW), lambda: crawlstate.requeue_stale(self.conn, {}, NOW),
                     lambda: crawlstate.reserve_card(self.conn, dict(self.plan, cards_per_day=True), NOW), lambda: crawlstate.note_refusal(self.conn, [], NOW, "a.example"),
                     lambda: crawlstate.ceilings(self.conn, dict(self.plan, fetches_per_day=0), NOW), lambda: crawlstate.ceilings(self.conn, dict(self.plan, filed_total=True), NOW),
                     lambda: crawlstate.finish(self.conn, dict(self.plan, retries=0), ident, "failed", "x", None, NOW)):
            with self.assertRaises(KbError):
                call()
        self.assertEqual(self.row(ident)["status"], "fetching")

    def test_a_truth_value_is_not_a_candidate_number_and_a_refusal_is_only_a_failed_try(self):
        queued = self.add("q")
        self.assertEqual(queued, 1)
        with self.assertRaises(KbError):
            crawlstate.block(self.conn, True, "x", NOW)
        self.assertEqual(self.row(queued)["status"], "queued")
        fetching = self.add("f", domain="f.example", status="fetching", tries=1)
        for status in ("kept", "rejected"):
            with self.assertRaises(KbError):
                crawlstate.finish(self.conn, self.plan, fetching, status, "x", "book-1", NOW, refusal=True)
        for refusal in ("yes", 1, None):
            with self.assertRaises(KbError):
                crawlstate.finish(self.conn, self.plan, fetching, "failed", "x", None, NOW, refusal=refusal)
        self.assertEqual(self.row(fetching)["status"], "fetching")
        self.assertEqual(self.counters(), {})


class Block(Case):
    def test_only_a_queued_row_is_blocked_with_its_reason(self):
        ident = self.add("a")
        crawlstate.block(self.conn, ident, "list:phishing_domains", NOW)
        got = self.row(ident)
        self.assertEqual((got["status"], got["reason"], got["updated"]), ("blocked", "list:phishing_domains", "2026-11-16T12:00:00Z"))
        for status in ("fetching", "kept", "rejected", "failed", "blocked"):
            other = self.add(f"o-{status}", domain=f"{status}.example", status=status)
            with self.assertRaises(KbError):
                crawlstate.block(self.conn, other, "x", NOW)
            self.assertEqual(self.row(other)["status"], status)
        for bad in (99999, None, "1", True):
            with self.assertRaises(KbError):
                crawlstate.block(self.conn, bad, "x", NOW)

    def test_the_reason_is_cleaned_and_a_blocked_row_is_never_taken(self):
        ident = self.add("a")
        crawlstate.block(self.conn, ident, "a\x1b[0m" + "q " * 400, NOW)
        self.assertLessEqual(len(self.row(ident)["reason"]), 300)
        self.assertNotIn("\x1b", self.row(ident)["reason"])
        self.assertEqual(self.reserve(), (None, "nothing_queued"))


class Counters(Case):
    def test_cards_are_reserved_up_to_the_day_and_a_new_day_starts_again(self):
        self.plan = plan(cards_per_day=2)
        self.assertTrue(crawlstate.reserve_card(self.conn, self.plan, NOW))
        self.assertTrue(crawlstate.reserve_card(self.conn, self.plan, NOW))
        self.assertFalse(crawlstate.reserve_card(self.conn, self.plan, NOW))
        self.assertEqual(self.counters()[("2026-11-16", "card")], 2)
        self.assertTrue(crawlstate.reserve_card(self.conn, self.plan, NOW + datetime.timedelta(days=1)))

    def test_a_hop_to_another_site_is_counted_apart_up_to_the_same_cap_and_not_when_it_is_stopped(self):
        self.plan = plan(per_domain_per_day=2, domain_refusals=2)
        self.assertEqual([crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example") for _ in range(3)], ["", "", "the site is at its limit for the day"])
        self.assertEqual(self.counters()[("2026-11-16", "hop:v.example")], 2)
        self.assertNotIn(("2026-11-16", "fetch:v.example"), self.counters())              # the units that `reserve` reads are not touched
        crawlstate.note_refusal(self.conn, self.plan, NOW, "w.example")
        crawlstate.note_refusal(self.conn, self.plan, NOW, "w.example")
        self.assertEqual(crawlstate.charge_hop(self.conn, self.plan, NOW, "w.example"), "the site is stopped for the day")
        self.assertNotIn(("2026-11-16", "hop:w.example"), self.counters())
        self.assertEqual(crawlstate.charge_hop(self.conn, self.plan, NOW + datetime.timedelta(days=1), "v.example"), "")      # a new day
        for bad in ("", "A.example", "a b", None, 3, "x" * 300):
            with self.subTest(bad), self.assertRaises(KbError):
                crawlstate.charge_hop(self.conn, self.plan, NOW, bad)

    def test_hops_to_a_site_leave_all_its_units_to_the_candidates_that_are_queued_for_it(self):
        self.plan = plan(per_domain_per_day=3)
        ids = [self.add(f"c{n}", domain="v.example") for n in range(3)]
        self.assertEqual([crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example") for _ in range(4)], ["", "", "", "the site is at its limit for the day"])
        taken = [self.reserve(run=f"run-{n}")[0] for n in range(3)]
        self.assertEqual([row["id"] for row in taken], ids)                                  # the three real candidates are all taken
        self.assertEqual(self.reserve(run="run-9"), (None, "nothing_queued"))
        self.assertEqual((self.counters()[("2026-11-16", "fetch:v.example")], self.counters()[("2026-11-16", "hop:v.example")]), (3, 3))

    def test_a_hop_to_a_site_whose_real_fetches_are_at_the_cap_is_refused_and_counts_nothing(self):
        self.plan = plan(per_domain_per_day=2)
        for n in range(2):
            self.add(f"c{n}", domain="v.example")
            self.assertIsNotNone(self.reserve(run=f"run-{n}")[0])
        self.assertEqual(crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example"), "the site is at its limit for the day")
        self.assertNotIn(("2026-11-16", "hop:v.example"), self.counters())

    def test_hops_do_not_count_toward_the_fetches_of_the_day(self):
        self.plan = plan(fetches_per_day=1)
        self.add("c", domain="a.example")
        for _ in range(3):
            crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example")
        self.assertIsNotNone(self.reserve()[0])                                               # the one fetch of the day is still there
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 1)                        # only the candidate's own fetch is in the day's count

    def test_the_hop_counters_of_two_sites_are_independent_and_a_new_day_starts_afresh(self):
        self.plan = plan(per_domain_per_day=1)
        self.assertEqual((crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example"), crawlstate.charge_hop(self.conn, self.plan, NOW, "w.example")), ("", ""))
        self.assertEqual(crawlstate.charge_hop(self.conn, self.plan, NOW, "v.example"), "the site is at its limit for the day")
        self.assertEqual(crawlstate.charge_hop(self.conn, self.plan, NOW + datetime.timedelta(days=1), "v.example"), "")

    def test_a_failure_part_way_through_a_hop_charge_counts_nothing(self):
        before = self.table()
        probe = Failing(self.conn, 10**6)
        crawlstate.charge_hop(probe, self.plan, NOW, "v.example")
        statements = probe.calls
        self.conn.execute("DELETE FROM counters")
        for n in range(1, statements + 1):
            with self.subTest(statement=n):
                with self.assertRaises(sqlite3.OperationalError):
                    crawlstate.charge_hop(Failing(self.conn, n), self.plan, NOW, "v.example")
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(self.table(), before)

    def test_a_card_failure_part_way_loses_nothing_and_counts_nothing(self):
        before = self.table()
        probe = Failing(self.conn, 10**6)
        crawlstate.reserve_card(probe, self.plan, NOW)
        statements = probe.calls
        self.conn.execute("DELETE FROM counters")
        for n in range(1, statements + 1):
            with self.subTest(statement=n):
                with self.assertRaises(sqlite3.OperationalError):
                    crawlstate.reserve_card(Failing(self.conn, n), self.plan, NOW)
                self.assertFalse(self.conn.in_transaction)
                self.assertEqual(self.table(), before)

    def test_threads_reserving_cards_never_pass_the_ceiling(self):
        self.plan = plan(cards_per_day=7)
        got, errors = [], []
        barrier = threading.Barrier(4)

        def work():
            conn = crawlqueue.connect(self.folder)
            try:
                barrier.wait()
                for _ in range(5):
                    got.append(crawlstate.reserve_card(conn, self.plan, NOW))
            except BaseException as e:           # noqa: BLE001
                errors.append(e)
            finally:
                conn.close()

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(got.count(True), 7)
        self.assertEqual(self.counters()[("2026-11-16", "card")], 7)

    def test_threads_charging_hops_never_pass_a_sites_cap(self):
        self.plan = plan(per_domain_per_day=7)
        got, errors = [], []
        barrier = threading.Barrier(4)

        def work():
            conn = crawlqueue.connect(self.folder)
            try:
                barrier.wait()
                for _ in range(5):
                    got.append(crawlstate.charge_hop(conn, self.plan, NOW, "v.example"))
            except BaseException as e:           # noqa: BLE001
                errors.append(e)
            finally:
                conn.close()

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(got.count(""), 7)
        self.assertEqual(self.counters()[("2026-11-16", "hop:v.example")], 7)

    def test_a_refusal_is_counted_for_its_site_in_the_plans_day(self):
        self.plan = plan(timezone="Asia/Tokyo")
        crawlstate.note_refusal(self.conn, self.plan, NOW, "bad.example")
        crawlstate.note_refusal(self.conn, self.plan, NOW, "bad.example")
        crawlstate.note_refusal(self.conn, self.plan, datetime.datetime(2026, 11, 16, 15, 30, tzinfo=UTC), "bad.example")
        self.assertEqual(self.counters(), {("2026-11-16", "refusal:bad.example"): 2, ("2026-11-17", "refusal:bad.example"): 1})
        for site in ("", None, 5, "a b", "x/y", "A\x00", "x" * 254, "refusal:x"):
            with self.assertRaises(KbError):
                crawlstate.note_refusal(self.conn, self.plan, NOW, site)

    def test_the_ceilings_are_read_without_changing_anything(self):
        self.plan = plan(fetches_per_day=5, cards_per_day=4, filed_total=9)
        self.add("a")
        self.add("b", domain="b.example")
        self.reserve()
        self.reserve()
        crawlstate.reserve_card(self.conn, self.plan, NOW)
        before = self.table()
        got = crawlstate.ceilings(self.conn, self.plan, NOW, filed=3)
        self.assertEqual(got, {"day": "2026-11-16", "fetch": (2, 5), "card": (1, 4), "filed": (3, 9)})
        self.assertEqual(crawlstate.ceilings(self.conn, self.plan, NOW)["filed"], (None, 9))
        self.assertEqual(crawlstate.ceilings(self.conn, self.plan, NOW + datetime.timedelta(days=1))["fetch"], (0, 5))
        self.assertNotEqual(self.plan["filed_total"], self.plan["fetches_per_day"])
        self.assertEqual(self.table(), before)
        self.assertFalse(self.conn.in_transaction)

    def test_the_books_filed_are_those_with_a_crawl_found_event_counted_once(self):
        events = {
            "b1": [{"event": "created", "at": "x"}, {"event": "crawl_found", "at": "x"}],
            "b2": [{"event": "created", "at": "x"}],
            "b3": [{"event": "crawl_found", "at": "x"}, {"event": "crawl_found", "at": "y"}],
            "b4": [],
            "b5": [{"event": "crawl_found", "at": "x"}, {"event": "weeded", "at": "y"}],
            "b6": [{"event": "crawl_found", "at": "x"}] * 3,
            "b7": [{"event": "weeded", "at": "x"}],
            "b8": [{"event": "weeded", "at": "x"}, {"event": "weeded", "at": "y"}],
            "b9": [{"event": "weeded", "at": "x"}],
        }
        self.assertEqual(crawlstate.filed_total(events), 4)
        self.assertEqual(crawlstate.filed_total({}), 0)
        for bad in (None, [], "x", {"b": "event"}, {"b": [5]}, {"b": [{"at": "x"}]}, {"b": [{"event": 5}]}, {5: []}):
            with self.assertRaises(KbError):
                crawlstate.filed_total(bad)


class Wiring(Case):
    def test_no_function_deletes_a_row_and_none_adds_one_or_drops_a_table(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlstate.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("DELETE", "DROP", "INSERT INTO candidates", "REPLACE INTO", "INSERT OR REPLACE", "TRUNCATE", "ALTER"):
            self.assertNotIn(word, source, word)
        for word in ("socket", "urllib", "subprocess", "os.environ", "getenv", "webclient"):
            self.assertNotIn(word, source, word)

    def test_all_the_operations_together_never_remove_a_row(self):
        ids = [self.add(f"r{i}", domain=f"s{i}.example") for i in range(6)]
        crawlstate.block(self.conn, ids[0], "x", NOW)
        a, _ = self.reserve()
        b, _ = self.reserve()
        crawlstate.finish(self.conn, self.plan, a["id"], "kept", "ok", "book-1", NOW)
        crawlstate.finish(self.conn, self.plan, b["id"], "failed", "403", None, NOW, refusal=True)
        crawlstate.requeue_stale(self.conn, self.plan, NOW + datetime.timedelta(days=3))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 6)
        self.assertEqual(sorted(r[0] for r in self.conn.execute("SELECT id FROM candidates")), sorted(ids))

    def test_the_queue_module_itself_still_has_no_update_in_it(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlqueue.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("UPDATE", source)
        self.assertNotIn("DELETE", source)

    def test_counts_of_the_queue_follow_the_transitions(self):
        for i in range(3):
            self.add(f"r{i}", domain=f"s{i}.example")
        a, _ = self.reserve()
        self.assertEqual(crawlqueue.counts(self.conn)["fetching"], 1)
        crawlstate.finish(self.conn, self.plan, a["id"], "rejected", "no", None, NOW)
        got = crawlqueue.counts(self.conn)
        self.assertEqual((got["queued"], got["fetching"], got["rejected"]), (2, 0, 1))


if __name__ == "__main__":
    unittest.main()
