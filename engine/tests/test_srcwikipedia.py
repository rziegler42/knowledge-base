"""Wikipedia search as a source of candidates for the unattended crawl (`kb/srcwikipedia.py`; `docs/specs/population.md`, "Discovery").

No test opens a socket: `get` is a fake. The fixtures in `fixtures/crawl/` are made by hand from the documentation of the Action API
(`mediawiki.org/wiki/API:Search`, `API:Etiquette`, the Wikimedia User-Agent policy and robot policy, read on 2026-11-16; the plan's Result holds
the hashes)."""

import json
import re
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from engine.tests import ENGINE_DIR
from engine.tests.test_srcopenalex import Fake, ok, query

from kb import KbError, crawlqueue, srcopenalex, srcwikipedia

FIXTURES = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawl"
NOW = "2026-11-16T10:00:00Z"
PAGE = "https://en.wikipedia.org/wiki/"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def answer(*pages, **top):
    body = {"batchcomplete": True, "query": {"searchinfo": {"totalhits": len(pages)}, "search": list(pages)}}
    body.update(top)
    return ok(json.dumps(body).encode())


def page(title, pageid=1, ns=0):
    return {"ns": ns, "title": title, "pageid": pageid}


def search(reply, query_text="control theory", limit=10, fake=None):
    fake = fake or Fake(reply)
    return srcwikipedia.search(query_text, fake, limit), fake


class RequestTest(unittest.TestCase):
    def test_one_request_to_the_action_api_for_a_text_search_of_the_articles_with_nothing_else_asked(self):
        found, fake = search(ok(fixture("wikipedia_search.json")))
        self.assertEqual(len(fake.calls), 1)
        base, params = query(fake.urls[0])
        self.assertEqual(base, "https://en.wikipedia.org/w/api.php")
        self.assertEqual(params, {"action": "query", "list": "search", "srsearch": "control theory", "srnamespace": "0",
                                  "srlimit": "10", "srprop": "", "srinfo": "", "format": "json", "formatversion": "2"})

    def test_the_agent_is_honest_and_generic_and_no_address_or_key_is_sent(self):
        _, fake = search(ok(fixture("wikipedia_empty.json")))
        url, headers, timeout = fake.calls[0]
        self.assertEqual(headers["User-Agent"], srcopenalex.USER_AGENT)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("@", url + " ".join(headers.values()))
        self.assertNotIn("Authorization", headers)
        self.assertEqual(timeout, 30)

    def test_only_plain_words_reach_the_search_and_the_words_that_are_operators_are_not(self):
        hostile = 'intitle:evil insource:"x" -foo prefix:bar *wild ~fuzzy "phrase" AND NOT OR (a) b'
        _, fake = search(ok(fixture("wikipedia_empty.json")), hostile)
        words = query(fake.urls[0])[1]["srsearch"].split(" ")
        self.assertEqual(words, ["intitle", "evil", "insource", "x", "foo", "prefix", "bar", "wild", "fuzzy", "phrase", "and", "not"])
        self.assertTrue(all(re.fullmatch(r"[^\W_]+", w) for w in words))
        self.assertFalse({"AND", "OR", "NOT"} & set(words))

    def test_each_of_the_three_operator_words_is_written_in_lower_case_wherever_it_stands(self):
        _, fake = search(ok(fixture("wikipedia_empty.json")), "control OR theory AND filter NOT bad")
        self.assertEqual(query(fake.urls[0])[1]["srsearch"], "control or theory and filter not bad")

    def test_a_word_that_is_part_of_another_is_not_an_operator(self):
        _, fake = search(ok(fixture("wikipedia_empty.json")), "ANDROID ORBIT NOTE and or not And")
        self.assertEqual(query(fake.urls[0])[1]["srsearch"], "ANDROID ORBIT NOTE and or not And")

    def test_at_most_12_words_are_sent(self):
        _, fake = search(ok(fixture("wikipedia_empty.json")), " ".join(f"w{i}" for i in range(20)))
        self.assertEqual(len(query(fake.urls[0])[1]["srsearch"].split(" ")), 12)

    def test_a_query_with_no_letter_or_digit_asks_nothing(self):
        for text in ("!!!", "---", "(  )", "+ - *", "_ _"):
            with self.subTest(query=text):
                fake = Fake(ok(fixture("wikipedia_empty.json")))
                with self.assertRaises(KbError):
                    srcwikipedia.search(text, fake, 10)
                self.assertEqual(fake.calls, [])

    def test_the_query_and_the_limit_are_checked_and_nothing_is_asked_when_they_are_wrong(self):
        self.assertEqual(search(ok(fixture("wikipedia_empty.json")), "x" * 300)[0]["candidates"], [])
        for text in ("", "   ", "a\x00b", "line\nbreak", "tab\there", "a\x1fb", "a\x7fb", "x" * 301, 5, None, b"x"):
            with self.subTest(query=text):
                fake = Fake(ok(fixture("wikipedia_empty.json")))
                with self.assertRaises(KbError):
                    srcwikipedia.search(text, fake, 10)
                self.assertEqual(fake.calls, [])
        for limit in (0, -1, 51, 1.5, True, "5", None):
            with self.subTest(limit=limit):
                with self.assertRaises(KbError):
                    srcwikipedia.search("control theory", Fake(ok(fixture("wikipedia_empty.json"))), limit)
        with self.assertRaises(KbError):
            srcwikipedia.search("control theory", "not a function", 10)
        fake = Fake(ok(fixture("wikipedia_empty.json")))
        for limit in (1, 50):
            srcwikipedia.search("control theory", fake, limit)
        self.assertEqual([query(u)[1]["srlimit"] for u in fake.urls], ["1", "50"])


