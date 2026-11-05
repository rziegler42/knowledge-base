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
