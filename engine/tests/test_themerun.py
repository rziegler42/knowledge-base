import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
import unittest.mock
from collections import Counter

from engine.tests import ENGINE_DIR
from engine.tests.test_themecheck import config
from engine.tests.test_themeextract import Fake, VersionCase, row, values

from kb import KbError, card, cardstate, models, theme, themecheck, themeextract, themerun
from kb import __main__ as kbmain
from kb import config as kbconfig

RUN_OLD, RUN_NEW = "20261110t100000z-aaaaaa", "20261111t100000z-bbbbbb"


def extraction(**over):
    return {"model": "m1:latest", "prompt_version": themeextract.THEME_JOB.prompt_version, **over}


def check(**over):
    return {"model": "m2:latest", "prompt_version": themecheck.check_job(1).prompt_version, **over}


def item(book, version, status="done", generation=1, made="both", **over):
    made = {"theme": extraction(), "theme-check": check()} if made == "both" else made
    base = {"book_id": book, "version_id": version, "pieces": 1, "status": status, "attempts": 0, "generation": generation, "reason": "",
            "made": made, "conversion": None, "stats": None}
    base.update(over)
    return base


def record(run, items, **over):
    base = {"format": 1, "kind": "themes", "run": run, "created": "2026-11-11T10:00:00Z", "again": False, "extraction": extraction(),
            "check": check(), "items": items}
    base.update(over)
    return base


class PlanCase(VersionCase):
    def plan(self, cfg=None, **kw):
        return themerun.plan(self.store, cfg or config(), **kw)

    def index_root(self):
        return self.store.cfg["index_root"]

    def file_generation(self, book, version, model="m1:latest", prompt=None, themes=True):
        """File a generation of themes for a version, made as the extraction makes them, but saying it was made with the model and the prompt given."""
        fake = Fake(values(row()) if themes else values())
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themeextract.make_for_version(self.store, config(), book, version)
        for t in got["themes"]:
            t["made"] = {"model": model, "prompt_version": prompt or themeextract.THEME_JOB.prompt_version, "date": t["made"]["date"]}
        return theme.file(self.store, theme.make(book, version, got["themes"]))

    def skipped(self, got, reason):
        return [b["book_id"] for b in got["skipped_books"] if b["reason"] == reason]

    def written(self):
        folder = os.path.join(self.index_root(), cardstate.FOLDER)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


class BooksToMakeTest(PlanCase):
    def test_a_converted_book_with_a_card_is_to_make_and_its_pieces_are_counted(self):
        book, version = self.converted_book()
        got = self.plan()
        self.assertEqual(got["books"], 1)
        self.assertEqual([(b["book_id"], b["pieces"]) for b in got["to_make"]], [(book, len(themeextract.pieces(themeextract.prepare(self.store, book)[3])))])
        self.assertEqual(got["pieces"], got["to_make"][0]["pieces"])
        self.assertEqual(got["calls_known"], {"theme": got["pieces"]})
        self.assertEqual(got["skipped"], {reason: 0 for reason in themerun.REASONS})
        self.assertEqual(got["models"], {"theme": "themer", "theme-check": "checker"})
        self.assertEqual(got["prompt_versions"], {"theme": themeextract.THEME_JOB.prompt_version, "theme-check": themecheck.check_job(1).prompt_version})

    def test_the_estimate_is_the_pieces_times_the_rates_of_the_trials_and_says_so(self):
        for _ in range(3):
            self.converted_book()
        got = self.plan()
        pieces = got["pieces"]
        self.assertGreaterEqual(pieces, 3)
        low, high = themerun.SECONDS_PER_PIECE
        self.assertEqual((got["estimate"]["seconds_low"], got["estimate"]["seconds_high"]), (pieces * low, pieces * high))
        self.assertEqual((got["estimate"]["check_calls_low"], got["estimate"]["check_calls_high"]),
                         (round(pieces * themerun.CHECKS_PER_PIECE[0]), round(pieces * themerun.CHECKS_PER_PIECE[1])))
        self.assertIn("trials", got["estimate"]["basis"])
        self.assertIn("estimate", got["estimate"]["basis"])

    def test_a_plan_of_no_books_is_an_empty_plan_and_says_so(self):
        got = self.plan()
        self.assertEqual((got["books"], got["pieces"], got["to_make"], got["estimate"]["seconds_low"]), (0, 0, [], 0))

    def test_the_books_are_in_the_order_of_the_library_and_a_book_named_twice_is_planned_once(self):
        a = self.converted_book()[0]
        b = self.converted_book()[0]
        self.assertEqual([x["book_id"] for x in self.plan()["to_make"]], self.store.list_books())
        got = self.plan(book_ids=[b, a, b])
        self.assertEqual([x["book_id"] for x in got["to_make"]], [b, a])

    def test_the_plan_can_be_limited_to_the_books_named_and_a_book_that_is_not_there_is_refused_with_nothing_written(self):
        a = self.converted_book()[0]
        self.converted_book()
        self.assertEqual([x["book_id"] for x in self.plan(book_ids=[a])["to_make"]], [a])
        before = self.written()
        with self.assertRaises(KbError):
            self.plan(book_ids=[a, "01ARZ3NDEKTSV4RRFFQ69G5FAV"])
        self.assertEqual(self.written(), before)

    def test_the_titles_are_cleaned_and_cut_for_the_plan_that_is_shown(self):
        book, _ = self.converted_book()
        self.assertEqual(self.plan()["to_make"][0]["title"], "A paper on annealing")
        self.store.create_book(title="Long " + "word " * 40, kind="preprint")
        self.store.create_book(title="Tab\there", kind="preprint")
        titles = [b["title"] for b in self.plan()["skipped_books"]]
        self.assertTrue(all(len(t) <= 80 for t in titles), titles)
        self.assertTrue(any(len(t) >= 70 for t in titles), titles)                # cut, not dropped
        self.assertTrue(all("\t" not in t and "\n" not in t for t in titles), titles)

    def test_the_books_named_are_checked_before_any_book_is_looked_at(self):
        a = self.converted_book()[0]
        with unittest.mock.patch.object(themeextract, "pieces", wraps=themeextract.pieces) as counted, self.assertRaises(KbError):
            self.plan(book_ids=[a, "01ARZ3NDEKTSV4RRFFQ69G5FAV"])
        counted.assert_not_called()


