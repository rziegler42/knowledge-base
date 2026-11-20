"""The owner's confirmation of a proposed shelf (`kb/placereview.py`, Increment C of the plan `2026-11-15-propose-a-shelf-for-each-book`).

The dialogue is driven by an input function and a captured output on a fixture library whose proposals are made by `placement.propose` with fake hooks, so nothing here needs a network, a model or a terminal.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_placereview`."""
import copy
import io
import json
import os
import subprocess
import sys
import types
import unicodedata
import unittest
from contextlib import redirect_stdout
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_card import MODEL
from engine.tests.test_placement import LONG, PlaceCase
from engine.tests.test_shelfmatch import schema_data

from kb import KbError, card, placement, placereview


class ReviewCase(PlaceCase):
    """Books with proposals, and a way to answer the dialogue."""

    def proposed(self, title, answer=None, target="gene-editing", **kw):
        book, version = self.book_with(title, target=target, **kw)
        self.answers[title] = answer
        self.propose(book_ids=[book])
        return book, version

    def session(self, answers, tty=True, **kw):
        """Run the dialogue with these answers, one for each question; returns (counts, everything shown, the prompts asked)."""
        asked, shown = [], []
        feed = iter(answers)

        def input_fn(prompt):
            asked.append(prompt)
            try:
                return next(feed)
            except StopIteration:
                raise EOFError
        kw.setdefault("schema_path", self.schema_path)
        counts = placereview.review(self.store, input_fn=input_fn, say=shown.append, is_tty=lambda: tty, **kw)
        return counts, "\n".join(shown), asked

    def confirmations(self, book):
        return [e for e in self.store.read_events(book) if e["event"] == "placement_confirmed"]

    def edit_proposal(self, book, mutate):
        """Rewrite the newest proposal event of a book with `mutate` applied (the event log is a file of lines; this is what a hand edit or a damaged file looks like)."""
        path = self.store.events_file(book)
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        last = max(i for i, e in enumerate(lines) if e["event"] == "placement_proposed")
        mutate(lines[last])
        with open(path, "w") as f:
            f.write("".join(json.dumps(e) + "\n" for e in lines))

    def pick_of(self, book):
        (event,) = [e for e in self.store.read_events(book) if e["event"] == "placement_proposed"][-1:]
        return event


class Shown(ReviewCase):
    def test_a_book_is_shown_with_its_summary_and_the_five_shelves_in_the_order_the_model_saw_and_the_pick_marked(self):
        book, _ = self.proposed("The gene book", answer="2: It is about editing genes.", summary=LONG + " SUMMARYWORD",
                                source={"address_final": "https://example.org/gene", "retrieved": "2026-11-01T00:00:00+00:00", "sha256": "ab" * 32})
        counts, out, asked = self.session(["quit"])
        event = self.pick_of(book)
        by_slug = {s["slug"]: s for s in schema_data()["shelves"]}
        self.assertIn("The gene book", out)
        self.assertIn("https://example.org/gene", out)
        self.assertIn("SUMMARYWORD", out)
        for n, slug in enumerate(event["order"], 1):
            self.assertIn("%d. %s" % (n, by_slug[slug]["name"]), out)
            self.assertIn(by_slug[slug]["scope"], out)
        self.assertIn("It is about editing genes.", out)
        lines = out.splitlines()
        picked = [l for l in lines if "model's pick" in l]
        self.assertEqual(len(picked), 1)
        self.assertIn("2. " + by_slug[event["order"][1]]["name"], picked[0])

    def test_the_path_of_a_topic_shelf_is_shown_and_a_custom_shelf_says_it_has_none(self):
        self.proposed("The gene book")
        _, out, _ = self.session(["quit"])
        self.assertRegex(out, r"Life Sciences > Biology > Genetics > ")
        craft, _ = self.proposed("Craft book", target="handicrafts")
        _, out, _ = self.session(["quit"], book_ids=[craft])
        self.assertIn("a custom shelf", out)

    def test_a_none_and_a_malformed_answer_and_a_missing_pick_are_said_in_words(self):
        self.proposed("Book none", answer="none: Nothing fits here.")
        _, out, _ = self.session(["quit"])
        self.assertIn("said none", out)
        self.assertIn("Nothing fits here.", out)
        bad, _ = self.proposed("Book malformed", answer="I would say two")
        _, out, _ = self.session(["quit"], book_ids=[bad])
        self.assertIn("no usable answer", out)

    def test_the_questions_say_what_can_be_answered(self):
        self.proposed("The gene book")
        _, _, asked = self.session(["quit"])
        for word in ("1-5", "ok", "none", "skip", "quit"):
            self.assertIn(word, asked[0])