class ResolutionTest(unittest.TestCase):
    def test_the_fixture_gives_four_articles_and_skips_another_namespace_a_page_with_no_id_and_a_repeat(self):
        found, _ = search(ok(fixture("wikipedia_search.json")))
        self.assertEqual(found, {"candidates": [
            {"address": PAGE + "Control_theory", "source": "wikipedia", "found_from": "control theory", "depth": 0},
            {"address": PAGE + "PID_controller", "source": "wikipedia", "found_from": "control theory", "depth": 0},
            {"address": PAGE + "Control_theory_(disambiguation)", "source": "wikipedia", "found_from": "control theory", "depth": 0},
            {"address": PAGE + "AC/DC", "source": "wikipedia", "found_from": "control theory", "depth": 0}], "rejected": []})

    def test_a_disambiguation_page_is_kept_the_judgement_is_the_runners(self):
        found, _ = search(ok(fixture("wikipedia_search.json")))
        self.assertIn(PAGE + "Control_theory_(disambiguation)", [c["address"] for c in found["candidates"]])

    def test_what_comes_back_is_what_the_queue_takes(self):
        found, _ = search(ok(fixture("wikipedia_search.json")))
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            kw = {"canon_address": lambda a: a, "site_of": lambda h: ".".join(h.split(".")[-2:]), "now": NOW}
            for c in found["candidates"]:
                self.assertEqual(crawlqueue.enqueue(conn, c, limits={"queued_total": 10, "queued_per_domain": 10}, **kw), "queued")

    def test_an_empty_answer_is_no_candidate_and_no_refusal(self):
        self.assertEqual(search(ok(fixture("wikipedia_empty.json")))[0], {"candidates": [], "rejected": []})

    def test_a_title_becomes_the_address_of_its_page_with_the_marks_that_would_change_it_written_out(self):
        for title, path in (("Control theory", "Control_theory"), ("C#", "C%23"), ("What?", "What%3F"), ("100%", "100%25"),
                            ("Café", "Caf%C3%A9"), ("Straße", "Stra%C3%9Fe"), ("AT&T", "AT&T"), ("C++", "C++"),
                            ("Foo bar_baz", "Foo_bar_baz"), ("AC/DC", "AC/DC"), ("A (b), c; d: e!", "A_(b),_c;_d:_e!"),
                            ("Foo*bar", "Foo*bar"), ("$100", "$100"), ("a=b", "a=b"), ("me@home", "me@home"), ("O'Neil", "O'Neil"),
                            ("x[y]{z}|w", "x%5By%5D%7Bz%7D%7Cw"), ("a<b>c", "a%3Cb%3Ec"), ('say "hi"', "say_%22hi%22"), ("a\\b", "a%5Cb"),
                            ("日本語", "%E6%97%A5%E6%9C%AC%E8%AA%9E")):
            with self.subTest(title=title):
                found, _ = search(answer(page(title)))
                self.assertEqual([c["address"] for c in found["candidates"]], [PAGE + path])

    def test_a_page_that_is_not_an_article_with_an_id_and_a_clean_title_is_skipped(self):
        hidden = [chr(0x200B), chr(0x202E), chr(0x2066), chr(0xFEFF), "\n", "\t", chr(0), chr(7)]
        bad = [page("Talk page", ns=1), page("Category:X", ns=14), page("X", ns=None), page("X", ns="0"), page("X", ns=False), page("X", ns=0.0),
               {"ns": 0, "title": "X"}, page("X", pageid=0), page("X", pageid=-3), page("X", pageid=True), page("X", pageid="5"),
               page("X", pageid=1.5), page("X", pageid=None), {"ns": 0, "pageid": 3}, page(None, 4), page(5, 5), page(["X"], 6), page("", 7),
               page(" ", 8), page(" Control theory", 9), page("Control theory ", 10), page("Control  theory", 11), page("x" * 256, 12)]
        bad += [page("Con" + h + "trol", 20 + i) for i, h in enumerate(hidden)]
        found, _ = search(answer(*bad, page("Real article", 99)), limit=50)
        self.assertEqual([c["address"] for c in found["candidates"]], [PAGE + "Real_article"])

    def test_a_title_with_a_dot_part_between_slashes_is_skipped_so_the_address_stays_under_wiki(self):
        for title in ("..", ".", "../w/api.php", "a/../b", "a/./b", "./x", "x/..", "x/.", "a/b/../../c", "../../etc/passwd"):
            with self.subTest(title=title):
                found, _ = search(answer(page(title, 5), page("Real", 6)))
                self.assertEqual([c["address"] for c in found["candidates"]], [PAGE + "Real"])

    def test_a_title_with_dots_that_is_not_a_dot_part_is_taken(self):
        for title, path in (("...", "..."), ("a..b", "a..b"), ("Version 1.2", "Version_1.2"), ("a/.../b", "a/.../b"), ("a/..b", "a/..b"),
                            (".NET", ".NET"), ("AC/DC", "AC/DC")):
            with self.subTest(title=title):
                found, _ = search(answer(page(title, 5)))
                self.assertEqual([c["address"] for c in found["candidates"]], [PAGE + path])

    def test_a_title_of_255_characters_is_taken(self):
        found, _ = search(answer(page("x" * 255)))
        self.assertEqual(len(found["candidates"]), 1)

    def test_a_page_listed_twice_by_id_or_by_title_is_one_candidate(self):
        found, _ = search(answer(page("Control theory", 1), page("Control theory", 2), page("Other", 1), page("Another", 3)))
        self.assertEqual([c["address"] for c in found["candidates"]], [PAGE + "Control_theory", PAGE + "Another"])

    def test_the_query_that_found_a_page_is_kept_cleaned(self):
        found, _ = search(ok(fixture("wikipedia_search.json")), "  control   theory  ")
        self.assertEqual({c["found_from"] for c in found["candidates"]}, {"control theory"})

    def test_as_many_pages_as_were_asked_for_is_not_too_many_and_one_more_is_a_refusal(self):
        pages = [page(f"Page {i}", i) for i in range(1, 6)]
        self.assertEqual(len(search(answer(*pages), limit=5)[0]["candidates"]), 5)
        with self.assertRaises(srcopenalex.SourceRefused):
            search(answer(*pages, page("Page 6", 6)), limit=5)

    def test_what_the_answer_says_beyond_the_title_is_never_used(self):
        evil = dict(page("Control theory", 1), snippet="<script>x</script> http://evil.example/", redirecttitle="Evil")
        found, _ = search(answer(evil))
        self.assertEqual(sorted(found["candidates"][0]), ["address", "depth", "found_from", "source"])
        self.assertNotIn("evil", str(found).lower())


