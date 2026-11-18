"""The `idle` step of a crawl run (`kb/crawlidle.py`, increment B of the plan `2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave`).

After the fetch, a run may spend `themes_window_s` seconds making themes for the books that have none, and gives the time back at a deadline. These tests run the real `themerun` on a temporary
library and index root, the real card lock and the real log, with a fake model whose every call moves a fake clock on; no test makes a request or calls a real model, reads the owner's config,
plan or key, or touches the owner's library.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlidle`."""
import datetime
import json
import os
import types
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_themecheck import config
from engine.tests.test_themeextract import JournalFake
from engine.tests.test_themerun import GOOD, REFUSED, SAYS, RunCase, scripted

from kb import KbError, cardstate, crawlguard, crawlidle, crawllog, crawlplan, crawlrun, models, theme, themerun

NOW = datetime.datetime(2026, 11, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
HOUR = datetime.timedelta(hours=1)


def roomy(path):
    return types.SimpleNamespace(f_bavail=10**9, f_frsize=4096)


def short(path):
    return types.SimpleNamespace(f_bavail=1, f_frsize=4096)


class IdleCase(RunCase):
    """A temporary library of converted books with cards, a crawl plan, a log, a fake clock and a context like the runner's."""

    def setUp(self):
        os.umask(0o077)
        super().setUp()
        self.now = NOW
        self.crawl_plan = crawlplan.defaults()
        self.crawl_plan.update(timezone="UTC", themes_window_s=600, model_down_minutes=30)
        os.makedirs(os.path.join(self.index_root(), "crawl"), mode=0o700, exist_ok=True)
        self.log = crawllog.Log(self.index_root(), "run-1", clock=lambda: self.now)
        self.tripped, self.probes, self.up_for = [], [], {}

    up = True

    def crawl_cfg(self):
        return {**config(), "bulk_root": self.store.cfg["bulk_root"], "index_root": self.index_root()}

    def ctx(self, cfg=None, deadline=None):
        ctx = types.SimpleNamespace(cfg=cfg or self.crawl_cfg(), index_root=self.index_root(), plan=self.crawl_plan, log=self.log, clock=lambda: self.now, run="run-1",
                                    deadline=deadline or self.now + HOUR, tripped=False, secrets=())

        def trip(kind, reason):
            ctx.tripped = True
            self.tripped.append((kind, reason))
            return crawlguard.trip(self.index_root(), kind, reason, "run-1", now=self.now, log=self.log)

        ctx.trip = trip
        return ctx

    def probe(self, cfg, task=None):
        self.probes.append(task)
        return self.up_for.get(task, self.up)

    def clocked(self, script, per_call=30, on_call=None):
        """`models.run_job` as a script of replies; each call, answered or not, moves the clock `per_call` seconds on."""
        fake = scripted(*script, fake_class=JournalFake)

        def call(*a, **k):
            try:
                return fake(*a, **k)
            finally:
                self.now += datetime.timedelta(seconds=per_call)
                if on_call:
                    on_call(len(fake.calls))
        call.calls = fake.calls
        return call

    def idle(self, script=(), per_call=30, ctx=None, on_call=None, **kw):
        kw.setdefault("statvfs", roomy)
        kw.setdefault("probe", self.probe)
        ctx = ctx or self.ctx()
        fake = self.clocked(script, per_call, on_call)
        self.fake = fake
        with mock.patch.object(models, "run_job", fake):
            crawlidle.make_step(**kw)(ctx)
        return ctx

    def lines(self, *steps):
        folder = os.path.join(self.index_root(), "crawl", "log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return [x for x in out if x["step"] in (steps or ("idle", "themes"))]

    def ended(self):
        got = [x for x in self.lines("idle")]
        self.assertEqual(len(got), 1, got)
        return got[0]

    def themed(self, book):
        return theme.generations(self.store, book, self.store.read_book(book)["current_version"])

    def stop_file(self):
        with open(os.path.join(self.index_root(), "crawl.stop"), "w"):
            pass

    def run_records(self):
        return [themerun.read_record(self.index_root(), name) for name in themerun._run_names(self.index_root())]


class WindowTest(IdleCase):
    def test_a_window_of_zero_makes_no_themes_plans_nothing_and_says_it_is_off(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 0
        self.idle()
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.written(), [])
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "off"))

    def test_the_books_with_no_themes_are_made_in_order_with_a_line_for_each_and_the_window_says_it_had_nothing_more_to_do(self):
        self.books(2)
        books = sorted(self.store.list_books())
        self.idle(GOOD + GOOD)
        self.assertEqual(len(self.fake.calls), 4)
        self.assertEqual([x["book"] for x in self.lines("themes")], books)
        self.assertEqual([x["outcome"] for x in self.lines("themes")], ["ok", "ok"])
        self.assertTrue(all(self.themed(b) for b in books))
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("ok", "nothing to do", 2))
        self.assertEqual(end["seconds"], 120)                            # four calls of 30 seconds
        cardstate_lock = cardstate.lock(self.index_root(), "after")      # the card lock was released
        with cardstate_lock:
            pass

    def test_only_an_active_book_with_a_card_and_a_conversion_and_no_themes_at_all_is_planned(self):
        self.books(1)
        eligible = self.store.list_books()[0]
        weeded, _ = self.converted_book()
        self.store.set_state(weeded, "weeded")
        no_card, _ = self.converted_book(with_card=False)
        no_version = self.store.create_book(title="No conversion", kind="preprint")
        made, version = self.converted_book()
        self.file_generation(made, version)                              # themes made with the current prompt
        old, old_version = self.converted_book()
        self.file_generation(old, old_version, prompt="v0")  # themes of an older prompt are the owner's to remake, not the window's
        empty, empty_version = self.converted_book()
        self.file_generation(empty, empty_version, themes=False)         # a generation with no themes counts as made
        self.idle(GOOD)
        records = self.run_records()
        self.assertEqual([[i["book_id"] for i in r["items"]] for r in records], [[eligible]])
        self.assertEqual(len(self.fake.calls), 2)
        for book in (weeded, no_card):
            self.assertFalse(self.themed(book))                          # nothing was filed for the books that were not eligible
        self.assertEqual(self.themed(old), [1])                          # the older generation is as it was: nothing new was filed

    def test_a_library_whose_only_books_without_themes_cannot_be_made_writes_no_record_however_often_it_is_asked(self):
        self.converted_book(with_card=False)
        weeded, _ = self.converted_book()
        self.store.set_state(weeded, "weeded")
        for _ in range(3):
            self.idle()
        self.assertEqual((self.fake.calls, self.written()), ([], []))      # no empty run is left in the folder by each window

    def test_no_more_than_a_batch_is_planned_at_a_time_and_a_later_batch_takes_the_rest(self):
        self.books(3)
        with mock.patch.object(crawlidle, "BATCH", 2):
            self.idle(GOOD * 3)
        self.assertEqual(sorted(len(r["items"]) for r in self.run_records()), [1, 2])
        self.assertEqual(len(self.fake.calls), 6)
        self.assertEqual(self.ended()["n"], 3)

    def test_a_library_with_every_book_themed_plans_nothing_and_writes_one_line_and_no_record(self):
        self.books(1)
        book = self.store.list_books()[0]
        self.file_generation(book, self.store.read_book(book)["current_version"])
        self.idle()
        self.assertEqual((self.fake.calls, self.written()), ([], []))
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("skipped", "nothing to do", 0))

    def test_the_models_for_themes_not_being_set_up_is_a_quiet_end_and_not_a_refusal_of_the_run(self):
        self.books(1)
        cfg = self.crawl_cfg()
        cfg["tasks"] = {}
        self.idle(ctx=self.ctx(cfg=cfg))
        self.assertEqual((self.fake.calls, self.written()), ([], []))
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "settings"))


