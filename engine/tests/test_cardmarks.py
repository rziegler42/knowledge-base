"""`card-marks`: the items of the cards marked stated and inferred, by field and by form of the card (plan
decide-what-to-do-with-inferred-items, Increment A). It reads the cards, calls no model and prints numbers, never card text."""
import json
import os
import subprocess
import sys
import unittest

from engine.tests import ENGINE_DIR
from engine.tests.test_cardmake import block
from engine.tests.test_trial import TrialCase, make_model

from kb import KbError, card, cardmarks


def entry(mark):
    """An entry of a grounding record: a stated item has notes and a quote, an inferred one has neither."""
    if mark == "stated":
        return {"mark": "stated", "notes": ["1.1"], "quote": "a quote of the book"}
    return {"mark": "inferred", "notes": [], "quote": None}


def earlier(marks):
    """A model part and its grounding record of the earlier form. `marks` gives the mark of each item as {field: [mark, ...]} for the
    topics, key ideas and caveats, and a mark or None for the limit; the model has as many items as there are marks."""
    model = make_model(topics=[f"zqtopic{i}" for i in range(len(marks.get("topics", [])))],
                       key_ideas=[f"zqidea{i}" for i in range(len(marks.get("key_ideas", [])))],
                       caveats=[f"zqcaveat{i}" for i in range(len(marks.get("caveats", [])))],
                       neutral_limits="zqlimit text" if marks.get("neutral_limits") else "")
    grounding = {field: [entry(m) for m in marks.get(field, [])] for field in card.GROUNDED_LISTS}
    grounding["neutral_limits"] = entry(marks["neutral_limits"]) if marks.get("neutral_limits") else None
    grounding["dropped"] = {"topics": 0, "key_ideas": 0, "caveats": 0, "neutral_limits": 0}
    return model, grounding


def sentences(marks, kept):
    """A model part and its grounding record of the sentence form. `kept` gives the marks of the kept sentences of each of the six
    fields; the field of the model is its sentences joined with a space."""
    texts = {field: [f"zq{field} sentence {n}." for n in range(len(kept.get(field, [])))] for field in card.SENTENCE_FIELDS}
    model = make_model(topics=[f"zqtopic{i}" for i in range(len(marks.get("topics", [])))],
                       key_ideas=[f"zqidea{i}" for i in range(len(marks.get("key_ideas", [])))],
                       caveats=[f"zqcaveat{i}" for i in range(len(marks.get("caveats", [])))],
                       **{field: " ".join(texts[field]) for field in card.SENTENCE_FIELDS})
    grounding = {field: [entry(m) for m in marks.get(field, [])] for field in card.GROUNDED_LISTS}
    grounding["neutral_limits"] = None
    grounding["dropped"] = {"topics": 0, "key_ideas": 0, "caveats": 0, "neutral_limits": 0}
    grounding["sentences"] = {field: {"kept": [{"text": t, **entry(m)} for t, m in zip(texts[field], kept.get(field, []))], "dropped": 0}
                              for field in card.SENTENCE_FIELDS}
    return model, grounding


class MarksCase(TrialCase):
    def add_card(self, title, pair=None):
        """File a card for a new book: of the pair (model part, grounding record), or, with none, a card of the first format."""
        book, version = self.converted_book(blocks=[block(f"{title} text")], title=title)
        model, grounding = pair if pair else (make_model(), None)
        # a card with fewer than three key ideas must be partial and say why; the marks do not depend on it
        card.file(self.store, card.make(self.store, book, version, model=model, records=[], grounding=grounding, reasons=["a card made for a test"]))
        return book, version

    def counts(self, **kw):
        return cardmarks.counts(self.store, **kw)


