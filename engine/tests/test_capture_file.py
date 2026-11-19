"""The capture of a PDF file from the owner's disk (`kb/capture_file.py`, Increment A of the plan `2026-11-19-load-pdf-files-from-a-folder-into-the-library`).

A file is read as bytes and stored; it is never parsed. The duplicate rule is an atomic claim of the content hash in the identity index. These tests run against a temporary library and
fixture files; nothing here touches the network or the owner's library.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_capture_file`."""
import errno
import hashlib
import json
import os
import types
import unittest
from unittest import mock

from engine.tests.test_capture_arxiv import PDF1, PDF2
from engine.tests.test_store import StoreCase

from kb import KbError, capture_file, identity, ids, stages, textutil

HEADER_ONLY = b"%PDF-"


class FileCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.ident = identity.Identity(self.index)
        self.files = os.path.join(self.base, "owner-folder-xyzzy")
        os.makedirs(self.files)

    def write(self, name, data=PDF1):
        path = os.path.join(self.files, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def capture(self, path, **kw):
        return capture_file.capture(self.store, self.ident, path, **kw)

    def active(self):
        return [b for b in self.store.list_books() if self.store.read_book(b)["state"] == "active"]

    def digest(self, data=PDF1):
        return hashlib.sha256(data).hexdigest()


class Filing(FileCase):
    def test_a_pdf_file_is_a_book_of_the_owners_with_the_file_filed_byte_for_byte_and_its_hash_as_a_key(self):
        path = self.write("Academic Press - Power Electronics Handbook.pdf")
        out = self.capture(path)
        self.assertEqual(out["status"], "filed")
        book, version = out["book_id"], out["version_id"]
        root = self.store.read_book(book)
        self.assertEqual((root["kind"], root["shelf"], root["auto_filed"], root["state"]), ("paper", "default", False, "active"))
        self.assertEqual(root["title"], "Academic Press - Power Electronics Handbook")
        self.assertEqual(root["identity_keys"], {"sha256": [self.digest()]})
        filed = os.path.join(self.store.payload_path(book, version, "original"), "paper.pdf")
        with open(filed, "rb") as f:
            self.assertEqual(f.read(), PDF1)
        self.assertIn("filed", [e["event"] for e in self.store.read_events(book)])
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertEqual(self.ident.lookup("sha256", self.digest()), book)
        source = self.store.read_version(book, version)["source"]
        self.assertEqual((source["file_name"], source["sha256"], source["bytes"]), ("Academic Press - Power Electronics Handbook", self.digest(), len(PDF1)))

    def test_the_same_bytes_under_another_name_are_a_duplicate_of_the_first_book_and_make_no_book(self):
        first = self.capture(self.write("one.pdf"))
        again = self.capture(self.write("two.pdf"))
        self.assertEqual((again["status"], again["book_id"]), ("duplicate", first["book_id"]))
        self.assertEqual(self.store.list_books(), [first["book_id"]])

    def test_an_entry_of_the_index_that_names_a_book_that_does_not_exist_is_taken_over(self):
        self.ident.register("sha256", self.digest(), ids.new_book_id())
        out = self.capture(self.write("a.pdf"))
        self.assertEqual(out["status"], "filed")
        self.assertEqual(self.ident.lookup("sha256", self.digest()), out["book_id"])

    def test_a_holder_that_is_weeded_is_taken_over_and_the_next_call_is_a_duplicate_of_the_new_book(self):
        old = self.capture(self.write("a.pdf"))["book_id"]
        self.store.set_state(old, "weeded")
        new = self.capture(self.write("b.pdf"))
        self.assertEqual(new["status"], "filed")
        self.assertNotEqual(new["book_id"], old)
        self.assertEqual(self.ident.lookup("sha256", self.digest()), new["book_id"])
        again = self.capture(self.write("c.pdf"))
        self.assertEqual((again["status"], again["book_id"]), ("duplicate", new["book_id"]))

    def test_a_live_book_with_the_hash_whose_stage_fetched_is_not_done_is_finished_and_no_second_book_is_made(self):
        book = self.store.create_book(title="half", kind="paper", identity_keys={"sha256": [self.digest()]})
        self.ident.register("sha256", self.digest(), book)
        out = self.capture(self.write("a.pdf"))
        self.assertEqual((out["status"], out["book_id"]), ("filed", book))
        self.assertEqual(self.store.list_books(), [book])
        filed = os.path.join(self.store.payload_path(book, out["version_id"], "original"), "paper.pdf")
        with open(filed, "rb") as f:
            self.assertEqual(f.read(), PDF1)
        self.assertEqual(stages.read(self.store, book, out["version_id"])["stages"]["fetched"]["status"], "done")
        self.assertEqual(self.capture(self.write("b.pdf"))["status"], "duplicate")

    def test_an_unfinished_book_of_the_crawls_is_never_written_into_and_the_file_is_a_duplicate_of_it(self):
        book = self.store.create_book(title="crawl", kind="paper", identity_keys={"sha256": [self.digest()]}, auto_filed=True)
        self.ident.register("sha256", self.digest(), book)
        out = self.capture(self.write("a.pdf"))
        self.assertEqual((out["status"], out["book_id"]), ("duplicate", book))
        self.assertIsNone(self.store.read_book(book)["current_version"])
        self.assertEqual(self.store.list_books(), [book])

    def test_an_unfinished_book_that_another_capture_made_is_not_written_into_and_keeps_its_source(self):
        d = self.digest()
        # each rule alone: another kind with no other key, a url key on a paper, an arxiv key on a paper, and a preprint with both
        for kind, keys in (("web page", {"sha256": [d]}), ("paper", {"url": "http://a.test/y", "sha256": [d]}), ("paper", {"arxiv": "2101.00002", "sha256": [d]}),
                           ("preprint", {"arxiv": "2101.00001", "sha256": [d]})):
            with self.subTest(kind=kind, keys=sorted(keys)):
                book = self.store.create_book(title="other " + kind, kind=kind, identity_keys=keys)
                version = self.store.add_version(book, source={"address_asked": "http://a.test/x", "note": "keep me"})
                self.ident.reassign("sha256", self.digest(), book)
                out = self.capture(self.write(kind.replace(" ", "") + "-".join(sorted(keys)) + ".pdf"))
                self.assertEqual((out["status"], out["book_id"]), ("duplicate", book))
                self.assertEqual(self.store.read_version(book, version)["source"], {"address_asked": "http://a.test/x", "note": "keep me"})
                self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "pending")

    def test_a_payload_filed_by_an_earlier_try_with_other_bytes_is_refused_and_not_marked_done(self):
        book = self.store.create_book(title="odd", kind="paper", identity_keys={"sha256": [self.digest()]})
        version = self.store.add_version(book, source={"file_name": "odd"})
        self.store.file_payload(book, version, "original", {"paper.pdf": PDF2}, primary="paper.pdf", tool="x")       # a payload that is not the bytes of the hash
        self.ident.reassign("sha256", self.digest(), book)
        out = self.capture(self.write("a.pdf"))
        self.assertEqual(out["status"], "refused")
        self.assertEqual(self.store.list_books(), [book])
        self.assertNotEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertEqual([e["event"] for e in self.store.read_events(book)].count("filed"), 0)
        self.assertEqual(self.store.read_version(book, version)["source"], {"file_name": "odd"})                    # the source is not overwritten with this file's hash

    def test_a_stop_between_the_event_and_the_stage_of_an_adopted_payload_loses_nothing(self):
        book = self.store.create_book(title="half", kind="paper", identity_keys={"sha256": [self.digest()]})
        version = self.store.add_version(book, source={"file_name": "half"})
        self.store.file_payload(book, version, "original", {"paper.pdf": PDF1}, primary="paper.pdf", tool="capture-file")
        self.ident.register("sha256", self.digest(), book)
        real, once = type(self.store).append_event, []

        def fail_once(this, *a, **k):
            if not once:
                once.append(1)
                raise KbError("disk gone")
            return real(this, *a, **k)

        with mock.patch.object(type(self.store), "append_event", fail_once):
            with self.assertRaises(KbError):
                self.capture(self.write("a.pdf"))
        self.assertNotEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")        # not finished, so the next run finishes it
        out = self.capture(self.write("b.pdf"))
        self.assertEqual((out["status"], out["book_id"]), ("filed", book))
        self.assertEqual([e["event"] for e in self.store.read_events(book)].count("filed"), 1)
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")

    def test_a_pipe_in_the_place_of_an_earlier_payload_does_not_hang_and_is_not_adopted(self):
        import signal
        book = self.store.create_book(title="odd", kind="paper", identity_keys={"sha256": [self.digest()]})
        version = self.store.add_version(book, source={"file_name": "odd"})
        folder = self.store.payload_path(book, version, "original")
        os.makedirs(folder)
        os.mkfifo(os.path.join(folder, "paper.pdf"))
        self.ident.reassign("sha256", self.digest(), book)
        signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(AssertionError("the capture hangs on a pipe")))
        signal.alarm(10)
        try:
            try:
                out = self.capture(self.write("a.pdf"))
                self.assertEqual(out["status"], "refused")
            except KbError:
                pass                                                             # a refusal by the store (the payload is already there) is as good
        finally:
            signal.alarm(0)
        self.assertNotEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")

    def test_a_book_whose_stages_cannot_be_read_makes_the_file_refused_and_nothing_else(self):
        out = self.capture(self.write("a.pdf"))
        with mock.patch.object(stages, "read", side_effect=KbError("bad stages")):
            again = self.capture(self.write("b.pdf"))
        self.assertEqual(again["status"], "refused")
        self.assertEqual(self.store.list_books(), [out["book_id"]])

    def test_a_book_that_had_its_payload_filed_before_a_stop_is_adopted_and_finished_not_filed_twice(self):
        book = self.store.create_book(title="half", kind="paper", identity_keys={"sha256": [self.digest()]})
        version = self.store.add_version(book, source={"file_name": "half", "sha256": self.digest(), "bytes": len(PDF1), "retrieved": "2026-11-19T00:00:00Z"})
        self.store.file_payload(book, version, "original", {"paper.pdf": PDF1}, primary="paper.pdf", tool="capture-file")
        self.ident.register("sha256", self.digest(), book)
        self.assertNotEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        out = self.capture(self.write("a.pdf"))
        self.assertEqual((out["status"], out["book_id"], out["version_id"]), ("filed", book, version))
        self.assertEqual(self.store.list_books(), [book])
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertEqual([e["event"] for e in self.store.read_events(book)].count("filed"), 1)
        self.assertEqual(self.capture(self.write("b.pdf"))["status"], "duplicate")