class Answers(ReviewCase):
    def setUp(self):
        super().setUp()
        self.the_book, self.the_version = self.proposed("The gene book", answer="2: Because.")
        self.event = self.pick_of(self.the_book)

    def confirmed(self, answers, **kw):
        counts, out, asked = self.session(answers, **kw)
        return counts, out, self.confirmations(self.the_book)

    def test_a_number_chooses_that_shelf_and_says_whether_it_is_the_pick(self):
        counts, _, (c,) = self.confirmed(["3"])
        self.assertEqual(c["result"], {"kind": "shelf", "shelf": self.event["order"][2], "words": None})
        self.assertIs(c["equals_pick"], False)
        self.assertEqual(c["answer"], "3")
        self.assertEqual(counts["confirmed"], 1)
        _, _, found = self.confirmed(["2"], again=True)
        c = found[-1]
        self.assertEqual(c["result"]["shelf"], self.event["order"][1])
        self.assertIs(c["equals_pick"], True)

    def test_ok_accepts_the_models_pick(self):
        _, _, (c,) = self.confirmed(["ok"])
        self.assertEqual(c["result"]["shelf"], self.event["order"][1])
        self.assertIs(c["equals_pick"], True)

    def test_ok_accepts_a_none_and_is_refused_when_there_is_no_pick_at_all(self):
        book, _ = self.proposed("Book none", answer="none: Nothing fits here.")
        self.session(["ok"], book_ids=[book])
        (c,) = self.confirmations(book)
        self.assertEqual(c["result"], {"kind": "none", "shelf": None, "words": None})
        self.assertIs(c["equals_pick"], True)
        bad, _ = self.proposed("Book malformed", answer="no idea")
        counts, out, asked = self.session(["ok", "4"], book_ids=[bad])
        (c,) = self.confirmations(bad)
        self.assertEqual(c["result"]["shelf"], self.pick_of(bad)["order"][3])
        self.assertIs(c["equals_pick"], False)
        self.assertEqual(len(asked), 2)
        self.assertIn("no model's pick to accept", out)

    def test_none_says_no_shelf_fits_and_is_not_the_pick_unless_the_model_said_none(self):
        _, _, (c,) = self.confirmed(["none"])
        self.assertEqual(c["result"], {"kind": "none", "shelf": None, "words": None})
        self.assertIs(c["equals_pick"], False)

    def test_skip_needs_words_and_records_them_cleaned(self):
        counts, out, asked = self.session(["skip", "skip   ", "skip \x07", "skip \u200b \x1b", "skipthis", "skip a page in a language I do not read\x07"])
        (c,) = self.confirmations(self.the_book)
        self.assertEqual(c["result"], {"kind": "skipped", "shelf": None, "words": "a page in a language I do not read"})
        self.assertEqual(c["answer"], "skip a page in a language I do not read")                 # what was typed is stored cleaned too
        self.assertIsNone(c["equals_pick"])
        self.assertEqual(len(asked), 6)                         # the first five were asked again
        self.assertEqual(counts["skipped"], 1)

    def test_skip_words_that_are_too_long_are_asked_again(self):
        counts, out, asked = self.session(["skip " + "x" * 301, "skip fine"])
        self.assertEqual(len(asked), 2)
        self.assertEqual(self.confirmations(self.the_book)[0]["result"]["words"], "fine")

    def test_quit_stops_without_recording_the_book_in_hand(self):
        counts, out, asked = self.session(["quit"])
        self.assertEqual(self.confirmations(self.the_book), [])
        self.assertEqual((counts["confirmed"], counts["stopped"]), (0, True))
        self.assertFalse(self.session(["1"])[0]["stopped"])

    def test_the_end_of_the_input_stops_without_recording(self):
        counts, out, asked = self.session([])
        self.assertEqual(self.confirmations(self.the_book), [])
        self.assertEqual(len(asked), 1)

    def test_anything_else_is_asked_again_and_never_guessed_at_and_never_recorded(self):
        counts, out, asked = self.session(["6", "0", "okay", "", "  ", "1 2", "yes", "OK!", "n", "-1", "01", "quit"])
        self.assertEqual(self.confirmations(self.the_book), [])
        self.assertEqual(len(asked), 12)
        self.assertEqual(out.count("not an answer"), 11)

    def test_the_answer_is_taken_as_typed_after_the_spaces_around_it_are_removed(self):
        _, _, (c,) = self.confirmed(["  3  "])
        self.assertEqual(c["result"]["shelf"], self.event["order"][2])
        self.assertEqual(c["answer"], "3")

    def test_the_event_says_which_proposal_it_answers(self):
        self.session(["1"])
        (c,) = self.confirmations(self.the_book)
        self.assertEqual(c["proposal"], self.event["at"])
        self.assertEqual((c["generation"], c["text_sha256"], c["schema_sha256"]), (self.event["generation"], self.event["text_sha256"], self.event["schema_sha256"]))
        self.assertEqual(c["version"], self.event["version"])

    def test_a_book_goes_on_to_the_next_after_an_answer(self):
        other, _ = self.proposed("Another book", answer="1: x.")
        counts, out, asked = self.session(["1", "2"])
        self.assertEqual(len(self.confirmations(self.the_book)), 1)
        self.assertEqual(len(self.confirmations(other)), 1)
        self.assertEqual(counts["confirmed"], 2)

    def test_a_book_is_only_confirmed_once_unless_again(self):
        self.session(["1"])
        counts, out, asked = self.session(["2"])
        self.assertEqual(asked, [])
        self.assertEqual(len(self.confirmations(self.the_book)), 1)
        self.session(["2"], again=True)
        self.assertEqual(len(self.confirmations(self.the_book)), 2)
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["accepted_pick"], counts["other_shelf"]), (1, 0))       # the latest answer counts: 2 is the model's pick


