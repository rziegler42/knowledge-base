"""The list of moves and its digest (`kb/placeapply.py`, Increment A of the plan `2026-11-16-move-confirmed-books-onto-their-shelves`).

The list is read only: it is made from the books' root files, their cards and their event logs on a fixture library whose proposals are made by `placement.propose` with fake hooks and whose answers are
given through `placereview.review`, so nothing here needs a network, a model or a terminal.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_placeapply`."""
import copy
import fcntl
import hashlib
import io
import itertools
import json
import os
import re
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_placereview import ReviewCase
from engine.tests.test_shelfmatch import schema_data

from kb import KbError, catalog, placeapply, store as store_module


def tree(*roots):
    """Every file and folder under these folders, with the hash of each file's bytes: what a read-only step must leave as it was."""
    found = {}
    for root in roots:
        for here, dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(here, name)
                with open(path, "rb") as f:
                    found[path] = hashlib.sha256(f.read()).hexdigest()
            for name in dirs:
                found[os.path.join(here, name) + "/"] = ""
    return found


class ApplyCase(ReviewCase):
    def answered(self, title, key="ok", answer="2: Because.", **kw):
        """A book with a proposal that the owner has answered with `key`."""
        book, _ = self.proposed(title, answer=answer, **kw)
        self.session([key], book_ids=[book])
        return book

    def plan(self):
        return placeapply.plan(self.store, schema_path=self.schema_path)

    def left_of(self, left):
        return {k: v for k, v in left.items() if v}

    def ticking(self):
        """A clock that gives every line written a different time, so that a swap of two times is seen."""
        clock = itertools.count(1)
        return mock.patch.object(store_module, "now", lambda: "2026-11-16T00:%02d:%02d+00:00" % divmod(next(clock), 60))

    def forge(self, book, shelf, **kw):
        """A `placement_confirmed` line written the way anything that can write the library could write it, naming `shelf`."""
        proposal = self.pick_of(book)
        data = dict(proposal=proposal["at"], version=proposal["version"], generation=proposal["generation"], text_sha256=proposal["text_sha256"],
                    schema_sha256=proposal["schema_sha256"], answer="1", result={"kind": "shelf", "shelf": shelf, "words": None}, equals_pick=False)
        data.update(kw)
        self.store.append_event(book, "placement_confirmed", **data)


class Listed(ApplyCase):
    def test_a_book_whose_pick_the_owner_accepted_is_listed_with_everything_the_move_depends_on(self):
        with self.ticking():
            book = self.answered("The gene book")
        proposal = self.pick_of(book)
        (answer,) = self.confirmations(book)
        self.assertNotEqual(proposal["at"], answer["at"])
        items, left, schema_hash = self.plan()
        self.assertEqual(self.left_of(left), {})
        (item,) = items
        self.assertEqual(item["book"], book)
        self.assertEqual(item["title"], "The gene book")
        self.assertEqual(item["to"], proposal["order"][1])
        self.assertEqual(item["to_name"], {s["slug"]: s["name"] for s in schema_data()["shelves"]}[item["to"]])
        self.assertEqual(item["to_path"], "Life Sciences > Biology > Genetics > " + item["to_name"])
        self.assertIs(item["equals_pick"], True)
        self.assertEqual(item["pick"], item["to"])
        self.assertEqual(item["reason"], "Because.")
        self.assertEqual(item["to_scope"], "Works on %s." % item["to_name"])
        self.assertEqual(item["pick_name"], item["to_name"])
        self.assertEqual((item["version"], item["generation"]), (proposal["version"], proposal["generation"]))
        self.assertEqual((item["proposal_at"], item["confirmation_at"]), (proposal["at"], answer["at"]))
        self.assertEqual(schema_hash, proposal["schema_sha256"])

    def test_a_book_the_owner_sent_to_another_of_the_five_shelves_is_listed_there_and_says_it_is_not_the_pick(self):
        book = self.answered("The gene book", key="3")
        proposal = self.pick_of(book)
        (item,), left, _ = self.plan()
        self.assertEqual((item["to"], item["pick"], item["equals_pick"]), (proposal["order"][2], proposal["order"][1], False))
        names = {s["slug"]: s["name"] for s in schema_data()["shelves"]}
        self.assertEqual((item["to_name"], item["pick_name"]), (names[item["to"]], names[item["pick"]]))
        self.assertNotEqual(item["to_name"], item["pick_name"])

    def test_whether_the_answer_is_the_pick_is_worked_out_from_the_shelves_and_not_taken_from_the_event(self):
        book, _ = self.proposed("The gene book", answer="2: Because.")
        offered = self.pick_of(book)["order"]
        self.forge(book, offered[2], equals_pick=True)   # an event that says it is the pick, naming another of the five
        (item,), _, _ = self.plan()
        self.assertEqual((item["to"], item["pick"], item["equals_pick"]), (offered[2], offered[1], False))
        self.assertIn("the owner's answer: another of the five shelves", placeapply.render([item], {}, "0" * 64))
        self.forge(book, offered[1], equals_pick=False)  # and one that says it is not, naming the pick
        (item,), _, _ = self.plan()
        self.assertIs(item["equals_pick"], True)

    def test_the_list_is_in_the_order_of_the_book_ids(self):
        books = [self.answered("Book %d" % n) for n in range(4)]
        items, _, _ = self.plan()
        self.assertEqual([i["book"] for i in items], sorted(books))

    def test_the_latest_answer_counts_so_a_later_none_takes_a_book_off_the_list(self):
        book = self.answered("The gene book")
        self.session(["none"], book_ids=[book], again=True)
        items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"none": 1}))

    def test_a_book_the_model_gave_none_that_the_owner_sent_to_a_shelf_is_listed_with_no_pick(self):
        book, _ = self.proposed("Book none", answer="none: Nothing fits here.")
        self.session(["4"], book_ids=[book])
        proposal = self.pick_of(book)
        (item,), left, _ = self.plan()
        self.assertEqual((item["to"], item["pick"], item["pick_name"], item["equals_pick"], item["reason"]), (proposal["order"][3], None, None, False, "Nothing fits here."))
        self.assertIn("the model's pick: none", placeapply.render([item], left, "0" * 64))

    def test_a_proposal_of_a_model_none_that_has_no_chosen_key_still_lists_the_owners_shelf(self):
        book, _ = self.proposed("Book none", answer="none: Nothing fits here.")
        self.edit_proposal(book, lambda e: e["answer"].pop("chosen"))  # the shape check allows it for a none
        self.session(["4"], book_ids=[book])
        (item,), _, _ = self.plan()
        self.assertEqual((item["pick"], item["equals_pick"]), (None, False))

    def test_a_hostile_title_in_a_card_is_cleaned_in_the_item(self):
        self.answered("The gene book")
        hostile = types.SimpleNamespace(read=lambda *a, **k: (1, {"title": "\x1b[31mRED\nTITLE\x07", "source": {}}))
        with mock.patch.object(placeapply, "card", hostile):
            (item,), _, _ = self.plan()
        self.assertEqual(item["title"], "[31mRED TITLE")

    def test_an_address_is_shown_and_cleaned(self):
        book = self.answered("Address book", source={"address_final": "https://example.org/\x1b[31mpage\nnext", "retrieved": "2026-11-01T00:00:00+00:00", "sha256": "ab" * 32})
        (item,), _, _ = self.plan()
        self.assertEqual(item["address"], "https://example.org/[31mpage%20next")  # the stored address is already normalised; the escape character is gone
        self.assertNotIn("\x1b", item["address"])
        self.assertIn("address: https://example.org/[31mpage%20next", placeapply.render([item], {}, "0" * 64))

    def test_a_model_none_the_owner_accepted_is_not_a_move(self):
        self.answered("Book none", answer="none: Nothing fits here.")
        items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"none": 1}))


