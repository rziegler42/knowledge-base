"""Giving the themes already made the flags of the rule now in force, with no call to a model (`themes-reflag`)."""
import contextlib
import copy
import io
import json
import os
import unittest
import unittest.mock

from engine.tests.test_themecheck import config, verdicts
from engine.tests.test_themeextract import Fake, VersionCase, row, values

from kb import KbError, card, cardstate, convert, models, theme, themecheck, themejournal, themereflag
from kb import __main__ as kbmain
from kb import config as kbconfig

# The library, as the flag counts it: "stopping" (a topic of the card) is held by a third of the books, "annealing" (the title) by one.
DF = ({"stopping": 10, "annealing": 1, "bandits": 1, "paper": 1, "search": 1}, 30)
OLD_STOPPING = {"kind": "field_words", "detail": "stopping"}
OLD_ANNEALING = {"kind": "field_words", "detail": "annealing"}
UNREADABLE = {"kind": "confidence_unreadable", "detail": "unsure"}


class ReflagCase(VersionCase):
    def setUp(self):
        super().setUp()
        patch = unittest.mock.patch.object(themecheck, "library_frequencies", return_value=DF)
        patch.start()
        self.addCleanup(patch.stop)

    def index_root(self):
        return self.store.cfg["index_root"]

    def book(self, problem, flags, file=True):
        """A book with a card and a conversion, and a generation of one theme whose description says `problem` and whose flags are `flags`."""
        book, version = self.converted_book()
        if file:
            fake = Fake(values(row(problem=problem)), verdicts("supports", "supports", "supports", "supports"))
            with unittest.mock.patch.object(models, "run_job", fake):
                got = themecheck.make_and_check_for_version(self.store, config(), book, version, frequencies=({}, 1000))
            themes = got["generation"]["themes"]
            for t in themes:
                t["flags"] = copy.deepcopy(flags)
            theme.file(self.store, theme.make(book, version, themes))
        return book, version

    def newest(self, book):
        version = self.store.read_book(book)["current_version"]
        return theme.read(self.store, book, version)

    def generations(self, book):
        return theme.generations(self.store, book, self.store.read_book(book)["current_version"])

    def library(self):
        """A, C and E are to change; B and D are not."""
        a = self.book("finding the stopping rule", [OLD_STOPPING])[0]               # the word is held by many books: the flag goes
        b = self.book("finding the stopping rule", [])[0]                           # no flag now and none by the rule
        c = self.book("an annealing schedule choice", [])[0]                        # a word that one book holds: the flag comes
        d = self.book("an annealing schedule choice", [UNREADABLE, OLD_ANNEALING])[0]   # the flags are the ones the rule gives
        e = self.book("finding the stopping rule", [UNREADABLE, OLD_STOPPING])[0]   # the flag goes and the other flag stays
        return a, b, c, d, e

    def snapshot(self):
        out = {}
        for root in {self.index_root(), self.store.bulk}:
            for folder, _, names in os.walk(root):
                for n in names:
                    p = os.path.join(folder, n)
                    out[p] = (os.path.getmtime(p), os.path.getsize(p))
        return out