class Stale(ReviewCase):
    def test_a_proposal_for_a_card_that_has_changed_is_not_confirmable(self):
        book, version = self.proposed("The gene book")
        card.file(self.store, card.make(self.store, book, version, model=dict(copy.deepcopy(MODEL), summary=LONG + " changed", topics=["t"]), records=[]))
        counts, out, asked = self.session(["1"])
        self.assertEqual(asked, [])
        self.assertEqual(self.confirmations(book), [])
        self.assertEqual(counts["stale"], 1)
        self.assertIn("place-propose", out)
        self.propose(book_ids=[book])
        counts, out, asked = self.session(["1"])
        self.assertEqual(len(asked), 1)

    def test_a_proposal_for_another_schema_is_not_confirmable(self):
        book, _ = self.proposed("The gene book")
        data = schema_data()
        data["shelves"][8]["scope"] = "A new scope sentence."
        with open(self.schema_path, "w") as f:
            json.dump(data, f)
        counts, out, asked = self.session(["1"])
        self.assertEqual((asked, counts["stale"]), ([], 1))

    def test_a_proposal_that_is_not_the_shape_this_engine_writes_is_unreadable_and_not_shown(self):
        book, _ = self.proposed("The gene book")
        path = self.store.events_file(book)
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        good = lines[-1]
        for mutate in (lambda e: e["answer"].update(chosen="not-a-shelf"), lambda e: e.update(order=e["order"][:4]), lambda e: e.update(order=["a"] * 5),
                       lambda e: e.update(answer="a string"), lambda e: e["answer"].update(index=9), lambda e: e.update(candidates="x"), lambda e: e.update(generation="one"),
                       lambda e: e["answer"].update(kind="other"), lambda e: e.update(order=[3] * 5)):
            bad = copy.deepcopy(good)
            mutate(bad)
            with open(path, "w") as f:
                f.write(json.dumps(bad) + "\n")
            counts, out, asked = self.session(["1"])
            self.assertEqual(asked, [], bad)
            self.assertEqual(counts["unreadable"], 1, bad)
        with open(path, "w") as f:
            f.write(json.dumps(good) + "\n")
        self.assertEqual(len(self.session(["quit"])[2]), 1)

    def test_each_part_of_the_shape_of_a_proposal_is_checked_on_its_own(self):
        book, _ = self.proposed("The gene book")
        mutations = {
            "a boolean generation": lambda e: e.update(generation=True),
            "a text hash that is not a hash": lambda e: e.update(text_sha256="zz"),
            "a text hash that is not text": lambda e: e.update(text_sha256=7),
            "a schema hash that is not a hash": lambda e: e.update(schema_sha256="zz"),
            "six shelves with five different": lambda e: e.update(order=e["order"] + [e["order"][0]]),
            "the same shelf five times": lambda e: e.update(order=["additive"] * 5, candidates=[["additive", 0.5]] * 5, answer={"kind": "none", "index": None, "chosen": None, "reason": "r"}),
            "five shelves that are not in the schema": lambda e: e.update(order=["a", "b", "c", "d", "e"], candidates=[[s, 0.5] for s in "abcde"],
                                                                         answer={"kind": "none", "index": None, "chosen": None, "reason": "r"}),
            "candidates of other shelves": lambda e: e.update(candidates=[["a", 0.5], ["b", 0.4], ["c", 0.3], ["d", 0.2], ["e", 0.1]]),
            "candidates that are not pairs": lambda e: e.update(candidates=[["additive"]] * 5),
            "candidates with a text score": lambda e: e.update(candidates=[[c[0], "high"] for c in e["candidates"]]),
            "a version that is not text": lambda e: e.update(version=1),
            "no time": lambda e: e.pop("at"),
            "an answer with another kind": lambda e: e["answer"].update(kind="maybe"),
            "an index out of range": lambda e: e["answer"].update(index=6),
            "a chosen shelf that is not the one numbered": lambda e: e["answer"].update(chosen=e["order"][4]),
        }
        original = json.dumps(self.pick_of(book))
        for name, mutate in mutations.items():
            with self.subTest(name):
                self.edit_proposal(book, lambda e: e.clear() or e.update(json.loads(original)))
                self.edit_proposal(book, mutate)
                counts, out, asked = self.session(["1"])
                self.assertEqual((asked, counts["unreadable"]), ([], 1), name)
        self.edit_proposal(book, lambda e: e.clear() or e.update(json.loads(original)))
        self.assertEqual(len(self.session(["quit"])[2]), 1)

    def test_a_proposal_is_stale_when_only_its_generation_its_version_or_its_text_is_not_the_cards(self):
        book, _ = self.proposed("The gene book")
        original = json.dumps(self.pick_of(book))
        for name, mutate in (("generation", lambda e: e.update(generation=5)), ("version", lambda e: e.update(version="v9")), ("text", lambda e: e.update(text_sha256="f" * 64)),
                             ("schema", lambda e: e.update(schema_sha256="e" * 64))):
            with self.subTest(name):
                self.edit_proposal(book, lambda e: e.clear() or e.update(json.loads(original)))
                self.edit_proposal(book, mutate)
                counts, out, asked = self.session(["1"])
                self.assertEqual((asked, counts["stale"]), ([], 1), name)

    def test_a_book_that_is_no_longer_active_is_stale_and_the_review_goes_on(self):
        gone, _ = self.proposed("Weeded book")
        self.store.set_state(gone, "weeded")
        here, _ = self.proposed("Present book")
        counts, out, asked = self.session(["1"])
        self.assertEqual((counts["stale"], counts["confirmed"]), (1, 1))
        self.assertEqual(len(self.confirmations(here)), 1)

    def test_an_event_log_that_cannot_be_read_is_unreadable_and_the_review_goes_on(self):
        bad, _ = self.proposed("Damaged log")
        with open(self.store.events_file(bad), "a") as f:
            f.write("this is not json\n")
        here, _ = self.proposed("Present book")
        counts, out, asked = self.session(["1"])
        self.assertEqual((counts["unreadable"], counts["confirmed"]), (1, 1))
        self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unreadable"], 1)

    def test_an_answer_to_another_proposal_or_of_another_shape_does_not_count(self):
        book, _ = self.proposed("The gene book")
        event = self.pick_of(book)
        base = dict(version=event["version"], generation=event["generation"], text_sha256=event["text_sha256"], schema_sha256=event["schema_sha256"], answer="1",
                    result={"kind": "shelf", "shelf": event["order"][0], "words": None}, equals_pick=False)
        self.store.append_event(book, "placement_confirmed", proposal="2020-01-01T00:00:00+00:00", **base)               # to another proposal
        self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 1)
        for bad in ({"result": "shelf"}, {"result": {"kind": "other"}}, {"equals_pick": "yes"}):
            self.store.append_event(book, "placement_confirmed", proposal=event["at"], **dict(base, **bad))              # of another shape
        self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 1)
        self.store.append_event(book, "placement_confirmed", proposal=event["at"], **base)
        self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["confirmed"], 1)

    def test_a_confirmation_is_checked_as_closely_as_a_proposal(self):
        book, _ = self.proposed("The gene book")
        event = self.pick_of(book)
        base = dict(proposal=event["at"], version=event["version"], generation=event["generation"], text_sha256=event["text_sha256"], schema_sha256=event["schema_sha256"],
                    answer="1", equals_pick=False)
        slug = event["order"][0]
        bad_equal = [dict(base, result={"kind": "shelf", "shelf": slug, "words": None}, equals_pick=None), dict(base, result={"kind": "none", "shelf": None, "words": None}, equals_pick=None),
                     dict(base, result={"kind": "skipped", "shelf": None, "words": "w"}, equals_pick=True), dict(base, result={"kind": "skipped", "shelf": None, "words": "w"}, equals_pick=False)]
        for forged in bad_equal:
            with self.subTest(equals=forged["result"]["kind"], value=forged["equals_pick"]):
                self.store.append_event(book, "placement_confirmed", **{k: v for k, v in forged.items()})
                self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 1)
        bad = [{"kind": "shelf", "shelf": "not-a-shelf", "words": None}, {"kind": "shelf", "shelf": 7, "words": None}, {"kind": "shelf", "shelf": None, "words": None},
               {"kind": "shelf", "shelf": slug, "words": "unexpected words"}, {"kind": "none", "shelf": slug, "words": None}, {"kind": "none", "shelf": None, "words": "w"},
               {"kind": "skipped", "shelf": None, "words": None}, {"kind": "skipped", "shelf": None, "words": "x" * 301}, {"kind": "skipped", "shelf": slug, "words": "w"},
               {"kind": "skipped", "shelf": None, "words": 7}, {"kind": "skipped", "shelf": None, "words": " "}, {"kind": "skipped", "shelf": None, "words": "   "},
               {"kind": "shelf", "shelf": slug}, {"kind": "shelf", "shelf": slug, "words": None, "extra": 1}]
        def equality(result):
            return None if isinstance(result, dict) and result.get("kind") == "skipped" else False          # the flag that goes with each kind, so that only the result is wrong
        for result in bad:
            with self.subTest(result=result):
                self.store.append_event(book, "placement_confirmed", result=result, **dict(base, equals_pick=equality(result)))
                self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 1)
        for good in ({"kind": "shelf", "shelf": slug, "words": None}, {"kind": "none", "shelf": None, "words": None}, {"kind": "skipped", "shelf": None, "words": "fine"}):
            with self.subTest(good=good):
                self.store.append_event(book, "placement_confirmed", result=good, **dict(base, equals_pick=equality(good)))
                self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 0)
                self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["confirmed"] + placereview.listing(self.store, schema_path=self.schema_path)["skipped"], 1)
                self.store.append_event(book, "placement_confirmed", result={"kind": "other"}, **base)               # an answer of the wrong shape does not undo the one before it
                self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["unconfirmed"], 0)

    def test_a_book_with_only_an_error_has_no_proposal_to_confirm(self):
        book, _ = self.proposed("Book error", answer=KbError("down"))
        counts, out, asked = self.session(["1"])
        self.assertEqual((asked, counts["no_proposal"]), ([], 1))