class SkippedTest(PlanCase):
    def test_a_book_that_is_not_active_is_skipped(self):
        book, _ = self.converted_book()
        self.store.set_state(book, "weeded")
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "inactive"), got["skipped"]["inactive"]), (0, [book], 1))

    def test_a_book_with_no_card_that_can_be_read_is_skipped(self):
        book, _ = self.converted_book(with_card=False)
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "no_card"), got["skipped"]["no_card"]), (0, [book], 1))

    def test_a_book_with_a_card_and_no_conversion_is_skipped(self):
        book = self.store.create_book(title="A page", kind="preprint")
        version = self.store.add_version(book, label="v1")
        self.store.file_payload(book, version, "original", {"page.html": b"<html>x</html>"}, primary="page.html")
        card.file(self.store, card.make(self.store, book, version))
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "no_conversion")), (0, [book]))

    def test_a_book_with_no_version_is_skipped_as_having_no_conversion(self):
        book = self.store.create_book(title="Empty", kind="preprint")
        self.assertEqual(self.skipped(self.plan(), "no_conversion"), [book])

    def test_a_book_with_more_pieces_than_may_be_read_is_skipped_and_one_with_exactly_that_many_is_not(self):
        book, _ = self.converted_book()
        pieces = self.plan()["to_make"][0]["pieces"]
        with unittest.mock.patch.object(themeextract, "MAX_PIECES", pieces - 1):
            got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "too_long")), (0, [book]))
        with unittest.mock.patch.object(themeextract, "MAX_PIECES", pieces):
            self.assertEqual(self.plan()["books"], 1)
        self.assertEqual(self.plan()["books"], 1)

    def test_every_book_is_either_to_make_or_skipped_with_one_reason(self):
        ok = self.converted_book()[0]
        gone = self.converted_book()[0]
        self.store.set_state(gone, "removed")
        nocard = self.converted_book(with_card=False)[0]
        got = self.plan()
        listed = [b["book_id"] for b in got["to_make"]] + [b["book_id"] for b in got["skipped_books"]]
        self.assertEqual(sorted(listed), sorted(self.store.list_books()))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(sum(got["skipped"].values()), len(got["skipped_books"]))
        self.assertEqual([b["book_id"] for b in got["to_make"]], [ok])
        self.assertIn(nocard, self.skipped(got, "no_card"))


class AlreadyMadeTest(PlanCase):
    def test_a_book_whose_newest_themes_were_made_with_this_prompt_and_model_is_skipped(self):
        book, version = self.converted_book()
        self.file_generation(book, version)
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "already_made")), (0, [book]))

    def test_another_prompt_version_or_another_model_makes_the_book_again(self):
        book, version = self.converted_book()
        self.file_generation(book, version, prompt="v3")
        self.assertEqual(self.plan()["books"], 1)
        self.file_generation(book, version, model="other:latest")
        self.assertEqual(self.plan()["books"], 1)
        self.file_generation(book, version)
        self.assertEqual(self.plan()["books"], 0)

    def test_one_theme_made_with_another_prompt_among_themes_made_with_this_one_makes_the_book_again(self):
        book, version = self.converted_book()
        fake = Fake(values(row(), row(title="Stopping", blocks="5", summary="The search stops when it is cold.")))
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themeextract.make_for_version(self.store, config(), book, version)
        for t in got["themes"]:
            t["made"] = {"model": "m1:latest", "prompt_version": themeextract.THEME_JOB.prompt_version, "date": t["made"]["date"]}
        got["themes"][1]["made"]["prompt_version"] = "v3"
        theme.file(self.store, theme.make(book, version, got["themes"]))
        self.assertEqual(self.plan()["books"], 1)
        got["themes"][1]["made"]["prompt_version"] = themeextract.THEME_JOB.prompt_version
        got["themes"][0]["made"]["model"] = "other:latest"
        theme.file(self.store, theme.make(book, version, got["themes"]))
        self.assertEqual(self.plan()["books"], 1)

    def test_only_the_newest_valid_generation_counts_so_an_older_one_that_matches_does_not_stop_a_remake(self):
        book, version = self.converted_book()
        self.file_generation(book, version)
        self.file_generation(book, version, prompt="v3")
        self.assertEqual(theme.generations(self.store, book, version), [1, 2])
        self.assertEqual(self.plan()["books"], 1)

    def test_a_newest_generation_that_is_damaged_is_not_the_newest_valid_one(self):
        book, version = self.converted_book()
        self.file_generation(book, version, prompt="v3")
        number = self.file_generation(book, version)
        path = os.path.join(self.store.version_dir(book, version), "derived", theme.TOOL, str(number), theme.FILENAME)
        self.assertTrue(os.path.exists(path))
        os.chmod(path, 0o600)   # a filed generation is read-only; this breaks it on purpose
        with open(path, "w") as f:
            f.write("{}")
        self.assertEqual([n for n, _ in theme.damaged(self.store, book, version)], [number])
        self.assertEqual(self.plan()["books"], 1)   # the newest that passes its check is the one made with the older prompt

    def test_an_older_generation_that_matches_stands_when_the_newer_one_is_damaged_and_the_plan_shows_the_damage(self):
        book, version = self.converted_book()
        self.file_generation(book, version)
        number = self.file_generation(book, version, prompt="v3")
        path = os.path.join(self.store.version_dir(book, version), "derived", theme.TOOL, str(number), theme.FILENAME)
        self.assertEqual(self.plan()["damaged"], [])
        os.chmod(path, 0o600)
        with open(path, "w") as f:
            f.write("{}")
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "already_made")), (0, [book]))   # the reader gets the first generation, which matches
        self.assertEqual([(d["book_id"], d["generations"]) for d in got["damaged"]], [(book, [number])])

    def test_a_book_whose_only_generation_is_damaged_is_made(self):
        book, version = self.converted_book()
        number = self.file_generation(book, version)
        path = os.path.join(self.store.version_dir(book, version), "derived", theme.TOOL, str(number), theme.FILENAME)
        os.chmod(path, 0o600)
        with open(path, "w") as f:
            f.write("{}")
        self.assertEqual(theme.generations(self.store, book, version), [number])
        self.assertEqual(self.plan()["books"], 1)

    def test_again_makes_a_book_that_would_be_skipped(self):
        book, version = self.converted_book()
        self.file_generation(book, version)
        got = self.plan(again=True)
        self.assertEqual((got["books"], got["again"], got["skipped"]["already_made"], got["check_unknown"]), (1, True, 0, []))
        self.assertTrue(themerun.read_record(self.index_root(), got["run"])["again"])

    def test_a_generation_with_no_themes_cannot_say_how_it_was_made_so_a_record_of_a_run_must(self):
        book, version = self.converted_book()
        number = self.file_generation(book, version, themes=False)
        self.assertEqual(theme.read(self.store, book, version)[1]["themes"], [])
        self.assertEqual(self.plan()["books"], 1)
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(book, version, generation=number)]))
        got = self.plan()
        self.assertEqual((got["books"], self.skipped(got, "already_made")), (0, [book]))
        themerun.write_record(self.index_root(), record(RUN_NEW, [item(book, version, generation=number + 1)]))   # a later record of another generation
        self.assertEqual(self.plan()["books"], 1)
        themerun.write_record(self.index_root(), record(RUN_NEW, [item(book, version, generation=number, made={"theme": extraction(prompt_version="v3"), "theme-check": check()})]))
        self.assertEqual(self.plan()["books"], 1)   # a record that names another prompt is not the evidence


