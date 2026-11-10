import hashlib
import json
import os
import stat
import subprocess
import sys
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_cardmake import LibraryCase, block
from engine.tests.test_models import FAKE_EMBED
from engine.tests.test_trial import make_model
from engine.tests.test_vectors import with_embedding

from kb import KbError, card, catalog, index, models, problem, problemtrial, search, vectors

# six books with chosen vectors in four dimensions (every neutral field of a book has the same vector)
BOOKS = {
    "ann": ("Annealing", "annealing cooling schedule", [1, 0, 0, 0]),
    "gen": ("Genetic", "genetic crossover mutation", [0.8, 0.6, 0, 0]),
    "gco": ("Gcode", "gcode toolpath nozzle travel", [0.6, 0.8, 0, 0]),
    "blo": ("Bloom", "bloom filter hashing membership", [0, 0, 1, 0]),
    "cra": ("Crawl", "crawler visited addresses", [0, 0, 0.8, 0.6]),
    "oth": ("Other", "unrelated pottery", [0, 0, 0, 1]),
}
SEARCHES = ("T", "K", "M", "P")


def problem_of(pid, text, expected=(), home=(), keywords=("x",), subs=("S",), control=False):
    return {"id": pid, "control": control, "text": text, "expected": list(expected), "home": list(home),
            "keyword_queries": list(keywords), "sub_problems": list(subs)}


# the four problems of the hand-worked case; the vectors of the texts below are in the table of the fake bridge
P1 = problem_of("p1", "Q1 text", ["Annealing", "Genetic"], ["Gcode"], ["annealing", "genetic"], ["S1a", "S1b"])
P2 = problem_of("p2", "Q2 text", ["Bloom"], ["Crawl"], ["bloom"], ["S2"])
P3 = problem_of("p3", "Q3 text", [], [], ["pottery"], ["S3"], control=True)
P4 = problem_of("p4", "Q4 text", ["Genetic"], [], ["bakery"], ["S4"])
TABLE = {"Q1 text": [0.6, 0.8, 0, 0], "S1a": [1, 0, 0, 0], "S1b": [0.28, 0.96, 0, 0], "Q2 text": [0, 0, 0.6, 0.8], "S2": [0, 0, 0.6, 0.8],
         "Q3 text": [0, 0, 0, 1], "S3": [0, 0, 0, 1], "Q4 text": [-0.8, -0.6, 0, 0], "S4": [-0.8, -0.6, 0, 0]}  # Genetic last (-1.0), Gcode fifth, Annealing fourth


