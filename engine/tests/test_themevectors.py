"""The vectors of the themes: the file in the index root, built from the cards and the themes of the active books."""
import builtins
import contextlib
import copy
import fcntl
import io
import json
import os
import sqlite3
import stat
import struct
import sys
import unittest
import unittest.mock
from contextlib import closing

from engine.tests.test_card import MODEL as CARD_MODEL, RECORD as CARD_RECORD
from engine.tests.test_models import FAKE_EMBED, config as models_config, embedding
from engine.tests.test_themecheck import config as theme_config, verdicts
from engine.tests.test_themeextract import Fake, VersionCase, row, values

from kb import KbError, card, catalog, convert, models, read as reading, search as fulltext, textutil, theme, themecheck, themevectors
from kb import __main__ as kbmain
from kb import config as kbconfig

def put(path, data, mode="w"):
    with open(path, mode) as f:
        f.write(data)


def open_bytes(path):
    return get(path, "rb")


def get(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


PARTS = ("problem", "method", "needs", "provides", "limits")
SUMMARIES = ["The search accepts worse moves less often as it cools.", "The temperature falls by a fixed factor at each step.",
             "The search stops once no move has been accepted for a while.", "A schedule that is too fast traps the search early."]


def with_embedding(**over):
    cfg = models_config(emb=embedding(**over))
    cfg["tasks"] = {"card-embed": "emb"}
    return cfg


def rows_of(n=2, **over):
    """n themes over distinct blocks, each with every part but the limits (the default row), or as `over` says."""
    blocks = ["1", "2", "4", "5"]
    return [row(title=f"Theme number {i + 1}", blocks=blocks[i], summary=SUMMARIES[i], problem=f"problem {i + 1}", method=f"method {i + 1}",
                needs=f"needs {i + 1}", provides=f"provides {i + 1}", **over) for i in range(n)]


class VectorsCase(VersionCase):
    def setUp(self):
        super().setUp()
        self.launcher = os.path.join(self.base_dir(), "wb")
        with open(self.launcher, "w") as f:
            f.write(FAKE_EMBED.format(python=sys.executable))
        os.chmod(self.launcher, 0o700)
        self.plan()
        self.mcfg = with_embedding()

    def base_dir(self):
        return os.path.dirname(self.store.cfg["index_root"])

    def plan(self, **p):
        with open(os.path.join(self.base_dir(), "plan.json"), "w") as f:
            json.dump(p, f)

    def sent(self):
        path = os.path.join(self.base_dir(), "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [t for line in f for t in json.loads(json.loads(line)["stdin"])["texts"]]

    def calls(self):
        path = os.path.join(self.base_dir(), "calls.jsonl")
        return len(get(path).splitlines()) if os.path.exists(path) else 0

    def themed(self, rows=None, title=None, flags=None):
        """A book with a card and a generation of themes made from `rows` (filed, not checked by a model beyond a fake)."""
        rows = rows if rows is not None else rows_of()
        book, version = self.converted_book()
        script = [values(*rows)]
        for r in rows:
            n = sum(1 for p in PARTS if r[p].strip(" .").casefold() not in ("none", "n/a", ""))
            if n:
                script.append(verdicts(*["supports"] * n))
        fake = Fake(*script)
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, theme_config(), book, version, frequencies=({}, 1000))
        generation = got["generation"]
        if flags is not None:
            for t in generation["themes"]:
                t["flags"] = copy.deepcopy(flags)
        theme.file(self.store, theme.make(book, version, generation["themes"]) if flags is not None else generation)
        return book, version

    def build(self, cfg=None, **kw):
        return themevectors.build(self.store, cfg or self.mcfg, launcher=self.launcher, **kw)

    def path(self):
        return themevectors.path_of(self.store.cfg["index_root"])

    def stored(self):
        with closing(sqlite3.connect(self.path())) as conn:
            rows = conn.execute("SELECT book_id, version_id, theme_id, field, text_sha256, vector FROM vectors ORDER BY book_id, version_id, theme_id, field").fetchall()
        return [(b, v, t, f, h, list(struct.unpack(f"<{len(blob) // 4}f", blob))) for b, v, t, f, h, blob in rows]

    def meta(self):
        with closing(sqlite3.connect(self.path())) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())

    def themes_read(self):
        with closing(themevectors.connect(self.path(), readonly=True)) as conn:
            return themevectors.read_themes(conn)