class CheckUnknownTest(PlanCase):
    def setUp(self):
        super().setUp()
        self.book, self.version = self.converted_book()
        self.number = self.file_generation(self.book, self.version)

    def unknown(self):
        got = self.plan()
        self.assertEqual(self.skipped(got, "already_made"), [self.book])   # in every case below the book is still skipped
        return [b["book_id"] for b in got["check_unknown"]]

    def test_a_record_that_names_the_check_now_set_leaves_the_book_off_the_list(self):
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number)]))
        self.assertEqual(self.unknown(), [])

    def test_a_record_that_names_another_check_model_or_prompt_puts_the_book_on_the_list(self):
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number, made={"theme": extraction(), "theme-check": check(model="other:latest")})]))
        self.assertEqual(self.unknown(), [self.book])
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number, made={"theme": extraction(), "theme-check": check(prompt_version="v0")})]))
        self.assertEqual(self.unknown(), [self.book])

    def test_a_book_with_no_record_is_on_the_list_and_so_is_every_book_when_the_records_are_lost(self):
        self.assertEqual(self.unknown(), [self.book])
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number)]))
        self.assertEqual(self.unknown(), [])
        os.remove(os.path.join(self.index_root(), cardstate.FOLDER, RUN_OLD, themerun.RECORD))
        self.assertEqual(self.unknown(), [self.book])

    def test_the_newest_record_of_the_book_decides(self):
        old = record(RUN_OLD, [item(self.book, self.version, generation=self.number)])
        new = record(RUN_NEW, [item(self.book, self.version, generation=self.number, made={"theme": extraction(), "theme-check": check(model="other:latest")})])
        themerun.write_record(self.index_root(), old)
        themerun.write_record(self.index_root(), new)
        self.assertEqual(self.unknown(), [self.book])
        themerun.write_record(self.index_root(), record(RUN_NEW, [item(self.book, self.version, generation=self.number)]))
        self.assertEqual(self.unknown(), [])

    def test_a_record_of_a_failed_or_waiting_item_or_of_another_generation_is_not_evidence(self):
        for over in ({"status": "failed", "generation": None, "made": None}, {"status": "waiting", "generation": None, "made": None},
                     {"generation": self.number + 5}, {"status": "failed"}, {"status": "waiting"}, {"status": "dropped"}, {"generation": None}):
            with self.subTest(over=over):
                themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, **{"generation": self.number, **over})]))
                self.assertEqual(self.unknown(), [self.book])

    def test_only_the_newest_records_are_read(self):
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number)]))
        themerun.write_record(self.index_root(), record(RUN_NEW, []))
        self.assertEqual(self.unknown(), [])
        with unittest.mock.patch.object(themerun, "RUNS_READ", 1):
            self.assertEqual(self.unknown(), [self.book])   # the older record is not read

    def test_a_record_that_cannot_be_read_is_passed_over_and_the_book_is_on_the_list(self):
        themerun.write_record(self.index_root(), record(RUN_OLD, [item(self.book, self.version, generation=self.number)]))
        path = os.path.join(self.index_root(), cardstate.FOLDER, RUN_OLD, themerun.RECORD)
        with open(path, "w") as f:
            f.write("not json")
        os.chmod(path, 0o600)
        self.assertEqual(self.unknown(), [self.book])


class SendsNothingTest(PlanCase):
    def test_a_plan_makes_no_call_to_any_model(self):
        book, version = self.converted_book()
        self.file_generation(book, version)
        self.converted_book()
        boom = AssertionError("the plan reached a model")
        with unittest.mock.patch.object(models, "run_job", side_effect=boom) as job, unittest.mock.patch.object(models, "call", side_effect=boom) as call:
            got = self.plan()
            self.plan(again=True)
        self.assertEqual((job.call_count, call.call_count, got["books"]), (0, 0, 1))


class RefusalTest(PlanCase):
    def test_a_missing_model_is_refused_before_anything_is_written(self):
        self.converted_book()
        for cfg in (config(check=False), {**config(), "models_on": False}, {**config(), "tasks": {"theme-check": "checker"}}):
            with self.subTest(cfg=cfg.get("tasks")), self.assertRaises(KbError):
                self.plan(cfg=cfg)
        self.assertEqual(self.written(), [])


