"""The report of a day of the unattended crawl (`kb/crawlreport.py`; `docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`, Increments E and F).

Every test runs on a temporary index root and on hand-made fixture files in the spec's log format. No test opens a socket, reads the owner's library,
config, plan or keys, or writes outside its temporary folder. Hostile text is made with `chr()` and plain strings here, never typed as hidden characters."""

import datetime
import json
import os
import re
import shutil
import stat
import time
import unittest
from pathlib import Path
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_crawlstatus import GOOD_BREAKER, RLO, SIDE_FILES, ZWSP, QueueBase, StateBase, raw

from kb import KbError, crawlqueue, crawlreport as cr, crawlstatus as cs

FIX = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawlstatus"
UTC = datetime.timezone.utc
DAY = datetime.date(2026, 11, 18)
NOW = datetime.datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
HOSTILE = ["[x](http://evil.example/)", "![i](http://evil.example/i.png)", "# h", "| a |", "<b>bold</b>", "a`b`c", "-----", "***", "> quote", "&lt;i&gt;"]


def snapshot(root):
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in Path(root).rglob("*")}


class ReportBase(QueueBase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))  # a folder made by a test is private, as the runner makes its own

    def put_day_log(self, name="crawl-2026-11-18.jsonl"):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / "report" / "crawl-2026-11-18.jsonl", folder / name)

    def row(self, conn, key, status, updated, *, domain="example.org", reason=None, book_id=None, address=None):
        self.put(conn, key, status, updated, domain=domain, reason=reason)
        conn.execute("UPDATE candidates SET book_id = ?, address = ? WHERE identity_key = ?", (book_id, address or f"https://{domain or 'none.example'}/{key}", key))

    def day_rows(self, conn):
        self.row(conn, "a", "kept", "2026-11-18T05:01:06Z", domain="example.org", book_id="b-001", address="https://example.org/a")
        self.row(conn, "c", "kept", "2026-11-18T05:03:03Z", domain="example.com", book_id="b-003", address="https://example.com/c")
        self.row(conn, "b", "rejected", "2026-11-18T05:02:06Z", domain="example.net", reason="below the threshold", address="https://example.net/b")
        self.row(conn, "d", "failed", "2026-11-18T05:50:00Z", domain="flaky.example", reason="timeout", address="https://flaky.example/d")
        self.row(conn, "e", "failed", "2026-11-18T07:00:11Z", domain="example.org", reason="connection reset", address="https://example.org/e")
        for key, domain in (("t1", "publisher.example"), ("t2", "publisher.example"), ("t3", "other.example"), ("t4", None)):
            self.row(conn, key, "rejected", "2026-11-18T05:00:05Z", domain=domain, reason="type")
        self.row(conn, "old", "kept", "2026-11-17T05:00:00Z", domain="old.example", book_id="b-old")
        self.row(conn, "oldfail", "failed", "2026-11-19T00:00:00Z", domain="old.example", reason="HTTP 500")

    def full_day(self):
        self.put_day_log()
        self.day_rows(self.make_queue())
        self.good_breaker()

    def quiet_day(self):
        """The same day with no connection left open to the queue, so that the files a reader makes beside it are the reader's."""
        self.put_day_log()
        w = self.make_queue()
        self.day_rows(w)
        w.close()
        self.good_breaker()

    def build(self, zone="UTC", day=DAY, now=NOW):
        return cr.build(self.tmp, day, zone, now)