class BuildTest(VectorsCase):
    def test_a_theme_with_every_part_has_seven_texts_and_seven_vectors(self):
        self.themed(rows_of(1, limits="where the schedule is too fast"))
        got = self.build()
        self.assertEqual((got["themes"], got["vectors"], got["made"], got["texts_sent"]), (1, 7, 7, 7))
        self.assertEqual([f for _, _, _, f, _, _ in self.stored()], sorted(themevectors.FIELDS))
        self.assertEqual(sorted(self.sent()), sorted([SUMMARIES[0], "problem 1", "method 1", "needs 1", "provides 1", "where the schedule is too fast",
                                                      "problem: problem 1\nmethod: method 1\nneeds: needs 1\nprovides: provides 1\nlimits: where the schedule is too fast"]))

    def test_the_needs_and_the_limits_are_embedded(self):
        self.themed(rows_of(1, limits="a limit"))
        self.build()
        fields = {f for _, _, _, f, _, _ in self.stored()}
        self.assertLessEqual({"needs", "limits", "description", "summary"}, fields)

    def test_a_part_with_no_text_has_no_text_of_its_own_and_is_left_out_of_the_description(self):
        self.themed(rows_of(1))   # the limits part is "none": no text
        got = self.build()
        self.assertEqual(got["vectors"], 6)
        self.assertNotIn("limits", {f for _, _, _, f, _, _ in self.stored()})
        self.assertIn("problem: problem 1\nmethod: method 1\nneeds: needs 1\nprovides: provides 1", self.sent())

    def test_a_theme_with_no_part_has_a_summary_and_no_description(self):
        self.themed([row(title="Bare", blocks="1", summary=SUMMARIES[0], problem="none", method="none", needs="none", provides="none", limits="none")])
        got = self.build()
        self.assertEqual((got["themes"], got["vectors"]), (1, 1))
        self.assertEqual([f for _, _, _, f, _, _ in self.stored()], ["summary"])

    def test_the_vectors_are_those_of_the_texts_the_bridge_made(self):
        from engine.tests.test_models import fake_vector
        self.themed(rows_of(1))
        self.build()
        for _, _, _, field, sha, vector in self.stored():
            texts = {themevectors.sha256(t): t for t in self.sent()}
            self.assertEqual(vector, [struct.unpack("<f", struct.pack("<f", x))[0] for x in fake_vector(texts[sha])])

    def test_only_the_texts_of_the_embedded_fields_are_sent_and_never_a_title_or_the_text_of_the_book(self):
        self.themed(rows_of(2))
        self.build()
        everything = "\n".join(self.sent())
        self.assertNotIn("A paper on annealing", everything)
        self.assertNotIn("Theme number", everything)
        self.assertNotIn("Annealing cools", everything)

    def test_a_second_build_keeps_every_vector_and_sends_nothing(self):
        self.themed(rows_of(2))
        first = self.build()
        before = self.calls()
        second = self.build()
        self.assertEqual((second["kept"], second["made"], second["texts_sent"]), (first["vectors"], 0, 0))
        self.assertEqual(self.calls(), before)

    def test_the_same_text_in_two_themes_is_sent_once(self):
        same = [row(title="One", blocks="1", summary=SUMMARIES[0], problem="the same problem", method="m one", needs="none", provides="none", limits="none"),
                row(title="Two", blocks="2", summary=SUMMARIES[1], problem="the same problem", method="m two", needs="none", provides="none", limits="none")]
        self.themed(same)
        got = self.build()
        self.assertEqual(self.sent().count("the same problem"), 1)
        self.assertEqual(got["vectors"], 2 * 4 - 0)   # summary, description, problem and method for each, the problem text shared in what is sent
        self.assertEqual(got["texts_sent"], got["vectors"] - 1)

    def test_a_changed_text_makes_only_that_vector_again(self):
        book, version = self.themed(rows_of(1))
        self.build()
        self.plan()
        before = self.calls()
        changed = rows_of(1)
        changed[0]["method"] = "a new method"
        fake = Fake(values(*changed), verdicts("supports", "supports", "supports", "supports"))
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, theme_config(), book, version, frequencies=({}, 1000))
        theme.file(self.store, got["generation"])
        second = self.build()
        self.assertEqual(second["made"], 2)   # the method and the description that holds it
        self.assertEqual(sorted(self.sent()[-2:]), sorted(["a new method", "problem: problem 1\nmethod: a new method\nneeds: needs 1\nprovides: provides 1"]))
        self.assertGreater(self.calls(), before)

    def test_a_changed_model_dimension_or_document_prefix_makes_every_vector_again_and_says_the_file_was_replaced(self):
        self.themed(rows_of(1))
        first = self.build()
        for cfg in (with_embedding(dimension=5), with_embedding(document_prefix="doc: ")):
            with self.subTest(cfg=cfg["models"]["emb"]):
                self.plan(dim=cfg["models"]["emb"]["dimension"])
                got = self.build(cfg)
                self.assertEqual((got["made"], got["kept"], got["replaced"]), (first["vectors"], 0, True))
        self.plan()
        got = self.build(with_embedding(model="other-model:1"))
        self.assertTrue(got["replaced"])

    def test_a_model_that_the_bridge_reports_as_another_than_the_one_that_made_the_kept_vectors_is_refused(self):
        book, version = self.themed(rows_of(1))
        self.build()
        changed = rows_of(1)
        changed[0]["method"] = "a method that is new"
        fake = Fake(values(*changed), verdicts("supports", "supports", "supports", "supports"))
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, theme_config(), book, version, frequencies=({}, 1000))
        theme.file(self.store, got["generation"])
        old = open_bytes(self.path())
        self.plan(model="another-model:9")
        with self.assertRaises(KbError) as cm:
            self.build()
        self.assertIn("is not the one that made the vectors that are kept", str(cm.exception))
        self.assertEqual(open_bytes(self.path()), old)

    def test_a_model_that_is_another_does_not_matter_when_no_vector_is_kept(self):
        book, version = self.themed(rows_of(1))
        self.build()
        entirely = [row(title="Another", blocks="1", summary="Nothing at all like the first.", problem="p other", method="m other", needs="n other", provides="v other")]
        fake = Fake(values(*entirely), verdicts("supports", "supports", "supports", "supports"))
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, theme_config(), book, version, frequencies=({}, 1000))
        theme.file(self.store, got["generation"])
        self.plan(model="another-model:9")
        built = self.build()
        self.assertEqual((built["kept"], built["model"]), (0, "another-model:9"))
        self.assertEqual(self.meta()["model"], "another-model:9")

    def test_again_makes_every_vector_again(self):
        self.themed(rows_of(1))
        first = self.build()
        got = self.build(again=True)
        self.assertEqual((got["made"], got["kept"], got["replaced"]), (first["vectors"], 0, False))
        with self.assertRaises(KbError):
            self.build(again="yes")

    def test_a_file_that_is_not_this_engines_is_damaged_or_of_another_format_is_replaced_by_a_build(self):
        self.themed(rows_of(1))
        index_root = self.store.cfg["index_root"]
        for how in ("garbage", "foreign", "format"):
            with self.subTest(how):
                if how == "garbage":
                    put(self.path(), b"not a database at all", "wb")
                elif how == "foreign":
                    os.unlink(self.path()) if os.path.exists(self.path()) else None
                    with closing(sqlite3.connect(self.path())) as conn:
                        conn.execute("CREATE TABLE other (x)")
                        conn.commit()
                else:
                    self.build()
                    with closing(sqlite3.connect(self.path())) as conn:
                        conn.execute("PRAGMA user_version = 99")
                        conn.commit()
                got = self.build()
                self.assertTrue(got["replaced"])
                self.assertEqual(got["kept"], 0)
                with closing(themevectors.connect(self.path(), readonly=True)) as conn:
                    themevectors.check_entry(conn, models.registry(self.mcfg)["emb"])
        self.assertEqual([n for n in os.listdir(index_root) if n.startswith(themevectors.BUILD_PREFIX)], [])

    def test_a_build_that_fails_leaves_the_old_file_as_it_was_and_no_folder_of_the_build(self):
        self.themed(rows_of(1))
        self.build()
        old = get(self.path(), "rb")
        other = rows_of(1)
        other[0]["method"] = "a method of another book"
        self.themed(other)   # another book, with a text to make
        self.plan(mode="short")
        with self.assertRaises(KbError):
            self.build()
        self.assertEqual(get(self.path(), "rb"), old)
        self.assertEqual([n for n in os.listdir(self.store.cfg["index_root"]) if n.startswith(themevectors.BUILD_PREFIX)], [])

    def test_a_failure_after_the_folder_of_the_build_exists_leaves_the_old_file_and_no_folder(self):
        self.themed(rows_of(1))
        self.build()
        old = get(self.path(), "rb")
        other = rows_of(1)
        other[0]["method"] = "a method of another book"
        self.themed(other)
        for name, patch in (("the replace fails", unittest.mock.patch.object(os, "replace", side_effect=OSError(28, "No space left on device"))),
                            ("the folder is not the one that was made", unittest.mock.patch.object(themevectors.vectors, "_identity", side_effect=[(1, 1), (2, 2)]))):
            with self.subTest(name):
                with patch, self.assertRaises(KbError):
                    self.build()
                self.assertEqual(get(self.path(), "rb"), old)
                self.assertEqual([n for n in os.listdir(self.store.cfg["index_root"]) if n.startswith(themevectors.BUILD_PREFIX)], [])

    def test_the_lock_is_held_while_the_file_is_put_in_place_and_a_second_writer_is_refused(self):
        self.themed(rows_of(1))
        held = []
        real = os.replace

        def replace(src, dst):
            fd = os.open(os.path.join(self.store.cfg["index_root"], themevectors.LOCK_FILE), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except OSError:
                held.append(True)
            finally:
                os.close(fd)
            return real(src, dst)

        with unittest.mock.patch.object(os, "replace", replace):
            self.build()
        self.assertEqual(held, [True])
        with unittest.mock.patch.object(catalog, "LOCK_WAIT", 0.2), themevectors.lock(self.store.cfg["index_root"]):
            with self.assertRaises(KbError):
                self.build()

    def test_a_leftover_of_a_build_that_was_killed_is_removed_by_the_next_build(self):
        self.themed(rows_of(1))
        left = os.path.join(self.store.cfg["index_root"], themevectors.BUILD_PREFIX + "abcd")
        os.mkdir(left)
        put(os.path.join(left, "half"), "x")
        self.build()
        self.assertFalse(os.path.exists(left))

    def test_the_file_is_private_and_nothing_else_is_left_beside_it(self):
        self.themed(rows_of(1))
        self.build()
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)
        leftovers = [n for n in os.listdir(self.store.cfg["index_root"]) if n.startswith(".theme-vectors") or n.endswith("-journal")]
        self.assertEqual(leftovers, [])

    def test_the_build_takes_the_lock_to_write(self):
        self.themed(rows_of(1))
        with unittest.mock.patch.object(themevectors, "lock", wraps=themevectors.lock) as locked:
            self.build()
        locked.assert_called_once()

    def test_a_vector_that_is_all_zeros_or_not_finite_is_refused(self):
        self.themed(rows_of(1))
        for mode in ("nan", "inf", "short", "extra", "ragged", "dimension_says"):
            with self.subTest(mode):
                self.plan(mode=mode)
                with self.assertRaises(KbError):
                    self.build(again=True)
        self.plan(table={SUMMARIES[0]: [0, 0, 0, 0]})
        with self.assertRaises(KbError):
            self.build(again=True)

    def test_model_work_that_is_off_or_a_task_that_is_not_set_is_refused_before_anything_is_read_or_sent(self):
        self.themed(rows_of(1))
        off = with_embedding()
        off["models_on"] = False
        for cfg in (off, models_config(emb=embedding())):
            with self.subTest(tasks=cfg.get("tasks")):
                with self.assertRaises(KbError):
                    self.build(cfg)
        self.assertEqual(self.calls(), 0)


