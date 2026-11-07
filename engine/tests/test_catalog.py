import copy
import json
import os
import sqlite3
import stat
import unittest
from contextlib import closing
from unittest import mock

from engine.tests.test_card import MODEL, CardCase

from kb import KbError, card, catalog, read


class CatalogCase(CardCase):
    def carded(self, title="A paper on stopping", model=None, source=None, filed=True, **kw):
        book, version = self.book(source=source, **kw)
        self.converted(book, version)
        self.store._rewrite(self.store.book_file(book), lambda root: root.__setitem__("title", title))
        if filed:
            card.file(self.store, card.make(self.store, book, version, model=copy.deepcopy(model or MODEL), records=[]))
        return book, version

    def rebuild(self):
        return catalog.rebuild(self.store)

    def path(self):
        return catalog.path_of(self.store.cfg["index_root"])

    def rows(self):
        with closing(sqlite3.connect(self.path())) as conn:
            return conn.execute("SELECT book_id, version_id, generation, is_current, added, citation, card FROM cards "
                                "ORDER BY book_id, version_id").fetchall()

    def match(self, expression):
        with closing(sqlite3.connect(self.path())) as conn:
            return sorted(r[0] for r in conn.execute("SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?", (expression,)))


class RebuildTest(CatalogCase):
    def test_the_newest_card_of_each_version_of_each_active_book_is_in_the_catalog(self):
        one, one_v = self.carded(title="One")
        newer = card.make(self.store, one, one_v, model=dict(copy.deepcopy(MODEL), summary="The newer summary."), records=[])
        card.file(self.store, newer)
        two, two_v = self.carded(title="Two")
        counts = self.rebuild()
        rows = self.rows()
        by_book = {r[0]: r for r in rows}
        self.assertEqual(sorted(by_book), sorted([one, two]))
        self.assertEqual(by_book[one][2], 2)
        self.assertEqual(json.loads(by_book[one][6])["model"]["summary"], "The newer summary.")
        self.assertEqual((counts["books"], counts["versions"], counts["cards"], counts["failed"]), (2, 2, 2, 0))

    def test_a_book_with_two_versions_gets_a_row_for_each_and_marks_the_current_one(self):
        book, v1 = self.carded()
        v2 = self.store.add_version(book, label="v2")
        self.store.file_payload(book, v2, "original", {"page.html": b"<html>y</html>"}, primary="page.html")
        from kb import stages
        stages.mark(self.store, book, v2, "fetched", "done")
        stages.mark(self.store, book, v2, "scanned", "done")
        self.converted(book, v2)
        card.file(self.store, card.make(self.store, book, v2, model=copy.deepcopy(MODEL), records=[]))
        self.rebuild()
        rows = {r[1]: r for r in self.rows()}
        self.assertEqual((rows["v1"][3], rows["v2"][3]), (0, 1))

    def test_a_book_with_no_card_has_no_row(self):
        self.carded(filed=False)
        counts = self.rebuild()
        self.assertEqual(self.rows(), [])
        self.assertEqual((counts["books"], counts["cards"], counts["failed"]), (1, 0, 0))

    def test_a_book_that_is_not_active_is_left_out_and_counted(self):
        book, _ = self.carded()
        self.store.set_state(book, "weeded")
        counts = self.rebuild()
        self.assertEqual(self.rows(), [])
        self.assertEqual((counts["inactive"], counts["books"]), (1, 0))

    def test_a_card_that_fails_its_checks_is_left_out_and_counted_and_the_others_go_on(self):
        good, _ = self.carded(title="Good")
        bad, bad_v = self.carded(title="Bad", filed=False)
        self.store.file_payload(bad, bad_v, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        counts = self.rebuild()
        self.assertEqual([r[0] for r in self.rows()], [good])
        self.assertEqual((counts["cards"], counts["failed"]), (1, 1))

    def test_a_card_of_another_book_in_a_folder_is_left_out(self):
        _, _ = self.carded(title="Real")
        other, other_v = self.carded(title="Other", filed=False)
        real_card = json.dumps(card.make(self.store, other, other_v, records=[])).encode()
        self.store.file_payload(other, other_v, "derived/card/1", {"card.json": real_card.replace(other.encode(), b"01M6SR01QXBXAZ9V8ZHBWPCDAF")},
                                tool="kb-card 1", untrusted=True)
        counts = self.rebuild()
        self.assertEqual(counts["failed"], 1)

    def test_the_full_text_row_belongs_to_the_card_with_the_same_id(self):
        books = [self.carded(title=f"Book {name}", model=dict(copy.deepcopy(MODEL), summary=f"about {name}word")) for name in ("alpha", "beta", "gamma")]
        self.rebuild()
        with closing(sqlite3.connect(self.path())) as conn:
            for name, (book, _) in zip(("alpha", "beta", "gamma"), books):
                (found,) = conn.execute("SELECT c.book_id FROM cards_fts f JOIN cards c ON c.id = f.rowid WHERE cards_fts MATCH ?",
                                        (f'"{name}word"',)).fetchall()
                self.assertEqual(found[0], book)

    def test_a_book_that_cannot_be_read_is_counted_and_the_others_go_on(self):
        good, _ = self.carded(title="Good")
        bad, _ = self.carded(title="Bad")
        real = self.store.version_ids

        def version_ids(book_id):
            if book_id == bad:
                raise KbError("cannot read")
            return real(book_id)

        with mock.patch.object(self.store, "version_ids", side_effect=version_ids):
            counts = self.rebuild()
        self.assertEqual([r[0] for r in self.rows()], [good])
        self.assertEqual((counts["failed"], counts["cards"]), (1, 1))

    def test_a_library_that_is_not_there_at_the_start_gives_no_catalog(self):
        self.carded()
        with mock.patch.object(self.store, "_guard", side_effect=KbError("the library is not there")):
            with self.assertRaises(KbError):
                self.rebuild()
        self.assertFalse(os.path.exists(self.path()))

    def test_every_state_that_keeps_a_book_out_is_left_out(self):
        for state in ("weeded", "removed", "duplicate"):
            book, _ = self.carded(title=state)
            self.store.set_state(book, state)
        kept, _ = self.carded(title="kept")
        counts = self.rebuild()
        self.assertEqual([r[0] for r in self.rows()], [kept])
        self.assertEqual(counts["inactive"], 3)

    def test_the_catalog_file_is_private(self):
        self.carded()
        self.rebuild()
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)

    def test_the_date_added_is_kept_only_if_it_has_the_shape_of_a_date(self):
        good, _ = self.carded(title="Good")
        bad, _ = self.carded(title="Bad")
        self.store._rewrite(self.store.book_file(bad), lambda root: root.__setitem__("added", "an untrusted text \x1b[31m"))
        self.rebuild()
        by_book = {r[0]: r[4] for r in self.rows()}
        self.assertRegex(by_book[good], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T")
        self.assertEqual(by_book[bad], "")

    def test_building_it_again_or_after_the_file_is_deleted_gives_the_same_catalog(self):
        self.carded(title="One")
        self.carded(title="Two")
        self.rebuild()
        first = self.rows()
        self.rebuild()
        self.assertEqual(self.rows(), first)
        os.remove(self.path())
        self.rebuild()
        self.assertEqual(self.rows(), first)

    def test_it_is_built_from_the_book_folders_and_not_from_the_search_index(self):
        self.carded()
        self.rebuild()
        self.assertFalse(os.path.exists(os.path.join(self.store.cfg["index_root"], "search.sqlite")))

    def test_the_stored_card_is_the_card_that_was_read(self):
        book, version = self.carded()
        self.rebuild()
        (row,) = self.rows()
        self.assertEqual(json.loads(row[6]), card.read(self.store, book, version)[1])
        self.assertEqual(row[4], self.store.read_book(book)["added"])
        self.assertEqual(row[5], catalog.citation_of(card.read(self.store, book, version)[1]))
        self.assertTrue(row[5].startswith('"A paper on stopping".'))

    def test_a_card_with_no_model_part_is_in_the_catalog_and_found_by_its_title(self):
        book, version = self.book()
        self.store._rewrite(self.store.book_file(book), lambda root: root.__setitem__("title", "Zymurgy of barley"))
        card.file(self.store, card.make(self.store, book, version))
        self.rebuild()
        (row,) = self.rows()
        self.assertEqual(self.match('title : "zymurgy"'), [1])
        self.assertEqual(self.match('summary : "zymurgy"'), [])
        self.assertIsNone(json.loads(row[6])["model"])

    def test_every_text_field_of_a_card_is_searchable_in_its_own_column(self):
        words = {"summary": "summaryword", "uses": "usesword", "topics": "topicsword", "adjacent": "adjacentword", "ideas": "ideasword",
                 "n_problem": "problemword", "n_approach": "approachword", "n_needs": "needsword", "n_provides": "providesword",
                 "n_limits": "limitsword", "caveats": "caveatsword"}
        model = {"summary": "about summaryword", "useful_for": ["a usesword here"], "topics": ["topicsword"], "adjacent_topics": ["adjacentword"],
                 "key_ideas": ["ideasword one", "two", "three"], "neutral_problem": "problemword", "neutral_approach": "approachword",
                 "neutral_needs": "needsword", "neutral_provides": "providesword", "neutral_limits": "limitsword",
                 "caveats": ["caveatsword"]}
        self.carded(title="Titleword here", model=model)
        self.rebuild()
        self.assertEqual(self.match('title : "titleword"'), [1])
        for column, word in words.items():
            with self.subTest(column=column):
                self.assertEqual(self.match(f'{column} : "{word}"'), [1])
                self.assertEqual(self.match(f'"{word}"'), [1])

    def test_a_word_is_found_without_its_accents(self):
        self.carded(title="Théorie des jeux")
        self.rebuild()
        self.assertEqual(self.match('"theorie"'), [1])

    def test_the_stale_files_of_the_old_catalog_are_removed(self):
        self.carded()
        self.rebuild()
        for suffix in ("-journal", "-wal", "-shm"):
            with open(self.path() + suffix, "w") as f:
                f.write("stale")
        self.rebuild()
        for suffix in ("-journal", "-wal", "-shm", ".new"):
            self.assertFalse(os.path.exists(self.path() + suffix), suffix)


class FailureTest(CatalogCase):
    def test_a_failure_while_building_leaves_the_old_catalog_as_it_was(self):
        self.carded(title="One")
        self.rebuild()
        before = self.rows()
        self.carded(title="Two")
        with mock.patch.object(catalog, "_insert", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(KbError):
                self.rebuild()
        self.assertEqual(self.rows(), before)
        self.assertFalse(os.path.exists(self.path() + ".new"))

    def test_a_library_that_goes_away_before_the_catalog_is_put_in_place_leaves_the_old_one(self):
        self.carded(title="One")
        self.rebuild()
        before = self.rows()
        self.carded(title="Two")
        real = self.store._guard
        calls = []

        def guard():
            calls.append(1)
            if len(calls) > 1:
                raise KbError("the library is not there")
            real()

        with mock.patch.object(self.store, "_guard", side_effect=guard):
            with self.assertRaises(KbError):
                self.rebuild()
        self.assertEqual(self.rows(), before)

    def test_a_second_writer_waits_for_the_first_and_then_gives_up(self):
        self.carded()
        with catalog.lock(self.store.cfg["index_root"]):
            with mock.patch.object(catalog, "LOCK_WAIT", 0.2):
                with self.assertRaises(KbError) as cm:
                    self.rebuild()
        self.assertIn("another", str(cm.exception))
        self.rebuild()  # and builds when the first has finished

    def test_the_lock_file_is_private_and_a_link_in_its_place_is_refused(self):
        root = self.store.cfg["index_root"]
        with catalog.lock(root):
            pass
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(root, catalog.LOCK_FILE)).st_mode), 0o600)
        os.remove(os.path.join(root, catalog.LOCK_FILE))
        target = os.path.join(self.base, "elsewhere")
        with open(target, "w") as f:
            f.write("x")
        os.symlink(target, os.path.join(root, catalog.LOCK_FILE))
        with self.assertRaises(KbError):
            with catalog.lock(root):
                pass


