"""The queue of cards: a plan (a snapshot of the books that need a card) and a run that works through the models one at a time."""
import copy
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_cardmake import LibraryCase, block, config_models

from kb import KbError, card, cardmake, cardqueue, cardstate, catalog, models
from kb import config as kbconfig

FAKE = """#!{python}
import json, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = lambda name: args[args.index(name) + 1] if name in args else None
prompt = sys.stdin.read()
kind = os.path.basename(opt("--schema") or "")
plan = json.load(open(os.path.join(here, "plan.json")))
title = (re.search(r"TITLE [0-9a-f]+ BEGIN>>>\\n(.*?)\\n<<<TITLE", prompt, re.S) or [None, ""])[1]
with open(os.path.join(here, "calls.jsonl"), "a") as handle:
    handle.write(json.dumps({"server": opt("--server"), "model": opt("--model"), "kind": kind, "title": title}) + "\\n")
for name, job in (("down_card", "card.json"), ("down_notes", "card-notes.json")):
    down = plan.get(name, {}).get(title, 0)
    if (kind == job or (name == "down_card" and kind == "card-earlier.json")) and down:
        plan[name][title] = down - 1
        json.dump(plan, open(os.path.join(here, "plan.json"), "w"))
        sys.stdout.write(json.dumps({"contract": 2, "ok": False, "vendor": "ollama", "error": "unreachable", "detail": "no answer"}))
        sys.exit(1)
if kind == "card-check.json":
    answer = {"verdicts": ["supports"] * sum(1 for line in prompt.splitlines() if re.match(r"\\d+\\. \\[", line))}
elif kind == "card-notes.json":
    answer = dict(plan["notes"])
    left = plan.get("bad_notes", {}).get(title, 0)
    if left:
        plan["bad_notes"][title] = left - 1
        json.dump(plan, open(os.path.join(here, "plan.json"), "w"))
        answer["quotes"] = []  # not the length of the points: a reply that is refused
else:
    answer = dict(plan["earlier_card"] if kind == "card-earlier.json" else plan["card"])
    left = plan.get("bad_card", {}).get(title, 0)
    if kind in ("card.json", "card-earlier.json") and left:
        plan["bad_card"][title] = left - 1
        json.dump(plan, open(os.path.join(here, "plan.json"), "w"))
        answer["topics_support"] = ["1.1"]  # not the length of the topics: a reply that is refused
sys.stdout.write(json.dumps({"contract": 2, "ok": True, "vendor": "ollama", "model": "m1:latest", "reply": json.dumps(answer),
                             "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": None, "cached_input_tokens": None,
                                       "reasoning_output_tokens": None}}))
"""

TEXT = "the text studies one stopping rule and it proves a bound on regret " + "filler " * 200
NOTES = {"points": ["the text studies one stopping rule"], "quotes": ["studies one stopping rule"]}
CARD = {"useful_for": ["finding a stopping rule"], "topics": ["stopping rule", "early rule"],
        "adjacent_topics": ["search"], "key_ideas": ["stopping rule studied", "rule of stopping", "stopping early rule"],
        "caveats": [], "topics_support": ["1.1", "1.1"], "key_ideas_support": ["1.1", "1.1", "1.1"], "caveats_support": [],
        "sentence_fields": ["limits"], "sentences": ["stopping rule only"], "sentences_support": ["1.1"]}
EARLIER_CARD = {"summary": "A short summary of the work.", "useful_for": ["finding a stopping rule"], "topics": ["stopping rule", "early rule"],
                "adjacent_topics": ["search"], "key_ideas": ["stopping rule studied", "rule of stopping", "stopping early rule"],
                "neutral_problem": "deciding when to stop", "neutral_approach": "compare a running score with a threshold",
                "neutral_needs": "a stream of observations", "neutral_provides": "a stopping time", "neutral_limits": "stopping rule only",
                "caveats": [], "topics_support": ["1.1", "1.1"], "key_ideas_support": ["1.1", "1.1", "1.1"], "caveats_support": [],
                "neutral_limits_support": "1.1"}
SERVERS = {"notes": "srv-n", "cardm": "srv-c", "checker": "srv-k", "morem": "srv-m"}


