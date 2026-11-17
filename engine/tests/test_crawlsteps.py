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

from kb import KbError, convert_run, crawlbooks, crawlguard, crawllog, crawlplan, crawlqueue, crawlrun, crawlsteps, scan, scan_tool, stages

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
        self.fake.kinds = ["javascript_urls", "large_image_streams"]
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
                self.assertEqual(self.store.read_book(book)["state"], "weeded")           # kept on disk, but out of the reach of every command that walks the active books
                hold = [x for x in self.lines() if x["step"] == "hold" and x["book"] == book]
                self.assertEqual([(x["outcome"], x["reason"]) for x in hold], [("held", kind)])

    def test_the_kinds_that_hold_are_listed_and_the_others_found_with_them_are_not(self):
        book = self.filed()
        self.run_step(FakeScan(["javascript", "javascript_urls", "encrypted", "script_elements"]))
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


class HeldBooksLeaveTheEngine(Case):
    def model_cfg(self):
        entry = {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "chat", "thinking": False}
        return {"models_on": True, "models": {"m": entry}, "tasks": {"card-notes": "m", "card": "m", "card-check": "m"}}

    def test_the_commands_that_walk_every_book_skip_a_held_book(self):
        held, other = self.filed(), self.filed()
        self.run_step(FakeScan(["javascript"]))                                   # both books are scanned: the first is held, the second ... also (one fake for both)
        self.assertEqual(self.store.read_book(held)["state"], "weeded")
        good = self.filed()
        FakeScan()(self.store, good, self.version(good))
        from kb import cardqueue, placement, process
        reported = {r["book_id"] for r in process.process(self.store)}
        self.assertNotIn(held, reported)
        self.assertNotIn(other, reported)
        with mock.patch.object(cardqueue, "_sequence", return_value=["m", "m", "m"]), mock.patch.object(cardqueue.cardmake, "pieces_limit", return_value=1), \
                mock.patch.object(cardqueue, "_turns", return_value=[]), mock.patch.object(cardqueue, "_count_calls", create=True, return_value=0):
            try:
                planned = cardqueue.plan(self.store, {})
            except Exception as e:                                             # the plan may stop after it has read the books; only what it said of them matters here
                planned = None
                self.fail(f"the plan stopped: {type(e).__name__}: {e}")
        self.assertEqual(planned["skipped"]["inactive"], 2)
        items, _left = placement.select(self.store)
        self.assertNotIn(held, [i["book"] for i in items])

    def test_a_book_held_after_it_was_indexed_leaves_the_index_in_the_same_run(self):
        book = self.filed()
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_step(FakeScan(["encrypted"]))
        self.assertEqual(forget.call_count, 1)

    def test_nothing_is_taken_out_of_the_index_when_nothing_was_held(self):
        self.filed()
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_step()
        self.assertEqual(forget.call_count, 0)

    def test_a_hold_finished_by_the_next_scan_step_takes_the_book_out_of_the_index_too(self):
        book = self.filed()
        crawlbooks.record_held(self.store, book, ["encrypted"])                     # a hold that died before its state
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_step()
        self.assertEqual((forget.call_count, self.store.read_book(book)["state"]), (1, "weeded"))

    def test_a_hold_that_died_before_the_state_was_written_is_finished_by_the_next_scan_step(self):
        book = self.filed()
        with mock.patch.object(self.store.__class__, "set_state", side_effect=RuntimeError("died")), self.assertRaises(RuntimeError):
            self.run_step(FakeScan(["encrypted"]))
        self.assertEqual((self.held(book), self.store.read_book(book)["state"]), (["encrypted"], "active"))
        self.run_step()
        self.assertEqual(self.store.read_book(book)["state"], "weeded")


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


class TheTimeBudget(Case):
    def spent(self, ctx):
        ctx.deadline = self.now                                           # the clock is fixed: the budget is spent exactly now
        return ctx

    def test_the_scan_step_begins_no_scan_when_the_budget_of_the_run_is_spent_and_says_so_once(self):
        book = self.filed()
        ctx = self.run_step(ctx=self.spent(self.ctx()))
        self.assertEqual((self.fake.calls, self.held(book)), ([], None))
        self.assertEqual([x["reason"] for x in self.lines() if x["outcome"] == "skipped"], ["the time budget of the run is spent"])
        self.assertEqual(ctx.scan_report["ended"], "the time budget of the run is spent")

    def test_when_the_stop_file_is_there_too_the_stop_file_is_the_reason_given(self):
        self.filed()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        ctx = self.run_step(ctx=self.spent(self.ctx()))
        self.assertEqual(ctx.scan_report["ended"], "the stop file is present")

    def test_the_budget_is_looked_at_before_each_scan_and_not_only_at_the_start(self):
        first, second = self.filed(), self.filed()
        ctx = self.ctx()

        def spending(store, book, version):
            out = self.fake(store, book, version)
            ctx.deadline = self.now
            return out

        self.run_step(spending, ctx=ctx)
        self.assertEqual(self.fake.calls, [first])


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
        self.run_step(FakeScan(["javascript_urls"]))
        self.assertIsNone(self.held(book))
        self.plan["hold_kinds"] = ["javascript_urls"]
        fake = FakeScan()
        self.run_step(fake)
        self.assertEqual((self.held(book), fake.calls), (["javascript_urls"], []))

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


# ---- Increment I: convert and index

class FakeConvert:
    """A converter that does what the test says, and files the conversion record the way the real one does."""

    def __init__(self, chars=1000, status="done", reason="the tool failed", error=None):
        self.chars, self.status, self.reason, self.error, self.calls = chars, status, reason, error, []

    def __call__(self, store, book_id, version_id):
        self.calls.append(book_id)
        if self.error is not None:
            raise self.error
        if self.status == "done":
            record = {"tool": "kb-t", "version": "1", "generation": 1, "payload": "derived/kb-t/1", "parse": "blocks-json", "quality": "full", "blocks": 3, "chars": self.chars, "pages": None, "truncated": False}
            check = {"rule": "extractor-size", "compared": False, "partial": False, "reasons": [], "ratio": 2.0, "chars": {"kb-t 1": self.chars}, "notes": {}}
            store.set_version_conversions(book_id, version_id, [record], {"tool": "kb-t", "version": "1", "generation": 1}, check)
            stages.mark(store, book_id, version_id, "converted", "done", tool="kb-t 1")
            return {"status": "done"}
        stages.mark(store, book_id, version_id, "converted", self.status, reason=self.reason, tool="kb-t 1")
        return {"status": self.status, "reason": self.reason}


