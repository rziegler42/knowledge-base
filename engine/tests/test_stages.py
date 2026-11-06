import json
import os
import unittest
from unittest import mock

from kb import KbError, stages

from engine.tests.test_store import StoreCase, read_json


class StagesTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.book, self.version = self.new_version()

    def status(self, stage):
        return stages.read(self.store, self.book, self.version)["stages"][stage]["status"]

    def test_a_new_version_starts_with_found_done_and_the_rest_pending(self):
        self.assertEqual([self.status(s) for s in stages.STAGES], ["done", "pending", "pending", "pending", "pending"])

    def test_a_stage_cannot_be_done_before_the_stage_it_needs(self):
        with self.assertRaises(KbError) as cm:
            stages.mark(self.store, self.book, self.version, "scanned", "done")
        self.assertIn("fetched", str(cm.exception))
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "converted", "done")
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "indexed", "done")
        self.assertEqual(self.status("scanned"), "pending")

    def test_the_chain_can_be_completed_in_order(self):
        for s in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, self.book, self.version, s, "done", tool="t")
        self.assertEqual([self.status(s) for s in stages.STAGES], ["done"] * 5)
        self.assertEqual(stages.due(self.store, self.book, self.version), [])

    def test_conversion_may_follow_a_failed_or_skipped_scan_but_not_a_pending_one(self):
        stages.mark(self.store, self.book, self.version, "fetched", "done")
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "converted", "done")
        stages.mark(self.store, self.book, self.version, "scanned", "failed", reason="tool crashed")
        stages.mark(self.store, self.book, self.version, "converted", "done")
        self.assertEqual(self.status("converted"), "done")

    def test_a_failed_stage_records_its_reason_and_is_due_again(self):
        stages.mark(self.store, self.book, self.version, "fetched", "failed", reason="timeout", tool="fetch 1")
        entry = stages.read(self.store, self.book, self.version)["stages"]["fetched"]
        self.assertEqual((entry["status"], entry["reason"], entry["tool"]), ("failed", "timeout", "fetch 1"))
        self.assertEqual(stages.due(self.store, self.book, self.version), ["fetched"])
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "fetched", "failed")  # a failure needs a reason

    def test_a_reason_is_cleaned_and_one_that_is_nothing_once_cleaned_counts_as_no_reason(self):
        stages.mark(self.store, self.book, self.version, "fetched", "failed", reason="bad \x1b[31mthing‮ happened\n", tool="t\x07ool")
        entry = stages.read(self.store, self.book, self.version)["stages"]["fetched"]
        self.assertEqual((entry["reason"], entry["tool"]), ("bad [31mthing happened", "tool"))
        for empty in ("\x1b‮​", "   \n ", "ㅤ"):
            with self.assertRaises(KbError, msg=repr(empty)):
                stages.mark(self.store, self.book, self.version, "fetched", "failed", reason=empty)

    def test_due_lists_only_runnable_pending_or_failed_stages(self):
        self.assertEqual(stages.due(self.store, self.book, self.version), ["fetched"])
        stages.mark(self.store, self.book, self.version, "fetched", "done")
        self.assertEqual(stages.due(self.store, self.book, self.version), ["scanned"])
        stages.mark(self.store, self.book, self.version, "scanned", "skipped", reason="no scanner for this kind")
        self.assertEqual(stages.due(self.store, self.book, self.version), ["converted"])

    def test_a_done_stage_is_not_run_again_or_changed(self):
        stages.mark(self.store, self.book, self.version, "fetched", "done")
        stages.mark(self.store, self.book, self.version, "fetched", "done")  # repeating is harmless
        self.assertNotIn("fetched", stages.due(self.store, self.book, self.version))
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "fetched", "failed", reason="x")
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "fetched", "pending")

    def test_an_unknown_stage_or_status_is_refused(self):
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "carded", "done")
        with self.assertRaises(KbError):
            stages.mark(self.store, self.book, self.version, "fetched", "finished")

    def test_a_stage_change_that_fails_to_write_leaves_the_old_state(self):
        with mock.patch("os.replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                stages.mark(self.store, self.book, self.version, "fetched", "done")
        self.assertEqual(self.status("fetched"), "pending")

    def test_a_killed_stage_change_leaves_the_old_state(self):
        done = self.run_child(f"""
from unittest import mock
from kb import stages, store
s = store.Store.open()
with mock.patch("os.replace", lambda *a, **k: os._exit(7)):
    stages.mark(s, {self.book!r}, {self.version!r}, "fetched", "done")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(self.status("fetched"), "pending")

    def test_a_damaged_state_file_is_reported(self):
        with open(os.path.join(self.store.version_dir(self.book, self.version), "stages.json"), "w") as f:
            f.write("{not json")
        with self.assertRaises(KbError):
            stages.read(self.store, self.book, self.version)


class RedoTest(StoreCase):
    """The owner's command to make the later stages of a version again, after a tool was changed and approved anew."""

    def setUp(self):
        super().setUp()
        self.book, self.version = self.new_version()
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, self.book, self.version, stage, "done", tool="t 1")

    def status(self, stage, version=None):
        return stages.read(self.store, self.book, version or self.version)["stages"][stage]["status"]

    def all_status(self):
        return [self.status(s) for s in stages.STAGES]

    def test_making_the_conversion_again_puts_it_and_the_index_back_and_nothing_before_it(self):
        self.assertEqual(stages.redo(self.store, self.book, self.version, "converted", "tools changed"), ["converted", "indexed"])
        self.assertEqual(self.all_status(), ["done", "done", "done", "pending", "pending"])
        entry = stages.read(self.store, self.book, self.version)["stages"]["converted"]
        self.assertEqual((entry["reason"], entry["tool"]), ("tools changed", ""))
        self.assertEqual(stages.due(self.store, self.book, self.version), ["converted"])  # the index waits for the conversion

    def test_making_the_scan_again_puts_back_the_scan_the_conversion_and_the_index(self):
        self.assertEqual(stages.redo(self.store, self.book, self.version, "scanned", "r"), ["scanned", "converted", "indexed"])
        self.assertEqual(self.all_status(), ["done", "done", "pending", "pending", "pending"])
        self.assertEqual(stages.due(self.store, self.book, self.version), ["scanned"])

    def test_only_the_index_can_be_made_again_alone(self):
        self.assertEqual(stages.redo(self.store, self.book, self.version, "indexed", "r"), ["indexed"])
        self.assertEqual(self.all_status(), ["done"] * 4 + ["pending"])

    def test_a_stage_that_is_not_done_is_left_as_it_is_and_is_not_reported(self):
        book, version = self.new_version()
        stages.mark(self.store, book, version, "fetched", "done")
        stages.mark(self.store, book, version, "scanned", "skipped", reason="no scanner")
        stages.mark(self.store, book, version, "converted", "failed", reason="it broke")
        self.assertEqual(stages.redo(self.store, book, version, "scanned", "r"), [])
        state = stages.read(self.store, book, version)["stages"]
        self.assertEqual((state["scanned"]["status"], state["scanned"]["reason"]), ("skipped", "no scanner"))
        self.assertEqual((state["converted"]["status"], state["converted"]["reason"]), ("failed", "it broke"))

    def test_a_version_that_was_not_fetched_is_left_alone(self):
        book, version = self.new_version()
        self.assertEqual(stages.redo(self.store, book, version, "converted", "r"), [])
        self.assertEqual(stages.redo(self.store, book, version, "scanned", "r"), [])
        stages.mark(self.store, book, version, "fetched", "failed", reason="timeout")
        self.assertEqual(stages.redo(self.store, book, version, "scanned", "r"), [])
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "failed")

    def test_a_state_that_says_a_later_stage_is_done_without_the_fetch_is_not_touched(self):
        book, version = self.new_version()
        state = stages.read(self.store, book, version)
        state["stages"]["converted"]["status"] = "done"  # a state no run of the engine makes: damaged, or edited by hand
        with open(self.store.stages_file(book, version), "w") as f:
            json.dump(state, f)
        self.assertEqual(stages.redo(self.store, book, version, "converted", "r"), [])
        self.assertEqual(stages.read(self.store, book, version)["stages"]["converted"]["status"], "done")

    def test_the_stages_before_the_scan_cannot_be_made_again_and_nor_can_a_name_that_is_none(self):
        for stage in ("found", "fetched", "nonsense", "", None, ["converted"]):
            with self.assertRaises(KbError, msg=repr(stage)):
                stages.redo(self.store, self.book, self.version, stage, "r")
        self.assertEqual(self.all_status(), ["done"] * 5)

    def test_the_reason_is_cleaned_like_any_other_text_from_outside(self):
        stages.redo(self.store, self.book, self.version, "converted", "bad \x1b[31mthing\u202e happened\n")
        self.assertEqual(stages.read(self.store, self.book, self.version)["stages"]["converted"]["reason"], "bad [31mthing happened")

    def test_making_it_again_twice_changes_nothing_the_second_time(self):
        stages.redo(self.store, self.book, self.version, "converted", "r")
        self.assertEqual(stages.redo(self.store, self.book, self.version, "converted", "again"), [])
        self.assertEqual(stages.read(self.store, self.book, self.version)["stages"]["converted"]["reason"], "r")

    def test_a_change_that_cannot_be_written_leaves_the_old_state(self):
        with mock.patch("kb.config.write_json_atomic", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                stages.redo(self.store, self.book, self.version, "converted", "r")
        self.assertEqual(self.all_status(), ["done"] * 5)

    def test_a_library_that_is_not_safe_to_write_is_not_written(self):
        with mock.patch.object(self.store, "_guard", side_effect=KbError("the library is not there")):
            with self.assertRaises(KbError):
                stages.redo(self.store, self.book, self.version, "converted", "r")
        self.assertEqual(self.all_status(), ["done"] * 5)

    def test_a_book_that_is_not_active_is_left_alone_and_the_books_named_are_the_only_ones_touched(self):
        other, other_version = self.new_version()
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, other, other_version, stage, "done")
        weeded, weeded_version = self.new_version()
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, weeded, weeded_version, stage, "done")
        self.store.set_state(weeded, "weeded")
        done = stages.redo_books(self.store, [self.book, weeded], scan=False, reason="r")
        self.assertEqual(done, [{"book_id": self.book, "version_id": self.version, "stages": ["converted", "indexed"]}])
        self.assertEqual(self.all_status(), ["done", "done", "done", "pending", "pending"])
        self.assertEqual(stages.read(self.store, other, other_version)["stages"]["converted"]["status"], "done")
        self.assertEqual(stages.read(self.store, weeded, weeded_version)["stages"]["converted"]["status"], "done")

    def test_with_no_books_named_every_active_book_and_every_version_of_it_is_made_again(self):
        second = self.store.add_version(self.book, label="v2")
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, self.book, second, stage, "done")
        other, other_version = self.new_version()  # not fetched: nothing to do
        done = stages.redo_books(self.store, None, scan=True, reason="r")
        self.assertEqual(sorted((d["version_id"], tuple(d["stages"])) for d in done),
                         sorted([(self.version, ("scanned", "converted", "indexed")), (second, ("scanned", "converted", "indexed"))]))
        self.assertEqual(stages.read(self.store, other, other_version)["stages"]["fetched"]["status"], "pending")

    def test_a_book_that_is_named_and_not_there_is_refused_before_anything_is_done(self):
        with self.assertRaises(KbError):
            stages.redo_books(self.store, [self.book, "01ZZZZZZZZZZZZZZZZZZZZZZZZ"], scan=False, reason="r")
        self.assertEqual(self.all_status(), ["done"] * 5)

    def test_a_version_that_cannot_be_read_is_reported_and_the_others_go_on(self):
        book2, version2 = self.new_version()
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, book2, version2, stage, "done")
        with open(self.store.stages_file(self.book, self.version), "w") as f:
            f.write("{not json")
        done = stages.redo_books(self.store, None, scan=False, reason="r")
        errors = [d for d in done if "error" in d]
        self.assertEqual([(e["book_id"], e["version_id"]) for e in errors], [(self.book, self.version)])
        self.assertIn("stage state", errors[0]["error"])
        self.assertIn({"book_id": book2, "version_id": version2, "stages": ["converted", "indexed"]}, done)

    def test_a_second_run_after_a_stop_part_way_finishes_the_rest_and_reports_only_what_it_did(self):
        book2, version2 = self.new_version()
        for stage in ("fetched", "scanned", "converted", "indexed"):
            stages.mark(self.store, book2, version2, stage, "done")
        real = stages.redo
        calls = []

        def stop_on_second(store, book_id, version_id, stage, reason):
            calls.append(version_id)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(store, book_id, version_id, stage, reason)
        with mock.patch.object(stages, "redo", side_effect=stop_on_second):
            with self.assertRaises(KeyboardInterrupt):
                stages.redo_books(self.store, None, scan=False, reason="r")
        again = stages.redo_books(self.store, None, scan=False, reason="r")
        self.assertEqual(len(again), 1)  # one was done before the stop; this run does the other
        self.assertEqual([self.status("converted"), stages.read(self.store, book2, version2)["stages"]["converted"]["status"]],
                         ["pending", "pending"])


