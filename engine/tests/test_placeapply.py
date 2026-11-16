"""The list of moves and its digest (`kb/placeapply.py`, Increment A of the plan `2026-11-16-move-confirmed-books-onto-their-shelves`).

The list is read only: it is made from the books' root files, their cards and their event logs on a fixture library whose proposals are made by `placement.propose` with fake hooks and whose answers are
given through `placereview.review`, so nothing here needs a network, a model or a terminal.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_placeapply`."""
import copy
import hashlib
import io
import itertools
import os
import re
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_placereview import ReviewCase
from engine.tests.test_shelfmatch import schema_data

from kb import KbError, placeapply, store as store_module


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
        cases["not_on_default"] = lambda: self.store.set_shelf(self.answered("Shelved book"), "gene-editing")
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

    def test_a_digest_is_refused_for_now_and_nothing_is_written(self):
        self.answered("The gene book")
        before = tree(self.store.bulk, self.index_root)
        with mock.patch.object(placeapply, "DEFAULT_SCHEMA", self.schema_path):
            code, out, err = self.run_cli("place-apply", "--digest", "0" * 32)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not built", err)
        self.assertEqual(tree(self.store.bulk, self.index_root), before)


if __name__ == "__main__":
    unittest.main()
