"""The journal of a book in the making: the accepted answer of each piece of the extraction, kept in the index root."""
import copy
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from kb import KbError, cardstate, themeextract, themejournal

BOOK = "01M6SR0ZCZ1P0XFDV3KMEHG1PT"
OTHER = "01M73EX71EM1N3KJC5A05JMX2M"
RECORD = {"model": "gemma4:12b", "registry": "gemma", "prompt_version": "v4", "date": "2026-11-12T10:00:00+00:00",
          "input_tokens": 100, "output_tokens": 20}


def entry(n):
    return {"piece": n, "key": f"{n:064x}", "values": {"titles": [f"theme {n}"], "types": ["method"]}, "record": dict(RECORD)}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.base, "index")
        os.mkdir(self.root, 0o700)

    def path(self, book=BOOK, version="v1"):
        return os.path.join(self.root, cardstate.FOLDER, themejournal.RUN, f"{book}-{version}.json")

    def write(self, count=2):
        themejournal.write(self.root, BOOK, "v1", [entry(n) for n in range(1, count + 1)])

    def doc(self, entries=None):
        return {"format": 1, "book_id": BOOK, "version_id": "v1", "entries": entries if entries is not None else [entry(1), entry(2)]}

    def raw(self, doc, mode=0o600):
        for folder in (os.path.join(self.root, cardstate.FOLDER), os.path.dirname(self.path())):
            if not os.path.isdir(folder):
                os.mkdir(folder, 0o700)
                os.chmod(folder, 0o700)
        with open(self.path(), "w") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))
        os.chmod(self.path(), mode)

    def refused(self, doc=None, mode=0o600):
        self.raw(self.doc() if doc is None else doc, mode)
        with self.assertRaises(KbError):
            themejournal.read(self.root, BOOK, "v1")


class RoundTripTest(Base):
    def test_a_journal_is_written_and_read_back_the_same(self):
        self.write(3)
        self.assertEqual(themejournal.read(self.root, BOOK, "v1"), [entry(1), entry(2), entry(3)])

    def test_a_journal_that_is_not_there_reads_as_none(self):
        self.assertIsNone(themejournal.read(self.root, BOOK, "v1"))
        self.assertIsNone(themejournal.read(self.root, OTHER, "v1"))

    def test_the_file_is_private_and_nothing_else_is_left_in_the_folder(self):
        self.write()
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path())).st_mode), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(self.path())), [f"{BOOK}-v1.json"])

    def test_writing_again_replaces_the_file_whole(self):
        self.write(1)
        self.write(3)
        self.assertEqual(len(themejournal.read(self.root, BOOK, "v1")), 3)
        self.write(1)
        self.assertEqual(len(themejournal.read(self.root, BOOK, "v1")), 1)

    def test_an_empty_journal_can_be_written_and_read(self):
        themejournal.write(self.root, BOOK, "v1", [])
        self.assertEqual(themejournal.read(self.root, BOOK, "v1"), [])

    def test_the_journal_of_one_book_does_not_read_as_the_journal_of_another(self):
        self.write()
        self.assertIsNone(themejournal.read(self.root, OTHER, "v1"))
        self.assertIsNone(themejournal.read(self.root, BOOK, "v2"))

    def test_the_limit_is_the_pieces_one_run_reads(self):
        self.assertEqual(themejournal.MAX_PIECES, themeextract.MAX_PIECES)

    def test_the_file_is_where_the_module_says(self):
        self.write()
        self.assertTrue(os.path.isfile(os.path.join(self.root, "card-runs", "theme-journal", f"{BOOK}-v1.json")))

    def test_the_folder_is_not_a_run_of_the_card_queue_by_its_name(self):
        self.assertRegex(themejournal.RUN, cardstate._RUN.pattern)