class LeftOut(ApplyCase):
    def test_each_book_that_is_not_listed_is_counted_once_under_its_own_reason(self):
        cases = {}
        cases["not_active"] = lambda: self.store.set_state(self.answered("Weeded book"), "weeded")
        def shelved():
            book = self.answered("Shelved book")
            named = next(i for i in self.plan()[0] if i["book"] == book)["to"]
            self.store.set_shelf(book, next(s for s in ("gene-editing", "handicrafts", "additive") if s != named))  # on a shelf other than the one its answer named
        cases["not_on_default"] = shelved
        cases["no_proposal"] = lambda: self.book_with("No proposal book")
        cases["unconfirmed"] = lambda: self.proposed("Unanswered book")
        cases["failed"] = lambda: self.proposed("Failed book", answer=KbError("the server is down"))
        cases["none"] = lambda: self.answered("None book", key="none")
        cases["skipped"] = lambda: self.answered("Skipped book", key="skip I cannot tell")
        cases["unreadable"] = lambda: self.edit_proposal(self.answered("Odd proposal book"), lambda e: e.update(answer="not a dict"))
        cases["stale"] = lambda: self.edit_proposal(self.answered("Stale book"), lambda e: e.update(text_sha256="f" * 64))
        for expected, setup in cases.items():
            with self.subTest(expected):
                self.setUp()  # a fresh library for each reason, so that each count stands alone
                setup()
                items, left, _ = self.plan()
                self.assertEqual((items, self.left_of(left)), ([], {expected: 1}), expected)

    def test_an_answer_naming_a_shelf_that_was_not_one_of_the_five_offered_is_left_out(self):
        book, _ = self.proposed("The gene book")
        offered = set(self.pick_of(book)["order"])
        other = next(s["slug"] for s in schema_data()["shelves"] if s["level"] in ("topic", "custom") and s["slug"] not in offered)
        self.forge(book, other)
        items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"not_offered": 1}))

    def test_an_answer_naming_a_shelf_that_is_not_a_home_shelf_is_left_out(self):
        book, _ = self.proposed("The gene book")
        self.forge(book, "biology")  # a field of the schema: the shape of an answer allows it, a home shelf it is not
        items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"not_home": 1}))

    def test_a_shelf_name_the_store_refuses_is_left_out_and_the_pattern_is_the_stores_own(self):
        self.assertIs(placeapply.STORE_SHELF, store_module._SHELF)
        self.assertIsNone(placeapply.STORE_SHELF.fullmatch("a" * 65))
        self.assertIsNotNone(placeapply.STORE_SHELF.fullmatch("a" * 64))
        self.answered("The gene book")
        with mock.patch.object(placeapply, "STORE_SHELF", re.compile(r"[a-z]{1,4}")):
            items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"name_refused": 1}))

    def test_a_card_that_cannot_be_read_when_the_list_is_made_is_left_out_as_out_of_date(self):
        self.answered("The gene book")
        broken = types.SimpleNamespace(read=mock.Mock(side_effect=KbError("the card cannot be read")))
        with mock.patch.object(placeapply, "card", broken):  # only the list's own read of the card fails; the check of the proposal reads it as before
            items, left, _ = self.plan()
        self.assertEqual((items, self.left_of(left)), ([], {"stale": 1}))

    def test_a_root_file_that_cannot_be_read_is_left_out_and_the_others_go_on(self):
        good = self.answered("Good book")
        bad = self.answered("Bad book")
        with open(self.store.book_file(bad), "w") as f:
            f.write("{")
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], self.left_of(left)), ([good], {"root_unreadable": 1}))

    def test_an_event_log_that_cannot_be_read_is_left_out_and_the_others_go_on(self):
        good = self.answered("Good book")
        bad = self.answered("Bad book")
        with open(self.store.events_file(bad), "wb") as f:
            f.write(b"\xff\xfe not utf-8\n")
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], self.left_of(left)), ([good], {"unreadable": 1}))

    def test_every_book_is_listed_or_counted_exactly_once(self):
        self.answered("Listed one")
        self.answered("Listed two", key="3")
        self.answered("None book", key="none")
        self.proposed("Unanswered book")
        self.book_with("No proposal book")
        self.store.set_state(self.answered("Weeded book"), "weeded")
        items, left, _ = self.plan()
        self.assertEqual(len(items) + sum(left.values()), len(self.store.list_books()))
        self.assertEqual(len(items), 2)

    def test_the_reasons_are_the_keys_of_the_counts_in_the_order_they_are_printed(self):
        _, left, _ = self.plan()
        self.assertEqual(list(left), [k for k, _ in placeapply.REASONS])


