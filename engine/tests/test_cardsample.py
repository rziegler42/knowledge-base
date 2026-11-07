import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_cardmake import block
from engine.tests.test_trial import TrialCase, make_model

from kb import KbError, card, cardsample, models


def model_for(tag, **over):
    """A card model part whose items all carry `tag`, so that a test can tell the cards and the generations apart."""
    base = dict(summary=f"{tag} first sentence. {tag} second sentence.", useful_for=[f"{tag} use"], topics=[f"{tag} topic one", f"{tag} topic two"],
                adjacent_topics=[f"{tag} near one", f"{tag} near two"], key_ideas=[f"{tag} idea one", f"{tag} idea two", f"{tag} idea three"],
                neutral_problem=f"{tag} problem", neutral_approach=f"{tag} approach", neutral_needs=f"{tag} needs",
                neutral_provides=f"{tag} provides", neutral_limits=f"{tag} limits", caveats=[f"{tag} caveat"])
    base.update(over)
    return make_model(**base)


PER_CARD = 13  # 2 summary sentences + 2 topics + 3 key ideas + 5 neutral fields + 1 caveat; not the use, not the near topics


class SampleCase(TrialCase):
    """Three books, each with a card of generation 1 and one of generation 2."""

    def setUp(self):
        super().setUp()
        self.books = {}
        for tag in ("alpha", "bravo", "charlie"):
            blocks = [block(f"{tag} opening block"), block(f"the {tag} zebra method decides when to stop"), block(f"{tag} closing block")]
            book, version = self.converted_book(blocks=blocks, title=f"Book {tag}")
            for generation_tag in (f"{tag}x", f"{tag}y"):
                card.file(self.store, card.make(self.store, book, version, model=model_for(generation_tag), records=[]))
            self.books[tag] = book
        self.out = os.path.join(self.base, "sample")

    def sample(self, items=12, calibration=3, seed=7, generations=(1, 2), out=None):
        return cardsample.sample(self.store, out or self.out, items=items, calibration=calibration, seed=seed, generations=generations)

    def load(self, name, out=None):
        with open(os.path.join(out or self.out, name)) as f:
            return json.load(f)


class DrawTest(SampleCase):
    def test_the_sample_has_the_number_asked_and_half_from_each_generation(self):
        self.sample(items=12)
        key = self.load("key.json")["items"]
        self.assertEqual(len(self.load("items.json")["items"]), 12)
        self.assertEqual(sorted(e["generation"] for e in key.values()), [1] * 6 + [2] * 6)

    def test_every_card_is_drawn_from_in_turn_and_every_field_in_turn_within_a_card(self):
        self.sample(items=12)
        by_card = {}
        for entry in self.load("key.json")["items"].values():
            by_card.setdefault((entry["book_id"], entry["generation"]), []).append(entry["field"])
        self.assertEqual(sorted(len(v) for v in by_card.values()), [2] * 6)  # 6 items per generation over 3 cards
        self.assertEqual(len(by_card), 6)
        for fields in by_card.values():
            self.assertEqual(len(set(fields)), 2)  # two different fields, not the same one twice

    def test_the_same_seed_gives_the_same_sample_and_another_seed_another(self):
        self.sample(seed=7)
        first = (self.load("items.json"), self.load("key.json"))
        other = os.path.join(self.base, "sample2")
        self.sample(seed=7, out=other)
        self.assertEqual((self.load("items.json", other), self.load("key.json", other)), first)
        third = os.path.join(self.base, "sample3")
        self.sample(seed=8, out=third)
        self.assertNotEqual(self.load("key.json", third)["items"], first[1]["items"])

    def test_the_whole_pool_can_be_drawn_and_holds_neither_use_nor_near_topics(self):
        self.sample(items=6 * PER_CARD, calibration=5)
        fields = [e["field"] for e in self.load("key.json")["items"].values()]
        self.assertEqual(len(fields), 78)
        self.assertEqual(sorted(set(fields)), sorted(["summary", "topics", "key_ideas", "caveats", "neutral_problem", "neutral_approach",
                                                       "neutral_needs", "neutral_provides", "neutral_limits"]))
        self.assertEqual(fields.count("summary"), 12)
        self.assertEqual(fields.count("key_ideas"), 18)

    def test_a_sample_larger_than_the_pool_is_refused(self):
        with self.assertRaises(KbError):
            self.sample(items=6 * PER_CARD + 1)

    def test_without_a_generation_the_newest_card_of_each_version_is_drawn(self):
        cardsample.sample(self.store, self.out, items=6, calibration=0, seed=1)
        self.assertEqual({e["generation"] for e in self.load("key.json")["items"].values()}, {2})

    def test_a_generation_that_no_card_has_is_refused(self):
        with self.assertRaises(KbError):
            self.sample(generations=(1, 9))

    def test_the_summary_is_drawn_a_sentence_at_a_time(self):
        self.sample(items=6 * PER_CARD, calibration=0)
        texts = {e["text"] for e in self.load("items.json")["items"] if e["field"] == "summary"}
        self.assertIn("alphax first sentence.", texts)
        self.assertIn("alphax second sentence.", texts)