class DeadlineTest(IdleCase):
    def test_the_window_ends_at_its_deadline_before_the_next_call_and_the_next_window_finishes_the_cut_book_from_its_pieces(self):
        self.books(2)
        first, second = sorted(self.store.list_books())
        self.crawl_plan["themes_window_s"] = 250
        self.idle(GOOD + GOOD, per_call=100)                              # book 1: 0 to 200 seconds; book 2: its piece at 200 to 300, then the deadline
        self.assertEqual(len(self.fake.calls), 3)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("ok", "deadline", 1))
        self.assertTrue(self.themed(first))
        self.assertFalse(self.themed(second))
        self.now += HOUR
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        self.idle([SAYS], per_call=10)
        self.assertEqual(len(self.fake.calls), 1)                         # the piece was not asked for again: only the check
        self.assertTrue(self.themed(second))

    def test_the_window_never_goes_past_the_time_budget_of_the_run(self):
        self.books(2)
        self.idle(GOOD + GOOD, per_call=100, ctx=self.ctx(deadline=NOW + datetime.timedelta(seconds=150)))
        self.assertEqual(len(self.fake.calls), 2)                         # calls at 0 and 100 seconds; at 200 the budget is spent
        self.assertEqual(self.ended()["reason"], "deadline")

    def test_a_stop_file_that_appears_in_the_middle_ends_the_window_before_the_next_call(self):
        self.books(2)
        self.idle(GOOD + GOOD, on_call=lambda n: self.stop_file() if n == 2 else None)
        self.assertEqual(len(self.fake.calls), 2)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "stopped"))

    def test_a_disk_floor_that_refuses_ends_the_window_before_anything_is_planned_or_asked(self):
        self.books(1)
        self.idle(statvfs=short)
        self.assertEqual((self.fake.calls, self.written()), ([], []))
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "disk"))

    def test_a_stop_file_that_is_there_when_the_step_begins_asks_nothing_and_plans_nothing(self):
        self.books(1)
        self.stop_file()
        self.idle()
        self.assertEqual((self.fake.calls, self.written()), ([], []))
        self.assertEqual(self.ended()["reason"], "stopped")