class FakeIndex:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def __call__(self, store, book_id, version_id):
        self.calls.append(book_id)
        if self.error is not None:
            raise self.error
        stages.mark(store, book_id, version_id, "indexed", "done", tool="kb-index")
        return {"status": "done"}


class ConvertCase(Case):
    def setUp(self):
        super().setUp()
        self.conn = crawlqueue.connect(self.index)
        self.addCleanup(self.conn.close)
        self.convert, self.index_fake = FakeConvert(), FakeIndex()
        self.tripped = []

    def scanned_book(self, scanned=True, **kw):
        """A crawl book, found with a candidate row that is `kept` for it, whose scan is over."""
        number = 100 + self.stamp + 1
        book = self.filed(candidate=number, **kw)
        self.conn.execute("INSERT INTO candidates(id, identity_key, address, source, domain, status, book_id, added, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                          (number, f"k{number}", f"http://a.test/{number}", "openalex", "a.test", "kept", book, "2026-11-16T10:00:00Z", "2026-11-16T10:00:00Z"))
        if scanned:
            FakeScan()(self.store, book, self.version(book))
        return book

    def row(self, book):
        return self.conn.execute("SELECT status, reason FROM candidates WHERE book_id = ?", (book,)).fetchone()

    def stage(self, book, name):
        return stages.read(self.store, book, self.version(book))["stages"][name]["status"]

    def ctx(self):
        ctx = super().ctx()
        ctx.conn = self.conn

        def trip(kind, reason):
            ctx.tripped = True
            self.tripped.append((kind, reason))
            return crawlguard.trip(self.index, kind, reason, "run-1", now=self.now, log=self.log)

        ctx.trip = trip
        return ctx

    def run_convert(self, ctx=None, convert=None, index=None, statvfs=roomy):
        ctx = ctx or self.ctx()
        crawlsteps.make_convert_step(convert=convert or self.convert, index=index or self.index_fake, statvfs=statvfs)(ctx)
        return ctx

    def parked(self, book):
        found = [e for e in self.events(book) if e["event"] == "crawl_rejected"]
        return found[0] if found else None


class ConvertAndIndex(ConvertCase):
    def test_a_scanned_book_is_converted_and_then_indexed_and_the_stages_and_lines_say_so(self):
        book = self.scanned_book()
        ctx = self.run_convert()
        self.assertEqual((self.convert.calls, self.index_fake.calls), ([book], [book]))
        self.assertEqual((self.stage(book, "converted"), self.stage(book, "indexed")), ("done", "done"))
        self.assertEqual([(x["step"], x["outcome"], x["book"]) for x in self.lines()], [("convert", "ok", book), ("index", "ok", book)])
        self.assertEqual(self.listed(), [book])
        self.assertEqual(ctx.convert_report, {"converted": 1, "indexed": 1, "held": 0, "rejected": 0, "failed": 0, "parked": 0, "ended": "all the books are converted and indexed"})

    def test_the_second_run_does_nothing_and_a_book_converted_before_a_death_is_only_indexed(self):
        done, half = self.scanned_book(), self.scanned_book()
        self.run_convert()
        self.convert.calls.clear()
        self.index_fake.calls.clear()
        before = (len(self.lines()), self.events(done))
        self.run_convert()
        self.assertEqual((self.convert.calls, self.index_fake.calls, len(self.lines()), self.events(done)), ([], [], before[0], before[1]))
        third = self.scanned_book()
        FakeConvert()(self.store, third, self.version(third))
        self.run_convert()
        self.assertEqual((self.convert.calls, self.index_fake.calls), ([], [third]))

    def test_only_a_book_whose_scan_is_done_and_that_is_not_final_is_converted(self):
        pending = self.scanned_book(scanned=False)
        failed = self.scanned_book(scanned=False)
        stages.mark(self.store, failed, self.version(failed), "scanned", "failed", reason="the tool failed", tool=scan.TOOL_LABEL)
        skipped = self.scanned_book(scanned=False)
        stages.mark(self.store, skipped, self.version(skipped), "scanned", "skipped", reason="no scanner", tool=scan.TOOL_LABEL)
        held, unplaced = self.scanned_book(), self.scanned_book()
        crawlbooks.record_held(self.store, held, ["encrypted"])
        crawlbooks.record_unplaced(self.store, unplaced, "none")
        stranger = self.scanned_book()
        self.store.append_event(stranger, "crawl_rejected", reason="x", score=None, stage="judge")
        owner = self.book(auto_filed=False)
        mine = self.scanned_book()
        self.run_convert()
        self.assertEqual(self.convert.calls, [mine])
        self.assertEqual((self.index_fake.calls, self.events(owner)), ([mine], []))
        for book in (pending, failed, skipped):
            self.assertEqual(self.stage(book, "converted"), "pending")

    def test_a_book_of_an_unapproved_plan_is_not_converted(self):
        book = self.scanned_book(digest="f" * 32)
        self.run_convert()
        self.assertEqual((self.convert.calls, self.stage(book, "converted")), ([], "pending"))

    def test_the_books_are_taken_oldest_found_first(self):
        a, b, c = self.scanned_book(), self.scanned_book(), self.scanned_book()
        self.run_convert()
        self.assertEqual((self.convert.calls, self.index_fake.calls), ([a, b, c], [a, b, c]))


class ConvertRefusals(ConvertCase):
    def test_the_disk_floors_are_read_before_each_conversion_and_each_index_write(self):
        self.scanned_book()
        self.scanned_book()
        asked = []

        def reading(path):
            asked.append(path)
            return roomy(path)

        self.run_convert(statvfs=reading)
        self.assertEqual(len(asked), 4 * 2)                                  # two floors (bulk and index) before each of 2 conversions and 2 index writes

    def test_a_floor_before_the_index_write_leaves_the_book_converted_and_ends_the_step_quietly(self):
        book, other = self.scanned_book(), self.scanned_book()
        reads = []

        def reading(path):
            reads.append(path)
            return roomy(path) if len(reads) <= 2 else types.SimpleNamespace(f_bavail=1, f_frsize=4096)

        ctx = self.run_convert(statvfs=reading)
        self.assertEqual((self.stage(book, "converted"), self.stage(book, "indexed"), self.stage(other, "converted")), ("done", "pending", "pending"))
        self.assertEqual((self.convert.calls, self.index_fake.calls), ([book], []))
        last = self.lines()[-1]
        self.assertEqual((last["step"], last["outcome"]), ("convert", "skipped"))
        self.assertIn("floor", last["reason"])
        self.assertEqual((self.parked(book), ctx.tripped), (None, False))

    def test_the_stop_file_is_looked_at_before_each_conversion_and_each_index_write(self):
        first, second = self.scanned_book(), self.scanned_book()

        def stopping(store, book, version):
            out = self.convert(store, book, version)
            open(os.path.join(self.index, "crawl.stop"), "w").close()
            return out

        self.run_convert(convert=stopping)
        self.assertEqual((self.convert.calls, self.index_fake.calls), ([first], []))
        self.assertEqual((self.stage(first, "converted"), self.stage(first, "indexed"), self.stage(second, "converted")), ("done", "pending", "pending"))
        self.assertEqual(self.lines()[-1]["reason"], "the stop file is present")

    def test_a_refusal_is_said_once_and_the_books_after_it_wait(self):
        for _ in range(3):
            self.scanned_book()
        full = lambda path: types.SimpleNamespace(f_bavail=1, f_frsize=4096)    # noqa: E731
        self.run_convert(statvfs=full)
        self.assertEqual([(x["step"], x["outcome"]) for x in self.lines()], [("convert", "skipped")])

    def test_a_stop_file_at_the_start_does_nothing_and_a_refusal_is_no_failed_try(self):
        book = self.scanned_book()
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.run_convert()
        self.assertEqual((self.convert.calls, self.names(book).count("crawl_step_failed")), ([], 0))


class ConverterFailures(ConvertCase):
    def test_a_converter_that_fails_is_a_failed_try_and_at_retries_the_book_is_parked_and_its_row_rejected(self):
        book = self.scanned_book()
        bad = FakeConvert(status="failed")
        for expected in ("retry", "retry", "parked"):
            self.run_convert(convert=bad)
            self.assertEqual(self.parked(book) is not None, expected == "parked")
        self.assertEqual(self.names(book).count("crawl_step_failed"), 3)
        found = self.parked(book)
        self.assertEqual((found["stage"], self.store.read_book(book)["state"]), ("convert", "weeded"))
        self.assertEqual(self.row(book)[0], "rejected")
        self.assertEqual(self.listed(), [])
        before = len(bad.calls)
        self.run_convert(convert=bad)
        self.assertEqual(len(bad.calls), before)                              # parked: never converted again

    def test_a_failed_try_and_a_rejection_are_each_one_line_with_a_fixed_reason(self):
        failing, short = self.scanned_book(), self.scanned_book()
        fakes = {failing: FakeConvert(status="failed"), short: FakeConvert(chars=3)}
        self.run_convert(convert=lambda store, book, version: fakes[book](store, book, version))
        self.assertEqual([(x["step"], x["outcome"], x["book"], x["reason"]) for x in self.lines()],
                         [("convert", "failed", failing, "the conversion failed"), ("convert", "ok", short, None), ("reject", "rejected", short, "the converted text is shorter than min_chars")])

    def test_a_book_that_fails_its_last_try_is_said_to_be_parked(self):
        book = self.scanned_book()
        self.plan["retries"] = 1
        self.run_convert(convert=FakeConvert(status="failed"))
        self.assertEqual([(x["step"], x["outcome"], x["reason"]) for x in self.lines()], [("reject", "rejected", "the book is parked after failed tries")])
        self.assertEqual(self.row(book)[0], "rejected")

    def test_a_result_that_is_neither_done_failed_nor_skipped_is_a_failed_try(self):
        book = self.scanned_book()
        self.run_convert(convert=lambda store, b, v: {"status": "odd"})
        self.assertEqual((self.names(book).count("crawl_step_failed"), self.stage(book, "converted")), (1, "pending"))

    def test_every_way_a_converter_can_die_is_a_failed_try_and_not_a_crash_of_the_step(self):
        for error in (KbError("the tool failed"), OSError("no space"), ValueError("bad"), MemoryError(), KeyError("odd"), TypeError("odd"), RuntimeError("odd")):
            with self.subTest(type(error).__name__):
                book = self.scanned_book()
                self.run_convert(convert=FakeConvert(error=error))
                self.assertEqual((self.names(book).count("crawl_step_failed"), self.parked(book)), (1, None))

    def test_a_converter_that_is_not_made_for_the_file_rejects_the_book_at_once(self):
        book = self.scanned_book()
        self.run_convert(convert=FakeConvert(status="skipped", reason="there is no converter for this kind of file"))
        self.assertEqual((self.parked(book)["stage"], self.row(book)[0]), ("convert", "rejected"))
        self.assertEqual(self.index_fake.calls, [])

    def test_one_dead_converter_does_not_trip_the_breaker_and_the_other_books_go_on(self):
        a, b = self.scanned_book(), self.scanned_book()
        self.plan["retries"] = 1
        fakes = {a: FakeConvert(status="failed"), b: self.convert}
        ctx = self.run_convert(convert=lambda store, book, version: fakes[book](store, book, version))
        self.assertEqual((ctx.tripped, self.tripped, self.stage(b, "indexed")), (False, [], "done"))
        self.assertIsNotNone(self.parked(a))

    def test_books_parked_in_one_run_over_the_bound_trip_the_breaker_as_a_stage_bound_and_end_the_run(self):
        self.plan.update(retries=1, consecutive_failures=2)
        books = [self.scanned_book() for _ in range(3)]
        ctx = self.ctx()
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_convert(ctx=ctx, convert=FakeConvert(status="failed"))
        self.assertEqual([self.parked(b) is not None for b in books], [True, True, False])
        self.assertEqual(self.tripped[0][0], "stage_bound")
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        self.assertEqual(ctx.convert_report["parked"], 2)
        self.assertEqual(ctx.convert_report["ended"], "the circuit breaker was tripped")

    def test_the_real_converter_with_no_approved_tool_is_a_failed_try_and_text_from_it_reaches_no_event_or_line(self):
        book = self.scanned_book()
        crawlsteps.make_convert_step(index=self.index_fake, statvfs=roomy)(self.ctx())              # the real converter: this temporary config approves no tool
        self.assertEqual((self.names(book).count("crawl_step_failed"), self.stage(book, "converted")), (1, "failed"))

    def test_what_a_tool_said_never_reaches_an_event_a_log_line_or_a_row(self):
        book = self.scanned_book()
        self.run_convert(convert=FakeConvert(status="failed", reason="Authorization: Bearer abcdefgh12345 CANARY-text"))
        text = json.dumps([self.lines(), self.events(book), self.row(book)])
        self.assertNotIn("CANARY", text)
        self.assertNotIn("abcdefgh12345", text)


class TextLimits(ConvertCase):
    def test_a_converted_text_shorter_than_min_chars_is_rejected_with_its_reason_and_never_indexed(self):
        self.plan["min_chars"] = 400
        book = self.scanned_book()
        self.run_convert(convert=FakeConvert(chars=399))
        found = self.parked(book)
        self.assertEqual((found["stage"], found["reason"]), ("convert", "the converted text is shorter than min_chars"))
        self.assertEqual((self.row(book), self.index_fake.calls), (("rejected", "the converted text is shorter than min_chars"), []))

    def test_a_converted_text_over_the_size_limit_is_rejected_with_its_reason(self):
        book = self.scanned_book()
        self.run_convert(convert=FakeConvert(chars=crawlsteps.MAX_TEXT_CHARS + 1))
        found = self.parked(book)
        self.assertEqual((found["stage"], found["reason"]), ("convert", "the converted text is over the size limit"))
        self.assertEqual((self.row(book)[0], self.index_fake.calls), ("rejected", []))

    def test_the_size_limit_is_five_million_characters_exactly(self):
        ok, over = self.scanned_book(), self.scanned_book()
        fakes = {ok: FakeConvert(chars=5_000_000), over: FakeConvert(chars=5_000_001)}
        self.run_convert(convert=lambda store, book, version: fakes[book](store, book, version))
        self.assertEqual((self.index_fake.calls, self.parked(ok), self.parked(over)["reason"]), ([ok], None, "the converted text is over the size limit"))

    def test_the_text_of_the_conversion_in_use_is_the_one_that_is_measured(self):
        book = self.scanned_book()
        version = self.version(book)
        records = [{"tool": "kb-a", "version": "1", "generation": 1, "payload": "derived/kb-a/1", "parse": "blocks-json", "quality": "full", "blocks": 1, "chars": 10, "pages": None, "truncated": False},
                   {"tool": "kb-b", "version": "1", "generation": 1, "payload": "derived/kb-b/1", "parse": "blocks-json", "quality": "full", "blocks": 1, "chars": 1000, "pages": None, "truncated": False}]
        check = {"rule": "extractor-size", "compared": True, "partial": False, "reasons": [], "ratio": 2.0, "chars": {"kb-a 1": 10, "kb-b 1": 1000}, "notes": {}}
        self.store.set_version_conversions(book, version, records, {"tool": "kb-b", "version": "1", "generation": 1}, check)
        stages.mark(self.store, book, version, "converted", "done", tool="kb-a 1 + kb-b 1")
        self.run_convert()
        self.assertEqual((self.parked(book), self.index_fake.calls), (None, [book]))

    def test_a_conversion_that_is_done_but_has_no_record_is_a_failed_try(self):
        book = self.scanned_book()
        stages.mark(self.store, book, self.version(book), "converted", "done", tool="kb-t 1")
        self.run_convert()
        self.assertEqual((self.names(book).count("crawl_step_failed"), self.index_fake.calls), (1, []))

    def test_a_text_at_each_limit_is_taken(self):
        low, high = self.scanned_book(), self.scanned_book()
        fakes = {low: FakeConvert(chars=self.plan["min_chars"]), high: FakeConvert(chars=crawlsteps.MAX_TEXT_CHARS)}
        self.run_convert(convert=lambda store, book, version: fakes[book](store, book, version))
        self.assertEqual((self.index_fake.calls, self.parked(low), self.parked(high)), ([low, high], None, None))

    def test_a_book_converted_in_an_earlier_run_is_checked_before_it_is_indexed(self):
        book = self.scanned_book()
        FakeConvert(chars=3)(self.store, book, self.version(book))
        self.run_convert()
        self.assertEqual((self.parked(book)["reason"], self.index_fake.calls), ("the converted text is shorter than min_chars", []))


class IndexFailures(ConvertCase):
    def test_an_index_write_that_fails_is_a_failed_try_for_the_index_step_and_at_retries_the_book_is_parked(self):
        book = self.scanned_book()
        bad = FakeIndex(error=KbError("the search index could not be written"))
        for _ in range(3):
            self.run_convert(index=bad)
        found = self.parked(book)
        self.assertEqual((found["stage"], self.row(book)[0], self.stage(book, "converted")), ("index", "rejected", "done"))
        self.assertEqual([e["step"] for e in self.events(book) if e["event"] == "crawl_step_failed"], ["index"] * 3)         # the failure that parks the book is recorded too

    def test_an_index_that_dies_in_any_way_is_a_failed_try_too(self):
        for error in (OSError("disk"), KeyError("odd"), TypeError("odd"), MemoryError()):
            with self.subTest(type(error).__name__):
                book = self.scanned_book()
                self.run_convert(index=FakeIndex(error=error))
                self.assertEqual((self.names(book).count("crawl_step_failed"), self.parked(book)), (1, None))


class OneBook(ConvertCase):
    def test_a_book_that_is_final_is_not_converted_even_when_asked_directly(self):
        book = self.scanned_book()
        crawlbooks.record_held(self.store, book, ["encrypted"])
        got = crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy)
        self.assertEqual((got, self.convert.calls), (("final", None), []))

    def test_the_convert_step_forgets_the_index_rows_of_a_book_it_held(self):
        book = self.scanned_book(scanned=False)
        FakeScan(["javascript"])(self.store, book, self.version(book))
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            ctx = self.run_convert()
        self.assertEqual((forget.call_count, ctx.convert_report["held"], self.store.read_book(book)["state"]), (1, 1, "weeded"))

    def test_the_convert_step_forgets_the_index_rows_of_a_hold_it_finished(self):
        book = self.scanned_book()
        crawlbooks.record_held(self.store, book, ["encrypted"])
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_convert()
        self.assertEqual((forget.call_count, self.store.read_book(book)["state"]), (1, "weeded"))

    def test_the_convert_step_forgets_nothing_when_it_held_nothing(self):
        self.scanned_book()
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_convert()
        self.assertEqual(forget.call_count, 0)

    def test_a_book_scanned_with_hold_findings_whose_hold_was_never_written_is_held_here_and_not_converted(self):
        book = self.scanned_book(scanned=False)
        FakeScan(["javascript"])(self.store, book, self.version(book))               # the scan step died between the scan and the hold
        got = crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy)
        self.assertEqual((got, self.convert.calls, self.held(book)), (("held", None), [], ["javascript"]))

    def test_findings_the_plan_does_not_hold_do_not_stop_the_conversion(self):
        book = self.scanned_book(scanned=False)
        FakeScan(["javascript_urls", "script_elements"])(self.store, book, self.version(book))
        got = crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy)
        self.assertEqual((got, self.convert.calls, self.held(book)), (("done", None), [book], None))

    def test_a_book_whose_findings_cannot_be_read_is_held_as_failed_and_not_converted(self):
        book = self.scanned_book()
        with mock.patch.object(self.store.__class__, "read_version", side_effect=KbError("unreadable")):
            got = crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy)
        self.assertEqual((got, self.convert.calls, self.held(book)), (("held", None), [], ["scan_failed"]))

    def test_a_book_whose_stage_file_cannot_be_read_is_left_alone(self):
        book = self.scanned_book()
        with mock.patch.object(crawlsteps.stages, "read", side_effect=KbError("unreadable")):
            got = crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy)
        self.assertEqual((got, self.convert.calls), (("skipped", None), []))

    def test_a_book_with_no_scan_yet_is_left_alone_when_asked_directly(self):
        book = self.scanned_book(scanned=False)
        self.assertEqual(crawlsteps.convert_and_index(self.ctx(), self.store, book, self.convert, self.index_fake, roomy), ("skipped", None))