class RulesTest(unittest.TestCase):
    def test_hit_at_five_and_after_setting_aside_and_the_reciprocal_rank(self):
        order = ["h1", "x", "y", "z", "w", "e1"]
        got = problemtrial._measures([order], ["e1"], ["h1"])
        self.assertEqual(got["places"], {"e1": 6})
        self.assertEqual(got["places_after_set_aside"], {"e1": 5})  # the home book is removed and the others move up
        self.assertIs(got["hit5"], False)
        self.assertIs(got["hit5_after_set_aside"], True)
        self.assertEqual(got["reciprocal_rank"], 1 / 6)
        self.assertEqual(got["home_in_first_five"], 1)

    def test_the_fifth_place_counts_and_the_sixth_does_not(self):
        self.assertIs(problemtrial._measures([["a", "b", "c", "d", "e"]], ["e"], [])["hit5"], True)
        self.assertIs(problemtrial._measures([["a", "b", "c", "d", "x", "e"]], ["e"], [])["hit5"], False)

    def test_a_book_that_is_not_in_the_list_has_no_place_and_adds_nothing(self):
        got = problemtrial._measures([["a", "b"]], ["e1", "b"], ["a"])
        self.assertEqual(got["places"], {"e1": None, "b": 2})
        self.assertEqual(got["places_after_set_aside"], {"e1": None, "b": 1})
        self.assertEqual(got["reciprocal_rank"], 1 / 2)
        none = problemtrial._measures([["a", "b"]], ["e1"], [])
        self.assertEqual((none["hit5"], none["hit5_after_set_aside"], none["reciprocal_rank"]), (False, False, 0.0))

    def test_the_best_placed_expected_book_gives_the_reciprocal_rank(self):
        self.assertEqual(problemtrial._measures([["a", "e2", "e1"]], ["e1", "e2"], [])["reciprocal_rank"], 1 / 2)

    def test_home_books_among_the_first_five_are_counted_before_they_are_removed(self):
        got = problemtrial._measures([["h1", "a", "h2", "b", "c", "h3"]], ["b"], ["h1", "h2", "h3"])
        self.assertEqual(got["home_in_first_five"], 2)
        self.assertEqual(got["places_after_set_aside"], {"b": 2})

    def test_over_several_queries_a_book_has_its_smallest_place_and_two_books_can_share_a_place(self):
        got = problemtrial._measures([["a", "e1"], ["e1", "c"]], ["e1", "c"], [])
        self.assertEqual(got["places"], {"e1": 1, "c": 2})  # e1 is second in the first query and first in the second
        home = problemtrial._measures([["h", "a", "e1"], ["x", "e1"]], ["e1"], ["h"])
        self.assertEqual((home["places"], home["places_after_set_aside"]), ({"e1": 2}, {"e1": 2}))  # the second query keeps it at 2
        self.assertEqual(problemtrial._measures([["h", "a", "e1"]], ["e1"], ["h"])["places_after_set_aside"], {"e1": 2})

    def test_the_place_over_several_queries_is_the_smallest_and_ties_are_ordered_by_book_id(self):
        order = problemtrial._order_over_queries([["b", "a"], ["a", "c"]])
        self.assertEqual(order, ["a", "b", "c"])  # a: places 2 and 1 -> 1; b: 1; c: 2; a and b tie at 1 and a comes first by id


class SummaryRulesTest(unittest.TestCase):
    def test_the_counts_use_the_positive_problems_only_and_keep_hit_and_hit_after_setting_aside_apart(self):
        none = {"places": None, "hit5": None, "hit5_after_set_aside": None, "reciprocal_rank": None}
        positive = {"places": {"a": 6, "b": None}, "hit5": False, "hit5_after_set_aside": True, "reciprocal_rank": 1 / 6}
        problems = [{"control": False, "expected": ["a", "b"], "searches": {n: dict(positive) for n in SEARCHES}},
                    {"control": True, "expected": [], "searches": {n: dict(none) for n in SEARCHES}}]
        got = problemtrial._summarize(problems)
        self.assertEqual((got["problems"], got["positive"], got["controls"]), (2, 1, 1))
        t = got["by_search"]["T"]
        self.assertEqual((t["hit5"], t["hit5_after_set_aside"], t["of"], t["pairs"], t["pairs_in_first_10"]), (0, 1, 1, 2, 1))
        self.assertEqual(t["mean_reciprocal_rank"], round(1 / 6, 4))

    def test_a_pair_at_the_tenth_place_is_within_the_first_ten_and_one_at_the_eleventh_is_not(self):
        def problem_at(place):
            s = {"places": {"a": place}, "hit5": False, "hit5_after_set_aside": False, "reciprocal_rank": 1 / place}
            return {"control": False, "expected": ["a"], "searches": {n: dict(s) for n in SEARCHES}}
        got = problemtrial._summarize([problem_at(10), problem_at(11)])["by_search"]["T"]
        self.assertEqual((got["pairs"], got["pairs_in_first_10"]), (2, 1))


