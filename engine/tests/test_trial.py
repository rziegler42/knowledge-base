import copy
from contextlib import closing
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_cardmake import LibraryCase, block

from kb import KbError, card, catalog, index, models, search, trial


def make_model(**over):
    """A card's model part in which every field says 'filler', so that a query only finds what a test puts in."""
    out = {"summary": "filler summary", "useful_for": ["filler use"], "topics": ["filler topic"], "adjacent_topics": ["filler near"],
           "key_ideas": ["filler idea one", "filler idea two", "filler idea three"], "neutral_problem": "filler problem",
           "neutral_approach": "filler approach", "neutral_needs": "filler needs", "neutral_provides": "filler provides",
           "neutral_limits": "filler limits", "caveats": []}
    out.update(over)
    return out


class TrialCase(LibraryCase):
    def add(self, title, text, model=None, blocks=None):
        book, version = self.converted_book(blocks=blocks or [block(text)], title=title)
        if model is not None:
            card.file(self.store, card.make(self.store, book, version, model=model, records=[]))
        return book

    def build(self):
        index.rebuild(self.store)
        catalog.rebuild(self.store)

    def write_corpus(self, questions, name="corpus.json", **extra):
        path = os.path.join(self.base, name)
        with open(path, "w") as f:
            json.dump({"format": 1, "questions": questions, **extra}, f)
        return path

    def report_path(self, name="report.json"):
        return os.path.join(self.base, name)

    def run_trial(self, questions, **extra):
        return trial.run(self.store, self.write_corpus(questions, **extra), self.report_path())

    def load_report(self):
        return self.load_report_at(self.report_path())

    def load_report_at(self, path):
        with open(path) as f:
            return json.load(f)