class Safe(ReviewCase):
    def test_every_text_shown_is_cleaned_of_control_and_escape_characters(self):
        hostile = "\x1b[31mRED\x1b[0m \x07bell \u202eRTL \u200bzero \x00nul \r carriage"
        book, version = self.book_with("Hostile title " + hostile, summary=LONG + " " + hostile, topics=["topic " + hostile], target="gene-editing")
        self.answers["Hostile title"] = "1: " + hostile.replace("\n", " ")
        self.propose(book_ids=[book])
        counts, out, asked = self.session(["quit"])
        for ch in out:
            if ch != "\n":
                self.assertNotEqual(unicodedata.category(ch)[0], "C", repr(ch))
        self.assertIn("RED", out)
        self.assertNotIn("\x1b", out)

    def test_a_reason_with_hidden_characters_is_shown_without_them(self):
        book, _ = self.proposed("The gene book", answer="1: Fine\u2800\u3164 reason\u034f.")      # hidden but not control characters: the reader lets them through
        _, out, _ = self.session(["quit"])
        self.assertIn("Fine reason.", out)

    def test_the_characters_the_engine_hides_are_not_shown_either(self):
        for ch in ("\u180b", "\u180c", "\u180d", "\u180f", "\ufe00", "\ufe0f", "\U000e0100", "\u2800", "\u3164", "\u034f", "\u200b", "\u202e", "\x1b"):
            with self.subTest(ch=repr(ch)):
                self.assertEqual(placereview.safe("a" + ch + "b", 50), "ab")
        self.assertEqual(placereview.safe("a \u180b b", 50), "a b")

    def test_a_long_run_of_combining_marks_and_compatibility_forms_are_made_plain(self):
        self.assertLessEqual(len(placereview.safe("a" + "\u0301" * 100, 300)), 4)                       # as many marks as the measured text rule keeps
        self.assertEqual(placereview.safe("\uff21\uff22\uff23 \ufb01", 20), "ABC fi")                       # full-width letters and a ligature
        self.assertEqual(placereview.safe("<\uff1c\uff1c", 20), "<<<")

    def test_the_prompt_asked_holds_no_text_of_the_book(self):
        self.proposed("The gene book", summary=LONG + " UNIQUEWORD")
        _, out, asked = self.session(["quit"])
        self.assertNotIn("UNIQUEWORD", " ".join(asked))

    def test_a_long_summary_is_shown_whole_up_to_what_a_card_can_hold_and_a_huge_text_is_cut(self):
        self.proposed("The gene book", summary="word " * 280)
        _, out, _ = self.session(["quit"])
        self.assertGreater(max(len(l) for l in out.splitlines() if "word word" in l), 1350)
        self.assertEqual(len(placereview.safe("x" * 10 ** 7, 100)), 100)
        self.assertEqual(len(placereview.safe("y " * 10 ** 6, 301)), 301)


HOSTILE = "\x1b[31mRED\x1b[0m \x07bell \u202eRTL \u200bzero \x00nul \r carriage \u2800 \u3164"


