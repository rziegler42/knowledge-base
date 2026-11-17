"""The scan and hold step of the unattended crawl (`kb/crawlsteps.py`, Increment H of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

The step scans each unfinished crawl book before it is converted, and holds a hostile one: `crawl_held` with the kinds, a `hold` log line, and the book is filed but never converted, indexed, carded or moved. A scan
that fails, cannot run or is not made for the file holds the book at once (fail closed) and is not tried again. Every test runs on a temporary library with a fake scan tool, injected disk readings and a clock;
none reads the owner's config, library or plan. Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlsteps`."""
import datetime
import json
import os
import types
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_crawlbooks import Case as BooksCase

from kb import KbError, convert_run, crawlbooks, crawlguard, crawllog, crawlplan, crawlsteps, scan, scan_tool, stages

NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=datetime.timezone.utc)
PAGE = b"<html><head><title>A page</title></head><body>Some words on a page.</body></html>"


def roomy(path):
    return types.SimpleNamespace(f_bavail=10**9, f_frsize=4096)


class FakeScan:
    """A scan tool that says what the test tells it, and marks the stage and the caveats the way the real scan does."""

    def __init__(self, kinds=(), status="done", reason="the tool failed"):
        self.kinds, self.status, self.reason, self.calls = list(kinds), status, reason, []

    def __call__(self, store, book_id, version_id):
        self.calls.append(book_id)
        if self.status == "raise":
            raise KbError("the version has not been fetched yet, so there is nothing to scan")
        if self.status == "done":
            caveats = [{"kind": k, "count": 1, "detail": scan_tool.KINDS[k], "tool": scan.TOOL_LABEL} for k in self.kinds]
            store.set_version_caveats(book_id, version_id, caveats)
            stages.mark(store, book_id, version_id, "scanned", "done", tool=scan.TOOL_LABEL)
            return {"status": "done", "caveats": caveats}
        if self.status == "skipped":
            stages.mark(store, book_id, version_id, "scanned", "skipped", reason="there is no scanner for this kind of file", tool=scan.TOOL_LABEL)
            return {"status": "skipped", "reason": "there is no scanner for this kind of file"}
        stages.mark(store, book_id, version_id, "scanned", "failed", reason=self.reason, tool=scan.TOOL_LABEL)
        return {"status": "failed", "reason": self.reason}