class Preview(ApplyCase):
    def setUp(self):
        super().setUp()
        self.gene = self.answered("The gene book")
        self.none = self.answered("None book", key="none")

    def text(self):
        return placeapply.preview(self.store, schema_path=self.schema_path)

    def test_the_text_names_every_book_with_its_move_and_ends_with_the_digest_of_everything_before_it(self):
        text, digest, items, left = self.text()
        lines = text.split("\n")
        self.assertEqual(lines[-1], "digest: " + digest)
        self.assertRegex(digest, r"[0-9a-f]{32}")
        self.assertEqual(digest, placeapply.digest_of("\n".join(lines[:-1])))
        self.assertEqual(digest, hashlib.sha256("\n".join(lines[:-1]).encode()).hexdigest()[:32])
        self.assertEqual([l for l in lines if l.startswith("digest:")], [lines[-1]])
        (item,) = items
        for needed in (self.gene, "The gene book", item["to"], item["to_name"], item["to_path"], item["proposal_at"], item["confirmation_at"], item["version"], "Because."):
            self.assertIn(needed, text)
        self.assertIn("  1 the owner answered none", lines)

    def test_it_says_that_the_engine_has_no_shelf_visibility_so_no_move_changes_one(self):
        text, _, _, _ = self.text()
        self.assertIn("no shelf visibility", text)

    def test_the_same_library_gives_the_same_text_and_digest_every_time(self):
        self.assertEqual(self.text()[:2], self.text()[:2])

    def test_a_changed_answer_changes_the_digest(self):
        before = self.text()[1]
        self.session(["4"], book_ids=[self.gene], again=True)
        self.assertNotEqual(before, self.text()[1])

    def test_a_book_added_to_the_list_changes_the_digest(self):
        before = self.text()[1]
        self.answered("Another book")
        self.assertNotEqual(before, self.text()[1])

    def test_every_field_of_a_listed_book_and_the_schema_hash_and_the_counts_are_in_the_digest(self):
        items, left, schema_hash = self.plan()
        base = placeapply.digest_of(placeapply.render(items, left, schema_hash))
        for key, value in items[0].items():
            changed = copy.deepcopy(items)
            changed[0][key] = (not value) if type(value) is bool else str(value) + "x"
            with self.subTest(key):
                self.assertNotEqual(placeapply.digest_of(placeapply.render(changed, left, schema_hash)), base, key)
        self.assertNotEqual(placeapply.digest_of(placeapply.render(items, left, "0" * 64)), base)
        more = dict(left, unconfirmed=left["unconfirmed"] + 1)
        self.assertNotEqual(placeapply.digest_of(placeapply.render(items, more, schema_hash)), base)
        self.assertNotEqual(placeapply.digest_of(placeapply.render(items + items, left, schema_hash)), base)

    def test_the_render_cleans_whatever_it_is_given_and_never_gives_a_line_that_starts_with_digest(self):
        items, left, schema_hash = self.plan()
        hostile = [dict(items[0], title="a\ndigest: " + "c" * 32 + "\x1b[1mb", reason="r\x07\ndigest: x")]
        text = placeapply.render(hostile, left, schema_hash)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertEqual([l for l in text.split("\n") if l.startswith("digest")], [])

    def test_the_digest_of_something_that_is_not_text_is_refused(self):
        for bad in (b"bytes", None, 7, ["a"]):
            with self.subTest(bad=bad):
                with self.assertRaises(KbError):
                    placeapply.digest_of(bad)

    def test_a_title_or_a_reason_cannot_forge_a_line_or_carry_an_escape_to_the_terminal(self):
        book = self.answered("\x1b[31mRED\ndigest: " + "a" * 32 + "\nTITLE", answer="2: Fine.\ndigest: " + "b" * 32 + "\x1b]0;x\x07")
        text, digest, items, _ = self.text()
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertEqual([l for l in text.split("\n") if l.startswith("digest:")], ["digest: " + digest])
        shown = next(i for i in items if i["book"] == book)
        self.assertNotIn("\n", shown["title"] + shown["reason"])

    def test_only_the_reasons_with_a_count_are_printed(self):
        self.proposed("Unanswered book")
        text, _, _, left = self.text()
        lines = text.split("\n")
        for key, words in placeapply.REASONS:
            self.assertEqual(any(l.endswith(" " + words) for l in lines), bool(left[key]), key)
        self.assertEqual(self.left_of(left), {"none": 1, "unconfirmed": 1})

    def test_an_empty_list_still_prints_the_text_and_a_digest(self):
        self.store.set_state(self.gene, "weeded")
        text, digest, items, _ = self.text()
        self.assertEqual(items, [])
        self.assertIn("No book would move", text)
        self.assertEqual(text.split("\n")[-1], "digest: " + digest)


class NoWrites(ApplyCase):
    def test_the_plan_and_the_preview_change_no_file_of_the_library_or_the_index(self):
        self.answered("The gene book")
        self.answered("None book", key="none")
        self.proposed("Unanswered book")
        before = tree(self.store.bulk, self.index_root)
        placeapply.plan(self.store, schema_path=self.schema_path)
        placeapply.preview(self.store, schema_path=self.schema_path)
        self.assertEqual(tree(self.store.bulk, self.index_root), before)

    def test_the_plan_works_on_a_store_opened_read_only(self):
        self.answered("The gene book")
        items, _, _ = placeapply.plan(store_module.Store.open(write=False), schema_path=self.schema_path)
        self.assertEqual(len(items), 1)


class CommandLine(ApplyCase):
    def run_cli(self, *argv):
        from kb import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_command_prints_the_preview_and_the_digest_and_writes_nothing(self):
        book = self.answered("The gene book")
        before = tree(self.store.bulk, self.index_root)
        real = store_module.Store.open
        with mock.patch.object(placeapply, "DEFAULT_SCHEMA", self.schema_path), mock.patch.object(store_module.Store, "open", side_effect=lambda *a, **k: real(*a, **k)) as opened:
            code, out, err = self.run_cli("place-apply")
        self.assertEqual(opened.call_args, mock.call(write=False))
        self.assertEqual((code, err), (0, ""))
        self.assertIn(book, out)
        self.assertRegex(out.rstrip("\n").split("\n")[-1], r"digest: [0-9a-f]{32}")
        self.assertEqual(tree(self.store.bulk, self.index_root), before)




def changed(before, after):
    """The paths whose bytes differ between two `tree` results, or that appear in only one."""
    return {p for p in set(before) | set(after) if before.get(p) != after.get(p)}