class BlindTest(SampleCase):
    def test_an_item_in_the_file_says_nothing_of_its_generation(self):
        self.sample()
        for item in self.load("items.json")["items"]:
            self.assertEqual(set(item), {"id", "book_id", "title", "field", "text", "passages", "label", "labelled_by", "note"})
            self.assertIsNone(item["label"])
            self.assertIsNone(item["labelled_by"])
            self.assertEqual(item["note"], "")

    def test_the_order_of_the_items_does_not_follow_the_generations(self):
        self.sample()
        key = self.load("key.json")["items"]
        order = [key[i["id"]]["generation"] for i in self.load("items.json")["items"]]
        self.assertNotEqual(order, sorted(order))
        self.assertNotEqual(order, sorted(order, reverse=True))

    def test_the_key_names_each_item_and_holds_the_hash_of_its_text(self):
        self.sample()
        items = {i["id"]: i for i in self.load("items.json")["items"]}
        key = self.load("key.json")
        self.assertEqual(set(items), set(key["items"]))
        self.assertEqual(key["seed"], 7)
        for item_id, entry in key["items"].items():
            self.assertEqual(set(entry), {"book_id", "version_id", "generation", "field", "position", "sha256"})
            self.assertEqual(entry["sha256"], hashlib.sha256(items[item_id]["text"].encode()).hexdigest())
            made = card.read(self.store, entry["book_id"], entry["version_id"], entry["generation"])[1]["model"]
            self.assertIn(items[item_id]["text"], str(made))
            self.assertEqual(items[item_id]["book_id"], entry["book_id"])
            self.assertEqual(items[item_id]["field"], entry["field"])

    def test_the_calibration_items_are_among_the_items_and_spread_over_the_fields(self):
        self.sample(items=24, calibration=6)
        items = {i["id"]: i for i in self.load("items.json")["items"]}
        calibration = self.load("calibration.json")["items"]
        self.assertEqual(len(calibration), 6)
        for item in calibration:
            self.assertEqual(item, items[item["id"]])
        self.assertEqual(len({i["field"] for i in calibration}), 6)  # six items, six different fields
        for seed in range(1, 12):  # as many different fields as the sample allows, whatever the seed
            other = os.path.join(self.base, f"seed{seed}")
            self.sample(items=24, calibration=5, seed=seed, out=other)
            drawn = self.load("items.json", other)["items"]
            self.assertEqual(len({i["field"] for i in self.load("calibration.json", other)["items"]}), min(5, len({i["field"] for i in drawn})), seed)

    def test_the_calibration_cannot_be_larger_than_the_sample(self):
        with self.assertRaises(KbError):
            self.sample(items=4, calibration=5)

    def test_the_rubric_is_written_and_is_the_one_in_the_code(self):
        self.sample()
        with open(os.path.join(self.out, "rubric.md")) as f:
            self.assertEqual(f.read(), cardsample.RUBRIC)
        for word in ("supported", "unsupported", "inference", "skip"):
            self.assertIn(word, cardsample.RUBRIC)
        self.assertEqual(self.load("items.json")["rubric"], cardsample.RUBRIC)