class WhatIsReadTest(VectorsCase):
    def test_the_newest_valid_generation_of_themes_and_the_newest_card_are_built(self):
        book, version = self.themed(rows_of(1))
        newer = rows_of(2)
        fake = Fake(values(*newer), *[verdicts("supports", "supports", "supports", "supports")] * 2)
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, theme_config(), book, version, frequencies=({}, 1000))
        number = theme.file(self.store, got["generation"])
        self.assertEqual(number, 2)
        counts = self.build()
        self.assertEqual(counts["themes"], 2)
        self.assertEqual({t["theme_generation"] for t in self.themes_read()}, {2})

    def test_a_newer_generation_that_is_damaged_is_passed_over_for_the_older_valid_one(self):
        book, version = self.themed(rows_of(1))
        theme.file(self.store, self.newest_generation(book, version))
        path = os.path.join(self.store.version_dir(book, version), "derived", theme.TOOL, "2", theme.FILENAME)
        os.chmod(path, 0o600)
        put(path, "{}")
        self.build()
        self.assertEqual({t["theme_generation"] for t in self.themes_read()}, {1})

    def newest_generation(self, book, version):
        return theme.read(self.store, book, version)[1]

    def test_books_that_cannot_be_built_are_left_out_and_counted(self):
        self.themed(rows_of(1))
        inactive = self.themed(rows_of(1))[0]
        self.store.set_state(inactive, "weeded")
        self.converted_book()                                  # a book with a card and no themes
        no_card = self.themed(rows_of(1))[0]
        broken = self.themed(rows_of(1))[0]
        real_read = card.read

        def read(store, book_id, *a, **k):
            if book_id == no_card:
                raise KbError("no card")
            return real_read(store, book_id, *a, **k)

        real_theme = theme.read

        def theme_read(store, book_id, *a, **k):
            if book_id == broken:
                raise KbError("damaged")
            return real_theme(store, book_id, *a, **k)

        with unittest.mock.patch.object(card, "read", read), unittest.mock.patch.object(theme, "read", theme_read):
            got = self.build()
        self.assertEqual((got["themes"], got["inactive"], got["no_themes"], got["no_card"], got["unreadable"]), (1, 1, 1, 1, 1))
        self.assertEqual((got["books"], got["built"]), (5, 1))
        self.assertEqual(got["books"], got["built"] + got["inactive"] + got["no_card"] + got["no_themes"] + got["unreadable"])   # each book is counted once

    def test_a_book_whose_newest_card_is_damaged_has_no_card_that_can_be_read(self):
        book, version = self.themed(rows_of(1))
        card.file(self.store, card.make(self.store, book, version, model=copy.deepcopy(CARD_MODEL), records=[dict(CARD_RECORD)], pieces=1, calls=1))
        path = os.path.join(self.store.version_dir(book, version), "derived", card.TOOL, "2", card.FILENAME)
        os.chmod(path, 0o600)
        put(path, "{}")
        got = self.build()
        self.assertEqual((got["no_card"], got["themes"], got["built"]), (1, 0, 0))

    def test_a_book_with_no_version_has_no_card(self):
        self.store.create_book(title="No version", kind="preprint")
        got = self.build()
        self.assertEqual((got["books"], got["no_card"], got["built"]), (1, 1, 0))

    def test_a_book_whose_record_cannot_be_read_is_unreadable_and_the_others_go_on(self):
        self.themed(rows_of(1))
        broken = self.themed(rows_of(1))[0]
        real = type(self.store).read_book

        def read_book(store, book_id):
            if book_id == broken:
                raise KbError("damaged")
            return real(store, book_id)

        with unittest.mock.patch.object(type(self.store), "read_book", read_book):
            got = self.build()
        self.assertEqual((got["books"], got["built"], got["unreadable"]), (2, 1, 1))

    def test_the_files_of_a_book_that_are_opened_are_not_its_original_or_its_converted_text(self):
        self.themed(rows_of(1))
        opened = []
        real = builtins.open

        def spy(file, *a, **k):
            opened.append(str(file))
            return real(file, *a, **k)

        with unittest.mock.patch.object(builtins, "open", spy):
            self.build()
        books = [p for p in opened if os.sep + "books" + os.sep in p]
        self.assertTrue(books)   # the card and the themes were read
        self.assertFalse([p for p in books if "kb-html-std" in p or os.sep + "original" + os.sep in p], books)
        self.assertTrue(all(os.sep + "derived" + os.sep in p or p.endswith("book.json") for p in books), books)

    def test_nothing_of_a_book_is_opened_but_its_card_and_its_themes(self):
        self.themed(rows_of(1))
        with unittest.mock.patch.object(convert, "load_in_use", side_effect=AssertionError("the converted text was opened")), \
                unittest.mock.patch.object(type(self.store), "read_version", side_effect=AssertionError("the manifest of a version was opened")):
            got = self.build()
        self.assertEqual(got["themes"], 1)

    def test_the_rows_hold_what_a_result_shows(self):
        book, version = self.themed(rows_of(1, limits="a limit"))
        self.build()
        [t] = self.themes_read()
        self.assertEqual((t["book_id"], t["version_id"], t["theme_id"]), (book, version, "t1"))
        self.assertEqual((t["book_title"], t["theme_generation"], t["card_generation"]), ("A paper on annealing", 1, 1))
        made = theme.read(self.store, book, version)[1]["themes"][0]
        self.assertEqual(t["theme"], made)                     # the whole theme, with its whole anchor, its parts and their marks, confidence and flags
        self.assertEqual(set(t["theme"]["anchor"]), {"start", "end", "path", "excerpt_sha256"})
        self.assertEqual(t["theme"]["neutral"]["limits"], {"text": "a limit", "mark": "stated"})
        self.assertIn("Language: not recorded", t["citation"])
        self.assertTrue(t["citation"].startswith(catalog.citation_of(card.read(self.store, book, version)[1])))
        self.assertEqual(set(t["hashes"]), set(themevectors.FIELDS))
        for field, sha in t["hashes"].items():
            self.assertEqual(len(sha), 64)

    def test_the_generation_of_the_newest_card_is_the_one_recorded(self):
        book, version = self.themed(rows_of(1))
        card.file(self.store, card.make(self.store, book, version, model=copy.deepcopy(CARD_MODEL), records=[dict(CARD_RECORD)], pieces=1, calls=1))
        self.assertEqual(card.read(self.store, book, version)[0], 2)
        self.build()
        self.assertEqual([t["card_generation"] for t in self.themes_read()], [2])

    def test_the_citation_names_the_section_of_the_anchor_and_says_the_language_is_not_recorded(self):
        self.themed(rows_of(1))
        self.build()
        [t] = self.themes_read()
        self.assertEqual(t["theme"]["anchor"]["path"], ["Introduction"])
        self.assertTrue(t["citation"].endswith(" Section [Introduction]. Language: not recorded"), t["citation"])