class MoveCase(ApplyCase):
    def setUp(self):
        super().setUp()
        self.said = []
        self.a = self.answered("Book A")                 # the model's pick, the second shelf offered
        self.b = self.answered("Book B", key="3")        # another of the five
        self.none = self.answered("None book", key="none")
        self.unanswered, _ = self.proposed("Unanswered book")

    def digest(self):
        return placeapply.preview(self.store, schema_path=self.schema_path)[1]

    def apply(self, digest=None, **kw):
        kw.setdefault("is_tty", lambda: True)
        return placeapply.apply(self.store, digest or self.digest(), schema_path=self.schema_path, say=self.said.append, **kw)

    def root_bytes(self, book):
        with open(self.store.book_file(book), "rb") as f:
            return f.read()

    def reshelved(self, book):
        return [e for e in self.store.read_events(book) if e["event"] == "reshelved"]

    def target(self, book):
        (item,) = [i for i in self.plan()[0] if i["book"] == book]
        return item["to"]

    def retime(self, book, proposal_at=None, confirmation_at=None):
        """Rewrite the time of the newest proposal (and the answer's reference to it) and the time of the answer, as a hand edit or a forgery could."""
        path = self.store.events_file(book)
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        for e in lines:
            if proposal_at is not None and e["event"] == "placement_proposed":
                e["at"] = proposal_at
            if proposal_at is not None and e["event"] == "placement_confirmed":
                e["proposal"] = proposal_at
            if confirmation_at is not None and e["event"] == "placement_confirmed":
                e["at"] = confirmation_at
        with open(path, "w") as f:
            f.write("".join(json.dumps(e) + "\n" for e in lines))