class ShownDirectly(ReviewCase):
    """`_show` with a hostile value in every field it prints: a card made by the engine already has a cleaned title and address, so only a direct call reaches the display's own cleaning."""

    def schema(self, **over):
        names = {"additive": "Add " + HOSTILE, "gene-editing": "Gene " + HOSTILE, "handicrafts": "Hand " + HOSTILE, "lean": "Lean " + HOSTILE, "pid": "PID " + HOSTILE}
        by_slug = {slug: {"name": names[slug], "scope": "Scope " + HOSTILE} for slug in names}
        by_slug["domain-x"] = {"name": "Domain " + HOSTILE, "scope": ""}
        by_slug["field-x"] = {"name": "Field " + HOSTILE, "scope": ""}
        by_slug["sub-x"] = {"name": "Sub " + HOSTILE, "scope": ""}
        ancestors = {slug: {"domain": "domain-x", "field": "field-x", "subfield": "sub-x"} for slug in names}
        ancestors["handicrafts"] = None
        return types.SimpleNamespace(by_slug=by_slug, ancestors=ancestors)

    def show(self, made, answer, schema=None):
        proposal = {"version": "v1", "generation": 1, "order": ["additive", "gene-editing", "handicrafts", "lean", "pid"], "answer": answer}
        shown = []
        with mock.patch.object(card, "read", return_value=(1, made)):
            placereview._show(shown.append, self.store, "book", proposal, schema or self.schema(), 1, 1)
        return "\n".join(shown)

    def assertClean(self, out):
        for ch in out:
            if ch != "\n":
                self.assertNotEqual(unicodedata.category(ch)[0], "C", repr(ch))
        for ch in "\u2800\u3164":
            self.assertNotIn(ch, out)

    def test_a_title_an_address_a_summary_and_every_shelf_text_are_cleaned_whatever_the_card_holds(self):
        made = {"title": "Title " + HOSTILE, "source": {"address_final": "https://example.org/" + HOSTILE}, "model": {"summary": "Summary " + HOSTILE}}
        for answer in ({"kind": "shelf", "index": 2, "chosen": "gene-editing", "reason": "Reason " + HOSTILE},
                       {"kind": "none", "index": None, "chosen": None, "reason": "Reason " + HOSTILE}):
            with self.subTest(kind=answer["kind"]):
                out = self.show(made, answer)
                self.assertClean(out)
                for word in ("Title ", "https://example.org/", "Summary ", "Add ", "Domain ", "Field ", "Sub ", "Scope ", "Reason "):
                    self.assertIn(word + "[31mRED[0m bell RTL zero nul carriage", out)     # the escape character is gone, what followed it is plain text

    def test_the_owner_sees_all_the_text_the_model_saw_the_summary_in_full_and_the_topics(self):
        summary = "start " + "word " * 280 + "THE-END"
        out = self.show({"title": "T", "model": {"summary": summary, "topics": ["first topic", "second\x1b topic"]}}, {"kind": "none", "index": None, "chosen": None, "reason": "r"})
        self.assertIn("THE-END", out)
        self.assertIn("Topics: first topic; second topic", out)
        none = self.show({"title": "T", "model": {"summary": "S", "topics": []}}, {"kind": "none", "index": None, "chosen": None, "reason": "r"})
        self.assertNotIn("Topics:", none)

    def test_the_address_asked_and_an_arxiv_id_stand_in_for_a_missing_final_address(self):
        answer = {"kind": "none", "index": None, "chosen": None, "reason": "r"}
        self.assertIn("https://example.org/asked", self.show({"title": "T", "source": {"address_asked": "https://example.org/asked"}, "model": {"summary": "S"}}, answer))
        self.assertIn("https://arxiv.org/abs/2001.00001", self.show({"title": "T", "source": {"arxiv_id": "2001.00001"}, "model": {"summary": "S"}}, answer))
        out = self.show({"title": "T", "source": {"arxiv_id": "bad id with spaces\x1b"}, "model": {"summary": "S"}}, answer)
        self.assertNotIn("arxiv.org", out)

    def test_the_shelves_are_numbered_in_the_order_of_the_proposal_not_in_any_order_of_their_own(self):
        out = self.show({"title": "T", "model": {"summary": "S"}}, {"kind": "none", "index": None, "chosen": None, "reason": "r"})
        numbered = [l.split("|")[0].strip() for l in out.splitlines() if l.startswith("  ")]
        self.assertEqual([n.split(". ")[1].split(" ")[0] for n in numbered], ["Add", "Gene", "Hand", "Lean", "PID"])
        proposal_order = ["pid", "lean", "handicrafts", "gene-editing", "additive"]
        shown = []
        with mock.patch.object(card, "read", return_value=(1, {"title": "T", "model": {"summary": "S"}})):
            placereview._show(shown.append, self.store, "book", {"version": "v1", "generation": 1, "order": proposal_order, "answer": {"kind": "none", "index": None, "chosen": None, "reason": "r"}},
                              self.schema(), 1, 1)
        numbered = [l.split("|")[0].strip() for l in shown if l.startswith("  ")]
        self.assertEqual([n.split(". ")[1].split(" ")[0] for n in numbered], ["PID", "Lean", "Hand", "Gene", "Add"])


class Unchanged(ReviewCase):
    def test_a_book_its_card_and_its_shelf_are_unchanged_and_only_its_event_log_gains_lines(self):
        book, version = self.proposed("The gene book")
        before = {}
        for root_, _, files in os.walk(self.store.book_dir(book)):
            for name in files:
                if name != "events.jsonl":
                    with open(os.path.join(root_, name), "rb") as f:
                        before[os.path.join(root_, name)] = f.read()
        with open(self.store.events_file(book)) as f:
            events_before = f.read()
        self.session(["1"])
        after = {}
        for root_, _, files in os.walk(self.store.book_dir(book)):
            for name in files:
                if name != "events.jsonl":
                    with open(os.path.join(root_, name), "rb") as f:
                        after[os.path.join(root_, name)] = f.read()
        self.assertEqual(before, after)
        self.assertEqual(self.store.read_book(book)["shelf"], "default")
        with open(self.store.events_file(book)) as f:
            events_after = f.read()
        self.assertTrue(events_after.startswith(events_before))
        self.assertEqual(len(events_after.splitlines()) - len(events_before.splitlines()), 1)