class RecordTest(PlanCase):
    def test_the_plan_writes_a_record_of_the_books_to_make_and_no_text_of_any_book(self):
        book, version = self.converted_book()
        got = self.plan()
        rec = themerun.read_record(self.index_root(), got["run"])
        self.assertEqual((rec["run"], rec["kind"], rec["again"], rec["extraction"], rec["check"]), (got["run"], "themes", False, extraction(), check()))
        self.assertEqual(rec["items"], [{"book_id": book, "version_id": version, "pieces": got["pieces"], "status": "waiting", "attempts": 0,
                                         "generation": None, "reason": "", "made": None,
                                         "conversion": themeextract.prepare(self.store, book)[2], "stats": None}])
        raw = open(os.path.join(self.index_root(), cardstate.FOLDER, got["run"], themerun.RECORD)).read()
        for text in ("cools a system", "A paper on annealing", "Annealing", "search"):
            self.assertNotIn(text, raw)
        self.assertEqual(os.stat(os.path.join(self.index_root(), cardstate.FOLDER, got["run"], themerun.RECORD)).st_mode & 0o777, 0o600)

    def test_each_plan_is_a_run_of_its_own(self):
        self.converted_book()
        a, b = self.plan()["run"], self.plan()["run"]
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(self.written()), sorted([a, b]))

    def test_a_name_that_is_taken_is_not_used_again(self):
        self.converted_book()
        with unittest.mock.patch.object(themerun, "_stamp", side_effect=["20261111t100000z-cccccc", "20261111t100000z-cccccc", "20261111t100000z-dddddd"]):
            first = self.plan()["run"]
            second = self.plan()["run"]
        self.assertEqual((first, second), ("20261111t100000z-cccccc", "20261111t100000z-dddddd"))
        self.assertEqual(len(themerun.read_record(self.index_root(), first)["items"]), 1)
        with unittest.mock.patch.object(themerun, "_stamp", return_value="20261111t100000z-cccccc"), self.assertRaises(KbError):
            self.plan()

    def test_a_record_that_is_not_in_the_form_is_refused_on_writing_and_on_reading(self):
        book, version = self.converted_book()
        good = record(RUN_OLD, [item(book, version, generation=1)])
        themerun.write_record(self.index_root(), good)
        self.assertEqual(themerun.read_record(self.index_root(), RUN_OLD)["items"][0]["book_id"], book)
        self.assertIsNone(themerun.read_record(self.index_root(), RUN_NEW))
        bad = [record(RUN_OLD, [item(book, version, status="finished")]), record(RUN_OLD, [item(book, version, pieces=-1)]),
               record(RUN_OLD, [item(book, "x1")]), record(RUN_OLD, [item("not-an-id", version)]), record(RUN_OLD, [item(book, version, reason="x" * 600)]),
               record(RUN_OLD, [item(book, version, made={"theme": extraction()})]),
               record(RUN_OLD, [item(book, version, made={"theme": extraction(), "theme-check": check(model="a b")})]),
               record(RUN_OLD, [item(book, version, made={"theme": extraction(), "theme-check": check(prompt_version="")})]),
               record(RUN_OLD, [item(book, version, made={"theme": extraction(model="a b"), "theme-check": check()})]),
               record(RUN_OLD, [{**item(book, version), "extra": 1}]), record(RUN_OLD, [], format=2), record(RUN_OLD, [], kind="cards"),
               record(RUN_OLD, [], again="yes"), record(RUN_OLD, [], extraction={"model": "m1:latest"}),
               record(RUN_OLD, [], created=5), record("Not A Run", [])]
        for rec in bad:
            with self.subTest(rec=str(rec)[:80]), self.assertRaises(KbError):
                themerun.write_record(self.index_root(), rec)
        path = os.path.join(self.index_root(), cardstate.FOLDER, RUN_OLD, themerun.RECORD)
        for text in ('{"format": 1}', json.dumps(record(RUN_NEW, [])), json.dumps({**good, "items": [{**good["items"][0], "status": "x"}]}), "[]"):
            with open(path, "w") as f:
                f.write(text)
            with self.subTest(text=text[:40]), self.assertRaises(KbError):
                themerun.read_record(self.index_root(), RUN_OLD)

    def test_a_record_is_not_taken_from_the_folder_of_a_card_run(self):
        self.converted_book()
        got = self.plan()
        self.assertEqual(cardstate.read_manifest(self.index_root(), got["run"]), None)   # a card run's manifest is another file: the card queue sees no run here

    def test_a_folder_of_a_card_run_is_passed_over_and_is_left_as_it_was(self):
        book, version = self.converted_book()
        manifest = cardstate.Manifest(RUN_NEW, "2026-11-11T10:00:00Z", False, [])
        cardstate.write_manifest(self.index_root(), RUN_NEW, manifest)
        self.assertIsNone(themerun.read_record(self.index_root(), RUN_NEW))
        got = self.plan()                                                                  # with a card run's folder present, and newer than any theme run
        self.assertEqual(got["books"], 1)
        self.assertEqual(cardstate.read_manifest(self.index_root(), RUN_NEW).run, RUN_NEW)
        themerun.write_record(self.index_root(), record(RUN_NEW, [item(book, version, status="waiting", generation=None, made=None)]))
        self.assertEqual(cardstate.read_manifest(self.index_root(), RUN_NEW).run, RUN_NEW)   # the two files live side by side
        self.assertEqual(themerun.read_record(self.index_root(), RUN_NEW)["items"][0]["book_id"], book)

    def test_two_items_for_the_same_version_are_refused(self):
        book, version = self.converted_book()
        twice = record(RUN_OLD, [item(book, version, status="waiting", generation=None, made=None), item(book, version, status="waiting", generation=None, made=None)])
        with self.assertRaises(KbError):
            themerun.write_record(self.index_root(), twice)
        self.assertIsNone(themerun.read_record(self.index_root(), RUN_OLD))


def verdicts(*words):
    return {"verdicts": list(words)}


GOOD = [values(row()), verdicts("supports", "supports", "supports", "supports")]   # a book whose one theme is made and checked: two calls
BAD = {**values(row()), "types": []}                                               # an answer whose lists are not of one length: refused
REFUSED = [BAD, BAD]                                                              # refused, asked again, refused again: the book fails


def scripted(*script):
    """Stands in for `models.run_job`: a script of replies, exceptions (including an interrupt, which `Fake` would return as a reply), and the calls made."""
    fake = Fake(*script)

    def call(*a, **k):
        if fake.script and isinstance(fake.script[0], BaseException) and not isinstance(fake.script[0], Exception):
            raise fake.script.pop(0)
        return fake(*a, **k)
    call.calls, call.script = fake.calls, fake.script
    return call


class RunCase(PlanCase):
    def books(self, n):
        for _ in range(n):
            self.converted_book()

    def planned(self, n):
        self.books(n)
        got = self.plan()
        return got["run"], [b["book_id"] for b in got["to_make"]]

    def run_with(self, run, script, cfg=None):
        fake = scripted(*script)
        with unittest.mock.patch.object(models, "run_job", fake):
            try:
                return themerun.run(self.store, cfg or config(), run)
            finally:
                self.fake = fake

    def items(self, run):
        return {i["book_id"]: i for i in themerun.read_record(self.index_root(), run)["items"]}

    def raw(self, run):
        return open(os.path.join(self.index_root(), cardstate.FOLDER, run, themerun.RECORD)).read()


