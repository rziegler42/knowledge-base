"""The judgement of a crawled book (`kb/crawljudge.py`, the judgement of Increment J of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

A book is judged once, on the converted text of its stored version: the text must be a real document (at least `min_chars`, and not an error page, a login page or a
menu), and its best match among the home shelves of the schema must reach the plan's `threshold`, using the title and the first 1,500 characters embedded by the
existing embedding entry against the shelf vectors. Every test runs on a temporary library, a fake embedding function passed as `embed` and fixture shelf vectors;
none makes a model call or a request, or reads the owner's config, plan or key. Run them with
`python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawljudge`."""
import datetime
import json
import math
import os
import re
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_models import fake_vector
from engine.tests.test_shelfmatch import schema_data
from engine.tests.test_shelfvectors import MEASURED, ShelfCase
from engine.tests.test_store import StoreCase

from kb import KbError, convert, crawlbooks, crawljudge, crawlplan, crawlqueue, shelfmatch, shelfvectors, stages

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
DIGEST = "a" * 32
DIM = 20
SCHEMA = shelfmatch.schema_from_data(schema_data())
ALL = list(SCHEMA.home) + [slug for level in shelfmatch.COARSE for slug in SCHEMA.levels[level]]
SPARE = DIM - 1  # an axis that no shelf has, so that a vector can be made with a chosen closeness to one shelf
VECTORS = {slug: [1.0 if i == n else 0.0 for i in range(DIM)] for n, slug in enumerate(ALL)}
LOADED = {"meta": {"model": MEASURED}, "vectors": VECTORS, "schema": SCHEMA, "identity": "x"}
ENTRY = ("emb", {"dimension": DIM, "model": MEASURED, "kind": "embedding"})
SENTENCE = "The controller keeps the plant stable when the load changes. "
BASE = SENTENCE.strip()


def vector_for(slug, score):
    """A unit vector whose cosine with the vector of the shelf `slug` is `score`, and with every other shelf 0."""
    v = [0.0] * DIM
    v[ALL.index(slug)] = score
    v[SPARE] = math.sqrt(1 - score * score)
    return v


def document(slug="pid", score=0.8, chars=600, marker=True):
    """A real document of at least `chars` characters whose fake embedding is close to `slug` by `score`."""
    text = f"[[{slug} {score}]] " if marker else ""
    while len(text) < chars:
        text += SENTENCE
    return text