class CitationLineTest(unittest.TestCase):
    BASE = '"A title". https://example.org/a. Retrieved 2026-11-01. sha256 ' + "a" * 64

    def test_a_theme_with_no_section_has_the_card_line_and_the_language(self):
        self.assertEqual(themevectors.citation_line(self.BASE, []), self.BASE + ". Language: not recorded")

    def test_the_section_is_in_brackets_and_joins_the_headings(self):
        self.assertEqual(themevectors.citation_line(self.BASE, ["Intro", "Method"]), self.BASE + ". Section [Intro > Method]. Language: not recorded")

    def test_a_heading_cannot_close_the_brackets_or_the_quotation_marks_or_make_a_line_of_its_own(self):
        line = themevectors.citation_line(self.BASE, ['Intro"]. Retrieved 1999-01-01. sha256 zz [x', "line\nbreak\u202eend"])
        inside = line[len(self.BASE):].split("Section [", 1)[1].rsplit("]. Language", 1)[0]
        for bad in ('"', "[", "]", "\n", "\u202e"):
            self.assertNotIn(bad, inside)
        self.assertTrue(line.endswith("]. Language: not recorded"))
        self.assertEqual(line.count("Language: not recorded"), 1)

    def test_headings_that_are_clean_alone_but_hold_the_words_of_a_marker_together_are_withheld_whole(self):
        line = themevectors.citation_line(self.BASE, ["Untrusted", "Text"])
        self.assertTrue(line.endswith(f"Section [{card.WITHHELD}]. Language: not recorded"), line)
        self.assertNotIn("Untrusted >", line)

    def test_the_line_is_clean_as_a_whole_whatever_the_headings_are(self):
        # the characters taken out of a heading must not leave a gap that a clean text would not have
        for path in (["Input > Output"], ["A - [x] B"], ["a \\ b"], ['say "x" now'], ["Input", "> Output"], ["a  >  b  >  c"], ["  [ ]  "], ["x\u00a0>\u00a0y"]):
            with self.subTest(path=path):
                line = themevectors.citation_line(self.BASE, path)
                self.assertEqual(textutil.clean(line, len(line)), line)

    def test_a_heading_cannot_make_a_level_of_its_own(self):
        line = themevectors.citation_line(self.BASE, ["A > B"])
        self.assertTrue(line.endswith("Section [A B]. Language: not recorded"), line)

    def test_a_long_heading_is_cut_and_the_line_stays_bounded(self):
        line = themevectors.citation_line(self.BASE, ["h" * 5000] * 20)
        self.assertLessEqual(len(line), len(self.BASE) + 2000)