class LockTest(IdleCase):
    def test_a_card_lock_held_by_another_ends_the_themes_part_with_no_call_and_a_later_window_makes_the_themes(self):
        self.books(1)
        book = self.store.list_books()[0]
        with cardstate.lock(self.index_root(), "another-run"):
            self.idle()
            self.assertEqual(self.fake.calls, [])
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "locked"))
        self.assertFalse(self.themed(book))
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        self.idle(GOOD)
        self.assertTrue(self.themed(book))
        self.assertEqual(len(self.fake.calls), 2)


class FailureTest(IdleCase):
    def test_a_book_that_fails_has_a_line_and_the_rest_are_made_and_a_failed_book_is_not_tried_again_by_a_later_batch_of_the_same_window(self):
        self.books(2)
        bad, good = sorted(self.store.list_books())
        self.idle(REFUSED + GOOD + REFUSED)                           # the first book is refused twice, the second is made, the first is tried once more by the run
        self.assertEqual(len(self.fake.calls), 6)
        self.assertEqual([(x["book"], x["outcome"]) for x in self.lines("themes")], [(bad, "failed"), (good, "ok")])   # in the order of the plan
        self.assertEqual(len(self.run_records()), 1)                      # no second plan took the failed book again
        self.assertEqual(self.ended()["reason"], "nothing to do")

    def test_three_books_in_a_row_that_fail_end_the_window_and_the_model_entries_are_asked_once_each(self):
        self.books(4)
        self.idle([ValueError("x")] * 3)
        self.assertEqual(len(self.fake.calls), 3)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("failed", "failed"))
        self.assertEqual(self.probes, ["theme", "theme-check"])

    def test_a_model_that_does_not_answer_is_not_the_books_fault_and_a_clock_of_its_own_runs_until_it_trips_the_breaker(self):
        self.books(4)
        self.up_for = {"theme": False}
        self.idle([ValueError("x")] * 3)
        self.assertEqual(self.probes, ["theme"])                          # the first that does not answer ends the asking
        self.assertEqual(self.ended()["reason"], "failed")
        self.assertEqual(self.tripped, [])
        self.now += datetime.timedelta(minutes=31)
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        with self.assertRaises(crawlrun.BreakerTripped):
            self.idle([ValueError("x")] * 3)
        self.assertEqual([k for k, _ in self.tripped], ["model_down"])

    def test_a_run_of_books_that_all_work_asks_no_model_entry(self):
        self.books(2)
        self.idle(GOOD + GOOD)
        self.assertEqual(self.probes, [])


