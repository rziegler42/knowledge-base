"""The vectors of the shelves of the schema (`kb/shelfvectors.py`, Increment A of the plan `2026-11-15-propose-a-shelf-for-each-book`).

The file is derived from the schema file and the embedding model that the config sets for the task `place-embed`; a fake bridge answers with vectors made from the text, so nothing here needs a network, a model or the owner's config.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_shelfvectors`."""
import copy
import hashlib
import json
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import io
import unittest
from contextlib import closing, redirect_stdout
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_models import FAKE_EMBED, config, embedding, fake_vector
from engine.tests.test_shelfmatch import schema_data
from engine.tests.test_store import StoreCase

from kb import KbError, models, shelfmatch, shelfvectors

MEASURED = "qwen3-embedding:4b"


def with_entry(**over):
    cfg = config(emb=embedding(model=MEASURED, **over))
    cfg["tasks"] = {"place-embed": "emb"}
    return cfg


class ShelfCase(StoreCase):
    """A fixture library, a fixture schema file, and a fake `embed` bridge that answers with a vector made from the text."""

    def setUp(self):
        super().setUp()
        self.launcher = os.path.join(self.base, "wb")
        with open(self.launcher, "w") as f:
            f.write(FAKE_EMBED.format(python=sys.executable))
        os.chmod(self.launcher, 0o700)
        self.plan()
        self.mcfg = with_entry()
        self.schema_path = os.path.join(self.base, "schema.json")
        self.write_schema(schema_data())

    def plan(self, **p):
        p.setdefault("model", MEASURED)
        with open(os.path.join(self.base, "plan.json"), "w") as f:
            json.dump(p, f)

    def write_schema(self, data):
        with open(self.schema_path, "w") as f:
            json.dump(data, f)

    def build(self, cfg=None, **kw):
        return shelfvectors.build(self.store, cfg or self.mcfg, schema_path=self.schema_path, launcher=self.launcher, **kw)

    def load(self, cfg=None):
        return shelfvectors.load(self.store.cfg["index_root"], cfg or self.mcfg, schema_path=self.schema_path)

    def path(self):
        return shelfvectors.path_of(self.store.cfg["index_root"])

    def calls(self):
        path = os.path.join(self.base, "calls.jsonl")
        if not os.path.exists(path):
            return 0
        with open(path) as f:
            return len(f.readlines())

    def sent(self):
        path = os.path.join(self.base, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [t for line in f for t in json.loads(json.loads(line)["stdin"])["texts"]]

    def meta(self):
        with closing(sqlite3.connect(self.path())) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())

    def stored(self):
        with closing(sqlite3.connect(self.path())) as conn:
            rows = conn.execute("SELECT slug, text_sha256, vector FROM shelves ORDER BY slug").fetchall()
        return {slug: (sha, list(struct.unpack(f"<{len(blob) // 4}f", blob))) for slug, sha, blob in rows}

    def sql(self, statement, *args):
        with closing(sqlite3.connect(self.path())) as conn:
            conn.execute(statement, args)
            conn.commit()


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TextRule(ShelfCase):
    def test_a_shelf_is_its_name_a_full_stop_a_space_and_its_scope_in_the_order_of_the_file(self):
        schema = shelfmatch.schema_from_data(schema_data())
        got = shelfvectors.texts(schema)
        self.assertEqual(got[0], ("physical-sciences", "Physical Sciences. Works on Physical Sciences."))
        self.assertEqual(got[-1], ("handicrafts", "Handicrafts. Works on Handicrafts."))
        self.assertEqual([slug for slug, _ in got], [s["slug"] for s in schema_data()["shelves"]])
        self.assertEqual(len(got), 17)

    def test_the_hash_of_a_schema_is_that_of_the_bytes_of_its_file(self):
        with open(self.schema_path, "rb") as f:
            want = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(shelfvectors.file_sha256(self.schema_path), want)


