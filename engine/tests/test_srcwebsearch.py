"""A web search engine as a source of candidates for the unattended crawl (`kb/srcwebsearch.py`; `docs/specs/population.md`, "Discovery").

No test opens a socket: `get` is a fake. The fixtures in `fixtures/crawl/` are made by hand from what is known of the page that DuckDuckGo's HTML
search gives (its markup is not documented, and no page was fetched to make them: the plan's Result says so). The terms of use were read
on 2026-11-16 and are unresolved; the source is off unless the owner's plan switches it on."""

import re
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from engine.tests import ENGINE_DIR
from engine.tests.test_srcopenalex import Fake, query

from kb import KbError, crawlqueue, srcopenalex, srcwebsearch

FIXTURES = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawl"
NOW = "2026-11-16T10:00:00Z"
HTML = "text/html; charset=utf-8"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(body, status=200, ctype=HTML):
    return status, ({"content-type": ctype} if ctype else {}), body


def result(href, cls="result__a"):
    return f'<div class="result web-result"><h2 class="result__title"><a rel="nofollow" class="{cls}" href="{href}">title</a></h2></div>'


def redirect(target, host="//duckduckgo.com"):
    return f"{host}/l/?uddg={quote(target, safe='')}&amp;rut=ab"


def page(*results):
    return ('<!DOCTYPE html><html><body><div id="links" class="results">' + "".join(results) + "</div></body></html>").encode()


def search(reply, query_text="control theory", limit=10, fake=None):
    fake = fake or Fake(reply)
    return srcwebsearch.search(query_text, fake, limit), fake


def addresses(found):
    return [c["address"] for c in found["candidates"]]


class RequestTest(unittest.TestCase):
    def test_one_request_to_the_html_search_with_the_words_as_the_query_and_nothing_else(self):
        found, fake = search(ok(fixture("ddg_results.html")))
        self.assertEqual(len(fake.calls), 1)
        base, params = query(fake.urls[0])
        self.assertEqual((base, params), ("https://html.duckduckgo.com/html/", {"q": "control theory"}))

    def test_the_agent_is_honest_and_generic_and_nothing_that_would_tell_one_visit_from_another_is_sent(self):
        _, fake = search(ok(fixture("ddg_no_results.html")))
        url, headers, timeout = fake.calls[0]
        self.assertEqual(headers, {"User-Agent": srcopenalex.USER_AGENT, "Accept": "text/html"})
        self.assertNotIn("@", url + " ".join(headers.values()))
        self.assertEqual(timeout, 30)

    def test_only_plain_words_reach_the_search_so_that_a_bang_an_operator_or_a_quotation_cannot(self):
        hostile = '!g site:evil.example filetype:pdf "exact phrase" -word +must intitle:x (a OR b) \\bang ^caret *star ?q'
        _, fake = search(ok(fixture("ddg_no_results.html")), hostile)
        words = query(fake.urls[0])[1]["q"].split(" ")
        self.assertEqual(words[:6], ["g", "site", "evil", "example", "filetype", "pdf"])
        self.assertEqual(len(words), 12)
        self.assertTrue(all(re.fullmatch(r"[^\W_]+", w) for w in words))
        self.assertNotIn("%21", fake.urls[0])  # not even an exclamation mark

    def test_a_bang_alone_is_a_word(self):
        _, fake = search(ok(fixture("ddg_no_results.html")), "!w control theory")
        self.assertEqual(query(fake.urls[0])[1]["q"], "w control theory")

    def test_a_query_with_no_letter_or_digit_asks_nothing(self):
        for text in ("!!!", "---", "(  )", "+ - *", "_ _"):
            with self.subTest(query=text):
                fake = Fake(ok(fixture("ddg_no_results.html")))
                with self.assertRaises(KbError):
                    srcwebsearch.search(text, fake, 10)
                self.assertEqual(fake.calls, [])

    def test_the_query_and_the_limit_are_checked_and_nothing_is_asked_when_they_are_wrong(self):
        self.assertEqual(search(ok(fixture("ddg_no_results.html")), "x" * 300)[0]["candidates"], [])
        for text in ("", "   ", "a\x00b", "line\nbreak", "tab\there", "a\x7fb", "x" * 301, 5, None, b"x"):
            with self.subTest(query=text):
                fake = Fake(ok(fixture("ddg_no_results.html")))
                with self.assertRaises(KbError):
                    srcwebsearch.search(text, fake, 10)
                self.assertEqual(fake.calls, [])
        for limit in (0, -1, 31, 1.5, True, "5", None):
            with self.subTest(limit=limit):
                with self.assertRaises(KbError):
                    srcwebsearch.search("control theory", Fake(ok(fixture("ddg_no_results.html"))), limit)
        with self.assertRaises(KbError):
            srcwebsearch.search("control theory", "not a function", 10)