def exact(n):
    """A text of exactly `n` characters (with sentences in it, and no white space at either end)."""
    k = max(2, (n - 5) // (len(BASE) + 1))
    text = " ".join([BASE] * k)
    assert len(text) <= n
    return text + "x" * (n - len(text))


class FakeEmbed:
    """The embedding function that is passed as `embed`: it answers with the vector that the marker `[[slug score]]` in the text asks for, and notes each call."""

    def __init__(self, model=MEASURED, dimension=DIM, fail=None, vectors=None):
        self.model, self.dimension, self.fail, self.vectors, self.calls = model, dimension, fail, vectors, []

    def __call__(self, cfg, name, texts, launcher=None, root=None, kind="document"):
        self.calls.append({"name": name, "texts": list(texts), "kind": kind})
        if self.fail is not None:
            raise self.fail
        if self.vectors is not None:
            return {"model": self.model, "dimension": self.dimension, "vectors": self.vectors}
        out = []
        for text in texts:
            found = re.search(r"\[\[([a-z-]+) (-?[0-9.]+)\]\]", text)
            out.append(vector_for(found.group(1), float(found.group(2))))
        return {"model": self.model, "dimension": self.dimension, "vectors": out}


@contextmanager
def shelves(loaded=LOADED, entry=ENTRY):
    with mock.patch.object(shelfvectors, "entry_for", return_value=entry) as entry_for, mock.patch.object(shelfvectors, "load", return_value=loaded) as load:
        yield entry_for, load


def below(score, shelf="pid", threshold=0.4):
    return crawljudge.below_threshold(shelf, score, threshold)


def plan(**over):
    p = crawlplan.defaults()
    p.update({"threshold": 0.4, "min_chars": 400, "retries": 3})
    p.update(over)
    return p


class TextRulesTest(unittest.TestCase):
    """What a real document is. Each rule is a fixed number or word list in `crawljudge`."""

    def check(self, text, **over):
        return crawljudge.is_document(text, plan(**over))

    def test_a_document_of_enough_characters_is_one(self):
        self.assertEqual(self.check(document(chars=800)), (True, None))

    def test_a_text_under_min_chars_is_not_one_and_one_of_exactly_min_chars_is(self):
        self.assertEqual(len(exact(400)), 400)
        self.assertEqual(self.check(exact(400)), (True, None))
        self.assertEqual(self.check(exact(399)), (False, crawljudge.NOT_LONG_ENOUGH))
        self.assertEqual(self.check(exact(400), min_chars=401), (False, crawljudge.NOT_LONG_ENOUGH))
        self.assertEqual(self.check(exact(400), min_chars=400), (True, None))

    def test_the_length_is_counted_after_white_space_is_made_one_space_and_the_ends_are_cut(self):
        padded = "   \n\n\t " + exact(399) + " \n\n   \n\n  "
        self.assertEqual(self.check(padded), (False, crawljudge.NOT_LONG_ENOUGH))
        self.assertEqual(self.check("   \n\n\t " + exact(400) + " \n\n   \n\n  "), (True, None))
        spaced = "x" + " " * 1000 + "y. z."
        self.assertEqual(self.check(spaced, min_chars=7), (True, None))        # "x y. z." is seven characters
        self.assertEqual(self.check(spaced, min_chars=8), (False, crawljudge.NOT_LONG_ENOUGH))

    def test_an_error_page_is_not_a_document(self):
        for phrase in ("404 Not Found", "Page not found", "403 Forbidden", "Access denied", "500 Internal Server Error", "Service Unavailable", "Bad gateway",
                       "Too many requests", "Something went wrong", "This page does not exist", "Please verify you are human"):
            text = f"{phrase}. The page you asked for could not be shown. " + "Go back to the home page and try again later. " * 12
            with self.subTest(phrase=phrase):
                self.assertGreaterEqual(len(text), 400)
                self.assertEqual(self.check(text), (False, crawljudge.ERROR_PAGE))

    def test_an_error_phrase_only_counts_at_the_start_of_a_short_text(self):
        long_text = "404 Not Found. " + document(chars=2200, marker=False)
        self.assertEqual(self.check(long_text), (True, None))
        late = ("x" * 340) + " Page not found. " + SENTENCE * 5
        self.assertEqual(self.check(late), (True, None))
        early = ("x" * 280) + " Page not found. " + SENTENCE * 8
        self.assertEqual(self.check(early), (False, crawljudge.ERROR_PAGE))
        head = "Page not found. "
        over = head + exact(2001 - len(head))
        self.assertEqual(len(over), 2001)
        self.assertEqual(self.check(over), (True, None))
        just = head + exact(2000 - len(head))
        self.assertEqual(len(just), 2000)
        self.assertEqual(self.check(just), (False, crawljudge.ERROR_PAGE))

    def test_an_ordinary_short_text_that_says_something_was_not_found_is_a_document(self):
        text = "The effect was not found in the second cohort. " + SENTENCE * 10
        self.assertEqual(self.check(text), (True, None))

    def test_a_login_page_is_not_a_document(self):
        text = "Sign in to continue. Username: Password: Forgot your password? Create an account. Remember me. " * 6
        self.assertGreaterEqual(len(text), 400)
        self.assertEqual(self.check(text), (False, crawljudge.LOGIN_PAGE))

    def test_two_login_words_are_not_enough_and_a_long_text_with_many_is_still_a_document(self):
        two = "Sign in with your password. " + SENTENCE * 20
        self.assertEqual(self.check(two), (True, None))
        many = "Sign in. Username. Password. " + SENTENCE * 100
        self.assertGreater(len(many), 3000)
        self.assertEqual(self.check(many), (True, None))
        three = "Sign in. Username. Password. " + SENTENCE * 20
        self.assertEqual(self.check(three), (False, crawljudge.LOGIN_PAGE))

    def test_the_same_login_word_said_three_times_is_one_word(self):
        text = "Password. Password. Password. " + SENTENCE * 20
        self.assertEqual(self.check(text), (True, None))

    def test_a_menu_is_not_a_document(self):
        text = "\n\n".join(["Home", "About us", "Products", "Pricing", "Blog", "Careers", "Contact", "Support", "Sitemap", "Terms of use", "Privacy"] * 5)
        self.assertGreaterEqual(len(" ".join(text.split())), 400)
        self.assertEqual(self.check(text), (False, crawljudge.MENU_PAGE))

    def test_a_list_of_links_with_no_sentence_is_not_a_document(self):
        text = " | ".join(f"Section {n}" for n in range(80))
        self.assertGreaterEqual(len(text), 400)
        self.assertEqual(self.check(text), (False, crawljudge.MENU_PAGE))

    def test_one_sentence_is_not_enough_and_two_are(self):
        words = " ".join(["word"] * 100)
        self.assertEqual(self.check(words + ".", min_chars=10), (False, crawljudge.MENU_PAGE))
        self.assertEqual(self.check(words + ". " + words + ".", min_chars=10), (True, None))
        for mark in ("!", "?", "。", "！", "？"):
            with self.subTest(mark=mark):
                self.assertEqual(self.check(words + mark + " " + words + mark, min_chars=10), (True, None))

    def test_a_text_with_no_sentence_that_is_long_is_left_to_the_judgement_of_the_shelves(self):
        text = " ".join(["word"] * 610)
        self.assertGreater(len(text), 3000)
        self.assertEqual(self.check(text), (True, None))

    def test_a_page_of_short_blocks_with_a_long_paragraph_in_it_is_a_document(self):
        blocks = ["Home.", "About.", "Contact.", "Blog.", "Docs.", "News.", "Jobs.", "Help."] * 2 + [SENTENCE * 6]
        self.assertEqual(self.check("\n\n".join(blocks)), (True, None))

    def test_eight_short_blocks_are_a_menu_and_seven_are_not(self):
        eight = "\n\n".join(f"Item {n} is here." for n in range(8))
        self.assertEqual(self.check(eight, min_chars=10), (False, crawljudge.MENU_PAGE))
        seven = "\n\n".join(f"Item {n} is here." for n in range(7))
        self.assertEqual(self.check(seven, min_chars=10), (True, None))

    def test_the_share_of_short_blocks_is_eighty_percent_and_a_short_block_is_forty_characters(self):
        short = ["Home."] * 8
        mid = ["A line of ordinary prose that is rather longer than forty characters."] * 3
        self.assertEqual(self.check("\n\n".join(short + mid[:2]), min_chars=10), (False, crawljudge.MENU_PAGE))   # 8 of 10
        self.assertEqual(self.check("\n\n".join(short[:7] + mid), min_chars=10), (True, None))                      # 7 of 10
        forty = "x" * 39 + "."
        forty_one = "x" * 40 + "."
        self.assertEqual(len(forty), 40)
        self.assertEqual(self.check("\n\n".join([forty] * 8), min_chars=10), (False, crawljudge.MENU_PAGE))
        self.assertEqual(self.check("\n\n".join([forty_one] * 8), min_chars=10), (True, None))

    def test_a_block_over_two_hundred_characters_is_not_a_menu(self):
        long_block = "y" * 199 + "."
        self.assertEqual(self.check("\n\n".join(["Home."] * 9 + [long_block]), min_chars=10), (False, crawljudge.MENU_PAGE))
        self.assertEqual(self.check("\n\n".join(["Home."] * 9 + ["y" * 200 + "."]), min_chars=10), (True, None))

    def test_the_rules_are_applied_in_the_order_short_error_login_menu(self):
        self.assertEqual(self.check("404 Not Found"), (False, crawljudge.NOT_LONG_ENOUGH))
        both = "404 Not Found. Sign in. Username. Password. " + "Back to the start. " * 30
        self.assertEqual(self.check(both), (False, crawljudge.ERROR_PAGE))
        login_menu = "Sign in. Username. Password. " + "\n\n".join(f"Item {n} is here." for n in range(12))
        self.assertEqual(self.check(login_menu, min_chars=10), (False, crawljudge.LOGIN_PAGE))

    def test_upper_case_is_the_same_and_a_text_that_is_not_text_is_refused(self):
        self.assertEqual(self.check("PAGE NOT FOUND. " + "Go back to the start page. " * 20), (False, crawljudge.ERROR_PAGE))
        for bad in (None, 5, b"abc", ["a"]):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                self.check(bad)

    def test_min_chars_must_be_a_whole_number_of_at_least_one(self):
        for bad in (None, 0, -1, 1.5, True, "400"):
            with self.subTest(min_chars=bad), self.assertRaises(KbError):
                crawljudge.is_document(document(), plan(min_chars=bad))


    def test_the_boundary_of_a_login_page_is_3000_characters_and_that_of_a_menu_of_prose_is_3000(self):
        login = "Sign in. Username. Password. "
        at = login + exact(3000 - len(login))
        self.assertEqual(len(at), 3000)
        self.assertEqual(self.check(at), (False, crawljudge.LOGIN_PAGE))
        over = login + exact(3001 - len(login))
        self.assertEqual(len(over), 3001)
        self.assertEqual(self.check(over), (True, None))
        words = " ".join(["word"] * 600)[:2999]
        self.assertEqual(self.check(words + "x"), (False, crawljudge.MENU_PAGE))
        self.assertEqual(len(words + "x"), 3000)
        self.assertEqual(self.check(words + "xx"), (True, None))

    def test_every_error_phrase_of_the_list_is_one(self):
        phrases = ("page not found", "404 not found", "error 404", "404 error", "403 forbidden", "error 403", "access denied", "internal server error", "500 error", "service unavailable",
                   "bad gateway", "gateway timeout", "too many requests", "something went wrong", "this page does not exist", "this page doesn't exist", "this page is not available",
                   "page you requested", "verify you are human", "enable javascript", "enable cookies", "unusual traffic", "request blocked", "are you a robot")
        self.assertEqual(set(phrases), set(crawljudge.ERROR_PHRASES))
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(self.check(phrase + ". " + "Please go back to the start page and try again later. " * 10), (False, crawljudge.ERROR_PAGE))

    def test_every_login_word_of_the_list_is_one(self):
        words = ("sign in", "log in", "login", "password", "username", "forgot", "create an account", "remember me", "two-factor", "email address")
        self.assertEqual(set(words), set(crawljudge.LOGIN_MARKERS))
        for word in words:
            others = [w for w in words if w != word and word not in w and w not in word][:2]
            text = " ".join(w.capitalize() + "." for w in [word] + others) + " " + SENTENCE * 20
            with self.subTest(word=word):
                self.assertEqual(self.check(text), (False, crawljudge.LOGIN_PAGE))
                without = " ".join(w.capitalize() + "." for w in others) + " " + SENTENCE * 20
                self.assertEqual(self.check(without), (True, None))

    def test_lines_that_are_apart_by_one_line_feed_are_one_block(self):
        verse = "\n".join(f"Short line {n}." for n in range(12))
        self.assertEqual(self.check(verse, min_chars=10), (True, None))

    def test_blank_lines_in_a_row_are_not_blocks(self):
        text = "\n\n\n\n".join(f"Item {n} is here." for n in range(7))
        self.assertEqual(self.check(text, min_chars=10), (True, None))
        spaced = "\n\n \n\n".join(f"Item {n} is here." for n in range(7))
        self.assertEqual(self.check(spaced, min_chars=10), (True, None))

    def test_the_white_space_in_a_block_is_one_space_when_its_length_is_counted(self):
        padded = "\n\n".join(["Home." + " " * 60] * 8)
        self.assertEqual(self.check(padded, min_chars=10), (False, crawljudge.MENU_PAGE))

    def test_a_plan_that_is_not_a_dictionary_refuses(self):
        with self.assertRaises(KbError):
            crawljudge.is_document(document(), "not a plan")
        with self.assertRaises(KbError):
            crawljudge.is_document(document(), None)

    def test_the_title_that_is_not_text_is_not_sent(self):
        self.assertEqual(crawljudge.embedded_text(5, "Body."), "Body.")
        self.assertEqual(crawljudge.embedded_text(None, "Body."), "Body.")
        self.assertEqual(crawljudge.embedded_text("   ", "Body."), "Body.")
        self.assertEqual(crawljudge.embedded_text("Title", "Body."), "Title\n\nBody.")


class JudgeTest(unittest.TestCase):
    """`judge(store, cfg, plan, book_id, version_id, embed)`: the verdict on a text, with no record kept."""

    def judge(self, text, title="A page", embed=None, p=None, loaded=LOADED, entry=ENTRY):
        embed = embed or FakeEmbed()
        store = mock.Mock()
        store.cfg = {"index_root": "/index"}
        with shelves(loaded, entry) as mocks, mock.patch.object(crawljudge, "converted_text", return_value=(title, text)):
            self.mocks = mocks
            return crawljudge.judge(store, {"models_on": True}, p or plan(), "book", "v1", embed=embed), embed

    def test_a_best_match_at_the_threshold_is_kept_with_its_shelf_and_score(self):
        (ok, score, shelf, reason), embed = self.judge(document("pid", 0.4))
        self.assertEqual((ok, shelf, reason), (True, "pid", None))
        self.assertAlmostEqual(score, 0.4, places=9)
        self.assertEqual(len(embed.calls), 1)

    def test_a_best_match_over_the_threshold_is_kept_and_one_under_it_is_not(self):
        (ok, score, shelf, reason), _ = self.judge(document("robot-control", 0.9))
        self.assertEqual((ok, shelf, reason), (True, "robot-control", None))
        self.assertAlmostEqual(score, 0.9, places=9)
        (ok, score, shelf, reason), _ = self.judge(document("gene-editing", 0.39))
        self.assertEqual((ok, shelf), (False, "gene-editing"))
        self.assertAlmostEqual(score, 0.39, places=9)
        self.assertEqual(reason, crawljudge.below_threshold("gene-editing", score, 0.4))
        for part in ("gene-editing", "0.390", "0.4"):
            self.assertIn(part, reason)

    def test_the_threshold_is_read_from_the_plan_and_may_be_negative(self):
        self.assertTrue(self.judge(document("pid", 0.39), p=plan(threshold=0.3))[0][0])
        v = [0.0] * DIM                      # every home shelf is the same distance away, under zero
        for slug in SCHEMA.home:
            v[ALL.index(slug)] = -0.3
        v[SPARE] = 0.5
        want = -0.3 / math.sqrt(9 * 0.09 + 0.25)
        (ok, score, shelf, _), _ = self.judge(document(marker=False), embed=FakeEmbed(vectors=[v]), p=plan(threshold=-0.5))
        self.assertEqual((ok, shelf), (True, SCHEMA.home[0]))
        self.assertAlmostEqual(score, want, places=9)
        self.assertFalse(self.judge(document(marker=False), embed=FakeEmbed(vectors=[v]), p=plan(threshold=-0.2))[0][0])

    def test_only_a_home_shelf_can_be_the_best_match_whatever_a_coarser_shelf_is_nearer(self):
        v = [0.0] * DIM
        v[ALL.index("engineering")] = 1.0     # a field shelf: nearer than any home shelf, which are all 0 here but pid
        v[ALL.index("pid")] = 0.1
        (ok, score, shelf, _), _ = self.judge(document(marker=False), embed=FakeEmbed(vectors=[v]))
        self.assertEqual(shelf, "pid")
        self.assertIn(shelf, SCHEMA.home)
        self.assertAlmostEqual(score, 0.1 / math.sqrt(1.01), places=9)
        self.assertFalse(ok)

    def test_a_custom_shelf_is_a_home_shelf(self):
        (ok, _, shelf, _), _ = self.judge(document("handicrafts", 0.7))
        self.assertEqual((ok, shelf), (True, "handicrafts"))

    def test_a_tie_goes_to_the_shelf_that_comes_first_in_the_schema(self):
        v = [0.0] * DIM
        v[ALL.index("process-control")] = 1.0
        v[ALL.index("robot-control")] = 1.0
        (_, _, shelf, _), _ = self.judge(document(marker=False), embed=FakeEmbed(vectors=[v]))
        self.assertEqual(shelf, "process-control")

    def test_what_is_embedded_is_the_title_and_the_first_1500_characters_as_a_document_in_one_call(self):
        body = "[[pid 0.8]] " + "".join(f"{n % 10}" for n in range(3000)) + " End. Last. Done."
        (_, _, _, _), embed = self.judge(body, title="The   Title")
        (call,) = embed.calls
        self.assertEqual((call["name"], call["kind"], len(call["texts"])), ("emb", "document", 1))
        self.assertEqual(call["texts"][0], "The Title" + "\n\n" + body[:1500])

    def test_a_text_under_1500_characters_is_sent_whole_with_its_white_space_made_plain(self):
        body = "[[pid 0.8]] " + SENTENCE * 8 + "\n\n" + SENTENCE * 8
        self.assertLess(len(body), 1500)
        _, embed = self.judge(body, title="T")
        self.assertEqual(embed.calls[0]["texts"][0], "T" + "\n\n" + " ".join(body.split()))

    def test_the_text_is_cut_at_exactly_1500_characters_after_it_is_made_plain(self):
        body = "[[pid 0.8]] " + "x" * 3000 + ". Done. Done."
        _, embed = self.judge(body, title="T")
        self.assertEqual(embed.calls[0]["texts"][0].count("x"), 1500 - len("[[pid 0.8]] "))

    def test_the_title_is_cut_to_300_characters_and_may_be_empty(self):
        _, embed = self.judge(document("pid", 0.8), title="t" * 500)
        self.assertEqual(embed.calls[0]["texts"][0].split("\n\n")[0], "t" * 300)
        _, embed = self.judge(document("pid", 0.8), title="")
        self.assertTrue(embed.calls[0]["texts"][0].startswith("[[pid"))
        _, embed = self.judge(document("pid", 0.8), title=None)
        self.assertTrue(embed.calls[0]["texts"][0].startswith("[[pid"))

    def test_control_and_invisible_characters_are_not_sent(self):
        body = "[[pid 0.8]] a\x00b\x1b[31mc" + chr(0x202e) + chr(0x200b) + "d " + SENTENCE * 20
        _, embed = self.judge(body, title="Ti\x07tle" + chr(0x202e))
        sent = embed.calls[0]["texts"][0]
        self.assertFalse([c for c in sent if not c.isprintable() and c != "\n"])
        self.assertNotIn(chr(0x202e), sent)
        self.assertNotIn(chr(0x200b), sent)
        self.assertTrue(sent.startswith("Title"))

    def test_a_text_that_is_not_a_document_is_rejected_with_no_score_no_model_call_and_no_shelf_vectors_read(self):
        for text, reason in (("short", crawljudge.NOT_LONG_ENOUGH), ("Page not found. " + "Go back to the start page. " * 20, crawljudge.ERROR_PAGE)):
            with self.subTest(reason=reason):
                (ok, score, shelf, got), embed = self.judge(text)
                self.assertEqual((ok, score, shelf, got, embed.calls), (False, None, None, reason, []))
                self.mocks[1].assert_not_called()
                self.mocks[0].assert_not_called()

    def test_an_empty_or_odd_threshold_refuses_before_anything_else(self):
        for bad in (None, True, False, "0.4", float("nan"), float("inf"), 1.01, -1.01, [0.4]):
            with self.subTest(threshold=bad):
                embed = FakeEmbed()
                store = mock.Mock()
                with shelves() as (entry_for, load), mock.patch.object(crawljudge, "converted_text") as text, self.assertRaises(KbError):
                    crawljudge.judge(store, {}, plan(threshold=bad), "b", "v", embed=embed)
                self.assertEqual((embed.calls, entry_for.call_count, load.call_count, text.call_count, store.method_calls), ([], 0, 0, 0, []))

    def test_the_threshold_may_be_minus_one_zero_or_one(self):
        for good in (-1, 0, 1, -1.0, 0.0, 1.0):
            with self.subTest(threshold=good):
                self.judge(document("pid", 0.5), p=plan(threshold=good))

    def test_a_missing_key_of_the_plan_or_a_plan_that_is_not_a_dictionary_refuses(self):
        for key in ("threshold", "min_chars"):
            p = plan()
            del p[key]
            with self.subTest(missing=key), self.assertRaises(KbError):
                self.judge(document(), p=p)
        with self.assertRaises(KbError):
            self.judge(document(), p="not a plan")

    def test_a_refusal_of_the_entry_or_the_vectors_comes_before_any_model_call_and_is_not_a_failed_try(self):
        for target in ("entry_for", "load"):
            embed = FakeEmbed()
            store = mock.Mock()
            store.cfg = {"index_root": "/index"}
            with shelves(), mock.patch.object(shelfvectors, target, side_effect=KbError("no shelf vectors")), \
                    mock.patch.object(crawljudge, "converted_text", return_value=("T", document())), self.assertRaises(KbError) as raised:
                crawljudge.judge(store, {}, plan(), "b", "v", embed=embed)
            with self.subTest(target=target):
                self.assertNotIsInstance(raised.exception, crawljudge.ModelFailed)
                self.assertEqual(embed.calls, [])

    def test_the_shelf_vectors_are_loaded_from_the_index_root_of_the_store_with_the_config(self):
        store = mock.Mock()
        store.cfg = {"index_root": "/the/index"}
        cfg = {"models_on": True, "marker": 1}
        with shelves() as (entry_for, load), mock.patch.object(crawljudge, "converted_text", return_value=("T", document())):
            crawljudge.judge(store, cfg, plan(), "b", "v", embed=FakeEmbed())
        load.assert_called_once_with("/the/index", cfg)
        entry_for.assert_called_once_with(cfg)

    def test_a_model_that_fails_is_a_failed_try_and_not_a_verdict_and_what_it_says_is_not_kept(self):
        for fail in (KbError("the bridge is down: Authorization: Bearer SECRETKEY1234567890"), OSError(5, "I/O error")):
            with self.subTest(fail=type(fail).__name__), self.assertRaises(crawljudge.ModelFailed) as raised:
                self.judge(document(), embed=FakeEmbed(fail=fail))
            self.assertIsInstance(raised.exception, KbError)
            self.assertEqual(raised.exception.why, crawljudge.MODEL_FAILED)
            self.assertNotIn("SECRETKEY", str(raised.exception) + raised.exception.why)

    def test_an_answer_of_the_wrong_shape_is_a_failed_try(self):
        good = vector_for("pid", 0.8)
        cases = (("no vectors", {"model": MEASURED, "dimension": DIM, "vectors": []}), ("two vectors", {"model": MEASURED, "dimension": DIM, "vectors": [good, good]}),
                 ("a short vector", {"model": MEASURED, "dimension": DIM, "vectors": [good[:-1]]}), ("a vector that is not a list", {"model": MEASURED, "dimension": DIM, "vectors": ["x"]}),
                 ("a vector of zeros", {"model": MEASURED, "dimension": DIM, "vectors": [[0.0] * DIM]}), ("not a dict", [good]), ("no vectors key", {"model": MEASURED}),
                 ("a nan", {"model": MEASURED, "dimension": DIM, "vectors": [[float("nan")] + good[1:]]}), ("vectors not a list", {"model": MEASURED, "vectors": "abc"}))
        for name, got in cases:
            with self.subTest(name=name), self.assertRaises(crawljudge.ModelFailed) as raised:
                self.judge(document(), embed=lambda *a, **k: got)
            self.assertEqual(raised.exception.why, crawljudge.MODEL_ANSWER_BAD)

    def test_a_model_the_bridge_names_other_than_the_measured_one_is_a_refusal_and_not_a_failed_try(self):
        with self.assertRaises(KbError) as raised:
            self.judge(document(), embed=FakeEmbed(model="another-model:7b"))
        self.assertNotIsInstance(raised.exception, crawljudge.ModelFailed)
        other = dict(LOADED, meta={"model": "another-model:7b"})
        with self.assertRaises(KbError) as raised:
            self.judge(document(), loaded=other)
        self.assertNotIsInstance(raised.exception, crawljudge.ModelFailed)

    def test_vectors_that_cannot_make_a_space_are_a_refusal_before_the_model_is_asked(self):
        broken = dict(LOADED, vectors={slug: v for slug, v in VECTORS.items() if slug != "pid"})
        embed = FakeEmbed()
        with self.assertRaises(KbError) as raised:
            self.judge(document(), embed=embed, loaded=broken)
        self.assertNotIsInstance(raised.exception, crawljudge.ModelFailed)
        self.assertEqual(embed.calls, [])

    def test_a_model_that_the_bridge_and_the_vectors_both_name_but_that_is_not_the_measured_one_is_refused(self):
        other = dict(LOADED, meta={"model": "another-model:7b"})
        with self.assertRaises(KbError) as raised:
            self.judge(document(), embed=FakeEmbed(model="another-model:7b"), loaded=other)
        self.assertNotIsInstance(raised.exception, crawljudge.ModelFailed)

    def test_a_vector_of_another_width_than_the_entry_says_is_a_failed_try(self):
        entry = ("emb", {"dimension": DIM - 1, "model": MEASURED, "kind": "embedding"})
        with self.assertRaises(crawljudge.ModelFailed):
            self.judge(document(), entry=entry)

    def test_a_score_equal_to_the_threshold_is_kept_and_one_a_hair_under_is_not(self):
        (_, score, _, _), _ = self.judge(document("pid", 0.5))
        self.assertTrue(self.judge(document("pid", 0.5), p=plan(threshold=score))[0][0])
        self.assertFalse(self.judge(document("pid", 0.5), p=plan(threshold=math.nextafter(score, 2)))[0][0])

    def test_the_score_is_a_plain_float_in_the_range_of_a_score(self):
        (_, score, _, _), _ = self.judge(document("pid", 1.0 - 1e-12))
        self.assertIs(type(score), float)
        self.assertTrue(-1.0 <= score <= 1.0)

    def test_an_embed_that_is_not_given_is_the_engines_own(self):
        store = mock.Mock()
        store.cfg = {"index_root": "/i"}
        with shelves(), mock.patch.object(crawljudge, "converted_text", return_value=("T", document())), \
                mock.patch.object(crawljudge.models, "embed", side_effect=FakeEmbed()) as engine:
            crawljudge.judge(store, {"c": 1}, plan(), "b", "v")
        engine.assert_called_once()
        self.assertEqual(engine.call_args.args[:2], ({"c": 1}, "emb"))
        self.assertEqual(engine.call_args.kwargs, {"kind": "document"})

    def test_the_text_that_is_judged_is_asked_of_the_reader_of_the_converted_text_for_this_book_and_version(self):
        store = mock.Mock()
        store.cfg = {"index_root": "/i"}
        with shelves(), mock.patch.object(crawljudge, "converted_text", return_value=("T", document())) as reader:
            crawljudge.judge(store, {}, plan(), "the-book", "the-version", embed=FakeEmbed())
        reader.assert_called_once_with(store, "the-book", "the-version")


class ConvertedTextTest(StoreCase):
    """The text that is judged is the converted text of the stored version, and only that."""

    def version(self, title="The Title"):
        book = self.store.create_book(title=title, kind="preprint", auto_filed=True)
        version = self.store.add_version(book, label="v1")
        stages.mark(self.store, book, version, "fetched", "done")
        stages.mark(self.store, book, version, "scanned", "skipped", reason="no tool")
        return book, version

    def conversion(self, *texts):
        return convert.build([{"kind": "paragraph", "level": 0, "text": t} for t in texts])

    def test_the_converted_text_of_the_version_in_use_and_the_title_of_the_book_are_given(self):
        book, version = self.version()
        stages.mark(self.store, book, version, "converted", "done")
        with mock.patch.object(convert, "load_in_use", return_value=({"tool": "t"}, self.conversion("First block.", "Second block."), {})) as loaded:
            title, text = crawljudge.converted_text(self.store, book, version)
        self.assertEqual((title, text), ("The Title", "First block.\n\nSecond block."))
        loaded.assert_called_once_with(self.store, book, version)

    def test_a_version_that_is_not_converted_is_refused_and_nothing_is_read_of_it(self):
        book, version = self.version()
        with mock.patch.object(convert, "load_in_use") as loaded, self.assertRaises(KbError):
            crawljudge.converted_text(self.store, book, version)
        loaded.assert_not_called()
        stages.mark(self.store, book, version, "converted", "failed", reason="it broke")
        with mock.patch.object(convert, "load_in_use") as loaded, self.assertRaises(KbError):
            crawljudge.converted_text(self.store, book, version)
        loaded.assert_not_called()

    def test_a_converted_version_with_no_conversion_in_use_is_refused(self):
        book, version = self.version()
        stages.mark(self.store, book, version, "converted", "done")
        with mock.patch.object(convert, "load_in_use", return_value=None), self.assertRaises(KbError):
            crawljudge.converted_text(self.store, book, version)

    def test_a_book_with_no_title_gives_an_empty_one(self):
        book, version = self.version(title="")
        stages.mark(self.store, book, version, "converted", "done")
        with mock.patch.object(convert, "load_in_use", return_value=({}, self.conversion("Text."), {})):
            self.assertEqual(crawljudge.converted_text(self.store, book, version)[0], "")

    def test_the_card_and_the_original_of_the_book_are_not_opened(self):
        book, version = self.version()
        stages.mark(self.store, book, version, "converted", "done")
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)

        with mock.patch.object(convert, "load_in_use", return_value=({}, self.conversion("Text."), {})), mock.patch.object(os, "open", spy):
            crawljudge.converted_text(self.store, book, version)
        self.assertFalse([p for p in opened if "card" in os.path.basename(p) or "/original" in p])