class Terminal(ReviewCase):
    def test_the_review_refuses_when_its_input_is_not_a_terminal_and_records_nothing(self):
        book, _ = self.proposed("The gene book")
        with self.assertRaisesRegex(KbError, "terminal"):
            self.session(["1"], tty=False)
        self.assertEqual(self.confirmations(book), [])

    def test_the_command_refuses_a_piped_input_and_takes_no_answer_from_an_argument_or_a_file(self):
        book, _ = self.proposed("The gene book")
        run = lambda *a, **k: subprocess.run([sys.executable, "-m", "kb", *a], cwd=ENGINE_DIR, env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=120, **k)
        r = run("place-review", input="1\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("terminal", r.stderr)
        r = run("place-review", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        self.assertNotEqual(run("place-review", "--answer", "1").returncode, 0)
        self.assertNotEqual(run("place-review", "--answers-from", "/dev/null").returncode, 0)
        self.assertEqual(self.confirmations(book), [])


class Listing(ReviewCase):
    def test_the_counts_say_where_each_book_stands_and_need_no_terminal(self):
        a, _ = self.proposed("Book a", answer="1: x.")
        b, _ = self.proposed("Book b", answer="1: x.")
        c, _ = self.proposed("Book c", answer="1: x.")
        d, _ = self.proposed("Book d", answer="1: x.")
        e, _ = self.proposed("Book e", answer="1: x.")
        f, vf = self.proposed("Book f", answer="1: x.")
        g, _ = self.proposed("Book g", answer=KbError("down"))
        h, _ = self.proposed("Book h", answer="none: no.")
        self.session(["ok", "3", "none", "skip I cannot judge it", "quit"], book_ids=[a, b, c, d, e])
        card.file(self.store, card.make(self.store, f, vf, model=dict(copy.deepcopy(MODEL), summary=LONG + " changed", topics=["t"]), records=[]))
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual(counts["accepted_pick"], 1)       # a: ok
        self.assertEqual(counts["other_shelf"], 1)         # b: 3
        self.assertEqual(counts["none"], 1)                # c: none
        self.assertEqual(counts["skipped"], 1)             # d: skip
        self.assertEqual(counts["unconfirmed"], 2)         # e and h (quit stopped before h)
        self.assertEqual(counts["stale"], 1)               # f
        self.assertEqual(counts["no_proposal"], 1)         # g
        self.assertEqual(counts["confirmed"], 3)           # a, b and c; the skipped book d is counted apart
        self.assertEqual(counts["books"], 8)

    def test_a_book_with_no_event_is_not_counted(self):
        self.book_with("Never proposed")
        self.assertEqual(placereview.listing(self.store, schema_path=self.schema_path)["books"], 0)

    def test_the_listing_changes_nothing(self):
        book, _ = self.proposed("The gene book")
        with open(self.store.events_file(book)) as f:
            before = f.read()
        placereview.listing(self.store, schema_path=self.schema_path)
        with open(self.store.events_file(book)) as f:
            self.assertEqual(f.read(), before)


class Choosing(ReviewCase):
    def test_a_book_may_be_named_and_an_unknown_one_is_refused(self):
        a, _ = self.proposed("Book a")
        b, _ = self.proposed("Book b")
        counts, out, asked = self.session(["1"], book_ids=[b])
        self.assertEqual((len(self.confirmations(a)), len(self.confirmations(b))), (0, 1))
        with self.assertRaises(KbError):
            self.session(["1"], book_ids=["no-such-book"])

    def test_the_books_come_in_the_order_of_the_library(self):
        names = ["Title-A", "Title-B", "Title-C"]
        books = [self.proposed(name)[0] for name in names]
        counts, out, asked = self.session(["1", "1", "1"])
        shown = sorted(range(3), key=lambda i: out.index(names[i] + "\n"))
        self.assertEqual([books[i] for i in shown], [b for b in self.store.list_books() if b in books])

    def test_the_books_named_are_a_list_of_ids(self):
        self.proposed("The gene book")
        for bad in ("a-string", [7], [None], 7):
            with self.subTest(bad=bad):
                with self.assertRaises(KbError):
                    self.session(["1"], book_ids=bad)

    def test_again_must_be_true_or_false(self):
        self.proposed("The gene book")
        with self.assertRaises(KbError):
            self.session(["1"], again="yes")


class MovedBooks(ReviewCase):
    """A book that has been moved onto a shelf is not on `default` any more: its shelf is decided, so it is neither stale nor asked again (Increment B of the plan `2026-11-16-move-confirmed-books-onto-their-shelves`)."""

    def moved(self, title, answer="2: Because.", key=None):
        book, _ = self.proposed(title, answer=answer)
        if key:
            self.session([key], book_ids=[book])
        self.store.set_shelf(book, "gene-editing")
        return book

    def test_an_unanswered_book_that_was_moved_is_counted_as_moved_and_not_as_stale_or_unconfirmed(self):
        self.moved("The gene book")
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["moved"], counts["stale"], counts["unconfirmed"], counts["confirmed"]), (1, 0, 0, 0))

    def test_an_answered_book_that_was_moved_is_counted_as_moved_and_not_as_confirmed(self):
        self.moved("The gene book", key="ok")
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["moved"], counts["confirmed"], counts["accepted_pick"], counts["books"]), (1, 0, 0, 1))

    def test_a_moved_book_is_not_asked_about_again_even_with_again(self):
        book = self.moved("The gene book", key="ok")
        for again in (False, True):
            with self.subTest(again=again):
                counts, out, asked = self.session(["1"], again=again)
                self.assertEqual((asked, counts["moved"], counts["asked"]), ([], 1, 0))
        self.assertEqual(len(self.confirmations(book)), 1)

    def test_a_moved_book_that_is_named_is_said_to_be_moved(self):
        book = self.moved("The gene book")
        counts, out, asked = self.session(["1"], book_ids=[book])
        self.assertEqual((asked, counts["moved"]), ([], 1))
        self.assertIn("no longer on the shelf default", out)

    def test_a_book_with_no_shelf_or_a_shelf_that_is_not_a_shelf_name_is_not_taken_for_moved(self):
        for name, value in (("none", None), ("a list", ["x"]), ("empty", ""), ("a path", "../x"), ("a number", 5), ("upper case", "Gene")):
            with self.subTest(name):
                self.setUp()
                book, _ = self.proposed("The gene book")
                self.store._rewrite(self.store.book_file(book), lambda root: root.__setitem__("shelf", value))
                counts = placereview.listing(self.store, schema_path=self.schema_path)
                self.assertEqual(counts["moved"], 0, name)

    def test_a_moved_book_that_is_not_named_is_counted_without_a_word_said(self):
        self.moved("The gene book")
        counts, out, asked = self.session(["1"])
        self.assertEqual((counts["moved"], asked), (1, []))
        self.assertNotIn("no longer on the shelf", out)

    def test_a_moved_book_with_a_failed_proposal_is_moved_all_the_same(self):
        self.moved("The gene book", answer=KbError("the server is down"))
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["moved"], counts["no_proposal"]), (1, 0))

    def test_a_book_whose_root_file_cannot_be_read_is_not_taken_for_moved(self):
        book, _ = self.proposed("The gene book")
        with open(self.store.book_file(book), "w") as f:
            f.write("{")
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["moved"], counts["unreadable"]), (0, 1))   # the reader of the event log reads the root file first, so such a book is unreadable


class CommandLine(ReviewCase):
    def test_the_flags_are_handed_on_and_the_listing_prints_counts_as_json(self):
        from kb import __main__ as cli
        book, _ = self.proposed("The gene book")
        with mock.patch.object(placereview, "listing", return_value={"books": 1}) as listed, mock.patch.object(placereview, "review", return_value={"confirmed": 0}) as reviewed:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli.main(["place-review", "--list"]), 0)
                self.assertEqual(cli.main(["place-review", "--again", "--book", book]), 0)
        self.assertEqual(json.loads(out.getvalue().splitlines()[0]), {"books": 1})
        self.assertEqual((reviewed.call_args.kwargs["again"], reviewed.call_args.kwargs["book_ids"]), (True, [book]))
        listed.assert_called_once()

    def test_the_command_is_listed(self):
        r = subprocess.run([sys.executable, "-m", "kb", "--help"], cwd=ENGINE_DIR, env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=120)
        self.assertIn("place-review", r.stdout)


