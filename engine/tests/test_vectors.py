import copy
import hashlib
import json
import math
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import unittest
from contextlib import closing
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_card import MODEL, RECORD, SENTENCE_MODEL, grounding, sentences_of
from engine.tests.test_catalog import CatalogCase
from engine.tests.test_models import FAKE_EMBED, config, embedding, fake_vector

from kb import KbError, card, catalog, models, vectors

SEARCHED = ("neutral_problem", "neutral_approach", "neutral_provides")


def with_embedding(**over):
    cfg = config(emb=embedding(**over))
    cfg["tasks"] = {"card-embed": "emb"}
    return cfg


class VectorCase(CatalogCase):
    """Books with cards in a fixture library, and a fake `embed` bridge that answers with a vector made from the text."""

    def setUp(self):
        super().setUp()
        self.launcher = os.path.join(self.base, "wb")
        with open(self.launcher, "w") as f:
            f.write(FAKE_EMBED.format(python=sys.executable))
        os.chmod(self.launcher, 0o700)
        self.plan()
        self.mcfg = with_embedding()

    def plan(self, **p):
        with open(os.path.join(self.base, "plan.json"), "w") as f:
            json.dump(p, f)

    def sent(self):
        path = os.path.join(self.base, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [t for line in f for t in json.loads(json.loads(line)["stdin"])["texts"]]

    def calls(self):
        path = os.path.join(self.base, "calls.jsonl")
        if not os.path.exists(path):
            return 0
        with open(path) as f:
            return len(f.readlines())

    def build(self, cfg=None, **kw):
        return vectors.build(self.store, cfg or self.mcfg, launcher=self.launcher, **kw)

    def path(self):
        return vectors.path_of(self.store.cfg["index_root"])

    def stored(self):
        with closing(sqlite3.connect(self.path())) as conn:
            rows = conn.execute("SELECT book_id, version_id, generation, field, text_sha256, vector FROM vectors "
                                "ORDER BY book_id, version_id, field").fetchall()
        return [(b, v, g, f, h, list(struct.unpack(f"<{len(blob) // 4}f", blob))) for b, v, g, f, h, blob in rows]

    def meta(self):
        with closing(sqlite3.connect(self.path())) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())

    def model_with(self, tag, **over):
        model = copy.deepcopy(MODEL)
        model.update(neutral_problem=f"{tag} problem", neutral_approach=f"{tag} approach", neutral_needs=f"{tag} needs",
                     neutral_provides=f"{tag} provides", neutral_limits=f"{tag} limits")
        model.update(over)
        return model

    def sentence_card(self, book=None, version=None, title="Sentences", **over):
        """A card in which the model part has sentences, the one form in which a neutral field can be empty; filed for a new book, or
        as the next generation of the book and version given."""
        model = copy.deepcopy(SENTENCE_MODEL)
        model.update(over)
        record = grounding(model)
        record["neutral_limits"] = None
        record["sentences"] = sentences_of(model)
        if book is None:
            book, version = self.carded(title=title, filed=False)
        card.file(self.store, card.make(self.store, book, version, model=model, records=[dict(RECORD)], pieces=1, calls=1, grounding=record))
        return book, version

    def two(self):
        one = self.carded(title="One", model=self.model_with("one"))
        two = self.carded(title="Two", model=self.model_with("two"))
        return one, two