class RunTest(RunCase):
    def test_a_run_makes_the_books_files_their_generations_and_records_what_was_done(self):
        run, ids = self.planned(2)
        report = self.run_with(run, GOOD + GOOD)
        self.assertEqual((report["stopped"], report["passes"], report["counts"]), (None, 1, {"waiting": 0, "done": 2, "failed": 0, "dropped": 0}))
        self.assertEqual(len(self.fake.calls), 4)
        for book in ids:
            item = self.items(run)[book]
            version = self.store.read_book(book)["current_version"]
            number, generation = theme.read(self.store, book, version)
            self.assertEqual((item["status"], item["generation"], item["attempts"], item["reason"]), ("done", number, 0, ""))
            self.assertEqual(item["made"], {"theme": {"model": "m1:latest", "prompt_version": "v1"}, "theme-check": {"model": "m1:latest", "prompt_version": "v1"}})
            themes = generation["themes"]
            marks = [p["mark"] for t in themes for p in t["neutral"].values() if p["mark"]]
            stats = item["stats"]
            self.assertEqual((stats["themes"], stats["pieces"], stats["calls"], stats["stated"], stats["inferred"]),
                             (len(themes), 1, 2, marks.count("stated"), marks.count("inferred")))
            self.assertEqual(stats["input_tokens"], 2 * RECORD_TOKENS[0])
            self.assertEqual(stats["output_tokens"], 2 * RECORD_TOKENS[1])
            self.assertEqual(stats["flags"], dict(Counter(f["kind"] for t in themes for f in t["flags"])))
            self.assertEqual(stats["dropped"], {})
        self.assertEqual([i["book_id"] for i in report["items"]], ids)

    def test_a_refused_answer_fails_that_book_and_the_others_go_on_and_the_failed_book_is_tried_once_more_after_the_last(self):
        run, ids = self.planned(2)
        report = self.run_with(run, REFUSED + GOOD + GOOD)             # the first book is refused, the second is made, then the first is made
        self.assertEqual((report["counts"]["done"], report["passes"]), (2, 2))
        first = self.items(run)[ids[0]]
        self.assertEqual((first["status"], first["attempts"], first["reason"]), ("done", 1, ""))
        self.assertEqual(self.items(run)[ids[1]]["attempts"], 0)
        refused = os.path.join(self.index_root(), "refused")
        self.assertGreaterEqual(len(os.listdir(refused)), 1)              # the answers were kept aside for the owner

    def test_a_book_refused_in_both_passes_is_failed_with_the_kind_and_the_run_does_not_stop(self):
        run, ids = self.planned(2)
        report = self.run_with(run, REFUSED + GOOD + REFUSED)
        self.assertEqual((report["counts"], report["stopped"]), ({"waiting": 0, "done": 1, "failed": 1, "dropped": 0}, None))
        failed = self.items(run)[ids[0]]
        self.assertEqual((failed["status"], failed["attempts"], failed["reason"], failed["generation"], failed["stats"]), ("failed", 2, "refused", None, None))
        self.assertEqual(theme.generations(self.store, ids[0], self.store.read_book(ids[0])["current_version"]), [])
        again = self.run_with(run, [])                                     # failed books are not tried again by running again: plan again for them
        self.assertEqual((again["counts"]["failed"], len(self.fake.calls)), (1, 0))

    def test_a_failed_call_fails_that_book_with_a_fixed_reason_and_the_message_is_not_kept(self):
        run, ids = self.planned(2)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [KbError("the server said: secret-title-xyz"), *GOOD])
        self.assertEqual(report["counts"], {"waiting": 0, "done": 1, "failed": 1, "dropped": 0})
        self.assertEqual(self.items(run)[ids[0]]["reason"], "failed")
        self.assertNotIn("secret-title-xyz", self.raw(run))
        self.assertNotIn("secret-title-xyz", json.dumps(report))

    def test_an_unexpected_error_fails_that_book_and_shows_its_kind_only(self):
        run, ids = self.planned(2)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [ValueError("secret-title-xyz"), *GOOD])
        self.assertEqual(self.items(run)[ids[0]]["reason"], "an unexpected error (ValueError)")
        self.assertEqual(report["counts"]["done"], 1)
        self.assertNotIn("secret-title-xyz", self.raw(run) + json.dumps(report))

    def test_three_books_in_a_row_that_fail_for_a_reason_that_is_not_a_refused_answer_stop_the_run(self):
        run, ids = self.planned(4)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [KbError("x"), KbError("x"), KbError("x"), *GOOD])
        self.assertEqual(len(self.fake.calls), 3)                          # the fourth book was not tried
        self.assertIn("3 books in a row", report["stopped"])
        self.assertEqual(report["counts"], {"waiting": 1, "done": 0, "failed": 3, "dropped": 0})
        self.assertEqual(self.items(run)[ids[3]]["status"], "waiting")

    def test_three_unexpected_errors_in_a_row_stop_the_run_too(self):
        run, ids = self.planned(4)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [ValueError("x"), TypeError("x"), ValueError("x"), *GOOD])
        self.assertEqual(len(self.fake.calls), 3)
        self.assertIn("3 books in a row", report["stopped"])
        self.assertEqual([self.items(run)[b]["reason"] for b in ids[:3]],
                         ["an unexpected error (ValueError)", "an unexpected error (TypeError)", "an unexpected error (ValueError)"])

    def test_the_flags_of_the_themes_are_counted_in_the_stats(self):
        run, ids = self.planned(1)
        with unittest.mock.patch.object(themecheck, "library_frequencies", return_value=({"annealing": 1, "search": 1}, 30)):
            report = self.run_with(run, [values(row(problem="annealing of a search space")), verdicts("supports", "supports", "supports", "supports")])
        generation = theme.read(self.store, ids[0], self.store.read_book(ids[0])["current_version"])[1]
        flags = dict(Counter(f["kind"] for t in generation["themes"] for f in t["flags"]))
        self.assertEqual(flags.get("field_words"), 1)                       # the theme is flagged, so the stats have something to count
        self.assertEqual(self.items(run)[ids[0]]["stats"]["flags"], flags)
        self.assertEqual(report["totals"]["flags"], flags)

    def test_the_stop_waits_for_the_books_to_be_tried_again_when_they_may_be(self):
        run, ids = self.planned(4)
        report = self.run_with(run, [KbError("x"), KbError("x"), KbError("x"), *GOOD])
        self.assertIn("3 books in a row", report["stopped"])
        self.assertEqual(report["counts"], {"waiting": 4, "done": 0, "failed": 0, "dropped": 0})   # all four still wait: the run can be run again
        self.assertEqual([self.items(run)[b]["attempts"] for b in ids], [1, 1, 1, 0])
        resumed = self.run_with(run, GOOD * 4)
        self.assertEqual((resumed["stopped"], resumed["counts"]["done"]), (None, 4))

    def test_a_success_or_a_refused_answer_between_failures_means_the_failures_are_not_in_a_row(self):
        run, ids = self.planned(8)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            # two failures, a success; two failures, a refused answer; a failure, a success: never three in a row
            report = self.run_with(run, [KbError("x"), KbError("x"), *GOOD, KbError("x"), KbError("x"), *REFUSED, KbError("x"), *GOOD])
        self.assertIsNone(report["stopped"])
        self.assertEqual(report["counts"], {"waiting": 0, "done": 2, "failed": 6, "dropped": 0})

    def test_three_refused_books_do_not_stop_the_run(self):
        run, ids = self.planned(3)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, REFUSED * 3)
        self.assertEqual((report["stopped"], report["counts"]["failed"]), (None, 3))
        self.assertEqual({self.items(run)[b]["reason"] for b in ids}, {"refused"})

    def test_a_run_that_is_stopped_and_run_again_repeats_no_finished_book(self):
        run, ids = self.planned(3)
        with self.assertRaises(KeyboardInterrupt):
            self.run_with(run, GOOD + GOOD + [KeyboardInterrupt()])
        self.assertEqual(len(self.fake.calls), 4)
        self.assertEqual([self.items(run)[b]["status"] for b in ids], ["done", "done", "waiting"])
        report = self.run_with(run, GOOD)
        self.assertEqual(len(self.fake.calls), 2)                          # only the book that had not been made
        self.assertEqual(report["counts"]["done"], 3)
        self.assertEqual([theme.generations(self.store, b, self.store.read_book(b)["current_version"]) for b in ids], [[1], [1], [1]])

    def test_a_run_killed_after_a_book_is_filed_and_before_it_is_recorded_makes_that_book_again_as_a_new_generation(self):
        run, ids = self.planned(2)
        real = theme.file

        def file_then_die(store, generation):
            real(store, generation)
            raise KeyboardInterrupt()
        with unittest.mock.patch.object(theme, "file", file_then_die), self.assertRaises(KeyboardInterrupt):
            self.run_with(run, GOOD)
        version = self.store.read_book(ids[0])["current_version"]
        self.assertEqual((theme.generations(self.store, ids[0], version), self.items(run)[ids[0]]["status"]), ([1], "waiting"))   # filed, not recorded
        report = self.run_with(run, GOOD + GOOD)
        self.assertEqual(report["counts"]["done"], 2)
        self.assertEqual(theme.generations(self.store, ids[0], version), [1, 2])      # made again: the accepted window, one book at most
        self.assertEqual(self.items(run)[ids[0]]["generation"], 2)

    def test_what_the_record_will_say_is_checked_before_a_book_is_filed(self):
        run, ids = self.planned(2)
        bad = {"themes": -1}
        with unittest.mock.patch.object(themerun, "_stats_of", return_value=bad), unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, GOOD + GOOD)
        self.assertEqual(report["counts"], {"waiting": 0, "done": 0, "failed": 2, "dropped": 0})
        for book in ids:
            self.assertEqual(theme.generations(self.store, book, self.store.read_book(book)["current_version"]), [])   # nothing was filed
            self.assertEqual(self.items(run)[book]["reason"], "failed")

    def test_the_count_of_failures_in_a_row_goes_on_from_the_first_pass_into_the_second(self):
        run, ids = self.planned(2)
        report = self.run_with(run, [KbError("x"), KbError("x"), KbError("x"), *GOOD])   # the first book, the second, then the first again
        self.assertEqual(len(self.fake.calls), 3)
        self.assertIn("3 books in a row", report["stopped"])
        self.assertEqual((self.items(run)[ids[0]]["status"], self.items(run)[ids[0]]["attempts"]), ("failed", 2))
        self.assertEqual((self.items(run)[ids[1]]["status"], self.items(run)[ids[1]]["attempts"]), ("waiting", 1))

    def test_a_book_dropped_between_failures_neither_ends_nor_adds_to_the_count(self):
        run, ids = self.planned(4)
        self.store.set_state(ids[1], "weeded")
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [KbError("x"), KbError("x"), KbError("x"), *GOOD])
        self.assertIn("3 books in a row", report["stopped"])
        self.assertEqual((len(self.fake.calls), report["counts"]["dropped"]), (3, 1))

    def test_the_report_has_the_sums_of_the_books_done_and_the_time_of_the_call(self):
        run, ids = self.planned(2)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, [values(row(), row(type="proof", title="A proof", blocks="5")), verdicts("supports", "supports", "supports", "supports"), *REFUSED])
        items = [i for i in self.items(run).values() if i["status"] == "done"]
        totals = report["totals"]
        self.assertEqual((totals["books"], totals["themes"], totals["dropped"]), (1, 1, {"proof_or_definition": 1}))
        self.assertEqual((totals["calls"], totals["pieces"], totals["input_tokens"], totals["output_tokens"]), (2, 1, 2 * RECORD_TOKENS[0], 2 * RECORD_TOKENS[1]))
        self.assertEqual(totals["stated"], items[0]["stats"]["stated"])
        self.assertIsInstance(report["elapsed_seconds"], int)
        self.assertEqual(themerun.status(self.store, run)["totals"], totals)

    def test_a_run_with_nothing_waiting_makes_no_call(self):
        run, _ = self.planned(1)
        self.run_with(run, GOOD)
        report = self.run_with(run, [])
        self.assertEqual((len(self.fake.calls), report["passes"], report["counts"]["done"]), (0, 0, 1))

    def test_a_book_that_is_no_longer_active_is_dropped_and_reported(self):
        run, ids = self.planned(2)
        self.store.set_state(ids[0], "weeded")
        report = self.run_with(run, GOOD)
        self.assertEqual(report["counts"], {"waiting": 0, "done": 1, "failed": 0, "dropped": 1})
        self.assertEqual((self.items(run)[ids[0]]["status"], self.items(run)[ids[0]]["reason"]), ("dropped", "no_longer_active"))
        self.assertEqual(len(self.fake.calls), 2)

    def test_a_book_with_another_current_version_is_dropped(self):
        run, ids = self.planned(1)
        rec = themerun.read_record(self.index_root(), run)
        rec["items"][0]["version_id"] = "v9"
        themerun.write_record(self.index_root(), rec)
        report = self.run_with(run, GOOD)
        self.assertEqual((report["counts"]["dropped"], self.items(run)[ids[0]]["reason"], len(self.fake.calls)), (1, "no_longer_active", 0))

    def test_a_book_whose_conversion_changed_since_the_plan_is_dropped(self):
        run, ids = self.planned(1)
        rec = themerun.read_record(self.index_root(), run)
        rec["items"][0]["conversion"]["generation"] += 1
        themerun.write_record(self.index_root(), rec)
        report = self.run_with(run, GOOD)
        self.assertEqual((report["counts"]["dropped"], self.items(run)[ids[0]]["reason"], len(self.fake.calls)), (1, "conversion_changed", 0))

    def test_only_one_holder_of_the_lock_runs_at_a_time(self):
        run, _ = self.planned(1)
        with cardstate.lock(self.index_root(), run), self.assertRaises(KbError) as cm:
            self.run_with(run, GOOD)
        self.assertIn("another run holds the lock", str(cm.exception))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.run_with(run, GOOD)["counts"]["done"], 1)     # and the lock is free again when the holder ends

    def test_the_models_or_prompts_changed_since_the_plan_refuse_the_run_before_any_call(self):
        run, _ = self.planned(1)
        other = config()
        other["models"]["themer"]["model"] = "m9:latest"
        with self.assertRaises(KbError) as cm:
            self.run_with(run, GOOD, cfg=other)
        self.assertIn("plan again", str(cm.exception))
        other = config()
        other["models"]["checker"]["model"] = "m9:latest"
        with self.assertRaises(KbError) as cm:
            self.run_with(run, GOOD, cfg=other)
        self.assertIn("plan again", str(cm.exception))
        with unittest.mock.patch.object(themecheck, "check_job", return_value=unittest.mock.Mock(prompt_version="v7")), self.assertRaises(KbError) as cm:
            self.run_with(run, GOOD)
        self.assertIn("plan again", str(cm.exception))
        with unittest.mock.patch.object(themeextract.THEME_JOB, "prompt_version", "v9"), self.assertRaises(KbError) as cm:
            self.run_with(run, GOOD)
        self.assertIn("plan again", str(cm.exception))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.items(run)[next(iter(self.items(run)))]["status"], "waiting")

    def test_a_run_that_does_not_exist_or_a_missing_model_is_refused(self):
        with self.assertRaises(KbError):
            self.run_with("20261111t100000z-zzzzzz", GOOD)
        run, _ = self.planned(1)
        with self.assertRaises(KbError):
            self.run_with(run, GOOD, cfg=config(check=False))
        self.assertEqual(self.fake.calls, [])

    def test_the_library_is_counted_once_for_the_whole_run(self):
        run, _ = self.planned(3)
        with unittest.mock.patch.object(themecheck, "library_frequencies", wraps=themecheck.library_frequencies) as counted:
            self.run_with(run, GOOD * 3)
        self.assertEqual(counted.call_count, 1)

    def test_a_book_with_no_themes_is_filed_with_an_empty_generation_and_names_the_check_that_was_set(self):
        run, ids = self.planned(1)
        report = self.run_with(run, [values()])
        item = self.items(run)[ids[0]]
        self.assertEqual((report["counts"]["done"], item["stats"]["themes"], item["stats"]["calls"]), (1, 0, 1))
        self.assertEqual(item["made"]["theme-check"], {"model": "m2:latest", "prompt_version": themecheck.check_job(1).prompt_version})   # no check was made: the one that was set
        self.assertEqual(theme.read(self.store, ids[0], self.store.read_book(ids[0])["current_version"])[1]["themes"], [])

    def test_a_theme_dropped_is_counted_by_the_kind_of_reason(self):
        run, ids = self.planned(1)
        self.run_with(run, [values(row(), row(type="proof", title="A proof", blocks="5")), verdicts("supports", "supports", "supports", "supports")])
        self.assertEqual(self.items(run)[ids[0]]["stats"]["dropped"], {"proof_or_definition": 1})

    def test_a_filing_that_fails_fails_the_book_and_the_run_goes_on(self):
        run, ids = self.planned(2)
        real, filed = theme.file, []

        def file(store, generation):
            filed.append(generation["book_id"])
            if len(filed) == 1:
                raise KbError("no room")
            return real(store, generation)
        with unittest.mock.patch.object(theme, "file", file), unittest.mock.patch.object(themerun, "RETRIES", 0):
            report = self.run_with(run, GOOD + GOOD)
        self.assertEqual(filed, ids)
        self.assertEqual((self.items(run)[ids[0]]["status"], self.items(run)[ids[0]]["reason"]), ("failed", "failed"))
        self.assertEqual((self.items(run)[ids[1]]["status"], report["counts"]["done"]), ("done", 1))
        self.assertEqual(theme.generations(self.store, ids[0], self.store.read_book(ids[0])["current_version"]), [])

    def test_the_record_holds_no_text_of_a_book_or_of_a_reply(self):
        run, _ = self.planned(3)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            self.run_with(run, GOOD + [ValueError("secret-xyz")] + REFUSED)
        raw = self.raw(run)
        for text in ("annealing", "cools a system", "Stopping a search", "secret-xyz", "accept a worse state", "A paper"):
            self.assertNotIn(text, raw)