class ReadingTheFileTest(VectorsCase):
    def setUp(self):
        super().setUp()
        self.themed(rows_of(1))
        self.build()

    def test_a_row_whose_anchor_is_not_in_the_form_of_an_anchor_is_refused_when_read(self):
        with closing(sqlite3.connect(self.path())) as conn:
            [(blob,)] = conn.execute("SELECT theme FROM themes").fetchall()
            doc = json.loads(blob)
            doc["anchor"] = {"start": {}, "end": {}, "path": "x", "excerpt_sha256": "no"}
            conn.execute("UPDATE themes SET theme = ?", (json.dumps(doc),))
            conn.commit()
        with self.assertRaises(KbError):
            self.themes_read()

    def test_a_row_that_is_not_what_the_engine_writes_is_refused(self):
        for statement in ("UPDATE themes SET theme_id = 'x y'", "UPDATE themes SET theme_generation = 0", "UPDATE themes SET theme_id = 't9'", "UPDATE themes SET hashes = '{\"summary\": \"' || hex(zeroblob(32)) || '\"}'", "UPDATE themes SET book_title = ''",
                          "UPDATE themes SET citation = ''", "UPDATE themes SET hashes = 'not json'", "UPDATE themes SET theme = 'not json'"):
            with self.subTest(statement):
                with closing(sqlite3.connect(self.path())) as conn:
                    conn.execute(statement)
                    conn.commit()
                with self.assertRaises(KbError):
                    self.themes_read()
                self.build(again=True)   # and a build puts it right

    def test_a_vector_of_the_wrong_length_is_refused_or_left_out_if_lenient(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("UPDATE vectors SET vector = zeroblob(7) WHERE field = 'summary'")
            conn.commit()
        entry = models.registry(self.mcfg)["emb"]
        with closing(themevectors.connect(self.path(), readonly=True)) as conn:
            with self.assertRaises(KbError):
                themevectors.read_vectors(conn, entry["dimension"])
            lenient = themevectors.read_vectors(conn, entry["dimension"], lenient=True)
        self.assertEqual(sum(1 for v in lenient if v["vector"] is None), 1)

    def test_a_vector_that_is_all_zeros_or_not_finite_is_refused_when_read_and_left_out_if_lenient(self):
        entry = models.registry(self.mcfg)["emb"]
        for blob in (struct.pack("<4f", 0, 0, 0, 0), struct.pack("<4f", float("nan"), 1, 1, 1), struct.pack("<4f", float("inf"), 1, 1, 1)):
            with self.subTest(blob=blob):
                with closing(sqlite3.connect(self.path())) as conn:
                    conn.execute("UPDATE vectors SET vector = ? WHERE field = 'summary'", (blob,))
                    conn.commit()
                with closing(themevectors.connect(self.path(), readonly=True)) as conn:
                    with self.assertRaises(KbError):
                        themevectors.read_vectors(conn, entry["dimension"])
                    self.assertEqual(sum(1 for v in themevectors.read_vectors(conn, entry["dimension"], lenient=True) if v["vector"] is None), 1)
                self.build(again=True)

    def test_a_vector_row_for_a_field_that_is_not_embedded_or_a_bad_id_is_refused(self):
        entry = models.registry(self.mcfg)["emb"]
        for statement in ("UPDATE vectors SET field = 'bogus' WHERE field = 'summary'", "UPDATE vectors SET theme_id = 'X y' WHERE field = 'summary'",
                          "UPDATE vectors SET version_id = 'x' WHERE field = 'summary'", "UPDATE vectors SET book_id = 'x' WHERE field = 'summary'", "UPDATE vectors SET text_sha256 = 'nothash' WHERE field = 'summary'"):
            with self.subTest(statement):
                with closing(sqlite3.connect(self.path())) as conn:
                    conn.execute(statement)
                    conn.commit()
                with closing(themevectors.connect(self.path(), readonly=True)) as conn:
                    with self.assertRaises(KbError):
                        themevectors.read_vectors(conn, entry["dimension"])
                self.build(again=True)

    def test_a_file_for_another_model_dimension_or_prefix_is_refused_by_the_check(self):
        with closing(themevectors.connect(self.path(), readonly=True)) as conn:
            for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
                with self.assertRaises(KbError):
                    themevectors.check_entry(conn, models.registry(cfg)["emb"])
            meta = themevectors.check_entry(conn, models.registry(self.mcfg)["emb"])
        self.assertEqual(meta["configured"], "bge-m3:latest")

    def test_a_missing_file_a_link_and_a_file_with_a_trigger_or_a_view_are_refused(self):
        with self.assertRaises(KbError):
            themevectors.connect(os.path.join(self.store.cfg["index_root"], "nothing.sqlite"), readonly=True)
        link = os.path.join(self.store.cfg["index_root"], "link.sqlite")
        os.symlink(self.path(), link)
        with self.assertRaises(KbError):
            themevectors.connect(link, readonly=True)
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("CREATE VIEW v AS SELECT 1")
            conn.commit()
        with self.assertRaises(KbError):
            themevectors.connect(self.path(), readonly=True)

    def test_the_file_is_read_only_when_opened_so(self):
        with closing(themevectors.connect(self.path(), readonly=True)) as conn:
            with self.assertRaises(sqlite3.Error):
                conn.execute("DELETE FROM vectors")

    def test_the_file_has_the_tables_and_the_format_of_the_module(self):
        with closing(sqlite3.connect(self.path())) as conn:
            tables = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(tables, {"meta", "themes", "vectors"})
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], themevectors.FORMAT)
        self.assertEqual(set(self.meta()), set(themevectors._META_KEYS))


