"""The `idle` step of a crawl run (`kb/crawlidle.py`, increment B of the plan `2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave`).

After the fetch, a run may spend `themes_window_s` seconds making themes for the books that have none, and gives the time back at a deadline. These tests run the real `themerun` on a temporary
library and index root, the real card lock and the real log, with a fake model whose every call moves a fake clock on; no test makes a request or calls a real model, reads the owner's config,
plan or key, or touches the owner's library.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlidle`."""
import contextlib
import datetime
import fcntl
import json
import os
import sqlite3
import types
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_models import embedding, fake_vector
from engine.tests.test_themecheck import config
from engine.tests.test_themeextract import JournalFake, row, values
from engine.tests.test_themerun import GOOD, REFUSED, SAYS, RunCase, scripted

from kb import KbError, cardstate, catalog, crawlguard, crawlidle, crawllog, crawlplan, crawlqueue, crawlrun, crawlstate, models, theme, themerun, themevectors, vectors

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

    def crawl_cfg(self, embedding_entry=True):
        cfg = {**config(), "bulk_root": self.store.cfg["bulk_root"], "index_root": self.index_root()}
        if embedding_entry:
            cfg["models"] = {**cfg["models"], "emb": embedding()}
            cfg["tasks"] = {**cfg["tasks"], "card-embed": "emb"}
        return cfg

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

    def distinct(self, n):
        """The script of the model for `n` books whose themes have texts that no other has (a theme and its check each), so that nothing is shared between their vectors."""
        out = []
        for i in range(n):
            out += [values(row(title=f"Book {i} theme", summary=f"A summary of book {i}.", problem=f"problem of book {i}", method=f"method of book {i}", needs=f"needs of book {i}",
                               provides=f"provides of book {i}")), GOOD[1]]
        return out

    def embedding_fake(self, per_call=5, on_call=None, fail=False):
        """`models.embed` with a vector made from the text, which moves the clock `per_call` seconds on for each call and notes how many texts each call held."""
        self.embedded = []

        def embed(cfg, name, texts, launcher=None, root=None, kind="document"):
            self.embedded.append(len(texts))
            self.now += datetime.timedelta(seconds=per_call)
            if on_call:
                on_call(len(self.embedded))
            if fail:
                raise KbError("the bridge failed")
            return {"model": "bge-m3:latest", "dimension": 4, "vectors": [fake_vector(t) for t in texts]}
        return embed

    def no_weave(self):
        """A stand-in for `kb.weave` with numpy and no weave file: its status says there is no weave, as a library that has none says."""
        def status(index_root, cfg, store, now=None):
            raise KbError("there is no weave")
        return types.SimpleNamespace(_np=lambda: None, status=status, repair=lambda *a, **k: self.fail("no repair was to be made"))

    def idle(self, script=(), per_call=30, ctx=None, on_call=None, embed_per_call=5, embed_on_call=None, embed_fail=False, cards=False, **kw):
        """Run the step. The part for the vectors of the cards is left out unless `cards` is true, so that the tests of the other parts count only what they made (plan
        `2026-11-20-refresh-the-card-vectors-in-the-idle-window-and-tell-the-skills-what-the-search-covers`, Increment B: the tests of that part are `CardVectorsTest`)."""
        kw.setdefault("statvfs", roomy)
        kw.setdefault("probe", self.probe)
        kw.setdefault("weave", self.no_weave())
        ctx = ctx or self.ctx()
        fake = self.clocked(script, per_call, on_call)
        self.fake = fake
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(models, "run_job", fake))
            stack.enter_context(mock.patch.object(models, "embed", self.embedding_fake(embed_per_call, embed_on_call, embed_fail)))
            if not cards:
                stack.enter_context(mock.patch.object(crawlidle, "_card_vectors", lambda *a, **k: None))
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
        self.assertEqual(end["seconds"], 125)                            # four calls of 30 seconds and the embedding of the vectors, one call of 5
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

    def test_a_book_converted_again_whose_older_version_has_themes_is_not_planned_for_its_new_version(self):
        reconverted, version = self.converted_book()
        self.file_generation(reconverted, version)                       # the themes of v1
        newer = self.store.add_version(reconverted, label="v2", source={"retrieved": "2026-11-02T00:00:00+00:00"})   # becomes the version in use
        self.assertNotEqual(newer, version)
        self.assertEqual(self.store.read_book(reconverted)["current_version"], newer)
        self.assertFalse(self.themed(reconverted))                       # the version in use has none
        with mock.patch.object(themerun, "_assess", return_value=("make", newer, 1, {})):   # whatever the plan would say of the new version
            self.idle()
        self.assertEqual((self.fake.calls, self.written()), ([], []))    # a change of the conversion tool must not have the window theme the library again
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("skipped", "nothing to do", 0))

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