class ConnectTest(CatalogCase):
    def setUp(self):
        super().setUp()
        self.carded()
        self.rebuild()

    def test_a_good_catalog_opens_read_only(self):
        with closing(catalog.connect(self.path(), readonly=True)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM cards")

    def test_a_catalog_of_another_format_is_refused_with_the_command_to_run(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute(f"PRAGMA user_version = {catalog.FORMAT + 1}")
            conn.commit()
        with self.assertRaises(KbError) as cm:
            catalog.connect(self.path(), readonly=True)
        self.assertIn("card-index", str(cm.exception))

    def test_a_catalog_with_a_trigger_or_a_view_is_refused(self):
        for statement in ("CREATE TRIGGER t AFTER INSERT ON cards BEGIN SELECT 1; END", "CREATE VIEW v AS SELECT 1"):
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute(statement)
                conn.commit()
            with self.subTest(statement=statement), self.assertRaises(KbError) as cm:
                catalog.connect(self.path(), readonly=True)
            self.assertIn("card-index", str(cm.exception))
            self.rebuild()  # a rebuild replaces it

    def test_a_file_that_is_not_a_database_or_is_missing_is_refused(self):
        with open(self.path(), "wb") as f:
            f.write(b"this is not a database at all" * 10)
        with self.assertRaises(KbError):
            catalog.connect(self.path(), readonly=True)
        os.remove(self.path())
        with self.assertRaises(KbError) as cm:
            catalog.connect(self.path(), readonly=True)
        self.assertIn("card-index", str(cm.exception))

    def test_a_catalog_whose_tables_are_not_the_ones_this_engine_makes_is_refused(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("DROP TABLE cards")
            conn.execute("CREATE TABLE cards (x TEXT)")
            conn.commit()
        with self.assertRaises(KbError) as cm:
            catalog.connect(self.path(), readonly=True)
        self.assertIn("card-index", str(cm.exception))
        self.rebuild()
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("DROP TABLE cards_fts")
            conn.execute("CREATE TABLE cards_fts (title TEXT)")
            conn.commit()
        with self.assertRaises(KbError) as cm:
            catalog.connect(self.path(), readonly=True)
        self.assertIn("card-index", str(cm.exception))

    def test_a_catalog_missing_a_table_is_refused(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("DROP TABLE cards_fts")
            conn.commit()
        with self.assertRaises(KbError):
            catalog.connect(self.path(), readonly=True)


class CitationTest(CatalogCase):
    def citation(self, **source):
        book, version = self.carded(source=source)
        made = card.read(self.store, book, version)[1]
        return catalog.citation_of(made), read._citation(self.store, self.store.read_book(book), self.store.read_version(book, version))

    def test_a_web_page_has_the_citation_a_read_gives(self):
        mine, theirs = self.citation(address_final="https://example.org/a", retrieved="2026-11-01T00:00:00+00:00", sha256="ab" * 32)
        self.assertEqual(mine, theirs)
        self.assertIn("https://example.org/a", mine)
        self.assertIn("Retrieved 2026-11-01", mine)

    def test_an_arxiv_paper_has_the_citation_a_read_gives_without_the_pdf_address(self):
        mine, theirs = self.citation(arxiv_id="2101.00001", label="v2", address_pdf="https://arxiv.org/pdf/2101.00001v2",
                                     retrieved="2026-11-01T00:00:00+00:00", sha256="cd" * 32)
        self.assertIn(", https://arxiv.org/pdf/2101.00001v2.", theirs)
        self.assertEqual(mine, theirs.replace(", https://arxiv.org/pdf/2101.00001v2", ""))
        self.assertIn("arXiv:2101.00001v2", mine)

    def test_a_source_with_nothing_recorded(self):
        mine, theirs = self.citation()
        self.assertEqual(mine, theirs)
        self.assertIn("no source address recorded", mine)
        self.assertIn("date not recorded", mine)
        self.assertIn("hash not recorded", mine)

    def test_the_title_cannot_close_its_quotation_marks_or_escape_them(self):
        book, version = self.carded(title='Say "hello" and end with a backslash \\', source={"address_final": "https://example.org/a"})
        mine = catalog.citation_of(card.read(self.store, book, version)[1])
        theirs = read._citation(self.store, self.store.read_book(book), self.store.read_version(book, version))
        self.assertEqual(mine, theirs)
        self.assertNotIn('"hello"', mine)
        self.assertTrue(mine.startswith('"Say '))

    def test_where_the_citation_differs_from_a_reads_in_odd_cases(self):
        """A card keeps only a web address with no user name and cuts it at 300 characters, so in these cases the line differs."""
        mine, theirs = self.citation(address_final="ftp://example.org/x", address_asked="https://example.org/a")
        self.assertIn("non-web address", theirs)  # a read takes the final address, which is not a web address
        self.assertIn("https://example.org/a", mine)  # the card dropped it and kept the address that was asked for
        mine, theirs = self.citation(address_final="ftp://example.org/x")
        self.assertIn("non-web address", theirs)
        self.assertIn("no source address recorded", mine)
        long = "https://example.org/" + "a" * 380
        mine, theirs = self.citation(address_final=long)
        self.assertIn(long, theirs)
        self.assertIn(long[:300], mine)
        self.assertNotIn(long, mine)

    def test_a_title_with_the_words_of_a_marker_gives_untitled(self):
        book, version = self.carded(title="An untrusted text title", source={"address_final": "https://example.org/a"})
        mine = catalog.citation_of(card.read(self.store, book, version)[1])
        self.assertTrue(mine.startswith('"untitled".'))


if __name__ == "__main__":
    unittest.main()
