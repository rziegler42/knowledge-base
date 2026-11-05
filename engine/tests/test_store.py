import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, config, ids, incoming, library, store


def make_writable(path):
    """Undo the read-only marking so a temporary folder can be removed."""
    for dirpath, dirnames, filenames in os.walk(path):
        os.chmod(dirpath, 0o700)
        for f in filenames:
            p = os.path.join(dirpath, f)
            if not os.path.islink(p):
                os.chmod(p, 0o600)


def read_json(path):
    with open(path) as f:
        return json.load(f)


class StoreCase(unittest.TestCase):
    """A fresh library in a temporary folder, with the config directory taken from the environment."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.addCleanup(make_writable, self.base)
        self.cfg = os.path.join(self.base, "cfg")
        self.bulk = os.path.join(self.base, "bulk")
        self.index = os.path.join(self.base, "index")
        saved = os.environ.get("KB_CONFIG_DIR")
        os.environ["KB_CONFIG_DIR"] = self.cfg
        self.addCleanup(lambda: os.environ.pop("KB_CONFIG_DIR", None) if saved is None
                        else os.environ.__setitem__("KB_CONFIG_DIR", saved))
        self.lib_id = library.setup(self.bulk, self.index, allow_main_disk=True)
        self.store = store.Store.open()

    def new_version(self, **kw):
        book = self.store.create_book(title="A paper", kind="preprint", **kw)
        return book, self.store.add_version(book, label="v1")

    def run_child(self, code):
        """Run code in a child process. The code may kill the child with os._exit, so no cleanup runs."""
        full = "import os, sys\nsys.path.insert(0, %r)\n%s" % (ENGINE_DIR, code)
        return subprocess.run([sys.executable, "-c", full], env=dict(os.environ, KB_CONFIG_DIR=self.cfg),
                              capture_output=True, text=True, timeout=60)


    def run_child_async(self, code):
        """Start code in a child process and return at once, so the test can act on it while it runs."""
        full = "import os, sys\nsys.path.insert(0, %r)\n%s" % (ENGINE_DIR, code)
        return subprocess.Popen([sys.executable, "-c", full], env=dict(os.environ, KB_CONFIG_DIR=self.cfg),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class IdsTest(unittest.TestCase):
    def test_an_id_is_a_26_character_ulid(self):
        i = ids.new_book_id()
        self.assertRegex(i, r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
        ids.check_id(i)

    def test_ids_sort_by_time_and_differ_in_their_random_part(self):
        a = ids.new_book_id(now_ms=1_000_000, rand=5)
        b = ids.new_book_id(now_ms=1_000_001, rand=0)
        self.assertLess(a, b)
        self.assertNotEqual(ids.new_book_id(now_ms=7), ids.new_book_id(now_ms=7))

    def test_bad_ids_are_refused(self):
        for bad in ("", "../x", "a" * 26, "0" * 25, "0" * 27, "I" * 26, "01ARZ3NDEKTSV4RRFFQ69G5FA/", None, 5,
                    ids.new_book_id() + "\n", "\n" + ids.new_book_id()):
            with self.assertRaises(KbError, msg=repr(bad)):
                ids.check_id(bad)

    def test_the_shard_is_the_end_of_the_id_and_the_qualified_form_names_the_library(self):
        i = ids.new_book_id()
        self.assertEqual(ids.shard(i), i[-2:])
        self.assertEqual(ids.qualified("L" * 32, i), "L" * 32 + "/" + i)


class BookTest(StoreCase):
    def test_create_and_read_a_book(self):
        book = self.store.create_book(title="Attention", authors=["A. Author"], year=2017, kind="preprint",
                                      language="en", identity_keys={"arxiv": "1706.03762"}, shelf="ml")
        root = self.store.read_book(book)
        self.assertEqual(root["book_id"], book)
        self.assertEqual(root["library_id"], self.lib_id)
        self.assertEqual((root["title"], root["year"], root["shelf"]), ("Attention", 2017, "ml"))
        self.assertEqual(root["identity_keys"], {"arxiv": "1706.03762"})
        self.assertEqual((root["state"], root["current_version"], root["same_work"]), ("active", None, []))
        self.assertIn(book, self.store.list_books())

    def test_books_are_stored_flat_and_sharded_by_the_end_of_the_id(self):
        book = self.store.create_book(title="t", kind="web page")
        expected = os.path.join(self.bulk, "books", book[-2:], book, "book.json")
        self.assertTrue(os.path.isfile(expected))

    def test_a_shelf_is_a_field_and_changing_it_moves_no_bytes(self):
        book, version = self.new_version()
        before = os.stat(self.store.version_dir(book, version)).st_ino
        self.store.set_shelf(book, "other-shelf")
        self.assertEqual(self.store.read_book(book)["shelf"], "other-shelf")
        self.assertEqual(os.stat(self.store.version_dir(book, version)).st_ino, before)
        with self.assertRaises(KbError):
            self.store.set_shelf(book, "../escape")

    def test_an_unknown_or_malformed_book_id_is_refused_before_any_path_is_built(self):
        for bad in ("../../etc", "x", ""):
            with self.assertRaises(KbError):
                self.store.read_book(bad)
        with self.assertRaises(KbError):
            self.store.read_book(ids.new_book_id())

    def test_a_stored_manifest_holds_no_absolute_path(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", {"a.txt": b"hello"}, primary="a.txt")
        seen = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(k)
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
            elif isinstance(obj, str):
                seen.append(obj)

        count = 0
        for dirpath, _dirs, files in os.walk(os.path.join(self.bulk, "books")):
            for f in files:
                if f.endswith(".json"):
                    count += 1
                    walk(read_json(os.path.join(dirpath, f)))
        self.assertGreaterEqual(count, 4)
        for s in seen:
            self.assertFalse(s.startswith("/"), s)
            self.assertNotIn(self.base, s)

    def test_a_write_is_refused_when_the_write_guard_fails(self):
        os.remove(os.path.join(self.bulk, library.MARKER))
        with self.assertRaises(KbError) as cm:
            self.store.create_book(title="t", kind="web page")
        self.assertIn("marker", str(cm.exception))

    def test_the_manifest_rewrite_leaves_the_old_file_when_the_rename_fails(self):
        book = self.store.create_book(title="t", kind="web page", shelf="one")
        with mock.patch("os.replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.store.set_shelf(book, "two")
        self.assertEqual(self.store.read_book(book)["shelf"], "one")
        folder = os.path.dirname(self.store.book_file(book))
        self.assertEqual([n for n in os.listdir(folder) if ".tmp." in n], [])

    def test_a_killed_manifest_rewrite_leaves_the_old_manifest_intact(self):
        book = self.store.create_book(title="t", kind="web page", shelf="one")
        done = self.run_child(f"""