class PassageTest(SampleCase):
    def item(self, text):
        return next(i for i in self.load("items.json")["items"] if i["text"] == text)

    def draw_all(self):
        self.sample(items=6 * PER_CARD, calibration=0)

    def test_the_best_matching_block_comes_first_with_the_blocks_around_it(self):
        book, version = self.converted_book(blocks=[block("opening block"), block("the quokka method decides when to stop"),
                                                     block("closing block")], title="Book quokka")
        card.file(self.store, card.make(self.store, book, version, model=model_for("delta", topics=["quokka method decides", "second topic"]),
                                        records=[]))
        cardsample.sample(self.store, self.out, items=13, calibration=0, seed=1, generations=(1,), books=[book])
        passage = self.item("quokka method decides")["passages"][0]
        self.assertEqual(passage, "opening block\n\nthe quokka method decides when to stop\n\nclosing block")

    def test_there_are_at_most_five_passages_and_none_overlap(self):
        blocks = [block(f"zebra number {i}") for i in range(30)]
        book, version = self.converted_book(blocks=blocks, title="Book zebra")
        card.file(self.store, card.make(self.store, book, version, model=model_for("echo", topics=["zebra number", "other"]), records=[]))
        cardsample.sample(self.store, self.out, items=13, calibration=0, seed=1, generations=(1,), books=[book])
        passages = self.item("zebra number")["passages"]
        self.assertEqual(len(passages), 5)
        self.assertEqual(len(set(passages)), 5)
        blocks_used = [{b for b in p.split("\n\n")} for p in passages]
        for a in range(5):
            for b in range(a + 1, 5):
                self.assertFalse(blocks_used[a] & blocks_used[b])

    def test_an_item_that_the_book_does_not_mention_has_no_passages(self):
        book, version = self.converted_book(blocks=[block("opening block"), block("closing block")], title="Book marsupial")
        card.file(self.store, card.make(self.store, book, version, model=model_for("hotel", caveats=["quokka marsupial"]), records=[]))
        cardsample.sample(self.store, self.out, items=13, calibration=0, seed=1, generations=(1,), books=[book])
        self.assertEqual(self.item("quokka marsupial")["passages"], [])

    def test_a_passage_is_cut_to_600_characters_around_the_words_that_matched(self):
        long = "filler " * 280 + "the platypus method is here " + "filler " * 280
        book, version = self.converted_book(blocks=[block(long)], title="Book platypus")
        card.file(self.store, card.make(self.store, book, version, model=model_for("foxtrot", topics=["platypus method", "other"]), records=[]))
        cardsample.sample(self.store, self.out, items=13, calibration=0, seed=1, generations=(1,), books=[book])
        passage = self.item("platypus method")["passages"][0]
        self.assertLessEqual(len(passage), 600)
        self.assertIn("platypus method", passage)

    def test_a_best_block_of_about_600_characters_still_gives_a_passage_of_at_most_600(self):
        for length in range(590, 606):
            best = "b" * length
            with self.subTest(length=length):
                passage = cardsample._cut("p" * 50, best, "f" * 5000)
                self.assertLessEqual(len(passage), 600)
                self.assertTrue(passage.startswith("b" * min(length, 590)) or "b" * min(length, 590) in passage)
        blocks = ["x " * 20, "quokka " * 85 + "z", "y " * 3000]  # a middle block of 596 characters, a long block after it
        for found in cardsample.passages(blocks, "quokka"):
            self.assertLessEqual(len(found), 600)

    def test_the_passages_are_marked_as_untrusted_in_the_file(self):
        self.sample()
        self.assertIs(self.load("items.json")["untrusted"], True)