class Sweep(ConvertCase):
    def test_a_book_weeded_whose_row_was_not_rejected_before_a_death_gets_its_row_rejected_the_next_run(self):
        book = self.scanned_book()
        crawlbooks.record_rejected(self.store, book, "the judge said no", 0.1, "judge")        # the event was written, the state and the row were not
        self.assertEqual((self.store.read_book(book)["state"], self.row(book)[0]), ("active", "kept"))
        self.run_convert()
        self.assertEqual((self.store.read_book(book)["state"], self.row(book)[0], self.convert.calls), ("weeded", "rejected", []))
        self.assertEqual(self.row(book)[1], "the judge said no")
        before = self.lines()
        self.run_convert()
        self.assertEqual(self.lines(), before)

    def test_a_held_or_unplaced_book_keeps_its_row_and_nothing_else_is_swept(self):
        held = self.scanned_book()
        crawlbooks.record_held(self.store, held, ["encrypted"])
        self.run_convert()
        self.assertEqual((self.row(held)[0], self.store.read_book(held)["state"]), ("kept", "weeded"))       # a hold that died before its state is finished; the row of a held book stays `kept`: the book is only kept aside


class ConvertWiring(ConvertCase):
    def test_the_module_has_a_default_convert_step(self):
        self.assertTrue(callable(crawlsteps.convert_step))