class HandWorkedTest(TrialCase):
    """Five questions over four books, worked out on paper before any code was written."""

    def setUp(self):
        super().setUp()
        self.a = self.add("Alpha", "zebra method for deciding", make_model(
            summary="sequential testing", topics=["stopping"], neutral_problem="when to quit watching"))
        self.b = self.add("Beta", "zebra foraging patches", make_model(
            summary="foraging in patches", topics=["leaving"], neutral_problem="when to leave a source"))
        self.c = self.add("Gamma", "tides moon cycles", make_model(
            summary="tides and lunar cycles", topics=["moon"], neutral_problem="periodic prediction"))
        self.d = self.add("Delta", "walrus ocean")  # converted, no card: uncovered
        self.build()
        self.questions = [
            {"id": "q1", "text": "How to stop early?", "queries": ["stopping", "quit watching"], "right": [self.a]},
            {"id": "q2", "text": "Zebra?", "queries": ["zebra"], "right": [self.a, self.b]},
            {"id": "q3", "text": "Tides?", "queries": ["tides", "moon"], "right": [self.c, self.d]},
            {"id": "q4", "text": "Method or foraging?", "queries": ["method", "foraging"], "right": [self.a, self.b]},
            {"id": "q5", "text": "Filler?", "queries": ["filler"], "right": [self.c]},
        ]
        self.summary = self.run_trial(self.questions)
        self.report = self.load_report()
        self.by_id = {q["id"]: q for q in self.report["questions"]}

    def found(self, qid, search_name):
        return self.by_id[qid]["searches"][search_name]["found"]

    def test_a_query_that_finds_nothing_in_one_search_and_something_in_the_other(self):
        self.assertEqual(self.found("q1", "cards"), {self.a: 1})
        self.assertEqual(self.found("q1", "text"), {self.a: None})

    def test_the_union_over_the_queries_takes_the_best_place_of_each_book(self):
        q4 = self.by_id["q4"]
        self.assertEqual([qq["books"]["text"] for qq in q4["queries"]], [[self.a], [self.b]])  # each query finds one of them
        self.assertEqual(self.found("q4", "text"), {self.a: 1, self.b: 1})  # a tie of places, each found by one query
        self.assertEqual(q4["searches"]["text"]["order"], sorted([self.a, self.b]))  # and a tie is ordered by book id
        self.assertEqual(self.found("q4", "cards"), {self.a: None, self.b: 1})

    def test_a_book_found_by_one_of_two_queries_is_found(self):
        self.assertEqual(self.found("q1", "summary"), {self.a: 1})  # "stopping" is on the summary side, "quit watching" is not
        self.assertEqual(self.found("q1", "neutral"), {self.a: 1})  # "quit watching" is on the neutral side, "stopping" is not

    def test_both_books_of_a_question_found_by_the_text_have_places_one_and_two(self):
        found = self.found("q2", "text")
        self.assertEqual(sorted(found.values()), [1, 2])
        self.assertEqual(self.found("q2", "cards"), {self.a: None, self.b: None})

    def test_an_uncovered_book_is_listed_and_kept_out_of_the_card_measures(self):
        self.assertEqual(self.report["uncovered"], [{"book_id": self.d, "reason": "no card", "questions": ["q3"]}])
        self.assertNotIn(self.d, self.found("q3", "cards"))
        self.assertEqual(self.found("q3", "text"), {self.c: 1, self.d: None})

    def test_the_sets_over_the_covered_pairs(self):
        sets = self.summary["sets"]
        self.assertEqual(sets, {"cards_only": 2, "text_only": 3, "both": 2, "neither": 0, "of": 7})

    def test_recall_hit_rate_and_noise_with_their_counts(self):
        s = self.summary
        self.assertEqual((s["pairs"], s["covered_pairs"], s["uncovered_pairs"], s["questions"]), (8, 7, 1, 5))
        self.assertEqual(s["recall"]["cards"], {"found": 4, "of": 7})
        self.assertEqual(s["recall"]["text"], {"found": 5, "of": 7})
        self.assertEqual(s["recall"]["text_all_pairs"], {"found": 5, "of": 8})
        self.assertEqual(s["hit_rate"]["cards"], {"questions_hit": 4, "of": 5})
        self.assertEqual(s["hit_rate"]["text"], {"questions_hit": 3, "of": 5})
        self.assertEqual(s["noise"]["text"], {"mean": 0.0, "of": 5})
        self.assertEqual(s["noise"]["cards"], {"mean": 0.4, "of": 5})  # q5: "filler" is in every card, so two cards are not right

    def test_the_reciprocal_rank_is_the_best_place_of_a_right_book(self):
        place = self.found("q5", "cards")[self.c]
        self.assertIn(place, (1, 2, 3))
        self.assertAlmostEqual(self.summary["mean_reciprocal_rank"]["cards"]["value"], (3 + 1 / place) / 5)
        self.assertAlmostEqual(self.summary["mean_reciprocal_rank"]["text"]["value"], 3 / 5)
        self.assertEqual(self.summary["mean_reciprocal_rank"]["text"]["of"], 5)

    def test_every_search_of_every_query_is_in_the_report_in_order(self):
        record = self.by_id["q2"]["queries"][0]
        self.assertEqual(record["query"], "zebra")
        self.assertEqual(set(record["books"]), {"cards", "summary", "neutral", "text"})
        self.assertEqual(sorted(record["books"]["text"]), sorted([self.a, self.b]))
        self.assertEqual(record["books"]["cards"], [])
        self.assertIs(record["text_limit_reached"], False)

    def test_the_input_manifest_names_the_cards_and_the_indexes(self):
        manifest = self.report["manifest"]
        self.assertEqual(manifest["library_id"], self.store.library_id)
        cards = {c["book_id"]: c for c in manifest["cards"]}
        self.assertEqual(sorted(cards), sorted([self.a, self.b, self.c]))
        for book_id, entry in cards.items():
            version = entry["version_id"]
            payload = self.store.verify_payload(book_id, version, f"derived/card/{entry['generation']}")
            self.assertEqual(entry["sha256"], payload["files"]["card.json"]["sha256"])
        root = self.store.cfg["index_root"]
        with open(catalog.path_of(root), "rb") as f:
            self.assertEqual(manifest["catalog_sha256"], hashlib.sha256(f.read()).hexdigest())
        with open(index.path_of(root), "rb") as f:
            self.assertEqual(manifest["text_index_sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertEqual(manifest["catalog_cards"], 3)

    def test_the_corpus_hash_and_the_date_are_recorded(self):
        with open(os.path.join(self.base, "corpus.json"), "rb") as f:
            self.assertEqual(self.report["corpus_sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertEqual(self.summary["corpus_sha256"], self.report["corpus_sha256"])
        self.assertRegex(self.report["date"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\+00:00$")
        self.assertEqual(self.report["full_text_limit"], 50)


class RulesTest(unittest.TestCase):
    """The pure rules, on lists worked out by hand."""

    def entry(self, **books):
        empty = {name: [] for name in trial.SEARCHES}
        return {"query": "q", "books": {**empty, **books}, "text_limit_reached": False}

    def test_a_book_takes_the_best_place_it_has_in_any_query_and_ties_go_by_book_id(self):
        per_query = [self.entry(cards=["Y", "X", "Z"]), self.entry(cards=["X"]), self.entry(cards=["W", "Z"])]
        result = trial._question_result({"id": "q", "text": "t", "right": ["X", "Z", "N"], "queries": []}, per_query, {"X", "Z"})
        cards = result["searches"]["cards"]
        self.assertEqual(cards["found"], {"X": 1, "Z": 2})  # X: places 2 and 1; Z: places 3 and 2; N is not covered
        self.assertEqual(cards["order"], ["W", "X", "Y", "Z"])  # place 1: W, X and Y (a tie, by id), then Z at place 2
        self.assertEqual(cards["noise"], 2)  # W and Y are not right; N is right and was not found

    def test_the_reciprocal_rank_uses_the_smallest_place_among_the_covered_right_books(self):
        per_query = [self.entry(cards=["A", "B"], text=["B"]), self.entry(cards=["C"], text=["C", "A"])]
        question = {"id": "q", "text": "t", "right": ["B", "C", "U"], "queries": []}
        result = trial._question_result(question, per_query, {"B", "C"})
        summary = trial._summarize([result])
        self.assertEqual(result["searches"]["cards"]["found"], {"B": 2, "C": 1})
        self.assertEqual(summary["mean_reciprocal_rank"]["cards"], {"value": 1.0, "of": 1})
        self.assertEqual(result["searches"]["text"]["found"], {"B": 1, "C": 1, "U": None})  # the text is scored on every right book
        self.assertEqual(summary["recall"]["text"], {"found": 2, "of": 2})
        self.assertEqual(summary["recall"]["text_all_pairs"], {"found": 2, "of": 3})

    def test_the_reciprocal_rank_is_one_over_the_best_place_and_not_over_the_position_in_the_merged_list(self):
        # Y, X and W are at place 1 in some query and Z is at place 2, so Z sits fourth in the merged list but its place is 2
        per_query = [self.entry(cards=["Y", "Z"]), self.entry(cards=["X", "Z"]), self.entry(cards=["W"])]
        result = trial._question_result({"id": "q", "text": "t", "right": ["Z"], "queries": []}, per_query, {"Z"})
        self.assertEqual(result["searches"]["cards"]["order"], ["W", "X", "Y", "Z"])
        self.assertEqual(result["searches"]["cards"]["reciprocal_rank"], 0.5)
        self.assertEqual(trial._summarize([result])["mean_reciprocal_rank"]["cards"], {"value": 0.5, "of": 1})

    def test_a_query_has_its_own_found_and_noise_and_a_question_its_hit_and_rank(self):
        per_query = [self.entry(cards=["A", "B", "N"], text=["N"]), self.entry(cards=["C"], text=["C", "A"])]
        result = trial._question_result({"id": "q", "text": "t", "right": ["B", "C", "U"], "queries": []}, per_query, {"B", "C"})
        first, second = result["queries"]
        self.assertEqual(first["found"]["cards"], {"B": 2, "C": None})
        self.assertEqual(first["noise"]["cards"], 2)  # A and N are not right
        self.assertEqual(second["found"]["cards"], {"B": None, "C": 1})
        self.assertEqual(second["found"]["text"], {"B": None, "C": 1, "U": None})  # the text is scored on every right book
        self.assertEqual((result["searches"]["cards"]["hit"], result["searches"]["cards"]["reciprocal_rank"]), (True, 1.0))
        self.assertEqual((result["searches"]["text"]["hit"], result["searches"]["text"]["reciprocal_rank"]), (True, 1.0))

    def test_a_question_with_nothing_covered_has_no_hit_and_no_rank(self):
        result = trial._question_result({"id": "q", "text": "t", "right": ["U"], "queries": []}, [self.entry(text=["U"])], set())
        self.assertEqual((result["searches"]["cards"]["hit"], result["searches"]["cards"]["reciprocal_rank"]), (None, None))

    def test_a_question_with_no_covered_right_book_is_left_out_of_the_rank_and_the_hit_rate(self):
        per_query = [self.entry(text=["U"])]
        result = trial._question_result({"id": "q", "text": "t", "right": ["U"], "queries": []}, per_query, set())
        summary = trial._summarize([result])
        self.assertEqual(summary["hit_rate"]["cards"], {"questions_hit": 0, "of": 0})
        self.assertEqual(summary["mean_reciprocal_rank"]["cards"], {"value": None, "of": 0})
        self.assertEqual((summary["pairs"], summary["covered_pairs"], summary["uncovered_pairs"]), (1, 0, 1))
        self.assertEqual(summary["recall"]["text_all_pairs"], {"found": 1, "of": 1})


class LimitTest(TrialCase):
    def test_the_full_text_limit_is_reported_when_it_is_reached(self):
        crowded = self.add("Crowded", "x", make_model(summary="crowded"), blocks=[block(f"common word number {i}") for i in range(60)])
        quiet = self.add("Quiet", "quiet uncommon", make_model(summary="quiet"))
        self.build()
        self.run_trial([{"id": "q1", "text": "t", "queries": ["common", "uncommon"], "right": [crowded, quiet]}])
        queries = self.load_report()["questions"][0]["queries"]
        self.assertEqual([q["text_limit_reached"] for q in queries], [True, False])
        self.assertEqual(queries[0]["books"]["text"], [crowded])  # fifty blocks of one book are one book


class FieldWordsTest(TrialCase):
    def leaked(self, field_words, neutral):
        book = self.add("Quiet title", "text", make_model(topics=["sparkle"], neutral_problem=neutral, neutral_approach="plain approach",
                                                         neutral_needs="plain needs", neutral_provides="plain provides",
                                                         neutral_limits="plain limits"))
        self.build()
        self.run_trial([{"id": "q1", "text": "t", "queries": ["text"], "right": [book]}], field_words=field_words)
        return {c["book_id"]: c for c in self.load_report()["cards"]["each"]}[book]["leaked"]

    def test_a_field_word_of_any_length_is_found_in_the_neutral_fields(self):
        self.assertEqual(self.leaked(["llm", "AI"], "an LLM helps the ai team"), ["ai", "llm"])

    def test_a_field_word_that_is_a_common_word_is_found_if_the_owner_listed_it(self):
        self.assertEqual(self.leaked(["with"], "choosing with care"), ["with"])

    def test_a_field_word_that_the_neutral_fields_do_not_hold_is_not_a_leak(self):
        self.assertEqual(self.leaked(["quokka"], "general choosing"), [])

    def test_field_words_match_without_regard_to_case_or_accents_form(self):
        self.assertEqual(self.leaked(["Théorie"], "la théorie des jeux"), ["théorie"])


class CardMeasuresTest(TrialCase):
    def test_word_counts_and_the_words_the_neutral_fields_repeat(self):
        leaky = self.add("Banditry study", "text", make_model(
            summary="one two three", useful_for=["four five", "six"], topics=["bandit problems", "with data"],
            neutral_problem="choosing among bandit arms with care", neutral_limits="fails for the quokka"))
        clean = self.add("Clean title", "text two", make_model(
            summary="alpha beta", topics=["sparkle"], neutral_problem="general choosing", neutral_approach="plain approach",
            neutral_needs="plain needs", neutral_provides="plain provides", neutral_limits="plain limits"))
        bare = self.add("Bare", "text three")
        card.file(self.store, card.make(self.store, bare, self.store.read_book(bare)["current_version"]))
        self.build()
        self.run_trial([{"id": "q1", "text": "t", "queries": ["text"], "right": [leaky]}], field_words=["quokka", "zebra"])
        cards = {c["book_id"]: c for c in self.load_report()["cards"]["each"]}
        self.assertEqual(cards[leaky]["words"]["summary"], 3)
        self.assertEqual(cards[leaky]["words"]["useful_for"], 3)
        self.assertEqual(cards[leaky]["words"]["topics"], 4)
        self.assertEqual(cards[leaky]["words"]["neutral"], 6 + 2 + 2 + 2 + 4)  # the five neutral fields
        self.assertEqual(cards[leaky]["leaked"], ["bandit", "quokka"])  # "with" is not counted; "problems" is not repeated
        self.assertEqual(cards[clean]["leaked"], [])
        self.assertEqual(cards[bare]["words"]["total"], 0)
        self.assertIs(cards[bare]["has_model_part"], False)
        totals = self.load_report()["cards"]
        self.assertEqual(totals["with_model_part"], 2)
        self.assertEqual(totals["leaking"], {"cards": 1, "of": 2})


class RefusalTest(TrialCase):
    def setUp(self):
        super().setUp()
        self.a = self.add("Alpha", "alpha text", make_model(summary="alpha"))
        self.build()
        self.q = [{"id": "q1", "text": "t", "queries": ["alpha"], "right": [self.a]}]

    def refused(self, corpus=None, report=None, **kw):
        with self.assertRaises(KbError) as cm:
            trial.run(self.store, corpus or self.write_corpus(self.q), report or self.report_path(), **kw)
        return str(cm.exception)

    def test_a_corpus_or_report_inside_the_project_is_refused(self):
        inside = os.path.join(models._project_root(), "engine", "tests", "trial-corpus-should-not-exist.json")
        try:
            with open(inside, "w") as f:
                json.dump({"format": 1, "questions": self.q}, f)
            self.assertIn("outside", self.refused(corpus=inside))
        finally:
            os.remove(inside)
        report_inside = os.path.join(models._project_root(), "trial-report-should-not-exist.json")
        self.assertIn("outside", self.refused(report=report_inside))
        self.assertFalse(os.path.exists(report_inside))

    def test_a_path_inside_the_project_through_a_link_is_refused(self):
        link = os.path.join(self.base, "link")
        os.symlink(os.path.join(models._project_root(), "engine"), link)
        self.assertIn("outside", self.refused(report=os.path.join(link, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(models._project_root(), "engine", "report.json")))

    def test_a_corpus_that_is_not_in_the_expected_form(self):
        good = {"id": "q1", "text": "t", "queries": ["alpha"], "right": [self.a]}
        bad_corpora = {
            "not json": "not json", "an array": "[]", "no format": json.dumps({"questions": [good]}),
            "another format": json.dumps({"format": 2, "questions": [good]}), "no questions": json.dumps({"format": 1, "questions": []}),
            "an extra key": json.dumps({"format": 1, "questions": [good], "extra": 1}),
            "a repeated key": '{"format": 1, "format": 1, "questions": []}',
            "a question with an extra key": json.dumps({"format": 1, "questions": [dict(good, extra=1)]}),
            "a missing key": json.dumps({"format": 1, "questions": [{k: v for k, v in good.items() if k != "text"}]}),
            "a bad id": json.dumps({"format": 1, "questions": [dict(good, id="Q 1")]}),
            "a repeated id": json.dumps({"format": 1, "questions": [good, good]}),
            "no queries": json.dumps({"format": 1, "questions": [dict(good, queries=[])]}),
            "a query with no words": json.dumps({"format": 1, "questions": [dict(good, queries=["!!!"])]}),
            "a query that is too long": json.dumps({"format": 1, "questions": [dict(good, queries=["x" * 2001])]}),
            "a query that is not text": json.dumps({"format": 1, "questions": [dict(good, queries=[5])]}),
            "too many queries": json.dumps({"format": 1, "questions": [dict(good, queries=["alpha"] * 11)]}),
            "no right book": json.dumps({"format": 1, "questions": [dict(good, right=[])]}),
            "a bad book id": json.dumps({"format": 1, "questions": [dict(good, right=["../x"])]}),
            "a repeated right book": json.dumps({"format": 1, "questions": [dict(good, right=[self.a, self.a])]}),
            "a text that is not text": json.dumps({"format": 1, "questions": [dict(good, text=5)]}),
            "field words that are not a list": json.dumps({"format": 1, "questions": [good], "field_words": "x"}),
            "a field word with a space": json.dumps({"format": 1, "questions": [good], "field_words": ["two words"]}),
            "too many questions": json.dumps({"format": 1, "questions": [dict(good, id=f"q{i}") for i in range(201)]}),
        }
        for label, text in bad_corpora.items():
            path = os.path.join(self.base, "bad.json")
            with open(path, "w") as f:
                f.write(text)
            with self.subTest(label), self.assertRaises(KbError):
                trial.run(self.store, path, self.report_path())
            self.assertFalse(os.path.exists(self.report_path()), label)

    def test_a_corpus_that_is_missing_or_too_large_or_not_a_file(self):
        with self.assertRaises(KbError):
            trial.run(self.store, os.path.join(self.base, "missing.json"), self.report_path())
        big = os.path.join(self.base, "big.json")
        with open(big, "w") as f:
            f.write(" " * (trial.MAX_CORPUS_BYTES + 1))
        with self.assertRaises(KbError):
            trial.run(self.store, big, self.report_path())
        with self.assertRaises(KbError):
            trial.run(self.store, self.base, self.report_path())

    def test_a_book_that_is_not_in_the_library(self):
        q = [dict(self.q[0], right=["01M6SR01QXBXAZ9V8ZHBWPCDAF"])]
        self.assertIn("q1", self.refused(corpus=self.write_corpus(q)))

    def test_a_card_that_cannot_be_read_makes_its_book_uncovered_and_does_not_block_the_trial(self):
        broken = self.add("Broken", "broken text")
        version = self.store.read_book(broken)["current_version"]
        self.store.file_payload(broken, version, "derived/card/1", {"card.json": b"not json"}, tool="kb-card 1", untrusted=True)
        catalog.rebuild(self.store)  # leaves the broken card out and counts it
        q = [dict(self.q[0], right=[self.a, broken], queries=["alpha", "broken"])]
        trial.run(self.store, self.write_corpus(q), self.report_path())
        report = self.load_report()
        self.assertEqual(report["uncovered"], [{"book_id": broken, "reason": "card cannot be read", "questions": ["q1"]}])

    def test_the_reason_a_book_is_uncovered_is_told_apart(self):
        inactive = self.add("Gone", "gone text", make_model(summary="gone"))
        self.store.set_state(inactive, "weeded")
        nocard = self.add("Cardless", "cardless text")
        self.build()
        q = [dict(self.q[0], right=[self.a, inactive, nocard], queries=["alpha"])]
        trial.run(self.store, self.write_corpus(q), self.report_path())
        reasons = {u["book_id"]: u["reason"] for u in self.load_report()["uncovered"]}
        self.assertEqual(reasons, {inactive: "book is not active", nocard: "no card"})

    def test_a_right_book_that_is_not_in_the_text_index_is_listed(self):
        late = self.add("Late", "late text", make_model(summary="late"))  # converted and carded after the text index was built
        catalog.rebuild(self.store)
        q = [dict(self.q[0], right=[self.a, late], queries=["alpha", "late"])]
        trial.run(self.store, self.write_corpus(q), self.report_path())
        self.assertEqual(self.load_report()["text_uncovered"], [{"book_id": late, "questions": ["q1"]}])

    def test_a_report_path_that_is_a_link_is_written_where_it_is_named_and_not_through_the_link(self):
        elsewhere = os.path.join(self.base, "elsewhere")
        os.mkdir(elsewhere)
        target = os.path.join(elsewhere, "target.json")
        with open(target, "w") as f:
            f.write("keep me")
        link = self.report_path("link.json")
        os.symlink(target, link)
        self.refused(report=link)  # a name that exists, even as a link, is not overwritten
        trial.run(self.store, self.write_corpus(self.q), link, replace=True)
        with open(target) as f:
            self.assertEqual(f.read(), "keep me")
        self.assertFalse(os.path.islink(link))
        self.assertEqual(self.load_report_at(link)["format"], 1)

    def test_a_report_that_appears_between_the_check_and_the_write_is_not_overwritten(self):
        out = self.report_path("race.json")
        with open(out, "w") as f:
            f.write("someone else's file")
        with self.assertRaises(KbError):
            trial._write_report(out, {"format": 1}, replace=False)
        with open(out) as f:
            self.assertEqual(f.read(), "someone else's file")
        self.assertEqual(sorted(n for n in os.listdir(self.base) if ".tmp." in n), [])
        trial._write_report(out, {"format": 1}, replace=True)
        self.assertEqual(self.load_report_at(out), {"format": 1})

    def test_a_failed_write_leaves_no_report_behind(self):
        out = self.report_path("failed.json")
        with mock.patch.object(trial.config, "write_json_atomic", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                trial._write_report(out, {"format": 1}, replace=False)
        self.assertFalse(os.path.exists(out))

    def test_a_catalog_that_changes_during_the_run_is_refused(self):
        calls = []
        real = trial._sha256

        def sha(path):
            calls.append(path)
            return real(path) if len(calls) <= 2 else "changed"

        with mock.patch.object(trial, "_sha256", side_effect=sha):
            self.assertIn("changed during the run", self.refused())
        self.assertFalse(os.path.exists(self.report_path()))

    def test_a_catalog_row_that_is_not_the_card_in_the_book_folder_is_refused(self):
        import sqlite3
        other = self.add("Other", "other text", make_model(summary="other"))
        catalog.rebuild(self.store)
        root = self.store.cfg["index_root"]
        with closing(sqlite3.connect(catalog.path_of(root))) as conn, conn:  # closed, and committed on leaving
            stolen = conn.execute("SELECT card FROM cards WHERE book_id = ?", (other,)).fetchone()[0]
            conn.execute("UPDATE cards SET card = ? WHERE book_id = ?", (stolen, self.a))  # right keys, another book's card
        self.assertIn("card-index", self.refused())

    def test_a_report_in_a_folder_that_is_not_there(self):
        self.refused(report=os.path.join(self.base, "nowhere", "report.json"))

    def test_a_report_that_exists_is_not_overwritten_unless_asked(self):
        trial.run(self.store, self.write_corpus(self.q), self.report_path())
        with open(self.report_path()) as f:
            before = f.read()
        self.refused()
        with open(self.report_path()) as f:
            self.assertEqual(f.read(), before)
        trial.run(self.store, self.write_corpus(self.q), self.report_path(), replace=True)

    def test_the_report_is_private_and_no_temporary_file_is_left(self):
        trial.run(self.store, self.write_corpus(self.q), self.report_path())
        self.assertEqual(stat.S_IMODE(os.stat(self.report_path()).st_mode), 0o600)
        self.assertEqual(sorted(n for n in os.listdir(self.base) if ".tmp." in n), [])

    def test_a_catalog_that_is_not_the_one_the_cards_make_is_refused(self):
        b = self.add("Beta", "beta text", make_model(summary="beta"))  # a card made after the last card-index
        self.assertIn("card-index", self.refused())
        catalog.rebuild(self.store)
        trial.run(self.store, self.write_corpus(self.q), self.report_path())
        newer = card.make(self.store, b, self.store.read_book(b)["current_version"], model=make_model(summary="newer"), records=[])
        card.file(self.store, newer)  # a second generation, not yet in the catalog
        self.refused(replace=True)

    def test_a_missing_catalog_or_text_index_is_refused_with_the_command(self):
        os.remove(catalog.path_of(self.store.cfg["index_root"]))
        self.assertIn("card-index", self.refused())
        catalog.rebuild(self.store)
        os.remove(index.path_of(self.store.cfg["index_root"]))
        self.assertIn("index", self.refused())


class NothingChangesTest(TrialCase):
    def test_it_changes_nothing_and_calls_no_model(self):
        a = self.add("Alpha", "alpha text", make_model(summary="alpha"))
        self.build()
        root = self.store.cfg["index_root"]

        def snapshot():
            out = {}
            for base in (self.bulk, root):
                for dirpath, _, names in os.walk(base):
                    for name in names:
                        path = os.path.join(dirpath, name)
                        with open(path, "rb") as f:
                            out[path] = hashlib.sha256(f.read()).hexdigest()
            return out

        before = snapshot()
        with mock.patch.object(models, "call", side_effect=AssertionError("a model was called")), \
                mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")):
            trial.run(self.store, self.write_corpus([{"id": "q1", "text": "t", "queries": ["alpha"], "right": [a]}]), self.report_path())
        self.assertEqual(snapshot(), before)


class CommandTest(TrialCase):
    def kb(self, *args):
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg)
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)

    def test_trial_runs_through_the_command_line_and_prints_a_summary(self):
        a = self.add("Alpha", "alpha text", make_model(summary="alpha"))
        self.build()
        corpus = self.write_corpus([{"id": "q1", "text": "a private question", "queries": ["alpha"], "right": [a]}])
        r = self.kb("trial", corpus, self.report_path())
        self.assertEqual(r.returncode, 0, r.stderr)
        summary = json.loads(r.stdout)
        self.assertEqual(summary["recall"]["cards"], {"found": 1, "of": 1})
        self.assertNotIn("a private question", r.stdout)  # the questions are not printed, only the numbers
        self.assertTrue(os.path.isfile(self.report_path()))
        again = self.kb("trial", corpus, self.report_path())
        self.assertEqual(again.returncode, 2)
        self.assertIn("refused:", again.stderr)
        self.assertEqual(self.kb("trial", corpus, self.report_path(), "--replace").returncode, 0)

    def test_trial_refuses_a_path_inside_the_project(self):
        inside = os.path.join(models._project_root(), "report-should-not-exist.json")
        r = self.kb("trial", self.write_corpus([{"id": "q1", "text": "t", "queries": ["alpha"], "right": ["01M6SR01QXBXAZ9V8ZHBWPCDAF"]}]), inside)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(inside))


if __name__ == "__main__":
    unittest.main()