class Case(BooksCase):
    def setUp(self):
        super().setUp()
        self.digest = self.approve()
        self.approved = {self.digest}
        self.now = NOW
        self.log = crawllog.Log(self.index, "run-1", clock=lambda: self.now)
        self.plan = crawlplan.defaults()
        self.cfg = {"bulk_root": self.bulk, "index_root": self.index}
        self.fake = FakeScan()
        self.stamp = 0

    def filed(self, digest=None, **kw):
        """A crawl book whose page is filed and fetched, found in the order the tests make them."""
        self.stamp += 1
        book = self.found_at(digest or self.digest, f"2026-11-16T10:00:{self.stamp:02d}Z", **kw)
        version = self.store.add_version(book, source={"address_asked": "http://a.test/p"})
        self.store.file_payload(book, version, "original", {"page.html": PAGE}, primary="page.html", tool="t")
        stages.mark(self.store, book, version, "fetched", "done", tool="t")
        return book

    def version(self, book):
        return self.store.read_book(book)["current_version"]

    def ctx(self):
        return types.SimpleNamespace(cfg=self.cfg, index_root=self.index, plan=self.plan, log=self.log, clock=lambda: self.now, run="run-1", secrets=(), tripped=False, matcher=None, suffixes=None,
                                     plan_digest=self.digest, steps={})

    def run_step(self, fake=None, ctx=None, statvfs=roomy):
        ctx = ctx or self.ctx()
        crawlsteps.make_scan_step(scan=fake or self.fake, statvfs=statvfs)(ctx)
        return ctx

    def lines(self):
        folder = os.path.join(self.index, "crawl", "log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return out

    def held(self, book):
        found = [e for e in self.events(book) if e["event"] == "crawl_held"]
        return found[0]["kinds"] if found else None

    def listed(self):
        return crawlbooks.crawl_books(self.store, self.approved)


class Holds(Case):
    def test_a_book_with_no_hold_kind_is_scanned_and_goes_on(self):
        book = self.filed()
        self.fake.kinds = ["hidden_text", "large_image_streams"]
        self.run_step()
        self.assertEqual(self.fake.calls, [book])
        self.assertIsNone(self.held(book))
        self.assertEqual(self.listed(), [book])
        self.assertEqual([(x["step"], x["outcome"], x["book"], x["n"]) for x in self.lines()], [("scan", "ok", book, 2)])

    def test_every_kind_the_plan_holds_by_default_holds_the_book_which_is_filed_and_terminal_and_named_in_the_log(self):
        for kind in crawlplan.DEFAULT_HOLD:
            with self.subTest(kind):
                book = self.filed()
                fake = FakeScan([kind])
                self.run_step(fake)
                self.assertEqual(self.held(book), [kind])
                self.assertNotIn(book, self.listed())
                self.assertEqual(self.store.read_book(book)["state"], "active")           # filed, not weeded
                hold = [x for x in self.lines() if x["step"] == "hold" and x["book"] == book]
                self.assertEqual([(x["outcome"], x["reason"]) for x in hold], [("held", kind)])

    def test_the_kinds_that_hold_are_listed_and_the_others_found_with_them_are_not(self):
        book = self.filed()
        self.run_step(FakeScan(["javascript", "hidden_text", "encrypted", "script_elements"]))
        self.assertEqual(self.held(book), ["encrypted", "javascript"])

    def test_script_elements_event_handlers_and_pattern_in_binary_data_never_hold_even_if_the_plan_lists_them(self):
        self.plan["hold_kinds"] = list(crawlplan.DEFAULT_HOLD) + ["script_elements", "event_handlers", "pattern_in_binary_data"]
        for kind in ("script_elements", "event_handlers", "pattern_in_binary_data"):
            with self.subTest(kind):
                book = self.filed()
                self.run_step(FakeScan([kind]))
                self.assertIsNone(self.held(book))
                self.assertIn(book, self.listed())

    def test_a_kind_holds_only_if_the_plan_names_it(self):
        self.plan["hold_kinds"] = ["hidden_text"]
        held, free = self.filed(), self.filed()
        fakes = {held: FakeScan(["hidden_text"]), free: FakeScan(["javascript"])}
        self.run_step(lambda store, b, v: fakes[b](store, b, v))
        self.assertEqual((self.held(held), self.held(free)), (["hidden_text"], None))

    def test_an_empty_hold_list_holds_nothing_found_but_a_failed_scan_still_holds(self):
        self.plan["hold_kinds"] = []
        ok, bad = self.filed(), self.filed()
        fakes = {ok: FakeScan(["javascript"]), bad: FakeScan(status="failed")}
        self.run_step(lambda store, b, v: fakes[b](store, b, v))
        self.assertEqual((self.held(ok), self.held(bad)), (None, ["scan_failed"]))


class FailClosed(Case):
    def test_a_scan_that_fails_holds_the_book_at_once_and_is_never_repeated(self):
        book = self.filed()
        fake = FakeScan(status="failed")
        self.run_step(fake)
        self.assertEqual(self.held(book), ["scan_failed"])
        self.assertEqual(self.listed(), [])
        self.run_step(fake)
        self.run_step(fake)
        self.assertEqual((fake.calls, self.names(book).count("crawl_held")), ([book], 1))

    def test_a_scan_that_is_not_made_for_the_file_holds_it_as_unavailable(self):
        book = self.filed()
        self.run_step(FakeScan(status="skipped"))
        self.assertEqual(self.held(book), ["scan_unavailable"])

    def test_a_scan_that_raises_holds_it_as_failed(self):
        book = self.filed()
        self.run_step(FakeScan(status="raise"))
        self.assertEqual(self.held(book), ["scan_failed"])

    def test_the_real_scan_with_no_approved_tool_holds_the_book_as_unavailable(self):
        book = self.filed()
        ctx = self.ctx()
        crawlsteps.make_scan_step(statvfs=roomy)(ctx)                     # the real scan: this temporary config approves no tool
        self.assertEqual(self.held(book), ["scan_unavailable"])
        self.assertEqual(stages.read(self.store, book, self.version(book))["stages"]["scanned"]["status"], "failed")

    def test_a_tool_that_times_out_or_dies_holds_the_book_with_the_kind_that_says_which(self):
        entry = {"formats": ["html"], "name": "kb-scan"}
        for error, kind in (("kb-scan 1 timed out after 60 seconds", "scan_timeout"), ("kb-scan 1 exited with status 1", "scan_failed"), ("kb-scan 1 could not be started: no such file", "scan_unavailable"),
                            ("kb-scan 1 wrote more than the output limit (10 bytes) on its standard output", "scan_failed")):
            with self.subTest(error):
                book = self.filed()
                with mock.patch.object(scan.approvals, "find", return_value=entry), mock.patch.object(convert_run, "run_to_payload", side_effect=convert_run.ToolError(error)):
                    crawlsteps.make_scan_step(statvfs=roomy)(self.ctx())
                self.assertEqual(self.held(book), [kind])

    def test_a_tool_approved_for_other_formats_only_holds_the_book_as_unavailable(self):
        book = self.filed()
        with mock.patch.object(scan.approvals, "find", return_value={"formats": ["pdf"], "name": "kb-scan"}):
            crawlsteps.make_scan_step(statvfs=roomy)(self.ctx())
        self.assertEqual(self.held(book), ["scan_unavailable"])

    def test_the_kind_of_an_earlier_failure_is_read_from_the_stage_file_and_a_skipped_scan_is_unavailable(self):
        timed, skipped = self.filed(), self.filed()
        stages.mark(self.store, timed, self.version(timed), "scanned", "failed", reason="kb-scan 1 timed out after 60 seconds", tool=scan.TOOL_LABEL)
        stages.mark(self.store, skipped, self.version(skipped), "scanned", "skipped", reason="there is no scanner for this kind of file", tool=scan.TOOL_LABEL)
        self.run_step()
        self.assertEqual((self.held(timed), self.held(skipped), self.fake.calls), (["scan_timeout"], ["scan_unavailable"], []))

    def test_a_book_that_is_held_already_gets_no_second_event_or_log_line_when_asked_again(self):
        book = self.filed()
        ctx = self.ctx()
        got = crawlsteps.scan_and_hold(ctx, self.store, book, FakeScan(["encrypted"]), roomy)
        again = crawlsteps.scan_and_hold(ctx, self.store, book, FakeScan(), roomy)
        self.assertEqual((got, again), (("held", None), ("held", None)))
        self.assertEqual((self.names(book).count("crawl_held"), len([x for x in self.lines() if x["step"] == "hold"])), (1, 1))

    def test_a_scan_that_died_before_the_hold_was_written_is_held_the_next_run_without_scanning_again(self):
        book = self.filed()
        with mock.patch.object(crawlbooks, "record_held", side_effect=RuntimeError("died")), self.assertRaises(RuntimeError):
            self.run_step(FakeScan(["javascript"]))
        self.assertIsNone(self.held(book))
        fake = FakeScan()
        self.run_step(fake)
        self.assertEqual((self.held(book), fake.calls), (["javascript"], []))

    def test_a_failed_scan_recorded_in_the_stage_file_is_held_without_a_second_scan(self):
        book = self.filed()
        stages.mark(self.store, book, self.version(book), "scanned", "failed", reason="the tool failed", tool=scan.TOOL_LABEL)
        fake = FakeScan()
        self.run_step(fake)
        self.assertEqual((self.held(book), fake.calls), (["scan_failed"], []))

    def test_a_book_with_no_version_is_held_as_failed(self):
        book = self.found_at(self.digest, "2026-11-16T10:00:09Z")
        self.run_step()
        self.assertEqual((self.held(book), self.fake.calls), (["scan_failed"], []))

    def test_what_a_failed_tool_said_never_reaches_a_log_line_or_an_event(self):
        book = self.filed()
        self.run_step(FakeScan(status="failed", reason="Authorization: Bearer abcdefgh12345 CANARY-text"))
        text = json.dumps([self.lines(), self.events(book)])
        self.assertNotIn("CANARY", text)
        self.assertNotIn("abcdefgh12345", text)
        self.assertEqual(self.held(book), ["scan_failed"])


class UnreadableBooks(Case):
    def test_a_book_whose_stage_file_cannot_be_read_is_held_and_the_books_behind_it_are_still_scanned(self):
        bad, good = self.filed(), self.filed()
        real = stages.read

        def read(store, book, version):
            if book == bad:
                raise KbError("the stage file cannot be read")
            return real(store, book, version)

        with mock.patch.object(crawlsteps.stages, "read", read):
            self.run_step()
        self.assertEqual((self.held(bad), self.held(good), self.fake.calls), (["scan_failed"], None, [good]))

    def test_a_scanned_book_whose_version_file_cannot_be_read_is_held(self):
        book = self.filed()
        FakeScan()(self.store, book, self.version(book))
        with mock.patch.object(self.store.__class__, "read_version", side_effect=KbError("unreadable")):
            self.run_step()
        self.assertEqual(self.held(book), ["scan_failed"])


class Idempotent(Case):
    def test_a_scanned_book_is_not_scanned_again_and_a_second_run_writes_nothing(self):
        book = self.filed()
        self.run_step()
        before = (self.events(book), len(self.lines()))
        self.run_step()
        self.assertEqual(self.fake.calls, [book])
        self.assertEqual((self.events(book), len(self.lines())), before)

    def test_a_book_scanned_earlier_whose_findings_the_plan_holds_now_is_held_without_a_scan(self):
        book = self.filed()
        self.run_step(FakeScan(["hidden_text"]))
        self.assertIsNone(self.held(book))
        self.plan["hold_kinds"] = ["hidden_text"]
        fake = FakeScan()
        self.run_step(fake)
        self.assertEqual((self.held(book), fake.calls), (["hidden_text"], []))

    def test_the_report_counts_what_the_step_did(self):
        self.filed()
        self.filed()
        self.filed()
        fakes = iter([FakeScan(), FakeScan(["encrypted"]), FakeScan(status="failed")])
        ctx = self.run_step(lambda store, b, v: next(fakes)(store, b, v))
        self.assertEqual(ctx.scan_report, {"scanned": 3, "held": 2, "ended": "all the books are scanned"})


class Refusals(Case):
    def test_a_disk_floor_leaves_the_book_unscanned_and_unheld_and_ends_the_step_quietly(self):
        first, second = self.filed(), self.filed()
        asked = []

        def full(path):
            asked.append(path)
            return types.SimpleNamespace(f_bavail=1, f_frsize=4096)

        ctx = self.run_step(statvfs=full)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual((self.held(first), self.held(second), self.listed()), (None, None, [first, second]))
        self.assertEqual(stages.read(self.store, first, self.version(first))["stages"]["scanned"]["status"], "pending")
        self.assertEqual(sorted(set(asked)), sorted([self.bulk, self.index]))
        self.assertEqual(len(self.lines()), 1)                              # one line for the refusal, not one for each book
        line = self.lines()[-1]
        self.assertEqual((line["step"], line["outcome"]), ("scan", "skipped"))
        self.assertIn("floor", line["reason"])
        self.assertFalse(ctx.tripped)

    def test_the_stop_file_is_looked_at_before_each_scan(self):
        first, second = self.filed(), self.filed()

        def stopping(store, book, version):
            out = self.fake(store, book, version)
            open(os.path.join(self.index, "crawl.stop"), "w").close()
            return out

        self.run_step(stopping)
        self.assertEqual(self.fake.calls, [first])
        self.assertEqual((self.held(second), self.listed()), (None, [first, second]))
        self.assertEqual(self.lines()[-1]["reason"], "the stop file is present")

    def test_a_stop_file_at_the_start_scans_nothing(self):
        self.filed()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.run_step()
        self.assertEqual(self.fake.calls, [])

    def test_a_refusal_does_not_hide_a_book_whose_scan_is_over_and_failed_from_the_hold(self):
        pending, failed, skipped, done = self.filed(), self.filed(), self.filed(), self.filed()
        stages.mark(self.store, failed, self.version(failed), "scanned", "failed", reason="the tool failed", tool=scan.TOOL_LABEL)
        stages.mark(self.store, skipped, self.version(skipped), "scanned", "skipped", reason="no scanner", tool=scan.TOOL_LABEL)
        FakeScan(["encrypted"])(self.store, done, self.version(done))
        full = lambda path: types.SimpleNamespace(f_bavail=1, f_frsize=4096)    # noqa: E731
        self.run_step(statvfs=full)
        self.assertEqual([self.held(b) for b in (pending, failed, skipped, done)], [None, ["scan_failed"], ["scan_unavailable"], ["encrypted"]])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(len([x for x in self.lines() if x["step"] == "scan"]), 1)          # one line for the refusal

    def test_a_refusal_is_no_hold_and_a_later_run_scans_the_book(self):
        book = self.filed()
        full = lambda path: types.SimpleNamespace(f_bavail=1, f_frsize=4096)    # noqa: E731
        self.run_step(statvfs=full)
        self.run_step()
        self.assertEqual(self.fake.calls, [book])


class OnlyTheCrawlsBooks(Case):
    def test_an_owners_book_a_book_of_an_unapproved_plan_and_a_finished_book_are_never_scanned(self):
        mine = self.filed()
        owner = self.book(auto_filed=False)
        stranger = self.filed("f" * 32)
        done = self.filed()
        crawlbooks.record_unplaced(self.store, done, "none")
        plain = self.book()
        self.run_step()
        self.assertEqual(self.fake.calls, [mine])
        for ident in (owner, plain):
            self.assertEqual(self.events(ident), [])
        self.assertIsNone(self.held(stranger))

    def test_the_books_are_scanned_oldest_found_first(self):
        a, b, c = self.filed(), self.filed(), self.filed()
        self.run_step()
        self.assertEqual(self.fake.calls, [a, b, c])


class Wiring(Case):
    def test_the_module_has_a_default_step_and_runs_no_program_of_its_own(self):
        self.assertTrue(callable(crawlsteps.step))
        with open(os.path.join(ENGINE_DIR, "kb", "crawlsteps.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib", "http.client", "subprocess", "os.environ", "getenv", "open("):
            self.assertNotIn(word, source, word)


if __name__ == "__main__":
    unittest.main()