class BuildTest(ReportBase):
    def test_the_fixture_has_every_step_and_outcome_of_the_spec(self):
        steps, outcomes = set(), set()
        for line in (FIX / "report" / "crawl-2026-11-18.jsonl").read_text().splitlines():
            record = json.loads(line)
            steps.add(record["step"])
            outcomes.add(record["outcome"])
        self.assertEqual((steps, outcomes), (set(cs.STEPS), set(cs.OUTCOMES)))

    def test_the_counts_of_the_day_from_the_log(self):
        self.full_day()
        got = self.build()
        self.assertEqual(got["counts"], {"fetched": 3, "fetch_failed": 2, "kept": 1, "rejected": 1, "failed": 2, "fail_lines": 4})
        self.assertEqual((got["day"], got["zone"], got["generated"]), ("2026-11-18", "UTC", "2026-11-18T12:00:00Z"))
        self.assertEqual({k: got["log"][k] for k in ("lines", "first", "last", "bad", "cut", "problem")},
                         {"lines": 38, "first": "2026-11-18T05:00:00Z", "last": "2026-11-18T09:00:00Z", "bad": {}, "cut": False, "problem": None})

    def test_the_lines_by_step_and_outcome(self):
        self.full_day()
        steps = self.build()["steps"]
        self.assertEqual(set(steps), set(cs.STEPS))
        self.assertEqual((steps["fetch"], steps["fail"], steps["refuse"], steps["breaker"], steps["scan"]),
                         ({"ok": 3, "failed": 2}, {"failed": 4}, {"refused": 3}, {"tripped": 1}, {"ok": 1, "skipped": 1}))

    def test_the_runs_of_the_day_and_the_refused_firings_that_are_not_runs(self):
        self.full_day()
        runs = self.build()["runs"]
        self.assertEqual((runs["started"], runs["ended"], runs["ended_by_outcome"]), (2, 2, {"ok": 1, "tripped": 1}))
        self.assertEqual((runs["refused"], runs["refused_by_reason"]), (3, {"a run is in progress": 2, "the breaker is tripped": 1}))

    def test_the_day_is_the_plans_day_by_ts_and_not_by_the_file(self):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        for name in ("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"):
            shutil.copy(FIX / "log" / name, folder / name)
        got = self.build(zone="America/New_York", day=datetime.date(2026, 11, 16))
        self.assertEqual((got["log"]["lines"], got["log"]["first"], got["log"]["last"]), (7, "2026-11-16T05:00:00Z", "2026-11-17T04:59:59Z"))
        self.assertEqual((got["counts"]["fetched"], got["counts"]["fetch_failed"]), (2, 1))
        self.assertEqual(got["log"]["dates"], ["2026-11-16", "2026-11-17"])

    def test_the_log_and_the_queue_are_compared_and_a_difference_is_shown_and_not_hidden(self):
        self.full_day()
        got = self.build()
        self.assertEqual(got["queue"], {"status": "ok", "reason": None, "counts": {"kept": 2, "rejected": 1, "rejected_type": 4, "failed": 2}})
        self.assertEqual(got["compare"], [{"what": "kept", "log": 1, "queue": 2, "same": False}, {"what": "rejected", "log": 1, "queue": 1, "same": True},
                                          {"what": "failed", "log": 2, "queue": 2, "same": True}])

    def test_a_log_and_a_queue_that_agree_are_said_to_agree(self):
        self.put_day_log()
        w = self.make_queue()
        self.day_rows(w)
        w.execute("DELETE FROM candidates WHERE identity_key = 'c'")
        self.assertTrue(all(c["same"] for c in self.build()["compare"]))

    def test_rows_of_other_days_are_not_counted(self):
        self.full_day()
        counts = self.build()["queue"]["counts"]
        self.assertEqual((counts["kept"], counts["failed"]), (2, 2))

    def test_without_a_queue_the_parts_that_need_it_say_so_and_the_log_parts_stand(self):
        self.put_day_log()
        got = self.build()
        self.assertEqual((got["queue"]["status"], got["queue"]["counts"], got["compare"], got["rejected_for_type"]), ("missing", None, None, None))
        self.assertEqual(got["failures_by_reason"]["queue"], None)
        self.assertEqual((got["counts"]["fetched"], len(got["filed"]["books"])), (3, 3))

    def test_a_queue_that_is_busy_or_bad_is_said_with_its_reason(self):
        self.put_day_log()
        for status in ("busy", "bad"):
            with self.subTest(status=status), mock.patch.object(cs, "open_queue", return_value=cs.QueueOpen(None, status, "the queue is " + status)):
                got = self.build()
                self.assertEqual((got["queue"]["status"], got["queue"]["reason"], got["compare"]), (status, "the queue is " + status, None))

    def test_no_log_is_a_day_with_no_lines(self):
        got = self.build()
        self.assertEqual((got["log"]["lines"], got["log"]["first"], got["counts"]["fetched"], got["runs"]["started"]), (0, None, 0, 0))
        self.assertEqual((got["filed"]["books"], got["breaker"]["pauses"], got["lists_failed"]), ([], [], []))

    def test_bad_lines_and_a_cut_are_passed_on(self):
        self.put_day_log()
        with open(self.tmp / "crawl" / "log" / "crawl-2026-11-18.jsonl", "ab") as f:
            f.write(b"junk\n[1]\n")
        got = self.build()["log"]
        self.assertEqual((got["bad"], got["lines"]), ({"not_json": 1, "not_object": 1}, 38))

    def test_the_books_filed_by_address_and_host_each_once_in_time_order(self):
        self.full_day()
        books = self.build()["filed"]
        self.assertEqual((books["total"], books["truncated"]), (3, False))
        self.assertEqual(books["books"], [
            {"ts": "2026-11-18T05:01:02Z", "book": "b-001", "address": "https://example.org/a", "host": "example.org", "seen_in": "both"},
            {"ts": "2026-11-18T05:02:02Z", "book": "b-002", "address": None, "host": "example.net", "seen_in": "log"},
            {"ts": "2026-11-18T05:03:02Z", "book": "b-003", "address": "https://example.com/c", "host": "example.com", "seen_in": "both"}])

    def test_a_book_only_the_queue_knows_is_listed_and_a_row_with_no_book_is_not(self):
        self.full_day()
        w = self.make_queue()
        self.row(w, "x", "kept", "2026-11-18T06:30:00Z", domain="queue-only.example", book_id="b-009", address="https://queue-only.example/x")
        self.row(w, "y", "kept", "2026-11-18T06:40:00Z", domain="nobook.example", book_id=None)
        books = self.build()["filed"]["books"]
        self.assertEqual([b["book"] for b in books], ["b-001", "b-002", "b-003", "b-009"])
        self.assertEqual(books[-1], {"ts": "2026-11-18T06:30:00Z", "book": "b-009", "address": "https://queue-only.example/x", "host": "queue-only.example",
                                     "seen_in": "queue"})

    def test_a_capture_line_with_no_address_or_host_takes_them_from_the_queue_row_of_the_same_book(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="capture", outcome="ok", book="b-5"))
        self.row(self.make_queue(), "k", "kept", "2026-11-18T05:00:01Z", domain="rows.example", book_id="b-5", address="https://rows.example/k")
        self.assertEqual(self.build()["filed"]["books"], [{"ts": "2026-11-18T05:00:00Z", "book": "b-5", "address": "https://rows.example/k", "host": "rows.example",
                                                           "seen_in": "both"}])

    def test_a_book_captured_twice_is_listed_once_and_a_capture_that_is_not_ok_is_not_a_filing(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="capture", outcome="ok", book="b-1", candidate=1),
                     dict(ts="2026-11-18T05:00:05Z", run="r1", step="capture", outcome="ok", book="b-1", candidate=1),
                     dict(ts="2026-11-18T05:01:00Z", run="r1", step="capture", outcome="failed", book="b-2", candidate=2),
                     dict(ts="2026-11-18T05:02:00Z", run="r1", step="capture", outcome="ok", book=None, candidate=3))
        self.assertEqual([b["book"] for b in self.build()["filed"]["books"]], ["b-1"])

    def test_the_books_listed_are_bounded_and_the_total_is_said(self):
        self.put_log("2026-11-18", *[dict(ts=f"2026-11-18T05:{i:02d}:00Z", run="r1", step="capture", outcome="ok", book=f"b-{i:02d}") for i in range(30)])
        with mock.patch.object(cr, "MAX_FILED", 10):
            books = self.build()["filed"]
        self.assertEqual((len(books["books"]), books["total"], books["truncated"]), (10, 30, True))
        self.assertEqual(books["books"][0]["book"], "b-00")

    def test_a_candidate_rejected_twice_is_one_and_lines_with_no_candidate_are_each_one(self):
        self.put_log("2026-11-18",
                     *[dict(ts=f"2026-11-18T05:0{i}:00Z", run="r1", step="reject", outcome="rejected", candidate=1) for i in range(3)],
                     *[dict(ts=f"2026-11-18T06:0{i}:00Z", run="r1", step="fail", outcome="failed") for i in range(2)],
                     dict(ts="2026-11-18T07:00:00Z", run="r1", step="fail", outcome="failed", candidate=2),
                     dict(ts="2026-11-18T07:00:01Z", run="r1", step="fail", outcome="failed", candidate=2))
        got = self.build()["counts"]
        self.assertEqual((got["rejected"], got["failed"], got["fail_lines"]), (1, 3, 4))

    def test_a_row_at_the_first_second_of_the_day_is_in_it_and_one_at_the_first_second_of_the_next_is_not(self):
        w = self.make_queue()
        self.row(w, "first", "kept", "2026-11-18T00:00:00Z", book_id="b-first")
        self.row(w, "last", "kept", "2026-11-18T23:59:59Z", book_id="b-last")
        self.row(w, "next", "kept", "2026-11-19T00:00:00Z", book_id="b-next")
        self.row(w, "before", "kept", "2026-11-17T23:59:59Z", book_id="b-before")
        got = self.build()
        self.assertEqual(got["queue"]["counts"]["kept"], 2)
        self.assertEqual([b["book"] for b in got["filed"]["books"]], ["b-first", "b-last"])

    def test_a_book_only_the_queue_knows_that_was_filed_before_the_logs_books_is_listed_first(self):
        self.full_day()
        self.row(self.make_queue(), "early", "kept", "2026-11-18T04:00:00Z", domain="early.example", book_id="b-early", address="https://early.example/e")
        self.assertEqual([b["book"] for b in self.build()["filed"]["books"]][:2], ["b-early", "b-001"])

    def test_the_first_capture_of_a_book_gives_its_time_and_its_host_and_the_queue_gives_the_address(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="capture", outcome="ok", book="b-1", candidate=1, host="log.example"),
                     dict(ts="2026-11-18T05:30:00Z", run="r1", step="capture", outcome="ok", book="b-1", candidate=1, host="again.example"))
        self.row(self.make_queue(), "k", "kept", "2026-11-18T06:00:00Z", domain="queue.example", book_id="b-1", address="https://queue.example/1")
        self.assertEqual(self.build()["filed"]["books"], [{"ts": "2026-11-18T05:00:00Z", "book": "b-1", "address": "https://queue.example/1", "host": "log.example",
                                                           "seen_in": "both"}])

    def test_the_queue_rows_read_for_the_books_are_one_more_than_the_limit_so_that_a_cut_is_known(self):
        w = self.make_queue()
        for i in range(6):
            self.row(w, f"q{i}", "kept", f"2026-11-18T05:0{i}:00Z", domain="q.example", book_id=f"b-{i}")
        with mock.patch.object(cr, "MAX_FILED", 3):
            got = self.build()["filed"]
        self.assertEqual((len(got["books"]), got["total"], got["truncated"]), (3, 4, True))
        with mock.patch.object(cr, "MAX_FILED", 6):
            got = self.build()["filed"]
        self.assertEqual((len(got["books"]), got["total"], got["truncated"]), (6, 6, False))

    def test_a_failed_row_with_no_reason_is_named_in_the_queues_failures(self):
        w = self.make_queue()
        self.row(w, "n", "failed", "2026-11-18T05:00:00Z", reason=None)
        self.row(w, "m", "failed", "2026-11-18T05:00:01Z", reason="HTTP" + ZWSP + " 503")
        self.row(w, "o", "failed", "2026-11-18T05:00:02Z", reason="HTTP 503")
        self.assertEqual(self.build()["failures_by_reason"]["queue"], [{"reason": "HTTP 503", "n": 2}, {"reason": "(no reason)", "n": 1}])

    def test_the_time_must_be_a_time_with_a_zone_and_the_zone_must_be_known(self):
        for bad in (datetime.datetime(2026, 11, 18, 12, 0, 0), "2026-11-18T12:00:00Z", None):
            with self.subTest(now=bad), self.assertRaises(KbError):
                self.build(now=bad)
        with self.assertRaises(KbError):
            self.build(zone="Mars/Olympus")

    def test_a_book_judged_twice_is_one_kept_and_a_judge_line_with_no_book_is_each_one(self):
        self.put_log("2026-11-18",
                     dict(ts="2026-11-18T05:00:00Z", run="r1", step="judge", outcome="ok", book="b-1"),
                     dict(ts="2026-11-18T05:00:01Z", run="r1", step="judge", outcome="ok", book="b-1"),
                     dict(ts="2026-11-18T05:00:02Z", run="r1", step="judge", outcome="ok"),
                     dict(ts="2026-11-18T05:00:03Z", run="r1", step="judge", outcome="ok"),
                     dict(ts="2026-11-18T05:00:04Z", run="r1", step="judge", outcome="rejected", book="b-9"))
        self.assertEqual(self.build()["counts"]["kept"], 3)

    def test_a_stop_line_or_a_breaker_line_that_is_not_tripped_is_not_a_pause(self):
        self.put_log("2026-11-18",
                     dict(ts="2026-11-18T05:00:00Z", run="r1", step="stop", outcome="tripped", reason="not a pause"),
                     dict(ts="2026-11-18T05:00:01Z", run="r1", step="breaker", outcome="ok", reason="not a pause either"),
                     dict(ts="2026-11-18T05:00:02Z", run="r1", step="breaker", outcome="tripped", reason="a pause"))
        self.assertEqual([p["reason"] for p in self.build()["breaker"]["pauses"]], ["a pause"])

    def test_a_list_update_with_no_host_has_no_name(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="list_update", outcome="failed", reason="x"))
        self.assertEqual(self.build()["lists_failed"][0]["list"], None)

    def test_a_row_that_is_not_kept_or_not_rejected_for_its_type_is_not_in_those_parts(self):
        w = self.make_queue()
        self.row(w, "q", "queued", "2026-11-18T05:00:00Z", domain="queued.example", book_id="b-q", reason="type")
        self.row(w, "f", "failed", "2026-11-18T05:00:01Z", domain="failed.example", reason="type")
        self.row(w, "k", "kept", "2026-11-18T05:00:02Z", domain="kept.example", book_id="b-k", reason="type")
        got = self.build()
        self.assertEqual([b["book"] for b in got["filed"]["books"]], ["b-k"])
        self.assertEqual(got["rejected_for_type"], {"n": 0, "hosts": [], "hosts_total": 0})
        self.assertEqual(got["queue"]["counts"]["rejected_type"], 0)

    def test_when_the_queue_has_more_books_than_the_limit_the_earliest_are_taken(self):
        w = self.make_queue()
        for i, hour in enumerate((9, 7, 5, 8, 6)):
            self.row(w, f"q{i}", "kept", f"2026-11-18T0{hour}:00:00Z", domain="q.example", book_id=f"b-{hour}")
        with mock.patch.object(cr, "MAX_FILED", 2):
            got = self.build()["filed"]
        self.assertEqual(([b["book"] for b in got["books"]], got["total"], got["truncated"]), (["b-5", "b-6"], 3, True))

    def test_a_kept_row_whose_book_is_not_text_is_not_a_book(self):
        w = self.make_queue()
        self.row(w, "k", "kept", "2026-11-18T05:00:00Z", book_id="b-k")
        self.row(w, "n", "kept", "2026-11-18T05:00:01Z", book_id="x")
        w.execute("UPDATE candidates SET book_id = x'4142' WHERE identity_key = 'n'")
        self.assertEqual([b["book"] for b in self.build()["filed"]["books"]], ["b-k"])

    def test_the_hosts_rejected_for_their_type_are_in_order_and_a_host_with_no_name_is_one_and_last(self):
        w = self.make_queue()
        for key, domain, n in (("a", "x.example", 2), ("b", None, 2), ("c", "", 1), ("d", "a.example", 2), ("e", "big.example", 3)):
            for i in range(n):
                self.row(w, f"{key}{i}", "rejected", f"2026-11-18T05:0{i}:00Z", domain=domain, reason="type")
        got = self.build()["rejected_for_type"]
        self.assertEqual([(h["host"], h["n"]) for h in got["hosts"]],
                         [("big.example", 3), (cr.UNKNOWN_HOST, 3), ("a.example", 2), ("x.example", 2)])
        self.assertEqual((got["n"], got["hosts_total"]), (10, 4))

    def test_an_address_from_the_queue_is_cleaned_and_a_host_that_is_not_text_is_the_unknown_host(self):
        w = self.make_queue()
        self.row(w, "k", "kept", "2026-11-18T05:00:00Z", book_id="b-k", address="https://a.example/" + RLO + "x")
        self.row(w, "t", "rejected", "2026-11-18T05:00:01Z", domain="x", reason="type")
        w.execute("UPDATE candidates SET domain = x'4142' WHERE identity_key = 't'")
        got = self.build()
        self.assertEqual(got["filed"]["books"][0]["address"], "https://a.example/x")
        self.assertEqual(got["rejected_for_type"]["hosts"], [{"host": cr.UNKNOWN_HOST, "n": 1}])

    def test_a_row_whose_status_is_the_word_error_is_a_status_and_not_a_failed_part(self):
        w = self.make_queue()
        self.row(w, "k", "kept", "2026-11-18T05:00:00Z", book_id="b-k")
        self.row(w, "e", "error", "2026-11-18T05:00:01Z")
        got = self.build()
        self.assertEqual(got["queue"]["counts"]["kept"], 1)
        self.assertIsNotNone(got["compare"])

    def test_the_queue_is_closed_when_the_facts_are_read_and_when_they_fail(self):
        self.make_queue().close()
        closed = []

        class Spy:
            def __init__(self, conn):
                self.conn = conn

            def execute(self, *a, **k):
                return self.conn.execute(*a, **k)

            def close(self):
                closed.append(True)
                self.conn.close()

        real = cs.open_queue

        def opened(root):
            got = real(root)
            return cs.QueueOpen(Spy(got.conn), got.status, got.reason)

        with mock.patch.object(cs, "open_queue", opened):
            self.build()
            self.assertEqual(closed, [True])
            with mock.patch.object(cr, "_queue_facts", side_effect=RuntimeError("x")), self.assertRaises(RuntimeError):
                self.build()
        self.assertEqual(closed, [True, True])

    def test_the_generated_time_is_in_utc_whatever_the_zone_of_the_time_given(self):
        local = datetime.timezone(datetime.timedelta(hours=5))
        got = self.build(now=datetime.datetime(2026, 11, 18, 17, 0, 0, tzinfo=local))
        self.assertEqual(got["generated"], "2026-11-18T12:00:00Z")

    def test_the_works_rejected_for_their_type_by_host(self):
        self.full_day()
        w = self.make_queue()
        self.row(w, "n1", "rejected", "2026-11-18T05:00:06Z", domain="publisher.example", reason="TYPE")
        self.row(w, "n2", "rejected", "2026-11-18T05:00:07Z", domain="publisher.example", reason="types")
        self.row(w, "n3", "rejected", "2026-11-17T05:00:07Z", domain="publisher.example", reason="type")
        self.row(w, "n4", "failed", "2026-11-18T05:00:08Z", domain="publisher.example", reason="type")
        got = self.build()["rejected_for_type"]
        self.assertEqual(got, {"n": 4, "hosts": [{"host": "publisher.example", "n": 2}, {"host": "other.example", "n": 1}, {"host": "(unknown)", "n": 1}],
                               "hosts_total": 3})

    def test_the_hosts_rejected_for_their_type_are_bounded_and_the_total_is_said(self):
        w = self.make_queue()
        for i in range(60):
            self.row(w, f"t{i}", "rejected", "2026-11-18T05:00:00Z", domain=f"h{i:02d}.example", reason="type")
        got = self.build()["rejected_for_type"]
        self.assertEqual((got["n"], len(got["hosts"]), got["hosts_total"]), (60, 50, 60))

    def test_the_pauses_of_the_breaker_from_the_log_and_the_state_of_the_file_now(self):
        self.full_day()
        got = self.build()["breaker"]
        self.assertEqual(got["pauses"], [{"ts": "2026-11-18T07:00:20Z", "run": "r2", "reason": "8 failures in a row"}])
        self.assertIsNone(got["now"])
        (self.tmp / "crawl" / "breaker.json").write_text(json.dumps({**GOOD_BREAKER, "reason": "stage hit its bound"}))
        got = self.build()["breaker"]["now"]
        self.assertEqual((got["state"], got["reason"], got["at"], got["kind"]), ("tripped", "stage hit its bound", "2026-11-16T05:30:00Z", "stage_bound"))
        (self.tmp / "crawl" / "breaker.json").unlink()
        self.assertEqual(self.build()["breaker"]["now"]["state"], "missing")
        (self.tmp / "crawl" / "breaker.json").write_text("not json")
        self.assertEqual(self.build()["breaker"]["now"]["state"], "cannot_read")

    def test_only_a_breaker_line_that_says_tripped_is_a_pause(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="breaker", outcome="ok", reason="cleared by the owner"),
                     dict(ts="2026-11-18T06:00:00Z", run="r1", step="breaker", outcome="tripped", reason="model down"))
        self.assertEqual([p["reason"] for p in self.build()["breaker"]["pauses"]], ["model down"])

    def test_the_lists_that_could_not_be_refreshed_with_their_name_and_reason(self):
        self.full_day()
        self.assertEqual(self.build()["lists_failed"], [{"ts": "2026-11-18T05:00:03Z", "list": "publicsuffix.org", "outcome": "failed", "reason": "HTTP 503"}])

    def test_every_list_update_that_is_not_ok_is_listed_and_the_name_may_be_in_the_host(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="list_update", outcome="skipped", host="lists.example", reason="not due"),
                     dict(ts="2026-11-18T05:00:01Z", run="r1", step="list_update", outcome="ok", host="x.example"),
                     dict(ts="2026-11-18T05:00:02Z", run="r1", step="list_update", outcome="refused", host="y.example", reason="over the size"))
        got = self.build()["lists_failed"]
        self.assertEqual([(g["list"], g["outcome"]) for g in got], [("lists.example", "skipped"), ("y.example", "refused")])

    def test_the_failures_by_reason_commonest_first_from_the_log_and_from_the_queue(self):
        self.full_day()
        got = self.build()["failures_by_reason"]
        self.assertEqual(got["log"], [{"reason": "HTTP 503", "n": 2}, {"reason": "connection reset", "n": 1}, {"reason": "timeout", "n": 1}])
        self.assertEqual(got["queue"], [{"reason": "connection reset", "n": 1}, {"reason": "timeout", "n": 1}])

    def test_a_fail_line_with_no_reason_is_named_and_reasons_that_clean_alike_are_merged(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="fail", outcome="failed"),
                     dict(ts="2026-11-18T05:01:00Z", run="r1", step="fail", outcome="failed", reason="HTTP 503"),
                     dict(ts="2026-11-18T05:02:00Z", run="r1", step="fail", outcome="failed", reason="HTTP" + ZWSP + " 503"))
        self.assertEqual(self.build()["failures_by_reason"]["log"], [{"reason": "HTTP 503", "n": 2}, {"reason": "(no reason)", "n": 1}])

    def test_the_failures_listed_are_bounded(self):
        self.put_log("2026-11-18", *[dict(ts=f"2026-11-18T05:{i:02d}:00Z", run="r1", step="fail", outcome="failed", reason=f"reason {i:02d}") for i in range(40)])
        self.assertEqual(len(self.build()["failures_by_reason"]["log"]), 20)

    def test_a_part_that_fails_is_a_fault_of_that_part_and_the_rest_stand(self):
        self.full_day()
        for name in ("count_runs", "breaker_state", "open_queue"):
            with self.subTest(part=name), mock.patch.object(cs, name, side_effect=RuntimeError("it broke: Cookie: sid=1")):
                got = self.build()
                self.assertEqual(json.loads(json.dumps(got)), got)
                self.assertNotIn("sid=1", json.dumps(got))
                self.assertEqual(got["counts"]["fetched"], 3)
        with mock.patch.object(cs, "count_runs", side_effect=RuntimeError("x")):
            self.assertEqual(set(self.build()["runs"]), {"error"})

    def test_every_text_is_redacted_and_cleaned_in_the_data(self):
        evil = "evil" + RLO + chr(0x1b) + "[31m" + ZWSP
        self.put_log("2026-11-18",
                     dict(ts="2026-11-18T05:00:00Z", run="r1", step="capture", outcome="ok", book="b" + evil, reason="https://user:SECRET1@e.example/?token=SECRET2&x=" + evil,
                          host="h" + evil),
                     dict(ts="2026-11-18T05:00:01Z", run="r1", step="fail", outcome="failed", reason="Cookie: SECRET3 " + evil, candidate=1),
                     dict(ts="2026-11-18T05:00:02Z", run="r1", step="list_update", outcome="failed", host="n" + evil, reason="Auth-Key: SECRET4"),
                     dict(ts="2026-11-18T05:00:03Z", run="r1", step="breaker", outcome="tripped", reason="X-Api-Key: SECRET5"))
        text = json.dumps(self.build())
        for n in range(1, 6):
            self.assertNotIn(f"SECRET{n}", text)
        self.assertNotIn(RLO, text)
        self.assertNotIn("\\u001b", text)

    def test_nothing_is_written_beyond_the_queues_side_files(self):
        self.quiet_day()
        before = snapshot(self.tmp)
        self.build()
        after = snapshot(self.tmp)
        self.assertEqual({os.path.basename(p) for p in set(after) - set(before)}, SIDE_FILES)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)