class Build(ShelfCase):
    def test_one_vector_for_each_shelf_of_the_schema(self):
        counts = self.build()
        rows = self.stored()
        self.assertEqual(sorted(rows), sorted(s["slug"] for s in schema_data()["shelves"]))
        self.assertEqual((counts["shelves"], counts["made"], counts["kept"], counts["texts_sent"]), (17, 17, 0, 17))
        texts = dict(shelfvectors.texts(shelfmatch.schema_from_data(schema_data())))
        for slug, (digest, vector) in rows.items():
            self.assertEqual(digest, sha(texts[slug]))
            self.assertEqual(len(vector), 4)
            for got, want in zip(vector, fake_vector(texts[slug])):          # the vector of this shelf's own text, not of another's
                self.assertAlmostEqual(got, want, places=5)
        self.assertEqual(self.sent(), [t for _, t in shelfvectors.texts(shelfmatch.schema_from_data(schema_data()))])

    def test_the_first_build_is_one_call_to_the_bridge(self):
        self.build()
        self.assertEqual(self.calls(), 1)

    def test_a_long_schema_is_sent_in_chunks_that_fit_in_memory_and_a_model_that_changes_between_them_is_refused(self):
        with mock.patch.object(models, "MAX_EMBED_NUMBERS", 8):        # two texts of four numbers at a time
            self.build()
            self.assertEqual(self.calls(), 9)
            self.assertEqual(len(self.stored()), 17)
            os.remove(self.path())
            self.plan(bad_call=self.calls() + 2, bad_mode="othermodel")   # the fake counts every call of the test: the second of this build
            with self.assertRaises(KbError) as cm:
                self.build()
            self.assertIn("changed between the chunks", str(cm.exception))
            self.assertFalse(os.path.lexists(self.path()))

    def test_a_damaged_vector_in_the_old_file_is_made_again_and_the_others_are_kept(self):
        self.build()
        self.sql("UPDATE shelves SET vector = ? WHERE slug = 'lean'", b"\x00" * 3)
        before = len(self.sent())
        counts = self.build()
        self.assertEqual((counts["kept"], counts["made"], counts["replaced"]), (16, 1, False))
        self.assertEqual(self.sent()[before:], ["Lean Production. Works on Lean Production."])
        self.load()

    def test_again_must_be_true_or_false(self):
        for bad in (1, "yes", None):
            with self.assertRaises(KbError):
                self.build(again=bad)
        self.assertEqual(self.calls(), 0)

    def test_a_schema_that_changes_while_it_is_read_is_refused(self):
        real = shelfmatch.load_schema

        def changing(path):
            schema = real(path)
            with open(path, "a") as f:
                f.write(" ")
            return schema
        with mock.patch.object(shelfmatch, "load_schema", changing):
            with self.assertRaises(KbError) as cm:
                self.build()
        self.assertIn("changed while", str(cm.exception))
        self.assertEqual(self.calls(), 0)

    def test_the_file_says_what_made_it(self):
        self.build()
        meta = self.meta()
        self.assertEqual(meta["format"], str(shelfvectors.FORMAT))
        self.assertEqual(meta["model"], MEASURED)
        self.assertEqual(meta["configured"], MEASURED)
        self.assertEqual(meta["dimension"], "4")
        self.assertEqual(meta["document_prefix_sha256"], sha(""))
        self.assertEqual(meta["schema_sha256"], shelfvectors.file_sha256(self.schema_path))
        self.assertRegex(meta["built"], r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T")

    def test_a_second_build_with_nothing_changed_sends_nothing(self):
        self.build()
        before = self.calls()
        counts = self.build()
        self.assertEqual(self.calls(), before)
        self.assertEqual((counts["kept"], counts["made"], counts["texts_sent"], counts["replaced"]), (17, 0, 0, False))

    def test_a_changed_scope_sends_only_that_shelf(self):
        self.build()
        data = schema_data()
        data["shelves"][8]["scope"] = "A new scope sentence."
        self.write_schema(data)
        before = len(self.sent())
        counts = self.build()
        self.assertEqual((counts["kept"], counts["made"]), (16, 1))
        self.assertEqual(self.sent()[before:], ["Additive Manufacturing. A new scope sentence."])
        self.assertEqual(self.meta()["schema_sha256"], shelfvectors.file_sha256(self.schema_path))

    def test_a_shelf_added_to_the_schema_is_sent_and_one_taken_away_is_dropped(self):
        self.build()
        data = schema_data()
        extra = dict(data["shelves"][8], slug="extra-topic", name="Extra Topic", scope="Works on extra.", openalex="T9")
        data["shelves"].append(extra)
        data["shelves"] = [s for s in data["shelves"] if s["slug"] != "cloning"]
        self.write_schema(data)
        counts = self.build()
        self.assertEqual((counts["kept"], counts["made"], counts["shelves"]), (16, 1, 17))
        self.assertIn("extra-topic", self.stored())
        self.assertNotIn("cloning", self.stored())

    def test_again_sends_every_text(self):
        self.build()
        before = len(self.sent())
        counts = self.build(again=True)
        self.assertEqual((counts["made"], counts["kept"]), (17, 0))
        self.assertEqual(len(self.sent()) - before, 17)

    def test_a_file_made_by_another_model_is_replaced_and_every_text_is_sent_again(self):
        self.build()
        self.sql("UPDATE meta SET value = ? WHERE key = 'configured'", "bge-m3:latest")
        before = len(self.sent())
        counts = self.build()
        self.assertTrue(counts["replaced"])
        self.assertEqual((counts["made"], counts["kept"]), (17, 0))
        self.assertEqual(len(self.sent()) - before, 17)

    def test_a_file_that_is_not_ours_is_replaced(self):
        with open(self.path(), "wb") as f:
            f.write(b"not a database")
        counts = self.build()
        self.assertTrue(counts["replaced"])
        self.assertEqual(len(self.stored()), 17)

    def test_the_model_the_bridge_reports_is_recorded_and_a_change_between_builds_is_refused(self):
        self.build()
        self.plan(model="another-model:latest")
        self.write_schema(dict(schema_data(), shelves=[dict(s, scope=s["scope"] + " again") if s["slug"] == "cloning" else s for s in schema_data()["shelves"]]))
        with self.assertRaises(KbError) as cm:
            self.build()
        self.assertIn("again", str(cm.exception))                       # it says what to do
        self.assertEqual(self.meta()["model"], MEASURED)                # the old file is as it was

    def test_a_model_the_bridge_reports_that_is_not_the_measured_one_is_refused_and_nothing_is_written(self):
        self.plan(model="another-model:latest")
        with self.assertRaises(KbError) as cm:
            self.build()
        self.assertIn(MEASURED, str(cm.exception))
        self.assertFalse(os.path.lexists(self.path()))

    def test_a_failure_leaves_the_old_file_as_it_was_and_no_folder_of_the_build(self):
        self.build()
        with open(self.path(), "rb") as f:
            old = f.read()
        self.plan(mode="short")
        with self.assertRaises(KbError):
            self.build(again=True)
        with open(self.path(), "rb") as f:
            self.assertEqual(f.read(), old)
        self.assertEqual([n for n in os.listdir(self.store.cfg["index_root"]) if n.startswith(shelfvectors.BUILD_PREFIX)], [])

    def test_a_first_build_that_fails_leaves_no_file(self):
        self.plan(mode="short")
        with self.assertRaises(KbError):
            self.build()
        self.assertFalse(os.path.lexists(self.path()))

    def test_the_file_is_the_owners_alone_and_a_leftover_of_a_killed_build_is_removed(self):
        leftover = os.path.join(self.store.cfg["index_root"], shelfvectors.BUILD_PREFIX + "dead")
        os.mkdir(leftover)
        other = os.path.join(self.store.cfg["index_root"], "something-else.txt")
        with open(other, "w") as f:
            f.write("not ours")
        self.build()
        self.assertTrue(os.path.exists(other))              # nothing else in the index root is touched
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)
        self.assertFalse(os.path.exists(leftover))

    def test_a_schema_the_checker_refuses_stops_the_build_before_anything_is_sent(self):
        data = schema_data()
        data["shelves"].append(dict(data["shelves"][0]))                # a slug twice
        self.write_schema(data)
        with self.assertRaises(KbError):
            self.build()
        self.assertEqual(self.calls(), 0)
        self.assertFalse(os.path.lexists(self.path()))

    def test_a_schema_that_is_missing_is_refused(self):
        os.remove(self.schema_path)
        with self.assertRaises(KbError):
            self.build()
        self.assertEqual(self.calls(), 0)