class FixtureCase(LibraryCase):
    """Six books with text, cards and vectors, and a fake `embed` bridge that answers from a table."""

    def setUp(self):
        super().setUp()
        self.efolder = os.path.join(self.base, "embin")
        os.mkdir(self.efolder)
        self.elauncher = os.path.join(self.efolder, "wb")
        with open(self.elauncher, "w") as f:
            f.write(FAKE_EMBED.format(python=sys.executable))
        os.chmod(self.elauncher, 0o700)
        self.mcfg = with_embedding()
        self.ids = {}
        table = dict(TABLE)
        for key, (title, text, vector) in BOOKS.items():
            fields = {f"neutral_{n}": f"{key} {n}" for n in ("problem", "approach", "provides")}
            for value in fields.values():
                table[value] = vector
            book, version = self.converted_book(blocks=[block(text)], title=title)
            card.file(self.store, card.make(self.store, book, version, model=make_model(summary=text, **fields), records=[]))
            self.ids[key] = book
        self.plan(table=table)
        self.table = table
        index.rebuild(self.store)
        catalog.rebuild(self.store)
        vectors.build(self.store, self.mcfg, launcher=self.elauncher)
        self.root = self.store.cfg["index_root"]

    def plan(self, **p):
        with open(os.path.join(self.efolder, "plan.json"), "w") as f:
            json.dump(p, f)

    def sent(self):
        path = os.path.join(self.efolder, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [t for line in f for t in json.loads(json.loads(line)["stdin"])["texts"]]

    def write_corpus(self, problems, name="corpus.json", **extra):
        path = os.path.join(self.base, name)
        with open(path, "w") as f:
            json.dump({"format": 1, "problems": problems, **extra}, f)
        return path

    def report_path(self, name="report.json"):
        return os.path.join(self.base, name)

    def run_trial(self, problems=None, cfg=None, **kw):
        return problemtrial.run(self.store, cfg or self.mcfg, self.write_corpus(problems or [P1, P2, P3, P4]), self.report_path(),
                                launcher=self.elauncher, **kw)

    def report(self):
        with open(self.report_path()) as f:
            return json.load(f)

    def titles(self, *keys):
        return [self.ids[k] for k in keys]


class HandWorkedTest(FixtureCase):
    def setUp(self):
        super().setUp()
        self.before = len(self.sent())
        self.summary = self.run_trial()
        self.rep = self.report()
        self.by = {p["id"]: p for p in self.rep["problems"]}

    def order(self, pid, name):
        return self.by[pid]["searches"][name]["order"]

    def test_the_search_by_meaning_orders_the_books_by_closeness_and_places_the_expected_ones(self):
        ann, gen, gco = self.ids["ann"], self.ids["gen"], self.ids["gco"]
        self.assertEqual(self.order("p1", "M")[:3], [gco, gen, ann])  # 1.0, 0.96, 0.6
        m = self.by["p1"]["searches"]["M"]
        self.assertEqual(m["places"], {ann: 3, gen: 2})
        self.assertEqual(m["places_after_set_aside"], {ann: 2, gen: 1})  # the home book Gcode comes out and the others move up
        self.assertEqual((m["hit5"], m["hit5_after_set_aside"], m["home_in_first_five"]), (True, True, 1))
        self.assertEqual(m["reciprocal_rank"], 1 / 2)
        self.assertEqual([round(s, 3) for s in m["scores"][:3]], [1.0, 0.96, 0.6])

    def test_the_problem_search_places_a_book_by_its_position_in_the_merged_list(self):
        ann, gen, gco = self.ids["ann"], self.ids["gen"], self.ids["gco"]
        # merged by best score: Annealing 1.0 (sub-problem 1), Gcode 0.936 (2), Genetic 0.8 (1 and 2); Genetic is second in each sub-problem
        # and third in the merged list, which is the place that counts
        self.assertEqual(self.order("p1", "P")[:3], [ann, gco, gen])
        p = self.by["p1"]["searches"]["P"]
        self.assertEqual(p["places"], {ann: 1, gen: 3})
        self.assertEqual(p["places_after_set_aside"], {ann: 1, gen: 2})
        self.assertEqual(p["reciprocal_rank"], 1.0)
        self.assertEqual([round(s, 3) for s in p["scores"][:3]], [1.0, 0.936, 0.8])

    def test_the_keyword_searches_place_a_book_by_its_smallest_place_over_the_queries(self):
        for name in ("T", "K"):
            s = self.by["p1"]["searches"][name]
            self.assertEqual(s["places"], {self.ids["ann"]: 1, self.ids["gen"]: 1}, name)
            self.assertEqual(s["order"][:2], sorted([self.ids["ann"], self.ids["gen"]]), name)
            self.assertEqual((s["hit5"], s["home_in_first_five"]), (True, 0), name)

    def test_a_keyword_that_matches_nothing_gives_an_empty_list_and_no_place(self):
        for name in ("T", "K"):
            s = self.by["p4"]["searches"][name]
            self.assertEqual((s["order"], s["places"], s["hit5"], s["reciprocal_rank"]), ([], {self.ids["gen"]: None}, False, 0.0))

    def test_a_control_lists_its_books_and_has_no_measures(self):
        for name in SEARCHES:
            s = self.by["p3"]["searches"][name]
            self.assertTrue(self.by["p3"]["control"])
            for key in ("places", "places_after_set_aside", "hit5", "hit5_after_set_aside", "reciprocal_rank", "home_in_first_five"):
                self.assertIsNone(s[key], (name, key))
        self.assertEqual(self.order("p3", "M")[0], self.ids["oth"])
        self.assertEqual(self.by["p3"]["searches"]["T"]["first_five"][0], {"book_id": self.ids["oth"], "title": "Other"})

    def test_the_first_five_books_carry_their_titles(self):
        first = self.by["p2"]["searches"]["M"]["first_five"]
        self.assertEqual(first[0], {"book_id": self.ids["cra"], "title": "Crawl"})  # 0.96, the home book
        self.assertEqual(len(first), 5)

    def test_the_summary_counts_the_positive_problems_for_each_search(self):
        s = self.rep["summary"]
        self.assertEqual((s["problems"], s["positive"], s["controls"]), (4, 3, 1))
        by = s["by_search"]
        # p1 and p2 have an expected book in the first five of every search; p4 (Genetic) is sixth in M and P and not found by T and K
        self.assertEqual({n: by[n]["hit5"] for n in SEARCHES}, {"T": 2, "K": 2, "M": 2, "P": 2})
        self.assertEqual({n: by[n]["hit5_after_set_aside"] for n in SEARCHES}, {"T": 2, "K": 2, "M": 2, "P": 2})
        self.assertEqual(self.by["p4"]["searches"]["M"]["places"], {self.ids["gen"]: 6})
        self.assertEqual(self.by["p4"]["searches"]["P"]["places"], {self.ids["gen"]: 6})
        self.assertEqual({n: by[n]["of"] for n in SEARCHES}, {"T": 3, "K": 3, "M": 3, "P": 3})
        self.assertEqual(by["T"]["pairs"], 4)  # the expected books of the three positive problems: 2 + 1 + 1
        self.assertEqual(by["T"]["pairs_in_first_10"], 3)
        self.assertEqual(by["M"]["pairs_in_first_10"], 4)  # Genetic is sixth for p4

    def test_the_summary_gives_the_mean_reciprocal_rank_of_the_positive_problems(self):
        by = self.rep["summary"]["by_search"]
        self.assertEqual(by["T"]["mean_reciprocal_rank"], round(2 / 3, 4))  # p1 1.0, p2 1.0, p4 0.0
        self.assertEqual(by["M"]["mean_reciprocal_rank"], round((1 / 2 + 1 / 3 + 1 / 6) / 3, 4))  # p1 Genetic 2nd, p2 Bloom 3rd, p4 6th

    def test_the_command_sent_each_problem_and_then_its_sub_problems_once_and_nothing_else(self):
        self.assertEqual(self.sent()[self.before:], ["Q1 text", "S1a", "S1b", "Q2 text", "S2", "Q3 text", "S3", "Q4 text", "S4"])
        self.assertEqual(self.summary["sentences_sent"], 9)

    def test_the_report_holds_the_hashes_the_model_and_no_prefix_and_no_path(self):
        m = self.rep["manifest"]
        self.assertEqual(m["model"], "bge-m3:latest")
        self.assertIs(m["query_prefix"], False)
        for key in ("catalog_sha256", "text_index_sha256", "vectors_sha256", "library_id"):
            self.assertTrue(m[key], key)
        self.assertEqual((m["cards_searched"], m["stale"], m["without_vector"]), (6, 0, 0))
        self.assertEqual(self.rep["corpus_sha256"], self.summary["corpus_sha256"])
        text = json.dumps(self.rep)
        for secret in (self.base, os.path.expanduser("~")):
            self.assertNotIn(secret, text)

    def test_the_summary_returned_holds_the_report_hash_and_never_the_problems(self):
        with open(self.report_path(), "rb") as f:
            self.assertEqual(self.summary["report_sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertNotIn("Q1 text", json.dumps(self.summary))

    def test_with_a_query_prefix_the_queries_carry_it_and_the_report_says_so_without_showing_it(self):
        cfg = with_embedding(query_prefix="ZQ: ")  # a query prefix alone needs no new vectors
        sent = len(self.sent())
        out = self.run_trial(cfg=cfg, replace=True)
        self.assertIs(out["query_prefix"], True)
        self.assertIs(self.report()["manifest"]["query_prefix"], True)
        self.assertNotIn("ZQ", json.dumps(self.report()))
        self.assertTrue(all(t.startswith("ZQ: ") for t in self.sent()[sent:]))
        self.assertEqual(len(self.sent()) - sent, 9)

    def test_the_report_is_private_to_the_owner(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.report_path()).st_mode), 0o600)


class CheckTest(FixtureCase):
    def test_check_resolves_the_titles_prints_the_plan_and_sends_nothing_and_writes_no_report(self):
        before = len(self.sent())
        out = self.run_trial(check=True)
        self.assertEqual(len(self.sent()), before)
        self.assertFalse(os.path.exists(self.report_path()))
        self.assertEqual((out["problems"], out["positive"], out["controls"], out["sentences_to_send"]), (4, 3, 1, 9))
        self.assertIs(out["check"], True)
        self.assertEqual(out["resolved"]["p1"]["expected"], {"Annealing": self.ids["ann"], "Genetic": self.ids["gen"]})
        self.assertEqual(out["resolved"]["p1"]["home"], {"Gcode": self.ids["gco"]})

    def test_check_still_refuses_what_a_run_would_refuse(self):
        bad = problem_of("b", "text", ["No such title"])
        with self.assertRaises(KbError):
            self.run_trial([bad], check=True)
        os.remove(vectors.path_of(self.root))
        with self.assertRaises(KbError) as cm:
            self.run_trial(check=True)
        self.assertIn("card-vectors", str(cm.exception))

    def test_check_refuses_vectors_that_are_stale_and_says_how_many_cards_it_would_search(self):
        out = self.run_trial(check=True)
        self.assertEqual((out["cards_searched"], out["stale"], out["without_vector"]), (6, 0, 0))
        book = self.ids["ann"]
        version = self.store.read_book(book)["current_version"]
        card.file(self.store, card.make(self.store, book, version, model=make_model(neutral_problem="a changed problem"), records=[]))
        catalog.rebuild(self.store)
        before = len(self.sent())
        with self.assertRaises(KbError) as cm:
            self.run_trial(check=True)
        self.assertIn("card-vectors", str(cm.exception))
        self.assertEqual(len(self.sent()), before)

    def test_check_refuses_a_report_that_exists_so_the_owner_finds_out_early(self):
        with open(self.report_path(), "w") as f:
            f.write("{}")
        with self.assertRaises(KbError):
            self.run_trial(check=True)


class RefusalTest(FixtureCase):
    def refused(self, problems=None, message=None, **kw):
        calls = len(self.sent())
        with self.assertRaises(KbError) as cm:
            self.run_trial(problems, **kw)
        self.assertEqual(len(self.sent()), calls, "something was sent before the refusal")
        self.assertFalse(os.path.exists(self.report_path()))
        if message:
            self.assertIn(message, str(cm.exception))
        return str(cm.exception)

    def test_a_title_that_is_not_in_the_catalog_is_refused_and_nothing_is_sent(self):
        self.refused([problem_of("a", "text", ["No such title"])], "No such title")
        self.refused([problem_of("a", "text", ["Annealing"], ["Missing home"])], "Missing home")

    def test_a_title_that_matches_two_books_is_refused(self):
        book, version = self.converted_book(blocks=[block("again")], title="Annealing")
        card.file(self.store, card.make(self.store, book, version, model=make_model(), records=[]))
        catalog.rebuild(self.store)
        self.refused([P1], "Annealing")

    def test_the_corpus_and_the_report_must_be_outside_the_project(self):
        inside = os.path.join(models._project_root(), "engine", "tests", "problem-corpus-should-not-exist.json")
        try:
            with open(inside, "w") as f:
                json.dump({"format": 1, "problems": [P1]}, f)
            with self.assertRaises(KbError) as cm:
                problemtrial.run(self.store, self.mcfg, inside, self.report_path(), launcher=self.elauncher)
            self.assertIn("outside", str(cm.exception))
        finally:
            os.remove(inside)
        report_inside = os.path.join(models._project_root(), "problem-report-should-not-exist.json")
        with self.assertRaises(KbError) as cm:
            problemtrial.run(self.store, self.mcfg, self.write_corpus([P1]), report_inside, launcher=self.elauncher)
        self.assertIn("outside", str(cm.exception))
        self.assertFalse(os.path.exists(report_inside))

    def test_a_report_that_exists_is_refused_unless_replace_is_given(self):
        self.run_trial()
        sent = len(self.sent())
        with self.assertRaises(KbError) as cm:
            self.run_trial()
        self.assertIn("exists", str(cm.exception))
        self.assertEqual(len(self.sent()), sent)
        again = self.run_trial(replace=True)
        self.assertEqual(again["positive"], 3)

    def test_a_missing_catalog_text_index_or_vectors_is_refused(self):
        for path, word in ((catalog.path_of(self.root), "card-index"), (index.path_of(self.root), "index"), (vectors.path_of(self.root), "card-vectors")):
            os.rename(path, path + ".moved")
            try:
                self.refused(message=word)
            finally:
                os.rename(path + ".moved", path)

    def test_a_catalog_that_is_not_the_one_the_cards_make_is_refused(self):
        book, version = self.converted_book(blocks=[block("late")], title="Late")
        card.file(self.store, card.make(self.store, book, version, model=make_model(), records=[]))
        self.refused(message="card-index")

    def test_vectors_made_by_another_model_or_stale_are_refused_before_anything_is_sent(self):
        other = with_embedding(model="other:latest")
        self.refused(cfg=other)

    def stale_vectors(self):
        """The newest card of Annealing says something else in one neutral field, so one vector no longer matches its text."""
        book = self.ids["ann"]
        version = self.store.read_book(book)["current_version"]
        card.file(self.store, card.make(self.store, book, version, model=make_model(summary="annealing cooling schedule",
                                                                                      neutral_problem="a changed problem",
                                                                                      neutral_approach="ann approach",
                                                                                      neutral_provides="ann provides"), records=[]))
        catalog.rebuild(self.store)

    def test_vectors_that_no_longer_match_their_cards_are_refused_before_anything_is_sent(self):
        self.stale_vectors()
        message = self.refused(message="card-vectors")
        self.assertIn("1 stale", message)

    def test_a_card_that_has_no_vector_is_refused_before_anything_is_sent(self):
        book, version = self.converted_book(blocks=[block("late text")], title="Late")
        card.file(self.store, card.make(self.store, book, version, model=make_model(), records=[]))
        catalog.rebuild(self.store)
        message = self.refused(message="card-vectors")
        self.assertIn("1 without a vector", message)

    def test_one_failing_call_fails_the_whole_command_and_writes_no_report(self):
        base = len(self.sent())
        self.plan(table=self.table, bad_call=self.calls() + 3, bad_mode="short")
        with self.assertRaises(KbError):
            self.run_trial()
        self.assertFalse(os.path.exists(self.report_path()))
        self.assertEqual(len(self.sent()) - base, 3)  # it stopped at the third call and sent no more

    def calls(self):
        path = os.path.join(self.efolder, "calls.jsonl")
        with open(path) as f:
            return len(f.readlines())

    def test_a_library_that_changes_during_the_run_is_refused_and_no_report_is_written(self):
        real = problemtrial._file_hashes
        seen = []

        def changing(root):
            seen.append(1)
            got = real(root)
            return got if len(seen) == 1 else tuple("0" * 64 for _ in got)

        with mock.patch.object(problemtrial, "_file_hashes", side_effect=changing):
            with self.assertRaises(KbError) as cm:
                self.run_trial()
        self.assertIn("changed", str(cm.exception))
        self.assertFalse(os.path.exists(self.report_path()))


class CorpusTest(FixtureCase):
    def refused(self, doc=None, raw=None, message=None):
        path = os.path.join(self.base, "c.json")
        with open(path, "w") as f:
            f.write(raw if raw is not None else json.dumps(doc))
        with self.assertRaises(KbError) as cm:
            problemtrial.load_corpus(path)
        if message:
            self.assertIn(message, str(cm.exception))

    def doc(self, *problems, **extra):
        return {"format": 1, "problems": list(problems), **extra}

    def test_a_good_corpus_loads_and_has_a_hash(self):
        path = self.write_corpus([P1, P3])
        corpus, digest = problemtrial.load_corpus(path)
        with open(path, "rb") as f:
            self.assertEqual(digest, hashlib.sha256(f.read()).hexdigest())
        self.assertEqual([p["id"] for p in corpus["problems"]], ["p1", "p3"])

    def test_the_form_of_the_corpus(self):
        good = problem_of("a", "text", ["T"])
        cases = {
            "not json": dict(raw="not json"), "an array": dict(raw="[]"), "another format": dict(doc={"format": 2, "problems": [good]}),
            "no format": dict(doc={"problems": [good]}), "an extra key": dict(doc=self.doc(good, extra=1)),
            "a repeated key": dict(raw='{"format": 1, "format": 1, "problems": []}'), "no problems": dict(doc=self.doc()),
            "too many problems": dict(doc=self.doc(*[problem_of(f"p{n}", "t", ["T"]) for n in range(51)])),
            "a problem with an extra key": dict(doc=self.doc(dict(good, extra=1))),
            "a missing key": dict(doc=self.doc({k: v for k, v in good.items() if k != "text"})),
            "a bad id": dict(doc=self.doc(dict(good, id="A B"))), "a repeated id": dict(doc=self.doc(good, good)),
            "control not a boolean": dict(doc=self.doc(dict(good, control="no"))),
            "a control with an expected book": dict(doc=self.doc(dict(good, control=True))),
            "a problem with no expected book": dict(doc=self.doc(dict(good, expected=[]))),
            "too many expected books": dict(doc=self.doc(dict(good, expected=[f"T{n}" for n in range(21)]))),
            "a title twice": dict(doc=self.doc(dict(good, expected=["T", "T"]))),
            "a title that is not text": dict(doc=self.doc(dict(good, expected=[5]))),
            "a book both expected and home": dict(doc=self.doc(dict(good, home=["T"]))),
            "no text": dict(doc=self.doc(dict(good, text=""))), "a blank text": dict(doc=self.doc(dict(good, text="   "))),
            "a text that is too long": dict(doc=self.doc(dict(good, text="x" * 1001))),
            "a text that is not text": dict(doc=self.doc(dict(good, text=5))),
            "a text that cannot be sent": dict(doc=self.doc(dict(good, text="bad \ud800"))),
            "no keyword queries": dict(doc=self.doc(dict(good, keyword_queries=[]))),
            "four keyword queries": dict(doc=self.doc(dict(good, keyword_queries=["a", "b", "c", "d"]))),
            "a keyword query with no words": dict(doc=self.doc(dict(good, keyword_queries=["!!!"]))),
            "no sub-problems": dict(doc=self.doc(dict(good, sub_problems=[]))),
            "six sub-problems": dict(doc=self.doc(dict(good, sub_problems=["x"] * 6))),
            "a blank sub-problem": dict(doc=self.doc(dict(good, sub_problems=[" "]))),
            "a sub-problem that is too long": dict(doc=self.doc(dict(good, sub_problems=["x" * 1001]))),
            "a sub-problem that cannot be sent": dict(doc=self.doc(dict(good, sub_problems=["bad \udcff"]))),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.refused(**kw)

    def test_a_thousand_characters_are_allowed_and_five_sub_problems_and_three_queries(self):
        ok = problem_of("a", "x" * 1000, ["T"], keywords=["a", "b", "c"], subs=["y" * 1000] + ["z"] * 4)
        corpus, _ = problemtrial.load_corpus(self.write_corpus([ok]))
        self.assertEqual(len(corpus["problems"][0]["sub_problems"]), 5)

    def test_a_corpus_that_is_too_large_is_refused(self):
        with mock.patch.object(problemtrial, "MAX_CORPUS_BYTES", 50):
            with self.assertRaises(KbError):
                problemtrial.load_corpus(self.write_corpus([P1]))


class NothingChangesTest(FixtureCase):
    def test_a_run_changes_nothing_in_the_library_or_the_indexes(self):
        def state():
            out = {}
            for folder in (self.store.cfg["bulk_root"], self.root):
                for base, _, files in os.walk(folder):
                    for name in files:
                        path = os.path.join(base, name)
                        with open(path, "rb") as f:
                            out[path] = hashlib.sha256(f.read()).hexdigest()
            return out
        before = state()
        self.run_trial()
        after = state()
        after.pop(self.report_path(), None)
        self.assertEqual(after, before)


class CommandTest(FixtureCase):
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
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg, PATH=self.efolder + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, "-m", "kb", "trial-problems", *args], cwd=ENGINE_DIR, env=env, capture_output=True,
                              text=True, timeout=120)

    def test_the_command_runs_the_corpus_and_prints_the_summary_and_never_the_problems(self):
        r = self.kb(self.write_corpus([P1, P2, P3, P4]), self.report_path())
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["positive"], out["controls"]), (3, 1))
        self.assertTrue(os.path.exists(self.report_path()))
        self.assertNotIn("Q1 text", r.stdout)
        self.assertNotIn("\x1b", r.stdout)

    def test_check_through_the_command_sends_nothing(self):
        before = len(self.sent())
        r = self.kb("--check", self.write_corpus([P1, P2]), self.report_path())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.sent()), before)
        self.assertFalse(os.path.exists(self.report_path()))
        self.assertIs(json.loads(r.stdout)["check"], True)

    def test_the_command_refuses_what_it_cannot_do_and_prints_nothing_on_standard_output(self):
        for args in ([self.write_corpus([problem_of("a", "t", ["No such title"])]), self.report_path()],
                     [os.path.join(self.base, "missing.json"), self.report_path()], []):
            r = self.kb(*args)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
        self.assertEqual(self.kb(self.write_corpus([problem_of("a", "t", ["No such title"])]), self.report_path()).returncode, 2)


if __name__ == "__main__":
    unittest.main()