class Refusals(FileCase):
    def refused(self, path, **kw):
        out = self.capture(path, **kw)
        self.assertEqual(out["status"], "refused", out)
        self.assertEqual(self.store.list_books(), [])
        self.assertIsNone(self.ident.lookup("sha256", self.digest()))
        return out

    def test_what_does_not_begin_with_the_pdf_header_is_refused_and_a_bare_header_is_filed(self):
        for name, data in (("short", b"%PDF"), ("empty", b""), ("text", b"hello there"), ("other", b"%PDX-1.4 x"), ("space", b" %PDF-1.4")):
            self.assertEqual(self.capture(self.write(name + ".pdf", data))["status"], "refused", name)
        self.assertEqual(self.store.list_books(), [])
        self.assertEqual(self.capture(self.write("bare.pdf", HEADER_ONLY))["status"], "filed")      # only the header is checked here; the scan and the converter say what the file is

    def test_a_file_one_byte_over_the_limit_is_refused_and_one_at_the_limit_is_filed(self):
        path = self.write("a.pdf")
        self.refused(path, max_bytes=len(PDF1) - 1)
        self.assertEqual(self.capture(path, max_bytes=len(PDF1))["status"], "filed")

    def test_a_link_a_directory_a_pipe_and_a_missing_path_are_refused_without_a_hang(self):
        real = self.write("real.pdf")
        link = os.path.join(self.files, "link.pdf")
        os.symlink(real, link)
        self.refused(link)
        folder = os.path.join(self.files, "folder.pdf")
        os.mkdir(folder)
        self.assertEqual(self.refused(folder)["reason"], "it is not a regular file")
        pipe = os.path.join(self.files, "pipe.pdf")
        os.mkfifo(pipe)
        self.assertEqual(self.refused(pipe)["reason"], "it is not a regular file")
        self.refused(os.path.join(self.files, "missing.pdf"))

    def test_a_file_that_grew_after_the_size_was_read_is_refused_by_the_read_and_the_read_is_bounded(self):
        path = self.write("a.pdf", PDF1 + b"x" * 5000)
        real = os.fstat
        reads = []
        real_read = os.read

        def small(fd):
            info = real(fd)
            return types.SimpleNamespace(st_mode=info.st_mode, st_size=10)          # the size the file had before it grew

        def spy(fd, n):
            reads.append(n)
            return real_read(fd, n)

        with mock.patch.object(os, "fstat", small), mock.patch.object(os, "read", spy):
            out = self.refused(path, max_bytes=1000)
        self.assertIn("larger", out["reason"])
        self.assertTrue(reads and sum(reads) <= 1001, reads)

    def test_a_file_larger_than_the_limit_is_refused_by_its_size_before_any_read(self):
        path = self.write("a.pdf", PDF1 + b"x" * 5000)
        reads = []
        real_read = os.read
        with mock.patch.object(os, "read", lambda fd, n: reads.append(n) or real_read(fd, n)):
            self.refused(path, max_bytes=1000)
        self.assertEqual(reads, [])

    def test_a_path_with_a_nul_byte_is_refused_and_a_path_of_bytes_is_taken(self):
        self.assertEqual(self.capture(os.path.join(self.files, "a\x00b.pdf"))["status"], "refused")
        path = self.write("c.pdf")
        self.assertEqual(self.capture(os.fsencode(path))["status"], "filed")

    def test_the_file_is_opened_without_following_a_link(self):
        path = self.write("a.pdf")
        flags = []
        real_open = os.open

        def spy(p, f, *a, **k):
            if p == path:
                flags.append(f)
            return real_open(p, f, *a, **k)

        with mock.patch.object(os, "open", spy):
            self.capture(path)
        self.assertTrue(flags and all(f & os.O_NOFOLLOW and f & os.O_NONBLOCK and f & os.O_NOCTTY for f in flags), flags)

    def test_a_limit_that_is_not_a_positive_whole_number_is_refused(self):
        path = self.write("a.pdf")
        for bad in (0, -1, 1.5, "10", None, True):
            with self.assertRaises(KbError):
                self.capture(path, max_bytes=bad)


