"""The vectors of the themes: the file in the index root, built from the cards and the themes of the active books."""
import builtins
import copy
import fcntl
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

from kb import KbError, card, catalog, convert, models, theme, themecheck, themevectors

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

    def themed(self, rows=None, title=None):
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
        theme.file(self.store, got["generation"])
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

    def test_a_heading_cannot_make_a_level_of_its_own(self):
        line = themevectors.citation_line(self.BASE, ["A > B"])
        self.assertTrue(line.endswith("Section [A  B]. Language: not recorded"), line)

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
        for statement in ("UPDATE vectors SET field = 'bogus' WHERE field = 'summary'", "UPDATE vectors SET theme_id = 'x' WHERE field = 'summary'",
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


if __name__ == "__main__":
    unittest.main()