class LongWindowTest(IdleCase):
    """With the day's fetches used up the window is `themes_window_full_s` (never past the run's deadline or the end of the day); in every other run it is `themes_window_s`."""

    def queue(self, used, limit=5):
        """A queue connection on the context, with `used` of the day's `limit` fetches counted for the day of the fake clock."""
        self.crawl_plan["fetches_per_day"] = limit
        conn = crawlqueue.connect(self.index_root())
        self.addCleanup(conn.close)
        conn.execute("INSERT INTO counters(day, key, n) VALUES (?, 'fetch', ?) ON CONFLICT(day, key) DO UPDATE SET n = excluded.n", (crawlplan.day_of(self.now, "UTC"), used))
        ctx = self.ctx()
        ctx.conn = conn
        return ctx

    def themes_of(self, books):
        return [b for b in books if self.themed(b)]

    def test_with_the_fetches_used_up_a_window_longer_than_the_short_one_finishes_the_books_the_short_one_would_cut(self):
        self.books(3)
        books = sorted(self.store.list_books())
        self.crawl_plan["themes_window_s"] = 400
        self.idle(GOOD * 3, per_call=100, ctx=self.queue(used=5))
        self.assertEqual(len(self.fake.calls), 6)                                       # all three books: 600 seconds of calls, in a window of 3600 seconds
        self.assertEqual(self.themes_of(books), books)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("ok", "nothing to do", 3))

    def test_with_the_fetches_not_used_up_the_window_is_the_short_one_and_the_lines_are_those_of_before(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 400
        self.idle(GOOD + GOOD, per_call=100, ctx=self.queue(used=4))                    # one fetch short of the limit
        self.assertEqual(len(self.fake.calls), 3)                                        # as the test of the deadline: the share of 240 seconds is spent after three calls
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["n"]), ("ok", "deadline", 1))

    def test_the_limit_itself_is_used_up_and_one_short_of_it_is_not(self):
        for used, calls in ((4, 3), (5, 4), (6, 4)):
            with self.subTest(used=used):
                self.books(2)
                self.crawl_plan["themes_window_s"] = 400
                self.idle(GOOD + GOOD, per_call=100, ctx=self.queue(used=used))
                self.assertEqual(len(self.fake.calls), calls)
                for b in self.store.list_books():
                    self.store.set_state(b, "weeded")                                     # the next case starts with books of its own
                for name in os.listdir(os.path.join(self.index_root(), "crawl", "log")):
                    os.unlink(os.path.join(self.index_root(), "crawl", "log", name))
                self.now = NOW

    def test_the_long_window_is_cut_by_the_deadline_of_the_run(self):
        self.books(2)
        ctx = self.queue(used=5)
        ctx.deadline = NOW + datetime.timedelta(seconds=250)
        self.idle(GOOD + GOOD, per_call=100, ctx=ctx)
        self.assertEqual(len(self.fake.calls), 2)                                        # as in the short window: 60 percent of the 250 seconds the run has left
        self.assertEqual(self.ended()["reason"], "deadline")

    def test_the_long_window_starts_no_call_after_the_end_of_the_day_and_lets_a_call_that_began_before_it_finish(self):
        self.now = datetime.datetime(2026, 11, 18, 23, 50, 0, tzinfo=datetime.timezone.utc)      # ten minutes to the end of the day
        self.books(4)
        self.crawl_plan["themes_window_s"] = 100
        self.idle(GOOD * 4, per_call=350, ctx=self.queue(used=5))
        self.assertEqual(len(self.fake.calls), 2)                                        # calls at 0 and 350 seconds; the second ends at 700, after the day's end at 600; nothing more begins
        self.assertEqual(self.embedded, [])                                              # nor the embedding of the vectors, nor a repair of the weave
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"], end["seconds"]), ("ok", "deadline", 700))

    def test_the_themes_keep_60_percent_of_the_long_window(self):
        self.books(5)
        self.crawl_plan["themes_window_full_s"] = 1000
        self.idle(GOOD * 5, per_call=100, ctx=self.queue(used=5))
        self.assertEqual(len(self.fake.calls), 6)                                        # calls at 0 to 500; at 600 seconds the share of the themes (60 percent of 1000) is spent
        self.assertEqual(self.ended()["reason"], "deadline")

    def test_a_window_of_zero_is_off_whatever_the_long_one_says_and_a_long_one_of_zero_is_the_short_window(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 0
        self.crawl_plan["themes_window_full_s"] = 1800
        self.idle(GOOD + GOOD, ctx=self.queue(used=5))
        self.assertEqual(self.fake.calls, [])
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "off"))
        for name in os.listdir(os.path.join(self.index_root(), "crawl", "log")):
            os.unlink(os.path.join(self.index_root(), "crawl", "log", name))
        self.crawl_plan["themes_window_s"] = 400
        self.crawl_plan["themes_window_full_s"] = 0
        self.idle(GOOD + GOOD, per_call=100, ctx=self.queue(used=5))
        self.assertEqual(len(self.fake.calls), 3)                                        # the short window, though the fetches are used up

    def test_a_context_with_no_queue_a_counter_that_cannot_be_read_and_a_closed_connection_give_the_short_window(self):
        for how in ("no connection", "a plan error", "a locked database", "a closed connection"):
            with self.subTest(how):
                self.books(2)
                self.crawl_plan["themes_window_s"] = 400
                ctx = self.queue(used=5)
                patcher = None
                if how == "no connection":
                    del ctx.conn
                elif how == "a plan error":
                    patcher = mock.patch.object(crawlstate, "ceilings", side_effect=KbError("the plan is not right"))
                elif how == "a locked database":
                    patcher = mock.patch.object(crawlstate, "ceilings", side_effect=sqlite3.OperationalError("database is locked"))
                else:
                    ctx.conn.close()
                if patcher:
                    patcher.start()
                    self.addCleanup(patcher.stop)
                self.idle(GOOD + GOOD, per_call=100, ctx=ctx)
                self.assertEqual(len(self.fake.calls), 3, how)
                if patcher:
                    patcher.stop()
                for b in self.store.list_books():
                    self.store.set_state(b, "weeded")
                for name in os.listdir(os.path.join(self.index_root(), "crawl", "log")):
                    os.unlink(os.path.join(self.index_root(), "crawl", "log", name))
                self.now = NOW

    def test_a_day_with_no_counter_at_all_gives_the_short_window(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 400
        ctx = self.ctx()
        ctx.conn = crawlqueue.connect(self.index_root())                                 # a queue with no row for the day: nothing was fetched
        self.addCleanup(ctx.conn.close)
        self.idle(GOOD + GOOD, per_call=100, ctx=ctx)
        self.assertEqual(len(self.fake.calls), 3)

    def test_a_long_window_shorter_than_the_short_one_is_the_window_of_a_used_up_day(self):
        self.books(3)
        self.crawl_plan["themes_window_s"] = 3000
        self.crawl_plan["themes_window_full_s"] = 400                                    # the earliest of the three ends: the themes get 240 seconds of it
        self.idle(GOOD * 3, per_call=100, ctx=self.queue(used=5))
        self.assertEqual(len(self.fake.calls), 3)
        self.assertEqual(self.ended()["reason"], "deadline")

    def test_an_error_of_another_kind_in_the_read_of_the_counter_propagates_and_the_window_still_writes_its_line(self):
        self.books(1)
        ctx = self.queue(used=5)
        with mock.patch.object(crawlstate, "ceilings", side_effect=RuntimeError("a fault of the code")):
            with self.assertRaises(RuntimeError):
                self.idle(GOOD, ctx=ctx)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("failed", "failed"))
        self.assertEqual(self.fake.calls, [])

    def test_a_stop_file_made_in_the_middle_of_a_long_window_prevents_the_next_call(self):
        self.books(3)
        self.idle(GOOD * 3, per_call=100, ctx=self.queue(used=5), on_call=lambda n: self.stop_file() if n == 2 else None)
        self.assertEqual(len(self.fake.calls), 2)
        end = self.ended()
        self.assertEqual((end["outcome"], end["reason"]), ("skipped", "stopped"))

    def test_the_same_code_runs_in_the_long_window_the_lines_of_the_themes_the_vectors_and_the_weave(self):
        self.books(2)
        self.idle(GOOD + GOOD, per_call=100, ctx=self.queue(used=5))
        self.assertEqual([x["outcome"] for x in self.lines("themes")], ["ok", "ok"])
        self.assertTrue(self.embedded)                                                   # the vectors of the books were embedded in the same window