class ResolutionTest(unittest.TestCase):
    def test_the_fixture_gives_the_pages_it_links_to_and_nothing_else(self):
        found, _ = search(ok(fixture("ddg_results.html")))
        self.assertEqual(found, {"candidates": [
            {"address": "https://example.org/control/theory", "source": "web-search", "found_from": "control theory", "depth": 0},
            {"address": "https://example.net/guide?a=1&b=2", "source": "web-search", "found_from": "control theory", "depth": 0},
            {"address": "http://plain.example.com/page.pdf", "source": "web-search", "found_from": "control theory", "depth": 0}], "rejected": []})

    def test_what_comes_back_is_what_the_queue_takes(self):
        found, _ = search(ok(fixture("ddg_results.html")))
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            kw = {"canon_address": lambda a: a, "site_of": lambda h: ".".join(h.split(".")[-2:]), "now": NOW}
            for c in found["candidates"]:
                self.assertEqual(crawlqueue.enqueue(conn, c, limits={"queued_total": 10, "queued_per_domain": 10}, **kw), "queued")

    def test_the_limit_cuts_the_list_and_is_not_a_refusal(self):
        for limit, want in ((1, 1), (2, 2), (3, 3), (30, 3)):
            with self.subTest(limit=limit):
                self.assertEqual(len(search(ok(fixture("ddg_results.html")), limit=limit)[0]["candidates"]), want)

    def test_a_link_in_a_script_a_style_or_a_comment_is_not_a_result(self):
        body = page("<script>document.write('" + result("https://script.example/a") + "')</script>", "<style>" + result("https://style.example/a") + "</style>",
                    "<!-- " + result("https://comment.example/a") + " -->", result("https://real.example/a"))
        self.assertEqual(addresses(search(ok(body))[0]), ["https://real.example/a"])

    def test_only_the_title_link_of_a_result_counts_not_its_url_line_or_its_snippet(self):
        body = page(result("https://a.example/1", "result__url"), result("https://a.example/2", "result__snippet"), result("https://a.example/3", "result__a"),
                    result("https://a.example/4", "foo result__a bar"), result("https://a.example/5", "result__abc"), result("https://a.example/6", "xresult__a"),
                    result("https://a.example/7", "RESULT__A"), result("https://a.example/8", ""))
        self.assertEqual(addresses(search(ok(body))[0]), ["https://a.example/3", "https://a.example/4"])

    def test_a_link_in_an_advertisement_is_not_taken_even_when_it_goes_straight_to_the_advertiser_and_the_results_after_it_are(self):
        ad = '<div class="result results_links result--ad"><div class="inner"><div class="deeper">' + result("https://advertiser.example/buy") + "</div></div></div>"
        found, _ = search(ok(page(ad, result("https://real.example/a"), ad.replace("advertiser", "second"), result("https://real.example/b"))))
        self.assertEqual(addresses(found), ["https://real.example/a", "https://real.example/b"])

    def test_an_advertisement_is_told_by_the_start_of_a_class_and_a_link_after_an_inner_block_of_it_closes_is_still_in_it(self):
        for cls in ("result--ad", "result--ad--small", "result results_links result--ad extra", "x result--ad"):
            with self.subTest(cls=cls):
                ad = f'<div class="{cls}"><div>inner</div>' + result("https://advertiser.example/buy") + "</div>"
                self.assertEqual(addresses(search(ok(page(ad, result("https://real.example/a"))))[0]), ["https://real.example/a"])

    def test_a_class_that_only_has_the_letters_of_an_advertisement_in_it_is_not_one(self):
        body = page('<div class="loaded readable head adult">' + result("https://real.example/a") + "</div>")
        self.assertEqual(addresses(search(ok(body))[0]), ["https://real.example/a"])

    def test_an_advertisement_inside_an_advertisement_does_not_end_the_outer_one(self):
        ad = ('<div class="result--ad"><div class="result--ad"><div>x</div></div>' + result("https://outer.example/buy") + "</div>")
        self.assertEqual(addresses(search(ok(page(ad, result("https://real.example/a"))))[0]), ["https://real.example/a"])

    def test_a_noscript_inside_a_template_and_the_reverse_keep_their_links_hidden_to_the_end_of_the_outer_one(self):
        for outer, inner in (("template", "noscript"), ("noscript", "template"), ("noscript", "noscript")):
            with self.subTest(outer=outer, inner=inner):
                hidden = f"<{outer}><{inner}>x</{inner}>" + result("https://hidden.example/a") + f"</{outer}>"
                self.assertEqual(addresses(search(ok(page(hidden, result("https://real.example/a"))))[0]), ["https://real.example/a"])

    def test_a_page_of_only_advertisements_is_a_page_of_results_with_none_to_take(self):
        ad = '<div class="result result--ad">' + result("https://advertiser.example/buy") + "</div>"
        self.assertEqual(search(ok(page(ad)))[0], {"candidates": [], "rejected": []})

    def test_an_advertisement_that_is_never_closed_costs_the_results_after_it_and_not_a_wrong_one(self):
        found, _ = search(ok(b'<html><body><div class="result--ad">' + result("https://advertiser.example/buy").encode() + b"</body></html>"))
        self.assertEqual(found["candidates"], [])

    def test_a_link_in_a_noscript_or_a_template_is_not_a_result_and_a_title_or_a_textarea_is_text(self):
        for tag in ("noscript", "template"):
            with self.subTest(tag=tag):
                body = page(f"<{tag}>" + result("https://hidden.example/a") + f"</{tag}>", result("https://real.example/a"))
                self.assertEqual(addresses(search(ok(body))[0]), ["https://real.example/a"])
        for tag in ("title", "textarea"):
            with self.subTest(tag=tag):
                body = page(f"<{tag}>" + result("https://hidden.example/a") + f"</{tag}>", result("https://real.example/a"))
                self.assertEqual(addresses(search(ok(body))[0]), ["https://real.example/a"])

    def test_a_page_whose_only_links_are_in_a_noscript_is_not_a_page_of_results(self):
        with self.assertRaises(srcopenalex.SourceRefused):
            search(ok(page("<noscript>" + result("https://hidden.example/a") + "</noscript>")))

    def test_a_redirect_with_no_host_is_the_engines_redirect_too_and_any_other_link_with_no_host_is_not_a_link(self):
        target = quote("https://a.example/x", safe="")
        self.assertEqual(addresses(search(ok(page(result(f"/l/?uddg={target}&amp;rut=1"))))[0]), ["https://a.example/x"])
        for href in (f"/y.js?uddg={target}", f"/other/?uddg={target}", f"l/?uddg={target}", f"/l?uddg={target}", "/l/"):
            with self.subTest(href=href):
                self.assertEqual(addresses(search(ok(page(result(href))))[0]), [])

    def test_only_a_link_can_be_a_result_whatever_other_tag_carries_the_class(self):
        body = (b'<html><body><div class="result__a" href="https://div.example/a">x</div><span class="result__a" href="https://span.example/a">x</span>'
                b'<p class="result__a">p</p><link class="result__a" href="https://link.example/a"></body></html>')
        with self.assertRaises(srcopenalex.SourceRefused):
            search(ok(body))  # no result link at all: not a page of results
        both = body.replace(b"</body>", b'<a class="result__a" href="https://real.example/a">x</a></body>')
        self.assertEqual(addresses(search(ok(both))[0]), ["https://real.example/a"])  # and only the link is taken

    def test_a_link_with_a_host_that_cannot_be_read_is_skipped_and_the_page_is_still_read(self):
        found, _ = search(ok(page(result("https://[bad/x"), result("http://[::1/y"), result("https://good.example/z"))))
        self.assertEqual(addresses(found), ["https://good.example/z"])

    def test_a_link_to_the_engine_at_any_path_but_its_redirect_is_skipped_even_when_it_carries_the_parameter_of_the_redirect(self):
        target = quote("https://a.example/x", safe="")
        for host in ("//duckduckgo.com", "https://duckduckgo.com", "//html.duckduckgo.com", "//duck.com"):
            for path in ("/y.js", "/other", "/l", "/l/x", "/"):
                with self.subTest(href=host + path):
                    self.assertEqual(addresses(search(ok(page(result(f"{host}{path}?uddg={target}&amp;u3={target}"))))[0]), [])
        self.assertEqual(addresses(search(ok(page(result(f"//html.duckduckgo.com/l/?uddg={target}"))))[0]), ["https://a.example/x"])

    def test_the_address_asked_for_holds_no_space_and_no_mark_of_the_query_that_is_not_a_word(self):
        _, fake = search(ok(fixture("ddg_no_results.html")), "control theory of cafés & more")
        url = fake.urls[0]
        self.assertNotIn(" ", url)
        self.assertEqual(url, "https://html.duckduckgo.com/html/?q=control%20theory%20of%20caf%C3%A9s%20more")

    def test_the_target_of_a_redirect_is_read_in_its_forms_and_a_redirect_that_gives_none_is_skipped(self):
        good = [redirect("https://a.example/x"), redirect("https://a.example/y", "https://duckduckgo.com"), redirect("https://a.example/z", "http://duckduckgo.com"),
                "//duckduckgo.com/l/?rut=x&amp;uddg=" + quote("https://a.example/order", safe=""),
                "//duckduckgo.com/l/?uddg=" + quote("https://a.example/first", safe="") + "&amp;uddg=" + quote("https://a.example/second", safe="")]
        found, _ = search(ok(page(*[result(h) for h in good])))
        self.assertEqual(addresses(found), ["https://a.example/x", "https://a.example/y", "https://a.example/z", "https://a.example/order", "https://a.example/first"])
        for href in ("//duckduckgo.com/l/?rut=x", "//duckduckgo.com/l/", "//duckduckgo.com/l/?uddg=", "//duckduckgo.com/y.js?u3=" + quote("https://ad.example/", safe=""),
                     "//duckduckgo.com/l/?uddg=" + quote(quote("https://a.example/x", safe=""), safe="")):
            with self.subTest(href=href):
                self.assertEqual(addresses(search(ok(page(result(href))))[0]), [])

    def test_a_direct_link_is_taken_and_a_link_that_is_not_an_absolute_web_address_is_not(self):
        found, _ = search(ok(page(result("https://a.example/x?y=1&amp;z=2"), result("http://b.example/"))))
        self.assertEqual(addresses(found), ["https://a.example/x?y=1&z=2", "http://b.example/"])
        for href in ("/relative/path", "//a.example/x", "a.example/x", "mailto:a@b.example", "javascript:alert(1)", "ftp://a.example/x", "file:///etc/passwd",
                     "data:text/html,x", "", "#", "https://", "https:///x"):
            with self.subTest(href=href):
                self.assertEqual(addresses(search(ok(page(result(href))))[0]), [])

    def test_an_address_of_the_search_engine_or_one_that_is_not_a_plain_public_address_is_skipped(self):
        for target in ("https://duckduckgo.com/", "https://sub.duckduckgo.com/x", "https://DUCKDUCKGO.COM./x", "https://duck.com/x", "https://www.duck.co/x",
                       "javascript:alert(1)", "ftp://a.example/x", "http://127.0.0.1/a", "http://10.0.0.5/a", "http://169.254.169.254/a", "http://[::1]/a",
                       "http://localhost/a", "https://user:pw@a.example/x", "https://a.example/a b", "https://a.example/" + "a" * 2100,
                       "https://a.example/a\nb", "https://a.example/\x00"):
            with self.subTest(target=target[:40]):
                self.assertEqual(addresses(search(ok(page(result(redirect(target)))))[0]), [])
        self.assertEqual(addresses(search(ok(page(result(redirect("https://notduckduckgo.com/x")), result(redirect("https://duckduckgo.example/x")))))[0]),
                         ["https://notduckduckgo.com/x", "https://duckduckgo.example/x"])

    def test_a_page_listed_twice_is_one_candidate_and_the_order_is_the_pages(self):
        found, _ = search(ok(page(result(redirect("https://a.example/1")), result(redirect("https://b.example/2")), result(redirect("https://a.example/1")))))
        self.assertEqual(addresses(found), ["https://a.example/1", "https://b.example/2"])

    def test_a_page_of_results_that_gives_no_usable_address_is_no_candidate_and_no_refusal(self):
        found, _ = search(ok(page(result("//duckduckgo.com/y.js?u3=x"), result("javascript:alert(1)"))))
        self.assertEqual(found, {"candidates": [], "rejected": []})

    def test_the_query_that_found_a_page_is_kept_cleaned(self):
        found, _ = search(ok(fixture("ddg_results.html")), "  control   theory  ")
        self.assertEqual({c["found_from"] for c in found["candidates"]}, {"control theory"})

    def test_what_the_page_says_beyond_the_links_is_never_used(self):
        found, _ = search(ok(fixture("ddg_results.html")))
        self.assertEqual({tuple(sorted(c)) for c in found["candidates"]}, {("address", "depth", "found_from", "source")})
        self.assertNotIn("script.example", str(found))
        self.assertNotIn("ads.example", str(found))