class TheMeasuredConfiguration(ShelfCase):
    def refused(self, cfg, *words):
        with self.assertRaises(KbError) as cm:
            self.build(cfg)
        for word in words:
            self.assertIn(word, str(cm.exception))
        self.assertEqual(self.calls(), 0)
        self.assertFalse(os.path.lexists(self.path()))

    def test_another_embedding_model_is_refused_and_says_why(self):
        cfg = config(emb=embedding(model="bge-m3:latest"))
        cfg["tasks"] = {"place-embed": "emb"}
        self.refused(cfg, MEASURED, "measure")

    def test_a_document_prefix_is_refused(self):
        self.refused(with_entry(document_prefix="passage: "), "prefix")

    def test_a_task_that_is_not_set_is_refused_and_says_what_to_set(self):
        cfg = config(emb=embedding(model=MEASURED))
        self.refused(cfg, "place-embed")

    def test_model_work_off_is_refused(self):
        cfg = with_entry()
        cfg["models_on"] = False
        self.refused(cfg, "models_on")

    def test_the_card_embedding_task_does_not_stand_in_for_this_one(self):
        cfg = config(emb=embedding(model=MEASURED))
        cfg["tasks"] = {"card-embed": "emb"}
        self.refused(cfg, "place-embed")


class Describe(ShelfCase):
    def test_check_says_how_much_would_be_sent_and_sends_and_writes_nothing(self):
        text = shelfvectors.describe(self.mcfg, schema_path=self.schema_path)
        total = sum(len(t.encode()) for _, t in shelfvectors.texts(shelfmatch.schema_from_data(schema_data())))
        self.assertIn("17 shelf texts", text)
        self.assertIn("%d bytes in all" % total, text)
        self.assertIn(MEASURED, text)
        self.assertIn("in the clear", text)
        self.assertEqual(self.calls(), 0)
        self.assertFalse(os.path.lexists(self.path()))

    def test_check_with_again_says_that_every_text_would_be_sent(self):
        self.build()
        text = shelfvectors.describe(self.mcfg, schema_path=self.schema_path, index_root=self.store.cfg["index_root"], again=True)
        self.assertIn("17 of them are not in the file", text)
        plain = shelfvectors.describe(self.mcfg, schema_path=self.schema_path, index_root=self.store.cfg["index_root"])
        self.assertIn("0 of them are not in the file", plain)

    def test_check_refuses_what_the_build_refuses(self):
        cfg = config(emb=embedding(model="bge-m3:latest"))
        cfg["tasks"] = {"place-embed": "emb"}
        with self.assertRaises(KbError):
            shelfvectors.describe(cfg, schema_path=self.schema_path)

    def test_check_says_how_many_texts_a_build_would_send_when_a_file_exists(self):
        self.build()
        data = schema_data()
        data["shelves"][8]["scope"] = "Changed."
        self.write_schema(data)
        text = shelfvectors.describe(self.mcfg, schema_path=self.schema_path, index_root=self.store.cfg["index_root"])
        self.assertIn("1 of them are not in the file", text)


