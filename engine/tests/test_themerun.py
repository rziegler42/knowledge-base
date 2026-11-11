import copy
import json
import os
import unittest
import unittest.mock

from engine.tests.test_themecheck import config
from engine.tests.test_themeextract import Fake, VersionCase, row, values

from kb import KbError, card, cardstate, models, theme, themecheck, themeextract, themerun

RUN_OLD, RUN_NEW = "20261110t100000z-aaaaaa", "20261111t100000z-bbbbbb"


def extraction(**over):
    return {"model": "m1:latest", "prompt_version": themeextract.THEME_JOB.prompt_version, **over}


def check(**over):
    return {"model": "m2:latest", "prompt_version": themecheck.check_job(1).prompt_version, **over}


def item(book, version, status="done", generation=1, made="both", **over):
    made = {"theme": extraction(), "theme-check": check()} if made == "both" else made
    base = {"book_id": book, "version_id": version, "pieces": 1, "status": status, "attempts": 0, "generation": generation, "reason": "",
            "made": made}
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
                                         "generation": None, "reason": "", "made": None}])
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


if __name__ == "__main__":
    unittest.main()