class StatusTest(RunCase):
    def test_status_shows_where_each_book_has_got_to_and_no_text(self):
        run, ids = self.planned(2)
        before = themerun.status(self.store, run)
        self.assertEqual((before["counts"], [i["status"] for i in before["items"]]), ({"waiting": 2, "done": 0, "failed": 0, "dropped": 0}, ["waiting", "waiting"]))
        self.assertEqual(before["pieces"], sum(i["pieces"] for i in before["items"]))
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            self.run_with(run, GOOD + REFUSED)
        after = themerun.status(self.store, run)
        self.assertEqual(after["counts"], {"waiting": 0, "done": 1, "failed": 1, "dropped": 0})
        self.assertEqual([(i["book_id"], i["status"], i["reason"]) for i in after["items"]], [(ids[0], "done", ""), (ids[1], "failed", "refused")])
        self.assertEqual(after["pieces_done"], after["items"][0]["pieces"])
        self.assertNotIn("annealing", json.dumps(after))

    def test_status_of_a_run_that_does_not_exist_is_a_refusal(self):
        with self.assertRaises(KbError):
            themerun.status(self.store, "20261111t100000z-zzzzzz")


class CategoryTest(unittest.TestCase):
    def test_each_reason_for_dropping_a_theme_has_a_kind(self):
        cases = {"the excerpt is 6437 characters, more than the 6000 a theme may point to": "span_over_limit",
                 "the blocks are not numbers": "pointer_not_numbers", "the blocks named are not in the piece": "pointer_not_in_piece",
                 "skipped: a proof": "proof_or_definition", "skipped: a definition that serves only this text": "proof_or_definition",
                 "merged into a near-identical theme": "merged_near_identical", "unchecked: the answer was refused": "unchecked",
                 "the theme has no usable title": "unusable_field", "the theme has no summary": "unusable_field", "the excerpt has no words": "other",
                 "anything else": "other", "": "other"}
        for reason, kind in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(themerun._category(reason), kind)
        self.assertEqual(set(cases.values()) - set(themerun.DROP_KINDS), set())