class PlanTest(ReflagCase):
    def test_the_plan_counts_the_books_to_change_and_the_themes_flagged_before_and_after(self):
        a, b, c, d, e = self.library()
        got = themereflag.plan(self.store)
        self.assertEqual([x["book_id"] for x in got["to_change"]], sorted([a, c, e]))
        self.assertEqual(got["books"], 3)
        self.assertEqual(got["unchanged"], 2)
        self.assertEqual(got["left_out"], [])
        self.assertEqual((got["themes"], got["flagged_before"], got["flagged_after"]), (5, 3, 2))
        by = {x["book_id"]: x for x in got["to_change"]}
        self.assertEqual((by[a]["flagged_before"], by[a]["flagged_after"]), (1, 0))
        self.assertEqual((by[c]["flagged_before"], by[c]["flagged_after"]), (0, 1))
        self.assertEqual((by[e]["flagged_before"], by[e]["flagged_after"]), (1, 0))   # confidence_unreadable is not a field flag
        self.assertEqual(by[a]["title"], "A paper on annealing")
        self.assertEqual(got["share"], themecheck.FLAG_SHARE)

    def test_the_plan_writes_nothing_and_sends_nothing(self):
        self.library()
        before = self.snapshot()
        self.assertTrue(any(p.endswith(theme.FILENAME) for p in before))   # the snapshot sees the generations
        with unittest.mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")):
            themereflag.plan(self.store)
        self.assertEqual(self.snapshot(), before)

    def test_a_book_that_is_left_out_is_named_with_the_reason(self):
        a, *_ = self.library()
        inactive = self.book("finding the stopping rule", [OLD_STOPPING])[0]
        self.store.set_state(inactive, "weeded")
        no_themes = self.book("x", [], file=False)[0]
        no_card = self.book("finding the stopping rule", [OLD_STOPPING])[0]
        no_conversion = self.book("finding the stopping rule", [OLD_STOPPING])[0]
        real_card, real_load = card.read, convert.load_in_use

        def card_read(store, book_id, *args, **kw):
            if book_id == no_card:
                raise KbError("no card")
            return real_card(store, book_id, *args, **kw)

        def load(store, book_id, *args, **kw):
            return None if book_id == no_conversion else real_load(store, book_id, *args, **kw)

        with unittest.mock.patch.object(card, "read", card_read), unittest.mock.patch.object(convert, "load_in_use", load):
            got = themereflag.plan(self.store)
        left = {x["book_id"]: x["reason"] for x in got["left_out"]}
        self.assertEqual(left, {inactive: "inactive", no_themes: "no_themes", no_card: "no_card", no_conversion: "no_conversion"})
        self.assertEqual(got["left_out_counts"], {"inactive": 1, "no_themes": 1, "no_card": 1, "no_conversion": 1})
        self.assertIn(a, [x["book_id"] for x in got["to_change"]])
        self.assertTrue(all(len(x["title"]) <= 80 for x in got["left_out"]))

    def test_the_themes_of_a_book_are_counted_one_by_one(self):
        book, version = self.converted_book()
        fake = Fake(values(row(problem="finding the stopping rule"), row(title="A second theme", blocks="4", problem="an annealing schedule choice")),
                    verdicts("supports", "supports", "supports", "supports"), verdicts("supports", "supports", "supports", "supports"))
        with unittest.mock.patch.object(models, "run_job", fake):
            got = themecheck.make_and_check_for_version(self.store, config(), book, version, frequencies=({}, 1000))
        themes = got["generation"]["themes"]
        themes[0]["flags"] = [OLD_STOPPING]
        theme.file(self.store, theme.make(book, version, themes))
        got = themereflag.plan(self.store)
        self.assertEqual((got["themes"], got["flagged_before"], got["flagged_after"]), (2, 2, 1))   # the first loses its flag and the second keeps the one it has
        self.assertEqual((got["to_change"][0]["themes"], got["to_change"][0]["flagged_before"], got["to_change"][0]["flagged_after"]), (2, 2, 1))

    def test_a_title_that_is_long_or_has_a_tab_is_cleaned_and_cut_in_the_plan(self):
        self.store.create_book(title="Long " + "word " * 40, kind="preprint")
        self.store.create_book(title="Tab\there", kind="preprint")
        titles = [x["title"] for x in themereflag.plan(self.store)["left_out"]]
        self.assertEqual(len(titles), 2)
        self.assertTrue(all(len(x) <= 80 for x in titles), titles)
        self.assertTrue(any(len(x) >= 70 for x in titles), titles)
        self.assertTrue(all("\t" not in x for x in titles), titles)

    def test_a_book_whose_generations_all_fail_their_check_is_damaged_and_not_without_themes(self):
        book = self.book("finding the stopping rule", [OLD_STOPPING])[0]
        version = self.store.read_book(book)["current_version"]
        path = os.path.join(self.store.version_dir(book, version), "derived", theme.TOOL, "1", theme.FILENAME)
        os.chmod(path, 0o600)
        with open(path, "w") as f:
            f.write("{}")
        got = themereflag.plan(self.store)
        self.assertEqual([(x["book_id"], x["reason"]) for x in got["left_out"]], [(book, "damaged")])

    def test_a_book_that_cannot_be_read_is_left_out_and_named_and_the_others_go_on(self):
        a, b, c, d, e = self.library()
        real = themecheck.field_flag

        def flag(neutral, vocabulary):
            if neutral["problem"]["text"] == "an annealing schedule choice" and not hasattr(self, "_failed"):
                self._failed = True
                raise OSError("unreadable")
            return real(neutral, vocabulary)

        with unittest.mock.patch.object(themecheck, "field_flag", flag):
            got = themereflag.plan(self.store)
        self.assertEqual(len(got["left_out"]), 1)
        self.assertEqual(got["left_out"][0]["reason"], "unreadable")
        self.assertEqual(got["left_out_counts"], {"unreadable": 1})
        self.assertEqual(got["books"] + got["unchanged"], 4)   # the other four books were looked at

    def test_a_plan_of_no_books_is_an_empty_plan(self):
        got = themereflag.plan(self.store)
        self.assertEqual((got["books"], got["unchanged"], got["themes"], got["to_change"], got["left_out"]), (0, 0, 0, [], []))