class AcceptPicks(ReviewCase):
    """The step that answers `ok` for every unanswered book that has a pick (plan `2026-11-20-accept-the-models-picks-for-all-proposed-books-in-one-step`, Increment A)."""

    def setUp(self):
        super().setUp()
        self.a, _ = self.proposed("Book a", answer="2: Because a.", source={"address_final": "https://example.org/a", "retrieved": "2026-11-01T00:00:00+00:00", "sha256": "ab" * 32})
        self.b, _ = self.proposed("Book b", answer="none: Nothing fits b.")

    def preview(self):
        return placereview.accept_preview(self.store, schema_path=self.schema_path)

    def accept(self, digest, tty=True, **kw):
        return placereview.accept_picks(self.store, digest, schema_path=self.schema_path, is_tty=lambda: tty, say=lambda text: None, **kw)

    def lines(self):
        return {b: self.store.read_events(b) for b in self.store.list_books()}

    def test_the_list_holds_the_unanswered_books_with_a_pick_or_a_none_and_counts_the_others_by_reason(self):
        c, _ = self.proposed("Book c", answer="I would say two")                  # malformed: no pick
        d, _ = self.proposed("Book d", answer="1: x.")
        self.session(["ok"], book_ids=[d])                                          # answered
        e, ve = self.proposed("Book e", answer="1: x.")
        card.file(self.store, card.make(self.store, e, ve, model=dict(copy.deepcopy(MODEL), summary=LONG + " changed", topics=["t"]), records=[]))   # stale
        f, _ = self.proposed("Book f", answer="1: x.")
        with open(self.store.events_file(f), "a") as fh:
            fh.write("this is not json\n")                                          # unreadable
        g, _ = self.proposed("Book g", answer="1: x.")
        self.store.set_shelf(g, "gene-editing")                                     # moved
        h, _ = self.proposed("Book h", answer=KbError("down"))                      # error: no proposal
        text, digest, items, left = self.preview()
        self.assertEqual([i["book"] for i in items], [self.a, self.b])
        self.assertEqual(left, {"no_pick": 1, "confirmed": 1, "stale": 1, "unreadable": 1, "moved": 1, "no_proposal": 1})
        self.assertIsNone(items[1]["pick"])
        self.assertIn("Left out: 6 books", text)
        for words in ("with a proposal that has no pick", "already answered", "out of date", "cannot be read", "no longer on the shelf default", "is an error"):
            self.assertRegex(text, r"(?m)^  1 .*%s" % words)

    def test_a_card_that_cannot_be_read_when_the_list_is_made_leaves_the_book_out_as_stale(self):
        real = card.read

        def read(*a, **k):
            if sys._getframe(1).f_code.co_name == "accept_plan":
                raise KbError("gone")
            return real(*a, **k)
        with mock.patch.object(card, "read", read):
            _, _, items, left = self.preview()
        self.assertEqual((items, left["stale"]), ([], 2))

    def test_the_text_names_each_book_counts_each_shelf_and_ends_with_its_digest(self):
        import hashlib
        import re
        text, digest, items, left = self.preview()
        pick = self.pick_of(self.a)["order"][1]
        by_slug = {s["slug"]: s for s in schema_data()["shelves"]}
        for word in ("Book a", "Book b", "https://example.org/a", by_slug[pick]["name"], "Because a.", "Nothing fits b.", self.a, self.b, self.pick_of(self.a)["text_sha256"]):
            self.assertIn(word, text)
        self.assertRegex(text, r"(?m)^1 .*%s" % re.escape(by_slug[pick]["name"]))   # a count for the shelf
        self.assertRegex(text, r"(?m)^1 .*none")
        body, last = text.rsplit("\n", 1)
        self.assertEqual(last, "digest: " + digest)
        self.assertRegex(digest, r"[0-9a-f]{32}")
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest()[:32], digest)

    def test_the_preview_writes_nothing_and_takes_no_lock(self):
        before = self.lines()
        with mock.patch.object(placereview.catalog, "lock", side_effect=AssertionError("the preview takes no lock")):
            self.preview()
        self.assertEqual(self.lines(), before)

    def test_the_digest_changes_when_any_field_of_the_list_changes(self):
        _, first, _, _ = self.preview()
        self.edit_proposal(self.a, lambda e: e["answer"].__setitem__("reason", "A different reason."))
        _, second, _, _ = self.preview()
        self.assertNotEqual(first, second)
        self.proposed("Book c", answer="1: x.")
        _, third, _, _ = self.preview()
        self.assertNotEqual(second, third)

    def test_the_step_writes_one_line_for_each_book_of_the_shape_of_ok_and_nothing_else(self):
        twin, _ = self.proposed("Book twin", answer="2: Because a.")
        self.session(["ok"], book_ids=[twin])
        (typed,) = self.confirmations(twin)
        before = self.lines()
        _, digest, _, _ = self.preview()
        result = self.accept(digest)
        self.assertEqual(result["answered"], [self.a, self.b])
        (ca,) = self.confirmations(self.a)
        (cb,) = self.confirmations(self.b)
        proposal = self.pick_of(self.a)
        self.assertEqual(ca["result"], {"kind": "shelf", "shelf": proposal["order"][1], "words": None})
        self.assertEqual((cb["result"], cb["equals_pick"], ca["equals_pick"]), ({"kind": "none", "shelf": None, "words": None}, True, True))
        self.assertEqual(ca["answer"], "accept-picks")
        self.assertEqual(set(ca), set(typed))
        self.assertEqual((ca["proposal"], ca["version"], ca["generation"], ca["text_sha256"], ca["schema_sha256"]),
                         (proposal["at"], proposal["version"], proposal["generation"], proposal["text_sha256"], proposal["schema_sha256"]))
        after = self.lines()
        for book in before:
            self.assertEqual(after[book][:len(before[book])], before[book])                     # nothing is changed, only added to
            self.assertEqual(len(after[book]) - len(before[book]), 1 if book in (self.a, self.b) else 0)

    def test_a_book_answered_by_the_step_is_confirmed_in_the_listing_and_is_listed_by_place_apply(self):
        from kb import placeapply
        _, digest, _, _ = self.preview()
        self.accept(digest)
        counts = placereview.listing(self.store, schema_path=self.schema_path)
        self.assertEqual((counts["confirmed"], counts["accepted_pick"], counts["none"], counts["unconfirmed"]), (2, 1, 1, 0))
        items, _, _ = placeapply.plan(self.store, schema_path=self.schema_path)
        self.assertEqual([i["book"] for i in items], [self.a])
        self.assertEqual(items[0]["typed"], "accept-picks")

    def test_a_second_run_has_an_empty_list_and_writes_nothing(self):
        _, digest, _, _ = self.preview()
        self.accept(digest)
        before = self.lines()
        _, again, items, _ = self.preview()
        self.assertEqual(items, [])
        self.assertEqual(self.accept(again)["answered"], [])
        self.assertEqual(self.lines(), before)

    def test_a_digest_that_is_not_the_shape_of_one_or_is_of_another_list_is_refused_and_writes_nothing(self):
        before = self.lines()
        for bad in (None, "", "abc", "A" * 32, "g" * 32, "0" * 31, "0" * 33, 12):
            with self.assertRaisesRegex(KbError, "32 lowercase hexadecimal"):
                self.accept(bad)
        with self.assertRaisesRegex(KbError, "digest"):
            self.accept("0" * 32)
        self.assertEqual(self.lines(), before)

    def test_a_list_that_changed_after_the_preview_is_refused_and_writes_nothing(self):
        _, digest, _, _ = self.preview()
        self.session(["1"], book_ids=[self.a])                                      # the owner answers a book in between
        before = self.lines()
        with self.assertRaisesRegex(KbError, "changed"):
            self.accept(digest)
        self.assertEqual(self.lines(), before)

    def test_the_step_refuses_without_a_terminal_for_input_and_output_both_and_writes_nothing(self):
        _, digest, _, _ = self.preview()
        before = self.lines()
        tty, no = types.SimpleNamespace(isatty=lambda: True), types.SimpleNamespace(isatty=lambda: False)
        with self.assertRaisesRegex(KbError, "terminal"):
            self.accept(digest, tty=False)
        for stdin, stdout in ((tty, no), (no, tty), (no, no)):
            with mock.patch.object(placereview.sys, "stdin", stdin), mock.patch.object(placereview.sys, "stdout", stdout):
                with self.assertRaisesRegex(KbError, "terminal"):
                    placereview.accept_picks(self.store, digest, schema_path=self.schema_path, say=lambda text: None)
        self.assertEqual(self.lines(), before)
        with mock.patch.object(placereview.sys, "stdin", tty), mock.patch.object(placereview.sys, "stdout", tty):
            self.assertEqual(len(placereview.accept_picks(self.store, digest, schema_path=self.schema_path, say=lambda text: None)["answered"]), 2)

    def test_the_step_refuses_a_store_that_is_open_read_only(self):
        _, digest, _, _ = self.preview()
        before = self.lines()
        with mock.patch.object(self.store, "write", False), mock.patch.object(placereview.catalog, "lock", side_effect=AssertionError("refused before the lock")):
            with self.assertRaisesRegex(KbError, "read-only"):
                self.accept(digest)
        self.assertEqual(self.lines(), before)

    def test_the_step_holds_the_catalog_lock_while_it_writes(self):
        _, digest, _, _ = self.preview()
        held = []
        real = placereview.catalog.lock

        class Spy:
            def __init__(self, root):
                self.inner = real(root)

            def __enter__(self):
                held.append("in")
                return self.inner.__enter__()

            def __exit__(self, *a):
                held.append("out")
                return self.inner.__exit__(*a)
        original = self.store.append_event

        def appending(*a, **k):
            held.append("append")
            return original(*a, **k)
        with mock.patch.object(placereview.catalog, "lock", Spy), mock.patch.object(self.store, "append_event", appending):
            self.accept(digest)
        self.assertEqual(held, ["in", "append", "append", "out"])

    def test_a_stop_in_the_middle_leaves_the_books_answered_so_far_and_a_second_run_answers_the_rest(self):
        _, digest, _, _ = self.preview()
        original, calls = self.store.append_event, []

        def failing(*a, **k):
            calls.append(a[0])
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return original(*a, **k)
        with mock.patch.object(self.store, "append_event", failing):
            with self.assertRaisesRegex(KbError, "stopped at the book"):
                self.accept(digest)
        self.assertEqual((len(self.confirmations(self.a)), len(self.confirmations(self.b))), (1, 0))
        _, again, items, _ = self.preview()
        self.assertEqual([i["book"] for i in items], [self.b])
        self.accept(again)
        self.assertEqual(len(self.confirmations(self.b)), 1)

    def test_every_text_shown_is_cleaned_of_control_and_escape_characters(self):
        self.proposed("Evil \x1b[31mtitle\x1b[0m‮ book", answer="1: Reason \x1b]0;x\x07 here.")
        text, _, _, _ = self.preview()
        for bad in ("\x1b", "\x07", "‮"):
            self.assertNotIn(bad, text)