class CodeSpanTest(unittest.TestCase):
    def test_a_text_is_put_in_a_code_span_with_the_characters_that_could_break_out_replaced(self):
        self.assertEqual(cr.code("plain text"), "`plain text`")
        self.assertEqual(cr.code("a`b|c<d>e"), "`a%60b%7Cc%3Cd%3Ee`")
        self.assertEqual(cr.code("https://example.org/a?b=1&c=2"), "`https://example.org/a?b=1&c=2`")

    def test_nothing_or_nothing_left_is_named_and_not_an_empty_span(self):
        self.assertEqual(cr.code(None), "`(none)`")
        self.assertEqual(cr.code(""), "`(empty)`")
        self.assertEqual(cr.code(RLO + ZWSP), "`(empty)`")

    def test_a_text_is_cleaned_cut_and_redacted_before_it_is_put_in_the_span(self):
        self.assertEqual(cr.code("a\nb" + chr(0x1b) + "c"), "`a bc`")
        self.assertEqual(cr.code("x" * 500, 20), "`" + "x" * 20 + "`")
        self.assertEqual(cr.code("Cookie: sid=abc"), "`" + cs.WITHHELD + "`")
        self.assertEqual(cr.code("https://u:pw@example.org/?token=abc"), "`https://example.org/?token=[withheld]`")

    def test_the_limit_is_the_status_limit(self):
        for bad in (0, -1, 2001, "5", None, True, 1.5):
            with self.subTest(limit=bad), self.assertRaises(KbError):
                cr.code("x", bad)

    def test_a_number_is_a_number_and_not_a_span(self):
        self.assertEqual(cr.number(5), "5")
        self.assertEqual(cr.number(None), "unknown")
        self.assertEqual(cr.number(True), "unknown")
        self.assertEqual(cr.number("5"), "unknown")
        self.assertEqual(cr.number(-1), "unknown")