class FormOfRunRecordTest(PlanCase):
    def test_the_fixed_reasons_and_the_stats_are_checked_in_the_form(self):
        book, version = self.converted_book()
        stats = {"themes": 1, "dropped": {"span_over_limit": 2}, "flags": {"field_words": 1}, "stated": 3, "inferred": 1, "pieces": 1, "calls": 2,
                 "input_tokens": 10, "output_tokens": 5, "seconds": 7}
        ref = {"tool": "kb-html-std", "version": "0.0.1", "generation": 1}
        for reason in ("", "refused", "failed", "no_longer_active", "conversion_changed", "an unexpected error (ValueError)"):
            themerun.write_record(self.index_root(), record(RUN_OLD, [item(book, version, reason=reason, conversion=ref, stats=stats)]))
        bad = [dict(reason="the title of a book"), dict(reason="an unexpected error (Value Error)"), dict(reason="an unexpected error (ValueError) and more"),
               dict(conversion={**ref, "extra": 1}), dict(conversion={**ref, "generation": -1}), dict(conversion={**ref, "tool": ""}),
               dict(stats={**stats, "extra": 1}), dict(stats={**stats, "themes": -1}), dict(stats={**stats, "dropped": {"a book title": 1}}),
               dict(stats={**stats, "flags": {"Field Words": 1}}), dict(stats={**stats, "flags": {"field_words": "1"}}), dict(stats={**stats, "seconds": True}),
               dict(stats={k: v for k, v in stats.items() if k != "calls"}), dict(stats="many"), dict(conversion="v1")]
        for over in bad:
            with self.subTest(over=str(over)[:70]), self.assertRaises(KbError):
                themerun.write_record(self.index_root(), record(RUN_OLD, [item(book, version, **over)]))