class WriteRefusalTest(Base):
    def refuses(self, entries, book=BOOK, version="v1"):
        with self.assertRaises(KbError):
            themejournal.write(self.root, book, version, entries)
        self.assertFalse(os.path.exists(self.path(book, version)))

    def test_a_piece_out_of_order_repeated_or_with_a_gap_is_refused(self):
        self.refuses([entry(2), entry(1)])
        self.refuses([entry(1), entry(1)])
        self.refuses([entry(1), entry(3)])
        self.refuses([entry(2)])
        self.refuses([entry(0)])

    def test_more_pieces_than_one_run_reads_are_refused(self):
        self.refuses([entry(n) for n in range(1, themejournal.MAX_PIECES + 2)])

    def test_exactly_the_limit_is_accepted(self):
        themejournal.write(self.root, BOOK, "v1", [entry(n) for n in range(1, themejournal.MAX_PIECES + 1)])
        self.assertEqual(len(themejournal.read(self.root, BOOK, "v1")), themejournal.MAX_PIECES)

    def test_a_bad_book_or_version_is_refused(self):
        self.refuses([entry(1)], book="../x")
        self.refuses([entry(1)], book="not an id")
        self.refuses([entry(1)], version="1")
        self.refuses([entry(1)], version="v1/../v2")

    def test_values_that_are_not_plain_data_are_refused(self):
        bad = entry(1)
        bad["values"] = {"titles": [object()]}
        self.refuses([bad])
        bad["values"] = {"titles": [float("nan")]}
        self.refuses([bad])
        bad["values"] = ["not", "a", "dict"]
        self.refuses([bad])

    def test_values_that_would_not_read_back_equal_are_refused(self):
        for values in ({"titles": ("a", "b")}, {1: ["a"]}, {1: ["a"], "1": ["b"]}):
            bad = entry(1)
            bad["values"] = values
            self.refuses([bad])

    def test_a_recursion_error_while_writing_is_a_kb_error(self):
        # values nested deeper than the recursion limit raise it on some versions of Python (not on all), so it is raised here
        with mock.patch.object(themejournal.json, "dumps", side_effect=RecursionError):
            with self.assertRaises(KbError):
                themejournal.write(self.root, BOOK, "v1", [entry(1)])
        self.assertFalse(os.path.exists(self.path()))

    def test_an_entry_with_a_wrong_key_or_record_is_refused(self):
        for change in ({"key": "abc"}, {"key": "G" * 64}, {"key": 5}, {"piece": "1"}, {"piece": True}, {"extra": 1}):
            bad = {**entry(1), **change}
            self.refuses([bad])
        missing = entry(1)
        del missing["key"]
        self.refuses([missing])
        for record in (None, {}, {**RECORD, "model": "../x"}, {**RECORD, "date": "2026\n"}, {**RECORD, "input_tokens": -1},
                       {**RECORD, "extra": 1}, {**RECORD, "prompt_version": "v 4"}, {**RECORD, "prompt_version": "v4\n"}):
            bad = {**entry(1), "record": record}
            self.refuses([bad])

    def test_a_journal_larger_than_the_limit_is_refused(self):
        big = entry(1)
        big["values"] = {"titles": ["x" * 1000]}
        with mock.patch.object(cardstate, "MAX_BYTES", 500):
            self.refuses([big])

    def test_a_failed_write_leaves_no_temporary_file_and_keeps_the_earlier_file(self):
        self.write(2)
        with mock.patch("os.rename", side_effect=OSError("no")):
            with self.assertRaises(KbError):
                self.write(3)
        self.assertEqual(os.listdir(os.path.dirname(self.path())), [f"{BOOK}-v1.json"])
        self.assertEqual(len(themejournal.read(self.root, BOOK, "v1")), 2)