class RefusalTest(unittest.TestCase):
    def refused(self, reply, **kw):
        fake = Fake(reply)
        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            search(reply, fake=fake, **kw)
        return cm.exception, fake

    def test_a_429_that_shows_budget_left_is_still_a_refusal_for_the_day_here(self):
        """Only OpenAlex's own requests are told by `X-RateLimit-Remaining`; this source's refusal is for the day whatever the header says."""
        error, _ = self.refused((429, {"x-ratelimit-remaining": "9"}, b""))
        self.assertTrue(error.for_day)

    def test_the_refusal_is_the_one_every_source_raises_and_it_names_wikipedia(self):
        error, _ = self.refused(ok(b"", 429))
        self.assertIsInstance(error, srcopenalex.SourceRefused)
        self.assertIsInstance(error, KbError)
        self.assertTrue(str(error).startswith("Wikipedia: "), str(error))
        self.assertEqual(error.partial, {"candidates": [], "rejected": []})

    def test_a_status_other_than_200_is_a_refusal_that_names_it_and_asks_nothing_more(self):
        for status in (400, 401, 403, 404, 429, 500, 503, 301, 204):
            with self.subTest(status=status):
                error, fake = self.refused(ok(b"{}", status))
                self.assertIn(str(status), str(error))
                self.assertEqual(len(fake.calls), 1)

    def test_an_answer_that_is_not_the_expected_json_is_a_refusal(self):
        bad = [b"", b"<html>blocked</html>", b"not json", b"[]", b"null", b"{}", b'{"query": null}', b'{"query": []}', b'{"query": {}}',
               b'{"query": {"search": null}}', b'{"query": {"search": {}}}', b'{"query": {"search": [5]}}', b'{"query": {"search": ["x"]}}',
               b'{"query": {"search": []}, "query": {"search": []}}', b'{"query": {"search": []}, "x": NaN}', b"\xff\xfe{}",
               b"[" * 500000 + b"]" * 500000, b'{"query": {"search": [], "x": "\xff"}}']
        for body in bad:
            with self.subTest(body=body[:30]):
                self.refused(ok(body))

    def test_an_answer_that_reports_an_error_is_a_refusal_and_its_words_are_not_repeated(self):
        for top in ({"error": {"code": "ratelimited", "info": "SECRET-TOKEN-123"}}, {"errors": [{"code": "x", "text": "SECRET-TOKEN-123"}]},
                    {"error": "SECRET-TOKEN-123"}, {"error": None}):
            with self.subTest(top=top):
                error, _ = self.refused(answer(page("Control theory", 1), **top))
                self.assertNotIn("SECRET", str(error))
                self.assertNotIn("SECRET", error.reason)

    def test_an_answer_over_the_size_limit_is_a_refusal_and_the_limit_is_two_million_bytes(self):
        body = answer(page("Control theory", 1))[2]
        exact = body[:-1] + b" " * (2_000_000 - len(body)) + b"}"
        self.assertEqual(len(exact), 2_000_000)
        self.assertEqual(len(search(ok(exact))[0]["candidates"]), 1)
        self.refused(ok(exact + b" "))

    def test_a_body_that_is_not_bytes_and_a_status_that_is_not_a_number_are_refusals(self):
        for body in (None, "text", 5, ["x"]):
            with self.subTest(body=body):
                self.refused((200, {}, body))
        for status in (None, "200", 200.0, True):
            with self.subTest(status=status):
                self.refused((status, {}, fixture("wikipedia_empty.json")))

    def test_a_request_that_the_client_refuses_is_a_refusal_and_any_other_error_is_not_hidden(self):
        def fail(url):
            raise KbError("the address is not allowed")

        error, _ = self.refused(fail)
        self.assertTrue(str(error).startswith("Wikipedia: "))

        def crash(url):
            raise ZeroDivisionError()

        with self.assertRaises(ZeroDivisionError):
            search(crash)

    def test_a_refusal_that_the_client_itself_raises_is_named_for_wikipedia_too(self):
        def refuse(url):
            raise srcopenalex.SourceRefused("the pace was too fast")

        error, _ = self.refused(refuse)
        self.assertEqual(str(error), "Wikipedia: the pace was too fast")

    def test_the_reason_never_holds_what_the_server_sent(self):
        for reply in (ok(b"<html>SECRET-TOKEN-123 blocked</html>", 403), ok(b"SECRET-TOKEN-123"), ok(b'{"SECRET-TOKEN-123": 1}')):
            with self.subTest(reply=reply[2][:20]):
                error, _ = self.refused(reply)
                self.assertNotIn("SECRET", str(error))
                self.assertLessEqual(len(error.reason), 200)


if __name__ == "__main__":
    unittest.main()