class ResumeTest(StoreCase):
    """A payload is promoted and the process stops before the stage is marked done."""

    def setUp(self):
        super().setUp()
        self.book, self.version = self.new_version()
        stages.mark(self.store, self.book, self.version, "fetched", "done")

    def promote_scan_result(self):
        self.store.file_payload(self.book, self.version, "derived/scan/1", {"caveats.json": b"[]"}, tool="scan 1")

    def status(self, stage):
        return stages.read(self.store, self.book, self.version)["stages"][stage]["status"]

    def test_resume_with_no_promoted_payload_says_to_run_the_stage(self):
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "run")
        self.assertEqual(self.status("scanned"), "pending")

    def test_resume_adopts_a_valid_promoted_payload_without_touching_it(self):
        self.promote_scan_result()
        path = self.store.payload_dir(self.book, self.version, "derived/scan/1")
        before = os.stat(path).st_ino, os.listdir(path)
        self.assertEqual(self.status("scanned"), "pending")
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "adopted")
        self.assertEqual(self.status("scanned"), "done")
        entry = stages.read(self.store, self.book, self.version)["stages"]["scanned"]
        self.assertEqual(entry["tool"], "scan 1")
        self.assertEqual((os.stat(path).st_ino, os.listdir(path)), before)
        # nothing was duplicated, and filing the same payload again is still refused
        derived = os.path.join(self.store.version_dir(self.book, self.version), "derived")
        self.assertEqual(os.listdir(os.path.join(derived, "scan")), ["1"])
        with self.assertRaises(KbError):
            self.store.file_payload(self.book, self.version, "derived/scan/1", {"caveats.json": b"[]"})

    def test_resume_after_a_stop_between_the_rename_and_the_version_file_update(self):
        with mock.patch.object(self.store, "_note_payload", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.promote_scan_result()
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "adopted")
        self.assertEqual(self.status("scanned"), "done")

    def test_a_promoted_payload_that_fails_validation_marks_the_stage_failed_and_is_not_adopted(self):
        self.promote_scan_result()
        path = self.store.payload_dir(self.book, self.version, "derived/scan/1")
        os.chmod(path, 0o700)
        os.chmod(os.path.join(path, "caveats.json"), 0o600)
        with open(os.path.join(path, "caveats.json"), "w") as f:
            f.write("tampered")
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "invalid")
        entry = stages.read(self.store, self.book, self.version)["stages"]["scanned"]
        self.assertEqual(entry["status"], "failed")
        self.assertIn("caveats.json", entry["reason"])

    def test_resume_restores_the_version_file_after_a_stop_following_the_rename(self):
        book, version = self.new_version()
        stages.mark(self.store, book, version, "found", "done")
        with mock.patch.object(self.store, "_note_payload", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.store.file_payload(book, version, "original", {"a.txt": b"one"}, primary="a.txt", tool="fetch 1")
        self.assertIsNone(self.store.read_version(book, version)["primary"])
        self.assertEqual(stages.reconcile(self.store, book, version, "fetched", "original"), "adopted")
        v = self.store.read_version(book, version)
        self.assertEqual((v["primary"], list(v["payloads"])), ("a.txt", ["original"]))
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")

    def test_resume_seals_a_payload_whose_folders_were_not_yet_read_only(self):
        with mock.patch("kb.incoming.make_read_only", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.promote_scan_result()
        path = self.store.payload_dir(self.book, self.version, "derived/scan/1")
        self.assertNotEqual(os.stat(path).st_mode & 0o222, 0)
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "adopted")
        self.assertEqual(os.stat(path).st_mode & 0o222, 0)

    def test_a_filed_payload_whose_stage_inputs_are_not_ready_is_left_alone(self):
        self.store.file_payload(self.book, self.version, "derived/text/1", {"t.txt": b"x"}, tool="text 1")
        # converted needs scanned to be done, failed or skipped, and it is still pending
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "converted", "derived/text/1"), "blocked")
        self.assertEqual(self.status("converted"), "pending")

    def test_resume_leaves_a_done_stage_alone(self):
        self.promote_scan_result()
        stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1")
        self.assertEqual(stages.reconcile(self.store, self.book, self.version, "scanned", "derived/scan/1"), "done")


if __name__ == "__main__":
    unittest.main()