class Load(ShelfCase):
    def test_the_vectors_are_read_back_for_every_shelf(self):
        self.build()
        got = self.load()
        self.assertEqual(sorted(got["vectors"]), sorted(s["slug"] for s in schema_data()["shelves"]))
        self.assertEqual(got["meta"]["model"], MEASURED)
        stored = self.stored()
        for slug, vector in got["vectors"].items():
            self.assertEqual(vector, stored[slug][1])                      # each shelf's own vector
        self.assertNotEqual(got["vectors"]["additive"], got["vectors"]["cloning"])
        self.assertEqual(got["schema"].home[0], "additive")
        space = shelfmatch.build_space(got["schema"], got["vectors"])        # the pure matcher takes them as they come
        self.assertEqual(len(space.home_vectors), 9)

    def test_no_file_says_what_to_run(self):
        with self.assertRaises(KbError) as cm:
            self.load()
        self.assertIn("python3 -m kb shelf-vectors", str(cm.exception))

    def test_a_schema_that_changed_since_the_build_is_refused_as_stale(self):
        self.build()
        data = schema_data()
        data["shelves"][8]["scope"] = "Changed."
        self.write_schema(data)
        with self.assertRaises(KbError) as cm:
            self.load()
        self.assertIn("schema", str(cm.exception))

    def test_a_file_made_for_another_model_or_dimension_or_prefix_is_refused(self):
        self.build()
        for key, value in (("configured", "bge-m3:latest"), ("dimension", "5"), ("document_prefix_sha256", "0" * 64)):
            with self.subTest(key=key):
                saved = self.meta()[key]
                self.sql("UPDATE meta SET value = ? WHERE key = ?", value, key)
                with self.assertRaises(KbError):
                    self.load()
                self.sql("UPDATE meta SET value = ? WHERE key = ?", saved, key)
        self.load()

    def test_a_vector_that_is_not_a_vector_is_refused(self):
        self.build()
        for blob in (b"\x00" * 15, struct.pack("<4f", 0, 0, 0, 0), struct.pack("<4f", float("nan"), 1, 1, 1), struct.pack("<4f", float("inf"), 1, 1, 1)):
            with self.subTest(blob=blob):
                saved = self.stored()["additive"][1]
                self.sql("UPDATE shelves SET vector = ? WHERE slug = 'additive'", blob)
                with self.assertRaisesRegex(KbError, "not of the dimension"):
                    self.load()
                self.sql("UPDATE shelves SET vector = ? WHERE slug = 'additive'", struct.pack("<4f", *saved))
        self.load()

    def test_a_shelf_missing_or_extra_or_with_another_text_is_refused(self):
        self.build()
        self.sql("DELETE FROM shelves WHERE slug = 'cloning'")
        with self.assertRaises(KbError):
            self.load()
        self.build()
        self.sql("INSERT INTO shelves (slug, text_sha256, vector) VALUES ('not-a-shelf', ?, ?)", "a" * 64, struct.pack("<4f", 1, 1, 1, 1))
        with self.assertRaises(KbError):
            self.load()
        self.build(again=True)
        self.sql("UPDATE shelves SET text_sha256 = ? WHERE slug = 'lean'", "b" * 64)
        with self.assertRaises(KbError):
            self.load()

    def test_a_file_with_a_trigger_or_another_table_or_a_link_is_refused(self):
        self.build()
        self.sql("CREATE TABLE extra (x TEXT)")
        with self.assertRaises(KbError):
            self.load()
        self.build(again=True)
        self.sql("CREATE TRIGGER t AFTER INSERT ON shelves BEGIN SELECT 1; END")
        with self.assertRaises(KbError):
            self.load()
        self.build(again=True)
        os.rename(self.path(), self.path() + ".real")
        os.symlink(self.path() + ".real", self.path())
        with self.assertRaises(KbError):
            self.load()

    def test_a_file_made_by_a_model_that_is_not_the_measured_one_is_refused_by_the_reader_and_not_kept_by_a_build(self):
        self.build()
        self.sql("UPDATE meta SET value = ? WHERE key = 'model'", "another-model:latest")
        with self.assertRaisesRegex(KbError, "not by the measured model"):
            self.load()
        before = len(self.sent())
        counts = self.build()                                           # nothing changed in the schema: the old file still may not be kept
        self.assertTrue(counts["replaced"])
        self.assertEqual((counts["made"], counts["kept"]), (17, 0))
        self.assertEqual(len(self.sent()) - before, 17)
        self.assertEqual(self.meta()["model"], MEASURED)
        self.load()

    def test_a_file_in_another_format_or_with_other_columns_is_refused_for_that_reason(self):
        self.build()
        self.sql("PRAGMA user_version = 9")
        with self.assertRaisesRegex(KbError, "not in the shape"):
            self.load()
        self.build(again=True)
        self.sql("ALTER TABLE shelves RENAME COLUMN vector TO v")
        with self.assertRaisesRegex(KbError, "not the ones this version"):
            self.load()

    def test_a_file_whose_meta_is_not_what_we_write_is_refused(self):
        self.build()
        for key, value in (("schema_sha256", "xyz"), ("schema_sha256", "a" * 63), ("document_prefix_sha256", "g" * 64), ("dimension", "abc"), ("dimension", "0"),
                           ("format", "99"), ("model", "a b"), ("built", "x" * 41)):
            with self.subTest(key=key, value=value):
                saved = self.meta()[key]
                self.sql("UPDATE meta SET value = ? WHERE key = ?", value, key)
                with self.assertRaisesRegex(KbError, "does not say which model and schema"):
                    self.load()
                self.sql("UPDATE meta SET value = ? WHERE key = ?", saved, key)
        self.sql("DELETE FROM meta WHERE key = 'built'")
        with self.assertRaisesRegex(KbError, "does not say which model and schema"):
            self.load()

    def test_a_row_that_is_not_what_we_write_is_refused(self):
        self.build()
        for slug, digest in (("Bad Slug", "a" * 64), ("good-slug", "zz"), ("good-slug", "a" * 63)):
            with self.subTest(slug=slug, digest=digest):
                self.sql("INSERT INTO shelves (slug, text_sha256, vector) VALUES (?, ?, ?)", slug, digest, struct.pack("<4f", 1, 1, 1, 1))
                with self.assertRaisesRegex(KbError, "not what this engine writes"):
                    self.load()
                self.sql("DELETE FROM shelves WHERE slug = ?", slug)
        self.load()

    def test_the_identity_of_the_file_follows_what_made_it(self):
        self.build()
        first = self.load()["identity"]
        meta = self.meta()
        self.assertEqual(first, sha("|".join((meta["built"], meta["schema_sha256"], meta["model"], meta["dimension"], meta["document_prefix_sha256"]))))
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        data = schema_data()
        data["shelves"][8]["scope"] = "Changed."
        self.write_schema(data)
        self.build()
        self.assertNotEqual(self.load()["identity"], first)

    def test_the_file_is_opened_so_that_nothing_can_be_written(self):
        self.build()
        conn = shelfvectors.connect(self.path(), readonly=True)
        with closing(conn):
            with self.assertRaises(sqlite3.Error):
                conn.execute("DELETE FROM shelves")