class BuildTest(VectorCase):
    def test_a_vector_is_made_for_each_searched_field_of_each_card_and_for_no_other_field(self):
        (one, one_v), (two, two_v) = self.two()
        counts = self.build()
        rows = self.stored()
        self.assertEqual(sorted((b, f) for b, _, _, f, _, _ in rows), sorted((b, f) for b in (one, two) for f in SEARCHED))
        for book, version, generation, field, sha, vector in rows:
            text = f"{'one' if book == one else 'two'} {field.split('_')[1]}"
            self.assertEqual(sha, hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(generation, 1)
            for a, b in zip(vector, fake_vector(text)):
                self.assertAlmostEqual(a, b, places=6)
        self.assertEqual((counts["cards"], counts["vectors"], counts["kept"], counts["made"], counts["texts_sent"], counts["left_out"]),
                         (2, 6, 0, 6, 6, 0))

    def test_the_needs_and_the_limits_are_never_embedded_or_sent(self):
        self.two()
        self.build()
        self.assertEqual(sorted(self.sent()), sorted(f"{t} {f}" for t in ("one", "two") for f in ("problem", "approach", "provides")))
        self.assertFalse(any("needs" in t or "limits" in t for t in self.sent()))
        self.assertEqual({r[3] for r in self.stored()}, set(SEARCHED))

    def test_the_store_says_which_model_made_the_vectors(self):
        self.two()
        self.build()
        meta = self.meta()
        self.assertEqual((meta["model"], meta["configured"], meta["dimension"], meta["format"]), ("bge-m3:latest", "bge-m3:latest", "4", "1"))
        self.assertRegex(meta["built"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T")

    def test_the_store_is_private(self):
        self.two()
        self.build()
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)

    def test_a_card_with_no_model_part_and_an_empty_or_blank_field_make_no_row(self):
        book, version = self.book()
        card.file(self.store, card.make(self.store, book, version))  # a card from the metadata, with no model part
        self.sentence_card(title="Thin", neutral_provides="", neutral_approach="")
        counts = self.build()
        self.assertEqual([r[3] for r in self.stored()], ["neutral_problem"])
        self.assertEqual((counts["cards"], counts["no_model"], counts["vectors"]), (2, 1, 1))

    def test_a_book_that_is_not_active_is_left_out(self):
        book, _ = self.carded(title="Gone", model=self.model_with("gone"))
        self.carded(title="Kept", model=self.model_with("kept"))
        self.store.set_state(book, "weeded")
        self.build()
        self.assertEqual({r[0] for r in self.stored()} & {book}, set())
        self.assertEqual(len(self.stored()), 3)

    def test_a_card_that_fails_its_checks_is_left_out_and_counted_and_the_others_go_on(self):
        self.carded(title="Good", model=self.model_with("good"))
        bad, bad_v = self.carded(title="Bad", filed=False)
        self.store.file_payload(bad, bad_v, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        counts = self.build()
        self.assertEqual((counts["left_out"], counts["cards"], counts["vectors"]), (1, 1, 3))

    def test_the_newest_card_of_a_version_is_the_one_embedded(self):
        book, version = self.carded(title="One", model=self.model_with("old"))
        card.file(self.store, card.make(self.store, book, version, model=self.model_with("new"), records=[]))
        self.build()
        self.assertEqual({r[2] for r in self.stored()}, {2})
        self.assertEqual(sorted(self.sent()), sorted(f"new {f}" for f in ("problem", "approach", "provides")))

    def test_the_text_of_a_field_is_sent_as_the_card_holds_it(self):
        book, version = self.carded(title="One", model=self.model_with("one", neutral_problem="  spaced  \n text "))
        held = card.read(self.store, book, version)[1]["model"]
        self.build()
        self.assertIn(held["neutral_problem"], self.sent())
        self.assertEqual(sorted(self.sent()), sorted(held[f] for f in SEARCHED))

    def test_nothing_is_stored_when_there_is_nothing_to_embed(self):
        self.sentence_card(title="Thin", neutral_problem="", neutral_approach="", neutral_provides="")
        counts = self.build()
        self.assertEqual((counts["vectors"], counts["texts_sent"], self.calls()), (0, 0, 0))
        self.assertEqual(self.stored(), [])


class KeepTest(VectorCase):
    def test_building_again_makes_the_same_rows_and_sends_no_text(self):
        self.two()
        self.build()
        first, sent = self.stored(), len(self.sent())
        counts = self.build()
        self.assertEqual(self.stored(), first)
        self.assertEqual(len(self.sent()), sent)
        self.assertEqual((counts["kept"], counts["made"], counts["texts_sent"]), (6, 0, 0))

    def test_a_deleted_store_is_built_again_the_same(self):
        self.two()
        self.build()
        first = self.stored()
        os.remove(self.path())
        self.build()
        self.assertEqual(self.stored(), first)

    def test_a_card_whose_text_changed_gets_a_new_vector_and_the_others_keep_theirs(self):
        (one, one_v), (two, two_v) = self.two()
        self.build()
        before = {(r[0], r[3]): r for r in self.stored()}
        card.file(self.store, card.make(self.store, one, one_v, model=self.model_with("one", neutral_approach="a changed approach"), records=[]))
        calls = len(self.sent())
        counts = self.build()
        after = {(r[0], r[3]): r for r in self.stored()}
        self.assertEqual(self.sent()[calls:], ["a changed approach"])
        self.assertEqual((counts["kept"], counts["made"], counts["texts_sent"]), (5, 1, 1))
        self.assertNotEqual(after[(one, "neutral_approach")][4], before[(one, "neutral_approach")][4])
        for key in before:
            if key != (one, "neutral_approach"):
                self.assertEqual(after[key][4:], before[key][4:])
        self.assertEqual({r[2] for k, r in after.items() if k[0] == one}, {2})  # the generation is the new card's, vectors kept or not
        self.assertEqual({r[2] for k, r in after.items() if k[0] == two}, {1})

    def test_a_field_that_became_empty_loses_its_row_and_a_card_that_is_gone_loses_its_rows(self):
        (one, one_v), (two, _) = self.two()
        self.build()
        self.sentence_card(one, one_v, neutral_problem="one problem", neutral_approach="one approach", neutral_provides="")
        self.store.set_state(two, "weeded")
        counts = self.build()
        self.assertEqual(sorted((r[0], r[3]) for r in self.stored()), sorted((one, f) for f in ("neutral_problem", "neutral_approach")))
        self.assertEqual((counts["made"], counts["vectors"]), (0, 2))

    def test_again_makes_every_vector_again(self):
        self.two()
        self.build()
        sent = len(self.sent())
        counts = self.build(again=True)
        self.assertEqual(len(self.sent()) - sent, 6)
        self.assertEqual((counts["kept"], counts["made"]), (0, 6))

    def test_a_row_with_a_damaged_vector_is_not_kept(self):
        self.two()
        self.build()
        with closing(sqlite3.connect(self.path())) as conn:
            rows = conn.execute("SELECT rowid, vector FROM vectors ORDER BY rowid").fetchall()
            conn.execute("UPDATE vectors SET vector = ? WHERE rowid = ?", (rows[0][1][:-1], rows[0][0]))                    # the wrong length
            conn.execute("UPDATE vectors SET vector = ? WHERE rowid = ?", (struct.pack("<4f", 0, 0, 0, 0), rows[1][0]))       # zeros
            conn.execute("UPDATE vectors SET vector = ? WHERE rowid = ?", (struct.pack("<4f", math.nan, 1, 1, 1), rows[2][0]))  # not finite
            conn.execute("UPDATE vectors SET vector = ? WHERE rowid = ?", (struct.pack("<4f", math.inf, 1, 1, 1), rows[3][0]))
            conn.commit()
        calls = len(self.sent())
        counts = self.build()
        self.assertEqual((counts["kept"], counts["made"]), (2, 4))
        self.assertEqual(len(self.sent()) - calls, 4)
        self.assertTrue(all(all(math.isfinite(x) for x in r[5]) and any(r[5]) for r in self.stored()))

    def test_a_row_with_a_wrong_text_hash_is_not_kept(self):
        self.two()
        self.build()
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("UPDATE vectors SET text_sha256 = ?", ("0" * 64,))
            conn.commit()
        counts = self.build()
        self.assertEqual((counts["kept"], counts["made"]), (0, 6))

    def test_a_vector_of_a_changed_text_is_never_kept_for_the_new_text(self):
        (one, one_v), _ = self.two()
        self.build()
        old = {r[3]: r[5] for r in self.stored() if r[0] == one}
        card.file(self.store, card.make(self.store, one, one_v, model=self.model_with("one", neutral_problem="something else entirely"), records=[]))
        self.build()
        new = {r[3]: r[5] for r in self.stored() if r[0] == one}
        self.assertNotEqual(new["neutral_problem"], old["neutral_problem"])
        for a, b in zip(new["neutral_problem"], fake_vector("something else entirely")):
            self.assertAlmostEqual(a, b, places=6)


class ForeignStoreTest(VectorCase):
    """An existing file that this engine did not make, or that another model made, is not reused: the build replaces it."""

    def setUp(self):
        super().setUp()
        self.two()
        self.build()
        self.first = self.stored()

    def assertReplaced(self, counts):
        self.assertEqual((counts["kept"], counts["made"]), (0, 6))
        self.assertTrue(counts["replaced"])
        self.assertEqual([r[:5] for r in self.stored()], [r[:5] for r in self.first])
        with closing(vectors.connect(self.path(), readonly=True)) as conn:
            conn.execute("SELECT 1 FROM vectors").fetchall()

    def test_a_store_of_another_format_is_replaced(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute(f"PRAGMA user_version = {vectors.FORMAT + 1}")
            conn.commit()
        self.assertReplaced(self.build())

    def test_a_store_with_a_trigger_a_view_or_another_table_is_replaced(self):
        for statement in ("CREATE TRIGGER t AFTER INSERT ON vectors BEGIN SELECT 1; END", "CREATE VIEW v AS SELECT 1",
                          "CREATE TABLE extra (x TEXT)"):
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute(statement)
                conn.commit()
            with self.subTest(statement=statement):
                self.assertReplaced(self.build())

    def test_a_file_that_is_not_a_database_is_replaced(self):
        with open(self.path(), "wb") as f:
            f.write(b"this is not a database at all" * 10)
        self.assertReplaced(self.build())

    def test_a_store_made_for_another_dimension_or_another_configured_model_is_replaced(self):
        for key, value in (("dimension", "5"), ("configured", "another-model:1")):
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
                conn.commit()
            with self.subTest(key=key):
                self.assertReplaced(self.build())

    def test_a_change_of_the_configured_entry_replaces_the_store(self):
        cfg = with_embedding(model="other-model:1")
        counts = self.build(cfg=cfg)
        self.assertEqual((counts["kept"], counts["made"], counts["replaced"]), (0, 6, True))
        self.assertEqual(self.meta()["configured"], "other-model:1")

    def test_a_meta_table_with_odd_values_is_not_trusted_and_the_store_is_replaced_without_a_traceback(self):
        for key, value in (("dimension", "²"), ("dimension", "４"), ("dimension", "99999"), ("dimension", ""), ("dimension", "0"),
                           ("dimension", "8193"), ("model", b"blob"), ("model", "a b"), ("model", ""), ("configured", b"blob"),
                           ("built", b"blob"), ("built", "x" * 41), ("format", "01")):
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
                conn.commit()
            with self.subTest(key=key, value=value):
                self.assertReplaced(self.build())

    def test_a_good_store_is_not_called_replaced(self):
        self.assertFalse(self.build()["replaced"])

    def test_the_model_the_bridge_reports_must_be_the_one_in_the_store_when_rows_are_kept(self):
        (one, one_v) = next(iter({(r[0], r[1]) for r in self.first}))
        card.file(self.store, card.make(self.store, one, one_v, model=self.model_with("one", neutral_problem="changed"), records=[]))
        self.plan(model="other-model:2")
        before = self.stored()
        with self.assertRaises(KbError) as cm:
            self.build()
        self.assertIn("--again", str(cm.exception))
        self.assertEqual(self.stored(), before)
        counts = self.build(again=True)  # every vector made again by the one model: nothing is mixed
        self.assertEqual(self.meta()["model"], "other-model:2")
        self.assertEqual((counts["kept"], counts["made"]), (0, 6))


class ConnectTest(VectorCase):
    """The checks of a store when it is opened, which the search of Increment D relies on."""

    def setUp(self):
        super().setUp()
        self.two()
        self.build()

    def test_a_good_store_opens_read_only_and_its_rows_are_read_and_checked(self):
        entry = models.registry(self.mcfg)["emb"]
        with closing(vectors.connect(self.path(), readonly=True)) as conn:
            vectors.check_entry(conn, entry)
            rows = vectors.read_rows(conn, 4)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM vectors")
        self.assertEqual(len(rows), 6)
        self.assertEqual(set(rows[0]), {"book_id", "version_id", "generation", "field", "text_sha256", "vector"})
        self.assertTrue(all(len(r["vector"]) == 4 and r["field"] in SEARCHED for r in rows))

    def test_a_store_of_another_format_is_refused_with_the_command_to_run(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute(f"PRAGMA user_version = {vectors.FORMAT + 1}")
            conn.commit()
        with self.assertRaises(KbError) as cm:
            vectors.connect(self.path(), readonly=True)
        self.assertIn("card-vectors", str(cm.exception))

    def test_a_store_with_a_trigger_a_view_or_another_table_is_refused(self):
        for statement in ("CREATE TRIGGER t AFTER INSERT ON vectors BEGIN SELECT 1; END", "CREATE VIEW v AS SELECT 1", "CREATE TABLE extra (x TEXT)"):
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute(statement)
                conn.commit()
            with self.subTest(statement=statement), self.assertRaises(KbError) as cm:
                vectors.connect(self.path(), readonly=True)
            self.assertIn("card-vectors", str(cm.exception))
            self.build()

    def test_a_missing_file_or_one_that_is_not_a_database_is_refused(self):
        with open(self.path(), "wb") as f:
            f.write(b"this is not a database at all" * 10)
        with self.assertRaises(KbError):
            vectors.connect(self.path(), readonly=True)
        os.remove(self.path())
        with self.assertRaises(KbError) as cm:
            vectors.connect(self.path(), readonly=True)
        self.assertIn("card-vectors", str(cm.exception))

    def test_a_link_in_place_of_the_store_is_refused_even_when_it_leads_to_a_good_store(self):
        elsewhere = os.path.join(self.base, "elsewhere.sqlite")
        os.rename(self.path(), elsewhere)
        os.symlink(elsewhere, self.path())
        with self.assertRaises(KbError) as cm:
            vectors.connect(self.path(), readonly=True)
        self.assertIn("card-vectors", str(cm.exception))
        with closing(vectors.connect(elsewhere, readonly=True)) as conn:  # the same file, not as a link, is good
            self.assertEqual(len(vectors.read_rows(conn, 4)), 6)

    def test_a_store_whose_tables_are_not_the_ones_this_engine_makes_is_refused(self):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute("DROP TABLE vectors")
            conn.execute("CREATE TABLE vectors (x TEXT)")
            conn.commit()
        with self.assertRaises(KbError):
            vectors.connect(self.path(), readonly=True)

    def test_a_store_of_another_model_or_dimension_is_refused_for_the_entry_that_is_set(self):
        for key, value in (("dimension", "5"), ("configured", "another-model:1")):
            self.build(again=True)
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
                conn.commit()
            with self.subTest(key=key), closing(vectors.connect(self.path(), readonly=True)) as conn:
                with self.assertRaises(KbError) as cm:
                    vectors.check_entry(conn, models.registry(self.mcfg)["emb"])
                self.assertIn("card-vectors", str(cm.exception))

    def test_a_meta_table_with_odd_values_is_refused_for_the_entry(self):
        for key, value in (("dimension", "²"), ("dimension", "4.0"), ("dimension", "0"), ("dimension", "8193"), ("model", b"blob"),
                           ("model", "a b"), ("configured", b"blob"), ("built", "x" * 41), ("format", "2")):
            self.build(again=True)
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute("UPDATE meta SET value = ? WHERE key = ?", (value, key))
                conn.commit()
            with self.subTest(key=key, value=value), closing(vectors.connect(self.path(), readonly=True)) as conn:
                with self.assertRaises(KbError):
                    vectors.check_entry(conn, models.registry(self.mcfg)["emb"])

    def test_a_stored_vector_that_is_not_a_vector_of_the_entry_is_refused_when_rows_are_read(self):
        for blob in (b"\x00" * 7, struct.pack("<4f", 0, 0, 0, 0), struct.pack("<4f", math.nan, 1, 1, 1), struct.pack("<3f", 1, 1, 1)):
            self.build(again=True)
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute("UPDATE vectors SET vector = ? WHERE rowid = 1", (blob,))
                conn.commit()
            with self.subTest(blob=blob), closing(vectors.connect(self.path(), readonly=True)) as conn:
                with self.assertRaises(KbError) as cm:
                    vectors.read_rows(conn, 4)
                self.assertIn("card-vectors", str(cm.exception))

    def test_a_row_with_a_field_that_is_not_searched_or_a_bad_hash_is_refused_when_rows_are_read(self):
        for column, value in (("field", "neutral_needs"), ("text_sha256", "nope"), ("generation", 0)):
            self.build(again=True)
            with closing(sqlite3.connect(self.path())) as conn:
                conn.execute(f"UPDATE vectors SET {column} = ? WHERE rowid = 1", (value,))
                conn.commit()
            with self.subTest(column=column), closing(vectors.connect(self.path(), readonly=True)) as conn:
                with self.assertRaises(KbError):
                    vectors.read_rows(conn, 4)


class SafetyTest(VectorCase):
    def test_a_failure_while_building_leaves_the_old_store_as_it_was_and_no_half_built_file(self):
        self.carded(title="One", model=self.model_with("one"))
        self.build()
        before = self.stored()
        self.carded(title="Two", model=self.model_with("two"))
        with mock.patch.object(vectors, "_insert", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(KbError):
                self.build()
        self.assertEqual(self.stored(), before)
        self.assertFalse(os.path.exists(self.path() + ".new"))

    def test_the_new_file_is_private_from_the_moment_it_holds_anything(self):
        self.carded(title="One", model=self.model_with("one"))
        modes = []
        real = vectors._insert

        def insert(conn, meta, rows):
            modes.append(stat.S_IMODE(os.stat(self.path() + ".new").st_mode))
            return real(conn, meta, rows)

        with mock.patch.object(vectors, "_insert", insert):
            self.build()
        self.assertEqual(modes, [0o600])

    def test_a_text_that_cannot_be_sent_leaves_its_card_out_and_counts_it_and_the_others_go_on(self):
        self.two()
        real = card.read

        def read(store, book_id, version_id, generation=None):
            number, made = real(store, book_id, version_id, generation)
            if made["title"] == "One":
                made["model"]["neutral_problem"] = "a\ud800b"
            return number, made

        with mock.patch.object(card, "read", read):
            counts = self.build()
        self.assertEqual((counts["left_out"], counts["cards"], counts["vectors"]), (1, 1, 3))

    def test_a_failure_with_no_old_store_leaves_no_file(self):
        self.carded(title="One", model=self.model_with("one"))
        with mock.patch.object(vectors, "_insert", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(KbError):
                self.build()
        self.assertEqual(os.listdir(self.store.cfg["index_root"]).count("vectors.sqlite"), 0)
        self.assertFalse(os.path.exists(self.path() + ".new"))

    def test_a_wrong_reply_of_the_bridge_changes_nothing(self):
        self.carded(title="One", model=self.model_with("one"))
        self.build()
        before = self.stored()
        self.carded(title="Two", model=self.model_with("two"))
        self.plan(mode="short")
        with self.assertRaises(KbError):
            self.build()
        self.assertEqual(self.stored(), before)
        self.assertFalse(os.path.exists(self.path() + ".new"))

    def test_a_library_that_is_not_there_at_the_start_gives_no_store_and_sends_nothing(self):
        self.carded(title="One", model=self.model_with("one"))
        with mock.patch.object(self.store, "_guard", side_effect=KbError("the library is not there")):
            with self.assertRaises(KbError):
                self.build()
        self.assertFalse(os.path.exists(self.path()))
        self.assertEqual(self.sent(), [])

    def test_a_library_that_goes_away_before_the_store_is_put_in_place_leaves_the_old_one(self):
        self.carded(title="One", model=self.model_with("one"))
        self.build()
        before = self.stored()
        self.carded(title="Two", model=self.model_with("two"))
        real, calls = self.store._guard, []

        def guard():
            calls.append(1)
            if len(calls) > 1:
                raise KbError("the library is not there")
            real()

        with mock.patch.object(self.store, "_guard", side_effect=guard):
            with self.assertRaises(KbError):
                self.build()
        self.assertEqual(self.stored(), before)

    def test_a_second_writer_waits_for_the_first_and_then_gives_up(self):
        self.carded(title="One", model=self.model_with("one"))
        with catalog.lock(self.store.cfg["index_root"]):
            with mock.patch.object(catalog, "LOCK_WAIT", 0.2):
                with self.assertRaises(KbError) as cm:
                    self.build()
        self.assertIn("another", str(cm.exception))
        self.assertFalse(os.path.exists(self.path()))
        self.build()  # and builds when the first has finished

    def test_stale_files_of_the_old_store_are_removed(self):
        self.carded(title="One", model=self.model_with("one"))
        self.build()
        for suffix in ("-journal", "-wal", "-shm"):
            with open(self.path() + suffix, "wb") as f:
                f.write(b"stale")
        self.build(again=True)
        for suffix in ("-journal", "-wal", "-shm"):
            self.assertFalse(os.path.exists(self.path() + suffix))

    def test_a_link_or_a_folder_where_the_store_goes_is_not_followed(self):
        self.carded(title="One", model=self.model_with("one"))
        target = os.path.join(self.base, "elsewhere")
        with open(target, "w") as f:
            f.write("keep")
        os.symlink(target, self.path())
        self.build()
        self.assertFalse(os.path.islink(self.path()))
        with open(target) as f:
            self.assertEqual(f.read(), "keep")

    def test_the_vectors_come_in_chunks_that_fit_in_memory_and_the_result_is_the_same(self):
        self.two()
        self.build()
        whole = self.stored()
        calls = self.calls()
        with mock.patch.object(models, "MAX_EMBED_NUMBERS", 8):  # two texts of four numbers at a time
            counts = self.build(again=True)
        self.assertEqual(self.stored(), whole)
        self.assertEqual(self.calls() - calls, 3)
        self.assertEqual(counts["made"], 6)


class RefusalTest(VectorCase):
    def test_a_build_with_no_embedding_entry_set_is_refused_with_the_key_and_sends_nothing(self):
        self.two()
        cfg = config(emb=embedding())
        with self.assertRaises(KbError) as cm:
            self.build(cfg=cfg)
        self.assertIn("tasks.card-embed", str(cm.exception))
        self.assertEqual(self.sent(), [])
        self.assertFalse(os.path.exists(self.path()))

    def test_a_build_with_model_work_off_is_refused(self):
        self.two()
        with self.assertRaises(KbError):
            self.build(cfg=dict(self.mcfg, models_on=False))
        self.assertEqual(self.sent(), [])

    def test_a_build_with_a_wrong_registry_is_refused(self):
        self.two()
        cfg = with_embedding()
        cfg["tasks"] = {"card-embed": "nowhere"}
        with self.assertRaises(KbError):
            self.build(cfg=cfg)
        self.assertEqual(self.sent(), [])

    def test_the_options_are_checked(self):
        self.two()
        for bad in (1, "yes", None, 0):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                self.build(again=bad)
        self.assertEqual(self.sent(), [])


class CommandTest(VectorCase):
    def setUp(self):
        super().setUp()
        path = os.path.join(self.cfg, "config.json")
        with open(path) as f:
            doc = json.load(f)
        doc.update(with_embedding())
        with open(path, "w") as f:
            json.dump(doc, f)
        os.chmod(path, 0o600)

    def kb(self, *args):
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg, PATH=self.base + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)

    def test_card_vectors_builds_the_store_and_prints_the_counts(self):
        self.two()
        r = self.kb("card-vectors")
        self.assertEqual(r.returncode, 0, r.stderr)
        counts = json.loads(r.stdout)
        self.assertEqual((counts["cards"], counts["vectors"], counts["made"], counts["texts_sent"]), (2, 6, 6, 6))
        self.assertTrue(os.path.isfile(self.path()))
        again = json.loads(self.kb("card-vectors").stdout)
        self.assertEqual((again["kept"], again["made"]), (6, 0))
        every = json.loads(self.kb("card-vectors", "--again").stdout)
        self.assertEqual((every["kept"], every["made"]), (0, 6))

    def test_card_vectors_exits_one_when_a_card_could_not_be_read(self):
        self.carded(title="Good", model=self.model_with("good"))
        bad, bad_v = self.carded(title="Bad", filed=False)
        self.store.file_payload(bad, bad_v, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        r = self.kb("card-vectors")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["left_out"], 1)
        self.assertIn("could not be read", r.stderr)

    def test_card_vectors_refuses_what_it_cannot_do(self):
        self.two()
        self.assertEqual(self.kb("card-vectors", "--nope").returncode, 2)
        path = os.path.join(self.cfg, "config.json")
        with open(path) as f:
            doc = json.load(f)
        del doc["tasks"]
        with open(path, "w") as f:
            json.dump(doc, f)
        r = self.kb("card-vectors")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tasks.card-embed", r.stderr)
        self.assertEqual(self.sent(), [])


if __name__ == "__main__":
    unittest.main()