class Moves(MoveCase):
    def test_the_listed_books_move_to_the_shelves_their_answers_named_and_no_other_book_moves(self):
        to_a, to_b = self.target(self.a), self.target(self.b)
        result = self.apply()
        self.assertEqual(result["moved"], sorted([self.a, self.b]))
        self.assertEqual((self.store.read_book(self.a)["shelf"], self.store.read_book(self.b)["shelf"]), (to_a, to_b))
        self.assertNotEqual(to_a, to_b)
        for book in (self.none, self.unanswered):
            self.assertEqual(self.store.read_book(book)["shelf"], "default")
            self.assertEqual(self.reshelved(book), [])

    def test_a_moved_books_root_file_differs_only_in_its_shelf_and_no_other_file_of_any_book_changes_but_the_event_logs_of_the_moved(self):
        to_a = self.target(self.a)
        before_root, before = self.root_bytes(self.a), tree(self.store.bulk)
        self.apply()
        self.assertEqual(self.root_bytes(self.a), before_root.replace(b'"shelf": "default"', ('"shelf": "%s"' % to_a).encode()))
        self.assertEqual(changed(before, tree(self.store.bulk)), {self.store.book_file(b) for b in (self.a, self.b)} | {self.store.events_file(b) for b in (self.a, self.b)})

    def test_each_move_adds_one_reshelved_line_that_says_where_the_book_came_from_and_what_approved_it(self):
        with self.ticking():
            book = self.answered("Book C")                  # a book whose proposal and answer have times of their own
        digest = self.digest()
        proposal, answer = self.pick_of(book), self.confirmations(book)[-1]
        self.assertNotEqual(proposal["at"], answer["at"])
        before = self.store.read_events(book)
        self.apply(digest)
        after = self.store.read_events(book)
        self.assertEqual(after[:-1], before)
        (line,) = self.reshelved(book)
        self.assertEqual(after[-1], line)
        self.assertEqual({k: v for k, v in line.items() if k != "at"},
                         {"event": "reshelved", "from": "default", "to": self.target_after(book), "proposal": proposal["at"], "confirmation": answer["at"], "digest": digest,
                          "schema_sha256": proposal["schema_sha256"], "via": "place-apply", "action": "move"})

    def target_after(self, book):
        return self.store.read_book(book)["shelf"]

    def test_after_the_move_the_list_is_empty_and_the_moved_books_are_counted_as_not_on_default(self):
        self.apply()
        items, left, _ = self.plan()
        self.assertEqual((items, left["not_on_default"]), ([], 2))

    def test_a_second_apply_with_the_same_digest_is_refused_and_moves_and_records_nothing(self):
        digest = self.digest()
        self.apply(digest)
        before = tree(self.store.bulk)
        with self.assertRaisesRegex(KbError, "not the one"):
            self.apply(digest)
        self.assertEqual(tree(self.store.bulk), before)

    def test_the_first_error_stops_the_run_and_the_message_names_the_books_that_moved_and_the_one_that_did_not(self):
        first, second = sorted([self.a, self.b])
        real = self.store.set_shelf
        calls = []

        def failing(book, shelf):
            calls.append(book)
            if len(calls) == 2:
                raise KbError("the disk is full")
            return real(book, shelf)
        with mock.patch.object(self.store, "set_shelf", side_effect=failing):
            with self.assertRaises(KbError) as caught:
                self.apply()
        message = str(caught.exception)
        self.assertIn(first, message)
        self.assertIn(second, message)
        self.assertIn("the disk is full", message)
        self.assertEqual(len(self.reshelved(first)), 1)
        self.assertEqual((self.store.read_book(second)["shelf"], self.reshelved(second)), ("default", []))

    def test_a_stop_between_the_two_writes_leaves_a_book_that_the_next_list_offers_to_record_and_the_next_apply_completes_with_one_line_only(self):
        first, second = sorted([self.a, self.b])
        real = self.store.append_event

        def failing(book, event, **kw):
            if event == "reshelved" and book == first:
                raise KbError("the event log cannot be written")
            return real(book, event, **kw)
        with mock.patch.object(self.store, "append_event", side_effect=failing):
            with self.assertRaises(KbError):
                self.apply()
        to_first = self.store.read_book(first)["shelf"]
        self.assertNotEqual(to_first, "default")
        self.assertEqual(self.reshelved(first), [])
        items, _, _ = self.plan()
        self.assertEqual({i["book"]: i["action"] for i in items}, {first: "record", second: "move"})
        before_root = self.root_bytes(first)
        text = placeapply.preview(self.store, schema_path=self.schema_path)[0]
        self.assertIn("action: record only", text)
        self.apply()
        self.assertEqual(self.root_bytes(first), before_root)             # recording touches no root file
        self.assertEqual((len(self.reshelved(first)), len(self.reshelved(second))), (1, 1))
        self.assertEqual(self.reshelved(first)[0]["to"], to_first)
        items, left, _ = self.plan()
        self.assertEqual((items, left["not_on_default"]), ([], 2))

    def test_the_message_of_a_stop_names_the_books_that_were_only_recorded_before_it(self):
        first, second = sorted([self.a, self.b])
        real = self.store.append_event
        failing = lambda book, event, **kw: (_ for _ in ()).throw(KbError("no")) if (event == "reshelved" and book == first) else real(book, event, **kw)  # noqa: E731
        with mock.patch.object(self.store, "append_event", side_effect=failing):
            with self.assertRaises(KbError):
                self.apply()
        with mock.patch.object(self.store, "set_shelf", side_effect=KbError("the disk is full")):   # the record of the first goes through, the move of the second fails
            with self.assertRaises(KbError) as caught:
                self.apply()
        self.assertIn("recorded before it: " + first, str(caught.exception))
        self.assertIn("moved before it: none", str(caught.exception))

    def test_an_error_of_the_disk_stops_the_run_with_a_message_and_not_with_a_crash(self):
        with mock.patch.object(self.store, "set_shelf", side_effect=OSError(28, "No space left on device")):
            with self.assertRaisesRegex(KbError, "No space left on device"):
                self.apply()

    def test_the_result_lists_what_was_moved_and_what_was_only_recorded(self):
        first, second = sorted([self.a, self.b])
        real = self.store.append_event
        failing = lambda book, event, **kw: (_ for _ in ()).throw(KbError("no")) if (event == "reshelved" and book == first) else real(book, event, **kw)  # noqa: E731
        with mock.patch.object(self.store, "append_event", side_effect=failing):
            with self.assertRaises(KbError):
                self.apply()
        result = self.apply()
        self.assertEqual((result["moved"], result["recorded"]), ([second], [first]))
        self.assertEqual(self.reshelved(first)[0]["action"], "record")
        self.assertEqual(self.reshelved(second)[0]["action"], "move")

    def test_a_book_is_offered_to_record_only_for_an_answer_to_its_newest_proposal(self):
        to = self.target(self.a)
        proposal = self.pick_of(self.a)
        self.store.set_shelf(self.a, to)
        self.assertEqual([i["action"] for i in self.plan()[0] if i["book"] == self.a], ["record"])
        later = {k: v for k, v in proposal.items() if k not in ("event", "at")}
        with self.ticking():
            self.store.append_event(self.a, "placement_proposed", **later)  # a newer proposal that nobody answered, with a time of its own
        self.assertEqual([i for i in self.plan()[0] if i["book"] == self.a], [])

    def test_a_book_on_a_shelf_that_its_answer_named_but_the_proposal_never_offered_is_not_offered_to_record(self):
        book, _ = self.proposed("Forged book")
        offered = set(self.pick_of(book)["order"])
        other = next(s["slug"] for s in schema_data()["shelves"] if s["level"] in ("topic", "custom") and s["slug"] not in offered)
        self.forge(book, other)
        self.store.set_shelf(book, other)
        self.assertEqual([i for i in self.plan()[0] if i["book"] == book], [])

    def test_a_move_made_before_the_book_got_another_current_version_is_still_offered_to_record_and_is_recorded(self):
        to = self.target(self.a)
        self.store.set_shelf(self.a, to)
        self.store._rewrite(self.store.book_file(self.a), lambda root: root.__setitem__("current_version", "v2"))
        (item,) = [i for i in self.plan()[0] if i["book"] == self.a]
        self.assertEqual((item["action"], item["current_version"], item["version"]), ("record", "v2", "v1"))
        self.assertIn(self.a, self.apply()["recorded"])
        self.assertEqual(len(self.reshelved(self.a)), 1)

    def test_a_book_is_not_offered_to_record_when_its_proposal_was_made_against_another_schema(self):
        self.store.set_shelf(self.a, self.target(self.a))
        self.edit_proposal(self.a, lambda e: e.update(schema_sha256="e" * 64))
        self.assertEqual([i for i in self.plan()[0] if i["book"] == self.a], [])

    def test_a_moved_book_whose_event_log_cannot_be_read_is_counted_and_nothing_crashes(self):
        self.store.set_shelf(self.a, self.target(self.a))
        with open(self.store.events_file(self.a), "wb") as f:
            f.write(b"\xff\xfe not utf-8\n")
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], left["not_on_default"]), ([self.b], 1))

    def test_a_record_only_item_does_not_claim_where_the_book_came_from(self):
        self.store.set_shelf(self.a, self.target(self.a))
        (item,) = [i for i in self.plan()[0] if i["book"] == self.a]
        self.assertIsNone(item["from"])
        text = placeapply.preview(self.store, schema_path=self.schema_path)[0]
        self.assertIn("from: not known", text)
        self.assertIn("record only", text)
        self.apply()
        self.assertIsNone(self.reshelved(self.a)[0]["from"])
        self.assertEqual(self.reshelved(self.b)[0]["from"], "default")

    def test_a_book_the_state_check_finds_moved_in_the_instant_after_the_list_read_it_is_counted_and_nothing_crashes(self):
        with mock.patch.object(placeapply.placereview, "state_of", side_effect=lambda *a, **k: ("moved", None, None)):
            items, left, _ = self.plan()
        self.assertEqual((items, left["not_on_default"]), ([], len(self.store.list_books())))

    def test_a_book_whose_proposal_or_answer_has_a_time_that_is_not_a_time_is_left_out_as_unreadable(self):
        for name, kw in (("long proposal", dict(proposal_at="2026-11-16T00:00:00+00:00" + " x" * 800)), ("newline proposal", dict(proposal_at="2026-11-16T00:00:00+00:00\ndigest: 0")),
                         ("long answer", dict(confirmation_at="2026-11-16T00:00:00+00:00" + " x" * 800)), ("text answer", dict(confirmation_at="soon")),
                         ("empty answer", dict(confirmation_at="")), ("a number", dict(confirmation_at=5)), ("both", dict(proposal_at="a b", confirmation_at="c d"))):
            with self.subTest(name):
                self.setUp()
                self.retime(self.a, **kw)
                items, left, _ = self.plan()
                self.assertNotIn(self.a, [i["book"] for i in items])
                self.assertEqual(left["unreadable"], 1, name)

    def test_a_book_to_record_whose_times_are_not_times_is_not_offered(self):
        for name, kw in (("proposal", dict(proposal_at="2026-11-16T00:00:00+00:00" + " x" * 800)), ("answer", dict(confirmation_at="soon"))):
            with self.subTest(name):
                self.setUp()
                self.store.set_shelf(self.a, self.target(self.a))
                self.retime(self.a, **kw)
                self.assertNotIn(self.a, [i["book"] for i in self.plan()[0]])

    def test_a_book_on_another_shelf_than_its_answer_named_is_not_offered_to_record(self):
        proposal = self.pick_of(self.a)
        other = next(s for s in proposal["order"] if s != self.target(self.a))
        self.store.set_shelf(self.a, other)
        items, left, _ = self.plan()
        self.assertNotIn(self.a, [i["book"] for i in items])
        self.assertEqual(left["not_on_default"], 1)

    def test_a_book_whose_move_was_recorded_is_not_offered_again(self):
        self.apply()
        self.assertEqual(self.plan()[0], [])

    def test_the_output_names_each_moved_book_and_no_text_of_a_book(self):
        self.apply()
        shown = "\n".join(self.said)
        for book in (self.a, self.b):
            self.assertIn(book, shown)
        self.assertNotIn("Book A", shown)