class SearchCase(VectorsCase):
    """Two themes in two books, built with a bridge whose vectors the test chooses (dimension 4)."""

    QUERY = "how to stop a search once it has settled"

    def setUp(self):
        super().setUp()
        self.b1, self.v1 = self.themed(rows_of(1, limits="a limit"))
        other = [row(title="Another idea", blocks="4", summary="Nothing like the first.", problem="p other", method="m other", needs="n other",
                     provides="v other")]
        self.b2, self.v2 = self.themed(other)

    def search(self, *args, **kw):
        query = args[0] if args else self.QUERY   # a query given is passed as it is, whatever it is
        return themevectors.search(self.store.cfg["index_root"], self.mcfg, query, launcher=self.launcher, **kw)

    def built(self, **table):
        """Build with a bridge that answers with the vectors named (by text), and with the fake's own for the others."""
        self.plan(table=table)
        return self.build(again=True)


class SearchTest(SearchCase):
    def test_themes_are_ranked_by_the_closest_of_their_vectors_one_result_for_each_theme(self):
        away = [0, 0, 1, 0]   # every text that is not named below is made orthogonal to the query, so that the scores are the ones named
        self.built(**{self.QUERY: [1, 0, 0, 0], "problem 1": [1, 0, 0, 0], "provides 1": [1, 0.1, 0, 0], "p other": [0.6, 0.8, 0, 0], SUMMARIES[0]: away,
                      "method 1": away, "needs 1": away, "a limit": away, "problem: problem 1\nmethod: method 1\nneeds: needs 1\nprovides: provides 1\nlimits: a limit": away,
                      "Nothing like the first.": away, "m other": away, "n other": away, "v other": away,
                      "problem: p other\nmethod: m other\nneeds: n other\nprovides: v other": away})
        got = self.search()
        self.assertEqual([r["book_id"] for r in got["results"]], [self.b1, self.b2])   # two themes, and the first has several vectors near the query
        self.assertAlmostEqual(got["results"][0]["score"], 1.0, places=6)
        self.assertAlmostEqual(got["results"][1]["score"], 0.6, places=6)
        self.assertEqual(len({(r["book_id"], r["theme_id"]) for r in got["results"]}), len(got["results"]))

    def test_a_result_says_which_text_matched_shows_it_and_gives_the_mark_of_that_part(self):
        self.built(**{self.QUERY: [1, 0, 0, 0], "problem 1": [1, 0, 0, 0]})
        first = self.search()["results"][0]
        self.assertEqual((first["excerpt_field"], first["matched"]), ("problem", ["problem"]))
        self.assertEqual(first["excerpt_mark"], "stated")
        self.assertTrue(first["excerpt"].startswith(fulltext.MARKER + "\n"))
        self.assertTrue(first["excerpt"].endswith("problem 1"))
        self.built(**{self.QUERY: [1, 0, 0, 0], SUMMARIES[0]: [1, 0, 0, 0]})
        first = self.search()["results"][0]
        self.assertEqual((first["excerpt_field"], first["excerpt_mark"]), ("summary", None))
        self.built(**{self.QUERY: [1, 0, 0, 0], "problem: problem 1\nmethod: method 1\nneeds: needs 1\nprovides: provides 1\nlimits: a limit": [1, 0, 0, 0]})
        first = self.search()["results"][0]
        self.assertEqual((first["excerpt_field"], first["excerpt_mark"]), ("description", None))

    def test_a_result_has_the_theme_the_book_the_whole_anchor_the_summary_the_citation_the_flags_and_the_markers(self):
        self.built(**{self.QUERY: [1, 0, 0, 0], "problem 1": [1, 0, 0, 0]})
        r = self.search()["results"][0]
        made = theme.read(self.store, self.b1, self.v1)[1]["themes"][0]
        self.assertEqual((r["book_id"], r["version_id"], r["theme_id"], r["theme_generation"], r["card_generation"]), (self.b1, self.v1, made["id"], 1, 1))
        self.assertEqual(r["anchor"], made["anchor"])
        self.assertEqual(set(r["anchor"]), {"start", "end", "path", "excerpt_sha256"})
        self.assertEqual((r["theme_title"], r["type"], r["summary"], r["confidence"]), (made["title"], made["type"], made["summary"], made["confidence"]))
        self.assertEqual(r["book_title"], "A paper on annealing")
        self.assertEqual(r["flags"], [{"kind": f["kind"], "detail": f["detail"]} for f in made["flags"]])
        self.assertIn("Language: not recorded", r["citation"])
        self.assertTrue(r["untrusted"])
        self.assertTrue(r["text"].startswith(fulltext.MARKER + "\n") and r["text"].endswith("\n" + reading.END_MARKER))
        self.assertIn(made["summary"], r["text"])
        for part in theme.PARTS:
            if made["neutral"][part]["text"]:
                self.assertIn(f"{part} [{made['neutral'][part]['mark']}]: {made['neutral'][part]['text']}", r["text"])

    def test_a_tie_goes_to_the_first_text_and_then_to_the_first_theme(self):
        same = [1, 0, 0, 0]
        self.built(**{self.QUERY: same, SUMMARIES[0]: same, "problem 1": same, "p other": same})
        got = self.search()["results"]
        self.assertEqual(got[0]["excerpt_field"], "summary")             # the summary comes first of the texts
        self.assertEqual([r["book_id"] for r in got], sorted([self.b1, self.b2]))

    def test_the_limit_is_one_to_fifty_and_the_default_is_ten(self):
        self.built()
        before = self.calls()
        for bad in (0, 51, -1, "5", None, True, 2.0):
            with self.subTest(limit=bad):
                with self.assertRaises(KbError):
                    self.search(limit=bad)
        self.assertEqual(self.calls(), before)                          # refused before the query is sent
        self.assertEqual(len(self.search(limit=1)["results"]), 1)
        self.assertEqual(len(self.search()["results"]), 2)
        self.assertEqual(fulltext.DEFAULT_LIMIT, 10)

    def test_a_query_that_is_not_text_is_empty_or_too_long_is_refused_before_it_is_sent(self):
        self.built()
        before = self.calls()
        for bad in (None, 5, ["a"], "", "   \n", "x" * (fulltext.MAX_QUERY_CHARS + 1), "a\ud800b"):
            with self.subTest(query=bad):
                with self.assertRaises(KbError):
                    self.search(bad)
        self.assertEqual(self.calls(), before)

    def test_only_the_query_is_sent_and_nothing_is_written(self):
        self.built()
        before_files = sorted(os.listdir(self.store.cfg["index_root"]))
        before = get(self.path(), "rb")
        sent_before = len(self.sent())
        self.search()
        self.assertEqual(self.sent()[sent_before:], [self.QUERY])
        self.assertEqual(get(self.path(), "rb"), before)
        self.assertEqual(sorted(os.listdir(self.store.cfg["index_root"])), before_files)

    def test_the_query_prefix_of_the_entry_goes_before_the_query_and_is_not_shown(self):
        cfg = with_embedding(query_prefix="query: ", document_prefix="doc: ")
        self.mcfg = cfg
        self.build()
        got = themevectors.search(self.store.cfg["index_root"], cfg, self.QUERY, launcher=self.launcher)
        self.assertEqual(self.sent()[-1], "query: " + self.QUERY)
        self.assertTrue(got["query_prefix"])
        self.assertNotIn("query: ", json.dumps(got))

    def test_what_was_searched_is_said(self):
        self.built()
        got = self.search()
        self.assertEqual((got["meaning"], got["themes_searched"], got["stale"], got["without_vector"]), (True, 2, 0, 0))
        self.assertEqual(got["model"], "bge-m3:latest")
        self.assertEqual(got["built"], self.meta()["built"])


