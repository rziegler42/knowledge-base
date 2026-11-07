import json
import os
import re
import stat
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the path)

from kb import KbError, refused

BOOK = "01M6SR01QXBXAZ9V8ZHBWPCDAF"
RECORD = {"model": "m1:latest", "registry": "cardm", "prompt_version": "v2", "date": "2026-11-07T18:00:00+00:00",
          "input_tokens": 100, "output_tokens": 50}
REASON = "the answer's topics has more than the 15 items allowed"


class KeepCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.folder = os.path.join(self.root, "refused")

    def keep(self, answer="the answer", book=BOOK, version="v1", job="card", record=None, reason=REASON, root=None):
        return refused.keep(root or self.root, book_id=book, version_id=version, job=job,
                            record=dict(RECORD if record is None else record), reason=reason, answer=answer)

    def files(self):
        return sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []

    def read(self, name):
        with open(os.path.join(self.folder, name), "rb") as f:
            return f.read()


class KeepTest(KeepCase):
    def test_the_answer_is_kept_in_a_file_named_from_checked_parts(self):
        name = self.keep("a list of seventeen topics")
        self.assertRegex(name, r"^%s-v1-card-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.json$" % BOOK)
        self.assertEqual(self.files(), [name])
        doc = json.loads(self.read(name))
        self.assertEqual((doc["format"], doc["untrusted"], doc["book_id"], doc["version_id"], doc["job"]), (1, True, BOOK, "v1", "card"))
        self.assertEqual((doc["registry"], doc["model"], doc["prompt_version"], doc["date"]), ("cardm", "m1:latest", "v2", RECORD["date"]))
        self.assertEqual((doc["input_tokens"], doc["output_tokens"]), (100, 50))
        self.assertEqual((doc["reason"], doc["answer"], doc["answer_cut"]), (REASON, "a list of seventeen topics", False))

    def test_the_file_and_the_folder_are_private(self):
        name = self.keep()
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.folder, name)).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)

    def test_a_control_or_escape_character_in_the_answer_is_escaped_so_a_terminal_cannot_act_on_it(self):
        text = "red \x1b[31m text \x00 ‮ end é"
        name = self.keep(text)
        raw = self.read(name)
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\x1b", raw)
        self.assertNotIn(b"\x00", raw)
        self.assertEqual(json.loads(raw)["answer"], text)

    def test_the_answer_is_bounded(self):
        name = self.keep("x" * (refused.MAX_ANSWER + 5000))
        doc = json.loads(self.read(name))
        self.assertEqual(len(doc["answer"]), refused.MAX_ANSWER)
        self.assertIs(doc["answer_cut"], True)

    def test_the_reason_is_cleaned_and_cut(self):
        name = self.keep(reason="bad \x1b[31m reason " + "r" * 900)
        reason = json.loads(self.read(name))["reason"]
        self.assertNotIn("\x1b", reason)
        self.assertLessEqual(len(reason), 500)

    def test_two_refusals_with_the_same_metadata_keep_two_files_even_if_the_suffix_clashes(self):
        with mock.patch.object(refused, "_stamp", return_value="20261107T180000Z"), \
                mock.patch.object(refused.secrets, "token_hex", side_effect=["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"]):
            first = self.keep("first answer")
            second = self.keep("second answer")
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(json.loads(self.read(first))["answer"], "first answer")
        self.assertEqual(json.loads(self.read(second))["answer"], "second answer")

    def test_a_name_that_always_clashes_gives_up_without_overwriting(self):
        with mock.patch.object(refused, "_stamp", return_value="20261107T180000Z"), \
                mock.patch.object(refused.secrets, "token_hex", return_value="aaaaaaaa"):
            first = self.keep("first answer")
            with self.assertRaises(KbError):
                self.keep("second answer")
        self.assertEqual(self.files(), [first])
        self.assertEqual(json.loads(self.read(first))["answer"], "first answer")

    def test_a_write_that_fails_leaves_no_partial_file_and_does_not_count_toward_the_limit(self):
        for target in ("fsync", "fchmod"):
            with self.subTest(target=target):
                with mock.patch.object(refused.os, target, side_effect=OSError(28, "No space left on device")):
                    with self.assertRaises(KbError) as cm:
                        self.keep("an answer")
                self.assertIn("could not be written", str(cm.exception))
                self.assertEqual(self.files(), [])
        name = self.keep("a later answer")  # the failures left nothing behind, so a later answer is kept as usual
        self.assertEqual(self.files(), [name])

    def test_no_descriptor_is_left_open_after_a_failed_write(self):
        before = len(os.listdir("/dev/fd"))
        for _ in range(5):
            with mock.patch.object(refused.os, "fsync", side_effect=OSError(28, "No space left on device")), \
                    self.assertRaises(KbError):
                self.keep("an answer")
        self.assertLessEqual(len(os.listdir("/dev/fd")), before)

    def test_no_descriptor_is_left_open_when_the_stream_cannot_be_made(self):
        before = len(os.listdir("/dev/fd"))
        for _ in range(5):
            with mock.patch.object(refused.os, "fdopen", side_effect=OSError(24, "Too many open files")), self.assertRaises(KbError):
                self.keep("an answer")
        self.assertLessEqual(len(os.listdir("/dev/fd")), before)
        self.assertEqual(self.files(), [])

    def test_the_number_of_files_is_limited_and_nothing_is_deleted(self):
        os.mkdir(self.folder, 0o700)
        for i in range(refused.MAX_FILES - 1):
            with open(os.path.join(self.folder, f"old-{i}.json"), "w") as f:
                f.write("{}")
        self.keep()
        self.assertEqual(len(self.files()), refused.MAX_FILES)
        with self.assertRaises(KbError) as cm:
            self.keep()
        self.assertIn(str(refused.MAX_FILES), str(cm.exception))
        self.assertEqual(len(self.files()), refused.MAX_FILES)

    def test_the_parts_of_the_name_are_checked(self):
        for kwargs in ({"book": "../x"}, {"book": "short"}, {"book": BOOK + "\n"}, {"version": "v1/../x"}, {"version": "1"},
                       {"job": "Card"}, {"job": "-x"}, {"job": "a/b"}, {"job": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(KbError):
                self.keep(**kwargs)
        self.assertEqual(self.files(), [])

    def test_an_answer_that_is_not_text_is_refused(self):
        for bad in (None, b"bytes", 5, ["a"]):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                self.keep(answer=bad)

    def test_a_record_that_is_not_in_the_expected_form_is_refused(self):
        for bad in ({}, dict(RECORD, extra=1), dict(RECORD, input_tokens="5"), dict(RECORD, model=5), dict(RECORD, date=None)):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                self.keep(record=bad)
        self.assertEqual(self.files(), [])


class UnsafePlaceTest(KeepCase):
    def test_a_folder_that_is_a_link_is_refused_and_nothing_is_written_through_it(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        os.mkdir(elsewhere, 0o700)
        os.symlink(elsewhere, self.folder)
        with self.assertRaises(KbError):
            self.keep()
        self.assertEqual(os.listdir(elsewhere), [])

    def test_a_folder_that_is_a_file_is_refused(self):
        with open(self.folder, "w") as f:
            f.write("x")
        with self.assertRaises(KbError):
            self.keep()

    def test_a_folder_that_others_can_enter_is_refused(self):
        for mode in (0o755, 0o750, 0o770, 0o701):
            os.mkdir(self.folder)
            os.chmod(self.folder, mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(KbError):
                self.keep()
            self.assertEqual(os.listdir(self.folder), [])
            os.rmdir(self.folder)

    def test_a_folder_the_user_made_private_is_used(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o700)
        self.assertEqual(len(self.files()), 0)
        self.keep()
        self.assertEqual(len(self.files()), 1)

    def test_an_index_root_that_is_a_link_or_missing_is_refused(self):
        real = os.path.join(self.root, "real")
        os.mkdir(real)
        link = os.path.join(self.root, "link")
        os.symlink(real, link)
        with self.assertRaises(KbError):
            self.keep(root=link)
        self.assertEqual(os.listdir(real), [])
        with self.assertRaises(KbError):
            self.keep(root=os.path.join(self.root, "missing"))

    def test_a_file_that_appears_as_a_link_in_place_of_the_new_name_is_not_followed(self):
        os.mkdir(self.folder, 0o700)
        target = os.path.join(self.root, "target.txt")
        with open(target, "w") as f:
            f.write("keep me")
        with mock.patch.object(refused, "_stamp", return_value="20261107T180000Z"), \
                mock.patch.object(refused.secrets, "token_hex", side_effect=["aaaaaaaa", "bbbbbbbb"]):
            os.symlink(target, os.path.join(self.folder, f"{BOOK}-v1-card-20261107T180000Z-aaaaaaaa.json"))
            name = self.keep()
        with open(target) as f:
            self.assertEqual(f.read(), "keep me")
        self.assertTrue(name.endswith("bbbbbbbb.json"))


if __name__ == "__main__":
    unittest.main()