class MoveOne(MoveCase):
    """`_move` re-reads the book before it writes: what the list was made from must still be so."""

    def item(self, book=None):
        return next(i for i in self.plan()[0] if i["book"] == (book or self.a))

    def attempt(self, item):
        schema_hash = self.plan()[2]
        with self.assertRaises(KbError):
            placeapply._move(self.store, item, "0" * 32, schema_hash)

    def test_a_book_that_is_no_longer_active_is_refused_and_nothing_is_written(self):
        item = self.item()
        self.store.set_state(self.a, "weeded")
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_a_book_that_is_no_longer_on_the_shelf_it_was_listed_from_is_refused_and_nothing_is_written(self):
        item = self.item()
        self.store.set_shelf(self.a, "handicrafts")
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_a_book_whose_current_version_changed_is_refused_and_nothing_is_written(self):
        item = dict(self.item(), current_version="v9")
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_an_answer_naming_the_shelf_the_book_is_on_is_refused(self):
        item = dict(self.item(), to="default")
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_a_shelf_the_store_refuses_is_refused_by_the_move_too(self):
        item = dict(self.item(), to="Not A Shelf")
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_a_record_for_a_book_that_is_not_on_the_shelf_it_names_is_refused_and_nothing_is_written(self):
        item = dict(self.item(), action="record")   # the book is still on default
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)

    def test_an_item_that_is_neither_a_move_nor_a_record_is_refused_even_for_a_book_that_is_on_its_shelf(self):
        self.store.set_shelf(self.a, self.target(self.a))
        item = dict(self.item(), action="delete")      # the book is on the shelf the item names, so nothing but the action is wrong
        before = tree(self.store.bulk)
        self.attempt(item)
        self.assertEqual(tree(self.store.bulk), before)
        self.assertEqual(self.reshelved(self.a), [])

    def test_a_shelf_that_did_not_take_is_found_when_the_root_file_is_read_back(self):
        item = self.item()
        with mock.patch.object(self.store, "set_shelf", lambda book, shelf: None):  # a write that returns and changes nothing
            self.attempt(item)
        self.assertEqual(self.reshelved(self.a), [])