class Names(FileCase):
    def test_a_name_with_control_bidirectional_and_zero_width_characters_is_one_cleaned_form_everywhere(self):
        name = "Evil" + chr(0x202e) + " Name" + chr(0x200b) + chr(7) + chr(10) + "line.pdf"
        out = self.capture(self.write(name))
        self.assertEqual(out["status"], "filed")
        root = self.store.read_book(out["book_id"])
        source = self.store.read_version(out["book_id"], out["version_id"])["source"]
        self.assertEqual((root["title"], source["file_name"]), ("Evil Name line", "Evil Name line"))
        self.assertEqual(out["file_name"], "Evil Name line")
        filed = [e for e in self.store.read_events(out["book_id"]) if e["event"] == "filed"]
        self.assertEqual([e["file_name"] for e in filed], ["Evil Name line"])
        text = self.everything(out["book_id"])
        for raw in (chr(0x202e), chr(0x200b), "\\u202e", "\\u200b", "\\u0007", "\\n"):       # (the writer escapes non-ASCII characters, so the escaped forms are searched as well)
            self.assertNotIn(raw, text)

    def test_a_name_longer_than_two_hundred_characters_is_cut_to_two_hundred(self):
        out = self.capture(self.write("x" * 240 + ".pdf"))                           # (the file system allows 255 bytes)
        self.assertEqual(len(self.store.read_version(out["book_id"], out["version_id"])["source"]["file_name"]), 200)
        self.assertEqual(len(out["file_name"]), 200)

    def test_an_upper_case_extension_is_taken_off_and_a_name_that_is_only_the_extension_is_untitled(self):
        self.assertEqual(self.capture(self.write("UPPER.PDF"))["file_name"], "UPPER")
        self.assertEqual(self.capture(self.write(".pdf", PDF2))["file_name"], "untitled")

    def test_a_name_that_spells_the_marker_words_keeps_its_name_and_the_store_blanks_the_title(self):
        out = self.capture(self.write("untrusted text.pdf"))
        self.assertEqual(out["file_name"], "untrusted text")
        self.assertEqual(self.store.read_book(out["book_id"])["title"], "")                    # the store's own guard; the name of the file is kept in the source

    def test_no_folder_name_is_stored_anywhere_in_the_book(self):
        out = self.capture(self.write("a.pdf"))
        self.assertNotIn("owner-folder-xyzzy", self.everything(out["book_id"]))
        self.assertNotIn("owner-folder-xyzzy", json.dumps(out))

    def everything(self, book):
        """Every text file of the book's folder (root, versions, events), as one string."""
        out = []
        for here, _, names in os.walk(self.store.book_dir(book)):
            for n in names:
                if n.endswith((".json", ".jsonl")):
                    with open(os.path.join(here, n), encoding="utf-8") as f:
                        out.append(f.read())
        return "\n".join(out)