class RenderTest(ReportBase):
    def text(self):
        return cr.render(self.build())

    def test_the_headings_come_in_order_and_the_numbers_are_there(self):
        self.full_day()
        text = self.text()
        headings = [line for line in text.splitlines() if line.startswith("#")]
        self.assertEqual(headings, ["# Crawl report for 2026-11-18", "## The day in numbers", "## Runs", "## The log and the queue compared", "## Books filed",
                                    "## Works rejected for their type", "## Pauses of the circuit breaker", "## Lists that could not be refreshed",
                                    "## Failures by reason", "## The log"])
        for line in ("- Fetched: 3", "- Fetches that failed: 2", "- Kept: 1", "- Rejected: 1", "- Failed: 2 candidates, 4 fail lines", "- Started: 2",
                     "- Ended: 2", "- Refused firings, which are not runs: 3"):
            self.assertIn(line, text)

    def test_a_difference_between_the_log_and_the_queue_is_printed_with_both_numbers(self):
        self.full_day()
        text = self.text()
        self.assertIn("- kept: log 1, queue 2: DIFFERENT", text)
        self.assertIn("- rejected: log 1, queue 1: the same", text)
        self.assertIn("- failed: log 2, queue 2: the same", text)

    def test_the_books_filed_are_listed_by_address_and_host_in_code_spans(self):
        self.full_day()
        text = self.text()
        self.assertIn("- `2026-11-18T05:01:02Z` `b-001` address `https://example.org/a` host `example.org` (seen in both)", text)
        self.assertIn("- `2026-11-18T05:02:02Z` `b-002` address `(none)` host `example.net` (seen in log)", text)
        self.assertIn("3 books", text)

    def test_the_type_rejections_pauses_failed_lists_and_failures_are_there(self):
        self.full_day()
        text = self.text()
        self.assertIn("- `publisher.example`: 2", text)
        self.assertIn("- `2026-11-18T07:00:20Z` run `r2`: `8 failures in a row`", text)
        self.assertIn("- `2026-11-18T05:00:03Z` `publicsuffix.org` failed: `HTTP 503`", text)
        self.assertIn("- `HTTP 503`: 2", text)
        self.assertIn("Refused", text)

    def test_the_state_of_the_breaker_now_is_said_when_it_is_not_clear(self):
        self.full_day()
        (self.tmp / "crawl" / "breaker.json").unlink()
        self.assertIn("The breaker file now: `missing`", self.text())
        self.good_breaker()
        self.assertNotIn("The breaker file now", self.text())

    def test_no_queue_and_no_log_are_said_in_words(self):
        text = self.text()
        self.assertIn("No log line of this day was found", text)
        self.assertIn("The queue was not read: `missing`", text)
        self.assertNotIn("DIFFERENT", text)

    def test_a_part_that_failed_is_said_to_have_failed_with_its_cleaned_reason(self):
        self.full_day()
        with mock.patch.object(cs, "count_runs", side_effect=RuntimeError("it broke: Cookie: sid=1")):
            text = self.text()
        self.assertIn("could not be read: `" + cs.WITHHELD + "`", text)
        self.assertNotIn("sid=1", text)

    def test_the_bad_lines_and_a_cut_of_the_log_are_said(self):
        self.put_day_log()
        with open(self.tmp / "crawl" / "log" / "crawl-2026-11-18.jsonl", "ab") as f:
            f.write(b"junk\n")
        self.assertIn("- Bad lines skipped: 1", self.text())

    def test_the_zone_and_a_problem_with_it_are_said(self):
        data = self.build()
        data["zone_problem"] = "the time zone of the plan is not one the system knows, so the machine's is used"
        text = cr.render(data)
        self.assertIn("Zone: `UTC`", text)
        self.assertIn("not one the system knows", text)

    def test_hostile_text_cannot_make_a_link_an_image_a_heading_a_table_cell_or_html(self):
        self.put_log("2026-11-18",
                     *[dict(ts=f"2026-11-18T05:{i:02d}:00Z", run="r1", step="capture", outcome="ok", book=f"b{i}", host=h) for i, h in enumerate(HOSTILE)],
                     *[dict(ts=f"2026-11-18T06:{i:02d}:00Z", run="r1", step="fail", outcome="failed", reason=h, candidate=i) for i, h in enumerate(HOSTILE)],
                     *[dict(ts=f"2026-11-18T07:{i:02d}:00Z", run="r1", step="list_update", outcome="failed", host=h, reason=h) for i, h in enumerate(HOSTILE)],
                     *[dict(ts=f"2026-11-18T08:{i:02d}:00Z", run=h, step="breaker", outcome="tripped", reason=h) for i, h in enumerate(HOSTILE)],
                     *[dict(ts=f"2026-11-18T09:{i:02d}:00Z", run="", step="refuse", outcome="refused", reason=h) for i, h in enumerate(HOSTILE)])
        w = self.make_queue()
        for i, h in enumerate(HOSTILE):
            self.row(w, f"q{i}", "rejected", "2026-11-18T05:00:00Z", domain=h, reason="type")
            self.row(w, f"f{i}", "failed", "2026-11-18T05:00:00Z", domain=h, reason=h, address=h)
            self.row(w, f"k{i}", "kept", "2026-11-18T05:00:00Z", domain=h, book_id=f"k{i}", address=h)
        (self.tmp / "crawl" / "breaker.json").write_text(json.dumps({**GOOD_BREAKER, "reason": HOSTILE[0] + HOSTILE[5], "run": HOSTILE[2]}))
        text = self.text()
        outside = re.sub(r"`[^`\n]*`", "", text)
        for hostile in HOSTILE:
            self.assertNotIn(hostile.strip("`"), outside, hostile)
        for char in "[]<>|":
            self.assertNotIn(char, outside, char)
        spans = re.findall(r"`([^`\n]*)`", text)
        self.assertTrue(spans)
        for span in spans:
            self.assertFalse(set(span) & set("`|<>"), span)
        own = {"# Crawl report for 2026-11-18", "## The day in numbers", "## Runs", "## The log and the queue compared", "## Books filed",
               "## Works rejected for their type", "## Pauses of the circuit breaker", "## Lists that could not be refreshed", "## Failures by reason", "## The log"}
        self.assertEqual({line for line in text.splitlines() if line.startswith("#")}, own)
        self.assertFalse([line for line in outside.splitlines() if line.strip() and set(line.strip()) <= set("-*_= ")])
        self.assertFalse([line for line in text.splitlines() if line.startswith((">", "!", "|", "<", "[", "    "))])

    def test_the_books_filed_say_when_one_of_their_two_sources_was_not_read(self):
        self.put_day_log()
        text = self.text()
        self.assertIn("The queue was not read, so only the books of the log are listed.", text)
        self.assertNotIn("The log could not be read", text)
        self.full_day()
        self.assertNotIn("so only the books", self.text())
        with mock.patch.object(cs, "lines_of_day", side_effect=RuntimeError("it broke")):
            self.assertIn("The log could not be read, so only the books of the queue are listed.", self.text())

    def test_every_text_the_report_shows_from_outside_is_in_a_code_span_and_escaped(self):
        self.full_day()
        data = self.build()
        data["zone_problem"] = "zone`zp"
        data["notes"] = ["note`np"]
        data["queue"] = {"status": "bad`qs", "reason": "reason`qr", "counts": None}
        data["compare"] = None
        data["log"]["problem"] = "folder`lp"
        data["log"]["dates"] = ["date`ld"]
        data["log"]["cut"] = True
        data["breaker"]["now"] = {"state": "state`bs", "reason": "why`br", "kind": "kind`bk", "at": "at`ba", "run": "", "detail": None}
        data["runs"]["refused_by_reason"] = {"firing`rr": 1}
        text = cr.render(data)
        for want in ("`zone%60zp`", "`note%60np`", "`bad%60qs`", "`reason%60qr`", "`folder%60lp`", "`date%60ld`", "`state%60bs`", "`why%60br`", "`kind%60bk`", "`at%60ba`",
                     "`firing%60rr`", "The log was cut"):
            with self.subTest(want=want):
                self.assertIn(want, text)
        self.assertNotIn("`zone`", text)

    def test_the_text_has_no_character_that_is_not_printable_and_no_secret(self):
        evil = "evil" + RLO + chr(0x1b) + ZWSP
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="fail", outcome="failed", candidate=1, host="c" + evil, reason="Cookie: SECRET1 " + evil),
                     dict(ts="2026-11-18T05:01:00Z", run="r1", step="capture", outcome="ok", book="b" + evil, reason="https://u:SECRET2@e.example/" + evil))
        text = self.text()
        self.assertFalse([c for c in text if not (c.isprintable() or c == "\n")])
        self.assertNotIn("SECRET", text)

    def test_the_text_ends_with_one_line_feed_and_is_plain_text(self):
        self.full_day()
        text = self.text()
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))
        self.assertIsInstance(text, str)
        self.assertLess(len(text.encode()), cr.MAX_REPORT_BYTES)