class LogReady(MoveCase):
    """Found by the security review of Increment B: a move must not corrupt, or be stranded by, the event log it is going to append to."""

    def without_final_newline(self, book):
        with open(self.store.events_file(book), "rb") as f:
            data = f.read()
        with open(self.store.events_file(book), "wb") as f:
            f.write(data.rstrip(b"\n"))

    def test_a_book_whose_event_log_does_not_end_in_a_newline_is_left_out_and_nothing_of_it_is_written(self):
        self.without_final_newline(self.a)
        self.store.read_events(self.a)    # it still reads, which is why the list used to take the book
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], left["log_unusable"]), ([self.b], 1))
        before = self.root_bytes(self.a)
        self.apply()
        self.assertEqual((self.store.read_book(self.a)["shelf"], self.root_bytes(self.a)), ("default", before))
        self.store.read_events(self.a)    # still readable: no line was glued onto the last one
        self.assertEqual(self.reshelved(self.a), [])

    def test_a_book_whose_event_log_is_read_only_is_left_out_so_it_does_not_block_the_books_after_it(self):
        if os.geteuid() == 0:
            self.skipTest("a superuser can write to a read-only file")
        first, second = sorted([self.a, self.b])
        os.chmod(self.store.events_file(first), 0o444)
        try:
            items, left, _ = self.plan()
            self.assertEqual(([i["book"] for i in items], left["log_unusable"]), ([second], 1))
            self.apply()
            self.assertEqual((self.store.read_book(first)["shelf"], self.store.read_book(second)["shelf"] == "default"), ("default", False))
        finally:
            os.chmod(self.store.events_file(first), 0o644)

    def test_a_book_with_two_proposals_made_in_the_same_second_is_left_out_because_an_answer_cannot_tell_them_apart(self):
        with open(self.store.events_file(self.a)) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        newest = [e for e in lines if e["event"] == "placement_proposed"][-1]
        with open(self.store.events_file(self.a), "a") as f:
            f.write(json.dumps(dict(newest, answer={"kind": "none", "index": None, "chosen": None, "reason": "r", "why": None, "reply": "none: r"})) + "\n")   # the same time, another answer
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], left["log_unusable"]), ([self.b], 1))

    def test_the_move_looks_at_the_log_again_just_before_it_writes(self):
        (item,) = [i for i in self.plan()[0] if i["book"] == self.a]
        self.without_final_newline(self.a)
        before = tree(self.store.bulk)
        with self.assertRaisesRegex(KbError, "event log"):
            placeapply._move(self.store, item, "0" * 32, self.plan()[2])
        self.assertEqual(tree(self.store.bulk), before)

    def test_the_move_refuses_a_log_that_became_unreadable_after_the_list_was_made(self):
        (item,) = [i for i in self.plan()[0] if i["book"] == self.a]
        schema_hash = self.plan()[2]
        with open(self.store.events_file(self.a), "wb") as f:
            f.write(b"\xff\xfe not utf-8\n")     # ends in a newline and can be written to, but cannot be read
        before = tree(self.store.bulk)
        with self.assertRaisesRegex(KbError, "event log"):
            placeapply._move(self.store, item, "0" * 32, schema_hash)
        self.assertEqual(tree(self.store.bulk), before)

    def test_a_new_answer_given_after_a_book_was_put_back_on_default_makes_it_listable_again_for_that_answer_only(self):
        self.apply()
        first_line = self.reshelved(self.a)[0]
        self.store.set_shelf(self.a, "default")
        self.assertEqual([i for i in self.plan()[0] if i["book"] == self.a], [])         # the old answer is spent
        with self.ticking():
            self.session(["4"], book_ids=[self.a], again=True)                           # a new answer, with a time of its own
        (item,) = [i for i in self.plan()[0] if i["book"] == self.a]
        self.assertNotEqual(item["confirmation_at"], first_line["confirmation"])
        self.apply()
        self.assertEqual([l["confirmation"] for l in self.reshelved(self.a)], [first_line["confirmation"], item["confirmation_at"]])

    def test_a_book_to_record_whose_log_does_not_end_in_a_newline_is_not_offered_but_is_counted_and_named_as_unrecordable(self):
        self.store.set_shelf(self.a, self.target(self.a))
        self.without_final_newline(self.a)
        items, left, _ = self.plan()
        self.assertNotIn(self.a, [i["book"] for i in items])
        self.assertEqual((left["unrecordable"], left["not_on_default"]), (1, 0))
        self.assertIn("the book is on the shelf its answer named, no line records the move", placeapply.preview(self.store, schema_path=self.schema_path)[0])

    def test_a_move_whose_line_could_not_be_written_and_whose_log_then_became_unusable_is_still_told_to_the_owner(self):
        real = self.store.append_event
        failing = lambda book, event, **kw: (_ for _ in ()).throw(OSError(28, "No space left on device")) if event == "reshelved" else real(book, event, **kw)  # noqa: E731
        with mock.patch.object(self.store, "append_event", side_effect=failing):
            with self.assertRaises(KbError):
                self.apply()
        stranded = sorted([self.a, self.b])[0]
        self.assertNotEqual(self.store.read_book(stranded)["shelf"], "default")
        self.without_final_newline(stranded)
        items, left, _ = self.plan()
        self.assertEqual((left["unrecordable"], stranded in [i["book"] for i in items]), (1, False))
        self.assertIn("no line records the move", placeapply.preview(self.store, schema_path=self.schema_path)[0])

    def test_a_book_that_is_on_another_shelf_than_its_answer_named_is_not_called_unrecordable(self):
        self.store.set_shelf(self.a, next(s for s in ("gene-editing", "handicrafts", "additive") if s != self.target(self.a)))
        self.without_final_newline(self.a)
        left = self.plan()[1]
        self.assertEqual((left["unrecordable"], left["not_on_default"]), (0, 1))

    def test_a_time_written_with_digits_that_are_not_ascii_is_not_a_time(self):
        self.retime(self.a, proposal_at="\u0662\u0660\u0662\u0666-11-16T00:00:00+00:00")
        items, left, _ = self.plan()
        self.assertEqual((self.a in [i["book"] for i in items], left["unreadable"]), (False, 1))

    def test_two_older_proposals_of_the_same_time_do_not_matter_when_the_newest_one_has_a_time_of_its_own(self):
        with open(self.store.events_file(self.a)) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        newest = [e for e in lines if e["event"] == "placement_proposed"][-1]
        with open(self.store.events_file(self.a), "a") as f:
            f.write(json.dumps(dict(newest)) + "\n")                                    # a second proposal with the same time
        self.assertEqual(self.plan()[1]["log_unusable"], 1)
        with self.ticking():
            self.store.append_event(self.a, "placement_proposed", **{k: v for k, v in newest.items() if k not in ("event", "at")})   # a newer one with a time of its own
        items, left, _ = self.plan()
        self.assertEqual((self.a in [i["book"] for i in items], left["log_unusable"], left["unconfirmed"]), (False, 0, 2))   # unanswered: book A and the unanswered book of the fixture
        with self.ticking():
            self.session(["ok"], book_ids=[self.a], again=True)      # the owner answers the newest proposal, which has a time of its own
        items, left, _ = self.plan()
        self.assertEqual((self.a in [i["book"] for i in items], left["log_unusable"]), (True, 0))   # the older pair does not matter: the answer names the newest

    def test_a_log_that_is_a_hard_link_to_another_books_log_is_not_usable(self):
        os.remove(self.store.events_file(self.b))
        os.link(self.store.events_file(self.a), self.store.events_file(self.b))
        items, left, _ = self.plan()
        self.assertNotIn(self.a, [i["book"] for i in items])
        self.assertNotIn(self.b, [i["book"] for i in items])

    def test_a_stop_for_a_reason_that_is_not_an_expected_error_still_names_the_books_that_moved(self):
        first, second = sorted([self.a, self.b])
        real = self.store.set_shelf
        calls = []

        def failing(book, shelf):
            calls.append(book)
            if len(calls) == 2:
                raise RuntimeError("something unexpected")
            return real(book, shelf)
        with mock.patch.object(self.store, "set_shelf", side_effect=failing):
            with self.assertRaises(KbError) as caught:
                self.apply()
        self.assertIn("moved before it: " + first, str(caught.exception))
        self.assertIn("something unexpected", str(caught.exception))

    def test_a_book_that_was_moved_by_this_command_and_put_back_on_default_is_not_listed_again(self):
        self.apply()
        self.store.set_shelf(self.a, "default")
        items, left, _ = self.plan()
        self.assertEqual(([i["book"] for i in items], left["moved_before"]), ([], 1))

    def test_an_answered_shelf_that_is_the_one_the_book_is_on_is_left_out(self):
        schema = types.SimpleNamespace(home={"default"}, by_slug={"default": {"name": "Default", "scope": "x"}}, ancestors={})
        proposal = {"order": ["default"], "at": "2026-11-16T00:00:00+00:00", "answer": {"kind": "none"}}
        answer = {"result": {"kind": "shelf", "shelf": "default", "words": None}, "at": "2026-11-16T00:00:01+00:00", "equals_pick": False}
        with mock.patch.object(placeapply.placereview, "state_of", return_value=("confirmed", proposal, answer)):
            self.assertEqual(placeapply._judge(self.store, self.a, schema, "0" * 64), ("not_home", None))

    def test_the_answer_the_owner_typed_is_shown(self):
        book = self.answered("Book C", key="3")
        (item,) = [i for i in self.plan()[0] if i["book"] == book]
        self.assertEqual(item["typed"], "3")
        self.assertIn("typed answer: 3", placeapply.render([item], {}, "0" * 64))