class RecordCase(StoreCase):
    """A temporary library with a queue, and crawl books that the crawl has filed; the text of a book is given to the judgement by a fake reader."""
    fake_text = True

    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))
        self.conn = crawlqueue.connect(self.index)
        self.addCleanup(self.conn.close)
        self.texts = {}
        if self.fake_text:
            patcher = mock.patch.object(crawljudge, "converted_text", side_effect=lambda store, book, version: self.texts[book])
            patcher.start()
            self.addCleanup(patcher.stop)
        shelf = shelves()
        self.entry_for, self.load = shelf.__enter__()
        self.addCleanup(shelf.__exit__, None, None, None)
        self.cfg = {"models_on": True}

    def crawl_book(self, text=None, title="A page", status="kept", candidate=None):
        stamp = "2026-11-16T05:00:00Z"
        number = len(self.texts)
        cursor = self.conn.execute("INSERT INTO candidates (identity_key, address, source, status, domain, reason, added, updated) VALUES (?,?,?,?,?,?,?,?)",
                                   (f"k{number}", f"https://example.org/{number}", crawlqueue.SOURCES[0], status, "example.org", None, stamp, stamp))
        row = cursor.lastrowid
        book = self.store.create_book(title=title, kind="preprint", auto_filed=True)
        version = self.store.add_version(book, label="v1")
        crawlbooks.record_found(self.store, book, candidate=row if candidate is None else candidate, source=crawlqueue.SOURCES[0], found_from=None, topic=None, run="r1", plan_digest=DIGEST)
        self.texts[book] = (title, document() if text is None else text)
        return book, version, row

    def judge_book(self, book, version, embed=None, p=None, run="r1", now=NOW):
        embed = embed or FakeEmbed()
        return crawljudge.judge_book(self.store, self.conn, self.cfg, p or plan(), book, version, run, now, embed=embed), embed

    def events(self, book):
        return list(self.store.read_events(book))

    def named(self, book, name):
        return [e for e in self.events(book) if e.get("event") == name]

    def row(self, row):
        return dict(zip(("status", "reason", "updated"), self.conn.execute("SELECT status, reason, updated FROM candidates WHERE id = ?", (row,)).fetchone()))

    def log_lines(self):
        folder = Path(self.index) / "crawl" / "log"
        if not folder.exists():
            return []
        return [json.loads(line) for path in sorted(folder.iterdir()) for line in path.read_text().splitlines()]