class Interruptions(FileCase):
    POINTS = ("add_version", "file_payload", "append_event")

    def test_an_error_after_the_book_is_made_leaves_no_active_book_and_the_next_run_files_the_file_once(self):
        for point in self.POINTS:
            with self.subTest(point=point):
                path = self.write(f"{point}.pdf", PDF1 + point.encode())
                before = set(self.active())
                with mock.patch.object(type(self.store), point, side_effect=KbError("disk gone")):
                    with self.assertRaises(KbError):
                        self.capture(path)
                self.assertEqual(set(self.active()), before)
                out = self.capture(path)
                self.assertEqual(out["status"], "filed")
                self.assertEqual(set(self.active()), before | {out["book_id"]})
                self.assertEqual(self.capture(path)["status"], "duplicate")

    def test_an_error_at_the_claim_leaves_no_active_book_and_the_next_run_files_the_file(self):
        for target, point in ((identity.Identity, "register"), (identity.Identity, "lookup")):
            with self.subTest(point=point):
                path = self.write(f"{point}.pdf", PDF1 + point.encode())
                before = set(self.active())
                calls = []
                real = getattr(target, point)

                def flaky(this, *a, _real=real, _calls=calls, **k):
                    _calls.append(1)
                    if len(_calls) == (2 if point == "lookup" else 1):
                        raise KbError("index gone")
                    return _real(this, *a, **k)

                with mock.patch.object(target, point, flaky):
                    with self.assertRaises(KbError):
                        self.capture(path)
                self.assertEqual(set(self.active()), before)
                self.assertEqual(self.capture(path)["status"], "filed")

    def test_a_stop_by_the_owner_at_each_step_leaves_no_active_book(self):
        for point in ("add_version", "append_event"):
            with self.subTest(point=point):
                path = self.write(f"{point}.pdf", PDF1 + b"stop" + point.encode())
                before = set(self.active())
                real, once = getattr(type(self.store), point), []

                def stop_once(this, *a, _real=real, _once=once, **k):
                    if not _once:                                       # a stop happens once: the cleanup that follows is not stopped again
                        _once.append(1)
                        raise KeyboardInterrupt
                    return _real(this, *a, **k)

                with mock.patch.object(type(self.store), point, stop_once):
                    with self.assertRaises(KeyboardInterrupt):
                        self.capture(path)
                self.assertEqual(set(self.active()), before)
                self.assertEqual(self.capture(path)["status"], "filed")

    def test_a_full_disk_while_weeding_still_sets_the_book_aside(self):
        path = self.write("a.pdf")
        with mock.patch.object(type(self.store), "file_payload", side_effect=KbError("x")), \
                mock.patch.object(type(self.store), "append_event", side_effect=OSError(errno.ENOSPC, "no space")):
            with self.assertRaises(KbError):
                self.capture(path)
        self.assertEqual(self.active(), [])

    def test_an_error_in_the_stage_leaves_no_active_book(self):
        path = self.write("a.pdf")
        with mock.patch.object(stages, "mark", side_effect=KbError("no")):
            with self.assertRaises(KbError):
                self.capture(path)
        self.assertEqual(self.active(), [])
        self.assertEqual(self.capture(path)["status"], "filed")

    def test_a_stop_by_the_owner_after_the_book_is_made_also_leaves_no_active_book(self):
        path = self.write("a.pdf")
        with mock.patch.object(type(self.store), "file_payload", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.capture(path)
        self.assertEqual(self.active(), [])
        self.assertEqual(self.capture(path)["status"], "filed")

    def test_after_a_failure_the_first_run_owns_the_key_and_the_next_is_a_duplicate_of_it(self):
        path = self.write("a.pdf")
        with mock.patch.object(type(self.store), "file_payload", side_effect=KbError("x")):
            with self.assertRaises(KbError):
                self.capture(path)
        first = self.capture(path)
        second = self.capture(self.write("b.pdf"))
        self.assertEqual((first["status"], second["status"], second["book_id"]), ("filed", "duplicate", first["book_id"]))
        self.assertEqual(self.ident.lookup("sha256", self.digest()), first["book_id"])


class Claims(FileCase):
    def test_a_claim_made_by_another_between_the_book_and_the_claim_wins_and_this_book_is_weeded(self):
        rival = []

        def hook(step):
            if step == "made":
                book = self.store.create_book(title="rival", kind="paper", identity_keys={"sha256": [self.digest()]})
                self.ident.register("sha256", self.digest(), book)
                rival.append(book)

        out = self.capture(self.write("a.pdf"), step_hook=hook)
        self.assertEqual((out["status"], out["book_id"]), ("duplicate", rival[0]))
        mine = [b for b in self.store.list_books() if b != rival[0]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(self.store.read_book(mine[0])["state"], "weeded")
        self.assertIn("capture_failed", [e["event"] for e in self.store.read_events(mine[0])])
        self.assertEqual(self.ident.lookup("sha256", self.digest()), rival[0])

    def test_a_claim_by_another_that_names_a_book_that_does_not_exist_is_taken_over(self):
        def hook(step):
            if step == "made":
                self.ident.register("sha256", self.digest(), ids.new_book_id())

        out = self.capture(self.write("a.pdf"), step_hook=hook)
        self.assertEqual(out["status"], "filed")
        self.assertEqual(self.ident.lookup("sha256", self.digest()), out["book_id"])
        self.assertEqual(self.active(), [out["book_id"]])

    def test_once_claimed_the_book_is_a_live_book_of_the_owners_that_a_second_capture_finds(self):
        seen = []

        def hook(step):
            if step == "claimed":
                holder = self.ident.lookup("sha256", self.digest())
                seen.append((holder, self.store.read_book(holder)["state"], self.store.read_book(holder)["auto_filed"]))

        out = self.capture(self.write("a.pdf"), step_hook=hook)
        self.assertEqual(seen, [(out["book_id"], "active", False)])


class Load(FileCase):
    def test_an_error_of_the_store_or_the_file_system_for_one_file_is_a_refusal_of_that_file_and_the_next_is_taken(self):
        paths = [self.write(f"{n}.pdf", PDF1 + n.encode()) for n in ("a", "b", "c", "d")]
        real = capture_file.capture

        def flaky(store, ident, path, **kw):
            if path.endswith("b.pdf"):
                raise KbError("the store is unhappy\x07 with it")
            if path.endswith("c.pdf"):
                raise OSError(errno.EIO, "input output error")
            return real(store, ident, path, **kw)

        with mock.patch.object(capture_file, "capture", flaky):
            rows = list(capture_file.load(self.store, self.ident, [self.files]))
        self.assertEqual([(r["status"], r["file_name"]) for r in rows], [("filed", "a"), ("refused", "b"), ("refused", "c"), ("filed", "d")])
        self.assertEqual(rows[1]["reason"], "the store is unhappy with it")                      # cleaned of the control character
        self.assertIn("input output error", rows[2]["reason"])
        self.assertEqual(len(self.active()), 2)
        self.assertTrue(paths)

    def test_an_error_of_any_other_kind_for_one_file_is_a_refusal_too_but_a_stop_ends_the_run(self):
        import sqlite3
        self.write("a.pdf", PDF1 + b"a")
        self.write("b.pdf", PDF1 + b"b")
        real = capture_file.capture

        def flaky(store, ident, path, **kw):
            if path.endswith("a.pdf"):
                raise sqlite3.OperationalError("database is locked")
            return real(store, ident, path, **kw)

        with mock.patch.object(capture_file, "capture", flaky):
            rows = list(capture_file.load(self.store, self.ident, [self.files]))
        self.assertEqual([(r["status"], r["file_name"]) for r in rows], [("refused", "a"), ("filed", "b")])
        self.assertIn("database is locked", rows[0]["reason"])
        with mock.patch.object(capture_file, "capture", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                list(capture_file.load(self.store, self.ident, [self.files]))

    def test_links_in_a_folder_are_refused_and_named_and_a_folder_given_as_a_link_is_followed(self):
        real = self.write("real.pdf")
        os.symlink(real, os.path.join(self.files, "link.pdf"))
        os.symlink(self.files, os.path.join(self.files, "folderlink.pdf"))
        os.symlink(self.files, os.path.join(self.files, "folderlink"))
        rows = list(capture_file.load(self.store, self.ident, [self.files]))
        self.assertEqual([(r["status"], r["file_name"]) for r in rows], [("skipped", "folderlink"), ("refused", "folderlink"), ("refused", "link"), ("filed", "real")])
        outer = os.path.join(self.base, "outer-link")
        os.symlink(self.files, outer)
        again = list(capture_file.load(self.store, self.ident, [outer]))
        self.assertEqual([r["status"] for r in again if r["file_name"] == "real"], ["duplicate"])

    def test_a_skipped_entry_is_shown_cleaned_and_a_name_that_cleans_to_nothing_is_untitled(self):
        self.write("Bad" + chr(0x202e) + chr(7) + "name.txt", b"x")
        self.write(chr(0x200b), b"x")
        rows = list(capture_file.load(self.store, self.ident, [self.files]))
        self.assertEqual(sorted((r["status"], r["file_name"]) for r in rows), [("skipped", "Badname.txt"), ("skipped", "untitled")])

    def test_a_folder_that_cannot_be_read_is_one_refusal_with_its_cleaned_base_name_and_the_other_paths_are_taken(self):
        closed = os.path.join(self.base, "closed-folder-qwerty")
        os.mkdir(closed)
        path = self.write("a.pdf")
        os.chmod(closed, 0)
        self.addCleanup(os.chmod, closed, 0o700)
        rows = list(capture_file.load(self.store, self.ident, [closed, path]))
        self.assertEqual([(r["status"], r["file_name"]) for r in rows], [("refused", "closed-folder-qwerty"), ("filed", "a")])
        self.assertNotIn(self.base, json.dumps(rows))

    def test_the_limit_is_checked_before_any_file_is_looked_at(self):
        self.write("a.pdf")
        for bad in (0, -1, 1.5, None):
            with self.assertRaises(KbError):
                list(capture_file.load(self.store, self.ident, [self.files], max_bytes=bad))
        self.assertEqual(self.active(), [])


class Lock(FileCase):
    def test_a_second_holder_is_refused_and_the_lock_is_free_after_a_run_and_after_an_error(self):
        with capture_file.lock(self.index):
            with self.assertRaises(KbError) as caught:
                with capture_file.lock(self.index):
                    self.fail("the second holder got in")
            self.assertIn("another", str(caught.exception))
        with capture_file.lock(self.index):
            pass
        with self.assertRaises(RuntimeError):
            with capture_file.lock(self.index):
                raise RuntimeError("boom")
        with capture_file.lock(self.index):
            pass

    def test_a_lock_that_cannot_be_taken_for_another_reason_does_not_say_that_another_run_holds_it(self):
        with mock.patch.object(capture_file.fcntl, "flock", side_effect=OSError(errno.EIO, "io")):
            with self.assertRaises(KbError) as caught:
                with capture_file.lock(self.index):
                    pass
        self.assertNotIn("another", str(caught.exception))

    def test_the_lock_file_is_made_private_in_the_index_root_and_a_link_in_its_place_is_refused(self):
        with capture_file.lock(self.index):
            mode = os.stat(os.path.join(self.index, capture_file.LOCK)).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        os.unlink(os.path.join(self.index, capture_file.LOCK))
        os.symlink(os.path.join(self.base, "elsewhere"), os.path.join(self.index, capture_file.LOCK))
        with self.assertRaises(KbError):
            with capture_file.lock(self.index):
                pass


if __name__ == "__main__":
    unittest.main()