# ---- Increment J: the judgement step

class FakeJudge:
    """`crawljudge.judge_book`, with the result each book is told to give (default: kept), and a note of each call."""

    def __init__(self, results=None, default="kept", error=None):
        self.results, self.default, self.error, self.calls = results or {}, default, error, []

    def __call__(self, store, conn, cfg, plan, book_id, version_id, run, now, embed=None, charge=True):
        self.calls.append({"book": book_id, "version": version_id, "run": run, "now": now, "embed": embed, "plan": plan, "cfg": cfg, "charge": charge})
        if self.error is not None:
            raise self.error
        outcome = self.results.get(book_id, self.default)
        if outcome in ("retry", "parked") and not charge:                # a model that failed, left to the step: it asks the entry, and charges the try only when the entry answers
            return {"outcome": "model_failed", "ok": None, "score": None, "shelf": None, "reason": "CANARY-reason"}
        nodoc = outcome == "nodoc"                                    # a text that is not a document: rejected, with no score and no call of the model
        outcome = "rejected" if nodoc else outcome
        shelf = "pid" if outcome in ("kept", "rejected") and not nodoc else None
        score = 0.7 if outcome in ("kept", "rejected") and not nodoc else None
        return {"outcome": outcome, "ok": outcome == "kept", "score": score, "shelf": shelf, "reason": "CANARY-reason" if outcome != "kept" else None}