class DeadlineTest(IdleCase):
    def test_the_window_ends_at_its_deadline_before_the_next_call_and_the_next_window_finishes_the_cut_book_from_its_pieces(self):
        self.books(2)
        first, second = sorted(self.store.list_books())
        self.crawl_plan["themes_window_s"] = 400                           # the themes get 60 percent of it: 240 seconds
        self.idle(GOOD + GOOD, per_call=100)                              # book 1: 0 to 200 seconds; book 2: its piece at 200 to 300, then the share is spent
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
        self.idle(GOOD + GOOD, per_call=100, ctx=self.ctx(deadline=NOW + datetime.timedelta(seconds=250)))
        self.assertEqual(len(self.fake.calls), 2)                         # the themes get 150 seconds of the 250 the run has left: calls at 0 and 100, and at 200 their share is spent
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


class VectorsTest(IdleCase):
    """After the themes, the vectors of what was made, in a batch that fits the time left."""

    def vector_lines(self):
        return [(x["outcome"], x["reason"], x["n"]) for x in self.lines("theme_vectors")]

    def waiting(self):
        return themevectors.waiting_texts(self.store, self.crawl_cfg())

    def test_the_vectors_of_the_books_made_are_built_after_the_themes_and_nothing_is_left_waiting(self):
        self.books(2)
        self.idle(self.distinct(2))
        self.assertEqual(self.vector_lines(), [("ok", None, 12)])          # two books of one theme each, six texts each
        self.assertEqual(self.embedded, [12])
        self.assertEqual(self.waiting(), 0)
        self.assertTrue(os.path.exists(themevectors.path_of(self.index_root())))
        self.assertEqual(self.ended()["reason"], "nothing to do")

    def test_the_themes_get_sixty_percent_of_the_window_while_more_books_wait_and_the_vectors_get_the_rest(self):
        self.books(6)
        self.crawl_plan["themes_window_s"] = 300
        self.idle(self.distinct(6), per_call=30)                          # a book takes 60 seconds: the third ends at 180, the share of the themes
        self.assertEqual(len(self.lines("themes")), 3)
        self.assertEqual(self.vector_lines(), [("ok", None, 18)])         # the vectors of the three, after the themes
        end = self.ended()
        self.assertEqual((end["reason"], end["n"], end["seconds"]), ("deadline", 3, 185))     # 180 seconds of themes and one call of 5 seconds
        self.assertEqual(len(self.run_records()[0]["items"]), 6)          # all six were planned; the share ended the run

    def test_the_themes_use_the_whole_window_when_there_is_nothing_for_the_rest_to_do_with_the_books_that_are_left_to_make(self):
        self.books(2)
        self.crawl_plan["themes_window_s"] = 300
        self.idle(GOOD + GOOD, per_call=30)                               # both books end at 120: before the share
        self.assertEqual(len(self.lines("themes")), 2)

    def test_a_batch_that_the_time_left_limits_takes_whole_themes_and_the_next_window_goes_on(self):
        self.books(3)
        self.crawl_plan["themes_window_s"] = 300
        with mock.patch.multiple(crawlidle, SECONDS_A_TEXT=10.0, SECONDS_A_CALL=0.0, BUILD_OVERHEAD_S=0.0, MARGIN=1.0, MIN_BATCH=1, WEAVE_RESERVE_S=0.0):
            self.idle(self.distinct(3), per_call=30)                            # the themes end at 180; 120 seconds are left, so 12 texts
            self.assertEqual(self.vector_lines(), [("ok", None, 12)])
            self.assertEqual(self.embedded, [12])
            self.assertEqual(self.waiting(), 6)                           # a third theme, whole, waits
            self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
            self.now += HOUR
            self.idle([], per_call=30)                                    # no book is left to make; the six texts that waited fit
        self.assertEqual(self.waiting(), 0)

    def test_a_batch_that_the_time_limits_to_fewer_than_the_least_while_more_wait_is_not_begun(self):
        self.books(3)
        self.crawl_plan["themes_window_s"] = 200
        with mock.patch.multiple(crawlidle, SECONDS_A_TEXT=10.0, SECONDS_A_CALL=0.0, BUILD_OVERHEAD_S=0.0, MARGIN=1.0, MIN_BATCH=20, WEAVE_RESERVE_S=0.0):
            self.idle(self.distinct(3), per_call=30)                      # the themes end at 120 with two books made: 80 seconds are left, 8 texts of the 12 that wait
        self.assertEqual(self.embedded, [])
        self.assertEqual(self.vector_lines(), [("skipped", "waits for a longer window", None)])
        self.assertEqual(self.waiting(), 12)

    def test_a_final_backlog_of_fewer_than_the_least_is_embedded_whole_in_a_long_window(self):
        self.books(1)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, SECONDS_A_TEXT=4.0, SECONDS_A_CALL=0.0, BUILD_OVERHEAD_S=0.0, MARGIN=1.0, MIN_BATCH=20, WEAVE_RESERVE_S=0.0):
            self.idle(GOOD, per_call=30)                                  # the theme ends at 60; 40 seconds are left: 10 texts, and 6 wait
        self.assertEqual(self.embedded, [6])
        self.assertEqual(self.waiting(), 0)

    def test_a_backlog_that_would_need_more_than_the_time_left_but_is_below_the_least_waits_for_a_longer_window(self):
        self.books(1)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, SECONDS_A_TEXT=10.0, SECONDS_A_CALL=0.0, BUILD_OVERHEAD_S=0.0, MARGIN=1.0, MIN_BATCH=20, WEAVE_RESERVE_S=0.0):
            self.idle(GOOD, per_call=30)                                  # 40 seconds are left: 4 texts of the 6 that wait
        self.assertEqual(self.embedded, [])
        self.assertEqual(self.waiting(), 6)

    def test_the_fit_is_the_measured_cost_with_the_margin_and_never_below_zero(self):
        # 100 seconds: a quarter kept back, 5 seconds for the build, then 0.35 a text and 5 seconds a call of 40 texts
        self.assertEqual(crawlidle._fit(100), int((100 * 0.75 - 5) // (0.35 + 5 / 40)))
        self.assertEqual(crawlidle._fit(100), 147)
        self.assertEqual(crawlidle._fit(0), 0)
        self.assertEqual(crawlidle._fit(-50), 0)
        self.assertEqual(crawlidle._fit(6), 0)                            # under the fixed part of the build

    def test_the_calls_hold_at_most_the_group_of_the_step_and_the_group_is_forty_texts(self):
        self.assertEqual(crawlidle.EMBED_GROUP, 40)
        self.books(3)
        with mock.patch.object(crawlidle, "EMBED_GROUP", 7):
            self.idle(self.distinct(3))
        self.assertEqual(self.embedded, [7, 7, 4])

    def test_a_stop_file_made_between_two_calls_ends_the_build_before_the_next_and_writes_no_file(self):
        self.books(3)
        with mock.patch.object(crawlidle, "EMBED_GROUP", 6):
            self.idle(self.distinct(3), embed_on_call=lambda n: self.stop_file() if n == 1 else None)
        self.assertEqual(self.embedded, [6])
        self.assertFalse(os.path.exists(themevectors.path_of(self.index_root())))
        self.assertEqual(self.vector_lines(), [("skipped", "stopped", None)])
        self.assertEqual(self.ended()["reason"], "stopped")

    def test_a_build_that_fails_is_a_failed_step_and_the_embedding_entry_is_asked_once(self):
        self.books(1)
        self.idle(GOOD, embed_fail=True)
        self.assertEqual(self.vector_lines(), [("failed", "the vectors could not be made", None)])
        self.assertEqual(self.probes, ["card-embed"])
        self.assertEqual(self.ended()["reason"], "failed")

    def test_an_embedding_entry_that_does_not_answer_runs_its_clock_and_trips_the_breaker_in_the_end(self):
        self.books(1)
        self.up_for = {"card-embed": False}
        self.idle(GOOD, embed_fail=True)
        self.assertEqual(self.tripped, [])
        self.now += datetime.timedelta(minutes=31)
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        with self.assertRaises(crawlrun.BreakerTripped):
            self.idle([], embed_fail=True)
        self.assertEqual([k for k, _ in self.tripped], ["model_down"])

    def test_a_vector_file_that_another_writer_holds_is_a_skipped_step_with_no_embedding_and_no_probe(self):
        self.books(1)
        with mock.patch.object(catalog, "LOCK_WAIT", 0.1), themevectors.lock(self.index_root()):
            self.idle(GOOD)
        self.assertEqual(self.embedded, [])                               # the lock is looked at before the work, so that the work is not lost
        self.assertEqual(self.vector_lines(), [("skipped", "locked", None)])
        self.assertEqual(self.probes, [])
        self.assertEqual(self.waiting(), 6)                               # the themes were made and their vectors wait
        self.assertEqual(self.ended()["reason"], "nothing to do")         # the window goes on to the weave

    def test_the_step_looks_at_the_lock_without_waiting_and_lets_the_write_wait_a_few_seconds_at_most(self):
        self.assertEqual((crawlidle.LOCK_LOOK_S, crawlidle.LOCK_WRITE_S), (0.0, 5.0))        # not the two minutes of the catalog, which no stop is looked at in
        self.books(1)
        with mock.patch.object(themevectors, "lock", wraps=themevectors.lock) as locked:
            self.idle(GOOD)
        self.assertEqual([c.kwargs.get("wait") for c in locked.call_args_list], [crawlidle.LOCK_LOOK_S, crawlidle.LOCK_WRITE_S])

    def test_a_lock_that_is_taken_between_the_look_and_the_write_is_a_skipped_step_too_and_not_a_failed_one(self):
        self.books(1)
        with mock.patch.object(themevectors, "build", side_effect=themevectors.Busy("another writer")):
            self.idle(GOOD)
        self.assertEqual(self.vector_lines(), [("skipped", "locked", None)])
        self.assertEqual(self.probes, [])

    def test_the_refusal_of_the_lock_is_a_kb_error_as_it_was(self):
        self.assertTrue(issubclass(themevectors.Busy, KbError))

    def test_with_no_embedding_entry_set_the_step_is_skipped_for_want_of_settings_and_the_themes_are_made_all_the_same(self):
        self.books(1)
        self.idle(GOOD, ctx=self.ctx(cfg=self.crawl_cfg(embedding_entry=False)))
        self.assertEqual(len(self.lines("themes")), 1)
        self.assertEqual(self.vector_lines(), [("skipped", "settings", None)])
        self.assertEqual(self.embedded, [])

    def test_with_no_book_to_make_and_nothing_waiting_the_step_says_so_and_asks_no_model(self):
        self.idle()
        self.assertEqual(self.vector_lines(), [("skipped", "nothing waits", None)])
        self.assertEqual(self.embedded, [])


class WeaveTest(IdleCase):
    """The repair of the weave, when it is due, with at least the least time left; never a full build."""

    def weave_with(self, status=None, repair=None, np=None):
        calls = {"status": 0, "repair": []}

        def status_of(index_root, cfg, store, now=None):
            calls["status"] += 1
            if isinstance(status, Exception):
                raise status
            return status

        def repair_of(index_root, cfg, store, now=None, force=False):
            calls["repair"].append(force)
            if isinstance(repair, Exception):
                raise repair
            return repair
        return types.SimpleNamespace(_np=np or (lambda: None), status=status_of, repair=repair_of), calls

    def weave_lines(self):
        return [(x["outcome"], x["reason"], x["n"]) for x in self.lines("weave")]

    def state(self, due=True, full=False, waiting=5):
        return {"repair_due": due, "full_build_needed": full, "waiting": {"total": waiting, "new": waiting, "changed": 0}}

    def test_a_repair_that_is_due_is_made_once_and_not_forced(self):
        self.books(1)
        weave, calls = self.weave_with(self.state(), {"themes_added": 7, "generation": 3})
        self.idle(GOOD, weave=weave)
        self.assertEqual(calls["repair"], [False])
        self.assertEqual(self.weave_lines(), [("ok", None, 7)])

    def test_a_repair_that_is_not_due_is_not_made_and_the_line_says_so(self):
        weave, calls = self.weave_with(self.state(due=False))
        self.idle(weave=weave)
        self.assertEqual((calls["status"], calls["repair"]), (1, []))
        self.assertEqual(self.weave_lines(), [("skipped", "not due", 5)])

    def test_a_full_build_that_is_needed_is_the_owners_and_is_never_made_here(self):
        weave, calls = self.weave_with(self.state(full=True))
        self.idle(weave=weave)
        self.assertEqual(calls["repair"], [])
        self.assertEqual(self.weave_lines(), [("skipped", "a full build is needed", None)])

    def test_a_library_with_no_weave_skips_it_and_numpy_missing_skips_it_before_the_file_is_read(self):
        weave, calls = self.weave_with(KbError("there is no weave"))
        self.idle(weave=weave)
        self.assertEqual(self.weave_lines(), [("skipped", "no weave", None)])

        def no_numpy():
            raise KbError("needs numpy")
        weave, calls = self.weave_with(self.state(), np=no_numpy)
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        self.idle(weave=weave)
        self.assertEqual((calls["status"], calls["repair"]), (0, []))
        self.assertEqual(self.weave_lines()[-1], ("skipped", "numpy is not installed", None))

    def test_numpy_missing_leaves_the_themes_and_their_vectors_made(self):
        self.books(1)

        def no_numpy():
            raise KbError("needs numpy")
        weave, _ = self.weave_with(self.state(), np=no_numpy)
        self.idle(GOOD, weave=weave)
        self.assertEqual(len(self.lines("themes")), 1)
        self.assertEqual(self.embedded, [6])

    def test_a_repair_that_is_refused_is_a_failed_step_with_a_fixed_reason_and_not_the_text_of_the_refusal(self):
        weave, calls = self.weave_with(self.state(), KbError("a secret path /x/y"))
        self.idle(weave=weave)
        self.assertEqual(self.weave_lines(), [("failed", "the repair was refused", None)])
        self.assertNotIn("secret", json.dumps(self.lines("weave")))

    def test_with_less_than_the_least_time_left_the_weave_is_not_looked_at(self):
        self.books(1)
        self.crawl_plan["themes_window_s"] = 70
        weave, calls = self.weave_with(self.state())
        self.idle(GOOD, weave=weave, embed_per_call=5)                    # themes to 60, the vectors to 65: five seconds are left
        self.assertEqual((calls["status"], calls["repair"]), (0, []))
        self.assertEqual(self.weave_lines(), [("skipped", "too little time", None)])

    def test_the_repair_is_not_made_after_a_stop_file(self):
        self.books(1)
        weave, calls = self.weave_with(self.state())
        self.idle(GOOD, weave=weave, on_call=lambda n: self.stop_file() if n == 2 else None)
        self.assertEqual(calls["repair"], [])
        self.assertEqual(self.ended()["reason"], "stopped")


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


class CardVectorsTest(IdleCase):
    """After the themes and before the vectors of the themes, the vectors of the cards that have none, in a batch that fits the time left (plan `2026-11-20-refresh-the-card-vectors-in-the-idle-window-and-tell-the-skills-what-the-search-covers`,
    Increment B). A book of the fixture has a card of three embedded fields, so three texts."""

    FIT = dict(SECONDS_A_TEXT=10.0, SECONDS_A_CALL=0.0, BUILD_OVERHEAD_S=0.0, MARGIN=1.0, MIN_BATCH=1, WEAVE_RESERVE_S=0.0)

    def card_lines(self):
        return [(x["outcome"], x["reason"], x["n"]) for x in self.lines("card_vectors")]

    def waiting(self):
        return vectors.waiting_texts(self.store, self.crawl_cfg())

    def no_themes(self):
        """The themes of the books are not this part's business: nothing is eligible for them."""
        return mock.patch.object(crawlidle, "_eligible", return_value=[])

    def next_window(self):
        self.log = crawllog.Log(self.index_root(), "run-2", clock=lambda: self.now)
        self.now += HOUR

    def test_the_vectors_of_the_cards_are_built_after_the_themes_and_before_the_vectors_of_the_themes(self):
        self.books(2)
        self.idle(self.distinct(2), cards=True)
        self.assertEqual(self.card_lines(), [("ok", None, 6)])            # two cards of three texts
        self.assertEqual(self.embedded, [6, 12])                          # the cards, then the six texts of each of the two themes
        self.assertEqual([x["step"] for x in self.lines("themes", "card_vectors", "theme_vectors")], ["themes", "themes", "card_vectors", "theme_vectors"])
        self.assertEqual((self.waiting(), themevectors.waiting_texts(self.store, self.crawl_cfg())), (0, 0))
        self.assertTrue(os.path.exists(vectors.path_of(self.index_root())))
        self.assertEqual(self.ended()["reason"], "nothing to do")

    def test_a_library_whose_card_vectors_are_current_costs_a_count_and_no_model_call(self):
        self.books(1)
        self.idle(GOOD, cards=True)
        self.next_window()
        self.idle([], cards=True)
        self.assertEqual(self.card_lines()[-1], ("skipped", "nothing waits", None))
        self.assertEqual(self.embedded, [])                               # the second window sent nothing (the fake notes only the calls of its own window)

    def test_a_batch_that_the_time_limits_takes_whole_cards_and_the_next_window_goes_on(self):
        self.books(3)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, **self.FIT), self.no_themes():
            self.idle([], cards=True)                                     # 100 seconds, half of them for the cards: 5 texts fit, one card of three
            self.assertEqual(self.card_lines(), [("ok", None, 3)])
            self.assertEqual(self.ended()["reason"], "deadline")          # a batch that the time held back says so: the window ran out of time, not of work
            self.assertEqual(self.waiting(), 6)
            self.next_window()
            self.idle([], cards=True)
            self.next_window()
            self.idle([], cards=True)
        self.assertEqual(self.card_lines(), [("ok", None, 3)] * 3)
        self.assertEqual(self.waiting(), 0)

    def test_the_cards_take_no_more_than_half_of_what_is_left_so_that_the_vectors_of_the_themes_have_the_rest(self):
        self.assertEqual(crawlidle.CARD_VECTORS_SHARE, 0.5)
        self.books(3)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, **self.FIT), self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.embedded, [3])                              # a share of 1.0 would have fitted nine texts, three cards

    def test_a_batch_that_the_time_limits_to_fewer_than_the_least_while_more_wait_is_not_begun(self):
        self.books(3)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, **{**self.FIT, "MIN_BATCH": 20}), self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.card_lines(), [("skipped", "waits for a longer window", None)])
        self.assertEqual((self.embedded, self.waiting()), ([], 9))
        self.assertEqual(self.ended()["reason"], "deadline")              # the window says that time limited it

    def test_a_final_backlog_of_fewer_than_the_least_is_embedded_whole(self):
        self.books(1)
        self.crawl_plan["themes_window_s"] = 100
        with mock.patch.multiple(crawlidle, **{**self.FIT, "MIN_BATCH": 20, "SECONDS_A_TEXT": 4.0}), self.no_themes():
            self.idle([], cards=True)                                     # 50 seconds for the cards at 4 a text: 12 texts, and 3 wait
        self.assertEqual(self.embedded, [3])
        self.assertEqual(self.waiting(), 0)

    def test_a_stop_file_made_between_two_calls_ends_the_build_before_the_next_and_writes_no_file(self):
        self.books(3)
        with mock.patch.object(crawlidle, "EMBED_GROUP", 3), self.no_themes():
            self.idle([], cards=True, embed_on_call=lambda n: self.stop_file() if n == 1 else None)
        self.assertEqual(self.embedded, [3])
        self.assertFalse(os.path.exists(vectors.path_of(self.index_root())))
        self.assertEqual(self.card_lines(), [("skipped", "stopped", None)])
        self.assertEqual(self.ended()["reason"], "stopped")

    def test_a_build_that_fails_is_a_failed_step_and_the_embedding_entry_is_asked_once(self):
        self.books(1)
        with self.no_themes():
            self.idle([], cards=True, embed_fail=True)
        self.assertEqual(self.card_lines(), [("failed", "the vectors could not be made", None)])
        self.assertEqual(self.probes, ["card-embed"])
        self.assertEqual(self.ended()["reason"], "nothing to do")         # the failure is the part's own: the window goes on to the parts after it

    def test_a_catalog_lock_that_cannot_be_opened_is_a_failed_step_and_the_window_goes_on(self):
        self.books(1)
        with mock.patch.object(vectors, "write_lock", side_effect=KbError("the catalog lock cannot be opened (Permission denied)")), self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.card_lines(), [("failed", "the lock of the catalog could not be opened", None)])
        self.assertEqual((self.embedded, self.ended()["reason"]), ([], "nothing to do"))

    def test_a_disk_or_file_error_in_the_count_or_the_build_is_a_failed_step_too_and_the_window_goes_on(self):
        """From the security review: an `OSError` (a full disk, a permission) must not end the run with a traceback and skip the parts after this one."""
        self.books(1)
        for target in ("waiting_texts", "build"):
            with self.subTest(target=target), mock.patch.object(vectors, target, side_effect=OSError(28, "No space left on device")), self.no_themes():
                self.log = crawllog.Log(self.index_root(), "run-" + target, clock=lambda: self.now)
                before = len(self.card_lines())
                self.idle([], cards=True)
                self.assertEqual(len(self.card_lines()), before + 1)
                self.assertEqual(self.card_lines()[-1][0], "failed")

    def test_a_failure_of_the_cards_does_not_stop_the_vectors_of_the_themes_or_the_weave(self):
        self.books(1)
        with mock.patch.object(vectors, "build", side_effect=KbError("the model is not the one that made the vectors that are kept")):
            self.idle(GOOD, cards=True)
        self.assertEqual(self.card_lines(), [("failed", "the vectors could not be made", None)])
        self.assertEqual([(x["outcome"], x["n"]) for x in self.lines("theme_vectors")], [("ok", 6)])      # the themes of the book made in this window are embedded all the same
        self.assertEqual(self.embedded, [6])
        self.assertEqual(self.ended()["reason"], "nothing to do")
        self.assertEqual(self.probes, ["card-embed"])

    def test_a_catalog_lock_that_another_writer_holds_is_a_skipped_step_with_no_embedding_and_no_probe(self):
        self.books(1)
        fd = os.open(os.path.join(self.index_root(), catalog.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)
        with self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.embedded, [])                               # the lock is looked at before the work, so that the work is not lost
        self.assertEqual(self.card_lines(), [("skipped", "locked", None)])
        self.assertEqual(self.probes, [])
        self.assertEqual(self.waiting(), 3)

    def test_the_step_looks_at_the_lock_without_waiting_and_lets_the_write_wait_a_few_seconds_at_most(self):
        self.books(1)
        with mock.patch.object(vectors, "write_lock", wraps=vectors.write_lock) as locked, self.no_themes():
            self.idle([], cards=True)
        self.assertEqual([c.args[1] for c in locked.call_args_list], [crawlidle.LOCK_LOOK_S, crawlidle.LOCK_WRITE_S])

    def test_a_lock_that_is_taken_between_the_look_and_the_write_is_a_skipped_step_too_and_not_a_failed_one(self):
        self.books(1)
        with mock.patch.object(vectors, "build", side_effect=vectors.Busy("another writer")), self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.card_lines(), [("skipped", "locked", None)])
        self.assertEqual(self.probes, [])

    def test_with_no_embedding_entry_set_the_step_is_skipped_for_want_of_settings_and_the_themes_are_made_all_the_same(self):
        self.books(1)
        self.idle(GOOD, ctx=self.ctx(cfg=self.crawl_cfg(embedding_entry=False)), cards=True)
        self.assertEqual(len(self.lines("themes")), 1)
        self.assertEqual(self.card_lines(), [("skipped", "settings", None)])
        self.assertEqual(self.embedded, [])

    def test_a_card_count_that_cannot_be_made_is_a_failed_step_and_the_window_goes_on(self):
        self.books(1)
        with mock.patch.object(vectors, "waiting_texts", side_effect=KbError("cannot read")), self.no_themes():
            self.idle([], cards=True)
        self.assertEqual(self.card_lines(), [("failed", "the texts that wait could not be counted", None)])
        self.assertEqual(self.ended()["reason"], "nothing to do")

    def test_a_deadline_that_has_come_before_the_part_begins_ends_the_window_without_a_line_for_it(self):
        self.books(1)
        self.crawl_plan["themes_window_s"] = 60
        with self.no_themes():
            self.idle([], cards=True, ctx=self.ctx(deadline=self.now))    # the run's own time is spent
        self.assertEqual(self.lines("card_vectors"), [])
        self.assertEqual(self.embedded, [])

    def test_every_line_holds_a_fixed_sentence_or_a_number(self):
        self.books(1)
        with self.no_themes():
            self.idle([], cards=True)
        text = json.dumps(self.lines("card_vectors"))
        for word in ("annealing", "cools a system", "A paper", "stopping"):
            self.assertNotIn(word, text)


class RegistryTest(unittest.TestCase):
    def test_the_real_registry_attaches_the_step_at_the_idle_point(self):
        real = crawlrun.default_steps()
        self.assertIs(real["idle"], crawlidle.step)
        self.assertEqual(crawlrun.POINTS[-1], "idle")


if __name__ == "__main__":
    unittest.main()