class AcceptDirectly(ShownDirectly):
    """`accept_render` with a hostile value in every field it prints: a card and a proposal made by the engine are already clean, so only a direct call reaches the display's own cleaning."""

    def test_a_title_an_address_a_reason_and_every_shelf_text_are_cleaned_whatever_the_card_and_the_proposal_hold(self):
        made = {"title": "Title " + HOSTILE, "source": {"address_final": "https://example.org/" + HOSTILE}}
        for answer in ({"kind": "shelf", "index": 2, "chosen": "gene-editing", "reason": "Reason " + HOSTILE},
                       {"kind": "none", "index": None, "chosen": None, "reason": "Reason " + HOSTILE}):
            with self.subTest(kind=answer["kind"]):
                proposal = {"at": "2026-11-20T00:00:00+00:00", "version": "v1", "generation": 1, "text_sha256": "a" * 64, "schema_sha256": "b" * 64, "answer": answer}
                with mock.patch.object(placereview.shelfvectors, "_read_schema", return_value=(self.schema(), "c" * 64)), \
                        mock.patch.object(placereview, "state_of", return_value=("unconfirmed", proposal, None)), \
                        mock.patch.object(card, "read", return_value=(1, made)), mock.patch.object(self.store, "list_books", return_value=["book"]):
                    text, _, items, _ = placereview.accept_preview(self.store)
                self.assertEqual(len(items), 1)
                self.assertClean(text)
                for word in ("Title ", "https://example.org/", "Reason "):
                    self.assertIn(word, text)
                if answer["kind"] == "shelf":
                    for word in ("Gene ", "Domain ", "Field ", "Sub "):
                        self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