class JudgeCase(ConvertCase):
    def setUp(self):
        super().setUp()
        self.plan["threshold"] = 0.4
        self.judge = FakeJudge()
        self.probes = []
        self.up = True
        emb = {"bridge": "ask-ollama", "server": "ned", "model": "m", "kind": "embedding", "dimension": 8}          # (as the registry of the models accepts it)
        self.cfg = dict(self.cfg, models_on=True, models={"emb": emb}, tasks={"place-embed": "emb"})

    def probe(self, cfg, task=None):
        self.probes.append(task)
        return self.up

    def ready(self, **kw):
        """A crawl book that is scanned, converted and indexed: the books the judgement takes."""
        book = self.scanned_book(**kw)
        version = self.version(book)
        FakeConvert()(self.store, book, version)
        FakeIndex()(self.store, book, version)
        return book

    def run_judge(self, ctx=None, judge=None, statvfs=roomy, **kw):
        ctx = ctx or self.ctx()
        kw.setdefault("probe", self.probe)
        crawlsteps.make_judge_step(judge=judge or self.judge, statvfs=statvfs, **kw)(ctx)
        return ctx

    def clock_state(self):
        return crawlguard.load_state(self.index)[0]["entries_down"].get("emb")


class JudgingOrder(JudgeCase):
    def test_every_scanned_converted_and_indexed_book_is_judged_oldest_first_with_the_version_of_its_own_record(self):
        a, b, c = self.ready(), self.ready(), self.ready()
        embed = object()
        ctx = self.run_judge(embed=embed)
        self.assertEqual([x["book"] for x in self.judge.calls], [a, b, c])
        first = self.judge.calls[0]
        self.assertEqual((first["version"], first["run"], first["now"], first["embed"], first["plan"] is self.plan, first["cfg"] is ctx.cfg), (self.version(a), "run-1", NOW, embed, True, True))
        self.assertEqual(ctx.judge_report, {"kept": 3, "rejected": 0, "retry": 0, "parked": 0, "ended": "all the books are judged"})

    def test_only_a_book_that_has_been_through_the_earlier_steps_and_is_not_final_is_judged(self):
        unscanned = self.scanned_book(scanned=False)
        unconverted = self.scanned_book()
        unindexed = self.scanned_book()
        FakeConvert()(self.store, unindexed, self.version(unindexed))
        held = self.ready()
        crawlbooks.record_held(self.store, held, ["encrypted"])
        kept = self.ready()
        crawlbooks.record_judged(self.store, kept, 0.8, "pid", True)
        stranger = self.ready(digest="f" * 32)
        owner = self.book(auto_filed=False)
        mine = self.ready()
        self.run_judge()
        self.assertEqual([x["book"] for x in self.judge.calls], [mine])
        for book in (unscanned, unconverted, unindexed):
            self.assertEqual(self.names(book).count("crawl_judged"), 0)
        self.assertEqual(self.events(owner), [])

    def test_a_judged_book_is_not_judged_again_and_a_second_run_writes_nothing(self):
        book = self.ready()
        crawlbooks.record_judged(self.store, book, 0.8, "pid", True)
        before = len(self.lines())
        self.run_judge()
        self.assertEqual((self.judge.calls, len(self.lines())), ([], before))

    def test_an_empty_threshold_refuses_the_step_before_any_call(self):
        self.ready()
        self.plan["threshold"] = None
        with self.assertRaises(crawlrun.StepRefused):
            self.run_judge()
        self.assertEqual(self.judge.calls, [])


