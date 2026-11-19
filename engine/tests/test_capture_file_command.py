"""The command `kb capture-file` (Increment B of the plan `2026-11-19-load-pdf-files-from-a-folder-into-the-library`): one or more files, or the `.pdf` files directly inside folders, filed as books of the owner's.

The command is run as a child process against a temporary library (the way the tests of `capture-arxiv` do), so the real parser, the lock and the exit codes are tested.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_capture_file_command`."""
import json
import os
import subprocess
import sys
import unittest

from engine.tests import ENGINE_DIR
from engine.tests.test_capture_arxiv import PDF1, PDF2
from engine.tests.test_store import StoreCase

from kb import capture_file


class CommandCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.files = os.path.join(self.base, "owner-folder-xyzzy")
        os.makedirs(self.files)

    def write(self, name, data=PDF1, folder=None):
        path = os.path.join(folder or self.files, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def run_kb(self, *args):
        return subprocess.run([sys.executable, "-m", "kb", "capture-file", *args], cwd=ENGINE_DIR, env=dict(os.environ, KB_CONFIG_DIR=self.cfg),
                              capture_output=True, text=True, timeout=120)

    def lines(self, done):
        """The JSON lines of the output and its last line (the summary text)."""
        rows = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        return rows, done.stdout.splitlines()[-1] if done.stdout.splitlines() else ""

    def books(self):
        return self.store.list_books()


class Folder(CommandCase):
    def test_a_folder_files_its_pdf_files_in_name_order_and_says_what_it_skipped(self):
        self.write("b.pdf", PDF1)
        self.write("a.pdf", PDF2)
        self.write("C.PDF", PDF1 + b"third")
        self.write("notes.txt", b"hello")
        self.write(".DS_Store", b"\x00\x01")
        os.mkdir(os.path.join(self.files, "sub.pdf"))                     # a folder, even one named like a PDF, is not entered
        done = self.run_kb(self.files)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows, summary = self.lines(done)
        self.assertEqual([(r["status"], r["file_name"]) for r in rows if r["status"] != "skipped"], [("filed", "C"), ("filed", "a"), ("filed", "b")])
        self.assertEqual(sorted(r["file_name"] for r in rows if r["status"] == "skipped"), [".DS_Store", "notes.txt", "sub.pdf"])
        self.assertEqual(summary, "filed 3, duplicate 0, refused 0, skipped 3")
        self.assertEqual(len(self.books()), 3)
        self.assertNotIn("owner-folder-xyzzy", done.stdout + done.stderr)

    def test_a_second_run_of_the_same_folder_files_nothing_new(self):
        self.write("a.pdf")
        self.write("b.pdf", PDF2)
        first = self.run_kb(self.files)
        second = self.run_kb(self.files)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.lines(second)[1], "filed 0, duplicate 2, refused 0, skipped 0")
        self.assertEqual(len(self.books()), 2)
        self.assertEqual(self.lines(first)[1], "filed 2, duplicate 0, refused 0, skipped 0")

    def test_two_files_of_the_same_bytes_in_one_run_are_one_book_and_a_duplicate(self):
        self.write("one.pdf")
        self.write("two.pdf")
        done = self.run_kb(self.files)
        rows, summary = self.lines(done)
        self.assertEqual([r["status"] for r in rows], ["filed", "duplicate"])
        self.assertEqual(rows[1]["book_id"], rows[0]["book_id"])
        self.assertEqual(summary, "filed 1, duplicate 1, refused 0, skipped 0")