class QueueCase(LibraryCase):
    def setUp(self):
        super().setUp()
        with open(self.launcher, "w") as f:
            f.write(FAKE.replace("{python}", sys.executable))
        os.chmod(self.launcher, 0o700)
        self.set_plan()
        self.index_root = self.store.cfg["index_root"]

    def set_plan(self, **extra):
        with open(os.path.join(self.fake, "plan.json"), "w") as f:
            json.dump({"notes": NOTES, "card": CARD, "earlier_card": EARLIER_CARD, **extra}, f)

    def log(self):
        path = os.path.join(self.fake, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def changes(self):
        """The number of times the model changed from one call to the next."""
        servers = [(c["server"], c["model"]) for c in self.log()]
        return sum(1 for a, b in zip(servers, servers[1:]) if a != b)

    def books(self, count, prefix="Book"):
        return [self.converted_book(blocks=[block(TEXT)], title=f"{prefix} {n}")[0] for n in range(count)]

    def loaded(self):
        return kbconfig.load()

    def plan(self, **kw):
        return cardqueue.plan(self.store, self.loaded(), **kw)

    def run_queue(self, run_id, **kw):
        return cardqueue.run(self.store, self.loaded(), run_id, launcher=self.launcher, **kw)

    def manifest(self, run_id):
        return cardstate.read_manifest(self.index_root, run_id)

    def states(self, report):
        return {x["book_id"]: x["status"] for x in report["items"]}


class PlanTest(QueueCase):
    def test_a_plan_is_a_snapshot_of_the_active_converted_books_that_have_no_card(self):
        fresh = self.books(2)
        carded = self.books(1, "Carded")[0]
        card.file(self.store, card.make(self.store, carded, self.store.read_book(carded)["current_version"]))
        weeded = self.books(1, "Weeded")[0]
        self.store.set_state(weeded, "weeded")
        unconverted = self.converted_book(title="Pending", state="pending")[0]
        listed = self.plan()
        self.assertEqual(listed["books"], 2)
        self.assertEqual(listed["skipped"], {"inactive": 1, "not_converted": 1, "has_card": 1})
        manifest = self.manifest(listed["run"])
        self.assertEqual(set(self.books_of(manifest)), set(fresh))
        self.assertNotIn(carded, self.books_of(manifest))
        self.assertNotIn(weeded, self.books_of(manifest))
        self.assertNotIn(unconverted, self.books_of(manifest))

    def books_of(self, manifest):
        return [i["book_id"] for i in manifest.items]

    def test_a_plan_makes_no_call_and_sends_nothing(self):
        self.books(2)
        self.plan()
        self.assertEqual(self.log(), [])

    def test_again_includes_books_that_have_a_card_and_book_limits_the_plan(self):
        one, two = self.books(2)
        card.file(self.store, card.make(self.store, one, self.store.read_book(one)["current_version"]))
        self.assertEqual(self.plan()["books"], 1)
        self.assertEqual(self.plan(again=True)["books"], 2)
        listed = self.plan(book_ids=[one], again=True)
        self.assertEqual(listed["books"], 1)
        self.assertEqual(self.books_of(self.manifest(listed["run"])), [one])

    def test_a_book_that_arrives_after_the_plan_is_not_in_the_run(self):
        self.books(2)
        listed = self.plan()
        late = self.books(1, "Late")[0]
        report = self.run_queue(listed["run"])
        self.assertEqual(len(report["items"]), 2)
        self.assertEqual(card.generations(self.store, late, self.store.read_book(late)["current_version"]), [])
        self.assertEqual(self.plan()["books"], 1)  # the next plan has it

    def test_a_book_named_twice_is_planned_once(self):
        book = self.books(1)[0]
        listed = self.plan(book_ids=[book, book])
        self.assertEqual(listed["books"], 1)
        self.assertEqual(self.books_of(self.manifest(listed["run"])), [book])

    def test_the_calls_that_can_be_counted_are_those_of_the_books_that_need_the_models(self):
        self.converted_book(blocks=[block("a very short note")], title="Small")
        self.books(2)
        listed = self.plan()
        self.assertEqual(listed["books"], 3)
        self.assertEqual(listed["calls_known"], {"notes": 2, "card": 2})
        self.assertEqual(listed["skipped"]["has_card"], 0)

    def test_two_plans_have_two_runs_with_their_own_state(self):
        self.books(2)
        a, b = self.plan(), self.plan()
        self.assertNotEqual(a["run"], b["run"])
        self.run_queue(a["run"])
        self.assertEqual({i["status"] for i in self.manifest(b["run"]).items}, {"waiting"})

    def test_the_plan_names_the_models_by_entry_in_the_order_of_the_run_and_no_address(self):
        self.books(1)
        listed = self.plan()
        self.assertEqual(listed["order"], ["notes", "cardm", "checker"])
        self.assertNotIn("srv-", json.dumps(listed))

    def test_the_plan_refuses_an_unknown_book_and_a_missing_setting_and_writes_nothing(self):
        self.books(1)
        with self.assertRaises(KbError):
            self.plan(book_ids=["01ARZ3NDEKTSV4RRFFQ69G5FAV"])
        self.set_config(tasks={"card": "cardm"})
        with self.assertRaises(KbError):
            self.plan()
        self.assertFalse(os.path.exists(os.path.join(self.index_root, cardstate.FOLDER)))


class RunTest(QueueCase):
    def test_the_run_makes_the_cards_as_new_generations_and_reports_each_book(self):
        books = self.books(3)
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        for book in books:
            version = self.store.read_book(book)["current_version"]
            self.assertEqual(card.generations(self.store, book, version), [1])
            filed = card.read(self.store, book, version)[1]
            self.assertEqual(filed["format"], 2)
            self.assertEqual(filed["model"]["topics"], ["stopping rule", "early rule"])
        self.assertEqual(report["counts"], {"done": 3, "failed": 0, "dropped": 0, "waiting": 0})
        self.assertTrue(all(x["generation"] == 1 for x in report["items"]))

    def test_the_number_of_changes_from_one_model_to_another_does_not_depend_on_the_number_of_books(self):
        self.books(2)
        self.run_queue(self.plan()["run"])
        small = self.changes()
        self.assertEqual(small, 2)  # the notes, then the cards, then the checks
        os.remove(os.path.join(self.fake, "calls.jsonl"))
        self.books(6, "More")
        self.run_queue(self.plan()["run"])
        self.assertEqual(self.changes(), small)
        self.assertEqual(len(self.log()), 3 * 6)

    def test_two_entries_that_name_the_same_server_and_model_are_one_queue_and_keep_their_own_options(self):
        cfg = self.loaded()
        cfg["models"]["cardm2"] = dict(cfg["models"]["cardm"], max_output=1234)
        cfg["tasks"]["card-check"] = "cardm2"
        kbconfig.save(cfg)
        self.books(4)
        self.run_queue(self.plan()["run"])
        self.assertEqual(self.changes(), 1)  # the notes, then the cards and the checks on the same model
        self.assertEqual(self.plan()["order"], ["notes", "cardm", "cardm2"])
        kinds = [c["kind"] for c in self.log() if c["kind"] != "card-notes.json"]
        self.assertEqual(kinds, ["card.json", "card-check.json"] * 4)  # one visit: each book goes from its card to its checks

    def test_two_entries_that_name_different_models_are_two_queues(self):
        self.books(2)
        listed = self.plan()
        self.run_queue(listed["run"])
        self.assertEqual(len({(c["server"], c["model"]) for c in self.log()}), 3)

    def test_a_run_that_is_stopped_and_started_again_repeats_no_saved_call_and_makes_the_same_cards(self):
        books = self.books(3)
        listed = self.plan()
        original = models.run_job
        count = {"n": 0}

        def stop_after(limit):
            def wrapper(*args, **kw):
                if count["n"] >= limit:
                    raise KeyboardInterrupt()
                count["n"] += 1
                return original(*args, **kw)
            return wrapper

        with mock.patch.object(cardmake.models, "run_job", side_effect=stop_after(5)):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        self.assertEqual(len(self.log()), 5)
        self.assertTrue(os.path.isdir(os.path.join(self.index_root, cardstate.FOLDER, listed["run"])))
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        self.assertEqual(len(self.log()), 9)  # three calls for each of three books, none twice
        for book in books:
            self.assertEqual(card.generations(self.store, book, self.store.read_book(book)["current_version"]), [1])

    def test_a_card_is_filed_as_soon_as_its_last_call_is_made(self):
        books = self.books(2)
        listed = self.plan()
        original = card.file
        filed = []

        def file_once(store, made):
            if filed:
                raise KeyboardInterrupt()
            filed.append(made["book_id"])
            return original(store, made)

        with mock.patch.object(cardqueue.card, "file", side_effect=file_once):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        first, second = books
        saved = {i["book_id"]: i["status"] for i in self.manifest(listed["run"]).items}
        self.assertEqual(saved, {first: "done", second: "waiting"})  # the manifest was told as soon as the first card was filed
        self.assertEqual(card.generations(self.store, first, self.store.read_book(first)["current_version"]), [1])
        self.assertEqual(card.generations(self.store, second, self.store.read_book(second)["current_version"]), [])
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})

    def test_the_visits_are_one_for_each_run_of_stages_on_one_server_and_model(self):
        cfg = self.loaded()
        order = lambda c: cardqueue._turns(c, cardqueue._sequence(c))
        self.assertEqual(order(cfg), [(("srv-n", "m-notes"), {"notes"}), (("srv-c", "m-card"), {"cardm"}), (("srv-k", "m-check"), {"checker"})])
        shared = copy.deepcopy(cfg)
        shared["models"]["cardm2"] = dict(shared["models"]["cardm"], max_output=1234)
        shared["tasks"]["card-check"] = "cardm2"
        self.assertEqual(order(shared), [(("srv-n", "m-notes"), {"notes"}), (("srv-c", "m-card"), {"cardm", "cardm2"})])
        apart = copy.deepcopy(cfg)
        apart["tasks"]["card-check"] = "notes"  # the notes and the checks on one model, the card on another between them
        self.assertEqual(order(apart), [(("srv-n", "m-notes"), {"notes"}), (("srv-c", "m-card"), {"cardm"}), (("srv-n", "m-notes"), {"notes"})])
        more = copy.deepcopy(cfg)
        more["tasks"]["card-more"] = "morem"
        self.assertEqual([g for g, _ in order(more)], [("srv-n", "m-notes"), ("srv-c", "m-card"), ("srv-k", "m-check"),
                                                        ("srv-m", "m-more"), ("srv-k", "m-check")])

    def test_a_card_filed_just_before_a_stop_is_not_made_a_second_time_when_the_run_is_run_again(self):
        book = self.books(1)[0]
        version = self.store.read_book(book)["current_version"]
        listed = self.plan()
        original = card.file

        def file_then_stop(store, made):
            original(store, made)
            raise KeyboardInterrupt()  # the card is filed, and the manifest has not yet been told

        with mock.patch.object(cardqueue.card, "file", side_effect=file_then_stop):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        calls = len(self.log())
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {book: "done"})
        self.assertEqual(card.generations(self.store, book, version), [1])
        self.assertEqual(len(self.log()), calls)  # no call was made again
        self.assertIn("filed after the plan", report["items"][0]["reason"])

    def test_with_again_a_book_that_has_a_card_gets_the_next_generation(self):
        book = self.books(1)[0]
        version = self.store.read_book(book)["current_version"]
        self.run_queue(self.plan()["run"])
        report = self.run_queue(self.plan(again=True)["run"])
        self.assertEqual(report["items"][0]["generation"], 2)
        self.assertEqual(card.generations(self.store, book, version), [1, 2])

    def test_a_refused_answer_is_kept_aside_and_the_stage_is_tried_again_in_the_next_pass(self):
        books = self.books(2)
        self.set_plan(bad_card={"Book 0": 1})
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        self.assertEqual(report["passes"], 2)
        self.assertEqual(len(os.listdir(os.path.join(self.index_root, "refused"))), 1)
        item = next(x for x in report["items"] if x["book_id"] == books[0])
        self.assertEqual(item["attempts"], 1)
        cards_of_book_0 = [c for c in self.log() if c["kind"] == "card.json" and c["title"] == "Book 0"]
        self.assertEqual(len(cards_of_book_0), 2)

    def test_a_call_that_fails_is_left_for_the_next_pass_and_not_tried_again_in_the_same_pass(self):
        books = self.books(2)
        self.set_plan(down_card={"Book 0": 1})
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        self.assertEqual(report["passes"], 2)
        self.assertEqual(len([c for c in self.log() if c["kind"] == "card.json" and c["title"] == "Book 0"]), 2)  # once in each pass
        self.assertEqual(report["items"][0]["attempts"], 1)

    def test_a_book_that_failed_waits_for_the_next_pass_even_if_a_later_visit_serves_the_same_model(self):
        cfg = self.loaded()
        cfg["tasks"]["card-check"] = "notes"  # the notes and the checks on one model, the card on another between the two visits
        kbconfig.save(cfg)
        books = self.books(2)
        self.set_plan(down_notes={"Book 0": 1})
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        self.assertEqual(report["passes"], 2)  # the second visit of the model in the first pass did not try the failed book again
        order = [(c["kind"], c["title"]) for c in self.log()]
        self.assertEqual(order, [("card-notes.json", "Book 0"), ("card-notes.json", "Book 1"), ("card.json", "Book 1"), ("card-check.json", "Book 1"),
                                 ("card-notes.json", "Book 0"), ("card.json", "Book 0"), ("card-check.json", "Book 0")])

    def test_a_book_whose_answer_was_refused_waits_for_the_next_pass_even_if_a_later_visit_serves_the_same_model(self):
        cfg = self.loaded()
        cfg["tasks"]["card-check"] = "notes"
        kbconfig.save(cfg)
        books = self.books(2)
        self.set_plan(bad_notes={"Book 0": 1})
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {b: "done" for b in books})
        self.assertEqual(report["passes"], 2)
        self.assertEqual(len(os.listdir(os.path.join(self.index_root, "refused"))), 1)
        order = [(c["kind"], c["title"]) for c in self.log()]
        self.assertEqual(order, [("card-notes.json", "Book 0"), ("card-notes.json", "Book 1"), ("card.json", "Book 1"), ("card-check.json", "Book 1"),
                                 ("card-notes.json", "Book 0"), ("card.json", "Book 0"), ("card-check.json", "Book 0")])

    def test_a_call_that_keeps_failing_is_reported_as_failed_with_its_reason(self):
        books = self.books(2)
        self.set_plan(down_card={"Book 0": 99})
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {books[0]: "failed", books[1]: "done"})
        self.assertEqual(report["items"][0]["attempts"], 2)
        self.assertTrue(report["items"][0]["reason"])

    def test_the_passes_of_a_run_are_limited_and_a_run_that_is_run_again_goes_on(self):
        books = self.books(2)
        self.set_plan(down_card={"Book 0": 1})
        listed = self.plan()
        report = self.run_queue(listed["run"], passes=1)
        self.assertEqual((report["passes"], report["counts"]), (1, {"done": 1, "failed": 0, "dropped": 0, "waiting": 1}))
        again = self.run_queue(listed["run"], passes=1)
        self.assertEqual((again["passes"], again["counts"]["done"]), (1, 2))
        for bad in (0, 11, "2", True, None):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                self.run_queue(listed["run"], passes=bad)

    def test_a_saved_state_that_is_stale_or_wrong_is_dropped_and_not_taken_for_a_failure(self):
        books = self.books(2)
        listed = self.plan()
        original = models.run_job
        count = {"n": 0}

        def wrapper(*args, **kw):
            if count["n"] >= 2:
                raise KeyboardInterrupt()
            count["n"] += 1
            return original(*args, **kw)

        with mock.patch.object(cardmake.models, "run_job", side_effect=wrapper):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        version = self.store.read_book(books[0])["current_version"]
        journal = cardstate.read(self.index_root, listed["run"], books[0], version)
        journal.header["title"] = "Another title"
        cardstate.write(self.index_root, listed["run"], books[0], version, journal)
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {books[0]: "dropped", books[1]: "done"})
        self.assertIn("not usable", report["items"][0]["reason"])
        self.assertEqual(card.generations(self.store, books[0], version), [])

    def test_a_stage_that_fails_again_is_reported_as_failed_and_the_other_books_are_made(self):
        books = self.books(3)
        self.set_plan(bad_card={"Book 1": 99})
        report = self.run_queue(self.plan()["run"])
        states = self.states(report)
        self.assertEqual((states[books[0]], states[books[1]], states[books[2]]), ("done", "failed", "done"))
        failed = next(x for x in report["items"] if x["status"] == "failed")
        self.assertIn("same length", failed["reason"])
        self.assertEqual(failed["attempts"], 2)
        self.assertEqual(report["counts"], {"done": 2, "failed": 1, "dropped": 0, "waiting": 0})
        self.assertEqual(len([c for c in self.log() if c["kind"] == "card.json" and c["title"] == "Book 1"]), 2)  # tried, and tried once more
        self.assertLessEqual(report["passes"], cardqueue.PASS_CAP)

    def test_a_version_whose_conversion_changed_since_the_plan_is_dropped_and_reported(self):
        books = self.books(2)
        listed = self.plan()
        manifest = self.manifest(listed["run"])
        manifest.items[0]["fingerprint"] = dict(manifest.items[0]["fingerprint"], generation=99)
        cardstate.write_manifest(self.index_root, listed["run"], manifest)
        report = self.run_queue(listed["run"])
        states = self.states(report)
        self.assertEqual((states[books[0]], states[books[1]]), ("dropped", "done"))
        dropped = next(x for x in report["items"] if x["status"] == "dropped")
        self.assertIn("conversion", dropped["reason"])
        self.assertEqual(card.generations(self.store, books[0], self.store.read_book(books[0])["current_version"]), [])

    def test_a_book_that_is_no_longer_active_is_dropped(self):
        books = self.books(2)
        listed = self.plan()
        self.store.set_state(books[1], "weeded")
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {books[0]: "done", books[1]: "dropped"})
        self.assertIn("active", next(x for x in report["items"] if x["status"] == "dropped")["reason"])

    def test_an_error_while_filing_a_card_fails_that_book_and_the_run_goes_on(self):
        books = self.books(3)
        original = card.file

        def file_unless_book_1(store, made):
            if made["title"] == "Book 1":
                raise KbError("the card is too large to keep")
            return original(store, made)

        with mock.patch.object(cardqueue.card, "file", side_effect=file_unless_book_1):
            report = self.run_queue(self.plan()["run"])
        states = self.states(report)
        self.assertEqual((states[books[0]], states[books[1]], states[books[2]]), ("done", "failed", "done"))
        failed = next(x for x in report["items"] if x["status"] == "failed")
        self.assertIn("too large", failed["reason"])
        self.assertEqual(failed["attempts"], 2)
        self.assertEqual(report["passes"], 2)

    def test_an_error_while_filing_a_card_from_the_metadata_fails_that_book_and_the_run_goes_on(self):
        small = self.converted_book(blocks=[block("a very short note")], title="Small")[0]
        other = self.books(1)[0]
        original = card.file

        def file_unless_small(store, made):
            if made["title"] == "Small":
                raise KbError("the card is too large to keep")
            return original(store, made)

        with mock.patch.object(cardqueue.card, "file", side_effect=file_unless_small):
            report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {small: "failed", other: "done"})

    def stop_after(self, listed, calls):
        """Run until `calls` calls have been made and then stop, as an interrupt would."""
        original = models.run_job
        count = {"n": 0}

        def wrapper(*args, **kw):
            if count["n"] >= calls:
                raise KeyboardInterrupt()
            count["n"] += 1
            return original(*args, **kw)

        with mock.patch.object(cardmake.models, "run_job", side_effect=wrapper):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])

    def journal_path(self, run, book):
        return os.path.join(self.index_root, cardstate.FOLDER, run, f"{book}-{self.store.read_book(book)['current_version']}.json")

    def test_a_journal_that_cannot_be_read_drops_that_book_and_the_run_goes_on(self):
        books = self.books(3)
        listed = self.plan()
        self.stop_after(listed, 3)  # the notes of the three books
        with open(self.journal_path(listed["run"], books[0]), "w") as f:
            f.write("not json")
        os.chmod(self.journal_path(listed["run"], books[0]), 0o600)
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {books[0]: "dropped", books[1]: "done", books[2]: "done"})
        self.assertIn("not usable", report["items"][0]["reason"])

    def test_a_directory_or_a_pipe_in_place_of_a_journal_drops_that_book_and_the_run_goes_on(self):
        for make in (lambda path: os.mkdir(path, 0o700), lambda path: os.mkfifo(path, 0o600)):
            with self.subTest(make=make):
                books = self.books(2, prefix=f"Set{len(self.log())}")
                listed = self.plan()
                self.stop_after(listed, 2)
                path = self.journal_path(listed["run"], books[0])
                os.remove(path)
                make(path)
                report = self.run_queue(listed["run"])
                states = self.states(report)  # a book dropped by the first round of this test has no card and is in the second plan too
                self.assertEqual((states[books[0]], states[books[1]]), ("dropped", "done"))

    def test_an_unexpected_error_in_one_book_fails_that_book_and_shows_only_the_kind_of_error(self):
        books = self.books(3)
        original = cardmake.plan_version

        def broken_for_book_1(store, cfg, book_id, version_id=None, again=False):
            if book_id == books[1]:
                raise ValueError("secret words of the book")
            return original(store, cfg, book_id, version_id, again)

        listed = self.plan()
        with mock.patch.object(cardqueue.cardmake, "plan_version", side_effect=broken_for_book_1):
            report = self.run_queue(listed["run"])
        states = self.states(report)
        self.assertEqual((states[books[0]], states[books[1]], states[books[2]]), ("done", "failed", "done"))
        reason = next(x for x in report["items"] if x["status"] == "failed")["reason"]
        self.assertIn("ValueError", reason)
        self.assertNotIn("secret", reason)

    def test_a_manifest_that_cannot_be_written_stops_the_run_and_is_not_taken_for_the_failure_of_a_book(self):
        self.books(2)
        listed = self.plan()
        original = cardstate.write_manifest
        count = {"n": 0}

        def failing(*args, **kw):
            count["n"] += 1
            if count["n"] > 1:
                raise KbError("the saved state could not be written")
            return original(*args, **kw)

        with mock.patch.object(cardqueue.cardstate, "write_manifest", side_effect=failing):
            with self.assertRaises(KbError) as cm:
                self.run_queue(listed["run"])
        self.assertIn("could not be written", str(cm.exception))

    def test_a_book_that_has_a_newer_version_than_the_plan_saw_is_dropped(self):
        book = self.books(1)[0]
        listed = self.plan()
        newer = self.store.add_version(book, label="v2", source={"retrieved": "2026-11-02T00:00:00+00:00"})
        self.assertNotEqual(newer, self.manifest(listed["run"]).items[0]["version_id"])
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {book: "dropped"})
        self.assertIn("newer version", report["items"][0]["reason"])

    def test_two_plans_never_share_a_name(self):
        self.books(1)
        with mock.patch.object(cardqueue, "_stamp", return_value="20261108t120000z-abcdef"):
            self.plan()
            with self.assertRaises(KbError):
                self.plan()

    def test_a_small_book_gets_a_card_from_its_metadata_with_no_call(self):
        small = self.converted_book(blocks=[block("a very short note")], title="Small")[0]
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(self.states(report), {small: "done"})
        self.assertEqual(self.log(), [])
        self.assertIsNone(card.read(self.store, small, self.store.read_book(small)["current_version"])[1]["model"])

    def test_a_run_of_another_name_at_the_same_time_is_refused_too_because_one_queue_runs_at_a_time(self):
        self.books(2)
        first, second = self.plan(), self.plan()
        with cardstate.lock(self.index_root, first["run"]):
            with self.assertRaises(KbError) as cm:
                self.run_queue(second["run"])
            self.assertIn("another run", str(cm.exception))
            self.assertEqual(self.log(), [])
        self.assertEqual(self.run_queue(second["run"])["counts"]["done"], 2)

    def test_a_version_that_gets_its_card_from_the_metadata_now_but_had_a_conversion_at_the_plan_is_dropped(self):
        books = self.books(2)
        listed = self.plan()
        self.set_config(card_min_chars=10 ** 6)  # the text of the books is now shorter than the cutoff
        report = self.run_queue(listed["run"])
        self.assertEqual(self.states(report), {b: "dropped" for b in books})
        self.assertIn("conversion", report["items"][0]["reason"])
        self.assertEqual(card.generations(self.store, books[0], self.store.read_book(books[0])["current_version"]), [])

    def test_a_saved_state_made_with_other_settings_is_dropped_and_the_reason_says_so(self):
        books = self.books(1)
        listed = self.plan()
        original = models.run_job
        count = {"n": 0}

        def wrapper(*args, **kw):
            if count["n"] >= 1:
                raise KeyboardInterrupt()
            count["n"] += 1
            return original(*args, **kw)

        with mock.patch.object(cardmake.models, "run_job", side_effect=wrapper):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        self.set_config(card_pieces=1)
        report = self.run_queue(listed["run"])
        self.assertEqual(report["items"][0]["status"], "dropped")
        self.assertIn("stale", report["items"][0]["reason"])

    def test_a_second_run_at_the_same_time_is_refused_and_the_lock_is_released_afterwards(self):
        self.books(1)
        listed = self.plan()
        with cardstate.lock(self.index_root, listed["run"]):
            with self.assertRaises(KbError) as cm:
                self.run_queue(listed["run"])
            self.assertIn("another run", str(cm.exception))
            self.assertEqual(self.log(), [])
        report = self.run_queue(listed["run"])
        self.assertEqual(report["counts"]["done"], 1)

    def test_the_lock_is_released_when_a_run_is_interrupted(self):
        self.books(1)
        listed = self.plan()
        with mock.patch.object(cardmake.models, "run_job", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        self.assertEqual(self.run_queue(listed["run"])["counts"]["done"], 1)

    def test_the_catalog_is_rebuilt_at_the_end_of_a_run_that_made_cards(self):
        self.books(2)
        report = self.run_queue(self.plan()["run"])
        self.assertEqual(report["catalog"]["cards"], 2)
        self.assertEqual(len(catalog.search(self.index_root, "stopping")), 2)

    def test_a_run_that_made_no_card_does_not_rebuild_the_catalog(self):
        report = self.run_queue(self.plan()["run"])
        self.assertIsNone(report["catalog"])

    def test_a_finished_run_leaves_no_journal_of_a_card_that_was_made(self):
        books = self.books(2)
        listed = self.plan()
        self.run_queue(listed["run"])
        folder = os.path.join(self.index_root, cardstate.FOLDER, listed["run"])
        self.assertEqual(sorted(os.listdir(folder)), ["manifest.json"])

    def test_an_unknown_run_and_a_missing_setting_are_refused_before_any_call(self):
        self.books(1)
        with self.assertRaises(KbError):
            self.run_queue("nosuchrun")
        listed = self.plan()
        self.set_config(tasks={"card": "cardm"})
        with self.assertRaises(KbError):
            self.run_queue(listed["run"])
        self.assertEqual(self.log(), [])

    def test_a_finished_run_run_again_does_nothing(self):
        self.books(1)
        listed = self.plan()
        self.run_queue(listed["run"])
        calls = len(self.log())
        report = self.run_queue(listed["run"])
        self.assertEqual(len(self.log()), calls)
        self.assertEqual(report["counts"]["done"], 1)
        self.assertIsNone(report["catalog"])

    def test_the_second_round_is_a_turn_of_its_own_when_it_has_its_own_model(self):
        cfg = self.loaded()
        cfg["tasks"]["card-more"] = "morem"
        kbconfig.save(cfg)
        self.books(1)
        listed = self.plan()
        self.assertEqual(listed["order"], ["notes", "cardm", "checker", "morem", "checker"])


class StatusTest(QueueCase):
    def test_status_counts_the_books_by_where_they_are_and_names_the_failures_with_no_book_text(self):
        books = self.books(3)
        self.set_plan(bad_card={"Book 1": 99})
        listed = self.plan()
        before = cardqueue.status(self.store, listed["run"])
        self.assertEqual(before["counts"], {"done": 0, "failed": 0, "dropped": 0, "waiting": 3})
        self.assertEqual(before["waiting"], {"not started": 3})
        self.run_queue(listed["run"])
        after = cardqueue.status(self.store, listed["run"])
        self.assertEqual(after["counts"], {"done": 2, "failed": 1, "dropped": 0, "waiting": 0})
        self.assertEqual([x["book_id"] for x in after["items"] if x["status"] == "failed"], [books[1]])
        text = json.dumps(after)
        for word in ("Book 1", "stopping rule", "studies"):
            self.assertNotIn(word, text)

    def test_status_shows_how_far_a_stopped_run_has_got(self):
        self.books(2)
        listed = self.plan()
        original = models.run_job
        count = {"n": 0}

        def wrapper(*args, **kw):
            if count["n"] >= 2:
                raise KeyboardInterrupt()
            count["n"] += 1
            return original(*args, **kw)

        with mock.patch.object(cardmake.models, "run_job", side_effect=wrapper):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        self.assertEqual(cardqueue.status(self.store, listed["run"])["waiting"], {"notes": 2})  # the notes of both books, and nothing more

    def test_a_journal_that_cannot_be_read_does_not_hide_the_status_of_the_others(self):
        books = self.books(2)
        listed = self.plan()
        original = models.run_job
        count = {"n": 0}

        def wrapper(*args, **kw):
            if count["n"] >= 2:
                raise KeyboardInterrupt()
            count["n"] += 1
            return original(*args, **kw)

        with mock.patch.object(cardmake.models, "run_job", side_effect=wrapper):
            with self.assertRaises(KeyboardInterrupt):
                self.run_queue(listed["run"])
        version = self.store.read_book(books[0])["current_version"]
        path = os.path.join(self.index_root, cardstate.FOLDER, listed["run"], f"{books[0]}-{version}.json")
        with open(path, "w") as f:
            f.write("not json")
        self.assertEqual(cardqueue.status(self.store, listed["run"])["waiting"], {"unreadable": 1, "notes": 1})

    def test_a_report_with_no_catalog_says_so_when_cards_were_made_before(self):
        self.books(1)
        listed = self.plan()
        self.run_queue(listed["run"])
        again = self.run_queue(listed["run"])
        self.assertIsNone(again["catalog"])
        self.assertIn("card-index", again["catalog_note"])
        empty = self.run_queue(self.plan()["run"])
        self.assertEqual(empty["catalog_note"], "")

    def test_status_of_an_unknown_run_is_refused(self):
        with self.assertRaises(KbError):
            cardqueue.status(self.store, "nosuchrun")


class FormTest(QueueCase):
    """The form of the card call (`earlier` or `sentences`) is a property of a run: planned, kept in the manifest, used for every call,
    named in the reports, and a journal of the other form is refused."""

    def kinds(self):
        return [c["kind"] for c in self.log()]

    def test_a_plan_records_its_form_in_the_manifest_and_the_summary(self):
        self.books(1)
        for form in ("earlier", "sentences"):
            with self.subTest(form=form):
                listed = self.plan(form=form, again=True)
                self.assertEqual((listed["form"], self.manifest(listed["run"]).form), (form, form))

    def test_a_plan_without_a_form_is_the_sentence_form_as_it_was_before(self):
        self.books(1)
        listed = self.plan()
        self.assertEqual((listed["form"], self.manifest(listed["run"]).form), ("sentences", "sentences"))

    def test_a_form_outside_the_two_is_refused_before_a_run_is_written(self):
        self.books(1)
        for bad in ("third", "", None, 5, ["earlier"]):
            with self.subTest(bad=bad), self.assertRaises(KbError) as cm:
                self.plan(form=bad)
            self.assertIn("earlier, sentences", str(cm.exception))   # said at once, not as a manifest that cannot be written
        self.assertFalse(os.path.exists(os.path.join(self.index_root, cardstate.FOLDER)) and os.listdir(os.path.join(self.index_root, cardstate.FOLDER)))

    def test_a_run_of_the_earlier_form_makes_every_card_call_in_that_form_and_a_run_of_the_other_in_its_own(self):
        for form, schema in (("earlier", "card-earlier.json"), ("sentences", "card.json")):
            with self.subTest(form=form):
                self.books(1, f"Book {form}")
                before = len(self.log())
                listed = self.plan(form=form)
                ran = self.run_queue(listed["run"])
                self.assertEqual(ran["counts"]["done"], 1)
                made = [k for k in self.kinds()[before:] if k.startswith("card") and not k.startswith(("card-notes", "card-check", "card-more"))]
                self.assertEqual(made, [schema])
                self.assertEqual(ran["form"], form)

    def test_a_card_made_in_the_earlier_form_is_a_card_with_plain_neutral_parts_and_no_sentence_record(self):
        (book,) = self.books(1)
        self.run_queue(self.plan(form="earlier")["run"])
        version = self.store.read_book(book)["current_version"]
        made = card.read(self.store, book, version, 1)[1]
        self.assertEqual(made["model"]["neutral_problem"], EARLIER_CARD["neutral_problem"])
        self.assertNotIn("sentences", made["grounding"])

    def test_status_names_the_form(self):
        self.books(1)
        listed = self.plan(form="earlier")
        self.assertEqual(cardqueue.status(self.store, listed["run"])["form"], "earlier")

    def test_a_run_planned_before_the_forms_has_no_form_and_runs_as_the_sentence_form(self):
        self.books(1)
        listed = self.plan()
        doc = self.manifest(listed["run"]).document()
        doc.pop("form", None)
        path = os.path.join(self.index_root, cardstate.FOLDER, listed["run"], "manifest.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        ran = self.run_queue(listed["run"])
        self.assertEqual((ran["form"], ran["counts"]["done"]), ("sentences", 1))
        self.assertEqual([k for k in self.kinds() if k == "card-earlier.json"], [])

    def test_a_journal_of_the_other_form_is_refused_and_no_model_is_asked_for_that_book(self):
        (book,) = self.books(1)
        version = self.store.read_book(book)["current_version"]
        listed = self.plan(form="earlier")
        _, loaded, mechanical = cardmake.plan_version(self.store, self.loaded(), book, version, True)
        stale = cardmake.new_journal(self.loaded(), loaded[1], mechanical["title"], book, version, fingerprint=loaded[0],
                                     kind=mechanical["kind"], form="sentences")   # the header of the same card but for the other form
        cardstate.write(self.index_root, listed["run"], book, version, stale)
        ran = self.run_queue(listed["run"])
        self.assertEqual(self.states(ran), {book: "dropped"})
        self.assertIn("saved state", ran["items"][0]["reason"])
        self.assertEqual(self.log(), [])

    def test_a_run_that_is_run_again_keeps_its_form(self):
        self.books(2)
        listed = self.plan(form="earlier")
        self.run_queue(listed["run"], passes=1)
        again = self.run_queue(listed["run"])
        self.assertEqual(again["form"], "earlier")
        self.assertIn("card-earlier.json", self.kinds())
        self.assertNotIn("card.json", self.kinds())


class CommandTest(QueueCase):
    def kb(self, *args):
        env = dict(os.environ, KB_CONFIG_DIR=self.cfg, PATH=self.fake + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env, capture_output=True, text=True, timeout=120)

    def test_plan_run_and_status_run_through_the_command_line_and_print_numbers_and_ids_only(self):
        self.books(2)
        planned = self.kb("cards-queue", "plan")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        run_id = json.loads(planned.stdout)["run"]
        ran = self.kb("cards-queue", "run", run_id)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout)["counts"]["done"], 2)
        status = self.kb("cards-queue", "status", run_id)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertNotIn("stopping rule", ran.stdout + status.stdout + planned.stdout)

    def card_kinds(self):
        return [c["kind"] for c in self.log() if c["kind"] in ("card.json", "card-earlier.json")]

    def test_the_queue_plans_in_the_earlier_form_unless_the_sentence_form_is_asked_for(self):
        self.books(1)
        for args, form in (([], "earlier"), (["--form", "earlier"], "earlier"), (["--form", "sentences"], "sentences")):
            with self.subTest(args=args):
                planned = self.kb("cards-queue", "plan", "--again", *args)
                self.assertEqual(planned.returncode, 0, planned.stderr)
                run_id = json.loads(planned.stdout)["run"]
                self.assertEqual(json.loads(planned.stdout)["form"], form)
                before = len(self.card_kinds())
                ran = self.kb("cards-queue", "run", run_id)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertEqual(json.loads(ran.stdout)["form"], form)
                self.assertEqual(self.card_kinds()[before:], ["card-earlier.json" if form == "earlier" else "card.json"])
                self.assertEqual(json.loads(self.kb("cards-queue", "status", run_id).stdout)["form"], form)

    def test_cards_makes_the_card_in_the_earlier_form_unless_the_sentence_form_is_asked_for(self):
        (book,) = self.books(1)
        for args, schema in (([], "card-earlier.json"), (["--form", "sentences"], "card.json")):
            with self.subTest(args=args):
                before = len(self.card_kinds())
                done = self.kb("cards", "--book", book, "--again", *args)
                self.assertEqual(done.returncode, 0, done.stderr)
                report = json.loads(done.stdout.strip().splitlines()[-1])
                self.assertEqual((report["status"], report["form"]), ("carded", "earlier" if schema == "card-earlier.json" else "sentences"))
                self.assertEqual(self.card_kinds()[before:], [schema])

    def test_a_form_outside_the_two_is_refused_by_both_commands_and_nothing_is_sent(self):
        (book,) = self.books(1)
        for args in (["cards-queue", "plan", "--form", "third"], ["cards", "--book", book, "--form", "third"],
                     ["cards-queue", "plan", "--form", ""], ["cards", "--book", book, "--form", "Earlier"]):
            with self.subTest(args=args):
                self.assertEqual(self.kb(*args).returncode, 2)
        self.assertEqual(self.log(), [])

    def test_no_option_of_the_form_takes_a_path_an_address_or_a_model(self):
        for form in ("/etc/passwd", "http://x", "gpt-oss:20b", "../earlier"):
            with self.subTest(form=form):
                self.assertEqual(self.kb("cards-queue", "plan", "--form", form).returncode, 2)

    def test_no_option_names_a_model_a_server_or_an_address(self):
        for args in (["plan", "--model", "x"], ["plan", "--server", "x"], ["plan", "--address", "x"], ["run", "r", "--model", "x"],
                     ["run", "r", "--path", "x"], ["status", "r", "--server", "x"]):
            with self.subTest(args=args):
                self.assertEqual(self.kb("cards-queue", *args).returncode, 2)

    def test_the_exit_code_of_a_run_is_one_when_a_book_failed(self):
        self.books(2)
        self.set_plan(down_card={"Book 0": 99})
        run_id = json.loads(self.kb("cards-queue", "plan").stdout)["run"]
        ran = self.kb("cards-queue", "run", run_id)
        self.assertEqual(ran.returncode, 1)
        self.assertEqual(json.loads(ran.stdout)["counts"]["failed"], 1)
        self.assertIn("could not be carded", ran.stderr)

    def test_a_refusal_is_printed_and_the_exit_code_is_two(self):
        r = self.kb("cards-queue", "run", "nosuchrun")
        self.assertEqual(r.returncode, 2)
        self.assertIn("refused:", r.stderr)


if __name__ == "__main__":
    unittest.main()