class JudgingEligibility(JudgeCase):
    def test_a_book_whose_scan_did_not_finish_well_is_not_judged_even_if_it_was_converted_and_indexed(self):
        book = self.scanned_book(scanned=False)
        version = self.version(book)
        stages.mark(self.store, book, version, "scanned", "failed", reason="the tool failed", tool=scan.TOOL_LABEL)
        FakeConvert()(self.store, book, version)
        FakeIndex()(self.store, book, version)
        self.run_judge()
        self.assertEqual(self.judge.calls, [])

    def test_a_book_with_a_verdict_of_no_that_was_not_weeded_yet_is_given_to_the_judge_to_finish(self):
        book = self.ready()
        crawlbooks.record_judged(self.store, book, 0.1, "pid", False)
        self.run_judge()
        self.assertEqual([x["book"] for x in self.judge.calls], [book])

    def test_a_book_whose_stage_file_cannot_be_read_is_left_out_and_the_others_go_on(self):
        bad, good = self.ready(), self.ready()
        real = stages.read

        def read(store, book, version):
            if book == bad:
                raise KbError("unreadable")
            return real(store, book, version)

        with mock.patch.object(crawlsteps.stages, "read", read):
            self.run_judge()
        self.assertEqual([x["book"] for x in self.judge.calls], [good])

    def test_a_half_finished_rejection_is_finished_at_the_start_and_takes_the_book_out_of_the_index(self):
        book = self.ready()
        crawlbooks.record_rejected(self.store, book, "the judge said no", 0.1, "judge")
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_judge()
        self.assertEqual((self.row(book)[0], self.store.read_book(book)["state"], forget.call_count, self.judge.calls), ("rejected", "weeded", 1, []))


class TheBudgetInTheLaterSteps(JudgeCase):
    def test_the_convert_step_and_the_judge_step_begin_no_work_when_the_budget_of_the_run_is_spent(self):
        book = self.ready()
        done = self.scanned_book()
        for name, run, calls in (("convert", lambda ctx: self.run_convert(ctx=ctx), self.convert.calls), ("judge", lambda ctx: self.run_judge(ctx=ctx), self.judge.calls)):
            with self.subTest(name):
                ctx = self.ctx()
                ctx.deadline = self.now
                run(ctx)
                self.assertEqual(calls, [])
                self.assertEqual(self.names(book).count("crawl_step_failed"), 0)
                self.assertEqual(self.lines()[-1]["reason"], "the time budget of the run is spent")
        self.assertEqual(self.stage(done, "converted"), "pending")


class JudgingRefusals(JudgeCase):
    def test_the_stop_file_and_the_disk_floors_are_looked_at_before_each_call(self):
        first, second = self.ready(), self.ready()
        asked = []

        def reading(path):
            asked.append(path)
            return roomy(path)

        def stopping(store, conn, cfg, plan, book, version, run, now, embed=None, charge=True):
            out = self.judge(store, conn, cfg, plan, book, version, run, now, embed=embed, charge=charge)
            open(os.path.join(self.index, "crawl.stop"), "w").close()
            return out

        self.run_judge(judge=stopping, statvfs=reading)
        self.assertEqual(([x["book"] for x in self.judge.calls], len(asked)), ([first], 2))
        last = self.lines()[-1]
        self.assertEqual((last["step"], last["outcome"], last["reason"]), ("judge", "skipped", "the stop file is present"))
        self.assertEqual((self.names(second).count("crawl_step_failed"), self.names(first).count("crawl_step_failed")), (0, 0))

    def test_a_disk_floor_ends_the_step_quietly_with_no_failed_try(self):
        book = self.ready()
        full = lambda path: types.SimpleNamespace(f_bavail=1, f_frsize=4096)    # noqa: E731
        ctx = self.run_judge(statvfs=full)
        self.assertEqual((self.judge.calls, self.names(book).count("crawl_step_failed"), ctx.tripped), ([], 0, False))
        self.assertIn("floor", self.lines()[-1]["reason"])