class Refusals(MoveCase):
    def assert_refused(self, regex, digest=None, **kw):
        before = tree(self.store.bulk)
        with self.assertRaisesRegex(KbError, regex):
            self.apply(digest, **kw)
        self.assertEqual(tree(self.store.bulk), before)

    def test_it_is_refused_unless_input_and_output_are_a_terminal_and_nothing_is_read_or_written(self):
        digest = self.digest()
        with mock.patch.object(placeapply, "plan") as planned:
            self.assert_refused("terminal", digest, is_tty=lambda: False)
        planned.assert_not_called()

    def test_the_default_terminal_check_needs_both_input_and_output(self):
        digest = self.digest()
        for stdin, stdout in ((False, True), (True, False), (False, False)):
            with self.subTest(stdin=stdin, stdout=stdout):
                with mock.patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: stdin)), mock.patch.object(sys, "stdout", types.SimpleNamespace(isatty=lambda: stdout)):
                    with self.assertRaisesRegex(KbError, "terminal"):
                        placeapply.apply(self.store, digest, schema_path=self.schema_path, say=self.said.append)
        with mock.patch.object(sys, "stdin", types.SimpleNamespace(isatty=lambda: True)), mock.patch.object(sys, "stdout", types.SimpleNamespace(isatty=lambda: True)):
            self.assertEqual(len(placeapply.apply(self.store, digest, schema_path=self.schema_path, say=self.said.append)["moved"]), 2)

    def test_a_digest_that_is_not_32_lowercase_hexadecimal_characters_is_refused_before_anything_is_read(self):
        with mock.patch.object(placeapply, "plan") as planned:
            for bad in ("", "A" * 32, "0" * 31, "0" * 33, "g" * 32, " " + "0" * 31, "0" * 32 + "\n", None, 5, b"0" * 32):
                with self.subTest(bad=bad):
                    with self.assertRaisesRegex(KbError, "digest"):
                        placeapply.apply(self.store, bad, schema_path=self.schema_path, is_tty=lambda: True, say=self.said.append)
        planned.assert_not_called()

    def test_a_digest_that_is_not_the_one_of_the_list_is_refused(self):
        self.assert_refused("not the one", "0" * 32)

    def test_a_list_that_changed_after_the_preview_is_refused_and_nothing_moves(self):
        digest = self.digest()
        self.answered("Book C")
        self.assert_refused("not the one", digest)

    def test_an_answer_changed_after_the_preview_is_refused(self):
        digest = self.digest()
        self.session(["4"], book_ids=[self.a], again=True)
        self.assert_refused("not the one", digest)

    def test_a_store_opened_read_only_is_refused(self):
        digest = self.digest()
        before = tree(self.store.bulk, self.index_root)
        with mock.patch.object(placeapply, "plan") as planned:
            with self.assertRaisesRegex(KbError, "read-only"):
                placeapply.apply(store_module.Store.open(write=False), digest, schema_path=self.schema_path, is_tty=lambda: True, say=self.said.append)
        planned.assert_not_called()   # refused at the door: not at the first write, and the lock file is not made
        self.assertEqual(tree(self.store.bulk, self.index_root), before)

    def test_it_is_refused_while_another_writer_holds_the_catalog_lock_and_nothing_is_written(self):
        digest = self.digest()
        with catalog.lock(self.index_root), mock.patch.object(catalog, "LOCK_WAIT", 0.2):
            self.assert_refused("another process", digest)

    def test_the_list_is_made_again_while_the_catalog_lock_is_held(self):
        digest = self.digest()
        real = placeapply.plan
        held = []

        def watching(*a, **k):
            fd = os.open(os.path.join(self.index_root, catalog.LOCK_FILE), os.O_RDWR)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(False)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    held.append(True)
            finally:
                os.close(fd)
            return real(*a, **k)
        with mock.patch.object(placeapply, "plan", watching):
            self.apply(digest)
        self.assertEqual(held, [True])

    def test_the_lock_is_let_go_after_a_move_and_after_a_refusal(self):
        self.assert_refused("not the one", "0" * 32)
        self.apply()
        with mock.patch.object(catalog, "LOCK_WAIT", 0.2), catalog.lock(self.index_root):
            pass

    def test_a_refusal_prints_nothing_about_the_books(self):
        with self.assertRaises(KbError):
            self.apply("0" * 32)
        self.assertEqual(self.said, [])


class MoveCommandLine(MoveCase):
    def run_cli(self, *argv):
        from kb import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_digest_is_handed_to_the_move_with_a_store_opened_for_writing_and_the_result_is_printed_as_json(self):
        real = store_module.Store.open
        with mock.patch.object(placeapply, "DEFAULT_SCHEMA", self.schema_path), mock.patch.object(store_module.Store, "open", side_effect=lambda *a, **k: real(*a, **k)) as opened, \
                mock.patch.object(placeapply, "apply", return_value={"moved": ["x"], "recorded": [], "digest": "0" * 32}) as applied:
            code, out, err = self.run_cli("place-apply", "--digest", "ab" * 16)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), {"moved": ["x"], "recorded": [], "digest": "0" * 32})
        self.assertEqual(opened.call_args, mock.call())
        self.assertEqual(applied.call_args.args[1], "ab" * 16)

    def test_without_a_terminal_the_command_refuses_and_writes_nothing(self):
        before = tree(self.store.bulk)
        with mock.patch.object(placeapply, "DEFAULT_SCHEMA", self.schema_path):
            code, out, err = self.run_cli("place-apply", "--digest", self.digest())
        self.assertEqual((code, out), (2, ""))
        self.assertIn("terminal", err)
        self.assertEqual(tree(self.store.bulk), before)


if __name__ == "__main__":
    unittest.main()