class WriteTest(StateBase):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))

    TODAY = DAY
    SAME = object()

    def write(self, text="# Crawl report for 2026-11-18\n", day=DAY, today=SAME):
        return cr.write_report(self.tmp, day, text, today=self.TODAY if today is self.SAME else today)

    def test_the_report_is_written_where_the_owner_is_told_with_the_modes_of_the_plan(self):
        path = self.write()
        self.assertEqual(path, self.tmp / "crawl" / "report" / "crawl-report-2026-11-18.md")
        self.assertEqual(path.read_text(), "# Crawl report for 2026-11-18\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_the_mode_does_not_depend_on_the_umask(self):
        old = os.umask(0)
        self.addCleanup(os.umask, old)
        path = self.write()
        self.assertEqual((stat.S_IMODE(path.stat().st_mode), stat.S_IMODE(path.parent.stat().st_mode)), (0o600, 0o700))

    def test_a_missing_crawl_folder_is_made_private_too(self):
        self.write()
        self.assertEqual(stat.S_IMODE((self.tmp / "crawl").stat().st_mode), 0o700)

    def test_an_existing_crawl_folder_is_left_as_it_is(self):
        crawl = self.crawl()
        os.chmod(crawl, 0o755)
        self.write()
        self.assertEqual(stat.S_IMODE(crawl.stat().st_mode), 0o755)

    def test_the_file_is_written_to_a_temporary_file_in_the_same_folder_and_renamed_and_none_is_left(self):
        seen = []
        real = os.replace

        def spy(src, dst, *a, **k):
            seen.append((Path(src), Path(dst)))
            return real(src, dst, *a, **k)

        with mock.patch.object(os, "replace", spy):
            path = self.write()
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0][0].parent, seen[0][1]), (path.parent, path))
        self.assertEqual(os.listdir(path.parent), [path.name])

    def test_the_temporary_file_is_made_new_and_private_and_without_following_a_link(self):
        flags = []
        real = os.open

        def spy(p, f, *a, **k):
            flags.append((str(p), f, a))
            return real(p, f, *a, **k)

        with mock.patch.object(os, "open", spy):
            self.write()
        made = [x for x in flags if x[1] & os.O_CREAT]
        self.assertEqual(len(made), 1)
        for wanted in (os.O_CREAT, os.O_EXCL, os.O_NOFOLLOW, os.O_WRONLY):
            self.assertTrue(made[0][1] & wanted, wanted)
        self.assertEqual(made[0][2], (0o600,))

    def test_the_text_is_written_whole_even_when_the_system_takes_a_few_bytes_at_a_time_and_is_synced_before_it_is_renamed(self):
        order = []
        real_write, real_fsync, real_replace, real_close = os.write, os.fsync, os.replace, os.close
        opened = []
        real_open = os.open

        def write(fd, data):
            order.append("write")
            return real_write(fd, bytes(data[:3]))

        def spy_open(path, *a, **k):
            fd = real_open(path, *a, **k)
            if a and a[0] & os.O_CREAT:
                opened.append(fd)
            return fd

        with mock.patch.object(os, "write", write), mock.patch.object(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1]), \
                mock.patch.object(os, "replace", lambda s, d: (order.append("replace"), real_replace(s, d))[1]), \
                mock.patch.object(os, "close", lambda fd: (order.append(f"close{opened.index(fd)}" if fd in opened else "close"), real_close(fd))[1]), \
                mock.patch.object(os, "open", spy_open):
            path = self.write("0123456789\nabcdef\n")
        self.assertEqual(path.read_text(), "0123456789\nabcdef\n")
        self.assertEqual(order[-3:], ["fsync", "close0", "replace"])
        self.assertGreater(order.count("write"), 5)

    def test_a_text_of_exactly_the_size_limit_is_taken_and_one_byte_more_is_not(self):
        with mock.patch.object(cr, "MAX_REPORT_BYTES", 10):
            self.write("123456789\n")
            with self.assertRaises(KbError):
                self.write("1234567890\n")

    def test_a_temporary_file_that_cannot_be_opened_is_a_refusal_and_not_a_raw_error(self):
        self.write("old\n")
        real = os.open
        with mock.patch.object(os, "open", lambda path, flags, *a: (_ for _ in ()).throw(OSError(13, "denied")) if flags & os.O_CREAT else real(path, flags, *a)):
            with self.assertRaises(KbError):
                self.write("new\n")

    def test_a_failure_leaves_the_old_report_and_no_temporary_file(self):
        path = self.write("old\n")
        with mock.patch.object(os, "replace", side_effect=OSError(5, "I/O error")):
            with self.assertRaises(KbError):
                self.write("new\n")
        self.assertEqual(path.read_text(), "old\n")
        self.assertEqual(os.listdir(path.parent), [path.name])

    def test_the_same_day_again_replaces_the_file_and_another_day_is_another_file(self):
        first = self.write("one\n")
        second = self.write("two\n")
        self.assertEqual((first, first.read_text()), (second, "two\n"))
        other = self.write("other\n", day=datetime.date(2026, 11, 17))
        self.assertNotEqual(other, first)
        self.assertEqual(sorted(os.listdir(first.parent)), ["crawl-report-2026-11-17.md", "crawl-report-2026-11-18.md"])

    def test_a_link_in_the_files_place_is_replaced_and_what_it_pointed_to_is_not_written(self):
        folder = self.tmp / "crawl" / "report"
        folder.mkdir(parents=True)
        os.chmod(folder, 0o700)
        target = self.tmp / "precious.txt"
        target.write_text("keep")
        os.symlink(target, folder / "crawl-report-2026-11-18.md")
        path = self.write("new\n")
        self.assertFalse(path.is_symlink())
        self.assertEqual((path.read_text(), target.read_text()), ("new\n", "keep"))

    def test_a_folder_in_the_files_place_is_refused_and_leaves_no_temporary_file(self):
        folder = self.tmp / "crawl" / "report"
        folder.mkdir(parents=True)
        os.chmod(folder, 0o700)
        (folder / "crawl-report-2026-11-18.md").mkdir()
        with self.assertRaises(KbError):
            self.write()
        self.assertEqual(os.listdir(folder), ["crawl-report-2026-11-18.md"])

    def test_a_report_folder_that_is_a_link_not_ours_or_loose_is_refused_and_nothing_is_written(self):
        crawl = self.crawl()
        real = self.tmp / "elsewhere"
        real.mkdir()
        os.chmod(real, 0o700)
        os.symlink(real, crawl / "report")
        with self.assertRaises(KbError):
            self.write()
        self.assertEqual(os.listdir(real), [])
        (crawl / "report").unlink()
        (crawl / "report").mkdir()
        os.chmod(crawl / "report", 0o755)
        with self.assertRaises(KbError):
            self.write()
        os.chmod(crawl / "report", 0o770)
        with self.assertRaises(KbError):
            self.write()
        os.chmod(crawl / "report", 0o701)
        with self.assertRaises(KbError):
            self.write()
        os.chmod(crawl / "report", 0o700)
        with mock.patch.object(cr, "_me", return_value=os.getuid() + 1), self.assertRaises(KbError):
            self.write()
        self.assertEqual(os.listdir(crawl / "report"), [])
        self.write()

    def test_a_crawl_folder_that_is_a_link_or_a_file_is_refused(self):
        real = self.tmp / "elsewhere"
        real.mkdir()
        os.symlink(real, self.tmp / "crawl")
        with self.assertRaises(KbError):
            self.write()
        self.assertEqual(os.listdir(real), [])
        os.unlink(self.tmp / "crawl")
        (self.tmp / "crawl").write_text("x")
        with self.assertRaises(KbError):
            self.write()

    def test_a_crawl_folder_that_others_can_write_is_refused_and_one_they_can_only_read_is_not(self):
        crawl = self.tmp / "crawl"
        crawl.mkdir()
        for mode in (0o777, 0o722, 0o720, 0o702):
            os.chmod(crawl, mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(KbError):
                self.write()
        self.assertFalse((crawl / "report").exists())
        os.chmod(crawl, 0o755)
        self.write()

    def test_nothing_is_ever_written_into_the_log_folder(self):
        self.put_log("2026-11-18", dict(ts="2026-11-18T05:00:00Z", run="r1", step="run_start"))
        log = self.tmp / "crawl" / "log"
        file = log / "crawl-2026-11-18.jsonl"
        before = (snapshot(log), file.stat().st_mtime_ns, file.read_bytes(), log.stat().st_mtime_ns)
        self.write()
        self.write("again\n")
        self.assertEqual((snapshot(log), file.stat().st_mtime_ns, file.read_bytes(), log.stat().st_mtime_ns), before)

    def test_the_log_folder_may_be_a_link_and_the_report_is_not_written_through_it(self):
        crawl = self.crawl()
        real = self.tmp / "elsewhere"
        real.mkdir()
        os.symlink(real, crawl / "log")
        self.write()
        self.assertEqual(os.listdir(real), [])

    def test_a_day_that_is_not_a_date_or_is_in_the_future_or_before_2000_is_refused_before_anything_is_made(self):
        for bad in ("2026-11-18", None, 5, datetime.datetime(2026, 11, 18, 1, 0), datetime.date(2026, 11, 19), datetime.date(1999, 12, 31), datetime.date(1, 1, 1)):
            with self.subTest(day=bad), self.assertRaises(KbError):
                self.write(day=bad)
        self.assertFalse((self.tmp / "crawl").exists())
        self.write(day=datetime.date(2000, 1, 1))

    def test_today_must_be_a_date_too(self):
        for bad in (None, "2026-11-18", datetime.datetime(2026, 11, 18, 1, 0)):
            with self.subTest(today=bad), self.assertRaises(KbError):
                self.write(today=bad)

    def test_the_text_must_be_plain_printable_text_of_a_bounded_size(self):
        for bad in (None, b"bytes", 5, "a" + chr(0x1b) + "b", "a" + RLO + "b", "tab" + chr(9) + "here", "x" * (cr.MAX_REPORT_BYTES + 1), chr(0xD800)):
            with self.subTest(text=repr(bad)[:30]), self.assertRaises(KbError):
                self.write(bad)
        self.assertFalse((self.tmp / "crawl" / "report").exists())
        self.write("fine\nlines\n")

    def test_the_name_of_the_file_is_the_day_and_nothing_else_can_be_in_it(self):
        self.assertEqual(self.write(day=datetime.date(2026, 1, 2), today=datetime.date(2026, 2, 1)).name, "crawl-report-2026-01-02.md")


class MakeReportTest(ReportBase):
    def approve(self):
        shutil.copytree(FIX / "approved", self.tmp / "crawl" / "approved")

    def reader(self, **over):
        values = {"timezone": "UTC", **over}
        return lambda path: dict(values)

    def make(self, **kw):
        return cr.make_report(self.tmp, read_plan=kw.pop("read_plan", self.reader()), now=kw.pop("now", NOW), **kw)

    def test_the_report_of_the_day_is_made_and_written_and_its_path_and_counts_are_given(self):
        self.full_day()
        self.approve()
        got = self.make(day=DAY)
        path = Path(got["path"])
        self.assertEqual(path, self.tmp / "crawl" / "report" / "crawl-report-2026-11-18.md")
        self.assertTrue(path.read_text().startswith("# Crawl report for 2026-11-18\n"))
        self.assertEqual((got["day"], got["counts"]["fetched"], got["filed"], got["zone"]), ("2026-11-18", 3, 3, "UTC"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_the_day_is_today_in_the_plans_zone_when_none_is_given(self):
        self.full_day()
        self.approve()
        self.assertEqual(self.make()["day"], "2026-11-18")
        self.assertEqual(self.make(read_plan=self.reader(timezone="Pacific/Auckland"), now=datetime.datetime(2026, 11, 17, 20, 0, 0, tzinfo=UTC))["day"], "2026-11-18")
        self.assertEqual(self.make(read_plan=self.reader(timezone="America/New_York"), now=datetime.datetime(2026, 11, 18, 3, 0, 0, tzinfo=UTC))["day"], "2026-11-17")

    def test_no_approved_plan_uses_the_machines_zone_and_says_so_in_the_report(self):
        self.full_day()
        old = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old is not None else os.environ.pop("TZ", None), time.tzset()))
        os.environ["TZ"] = "UTC"
        time.tzset()
        got = self.make(day=DAY)
        text = Path(got["path"]).read_text()
        self.assertEqual(got["zone"], "local")
        self.assertIn("no approved plan", text)

    def test_a_plan_that_cannot_be_read_and_a_zone_that_is_not_known_are_said(self):
        self.full_day()
        self.approve()
        text = Path(self.make(day=DAY, read_plan=mock.Mock(side_effect=KbError("line 3: bad")))["path"]).read_text()
        self.assertIn("cannot be read", text)
        text = Path(self.make(day=DAY, read_plan=self.reader(timezone="Mars/Olympus"))["path"]).read_text()
        self.assertIn("not one the system knows", text)

    def test_a_plan_part_that_itself_fails_is_an_unreadable_plan_and_the_report_is_made(self):
        self.full_day()
        with mock.patch.object(cs, "approved_plan", side_effect=RuntimeError("it broke: Cookie: sid=1")):
            got = self.make(day=DAY)
        text = Path(got["path"]).read_text()
        self.assertIn("cannot be read", text)
        self.assertNotIn("sid=1", text)
        self.assertEqual(got["zone"], "local")

    def test_the_notes_tell_a_plan_that_is_not_there_from_one_that_cannot_be_read(self):
        self.full_day()
        self.assertEqual(self.make(day=DAY)["notes"], ["no approved plan: the time zone is the machine's"])
        self.approve()
        self.assertEqual(self.make(day=DAY)["notes"], [])
        with mock.patch.object(cs, "approved_plan", side_effect=RuntimeError("it broke")):
            self.assertEqual(self.make(day=DAY)["notes"], ["the approved plan cannot be read: the time zone is the machine's"])
        (self.tmp / "crawl" / "approved" / "0123456789abcdef0123456789abcdef" / "plan.txt").chmod(0o600)
        with mock.patch.object(cs, "approved_plan", return_value={"status": "unreadable", "digest": None, "values": None, "reason": "x"}):
            self.assertEqual(self.make(day=DAY)["notes"], ["the approved plan cannot be read: the time zone is the machine's"])

    def test_a_day_that_is_not_a_date_or_is_in_the_future_is_refused_and_no_report_is_made(self):
        self.full_day()
        self.approve()
        for bad in ("2026-11-18", datetime.date(2026, 11, 19), datetime.date(1999, 1, 1)):
            with self.subTest(day=bad), self.assertRaises(KbError):
                self.make(day=bad)
        self.assertFalse((self.tmp / "crawl" / "report").exists())

    def test_the_time_must_be_a_time_with_a_zone(self):
        for bad in (datetime.datetime(2026, 11, 18, 12, 0, 0), "2026-11-18T12:00:00Z", None):
            with self.subTest(now=bad), self.assertRaises(KbError):
                self.make(now=bad)

    def test_nothing_is_written_but_the_report_and_the_side_files_of_the_queue(self):
        self.quiet_day()
        self.approve()
        before = snapshot(self.tmp)
        got = self.make(day=DAY)
        after = snapshot(self.tmp)
        added = {os.path.relpath(p, self.tmp) for p in set(after) - set(before)}
        self.assertEqual(added, {"crawl/report", f"crawl/report/{Path(got['path']).name}", "candidates.sqlite-wal", "candidates.sqlite-shm"})
        files = {k: v for k, v in before.items() if not os.path.isdir(k)}  # a folder's own time and size change when something is made in it
        self.assertEqual({k: after[k] for k in files}, files)

    def test_the_report_of_a_day_again_replaces_it(self):
        self.full_day()
        self.approve()
        first = self.make(day=DAY)["path"]
        with open(self.tmp / "crawl" / "log" / "crawl-2026-11-18.jsonl", "ab") as f:
            f.write(raw(ts="2026-11-18T10:00:00Z", run="r3", step="run_start") + b"\n")
        second = self.make(day=DAY)["path"]
        self.assertEqual(first, second)
        self.assertIn("- Started: 3", Path(second).read_text())

    def test_the_text_of_the_file_is_what_render_gives(self):
        self.full_day()
        self.approve()
        got = self.make(day=DAY)
        self.assertEqual(Path(got["path"]).read_text(), cr.render(cr.build(self.tmp, DAY, "UTC", NOW)))


class SourceTest(unittest.TestCase):
    def test_the_module_writes_only_through_the_one_function_that_makes_the_report_file(self):
        source = (Path(ENGINE_DIR) / "kb" / "crawlreport.py").read_text(encoding="utf-8")
        for token in ("socket", "urllib.request", "http.client", "subprocess", "os.system(", "os.popen(", "shutil", ".write_text(", ".write_bytes(",
                      "os.remove(", "os.rename(", "os.symlink(", "os.link(", "os.chmod(", "os.chown(", "O_APPEND", "O_RDWR", "INSERT", "UPDATE", "DELETE", "DROP",
                      "CREATE", "sqlite3.connect"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIsNone(re.search(r"(?<![.\w])open\(", source), "the builtin open")
        for call, times in ((r"O_CREAT", 1), (r"os\.replace\(", 1), (r"os\.mkdir\(", 1), (r"os\.unlink\(", 1), (r"os\.write\(", 1)):
            with self.subTest(call=call):
                self.assertEqual(len(re.findall(call, source)), times)
        self.assertIsNone(re.search(r'/\s*"log"', source), "a path into the log folder")
        self.assertIsNone(re.search(r"\blog_files\b|\.jsonl", source), "the log's files by name")


if __name__ == "__main__":
    unittest.main()