class ReadRefusalTest(Base):
    def test_the_good_document_is_read(self):
        self.raw(self.doc())
        self.assertEqual(len(themejournal.read(self.root, BOOK, "v1")), 2)

    def test_a_link_is_refused(self):
        self.raw(self.doc())
        target = os.path.join(self.base, "elsewhere.json")
        os.rename(self.path(), target)
        os.symlink(target, self.path())
        with self.assertRaises(KbError):
            themejournal.read(self.root, BOOK, "v1")

    def test_a_pipe_is_refused(self):
        self.raw(self.doc())
        os.unlink(self.path())
        os.mkfifo(self.path(), 0o600)
        with self.assertRaises(KbError):
            themejournal.read(self.root, BOOK, "v1")

    def test_a_file_that_others_can_read_is_refused(self):
        self.refused(mode=0o644)

    def test_a_file_of_another_user_is_refused(self):
        self.raw(self.doc())
        with mock.patch.object(cardstate.os, "getuid", return_value=os.getuid() + 1):   # the folders are then another user's too
            with self.assertRaises(KbError):
                themejournal.read(self.root, BOOK, "v1")

    def test_a_file_that_is_larger_than_the_limit_is_refused(self):
        self.raw(self.doc())
        with mock.patch.object(cardstate, "MAX_BYTES", 50):
            with self.assertRaises(KbError):
                themejournal.read(self.root, BOOK, "v1")

    def test_text_that_is_not_json_or_not_one_object_is_refused(self):
        self.refused("not json")
        self.refused("[1, 2]")
        self.refused("")

    def test_a_repeated_key_is_refused(self):
        self.refused('{"format": 1, "format": 1, "book_id": "%s", "version_id": "v1", "entries": []}' % BOOK)

    def test_a_key_not_expected_or_a_key_missing_is_refused(self):
        self.refused({**self.doc(), "extra": 1})
        bare = self.doc()
        del bare["entries"]
        self.refused(bare)

    def test_a_format_that_is_not_this_one_is_refused(self):
        self.refused({**self.doc(), "format": 2})
        self.refused({**self.doc(), "format": True})

    def test_a_file_for_another_book_or_version_than_its_name_says_is_refused(self):
        self.refused({**self.doc(), "book_id": OTHER})
        self.refused({**self.doc(), "version_id": "v2"})

    def test_pieces_out_of_order_repeated_or_with_a_gap_are_refused(self):
        self.refused(self.doc([entry(2), entry(1)]))
        self.refused(self.doc([entry(1), entry(1)]))
        self.refused(self.doc([entry(1), entry(3)]))
        self.refused(self.doc([entry(2)]))

    def test_more_pieces_than_the_limit_are_refused(self):
        self.refused(self.doc([entry(n) for n in range(1, themejournal.MAX_PIECES + 2)]))

    def test_an_entry_or_a_record_that_is_not_as_described_is_refused(self):
        self.refused(self.doc([{**entry(1), "key": "short"}]))
        self.refused(self.doc([{**entry(1), "values": []}]))
        self.refused(self.doc([{**entry(1), "record": {**RECORD, "date": "x‮"}}]))
        self.refused(self.doc([{**entry(1), "record": {**RECORD, "model": "a b"}}]))

    def test_entries_that_are_not_a_list_are_refused(self):
        self.refused({**self.doc(), "entries": {"a": 1}})

    def test_a_folder_that_others_can_enter_is_refused(self):
        self.raw(self.doc())
        os.chmod(os.path.dirname(self.path()), 0o755)
        with self.assertRaises(KbError):
            themejournal.read(self.root, BOOK, "v1")

    def test_what_is_read_is_a_copy_the_caller_may_change(self):
        self.write()
        first = themejournal.read(self.root, BOOK, "v1")
        first[0]["values"]["titles"].append("changed")
        self.assertEqual(themejournal.read(self.root, BOOK, "v1"), [entry(1), entry(2)])


class RemoveTest(Base):
    def test_remove_deletes_the_file(self):
        self.write()
        themejournal.remove(self.root, BOOK, "v1")
        self.assertFalse(os.path.exists(self.path()))
        self.assertIsNone(themejournal.read(self.root, BOOK, "v1"))

    def test_remove_with_no_file_or_no_folder_is_not_an_error(self):
        themejournal.remove(self.root, BOOK, "v1")
        self.write()
        themejournal.remove(self.root, OTHER, "v1")
        self.assertTrue(os.path.exists(self.path()))

    def test_remove_also_removes_a_temporary_file_a_crash_left(self):
        self.write()
        stray = os.path.join(os.path.dirname(self.path()), f".{BOOK}-v1.json.abcd1234.tmp")
        open(stray, "w").close()
        themejournal.remove(self.root, BOOK, "v1")
        self.assertEqual(os.listdir(os.path.dirname(self.path())), [])

    def test_remove_keeps_the_journal_of_another_book(self):
        self.write()
        themejournal.write(self.root, OTHER, "v1", [entry(1)])
        themejournal.remove(self.root, BOOK, "v1")
        self.assertEqual(len(themejournal.read(self.root, OTHER, "v1")), 1)


if __name__ == "__main__":
    unittest.main()