class RunTest(ReflagCase):
    def test_a_new_generation_is_filed_for_each_book_to_change_and_only_the_field_flags_change(self):
        a, b, c, d, e = self.library()
        before = {x: self.newest(x)[1] for x in (a, b, c, d, e)}
        report = themereflag.run(self.store)
        self.assertEqual(sorted(f["book_id"] for f in report["filed"]), sorted([a, c, e]))
        self.assertEqual(report["failed"], [])
        for book in (a, c, e):
            self.assertEqual(self.generations(book), [1, 2])
        for book in (b, d):
            self.assertEqual(self.generations(book), [1])
        expected = {a: [], c: [{"kind": "field_words", "detail": "annealing"}], e: [UNREADABLE]}
        for book, flags in expected.items():
            number, now = self.newest(book)
            self.assertEqual(number, 2)
            old, new = before[book]["themes"], now["themes"]
            self.assertEqual(len(old), len(new))
            for o, n in zip(old, new):
                self.assertEqual(n["flags"], flags)
                self.assertEqual({k: v for k, v in n.items() if k != "flags"}, {k: v for k, v in o.items() if k != "flags"})
            self.assertEqual(theme.read(self.store, book, self.store.read_book(book)["current_version"], 1)[1], before[book])   # the older one stays

    def test_a_second_run_files_nothing(self):
        self.library()
        themereflag.run(self.store)
        again = themereflag.run(self.store)
        self.assertEqual((again["filed"], again["failed"], again["books"]), ([], [], 0))
        self.assertEqual(themereflag.plan(self.store)["books"], 0)

    def test_a_book_whose_flags_already_match_files_nothing(self):
        d = self.book("an annealing schedule choice", [UNREADABLE, OLD_ANNEALING])[0]
        report = themereflag.run(self.store)
        self.assertEqual((report["filed"], self.generations(d)), ([], [1]))

    def test_the_report_has_counts_and_ids_and_no_text_of_a_book(self):
        self.library()
        report = themereflag.run(self.store)
        text = json.dumps(report)
        for word in ("schedule", "stopping rule", "cools a system"):
            self.assertNotIn(word, text)
        self.assertEqual((report["themes"], report["flagged_before"], report["flagged_after"]), (5, 3, 2))

    def test_the_newest_valid_generation_is_the_one_reflagged_when_a_newer_one_is_damaged(self):
        a = self.book("finding the stopping rule", [OLD_STOPPING])[0]
        version = self.store.read_book(a)["current_version"]
        theme.file(self.store, self.newest(a)[1])   # a second generation, the same
        path = os.path.join(self.store.version_dir(a, version), "derived", theme.TOOL, "2", theme.FILENAME)
        os.chmod(path, 0o600)
        with open(path, "w") as f:
            f.write("{}")
        self.assertEqual(self.newest(a)[0], 1)
        report = themereflag.run(self.store)
        self.assertEqual([f["book_id"] for f in report["filed"]], [a])
        self.assertEqual(self.generations(a), [1, 2, 3])
        self.assertEqual(self.newest(a)[1]["themes"][0]["flags"], [])

    def test_a_book_that_raises_an_unexpected_error_fails_alone_and_the_others_go_on(self):
        a, b, c, d, e = self.library()
        real = theme.file

        def file(store, gen):
            if gen["book_id"] == c:
                raise RuntimeError("secret text of the book")
            return real(store, gen)

        with unittest.mock.patch.object(theme, "file", file):
            report = themereflag.run(self.store)
        self.assertEqual(sorted(f["book_id"] for f in report["filed"]), sorted([a, e]))
        self.assertEqual(report["failed"], [{"book_id": c, "reason": "an unexpected error (RuntimeError)"}])
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(self.generations(c), [1])

    def test_a_book_that_cannot_be_filed_fails_with_a_fixed_reason(self):
        self.library()
        with unittest.mock.patch.object(theme, "file", side_effect=KbError("the disk is full")):
            report = themereflag.run(self.store)
        self.assertEqual(report["filed"], [])
        self.assertTrue(all(f["reason"] == "failed" for f in report["failed"]))
        self.assertEqual(len(report["failed"]), 3)

    def test_the_run_holds_the_shared_lock_and_a_second_holder_is_refused(self):
        self.library()
        with cardstate.lock(self.index_root(), themejournal.RUN):
            with self.assertRaisesRegex(KbError, "lock"):
                themereflag.run(self.store)
        self.assertEqual(themereflag.run(self.store)["books"], 3)

    def test_the_run_calls_no_model(self):
        self.library()
        with unittest.mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")):
            themereflag.run(self.store)