class CommandLine(ShelfCase):
    """`python3 -m kb shelf-vectors` in a fixture library whose config is edited here; only --check is run, which sends nothing."""

    def run_kb(self, *args):
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=120)

    def set_config(self, **over):
        path = os.path.join(self.cfg, "config.json")
        with open(path) as f:
            doc = json.load(f)
        doc.update(over)
        with open(path, "w") as f:
            json.dump(doc, f)

    def test_check_through_the_command_line_says_what_would_be_sent_and_writes_nothing(self):
        self.set_config(models_on=True, models={"emb": embedding(model=MEASURED)}, tasks={"place-embed": "emb"})
        r = self.run_kb("shelf-vectors", "--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4816 shelf texts", r.stdout)
        self.assertIn("in the clear", r.stdout)
        self.assertFalse(os.path.lexists(self.path()))

    def test_the_command_without_a_task_set_is_refused_and_says_which(self):
        self.set_config(models_on=True, models={"emb": embedding(model=MEASURED)}, tasks={})
        r = self.run_kb("shelf-vectors", "--check")
        self.assertEqual(r.returncode, 2)                                   # the command line's code for a refusal
        self.assertIn("refused:", r.stderr)
        self.assertIn("place-embed", r.stderr)

    def test_the_command_with_another_model_is_refused_before_anything_is_sent(self):
        self.set_config(models_on=True, models={"emb": embedding(model="bge-m3:latest")}, tasks={"place-embed": "emb"})
        r = self.run_kb("shelf-vectors")
        self.assertEqual(r.returncode, 2)
        self.assertIn(MEASURED, r.stderr)
        self.assertFalse(os.path.lexists(self.path()))

    def test_the_command_hands_again_to_the_check(self):
        from kb import __main__ as cli
        with mock.patch.object(shelfvectors, "describe", return_value="text") as described:
            for argv, again in ((["shelf-vectors", "--check", "--again"], True), (["shelf-vectors", "--check"], False)):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(argv), 0)
                self.assertIs(described.call_args.kwargs["again"], again)

    def test_the_command_is_listed_and_takes_only_its_two_flags(self):
        self.assertIn("shelf-vectors", self.run_kb("--help").stdout)
        r = self.run_kb("shelf-vectors", "--nonsense")
        self.assertNotEqual(r.returncode, 0)


class Registry(unittest.TestCase):
    def test_the_task_names_an_embedding_entry_and_is_known(self):
        self.assertIn("place-embed", models.EMBED_TASKS)
        cfg = with_entry()
        self.assertEqual(models.choose(cfg, "place-embed")[0], "emb")

    def test_a_chat_entry_cannot_do_it(self):
        cfg = config(chat={"bridge": "ask-ollama", "server": "srv", "model": "m:1", "kind": "chat"})
        cfg["tasks"] = {"place-embed": "chat"}
        with self.assertRaises(KbError):
            models.registry(cfg)

    def test_the_card_tasks_are_not_changed(self):
        self.assertEqual(models.EMBED_TASKS[0], "card-embed")
        self.assertEqual(models.REQUIRED_TASKS, ("card-notes", "card", "card-check"))


if __name__ == "__main__":
    unittest.main()