class CountTest(MarksCase):
    def test_the_marks_of_each_field_are_counted_by_form(self):
        self.add_card("Earlier one", earlier({"topics": ["stated", "inferred"], "key_ideas": ["stated", "stated", "inferred"],
                                              "caveats": ["inferred"], "neutral_limits": "inferred"}))
        self.add_card("Earlier two", earlier({"topics": ["stated", "stated"], "key_ideas": ["inferred", "stated", "stated"],
                                              "caveats": ["inferred"], "neutral_limits": "stated"}))
        out = self.counts()
        e = out["forms"]["earlier"]
        self.assertEqual(e["cards"], 2)
        self.assertEqual(e["fields"]["topics"], {"stated": 3, "inferred": 1})
        self.assertEqual(e["fields"]["key_ideas"], {"stated": 4, "inferred": 2})
        self.assertEqual(e["fields"]["caveats"], {"stated": 0, "inferred": 2})
        self.assertEqual(e["fields"]["neutral_limits"], {"stated": 1, "inferred": 1})
        self.assertEqual(out["forms"]["sentences"]["cards"], 0)

    def test_the_two_forms_are_counted_apart_and_a_sentence_counts_in_its_own_field(self):
        self.add_card("Earlier", earlier({"topics": ["inferred"]}))
        kept = {"summary": ["stated", "stated"], "neutral_problem": ["stated"], "neutral_approach": ["inferred"], "neutral_needs": [],
                "neutral_provides": ["stated"], "neutral_limits": ["inferred"]}
        self.add_card("Sentences", sentences({"topics": ["stated"], "key_ideas": ["inferred", "inferred"]}, kept))
        out = self.counts()
        self.assertEqual(out["forms"]["earlier"]["fields"]["topics"], {"stated": 0, "inferred": 1})
        sent = out["forms"]["sentences"]
        self.assertEqual(sent["cards"], 1)
        self.assertEqual(sent["fields"]["topics"], {"stated": 1, "inferred": 0})
        self.assertEqual(sent["fields"]["key_ideas"], {"stated": 0, "inferred": 2})
        self.assertEqual(sent["fields"]["summary"], {"stated": 2, "inferred": 0})
        self.assertEqual(sent["fields"]["neutral_problem"], {"stated": 1, "inferred": 0})
        self.assertEqual(sent["fields"]["neutral_approach"], {"stated": 0, "inferred": 1})
        self.assertEqual(sent["fields"]["neutral_needs"], {"stated": 0, "inferred": 0})
        self.assertEqual(sent["fields"]["neutral_provides"], {"stated": 1, "inferred": 0})
        self.assertEqual(sent["fields"]["neutral_limits"], {"stated": 0, "inferred": 1})
        self.assertNotIn("summary", out["forms"]["earlier"]["fields"])   # the summary of the earlier form carries no mark

    def test_every_field_of_a_form_is_listed_even_when_nothing_is_counted(self):
        self.add_card("Only", earlier({}))
        out = self.counts()
        e = out["forms"]["earlier"]["fields"]
        self.assertEqual(list(e), ["topics", "key_ideas", "caveats", "neutral_limits"])
        self.assertTrue(all(v == {"stated": 0, "inferred": 0} for v in e.values()))
        self.assertEqual(list(out["forms"]["sentences"]["fields"]), ["topics", "key_ideas", "caveats", *card.SENTENCE_FIELDS])

    def test_a_card_built_from_the_metadata_and_a_card_with_no_marks_are_counted_apart(self):
        book, version = self.converted_book(blocks=[block("metadata text")], title="Metadata only")
        card.file(self.store, card.make(self.store, book, version))   # no model part
        self.add_card("Format one")                                   # a model part and no grounding record: not checked
        out = self.counts()
        self.assertEqual(out["without_marks"], {"metadata": 1, "not_checked": 1})
        self.assertEqual(out["cards"], 2)
        self.assertEqual((out["forms"]["earlier"]["cards"], out["forms"]["sentences"]["cards"]), (0, 0))

    def test_a_card_that_cannot_be_read_is_counted_and_left_out(self):
        self.add_card("Fine", earlier({"topics": ["stated"]}))
        broken, version = self.converted_book(blocks=[block("text")], title="Broken card")
        self.store.file_payload(broken, version, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        out = self.counts()
        self.assertEqual(out["unreadable"], 1)
        self.assertEqual(out["forms"]["earlier"]["cards"], 1)

    def two_generations(self):
        book, version = self.add_card("Two generations", earlier({"topics": ["inferred", "inferred"]}))
        model, grounding = earlier({"topics": ["stated", "stated"]})
        card.file(self.store, card.make(self.store, book, version, model=model, records=[], grounding=grounding, reasons=["a card made for a test"]))
        return book, version

    def test_the_newest_card_of_each_version_is_counted_and_not_the_older_ones(self):
        self.two_generations()
        out = self.counts()
        self.assertEqual(out["forms"]["earlier"]["cards"], 1)
        self.assertEqual(out["forms"]["earlier"]["fields"]["topics"], {"stated": 2, "inferred": 0})
        self.assertEqual(out["generations"], "newest")

    def test_generations_named_are_counted_each(self):
        self.two_generations()
        first = self.counts(generations=[1])
        self.assertEqual(first["forms"]["earlier"]["fields"]["topics"], {"stated": 0, "inferred": 2})
        self.assertEqual(first["generations"], [1])
        both = self.counts(generations=[1, 2])
        self.assertEqual(both["forms"]["earlier"]["cards"], 2)
        self.assertEqual(both["forms"]["earlier"]["fields"]["topics"], {"stated": 2, "inferred": 2})
        with self.assertRaises(KbError):
            self.counts(generations=[9])

    def test_a_book_that_is_not_active_is_left_out_and_books_can_be_named(self):
        weeded, _ = self.add_card("Weeded", earlier({"topics": ["inferred"]}))
        self.store.set_state(weeded, "weeded")
        kept, _ = self.add_card("Kept", earlier({"topics": ["stated"]}))
        self.add_card("Other", earlier({"topics": ["stated", "stated"]}))
        self.assertEqual(self.counts()["forms"]["earlier"]["cards"], 2)
        only = self.counts(books=[kept])
        self.assertEqual(only["forms"]["earlier"]["cards"], 1)
        self.assertEqual(only["forms"]["earlier"]["fields"]["topics"], {"stated": 1, "inferred": 0})

    def test_the_output_holds_numbers_and_names_of_fields_and_no_text_of_a_card(self):
        self.add_card("A distinctive zebra title", earlier({"topics": ["stated"], "key_ideas": ["inferred"], "neutral_limits": "stated"}))
        self.add_card("A sentence card", sentences({"topics": ["inferred"]}, {"summary": ["stated"], "neutral_limits": ["inferred"]}))
        text = json.dumps(self.counts())
        for word in ("zebra", "filler", "zq", "quote of the book", "sentence 0", "A sentence card"):
            self.assertNotIn(word, text)

    def test_the_counts_agree_with_the_totals_of_the_card_itself(self):
        # `card.grounding_counts` totals the marks of one card without the field; the fields of `card-marks` must add up to it
        cases = {"earlier": earlier({"topics": ["stated", "inferred"], "key_ideas": ["stated", "stated", "inferred"], "caveats": ["inferred"],
                                     "neutral_limits": "inferred"}),
                 "earlier, no limit": earlier({"topics": ["stated"], "key_ideas": ["inferred"]}),
                 "sentences": sentences({"topics": ["stated"], "key_ideas": ["inferred", "inferred"], "caveats": ["stated"]},
                                        {"summary": ["stated", "stated"], "neutral_problem": ["inferred"], "neutral_provides": ["stated"],
                                         "neutral_limits": ["inferred", "stated"]})}
        for label, pair in cases.items():
            with self.subTest(label):
                book, version = self.add_card(label, pair)
                made = card.read(self.store, book, version, 1)[1]
                total = card.grounding_counts(made)
                out = self.counts(books=[book])
                form = "sentences" if "sentences" in pair[1] else "earlier"
                added = {mark: sum(c[mark] for c in out["forms"][form]["fields"].values()) for mark in card.MARKS}
                self.assertEqual(added, total)

    def test_nothing_is_written_to_the_library(self):
        book, version = self.add_card("Read only", earlier({"topics": ["stated"]}))
        before = card.generations(self.store, book, version)
        self.counts()
        self.assertEqual(card.generations(self.store, book, version), before)


class CommandTest(MarksCase):
    def kb(self, *args):
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg)
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)

    def test_the_command_prints_the_counts_as_json_and_takes_no_model_option(self):
        self.add_card("Command", earlier({"topics": ["stated", "inferred"]}))
        r = self.kb("card-marks")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["forms"]["earlier"]["fields"]["topics"], {"stated": 1, "inferred": 1})
        for args in (["--model", "x"], ["--server", "x"], ["--path", "x"]):
            with self.subTest(args=args):
                self.assertEqual(self.kb("card-marks", *args).returncode, 2)

    def test_generation_and_book_can_be_repeated_and_a_wrong_generation_is_refused(self):
        book, _ = self.add_card("Command", earlier({"topics": ["stated"]}))
        r = self.kb("card-marks", "--generation", "1", "--book", book)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["generations"], [1])
        self.assertEqual(self.kb("card-marks", "--generation", "9").returncode, 2)
        self.assertEqual(self.kb("card-marks", "--generation", "x").returncode, 2)


if __name__ == "__main__":
    unittest.main()