class JudgingFailures(JudgeCase):
    def test_a_kept_verdict_clears_the_down_clock_and_asks_nothing_of_the_probe(self):
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [], "entries_down": {"emb": "2026-11-16T11:55:00Z"}})
        self.ready()
        self.run_judge()
        self.assertEqual((self.clock_state(), self.probes), (None, []))

    def test_a_failed_try_asks_the_probe_and_a_server_that_does_not_answer_starts_the_clock_and_ends_the_step(self):
        a, b = self.ready(), self.ready()
        self.judge.results[a] = "retry"
        self.up = False
        ctx = self.run_judge()
        self.assertEqual(([x["book"] for x in self.judge.calls], len(self.probes), self.clock_state()), ([a], 1, "2026-11-16T12:00:00Z"))
        self.assertEqual((self.lines()[-1]["step"], self.lines()[-1]["outcome"], self.lines()[-1]["reason"]), ("judge", "failed", "the model server did not answer"))
        self.assertEqual((ctx.tripped, ctx.judge_report["retry"], ctx.judge_report["ended"]), (False, 0, "the model server did not answer"))      # a try is charged only when the entry answers
        self.assertEqual((self.probes, [x["charge"] for x in self.judge.calls], self.names(a).count("crawl_step_failed")), (["place-embed"], [False], 0))

    def test_an_entry_that_stays_down_for_more_runs_than_the_retries_costs_the_book_no_try_and_parks_nothing(self):
        self.plan["retries"] = 2
        self.up = False
        book = self.ready()
        self.judge.results[book] = "retry"
        for number in range(self.plan["retries"] + 2):
            self.run_judge()
        self.assertEqual((self.names(book).count("crawl_step_failed"), self.store.read_book(book)["state"], self.row(book)[0], len(self.judge.calls)), (0, "active", "kept", 4))
        self.assertEqual(self.probes, ["place-embed"] * 4)

    def test_a_failure_while_the_entry_answers_is_the_books_try_and_clears_the_clock_and_a_book_at_the_retries_is_parked(self):
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [], "entries_down": {"emb": "2026-11-16T11:55:00Z"}})
        self.plan["retries"] = 2
        book = self.ready()
        self.judge.results[book] = "retry"
        ctx = self.run_judge()
        self.assertEqual((self.names(book).count("crawl_step_failed"), self.clock_state(), ctx.judge_report["retry"], self.probes), (1, None, 1, ["place-embed"]))
        self.run_judge()
        self.assertEqual((self.parked(book)["stage"], self.row(book)[0]), ("judge", "rejected"))

    def test_a_config_with_no_entry_for_the_judgements_task_is_a_refusal_of_the_step_and_charges_no_try(self):
        book = self.ready()
        self.judge.results[book] = "retry"
        ctx = self.ctx()
        ctx.cfg = dict(self.cfg, tasks={})
        with self.assertRaises(crawlrun.StepRefused):
            self.run_judge(ctx=ctx)
        self.assertEqual((self.names(book).count("crawl_step_failed"), crawlguard.load_state(self.index)[0]["entries_down"]), (0, {}))

    def test_the_default_probe_asks_the_entry_of_the_judgements_own_task_with_the_config(self):
        book = self.ready()
        self.judge.results[book] = "retry"
        with mock.patch.object(crawlsteps.crawlguard, "probe_entry", return_value=False) as probe:
            crawlsteps.make_judge_step(judge=self.judge, statvfs=roomy)(self.ctx())
        probe.assert_called_once_with(self.cfg, "place-embed")

    def test_an_entry_down_for_over_the_limit_trips_even_when_the_old_clock_of_the_embedding_is_untouched(self):
        crawlguard.save_state(self.index, {"model_down_since": "2026-11-16T11:59:00Z", "history": [], "entries_down": {"emb": "2026-11-16T10:00:00Z"}})
        book = self.ready()
        self.judge.results[book] = "retry"
        self.up = False
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge()
        state = crawlguard.load_state(self.index)[0]
        self.assertEqual((self.tripped[0][0], "the model entry emb" in self.tripped[0][1], state["model_down_since"]), ("model_down", True, "2026-11-16T11:59:00Z"))

    def test_a_probe_that_raises_is_a_server_that_does_not_answer(self):
        for error in (KbError("refused"), OSError("no route")):
            with self.subTest(type(error).__name__):
                crawlguard.save_state(self.index, {"model_down_since": None, "history": [], "entries_down": {}})
                book = self.ready()
                self.judge.results[book] = "retry"

                def probe(cfg, task=None, error=error):
                    raise error

                self.run_judge(probe=probe)
                self.assertIsNotNone(self.clock_state())
                self.judge.results.clear()
                self.run_judge()                                              # the book is still waiting: judge it kept, so the next case starts clean
                self.assertIsNone(self.clock_state())

    def test_a_text_that_is_not_a_document_asks_no_model_and_neither_clears_the_clock_nor_ends_a_run_of_failures(self):
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [], "entries_down": {"emb": "2026-11-16T11:55:00Z"}})
        book = self.ready()
        self.judge.results[book] = "nodoc"
        self.run_judge()
        self.assertEqual(self.clock_state(), "2026-11-16T11:55:00Z")
        self.plan["consecutive_failures"] = 3
        books = [self.ready() for _ in range(4)]
        for n, kind in enumerate(("retry", "retry", "nodoc", "retry")):
            self.judge.results[books[n]] = kind
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge()
        self.assertEqual(self.tripped[0][0], "stage_bound")                   # a book that needs no model says nothing of the model: it leaves the run of failures as it was

    def test_a_server_found_down_after_an_answer_stays_down_in_the_clock(self):
        kept, failing = self.ready(), self.ready()
        self.judge.results[failing] = "retry"
        self.up = False
        self.run_judge()
        self.assertEqual(self.clock_state(), "2026-11-16T12:00:00Z")

    def test_stored_conversions_that_cannot_be_read_book_after_book_trip_the_breaker_as_a_stage_bound(self):
        self.plan["consecutive_failures"] = 2
        books = [self.ready() for _ in range(3)]
        bad = FakeJudge(error=KbError("the conversion cannot be read"))
        with mock.patch.object(crawlsteps.crawljudge, "converted_text", side_effect=KbError("the conversion cannot be read")), self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge(judge=bad)
        self.assertEqual((len(bad.calls), self.tripped[0][0]), (2, "stage_bound"))

    def test_a_server_that_has_been_down_for_longer_than_the_limit_trips_the_breaker_as_model_down(self):
        crawlguard.save_state(self.index, {"model_down_since": None, "history": [], "entries_down": {"emb": "2026-11-16T10:00:00Z"}})
        book = self.ready()
        self.judge.results[book] = "retry"
        self.up = False
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge()
        self.assertEqual(self.tripped[0][0], "model_down")

    def test_a_server_that_answers_but_fails_book_after_book_trips_the_breaker_as_a_stage_bound(self):
        self.plan["consecutive_failures"] = 3
        books = [self.ready() for _ in range(5)]
        self.judge.default = "retry"
        ctx = self.ctx()
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge(ctx=ctx)
        self.assertEqual(([x["book"] for x in self.judge.calls], self.tripped[0][0]), (books[:3], "stage_bound"))
        self.assertEqual(ctx.judge_report["ended"], "the circuit breaker was tripped")

    def test_a_good_verdict_between_failures_starts_the_count_again(self):
        self.plan["consecutive_failures"] = 3
        books = [self.ready() for _ in range(6)]
        for n in (0, 1, 3, 4):
            self.judge.results[books[n]] = "retry"
        self.run_judge()
        self.assertEqual(len(self.judge.calls), 6)
        self.assertEqual(self.tripped, [])

    def test_a_parked_book_counts_as_a_failure_too(self):
        self.plan["consecutive_failures"] = 2
        books = [self.ready() for _ in range(3)]
        self.judge.default = "parked"
        self.plan["retries"] = 1
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_judge()
        self.assertEqual(len(self.judge.calls), 2)

    def test_a_book_whose_stored_conversion_cannot_be_read_is_a_failed_try_and_at_retries_is_parked(self):
        book = self.ready()
        self.plan["retries"] = 2
        bad = FakeJudge(error=KbError("the conversion cannot be read"))
        with mock.patch.object(crawlsteps.crawljudge, "converted_text", side_effect=KbError("the conversion cannot be read")):
            self.run_judge(judge=bad)
            self.assertIsNone(self.parked(book))
            self.run_judge(judge=bad)
        self.assertEqual((self.parked(book)["stage"], self.row(book)[0]), ("judge", "rejected"))
        self.assertEqual([e["step"] for e in self.events(book) if e["event"] == "crawl_step_failed"], ["judge", "judge"])

    def test_an_error_that_is_not_a_kb_error_is_the_books_fault_and_a_failed_try_and_never_a_crash_of_the_step(self):
        book, other = self.ready(), self.ready()
        self.plan["retries"] = 2
        odd = FakeJudge(error=KeyError("a malformed record"))
        for patched in (mock.patch.object(crawlsteps.crawljudge, "converted_text", return_value=("A page", "text")),
                        mock.patch.object(crawlsteps.crawljudge, "converted_text", side_effect=TypeError("odd"))):
            with patched:
                self.run_judge(judge=odd)
        self.assertEqual((self.parked(book)["stage"], self.parked(other)["stage"], self.row(book)[0]), ("judge", "judge", "rejected"))

    def test_a_stored_conversion_that_fails_in_any_way_when_it_is_read_again_is_the_books_fault(self):
        book = self.ready()
        with mock.patch.object(crawlsteps.crawljudge, "converted_text", side_effect=TypeError("odd")):
            self.run_judge(judge=FakeJudge(error=KbError("could not judge")))
        self.assertEqual(self.names(book).count("crawl_step_failed"), 1)

    def test_a_refusal_that_is_not_the_books_ends_the_run_and_marks_no_book(self):
        book = self.ready()
        before = self.events(book)
        bad = FakeJudge(error=KbError("the shelf vectors are not there"))
        with mock.patch.object(crawlsteps.crawljudge, "converted_text", return_value=("A page", "text")), self.assertRaises(crawlrun.StepRefused):
            self.run_judge(judge=bad)
        self.assertEqual(self.events(book), before)