class RefusalTest(unittest.TestCase):
    def refused(self, reply, **kw):
        fake = Fake(reply)
        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            search(reply, fake=fake, **kw)
        return cm.exception, fake

    def test_the_refusal_is_the_one_every_source_raises_and_it_names_the_engine(self):
        error, _ = self.refused(ok(b"", 429))
        self.assertIsInstance(error, srcopenalex.SourceRefused)
        self.assertIsInstance(error, KbError)
        self.assertTrue(str(error).startswith("DuckDuckGo: "), str(error))
        self.assertEqual(error.partial, {"candidates": [], "rejected": []})

    def test_a_status_other_than_200_is_a_refusal_that_names_it_and_asks_nothing_more(self):
        for status in (202, 204, 301, 302, 400, 401, 403, 404, 418, 429, 500, 503):
            with self.subTest(status=status):
                error, fake = self.refused(ok(fixture("ddg_results.html"), status))
                self.assertIn(str(status), str(error))
                self.assertEqual(len(fake.calls), 1)

    def test_a_page_that_asks_for_a_challenge_is_a_refusal_on_any_status_and_the_pages_words_are_not_repeated(self):
        for status in (200, 202, 403):
            with self.subTest(status=status):
                error, _ = self.refused(ok(fixture("ddg_challenge.html"), status))
                self.assertNotIn("bots", str(error))
                self.assertNotIn("human", str(error))
        error, _ = self.refused(ok(fixture("ddg_challenge.html")))
        self.assertIn("challenge", str(error))

    def test_a_challenge_among_results_is_a_refusal_whatever_else_is_on_the_page(self):
        both = page(result(redirect("https://a.example/x"))).replace(b"</body>", b'<form id="challenge-form"></form></body>')
        self.refused(ok(both))
        both = page(result(redirect("https://a.example/x"))).replace(b"</body>", b'<div class="anomaly-modal__modal"></div></body>')
        self.refused(ok(both))

    def test_a_page_that_is_not_a_page_of_results_is_a_refusal_so_that_a_changed_page_turns_the_source_off(self):
        for body in (fixture("ddg_changed.html"), b"", b"not html at all", b"<html></html>", b"<a href='https://a.example/'>a link outside a result</a>",
                     page(result("https://a.example/x", "result__title")), b'<div class="no-results-here">no</div>'):
            with self.subTest(body=body[:30]):
                self.refused(ok(body))

    def test_a_page_with_no_results_is_not_a_refusal(self):
        self.assertEqual(search(ok(fixture("ddg_no_results.html")))[0], {"candidates": [], "rejected": []})

    def test_the_content_type_is_checked_when_it_is_there(self):
        for ctype in ("application/json", "text/plain", "application/xml", "image/png", "text/htmlx"):
            with self.subTest(ctype=ctype):
                self.refused(ok(fixture("ddg_no_results.html"), ctype=ctype))
        for ctype in ("text/html", "text/html; charset=utf-8", "TEXT/HTML", "text/html ; charset=UTF-8", "application/xhtml+xml", None):
            with self.subTest(ctype=ctype):
                self.assertEqual(search(ok(fixture("ddg_no_results.html"), ctype=ctype))[0]["candidates"], [])
        self.refused((200, {"content-type": 5}, fixture("ddg_no_results.html")))
        self.refused((200, {"Content-Type": "text/plain"}, fixture("ddg_no_results.html")))
        self.assertEqual(search((200, None, fixture("ddg_no_results.html")))[0]["candidates"], [])

    def test_an_answer_of_exactly_a_million_bytes_is_taken_and_one_byte_more_is_not(self):
        body = fixture("ddg_no_results.html")
        exact = body + b" " * (1_000_000 - len(body))
        self.assertEqual(len(exact), 1_000_000)
        self.assertEqual(search(ok(exact))[0]["candidates"], [])
        self.refused(ok(exact + b" "))

    def test_a_page_of_over_50000_tags_is_a_refusal_and_one_of_exactly_that_is_taken(self):
        body = fixture("ddg_no_results.html")
        filler = 50_000 - body.count(b"<")
        self.assertEqual(search(ok(body + b"<i/>" * filler))[0]["candidates"], [])
        self.refused(ok(body + b"<i/>" * (filler + 1)))

    def test_text_that_is_not_utf_8_or_holds_a_nul_is_a_refusal(self):
        self.refused(ok(fixture("ddg_no_results.html") + bytes([0xFF])))
        self.refused(ok(fixture("ddg_no_results.html") + bytes([0])))

    def test_a_body_that_is_not_bytes_and_a_status_that_is_not_a_number_are_refusals(self):
        for body in (None, "text", 5, ["x"]):
            with self.subTest(body=body):
                self.refused((200, {}, body))
        for status in (None, "200", 200.0, True):
            with self.subTest(status=status):
                self.refused((status, {}, fixture("ddg_no_results.html")))

    def test_garbage_is_a_refusal_or_gives_only_addresses_that_are_in_it_and_never_another_kind_of_error(self):
        for body in (b"<" * 1000, b"<a " * 5000, b"&" * 5000, b"<!--" * 100, b"<![CDATA[" * 50, b"<a class='result__a' href='" * 50,
                     b"<a class=result__a href=", b"<!DOCTYPE", b"<?xml", b"<![if", b"</" * 100, b"<a class='result__a' href=\"https://a.example/" * 3,
                     b"<a class='result__a' href=\"https://a.example/x\"", b"<a class='result__a' href=\"https://a.example/x\">" * 40):
            with self.subTest(body=body[:20]):
                try:
                    found = search(ok(body))[0]
                except srcopenalex.SourceRefused:
                    continue
                for address in addresses(found):
                    self.assertRegex(address, r"^https?://")
                    self.assertIn(address.encode(), body)

    def test_a_request_that_the_client_refuses_is_a_refusal_and_any_other_error_is_not_hidden(self):
        def fail(url):
            raise KbError("the address is not allowed")

        error, _ = self.refused(fail)
        self.assertTrue(str(error).startswith("DuckDuckGo: "))

        def crash(url):
            raise ZeroDivisionError()

        with self.assertRaises(ZeroDivisionError):
            search(crash)

    def test_a_refusal_that_the_client_itself_raises_is_named_for_the_engine_and_keeps_its_reason(self):
        def refuse(url):
            raise srcopenalex.SourceRefused("the pace was too fast")

        error, _ = self.refused(refuse)
        self.assertEqual(str(error), "DuckDuckGo: the pace was too fast")

    def test_the_reason_never_holds_what_the_server_sent(self):
        for reply in (ok(b"<html>SECRET-TOKEN-123 blocked</html>", 403), ok(b"SECRET-TOKEN-123"), ok(b'<div class="SECRET-TOKEN-123"></div>')):
            with self.subTest(reply=reply[2][:20]):
                error, _ = self.refused(reply)
                self.assertNotIn("SECRET", str(error))
                self.assertLessEqual(len(error.reason), 200)

    def test_a_refusal_is_never_retried_or_worked_round(self):
        for reply in (ok(fixture("ddg_challenge.html"), 202), ok(b"", 429), ok(fixture("ddg_changed.html"))):
            _, fake = self.refused(reply)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(set(fake.calls[0][1]), {"User-Agent", "Accept"})


if __name__ == "__main__":
    unittest.main()