from unittest import mock
from kb import store
s = store.Store.open()
with mock.patch("os.replace", lambda *a, **k: os._exit(7)):
    s.set_shelf({book!r}, "two")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(self.store.read_book(book)["shelf"], "one")

    def test_a_killed_book_creation_leaves_no_book_visible(self):
        done = self.run_child("""
from unittest import mock
from kb import incoming, store
s = store.Store.open()
with mock.patch.object(incoming, "promote", lambda *a, **k: os._exit(7)):
    s.create_book(title="t", kind="web page")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(self.store.list_books(), [])
        self.assertTrue(os.listdir(os.path.join(self.bulk, "incoming")), "the crash should have left a leftover")


class VersionTest(StoreCase):
    def test_a_version_becomes_current_and_starts_with_its_stage_state(self):
        book = self.store.create_book(title="t", kind="preprint")
        v1 = self.store.add_version(book, label="v1")
        v2 = self.store.add_version(book, label="v2")
        self.assertEqual((v1, v2), ("v1", "v2"))
        self.assertEqual(self.store.read_book(book)["current_version"], "v2")
        self.assertEqual(self.store.read_version(book, "v1")["label"], "v1")
        self.assertTrue(os.path.isfile(os.path.join(self.store.version_dir(book, v1), "stages.json")))

    def test_a_killed_version_creation_leaves_the_old_current_version(self):
        book = self.store.create_book(title="t", kind="preprint")
        self.store.add_version(book, label="v1")
        done = self.run_child(f"""
from unittest import mock
from kb import incoming, store
s = store.Store.open()
with mock.patch.object(incoming, "promote", lambda *a, **k: os._exit(7)):
    s.add_version({book!r}, label="v2")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertEqual(self.store.read_book(book)["current_version"], "v1")
        self.assertEqual(self.store.version_ids(book), ["v1"])

    def test_names_with_a_trailing_newline_are_refused(self):
        book, version = self.new_version()
        with self.assertRaises(KbError):
            self.store.version_dir(book, version + "\n")
        with self.assertRaises(KbError):
            self.store.payload_path(book, version, "original\n")
        with self.assertRaises(KbError):
            self.store.payload_path(book, version, "derived/tool/1\n")
        with self.assertRaises(KbError):
            self.store.set_shelf(book, "shelf\n")

    def test_a_stop_after_the_version_folder_but_before_current_leaves_a_readable_orphan(self):
        book = self.store.create_book(title="t", kind="preprint")
        done = self.run_child(f"""
from unittest import mock
from kb import store
s = store.Store.open()
with mock.patch.object(store.Store, "_rewrite", lambda *a, **k: os._exit(7)):
    s.add_version({book!r}, label="v1")
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertIsNone(self.store.read_book(book)["current_version"])
        self.assertEqual(self.store.version_ids(book), ["v1"])
        self.assertEqual(self.store.read_version(book, "v1")["label"], "v1")  # readable
        self.assertEqual(self.store.add_version(book, label="v2"), "v2")  # no id is reused
        self.assertEqual(self.store.read_book(book)["current_version"], "v2")

    def test_a_version_of_an_unknown_book_is_refused(self):
        with self.assertRaises(KbError):
            self.store.add_version(ids.new_book_id())


class PayloadTest(StoreCase):
    FILES = {"paper.txt": b"the text", "notes/extra.txt": b"more"}

    def test_a_payload_is_filed_with_its_hashes_and_marked_read_only(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", self.FILES, primary="paper.txt", tool="fetch 1")
        path = self.store.payload_dir(book, version, "original")
        manifest = read_json(os.path.join(path, "payload.json"))
        self.assertEqual(set(manifest["files"]), set(self.FILES))
        import hashlib
        self.assertEqual(manifest["files"]["paper.txt"]["sha256"], hashlib.sha256(b"the text").hexdigest())
        self.assertEqual(manifest["tool"], "fetch 1")
        for rel in list(self.FILES) + ["payload.json"]:
            mode = stat.S_IMODE(os.stat(os.path.join(path, rel)).st_mode)
            self.assertEqual(mode & 0o222, 0, f"{rel} is writable")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o222, 0)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(path, "notes")).st_mode) & 0o222, 0)
        with open(os.path.join(path, "paper.txt"), "rb") as f:
            self.assertEqual(f.read(), b"the text")
        v = self.store.read_version(book, version)
        self.assertEqual(v["primary"], "paper.txt")
        self.assertEqual(v["payloads"]["original"]["files"], 2)
        self.store.verify_payload(book, version, "original")

    def test_files_are_already_read_only_when_the_folder_is_renamed_into_place(self):
        """So there is no moment when a visible payload has writable files."""
        book, version = self.new_version()
        with mock.patch.object(incoming, "make_read_only"):
            self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        path = self.store.payload_dir(book, version, "original")
        for name in ("a.txt", "payload.json"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(path, name)).st_mode) & 0o222, 0, name)

    def test_a_second_write_to_a_filed_payload_is_refused_and_changes_nothing(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        with self.assertRaises(KbError) as cm:
            self.store.file_payload(book, version, "original", {"a.txt": b"two"})
        self.assertIn("already filed", str(cm.exception))
        with open(os.path.join(self.store.payload_dir(book, version, "original"), "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"one")

    def test_a_changed_file_fails_the_hash_check(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        path = self.store.payload_dir(book, version, "original")
        os.chmod(path, 0o700)
        os.chmod(os.path.join(path, "a.txt"), 0o600)
        with open(os.path.join(path, "a.txt"), "wb") as f:
            f.write(b"tampered")
        with self.assertRaises(KbError) as cm:
            self.store.verify_payload(book, version, "original")
        self.assertIn("a.txt", str(cm.exception))

    def test_an_extra_or_missing_file_fails_the_hash_check(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        path = self.store.payload_dir(book, version, "original")
        os.chmod(path, 0o700)
        with open(os.path.join(path, "extra.txt"), "w") as f:
            f.write("x")
        with self.assertRaises(KbError):
            self.store.verify_payload(book, version, "original")
        os.remove(os.path.join(path, "extra.txt"))
        os.chmod(os.path.join(path, "a.txt"), 0o600)
        os.remove(os.path.join(path, "a.txt"))
        with self.assertRaises(KbError):
            self.store.verify_payload(book, version, "original")

    def test_unsafe_file_names_are_refused(self):
        book, version = self.new_version()
        for bad in ("../x", "/abs", "a/../b", "", "a\0b", "a\\b", ".", "payload.json", "sub//x"):
            with self.assertRaises(KbError, msg=repr(bad)):
                self.store.file_payload(book, version, "original", {bad: b"x"})
        with self.assertRaises(KbError):
            self.store.file_payload(book, version, "original", {"A.txt": b"x", "a.TXT": b"y"})
        with self.assertRaises(KbError):
            self.store.file_payload(book, version, "original", {})
        with self.assertRaises(KbError):
            self.store.file_payload(book, version, "original", {"a.txt": b"x"}, primary="missing.txt")
        self.assertIsNone(self.store.payload_dir(book, version, "original"))

    def test_unsafe_payload_names_are_refused(self):
        book, version = self.new_version()
        for bad in ("../original", "original/../x", "derived", "derived/tool", "Original", "derived/a/b/c"):
            with self.assertRaises(KbError, msg=repr(bad)):
                self.store.file_payload(book, version, bad, {"a.txt": b"x"})
        self.store.file_payload(book, version, "derived/tool-1/1", {"t.txt": b"x"})

    def test_a_killed_filing_before_verification_leaves_no_payload_and_a_retry_works(self):
        book, version = self.new_version()
        done = self.run_child(f"""
from unittest import mock
from kb import incoming, store
s = store.Store.open()
with mock.patch.object(incoming, "verify_incoming", lambda *a, **k: os._exit(7)):
    s.file_payload({book!r}, {version!r}, "original", {{"a.txt": b"one"}})
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertIsNone(self.store.payload_dir(book, version, "original"))
        self.assertEqual(self.store.read_version(book, version)["payloads"], {})
        self.assertTrue(os.listdir(os.path.join(self.bulk, "incoming")), "the crash should have left a leftover")
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        self.store.verify_payload(book, version, "original")

    def test_a_killed_filing_between_verification_and_the_rename_leaves_no_payload(self):
        book, version = self.new_version()
        done = self.run_child(f"""
from unittest import mock
from kb import incoming, store
s = store.Store.open()
with mock.patch.object(incoming, "promote", lambda *a, **k: os._exit(7)):
    s.file_payload({book!r}, {version!r}, "original", {{"a.txt": b"one"}})
""")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertIsNone(self.store.payload_dir(book, version, "original"))
        self.assertEqual(self.store.read_version(book, version)["payloads"], {})
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})

    def test_a_failure_before_the_rename_cleans_up_its_incoming_folder(self):
        book, version = self.new_version()
        with mock.patch.object(incoming, "verify_incoming", side_effect=KbError("boom")):
            with self.assertRaises(KbError):
                self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        self.assertEqual(os.listdir(os.path.join(self.bulk, "incoming")), [])

    def test_a_leftover_in_the_incoming_area_is_never_returned_as_a_payload_or_a_book(self):
        book, version = self.new_version()
        left = os.path.join(self.bulk, "incoming", "i-left")
        os.makedirs(left)
        with open(os.path.join(left, "a.txt"), "w") as f:
            f.write("half")
        self.assertIsNone(self.store.payload_dir(book, version, "original"))
        self.assertEqual(self.store.list_books(), [book])

    def test_a_crash_after_the_rename_leaves_a_payload_that_adoption_repairs_in_the_version_file(self):
        """The payload is promoted but the version file is not yet updated, so the primary file is not recorded."""
        book, version = self.new_version()
        with mock.patch.object(self.store, "_note_payload", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.store.file_payload(book, version, "original", {"a.txt": b"one", "b.txt": b"two"}, primary="b.txt")
        self.assertEqual(self.store.read_version(book, version)["payloads"], {})
        self.assertIsNone(self.store.read_version(book, version)["primary"])
        self.assertIsNotNone(self.store.payload_dir(book, version, "original"))
        with self.assertRaises(KbError):  # filing it again is refused, so adoption is the way to repair
            self.store.file_payload(book, version, "original", {"a.txt": b"one"}, primary="a.txt")
        self.store.adopt_payload(book, version, "original")
        v = self.store.read_version(book, version)
        self.assertEqual(v["primary"], "b.txt")
        self.assertEqual(v["payloads"]["original"]["files"], 2)
        self.store.adopt_payload(book, version, "original")  # repeating is harmless
        self.assertEqual(self.store.read_version(book, version)["primary"], "b.txt")

    def test_a_stop_before_the_folders_are_marked_read_only_is_repaired_by_adoption(self):
        book, version = self.new_version()
        with mock.patch.object(incoming, "make_read_only", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.store.file_payload(book, version, "original", {"d/a.txt": b"one"})
        path = self.store.payload_dir(book, version, "original")
        self.assertNotEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o222, 0)  # still writable
        self.store.adopt_payload(book, version, "original")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o222, 0)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(path, "d")).st_mode) & 0o222, 0)

    def test_adoption_refuses_a_payload_that_fails_its_check_and_changes_nothing(self):
        book, version = self.new_version()
        self.store.file_payload(book, version, "original", {"a.txt": b"one"})
        path = self.store.payload_dir(book, version, "original")
        os.chmod(path, 0o700)
        os.chmod(os.path.join(path, "a.txt"), 0o600)
        with open(os.path.join(path, "a.txt"), "wb") as f:
            f.write(b"tampered")
        with self.assertRaises(KbError):
            self.store.adopt_payload(book, version, "original")
        with open(os.path.join(path, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"tampered")  # adoption did not repair or rewrite the file

    def test_a_symlinked_payload_folder_is_not_a_payload(self):
        book, version = self.new_version()
        elsewhere = os.path.join(self.base, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(self.store.version_dir(book, version), "original"))
        self.assertIsNone(self.store.payload_dir(book, version, "original"))

    def test_a_symlinked_book_folder_or_shard_is_not_listed(self):
        book = self.store.create_book(title="t", kind="web page")
        shard = os.path.join(self.bulk, "books", book[-2:])
        # a shard folder that is a link to a folder outside the library, holding what looks like a book
        other = ids.new_book_id()
        while other[-2:] == book[-2:]:
            other = ids.new_book_id()
        outside = os.path.join(self.base, "outside")
        os.makedirs(os.path.join(outside, other))
        with open(os.path.join(outside, other, "book.json"), "w") as f:
            f.write("{}")
        os.symlink(outside, os.path.join(self.bulk, "books", other[-2:]))
        # a book folder that is a link, inside a real shard
        linked = ids.new_book_id()
        while linked[-2:] in (book[-2:], other[-2:]):
            linked = ids.new_book_id()
        os.makedirs(os.path.join(self.bulk, "books", linked[-2:]))
        os.symlink(os.path.join(shard, book), os.path.join(self.bulk, "books", linked[-2:], linked))
        self.assertEqual(self.store.list_books(), [book])


if __name__ == "__main__":
    unittest.main()