class CommandTest(ReflagCase):
    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(config())
        kbconfig.save(saved)

    def kb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(["themes-reflag", *args])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_plan_and_run_through_the_command_line(self):
        a, b, c, d, e = self.library()
        code, out, err = self.kb("plan")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["books"], 3)
        code, out, err = self.kb("run")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(json.loads(out)["filed"]), 3)
        self.assertEqual(json.loads(self.kb("plan")[1])["books"], 0)

    def test_the_exit_code_is_one_when_a_book_failed_and_the_error_output_says_so(self):
        self.library()
        with unittest.mock.patch.object(theme, "file", side_effect=KbError("no")):
            code, out, err = self.kb("run")
        self.assertEqual(code, 1)
        self.assertIn("3 books", err)
        self.assertEqual(len(json.loads(out)["failed"]), 3)

    def test_the_command_takes_no_model_server_or_address(self):
        for option in ("--model", "--server", "--address", "--host", "--url", "--port"):
            code, _, err = self.kb("plan", option, "x")
            self.assertEqual(code, 2, option)
        code, _, _ = self.kb("run", "extra")
        self.assertEqual(code, 2)

    def test_plan_opens_the_library_to_read_and_run_to_write(self):
        self.library()
        opened = []
        real = kbmain.Store.open
        with unittest.mock.patch.object(kbmain.Store, "open", side_effect=lambda *a, **k: opened.append((a, k)) or real(*a, **k)):
            self.kb("plan")
            self.kb("run")
        self.assertEqual(opened, [((), {"write": False}), ((), {})])


if __name__ == "__main__":
    unittest.main()