class JudgingRecords(JudgeCase):
    def test_a_rejection_or_a_parked_book_takes_its_index_rows_out_in_the_same_run_and_a_kept_one_does_not(self):
        keep, out = self.ready(), self.ready()
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_judge()
        self.assertEqual(forget.call_count, 0)
        self.judge.results[out] = "rejected"
        again = self.ready()
        self.judge.results[again] = "rejected"
        with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
            self.run_judge(judge=FakeJudge({again: "rejected"}))
        self.assertEqual(forget.call_count, 1)

    def test_a_rejected_book_alone_or_a_parked_book_alone_takes_the_index_rows_out(self):
        self.plan["retries"] = 1                                          # (the first failed try parks a book)
        for kind in ("rejected", "parked"):
            with self.subTest(kind):
                book = self.ready()
                with mock.patch.object(crawlsteps.index_stage, "forget_inactive") as forget:
                    self.run_judge(judge=FakeJudge({book: kind}, default="already_kept"))
                self.assertEqual(forget.call_count, 1)

    def test_the_report_counts_each_kind_of_outcome(self):
        books = [self.ready() for _ in range(5)]
        results = dict(zip(books, ("kept", "rejected", "retry", "parked", "already_kept")))
        self.plan["retries"] = 2
        crawlbooks.record_step_failed(self.store, books[3], "judge", "the model did not answer", "run-0")           # (one try already: the next parks this book)
        ctx = self.run_judge(judge=FakeJudge(results))
        self.assertEqual(ctx.judge_report, {"kept": 1, "rejected": 1, "retry": 1, "parked": 1, "ended": "all the books are judged"})

    def test_what_the_judge_returns_as_a_reason_is_never_written_by_the_step(self):
        books = [self.ready() for _ in range(2)]
        self.run_judge(judge=FakeJudge({books[0]: "rejected", books[1]: "retry"}))
        self.assertNotIn("CANARY", json.dumps([self.lines(), [self.events(b) for b in books]]))

    def test_the_real_judgement_keeps_a_document_and_weeds_one_that_is_not_and_asks_the_model_once_for_each(self):
        from engine.tests.test_crawljudge import FakeEmbed, document, shelves
        good, bad = self.ready(), self.ready()
        texts = {good: ("A page", document("pid", 0.8)), bad: ("A page", "short")}
        embed = FakeEmbed()
        with shelves(), mock.patch.object(crawlsteps.crawljudge, "converted_text", side_effect=lambda store, book, version: texts[book]):
            crawlsteps.make_judge_step(embed=embed, statvfs=roomy, probe=self.probe)(self.ctx())
            crawlsteps.make_judge_step(embed=embed, statvfs=roomy, probe=self.probe)(self.ctx())
        self.assertEqual((len(embed.calls), self.names(good).count("crawl_judged"), self.parked(bad)["stage"], self.row(bad)[0], self.row(good)[0]), (1, 1, "judge", "rejected", "kept"))
        self.assertEqual(self.store.read_book(bad)["state"], "weeded")


class JudgeWiring(JudgeCase):
    def test_the_module_has_a_default_judgement_step(self):
        self.assertTrue(callable(crawlsteps.judge_step))


if __name__ == "__main__":
    unittest.main()