class EndTest(IdleCase):
    """What the window's own line says when something goes wrong, and that the loop always ends."""

    def test_an_error_before_the_work_is_a_failed_window_and_not_one_that_had_nothing_to_do(self):
        self.books(1)
        with mock.patch.object(themerun, "plan", side_effect=KbError("no room")):
            with self.assertRaises(KbError):
                self.idle()
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("failed", "failed", 0))

    def test_a_pass_that_makes_nothing_and_fails_nothing_ends_the_window_and_does_not_plan_again_and_again(self):
        self.books(1)
        book = self.store.list_books()[0]
        item = {"book_id": book, "version_id": "v1", "pieces": 1, "status": "waiting", "generation": None, "reason": "", "attempts": 0, "made": None, "stats": None}
        with mock.patch.object(themerun, "run", return_value={"items": [item], "stopped": None, "counts": {}}):
            self.idle()
        self.assertEqual(len(self.run_records()), 1)                      # the book was planned once
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "nothing to do"))

    def test_a_book_that_the_run_dropped_is_not_planned_again_in_the_same_window(self):
        self.books(2)
        first, second = sorted(self.store.list_books())
        real = themerun.run

        def dropping(library, cfg, run, **kw):
            if len(self.run_records()) == 1:                              # the first plan: the first book is dropped by the run, the other goes on
                rec = themerun.read_record(self.index_root(), run)
                rec["items"][0]["status"], rec["items"][0]["reason"] = "dropped", "conversion_changed"
                themerun.write_record(self.index_root(), rec)
            return real(library, cfg, run, **kw)
        with mock.patch.object(themerun, "run", dropping):
            self.idle(GOOD)
        self.assertEqual(len(self.run_records()), 1)                      # no second plan took the dropped book again
        self.assertEqual([(x["book"], x["outcome"], x["reason"]) for x in self.lines("themes")], [(first, "skipped", "conversion_changed"), (second, "ok", None)])

    def test_a_failure_at_the_deadline_asks_no_model_entry_and_the_window_says_it_ended_by_the_deadline(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 100
        self.idle([ValueError("x")], per_call=100)                        # the one call fails at the very second the window ends
        self.assertEqual(self.probes, [])
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("ok", "deadline"))

    def test_a_failure_with_the_stop_file_there_asks_no_model_entry_and_the_window_says_it_was_stopped(self):
        self.books(2)
        self.idle([ValueError("x")], on_call=lambda n: self.stop_file())
        self.assertEqual(self.probes, [])
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "stopped"))


class LogTest(IdleCase):
    def test_every_line_holds_a_fixed_sentence_a_number_or_an_id_and_never_text_of_a_book_or_a_reply(self):
        self.books(2)
        self.idle(GOOD + [ValueError("secret-xyz")] * 3)
        text = json.dumps(self.lines("idle", "themes"))
        for word in ("annealing", "secret-xyz", "cools a system", "A paper"):
            self.assertNotIn(word, text)


class RegistryTest(unittest.TestCase):
    def test_the_real_registry_attaches_the_step_at_the_idle_point(self):
        real = crawlrun.default_steps()
        self.assertIs(real["idle"], crawlidle.step)
        self.assertEqual(crawlrun.POINTS[-1], "idle")


if __name__ == "__main__":
    unittest.main()