class CommandTest(RunCase):
    """`python3 -m kb themes-run`: in this process against a real temporary library (the models are the fake of the other tests), and once as a real command."""

    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(config())
        kbconfig.save(saved)

    def kb(self, *args, script=()):
        out, err = io.StringIO(), io.StringIO()
        self.asked = scripted(*script)
        with unittest.mock.patch.object(models, "run_job", self.asked), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(["themes-run", *args])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_plan_run_and_status_run_through_the_command_line_and_print_numbers_and_ids_and_titles_only(self):
        self.books(2)
        code, out, err = self.kb("plan")
        self.assertEqual((code, err, self.asked.calls), (0, "", []))   # the plan, as a command, sends nothing
        planned = json.loads(out)
        self.assertEqual((planned["books"], planned["pieces"] > 0), (2, True))
        self.assertEqual({b["title"] for b in planned["to_make"]}, {"A paper on annealing"})   # the titles are in the plan that is shown
        run = planned["run"]
        code, out, err = self.kb("run", run, script=GOOD + GOOD)
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual((report["counts"]["done"], report["stopped"]), (2, None))
        code, out, err = self.kb("status", run)
        self.assertEqual((code, err, json.loads(out)["counts"]["done"]), (0, "", 2))
        for text in (out, json.dumps(report)):
            self.assertNotIn("cools a system", text)

    def test_plan_takes_the_books_to_plan_and_again(self):
        a = self.converted_book()[0]
        self.converted_book()
        code, out, _ = self.kb("plan", "--book", a)
        self.assertEqual((code, [b["book_id"] for b in json.loads(out)["to_make"]]), (0, [a]))
        code, out, _ = self.kb("plan", "--again")
        self.assertEqual((code, json.loads(out)["again"]), (0, True))

    def test_the_exit_code_of_a_run_is_one_when_a_book_failed_and_the_error_output_says_so(self):
        run, _ = self.planned(2)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            code, out, err = self.kb("run", run, script=REFUSED + GOOD)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["counts"], {"waiting": 0, "done": 1, "failed": 1, "dropped": 0})
        self.assertIn("1 book", err)

    def test_the_exit_code_of_a_run_that_was_stopped_is_one_and_the_reason_is_on_the_error_output(self):
        run, _ = self.planned(4)
        with unittest.mock.patch.object(themerun, "RETRIES", 0):
            code, out, err = self.kb("run", run, script=[KbError("x"), KbError("x"), KbError("x")])
        self.assertEqual(code, 1)
        self.assertIn("3 books in a row", err)
        self.assertIn("3 books in a row", json.loads(out)["stopped"])

    def test_a_run_that_was_stopped_with_no_book_failed_yet_still_exits_with_one(self):
        run, _ = self.planned(4)
        code, out, err = self.kb("run", run, script=[KbError("x"), KbError("x"), KbError("x")])   # the books that failed once wait for another try
        self.assertEqual(json.loads(out)["counts"], {"waiting": 4, "done": 0, "failed": 0, "dropped": 0})
        self.assertEqual(code, 1)
        self.assertIn("3 books in a row", err)

    def test_status_opens_the_library_to_read_and_the_plan_and_the_run_to_write(self):
        run, _ = self.planned(1)
        opened = []
        real = kbmain.Store.open
        with unittest.mock.patch.object(kbmain.Store, "open", side_effect=lambda *a, **k: opened.append((a, k)) or real(*a, **k)):
            self.kb("status", run)
            self.kb("plan")
            self.kb("run", run, script=GOOD)
        self.assertEqual(opened, [((), {"write": False}), ((), {}), ((), {})])

    def test_a_refusal_is_printed_and_the_exit_code_is_two(self):
        code, out, err = self.kb("run", "nosuchrun")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("refused:", err)
        code, _, err = self.kb("status", "nosuchrun")
        self.assertEqual(code, 2)
        self.assertIn("refused:", err)

    def test_no_option_names_a_model_a_server_or_an_address_and_nothing_is_sent(self):
        run, _ = self.planned(1)
        for args in (["plan", "--model", "x"], ["plan", "--server", "x"], ["plan", "--address", "x"], ["run", run, "--model", "x"],
                     ["run", run, "--passes", "2"], ["status", run, "--server", "x"], ["plan", "--path", "x"], ["status", run, "--address", "x"], []):
            with self.subTest(args=args):
                self.assertEqual(self.kb(*args, script=GOOD)[0], 2)
        self.assertEqual(self.items(run)[next(iter(self.items(run)))]["status"], "waiting")   # none of them ran anything

    def test_a_plan_sends_nothing_when_it_is_run_as_a_command(self):
        self.books(1)
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg)
        done = subprocess.run([sys.executable, "-m", "kb", "themes-run", "plan"], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["books"], 1)
        bad = subprocess.run([sys.executable, "-m", "kb", "themes-run", "plan", "--model", "x"], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(bad.returncode, 2)


RECORD_TOKENS = (10, 5)   # the input and output tokens of the record that `Fake` returns for every call


if __name__ == "__main__":
    unittest.main()