class Refusals(CommandCase):
    def test_one_refused_file_does_not_stop_the_others_and_the_exit_code_says_so(self):
        self.write("a.pdf")
        self.write("b.pdf", b"not a pdf at all")
        self.write("c.pdf", PDF2)
        done = self.run_kb(self.files)
        self.assertEqual(done.returncode, 1)
        rows, summary = self.lines(done)
        self.assertEqual([(r["status"], r["file_name"]) for r in rows], [("filed", "a"), ("refused", "b"), ("filed", "c")])
        self.assertEqual(summary, "filed 2, duplicate 0, refused 1, skipped 0")
        self.assertIn("refused: b: ", done.stderr)
        self.assertEqual(len(self.books()), 2)

    def test_a_path_that_does_not_exist_is_refused_and_exits_one(self):
        done = self.run_kb(os.path.join(self.files, "missing.pdf"))
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.lines(done)[0][0]["status"], "refused")
        self.assertEqual(self.books(), [])

    def test_a_limit_is_passed_through_and_one_below_one_is_refused_before_any_file(self):
        path = self.write("a.pdf")
        small = self.run_kb("--max-bytes", str(len(PDF1) - 1), path)
        self.assertEqual(small.returncode, 1)
        self.assertEqual(self.lines(small)[0][0]["status"], "refused")
        exact = self.run_kb("--max-bytes", str(len(PDF1)), path)
        self.assertEqual(exact.returncode, 0, exact.stderr)
        self.write("b.pdf", PDF2)
        for bad in ("0", "-5"):
            done = self.run_kb("--max-bytes", bad, os.path.join(self.files, "b.pdf"))
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertTrue(done.stderr.startswith("refused: "), done.stderr)
        self.assertEqual(len(self.books()), 1)

    def test_a_run_started_while_the_lock_is_held_is_refused_and_files_nothing(self):
        path = self.write("a.pdf")
        with capture_file.lock(self.index):
            done = self.run_kb(path)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("another run of capture-file holds the lock", done.stderr)
        self.assertEqual(self.books(), [])
        self.assertEqual(self.run_kb(path).returncode, 0)                    # and the lock is free again after the holder ends

    def test_a_file_name_with_control_and_bidirectional_characters_is_shown_cleaned_and_the_folder_never(self):
        name = "Evil" + chr(0x202e) + " Name" + chr(0x200b) + chr(7) + chr(10) + "line.pdf"
        path = self.write(name)
        done = self.run_kb(path)
        rows, _ = self.lines(done)
        self.assertEqual(rows[0]["file_name"], "Evil Name line")
        for raw in (chr(0x202e), chr(0x200b), chr(7)):
            self.assertNotIn(raw, done.stdout + done.stderr)
        self.assertNotIn("owner-folder-xyzzy", done.stdout + done.stderr)

    def test_the_refusal_line_of_a_file_with_a_bad_name_shows_the_cleaned_name_on_the_standard_error(self):
        name = "Evil" + chr(0x202e) + " Name" + chr(0x200b) + chr(7) + "x.pdf"
        path = self.write(name, b"not a pdf")
        done = self.run_kb(path)
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused: Evil Namex: it does not begin like a PDF", done.stderr)
        for raw in (chr(0x202e), chr(0x200b), chr(7)):
            self.assertNotIn(raw, done.stdout + done.stderr)

    def test_a_folder_that_cannot_be_read_exits_one_with_its_base_name_and_never_its_path(self):
        closed = os.path.join(self.base, "closed-folder-qwerty")
        os.mkdir(closed)
        os.chmod(closed, 0)
        self.addCleanup(os.chmod, closed, 0o700)
        done = self.run_kb(closed)
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused: closed-folder-qwerty: the folder cannot be read", done.stderr)
        self.assertNotIn(self.base, done.stdout + done.stderr)


class Wiring(CommandCase):
    def test_no_path_is_a_usage_error_and_the_command_is_listed(self):
        done = self.run_kb()
        self.assertEqual(done.returncode, 2)
        helped = subprocess.run([sys.executable, "-m", "kb", "--help"], cwd=ENGINE_DIR, env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=60)
        self.assertIn("capture-file", helped.stdout)

    def test_a_file_and_a_folder_in_one_call_are_both_taken_in_the_order_given(self):
        other = os.path.join(self.base, "other-folder")
        os.makedirs(other)
        first = self.write("z.pdf", PDF2, folder=other)
        self.write("a.pdf", PDF1)
        done = self.run_kb(first, self.files)
        rows, _ = self.lines(done)
        self.assertEqual([r["file_name"] for r in rows], ["z", "a"])


if __name__ == "__main__":
    unittest.main()