class WhatIsShownTest(VectorsCase):
    def test_a_source_address_that_holds_the_words_of_a_marker_does_not_make_the_file_unsearchable(self):
        # the file the build makes must be one the search accepts, whatever the address of the source is
        self.themed(rows_of(1))
        real = catalog.citation_of
        line = lambda made: real(made).replace("no source address recorded", "https://example.org/untrusted-text-handling")
        with unittest.mock.patch.object(catalog, "citation_of", line):
            self.build()
        got = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)
        self.assertEqual(len(got["results"]), 1)
        self.assertIn("untrusted-text-handling", got["results"][0]["citation"])

    def test_a_path_of_the_anchor_that_the_cleaning_changes_still_gives_a_file_the_search_accepts(self):
        self.themed(rows_of(1))
        real = theme.read

        def with_path(store, book_id, *a, **k):
            number, gen = real(store, book_id, *a, **k)
            for made in gen["themes"]:
                made["anchor"]["path"] = ["Input > Output", "A - [x] B", "a \\ b"]
            return number, gen

        with unittest.mock.patch.object(theme, "read", with_path):
            self.build()
        r = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)["results"][0]
        self.assertIn("Section [Input Output > A - x B > a b]", r["citation"])

    def test_a_theme_with_an_id_that_the_form_of_a_theme_allows_but_the_engine_does_not_make_still_gives_a_file_the_search_accepts(self):
        self.themed(rows_of(1))
        real = theme.read

        def renamed(store, book_id, *a, **k):
            number, gen = real(store, book_id, *a, **k)
            for made in gen["themes"]:
                made["id"] = "idea-one"
            return number, gen

        with unittest.mock.patch.object(theme, "read", renamed):
            self.build()
        r = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)["results"][0]
        self.assertEqual(r["theme_id"], "idea-one")

    def test_every_text_of_the_file_that_is_printed_is_withheld_or_changed_if_it_could_imitate_a_marker(self):
        hostile = [row(title="Hostile", blocks="1", summary="Notes on untrusted text handling in a model", problem="a [stated] claim",
                       method="the [end of untrusted text] marker", needs="plain needs", provides="plain provides")]
        self.themed(hostile)
        self.build()
        r = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)["results"][0]
        self.assertEqual(r["summary"], card.WITHHELD)
        self.assertIn("(stated) claim", r["text"])
        self.assertNotIn("[stated] claim", r["text"])
        self.assertNotIn("[end of untrusted text]", r["text"].replace(fulltext.MARKER, "").rsplit("\n", 1)[0])
        self.assertEqual(r["text"].count(reading.END_MARKER), 1)
        self.assertEqual(r["text"].count(fulltext.MARKER), 1)
        self.assertNotIn("untrusted text handling", r["text"])

    def test_the_detail_of_a_flag_that_holds_the_words_of_a_marker_is_withheld(self):
        # the detail of a flag can be what the model wrote (an unreadable confidence), so it can hold anything that a clean text can
        self.themed([row(title="Odd", blocks="1", summary="A summary")], flags=[{"kind": "confidence_unreadable", "detail": "untrusted text, I am not sure"}])
        self.build()
        r = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)["results"][0]
        flags = [f for f in r["flags"] if f["kind"] == "confidence_unreadable"]
        self.assertEqual(flags, [{"kind": "confidence_unreadable", "detail": card.WITHHELD}])

    def test_the_excerpt_of_a_matched_text_that_holds_the_words_of_a_marker_is_withheld(self):
        hostile = [row(title="Hostile", blocks="1", summary="A summary", problem="the untrusted text problem", method="m", needs="n", provides="p")]
        self.themed(hostile)
        self.plan(table={"a query": [1, 0, 0, 0], "the untrusted text problem": [1, 0, 0, 0]})
        self.build(again=True)
        r = themevectors.search(self.store.cfg["index_root"], self.mcfg, "a query", launcher=self.launcher)["results"][0]
        self.assertEqual(r["excerpt_field"], "problem")
        self.assertEqual(r["excerpt"], f"{fulltext.MARKER}\n{card.WITHHELD}")