class JudgeBookTest(RecordCase):
    def test_a_book_that_reaches_the_threshold_is_kept_and_its_best_shelf_is_recorded(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["ok"], got["shelf"], got["reason"]), ("kept", True, "pid", None))
        self.assertAlmostEqual(got["score"], 0.7, places=9)
        (event,) = self.named(book, "crawl_judged")
        self.assertEqual((event["ok"], event["shelf"]), (True, "pid"))
        self.assertAlmostEqual(event["score"], 0.7, places=9)
        self.assertEqual((self.named(book, "crawl_rejected"), self.store.read_book(book)["state"], self.row(row)["status"]), ([], "active", "kept"))
        self.assertEqual(len(embed.calls), 1)

    def test_a_book_under_the_threshold_is_weeded_with_the_reason_and_the_score_and_its_row_is_rejected(self):
        book, version, row = self.crawl_book(document("gene-editing", 0.2))
        got, _ = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["ok"], got["shelf"]), ("rejected", False, "gene-editing"))
        self.assertAlmostEqual(got["score"], 0.2, places=9)
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual(event["stage"], "judge")
        self.assertEqual(event["reason"], got["reason"])
        self.assertAlmostEqual(event["score"], 0.2, places=9)
        self.assertIn("gene-editing", event["reason"])
        self.assertEqual(self.store.read_book(book)["state"], "weeded")
        self.assertEqual(self.named(book, "crawl_judged"), [])
        state = self.row(row)
        self.assertEqual((state["status"], state["reason"], state["updated"]), ("rejected", got["reason"], "2026-11-16T12:00:00Z"))

    def test_a_weeded_book_keeps_its_files_and_is_not_removed(self):
        book, version, _ = self.crawl_book(document("gene-editing", 0.1))
        self.judge_book(book, version)
        self.assertEqual(self.store.read_book(book)["state"], "weeded")
        self.assertTrue(os.path.isfile(self.store.book_file(book)))
        self.assertTrue(os.path.isdir(self.store.version_dir(book, version)))
        self.assertEqual(self.store.read_version(book, version)["version_id"], version)

    def test_a_text_that_is_not_a_document_is_weeded_with_no_score_and_no_model_call(self):
        book, version, row = self.crawl_book("too short")
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["ok"], got["score"], got["shelf"], got["reason"]), ("rejected", False, None, None, crawljudge.NOT_LONG_ENOUGH))
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual((event["reason"], event["score"], event["stage"]), (crawljudge.NOT_LONG_ENOUGH, None, "judge"))
        self.assertEqual((embed.calls, self.row(row)["status"], self.store.read_book(book)["state"]), ([], "rejected", "weeded"))

    def test_the_verdict_is_recorded_once_and_a_second_call_does_not_ask_the_model_again(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        first, embed = self.judge_book(book, version)
        again, second = self.judge_book(book, version)
        self.assertEqual((again["outcome"], again["ok"], again["shelf"]), ("already_kept", True, "pid"))
        self.assertAlmostEqual(again["score"], first["score"], places=9)
        self.assertEqual((len(embed.calls), len(second.calls)), (1, 0))
        self.assertEqual(len(self.named(book, "crawl_judged")), 1)
        self.assertEqual(len(self.log_lines()), 1)

    def test_a_server_that_would_answer_differently_the_second_time_is_not_asked(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        self.judge_book(book, version)
        self.texts[book] = ("A page", document("gene-editing", 0.0))
        again, second = self.judge_book(book, version, embed=FakeEmbed(fail=KbError("boom")))
        self.assertEqual((again["outcome"], again["shelf"], second.calls), ("already_kept", "pid", []))

    def test_a_rejection_is_found_again_and_the_model_is_not_asked_again(self):
        book, version, _ = self.crawl_book(document("gene-editing", 0.1))
        first, _ = self.judge_book(book, version)
        again, second = self.judge_book(book, version)
        self.assertEqual((again["outcome"], again["ok"], again["shelf"], again["reason"]), ("already_rejected", False, None, first["reason"]))
        self.assertAlmostEqual(again["score"], 0.1, places=9)
        self.assertEqual((second.calls, len(self.named(book, "crawl_rejected")), len(self.log_lines())), ([], 1, 1))

    def test_a_row_left_kept_by_a_death_between_the_weeding_and_the_row_is_finished_without_the_model(self):
        book, version, row = self.crawl_book(document("gene-editing", 0.1))
        with mock.patch.object(crawljudge.crawlstate, "reject_kept", side_effect=RuntimeError("died")), self.assertRaises(RuntimeError):
            self.judge_book(book, version)
        self.assertEqual((self.store.read_book(book)["state"], self.row(row)["status"]), ("weeded", "kept"))
        again, second = self.judge_book(book, version)
        self.assertEqual((again["outcome"], second.calls, self.row(row)["status"]), ("already_rejected", [], "rejected"))
        self.assertEqual(self.row(row)["reason"], self.named(book, "crawl_rejected")[0]["reason"])
        self.assertEqual(len(self.log_lines()), 1)

    def test_a_row_that_is_not_kept_is_left_as_it_is(self):
        book, version, row = self.crawl_book(document("gene-editing", 0.1), status="rejected")
        before = self.row(row)
        got, _ = self.judge_book(book, version)
        self.assertEqual((got["outcome"], self.row(row), len(self.log_lines())), ("rejected", before, 1))

    def test_a_verdict_that_says_no_with_no_rejection_is_finished_without_the_model(self):
        book, version, row = self.crawl_book(document("pid", 0.9))
        self.store.append_event(book, "crawl_judged", score=0.1, shelf="gene-editing", ok=False)
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["ok"], got["shelf"], embed.calls), ("rejected", False, "gene-editing", []))
        self.assertAlmostEqual(got["score"], 0.1, places=9)
        self.assertEqual((self.store.read_book(book)["state"], self.row(row)["status"]), ("weeded", "rejected"))
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual((event["stage"], event["reason"]), ("judge", crawljudge.below_threshold("gene-editing", 0.1, 0.4)))
        self.assertEqual(got["reason"], event["reason"])
        self.assertAlmostEqual(event["score"], 0.1, places=9)

    def test_the_newest_verdict_is_the_one_that_counts(self):
        book, version, _ = self.crawl_book(document("pid", 0.9))
        self.store.append_event(book, "crawl_judged", score=0.1, shelf="gene-editing", ok=False)
        self.store.append_event(book, "crawl_judged", score=0.8, shelf="pid", ok=True)
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["shelf"], embed.calls), ("already_kept", "pid", []))

    def test_a_candidate_number_that_is_not_in_the_queue_is_left_alone(self):
        book, version, row = self.crawl_book(document("gene-editing", 0.1), candidate=99999)
        got, _ = self.judge_book(book, version)
        self.assertEqual((got["outcome"], self.store.read_book(book)["state"], self.row(row)["status"]), ("rejected", "weeded", "kept"))
        self.assertEqual(self.log_lines()[0]["candidate"], 99999)

    def test_a_found_event_whose_candidate_is_not_a_number_is_logged_with_none(self):
        book = self.store.create_book(title="A page", kind="preprint", auto_filed=True)
        version = self.store.add_version(book, label="v1")
        self.store.append_event(book, "crawl_found", candidate="x", source=crawlqueue.SOURCES[0], plan_digest=DIGEST)
        self.texts[book] = ("A page", document("pid", 0.7))
        got, _ = self.judge_book(book, version)
        self.assertEqual(got["outcome"], "kept")
        self.assertIsNone(self.log_lines()[0]["candidate"])

    def test_a_book_the_crawl_filed_with_no_found_event_is_refused(self):
        book = self.store.create_book(title="A page", kind="preprint", auto_filed=True)
        version = self.store.add_version(book, label="v1")
        self.texts[book] = ("A page", document())
        embed = FakeEmbed()
        with self.assertRaises(KbError):
            crawljudge.judge_book(self.store, self.conn, self.cfg, plan(), book, version, "r1", NOW, embed=embed)
        self.assertEqual((embed.calls, self.log_lines()), ([], []))

    def test_a_book_weeded_at_another_stage_leaves_its_row_alone_and_is_not_judged(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        crawlbooks.weed(self.store, book, "the capture failed", None, "capture")
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["reason"], embed.calls, self.row(row)["status"], self.log_lines()), ("already_rejected", "the capture failed", [], "kept", []))

    def test_a_verdict_of_no_that_has_no_numbers_is_weeded_with_a_plain_reason(self):
        book, version, row = self.crawl_book(document("pid", 0.9))
        self.store.append_event(book, "crawl_judged", score="high", shelf=5, ok=False)
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["score"], got["shelf"], got["reason"], embed.calls), ("rejected", None, None, "judged out before", []))
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual((event["reason"], event["score"]), ("judged out before", None))

    def test_a_stored_verdict_with_odd_numbers_or_names_is_read_as_far_as_it_is_sound(self):
        cases = ((True, "pid", None, "judged out before"), (1.0, "pid", 1.0, below(1.0)), (-1.0, "pid", -1.0, below(-1.0)), (1.5, "pid", None, "judged out before"),
                 (0.1, "", 0.1, "judged out before"), (0.1, 5, 0.1, "judged out before"), ("high", "pid", None, "judged out before"), (None, "pid", None, "judged out before"),
                 (0.1, None, 0.1, "judged out before"), (float("nan"), "pid", None, "judged out before"), (float("inf"), "pid", None, "judged out before"))
        for score, shelf, want_score, want_reason in cases:
            with self.subTest(score=score, shelf=shelf):
                book, version, _ = self.crawl_book(document("pid", 0.9))
                self.store.append_event(book, "crawl_judged", score=score, shelf=shelf, ok=False)
                got, embed = self.judge_book(book, version)
                self.assertEqual((got["outcome"], got["score"], embed.calls), ("rejected", want_score, []))
                self.assertEqual(got["reason"], want_reason)
                self.assertEqual(self.named(book, "crawl_rejected")[0]["reason"], got["reason"])

    def test_a_stored_kept_verdict_with_odd_numbers_or_names_gives_none_for_them(self):
        for score, shelf, want_score, want_shelf in ((0.5, "pid", 0.5, "pid"), ("high", "pid", None, "pid"), (True, "pid", None, "pid"), (7, "pid", None, "pid"), (0.5, "", 0.5, None),
                                                      (0.5, 5, 0.5, None), (1, "pid", 1.0, "pid"), (-1, "pid", -1.0, "pid")):
            with self.subTest(score=score, shelf=shelf):
                book, version, _ = self.crawl_book(document("pid", 0.9))
                self.store.append_event(book, "crawl_judged", score=score, shelf=shelf, ok=True)
                got, embed = self.judge_book(book, version)
                self.assertEqual((got["outcome"], got["ok"], got["score"], got["shelf"], embed.calls), ("already_kept", True, want_score, want_shelf, []))

    def test_a_stored_rejection_with_odd_values_gives_none_for_them_and_still_repairs_the_row(self):
        book, version, row = self.crawl_book(document("pid", 0.9))
        self.store.append_event(book, "crawl_rejected", reason=5, score="x", stage="judge")
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["score"], got["reason"], embed.calls, self.row(row)["status"]), ("already_rejected", None, None, [], "rejected"))
        book, version, row = self.crawl_book(document("pid", 0.9))
        self.store.append_event(book, "crawl_rejected", reason="because", score=0.25, stage="judge")
        got, _ = self.judge_book(book, version)
        self.assertEqual((got["score"], got["reason"]), (0.25, "because"))

    def test_a_model_that_fails_is_a_failed_try_and_not_a_verdict(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        got, embed = self.judge_book(book, version, embed=FakeEmbed(fail=KbError("the bridge is down")))
        self.assertEqual((got["outcome"], got["ok"], got["score"], got["shelf"], got["reason"]), ("retry", None, None, None, crawljudge.MODEL_FAILED))
        (failed,) = self.named(book, "crawl_step_failed")
        self.assertEqual((failed["step"], failed["run"], failed["reason"]), ("judge", "r1", crawljudge.MODEL_FAILED))
        self.assertEqual((self.named(book, "crawl_judged"), self.named(book, "crawl_rejected")), ([], []))
        self.assertEqual((self.store.read_book(book)["state"], self.row(row)["status"]), ("active", "kept"))
        retry, second = self.judge_book(book, version)
        self.assertEqual((retry["outcome"], len(second.calls)), ("kept", 1))

    def test_with_charge_off_a_model_that_fails_is_left_to_the_caller_and_nothing_is_written_for_the_book(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        before, lines = self.events(book), self.log_lines()
        for fail in (FakeEmbed(fail=KbError("the bridge is down")), FakeEmbed(vectors=[])):
            got = crawljudge.judge_book(self.store, self.conn, self.cfg, plan(retries=1), book, version, "r1", NOW, embed=fail, charge=False)
            self.assertEqual((got["outcome"], got["ok"], got["score"], got["shelf"]), ("model_failed", None, None, None))
            self.assertIn(got["reason"], (crawljudge.MODEL_FAILED, crawljudge.MODEL_ANSWER_BAD))
        self.assertEqual((self.events(book), self.log_lines(), self.store.read_book(book)["state"], self.row(row)["status"]), (before, lines, "active", "kept"))
        self.assertEqual(crawlbooks.step_failures(self.store, book, "judge"), 0)

    def test_with_charge_off_a_verdict_is_given_as_before(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        got = crawljudge.judge_book(self.store, self.conn, self.cfg, plan(), book, version, "r1", NOW, embed=FakeEmbed(), charge=False)
        self.assertEqual(got["outcome"], "kept")

    def test_charge_failed_try_charges_one_try_and_parks_at_the_retries_and_writes_only_the_judges_own_sentences(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        p = plan(retries=2)
        first = crawljudge.charge_failed_try(self.store, self.conn, p, book, "CANARY text from elsewhere", "r1", NOW, 10)
        self.assertEqual((first["outcome"], first["reason"]), ("retry", crawljudge.MODEL_FAILED))
        second = crawljudge.charge_failed_try(self.store, self.conn, p, book, crawljudge.MODEL_ANSWER_BAD, "r1", NOW, 10)
        self.assertEqual(second["outcome"], "parked")
        self.assertEqual((self.store.read_book(book)["state"], self.row(row)["status"], crawlbooks.step_failures(self.store, book, "judge")), ("weeded", "rejected", 2))
        self.assertNotIn("CANARY", json.dumps([self.events(book), self.log_lines()]))
        self.assertEqual([(x["step"], x["outcome"]) for x in self.log_lines()], [("judge", "failed"), ("judge", "rejected")])

    def test_charge_failed_try_refuses_a_book_that_is_not_the_crawls(self):
        other = self.store.create_book(title="Owner book", kind="preprint")
        with self.assertRaises(KbError):
            crawljudge.charge_failed_try(self.store, self.conn, plan(), other, crawljudge.MODEL_FAILED, "r1", NOW)
        self.assertEqual(crawlbooks.step_failures(self.store, other, "judge"), 0)

    def test_a_model_answer_that_is_unusable_is_a_failed_try_with_its_own_reason(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        got, _ = self.judge_book(book, version, embed=FakeEmbed(vectors=[]))
        self.assertEqual((got["outcome"], got["reason"]), ("retry", crawljudge.MODEL_ANSWER_BAD))

    def test_at_the_plans_retries_the_book_is_parked_weeded_with_stage_judge_and_its_row_is_rejected(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        p = plan(retries=2)
        first, _ = self.judge_book(book, version, embed=FakeEmbed(fail=KbError("the bridge is down")), p=p)
        self.assertEqual(first["outcome"], "retry")
        second, _ = self.judge_book(book, version, embed=FakeEmbed(fail=KbError("the bridge is down")), p=p)
        self.assertEqual(second["outcome"], "parked")
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual((event["stage"], event["score"]), ("judge", None))
        self.assertIn("failed 2 times", event["reason"])
        self.assertEqual(second["reason"], event["reason"])
        self.assertEqual((self.store.read_book(book)["state"], self.row(row)["status"], self.row(row)["reason"]), ("weeded", "rejected", event["reason"]))
        self.assertEqual(crawlbooks.step_failures(self.store, book, "judge"), 2)
        third, embed = self.judge_book(book, version, p=p)
        self.assertEqual((third["outcome"], embed.calls), ("already_rejected", []))

    def test_a_book_that_is_final_already_is_not_judged_and_nothing_is_written(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        crawlbooks.record_held(self.store, book, ["javascript"])
        got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], embed.calls, self.named(book, "crawl_judged"), self.log_lines(), self.row(row)["status"]), ("final", [], [], [], "kept"))

    def test_a_book_the_crawl_did_not_file_is_refused(self):
        book = self.store.create_book(title="Mine", kind="preprint", auto_filed=False)
        version = self.store.add_version(book, label="v1")
        self.texts[book] = ("Mine", document())
        embed = FakeEmbed()
        with self.assertRaises(KbError):
            crawljudge.judge_book(self.store, self.conn, self.cfg, plan(), book, version, "r1", NOW, embed=embed)
        self.assertEqual((embed.calls, self.store.read_events(book), self.log_lines()), ([], [], []))

    def test_a_forged_event_on_a_book_that_is_not_auto_filed_is_refused(self):
        book = self.store.create_book(title="Mine", kind="preprint", auto_filed=False)
        version = self.store.add_version(book, label="v1")
        self.store.append_event(book, "crawl_found", candidate=1, source=crawlqueue.SOURCES[0], plan_digest=DIGEST)
        self.texts[book] = ("Mine", document())
        embed = FakeEmbed()
        with self.assertRaises(KbError):
            crawljudge.judge_book(self.store, self.conn, self.cfg, plan(), book, version, "r1", NOW, embed=embed)
        self.assertEqual((embed.calls, self.named(book, "crawl_judged"), self.log_lines()), ([], [], []))

    def test_an_empty_threshold_refuses_before_any_model_call_and_writes_nothing(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        embed = FakeEmbed()
        with self.assertRaises(KbError):
            crawljudge.judge_book(self.store, self.conn, self.cfg, plan(threshold=None), book, version, "r1", NOW, embed=embed)
        self.assertEqual((embed.calls, self.named(book, "crawl_judged"), self.named(book, "crawl_step_failed"), self.log_lines(), self.row(row)["status"]), ([], [], [], [], "kept"))

    def test_a_refusal_of_the_entry_or_the_vectors_is_not_a_failed_try(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        embed = FakeEmbed()
        self.entry_for.side_effect = KbError("no embedding entry is set")
        with self.assertRaises(KbError):
            self.judge_book(book, version, embed=embed)
        self.assertEqual((embed.calls, self.named(book, "crawl_step_failed"), self.named(book, "crawl_judged"), self.log_lines()), ([], [], [], []))

    def test_a_model_the_bridge_names_as_another_is_a_refusal_with_nothing_recorded(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        with self.assertRaises(KbError):
            self.judge_book(book, version, embed=FakeEmbed(model="another-model:7b"))
        self.assertEqual((self.named(book, "crawl_step_failed"), self.named(book, "crawl_judged"), self.log_lines()), ([], [], []))

    def test_the_judged_text_is_what_the_reader_of_the_converted_text_gives(self):
        book, version, _ = self.crawl_book(document("pid", 0.7), title="Own Title")
        _, embed = self.judge_book(book, version)
        self.assertTrue(embed.calls[0]["texts"][0].startswith("Own Title"))
        self.assertIn("[[pid 0.7]]", embed.calls[0]["texts"][0])

    def test_one_judge_line_is_logged_for_each_book_judged_with_counts_and_the_score_and_no_text_of_the_page(self):
        book, version, row = self.crawl_book("[[pid 0.7]] SECRETPAGEWORD " + SENTENCE * 20, title="TITLEWORD")
        self.judge_book(book, version)
        (line,) = self.log_lines()
        self.assertEqual((line["step"], line["outcome"], line["run"], line["candidate"], line["book"], line["host"]), ("judge", "ok", "r1", row, book, None))
        self.assertEqual(line["n"], len(self.texts[book][1]))
        self.assertEqual(line["reason"], "score 0.700 shelf pid")
        self.assertIsNotNone(line["seconds"])
        raw = json.dumps(line)
        self.assertNotIn("SECRETPAGEWORD", raw)
        self.assertNotIn("TITLEWORD", raw)
        self.assertEqual(line["ts"], "2026-11-16T12:00:00Z")

    def test_the_lines_of_a_rejection_a_short_text_and_a_failure_say_so(self):
        book, version, row = self.crawl_book(document("gene-editing", 0.1))
        self.judge_book(book, version)
        short, short_version, short_row = self.crawl_book("short")
        self.judge_book(short, short_version)
        failing, failing_version, failing_row = self.crawl_book(document("pid", 0.7))
        self.judge_book(failing, failing_version, embed=FakeEmbed(fail=KbError("down")))
        lines = self.log_lines()
        self.assertEqual([(l["outcome"], l["candidate"]) for l in lines], [("rejected", row), ("rejected", short_row), ("failed", failing_row)])
        self.assertIn("gene-editing", lines[0]["reason"])
        self.assertEqual((lines[1]["reason"], lines[1]["n"], lines[1]["seconds"]), (crawljudge.NOT_LONG_ENOUGH, 5, None))
        self.assertEqual((lines[2]["reason"], lines[2]["n"]), (crawljudge.MODEL_FAILED, len(self.texts[failing][1])))

    def test_a_parked_book_is_logged_as_rejected_with_its_reason(self):
        book, version, row = self.crawl_book(document("pid", 0.7))
        self.judge_book(book, version, embed=FakeEmbed(fail=KbError("down")), p=plan(retries=1))
        (line,) = self.log_lines()
        self.assertEqual((line["outcome"], line["candidate"]), ("rejected", row))
        self.assertIn("failed 1 times", line["reason"])

    def test_a_log_that_cannot_be_written_stops_the_judgement(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        with mock.patch.object(crawljudge.crawllog.Log, "write", side_effect=KbError("the log cannot be written")), self.assertRaises(KbError):
            self.judge_book(book, version)

    def long_name(self, n=52):
        return ("wnt-beta-catenin-signaling-in-development-and-cancer-" + "x" * n)[:n]

    def test_a_kept_book_whose_shelf_name_is_long_is_judged_and_its_line_shows_the_name_cut(self):
        name = self.long_name()
        book, version, row = self.crawl_book(document("pid", 0.7))
        with mock.patch.object(crawljudge, "_verdict", return_value=(True, 0.7, name, None)):
            got, _ = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["ok"], got["shelf"]), ("kept", True, name))
        (event,) = self.named(book, "crawl_judged")
        self.assertEqual(event["shelf"], name)
        (line,) = self.log_lines()
        self.assertEqual((line["outcome"], line["reason"]), ("ok", "score 0.700 shelf " + name[:36] + "..."))

    def test_a_rejected_book_whose_shelf_name_is_long_is_weeded_with_the_whole_name_and_its_line_shows_it_cut(self):
        name = self.long_name()
        book, version, row = self.crawl_book(document("pid", 0.1))
        with mock.patch.object(crawljudge, "_verdict", return_value=(False, 0.1, name, below(0.1, name))):
            got, _ = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["reason"]), ("rejected", below(0.1, name)))
        (event,) = self.named(book, "crawl_rejected")
        self.assertEqual(event["reason"], below(0.1, name))
        self.assertEqual((self.row(row)["status"], self.row(row)["reason"]), ("rejected", below(0.1, name)))
        (line,) = self.log_lines()
        self.assertEqual(line["reason"], below(0.1, name[:36] + "..."))

    def test_the_line_of_a_rejection_finished_later_shows_the_name_cut_too(self):
        name = self.long_name()
        book, version, row = self.crawl_book(document("pid", 0.1))
        with mock.patch.object(crawljudge, "_verdict", return_value=(False, 0.1, name, below(0.1, name))), \
                mock.patch.object(crawljudge.crawlstate, "reject_kept", side_effect=RuntimeError("died")), self.assertRaises(RuntimeError):
            self.judge_book(book, version)
        again, _ = self.judge_book(book, version)
        self.assertEqual((again["outcome"], self.row(row)["status"]), ("already_rejected", "rejected"))
        (line,) = self.log_lines()
        self.assertEqual(line["reason"], below(0.1, name[:36] + "..."))

    def test_a_name_of_39_characters_is_logged_whole_and_one_of_40_is_cut(self):
        for size, shown in ((39, self.long_name(39)), (40, self.long_name(40)[:36] + "...")):
            with self.subTest(size=size):
                book, version, row = self.crawl_book(document("pid", 0.7))
                with mock.patch.object(crawljudge, "_verdict", return_value=(True, 0.7, self.long_name(size), None)):
                    self.judge_book(book, version)
                self.assertEqual(self.log_lines()[-1]["reason"], "score 0.700 shelf " + shown)

    def test_the_run_must_be_a_name_and_now_a_time_with_a_zone_and_nothing_is_recorded_if_not(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        embed = FakeEmbed()
        for bad in ("a b", "", None, 5):
            with self.subTest(run=bad), self.assertRaises(KbError):
                self.judge_book(book, version, embed=embed, run=bad)
        for bad in (datetime.datetime(2026, 11, 16, 12), None, "2026-11-16"):
            with self.subTest(now=bad), self.assertRaises(KbError):
                self.judge_book(book, version, embed=embed, now=bad)
        self.assertEqual((self.named(book, "crawl_judged"), embed.calls), ([], []))

    def test_a_secret_in_what_a_model_says_reaches_nothing_that_is_kept(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        got, _ = self.judge_book(book, version, embed=FakeEmbed(fail=KbError("Authorization: Bearer SECRETKEY1234567890")))
        self.assertNotIn("SECRETKEY", json.dumps(got) + json.dumps(self.events(book)) + json.dumps(self.log_lines()))

    def test_the_stage_and_the_step_of_the_record_are_judge(self):
        book, version, _ = self.crawl_book(document("pid", 0.7))
        self.judge_book(book, version, embed=FakeEmbed(fail=KbError("down")))
        self.assertEqual(self.named(book, "crawl_step_failed")[0]["step"], "judge")
        self.assertEqual(self.log_lines()[0]["step"], "judge")


class WiringTest(RecordCase):
    """The text comes through the real reader of the converted text, with only the stored conversion faked."""
    fake_text = False

    def test_a_converted_version_is_judged_on_its_stored_conversion_and_the_title_of_its_book(self):
        book, version, row = self.crawl_book(title="Wired Title")
        stages.mark(self.store, book, version, "fetched", "done")
        stages.mark(self.store, book, version, "scanned", "skipped", reason="no tool")
        stages.mark(self.store, book, version, "converted", "done")
        conversion = convert.build([{"kind": "paragraph", "level": 0, "text": document("pid", 0.7, chars=500)}])
        with mock.patch.object(convert, "load_in_use", return_value=({}, conversion, {})):
            got, embed = self.judge_book(book, version)
        self.assertEqual((got["outcome"], got["shelf"]), ("kept", "pid"))
        self.assertTrue(embed.calls[0]["texts"][0].startswith("Wired Title"))
        self.assertIn("[[pid 0.7]]", embed.calls[0]["texts"][0])

    def test_a_version_that_is_not_converted_is_refused_with_nothing_recorded(self):
        book, version, row = self.crawl_book()
        embed = FakeEmbed()
        with self.assertRaises(KbError):
            self.judge_book(book, version, embed=embed)
        self.assertEqual((embed.calls, self.named(book, "crawl_step_failed"), self.named(book, "crawl_judged"), self.log_lines(), self.row(row)["status"]), ([], [], [], [], "kept"))


class ContractTest(ShelfCase):
    """The judgement over the real file of shelf vectors that `shelfvectors.build` makes and the real `shelfvectors.load` and `entry_for`."""

    def embed(self, cfg, name, texts, launcher=None, root=None, kind="document"):
        return {"model": MEASURED, "dimension": 4, "vectors": [fake_vector(t, 4) for t in texts]}

    def test_the_best_match_is_the_nearest_home_shelf_of_the_real_vectors_and_the_score_is_its_cosine(self):
        self.build()
        real_load = shelfvectors.load
        loaded = self.load()
        text = document(chars=700, marker=False) + "End."
        store = mock.Mock()
        store.cfg = {"index_root": self.store.cfg["index_root"]}
        with mock.patch.object(crawljudge, "converted_text", return_value=("Title", text)), \
                mock.patch.object(shelfvectors, "load", side_effect=lambda root, cfg: real_load(root, cfg, schema_path=self.schema_path)):
            ok, score, shelf, reason = crawljudge.judge(store, self.mcfg, plan(threshold=-1), "b", "v", embed=self.embed)
        query = shelfmatch.unit(fake_vector("Title" + "\n\n" + " ".join(text.split())[:1500], 4))
        home = loaded["schema"].home
        cosines = {slug: sum(a * b for a, b in zip(query, shelfmatch.unit(loaded["vectors"][slug]))) for slug in home}
        best = max(home, key=lambda slug: (cosines[slug], -home.index(slug)))
        self.assertEqual((ok, shelf, reason), (True, best, None))
        self.assertAlmostEqual(score, cosines[best], places=6)

    def test_an_embedding_entry_that_is_not_the_measured_one_is_refused_before_any_call(self):
        self.build()
        calls = []
        store = mock.Mock()
        store.cfg = {"index_root": self.store.cfg["index_root"]}
        other = dict(self.mcfg)
        other["models"] = {"emb": dict(self.mcfg["models"]["emb"], model="another-model:7b")}
        with mock.patch.object(crawljudge, "converted_text", return_value=("T", document(marker=False) + "End.")), self.assertRaises(KbError):
            crawljudge.judge(store, other, plan(threshold=-1), "b", "v", embed=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