class FilesTest(SampleCase):
    def test_the_folder_is_private_and_so_are_the_files(self):
        self.sample()
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)
        names = sorted(os.listdir(self.out))
        self.assertEqual(names, ["calibration.json", "items.json", "key.json", "rubric.md"])
        for name in names:
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.out, name)).st_mode), 0o600, name)

    def test_a_folder_inside_the_project_is_refused_and_nothing_is_made(self):
        inside = os.path.join(models._project_root(), "sample-should-not-exist")
        with self.assertRaises(KbError) as cm:
            self.sample(out=inside)
        self.assertIn("outside", str(cm.exception))
        self.assertFalse(os.path.exists(inside))

    def test_a_folder_with_files_in_it_is_refused_and_an_empty_one_is_used(self):
        os.mkdir(self.out)
        with open(os.path.join(self.out, "keep.txt"), "w") as f:
            f.write("x")
        with self.assertRaises(KbError):
            self.sample()
        os.remove(os.path.join(self.out, "keep.txt"))
        self.sample()
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o700)

    def test_a_folder_that_is_a_link_into_the_project_is_refused(self):
        link = os.path.join(self.base, "link")
        os.symlink(models._project_root(), link)
        with self.assertRaises(KbError):
            self.sample(out=link)

    def test_a_book_whose_text_cannot_be_read_stops_the_sample_and_leaves_no_file(self):
        broken, version = self.converted_book(blocks=[block("text")], title="Broken")
        card.file(self.store, card.make(self.store, broken, version, model=model_for("golf"), records=[]))
        payload = os.path.join(self.store.version_dir(broken, version), "derived", "kb-html-std", "1")
        os.chmod(payload, 0o700)
        os.remove(os.path.join(payload, "blocks.json"))
        for seed in range(1, 8):  # whichever items a seed draws, a book whose text cannot be read stops the sample
            with self.subTest(seed=seed), self.assertRaises(KbError):
                self.sample(items=1, calibration=0, seed=seed, generations=(1,))
            self.assertEqual(os.listdir(self.out) if os.path.isdir(self.out) else [], [])

    def test_a_failed_write_removes_what_the_sample_wrote_and_nothing_else(self):
        os.mkdir(self.out)
        real = cardsample.config.write_json_atomic
        calls = []

        def write(path, obj, mode):
            calls.append(path)
            if len(calls) == 1:
                real(path, obj, mode)  # the first file is written
                with open(os.path.join(self.out, "foreign.txt"), "w") as f:  # and a file of someone else appears
                    f.write("not ours")
                return
            raise OSError("disk full")

        with mock.patch.object(cardsample.config, "write_json_atomic", side_effect=write):
            with self.assertRaises(OSError):
                self.sample()
        self.assertEqual(os.listdir(self.out), ["foreign.txt"])

    def test_the_default_draws_the_newest_card_of_every_version_as_one_group(self):
        book, version = self.converted_book(blocks=[block("older book text")], title="Older")
        card.file(self.store, card.make(self.store, book, version, model=model_for("india"), records=[]))  # only generation 1
        self.sample(items=4 * PER_CARD, calibration=0, generations=None)
        counts = {}
        for entry in self.load("key.json")["items"].values():
            counts[entry["generation"]] = counts.get(entry["generation"], 0) + 1
        self.assertEqual(counts, {1: PER_CARD, 2: 3 * PER_CARD})

    def test_a_card_that_cannot_be_read_is_left_out_and_counted(self):
        broken, version = self.converted_book(blocks=[block("text")], title="Broken card")
        self.store.file_payload(broken, version, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        summary = cardsample.sample(self.store, self.out, items=6, calibration=0, seed=1)
        self.assertEqual(summary["unreadable_cards"], 1)
        self.assertNotIn(broken, {e["book_id"] for e in self.load("key.json")["items"].values()})

    def test_the_sample_changes_nothing_in_the_library(self):
        def snapshot():
            out = {}
            for dirpath, _, names in os.walk(self.bulk):
                for name in names:
                    path = os.path.join(dirpath, name)
                    with open(path, "rb") as f:
                        out[path] = hashlib.sha256(f.read()).hexdigest()
            return out
        before = snapshot()
        self.sample()
        self.assertEqual(snapshot(), before)


def labelled(book="01M6SR01QXBXAZ9V8ZHBWPCDAF", field="topics", text="t", label="supported", by="model", note="", item_id="i001"):
    return {"id": item_id, "book_id": book, "title": "T", "field": field, "text": text, "passages": [], "label": label, "labelled_by": by,
            "note": note}


def make_key(items, generations):
    """A key for hand-made items: `generations` gives the generation of each id."""
    return {"format": 1, "seed": 1, "items": {i["id"]: {"book_id": i["book_id"], "version_id": "v1", "generation": generations[i["id"]],
                                                         "field": i["field"], "position": 0,
                                                         "sha256": hashlib.sha256(i["text"].encode()).hexdigest()} for i in items}}


class HandMadeCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def write(self, name, obj):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            json.dump(obj, f)
        return path

    def items_file(self, items):
        return {"format": 1, "untrusted": True, "rubric": cardsample.RUBRIC, "items": items}


class AccuracyTest(HandMadeCase):
    def setUp(self):
        super().setUp()
        self.items = [
            labelled(item_id="i001", field="topics", text="one", label="supported"),
            labelled(item_id="i002", field="topics", text="two", label="unsupported"),
            labelled(item_id="i003", field="neutral_limits", text="three", label="inference", note="follows from the second passage"),
            labelled(item_id="i004", field="summary", text="four", label="supported"),
            labelled(item_id="i005", field="key_ideas", text="five", label="supported"),
            labelled(item_id="i006", field="caveats", text="six", label="skip"),
            labelled(item_id="i007", field="key_ideas", text="seven", label="unsupported", note="only the first half is stated"),
        ]
        self.generations = {"i001": 1, "i002": 1, "i003": 1, "i004": 1, "i005": 2, "i006": 2, "i007": 2}
        self.key = self.write("key.json", make_key(self.items, self.generations))

    def report(self, items=None):
        return cardsample.accuracy(self.write("items.json", self.items_file(items if items is not None else self.items)), self.key)

    def test_counts_and_shares_by_generation_and_field_worked_by_hand(self):
        r = self.report()
        g1, g2 = r["generations"]["1"], r["generations"]["2"]
        self.assertEqual((g1["items"], g1["skipped"], g1["supported"], g1["unsupported"], g1["inference"]), (4, 0, 2, 1, 1))
        self.assertEqual((g2["items"], g2["skipped"], g2["supported"], g2["unsupported"], g2["inference"]), (3, 1, 1, 1, 0))
        self.assertEqual(g1["shares"], {"supported": 0.5, "unsupported": 0.25, "inference": 0.25})
        self.assertEqual(g2["shares"], {"supported": 0.5, "unsupported": 0.5, "inference": 0.0})
        self.assertEqual(g1["fields"]["topics"], {"items": 2, "skipped": 0, "supported": 1, "unsupported": 1, "inference": 0})
        self.assertEqual(g2["fields"]["key_ideas"], {"items": 2, "skipped": 0, "supported": 1, "unsupported": 1, "inference": 0})
        self.assertEqual(g2["fields"]["caveats"], {"items": 1, "skipped": 1, "supported": 0, "unsupported": 0, "inference": 0})
        self.assertEqual(r["labelled_by"], {"model": 7})
        self.assertEqual(r["notes"], 2)
        self.assertEqual(r["items"], 7)

    def test_the_report_holds_no_item_text(self):
        text = json.dumps(self.report())
        for item in self.items:
            self.assertNotIn(f'"{item["text"]}"', text)
        self.assertNotIn("follows from", text)

    def refused(self, mutate):
        items = copy.deepcopy(self.items)
        mutate(items)
        with self.assertRaises(KbError):
            self.report(items)

    def test_every_form_of_bad_labels_is_refused(self):
        cases = {
            "an item not labelled": lambda i: i[0].update(label=None),
            "a label that is not one of the four": lambda i: i[0].update(label="maybe"),
            "an inference with no note": lambda i: i[2].update(note=""),
            "no labeller named": lambda i: i[0].update(labelled_by=None),
            "an empty labeller": lambda i: i[0].update(labelled_by=""),
            "a note that is too long": lambda i: i[0].update(note="x" * 501),
            "an extra key": lambda i: i[0].update(extra=1),
            "a missing key": lambda i: i[0].pop("passages"),
            "an id that is not in the key": lambda i: i[0].update(id="i999"),
            "a repeated id": lambda i: i[1].update(id="i001"),
            "an item missing": lambda i: i.pop(),
            "text that was changed": lambda i: i[0].update(text="changed"),
            "a field that was changed": lambda i: i[0].update(field="caveats"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.refused(mutate)

    def test_a_key_or_items_file_that_is_hostile_is_refused_not_crashed_on(self):
        good = make_key(self.items, self.generations)
        huge = os.path.join(self.dir, "huge.json")
        with open(huge, "w") as f:
            f.write(json.dumps(good).replace('"generation": 1', '"generation": 1' + "0" * 5000, 1))
        big = copy.deepcopy(good)
        big["items"]["i001"]["generation"] = 10 ** 9
        nested = os.path.join(self.dir, "nested.json")
        with open(nested, "w") as f:
            f.write("[" * 100000 + "]" * 100000)
        fifo = os.path.join(self.dir, "fifo.json")
        os.mkfifo(fifo)
        items = self.write("items.json", self.items_file(self.items))
        for label, key in {"a number of 5000 digits": huge, "a generation out of range": self.write("big.json", big), "deeply nested": nested, "a pipe": fifo}.items():
            with self.subTest(label), self.assertRaises(KbError):
                cardsample.accuracy(items, key)
        with self.assertRaises(KbError):
            cardsample.accuracy(nested, self.key)
        with self.assertRaises(KbError):
            cardsample.agreement(fifo, items)

    def test_a_file_that_is_not_in_the_expected_form_is_refused(self):
        key = self.key
        for label, obj in {"an array": [], "no items": {"format": 1}, "another format": {"format": 2, "items": []}}.items():
            with self.subTest(label), self.assertRaises(KbError):
                cardsample.accuracy(self.write("bad.json", obj), key)
        with self.assertRaises(KbError):
            cardsample.accuracy(os.path.join(self.dir, "missing.json"), key)


class AgreementTest(HandMadeCase):
    def setUp(self):
        super().setUp()
        self.full = [
            labelled(item_id="i001", text="one", label="supported", by="model"),
            labelled(item_id="i002", text="two", label="unsupported", by="model"),
            labelled(item_id="i003", text="three", label="inference", note="n", by="model"),
            labelled(item_id="i004", text="four", label="supported", by="model"),
            labelled(item_id="i005", text="five", label="skip", by="model"),
            labelled(item_id="i006", text="six", label="supported", by="model"),
        ]
        self.owner = [
            labelled(item_id="i001", text="one", label="supported", by="owner"),
            labelled(item_id="i002", text="two", label="supported", by="owner"),
            labelled(item_id="i003", text="three", label="inference", note="n", by="owner"),
            labelled(item_id="i004", text="four", label="unsupported", by="owner"),
            labelled(item_id="i005", text="five", label="supported", by="owner"),
            labelled(item_id="i006", text="six", label=None, by=None),
        ]

    def compare(self, first=None, second=None):
        a = self.write("a.json", self.items_file(first if first is not None else self.full))
        b = self.write("b.json", self.items_file(second if second is not None else self.owner))
        return cardsample.agreement(a, b)

    def test_agreement_worked_by_hand(self):
        r = self.compare()
        # compared: i001 agree, i002 supported/unsupported differ, i003 agree, i004 differ; i005 skipped by one; i006 unlabelled by one
        self.assertEqual((r["compared"], r["agree"], r["skipped"], r["unlabelled"]), (4, 2, 1, 1))
        self.assertEqual(r["share"], 0.5)
        self.assertEqual(r["differ"], ["i002", "i004"])
        self.assertEqual(r["pairs"], [{"first": "inference", "second": "inference", "count": 1},
                                      {"first": "supported", "second": "supported", "count": 1},
                                      {"first": "supported", "second": "unsupported", "count": 1},
                                      {"first": "unsupported", "second": "supported", "count": 1}])

    def test_the_smaller_file_may_be_either_and_compares_over_its_ids(self):
        subset = self.owner[:4]
        r = self.compare(first=subset, second=self.full)
        self.assertEqual((r["compared"], r["agree"]), (4, 2))
        r = self.compare(first=self.full, second=subset)
        self.assertEqual((r["compared"], r["agree"]), (4, 2))
        self.assertEqual(r["pairs"][2], {"first": "supported", "second": "unsupported", "count": 1})

    def test_no_comparison_leaves_the_share_empty(self):
        r = self.compare(first=[labelled(item_id="i001", text="one", label="skip")], second=[labelled(item_id="i001", text="one", label="skip")])
        self.assertEqual((r["compared"], r["agree"], r["share"], r["skipped"]), (0, 0, None, 1))

    def test_files_that_do_not_belong_together_are_refused(self):
        with self.assertRaises(KbError):
            self.compare(first=[labelled(item_id="i001", text="one"), labelled(item_id="i009", text="nine")], second=self.owner[:2])
        changed = copy.deepcopy(self.owner)
        changed[0]["text"] = "other"
        with self.assertRaises(KbError):
            self.compare(second=changed)
        wrong_field = copy.deepcopy(self.owner)
        wrong_field[0]["field"] = "caveats"
        with self.assertRaises(KbError):
            self.compare(second=wrong_field)
        with self.assertRaises(KbError):
            self.compare(first=self.full + [self.full[0]])  # a repeated id

    def test_the_output_holds_no_item_text(self):
        text = json.dumps(self.compare())
        for word in ("one", "two", "three", "four"):
            self.assertNotIn(f'"{word}"', text)


class CommandTest(SampleCase):
    def kb(self, *args):
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg)
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)

    def test_the_three_commands_run_through_the_command_line(self):
        r = self.kb("card-sample", self.out, "--items", "12", "--calibration", "3", "--seed", "7", "--generation", "1", "--generation", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        summary = json.loads(r.stdout)
        self.assertEqual(summary["items"], 12)
        self.assertNotIn("alphax", r.stdout)  # the summary holds numbers, not the texts of the cards
        self.assertEqual(self.kb("card-sample", self.out, "--items", "12").returncode, 2)  # the folder now holds files
        items = self.load("items.json")
        for item in items["items"]:
            item.update(label="supported", labelled_by="model")
        path = os.path.join(self.base, "labelled.json")
        with open(path, "w") as f:
            json.dump(items, f)
        r = self.kb("card-accuracy", path, os.path.join(self.out, "key.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertEqual(report["items"], 12)
        r = self.kb("card-agreement", path, path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["share"], 1.0)

    def test_the_command_refuses_a_folder_inside_the_project(self):
        inside = os.path.join(models._project_root(), "sample-should-not-exist")
        r = self.kb("card-sample", inside, "--items", "6")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(inside))


if __name__ == "__main__":
    unittest.main()