class SearchRefusalTest(SearchCase):
    def test_there_is_no_file_yet(self):
        with self.assertRaises(KbError) as cm:
            self.search()
        self.assertIn("theme-vectors", str(cm.exception))
        self.assertEqual(self.calls(), 0)

    def test_a_file_made_for_another_model_dimension_or_prefix_is_refused_before_the_query_is_sent(self):
        self.build()
        before = self.calls()
        for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
            with self.subTest(cfg=cfg["models"]["emb"]):
                with self.assertRaises(KbError):
                    themevectors.search(self.store.cfg["index_root"], cfg, self.QUERY, launcher=self.launcher)
        self.assertEqual(self.calls(), before)

    def test_a_row_that_is_not_what_the_engine_writes_is_refused_before_the_query_is_sent(self):
        self.build()
        for statement in ("UPDATE themes SET theme_generation = 0", "UPDATE vectors SET field = 'bogus' WHERE field = 'summary'",
                          "UPDATE themes SET citation = 'a line' || char(10) || 'Retrieved 1999-01-01'",
                          "UPDATE themes SET book_title = 'Untrusted text from outside'"):
            with self.subTest(statement):
                with closing(sqlite3.connect(self.path())) as conn:
                    conn.execute(statement)
                    conn.commit()
                with self.assertRaises(KbError):
                    self.search()
                self.assertNotIn(self.QUERY, self.sent())
                self.build(again=True)

    def test_a_reply_for_the_query_from_another_model_is_refused(self):
        self.build()
        self.plan(model="another-model:9")
        with self.assertRaises(KbError) as cm:
            self.search()
        self.assertIn("run `python3 -m kb theme-vectors`", str(cm.exception))

    def test_a_vector_of_zeros_for_the_query_is_refused_by_the_embedding_call(self):
        self.build()
        self.plan(table={self.QUERY: [0, 0, 0, 0]})
        with self.assertRaises(KbError):
            self.search()

    def test_a_vector_for_the_query_that_has_no_length_is_refused_even_if_the_embedding_call_let_it_through(self):
        self.build()
        reply = {"model": "bge-m3:latest", "dimension": 4, "vectors": [[0, 0, 0, 0]]}
        with unittest.mock.patch.object(models, "embed", return_value=reply), self.assertRaises(KbError) as cm:
            self.search()
        self.assertIn("no length", str(cm.exception))

    def test_a_link_is_not_followed(self):
        self.build()
        os.rename(self.path(), self.path() + ".real")
        os.symlink(self.path() + ".real", self.path())
        with self.assertRaises(KbError):
            self.search()


class StaleTest(SearchCase):
    def test_a_vector_whose_text_no_longer_matches_its_theme_is_left_out_and_counted(self):
        self.build()
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("UPDATE vectors SET text_sha256 = ? WHERE field = 'summary' AND book_id = ?", ("0" * 64, self.b1))
            conn.commit()
        got = self.search()
        self.assertEqual((got["stale"], got["themes_searched"], got["without_vector"]), (1, 2, 0))

    def test_a_damaged_vector_is_left_out_and_counted_and_a_theme_with_none_left_is_counted(self):
        self.build()
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("UPDATE vectors SET vector = zeroblob(16) WHERE book_id = ?", (self.b2,))
            conn.commit()
        got = self.search()
        stored_b2 = sum(1 for v in self.stored() if v[0] == self.b2)
        self.assertEqual((got["stale"], got["themes_searched"], got["without_vector"]), (stored_b2, 1, 1))
        self.assertEqual([r["book_id"] for r in got["results"]], [self.b1])

    def test_a_vector_with_no_theme_row_is_stale(self):
        self.build()
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("DELETE FROM themes WHERE book_id = ?", (self.b2,))
            conn.commit()
        got = self.search()
        self.assertEqual([r["book_id"] for r in got["results"]], [self.b1])
        self.assertGreater(got["stale"], 0)


class CommandTest(SearchCase):
    """`python3 -m kb theme-vectors` and `theme-search`, in this process against the temporary library, with the embedding call replaced."""

    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(with_embedding())
        kbconfig.save(saved)

    def kb(self, *args):
        from engine.tests.test_models import fake_vector

        def embed(cfg, name, texts, launcher=None, root=None, kind="document"):
            self.embedded.append((kind, list(texts)))
            return {"model": "bge-m3:latest", "dimension": 4, "vectors": [fake_vector(x) for x in texts]}

        self.embedded = []
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(models, "embed", embed), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_theme_vectors_builds_and_prints_the_counts_and_a_second_run_sends_nothing(self):
        code, out, err = self.kb("theme-vectors")
        counts = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((counts["built"], counts["themes"], counts["texts_sent"] > 0, counts["replaced"]), (2, 2, True, False))
        self.assertEqual(self.embedded[0][0], "document")
        code, out, err = self.kb("theme-vectors")
        self.assertEqual((code, json.loads(out)["texts_sent"], self.embedded), (0, 0, []))
        code, out, _ = self.kb("theme-vectors", "--again")
        self.assertEqual((code, json.loads(out)["kept"]), (0, 0))

    def test_theme_vectors_exits_with_one_and_says_so_when_a_book_could_not_be_read(self):
        real = theme.read

        def broken(store, book_id, *a, **k):
            if book_id == self.b2:
                raise KbError("damaged")
            return real(store, book_id, *a, **k)

        with unittest.mock.patch.object(theme, "read", broken):
            code, out, err = self.kb("theme-vectors")
        self.assertEqual(code, 1)
        self.assertIn("1 book", err)
        self.assertEqual(json.loads(out)["unreadable"], 1)

    def test_theme_search_prints_the_ranked_themes_and_sends_only_the_query(self):
        self.kb("theme-vectors")
        code, out, err = self.kb("theme-search", "stopping a search when it has cooled")
        found = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((found["themes_searched"], len(found["results"])), (2, 2))
        self.assertEqual(self.embedded, [("query", ["stopping a search when it has cooled"])])
        code, out, _ = self.kb("theme-search", "stopping a search", "--limit", "1")
        self.assertEqual((code, len(json.loads(out)["results"])), (0, 1))

    def test_theme_search_refuses_a_limit_out_of_range_and_a_missing_file_with_the_command_to_run(self):
        code, out, err = self.kb("theme-search", "anything")
        self.assertNotEqual(code, 0)
        self.assertIn("theme-vectors", out + err)
        self.kb("theme-vectors")
        code, out, err = self.kb("theme-search", "anything", "--limit", "99")
        self.assertNotEqual(code, 0)

    def test_the_commands_take_no_model_server_address_or_launcher(self):
        for command in ("theme-vectors", "theme-search"):
            for option in ("--model", "--server", "--address", "--host", "--url", "--launcher", "--bridge"):
                with self.subTest(command=command, option=option):
                    args = (command, "q", option, "x") if command == "theme-search" else (command, option, "x")
                    code, _, _ = self.kb(*args)
                    self.assertEqual(code, 2)

    def test_theme_search_opens_no_book_store_and_theme_vectors_opens_it_to_write(self):
        opened = []
        real = kbmain.Store.open
        with unittest.mock.patch.object(kbmain.Store, "open", side_effect=lambda *a, **k: opened.append((a, k)) or real(*a, **k)):
            self.kb("theme-vectors")
            self.kb("theme-search", "q")
        self.assertEqual(opened, [((), {})])


if __name__ == "__main__":
    unittest.main()
