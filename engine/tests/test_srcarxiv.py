"""arXiv search as a source of candidates for the unattended crawl (`kb/srcarxiv.py`; `docs/specs/population.md`, "Discovery").

No test opens a socket or waits: `get` is a fake, and the clock and the sleep of the pacer are fakes. The fixtures in `fixtures/crawl/` are
made by hand from arXiv's user manual (`info.arxiv.org/help/api/user-manual.html`, read on 2026-11-16; the plan's Result holds the hashes)."""

import re
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from engine.tests import ENGINE_DIR
from engine.tests.test_srcopenalex import Fake, query

from kb import KbError, capture_arxiv, crawlqueue, srcarxiv, srcopenalex

FIXTURES = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawl"
NOW = "2026-11-16T10:00:00Z"
ATOM = "application/atom+xml; charset=utf-8"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(body, status=200, ctype=ATOM):
    return status, ({"content-type": ctype} if ctype else {}), body


def entry(ident, title="A paper"):
    return (f"<entry><id>{ident}</id><updated>2024-01-01T00:00:00Z</updated><published>2024-01-01T00:00:00Z</published>"
            f"<title>{title}</title><summary>s</summary><author><name>A B</name></author></entry>")


def feed(*entries, extra=""):
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><title>q</title><id>http://arxiv.org/api/abc</id>'
            f'<opensearch:totalResults>{len(entries)}</opensearch:totalResults>{extra}' + "".join(entries) + "</feed>").encode()


class Clock:
    """A clock and a sleep that agree: sleeping moves the clock. Every sleep is kept."""

    def __init__(self, start=1000.0):
        self.now, self.slept, self.events = start, [], []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.events.append(("sleep", seconds))
        self.now += seconds


def pacer(clock=None):
    clock = clock or Clock()
    return srcarxiv.Pacer(3.0, clock=clock, sleep=clock.sleep), clock


def search(body, query_text="control theory", limit=10, pace=None, fake=None):
    fake = fake or Fake(body)
    return srcarxiv.search(query_text, fake, limit, pace or pacer()[0]), fake


class RequestTest(unittest.TestCase):
    def test_one_request_to_the_arxiv_api_with_the_words_as_field_terms_and_the_paging_the_manual_names(self):
        found, fake = search(ok(fixture("arxiv_search.xml")))
        self.assertEqual(len(fake.calls), 1)
        base, params = query(fake.urls[0])
        self.assertEqual(base, "https://export.arxiv.org/api/query")
        self.assertEqual(params, {"search_query": "all:control AND all:theory", "start": "0", "max_results": "10",
                                  "sortBy": "relevance", "sortOrder": "descending"})

    def test_the_agent_is_honest_and_generic_and_no_address_or_key_is_sent(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")))
        url, headers, timeout = fake.calls[0]
        self.assertEqual(headers["User-Agent"], srcopenalex.USER_AGENT)
        self.assertEqual(headers["Accept"], "application/atom+xml")
        self.assertNotIn("@", url + " ".join(headers.values()))
        self.assertNotIn("Authorization", headers)
        self.assertEqual(timeout, 30)

    def test_only_plain_words_reach_the_search_whatever_the_query_holds(self):
        hostile = 'control AND theory; ti:evil OR au:x site:y "quoted" ANDNOT (a OR b) -c +d *e ?f ~g ^h'
        _, fake = search(ok(fixture("arxiv_empty.xml")), hostile)
        terms = query(fake.urls[0])[1]["search_query"].split(" AND ")
        self.assertTrue(all(re.fullmatch(r"all:[^\W_]+", t) for t in terms), terms)
        self.assertEqual(terms, ["all:control", "all:theory", "all:ti"])  # the operator words AND and OR are stop words; `ti` is a word to look for
        self.assertEqual(len(terms), 3)

    def test_at_most_three_terms_are_sent_and_one_is_enough(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "one two three four five six seven eight nine ten")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:one AND all:two AND all:three")
        _, fake = search(ok(fixture("arxiv_empty.xml")), "kalman")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:kalman")

    def test_the_small_words_of_a_phrase_are_not_asked_for(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "FPGA architecture and design flow overview")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:FPGA AND all:architecture AND all:design")
        _, fake = search(ok(fixture("arxiv_empty.xml")), "The Theory OF Computation")  # a stop word is known in any case, and the words keep the case they had
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:Theory AND all:Computation")

    def test_the_words_that_topics_put_in_front_of_a_subject_are_not_asked_for(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "advanced principles of radio frequency engineering and circuit design")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:radio AND all:frequency AND all:engineering")
        _, fake = search(ok(fixture("arxiv_empty.xml")), "comparative analysis of ngspice and LTspice for circuit simulation")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:ngspice AND all:LTspice AND all:circuit")
        _, fake = search(ok(fixture("arxiv_empty.xml")), "relational database theory textbook introduction")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:relational AND all:database AND all:theory")

    def test_every_word_of_the_stop_list_is_dropped_wherever_it_stands(self):
        stop = ("a an and are as at be by for from in into is it of on or the their to with using via toward towards "
                "textbooks textbook overview introduction advanced principles fundamentals comparative analysis").split()
        self.assertEqual(len(stop), 34)
        for word in stop:
            with self.subTest(word=word):
                _, fake = search(ok(fixture("arxiv_empty.xml")), f"{word} kalman filter control")
                self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:kalman AND all:filter AND all:control")

    def test_a_stop_word_is_a_whole_word_and_not_a_part_of_one(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "android theory island")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:android AND all:theory AND all:island")

    def test_a_query_of_stop_words_alone_keeps_its_first_word(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "and of the")
        self.assertEqual(query(fake.urls[0])[1]["search_query"], "all:and")

    def test_the_same_phrase_always_makes_the_same_request(self):
        urls = [search(ok(fixture("arxiv_empty.xml")), "history of algebra from arithmetic to abstract structures")[1].urls[0] for _ in range(3)]
        self.assertEqual(len(set(urls)), 1)
        self.assertEqual(query(urls[0])[1]["search_query"], "all:history AND all:algebra AND all:arithmetic")

    def test_a_word_is_letters_and_digits_of_any_alphabet_and_the_marks_are_cut(self):
        _, fake = search(ok(fixture("arxiv_empty.xml")), "régulation optimale C++ k-means 3.5 snake_case")
        terms = query(fake.urls[0])[1]["search_query"].split(" AND ")
        self.assertEqual(terms, ["all:régulation", "all:optimale", "all:C"])  # the marks are cut before the words are chosen: `k`, `means`, `3`, `5` and `snake` would follow

    def test_a_query_with_no_letter_or_digit_asks_nothing(self):
        for text in ("!!!", "---", "(  )", "+ - *", "_ _"):
            with self.subTest(query=text):
                fake = Fake(ok(fixture("arxiv_empty.xml")))
                with self.assertRaises(KbError):
                    srcarxiv.search(text, fake, 10, pacer()[0])
                self.assertEqual(fake.calls, [])

    def test_the_query_and_the_limit_are_checked_and_nothing_is_asked_nor_waited_for_when_they_are_wrong(self):
        self.assertEqual(search(ok(fixture("arxiv_empty.xml")), "x" * 300)[0]["candidates"], [])
        for text in ("", "   ", "a\x00b", "line\nbreak", "tab\there", "a\x1fb", "a\x7fb", "x" * 301, 5, None, b"x"):
            with self.subTest(query=text):
                fake, (pace, clock) = Fake(ok(fixture("arxiv_empty.xml"))), pacer()
                with self.assertRaises(KbError):
                    srcarxiv.search(text, fake, 10, pace)
                self.assertEqual((fake.calls, clock.events), ([], []))
        for limit in (0, -1, 51, 1.5, True, "5", None):
            with self.subTest(limit=limit):
                with self.assertRaises(KbError):
                    srcarxiv.search("control theory", Fake(ok(fixture("arxiv_empty.xml"))), limit, pacer()[0])
        fake = Fake(ok(fixture("arxiv_empty.xml")))
        for limit in (1, 50):
            srcarxiv.search("control theory", fake, limit, pacer()[0])
        self.assertEqual([query(u)[1]["max_results"] for u in fake.urls], ["1", "50"])

    def test_get_and_the_pacer_must_be_what_they_are_said_to_be(self):
        with self.assertRaises(KbError):
            srcarxiv.search("control theory", "not a function", 10, pacer()[0])
        for bad in (None, 3, "wait", object()):
            with self.subTest(pacer=bad):
                fake = Fake(ok(fixture("arxiv_empty.xml")))
                with self.assertRaises(KbError):
                    srcarxiv.search("control theory", fake, 10, bad)
                self.assertEqual(fake.calls, [])


class ResolutionTest(unittest.TestCase):
    def test_the_fixture_gives_two_papers_without_their_versions_and_skips_the_repeat_and_the_bad_id(self):
        found, _ = search(ok(fixture("arxiv_search.xml")))
        self.assertEqual(found, {"candidates": [
            {"address": "https://arxiv.org/abs/2401.00001", "identity_key": "arxiv:2401.00001", "source": "arxiv",
             "found_from": "control theory", "depth": 0},
            {"address": "https://arxiv.org/abs/hep-ex/0307015", "identity_key": "arxiv:hep-ex/0307015", "source": "arxiv",
             "found_from": "control theory", "depth": 0}], "rejected": []})

    def test_what_comes_back_is_what_the_queue_takes(self):
        found, _ = search(ok(fixture("arxiv_search.xml")))
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            kw = {"canon_address": lambda a: a, "site_of": lambda h: ".".join(h.split(".")[-2:]), "now": NOW}
            for c in found["candidates"]:
                self.assertEqual(crawlqueue.enqueue(conn, c, limits={"queued_total": 10, "queued_per_domain": 10}, **kw), "queued")

    def test_an_empty_answer_is_no_candidate_and_no_refusal(self):
        found, _ = search(ok(fixture("arxiv_empty.xml")))
        self.assertEqual(found, {"candidates": [], "rejected": []})

    def test_the_forms_of_an_id_that_are_taken(self):
        for ident, want in (("http://arxiv.org/abs/2401.00001v3", "2401.00001"), ("https://arxiv.org/abs/2401.00001v3", "2401.00001"),
                            ("http://arxiv.org/abs/2401.00001", "2401.00001"), ("  http://arxiv.org/abs/2401.00001v1\n  ", "2401.00001"),
                            ("http://arxiv.org/abs/cs/0112017v2", "cs/0112017"), ("http://arxiv.org/abs/math.GT/0309136v1", "math.GT/0309136")):
            with self.subTest(id=ident):
                found, _ = search(ok(feed(entry(ident))))
                self.assertEqual([c["identity_key"] for c in found["candidates"]], ["arxiv:" + want])

    def test_an_id_that_is_not_an_arxiv_paper_address_is_skipped(self):
        for ident in ("http://evil.example/abs/2401.00001v1", "http://arxiv.org.evil.example/abs/2401.00001v1",
                      "http://notarxiv.org/abs/2401.00001v1", "http://arxivXorg/abs/2401.00001v1", "http://arxiv.org/abs/2401.00001v1/../../x", "http://arxiv.org/abs/2413.00001v1",
                      "ftp://arxiv.org/abs/2401.00001v1", "http://arxiv.org/pdf/2401.00001v1", "http://arxiv.org/abs/",
                      "http://arxiv.org/abs/2401.00001v1?x=1", "http://arxiv.org/abs/2401.00001v1#x", "http://user@arxiv.org/abs/2401.00001v1",
                      "http://arxiv.org:8080/abs/2401.00001v1", "2401.00001v1", "arxiv:2401.00001", "", "http://arxiv.org/abs/2401.00001v1 x",
                      "http://arxiv.org/abs/" + "1" * 5000):
            with self.subTest(id=ident[:50]):
                found, _ = search(ok(feed(entry(ident))))
                self.assertEqual(found["candidates"], [])

    def test_the_query_that_found_a_paper_is_kept_cleaned(self):
        found, _ = search(ok(fixture("arxiv_search.xml")), "  control   theory  ")
        self.assertEqual({c["found_from"] for c in found["candidates"]}, {"control theory"})

    def test_a_repeat_under_another_version_is_taken_once_in_the_order_of_the_answer(self):
        found, _ = search(ok(feed(entry("http://arxiv.org/abs/2401.00001v2"), entry("http://arxiv.org/abs/2402.00002v1"),
                                  entry("http://arxiv.org/abs/2401.00001v1"))))
        self.assertEqual([c["identity_key"] for c in found["candidates"]], ["arxiv:2401.00001", "arxiv:2402.00002"])

    def test_as_many_entries_as_were_asked_for_is_not_too_many_and_one_more_is_a_refusal(self):
        ids = [f"http://arxiv.org/abs/2401.{i:05d}v1" for i in range(1, 6)]
        found, _ = search(ok(feed(*[entry(i) for i in ids])), limit=5)
        self.assertEqual(len(found["candidates"]), 5)
        with self.assertRaises(srcopenalex.SourceRefused):
            search(ok(feed(*[entry(i) for i in ids] + [entry("http://arxiv.org/abs/2401.00099v1")])), limit=5)

    def test_what_the_entries_say_beyond_the_id_is_never_used(self):
        evil = entry("http://arxiv.org/abs/2401.00001v1", title="<script>alert(1)</script> http://evil.example/x")
        found, _ = search(ok(feed(evil)))
        self.assertEqual(sorted(found["candidates"][0]), ["address", "depth", "found_from", "identity_key", "source"])
        self.assertNotIn("evil", str(found))


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

    def test_the_refusal_is_the_one_every_source_raises_and_it_names_arxiv(self):
        error, _ = self.refused(ok(b"", 429))
        self.assertIsInstance(error, srcopenalex.SourceRefused)
        self.assertIsInstance(error, KbError)
        self.assertTrue(str(error).startswith("arXiv: "), str(error))
        self.assertEqual(error.partial, {"candidates": [], "rejected": []})

    def test_a_status_other_than_200_is_a_refusal_that_names_it_and_asks_nothing_more(self):
        for status in (400, 401, 403, 404, 429, 500, 503, 301, 204):
            with self.subTest(status=status):
                error, fake = self.refused(ok(feed(), status))
                self.assertIn(str(status), str(error))
                self.assertEqual(len(fake.calls), 1)

    def test_an_answer_that_is_not_an_atom_feed_is_a_refusal(self):
        bad = [b"", b"not xml", b"<html><body>blocked</body></html>", b"<feed>", b"<feed xmlns='http://example.org/ns'></feed>",
               b"<?xml version='1.0'?><rss version='2.0'><channel/></rss>", b"[]", b"{}", b"\xff\xfe<\x00f\x00>\x00"]
        for body in bad:
            with self.subTest(body=body[:30]):
                self.refused(ok(body))

    def test_a_declaration_a_nul_or_text_that_is_not_utf_8_is_refused_as_the_capture_refuses_it(self):
        bodies = [b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY x "y">]><feed xmlns="http://www.w3.org/2005/Atom">&x;</feed>',
                  b'<?xml version="1.0"?><!doctype feed><feed xmlns="http://www.w3.org/2005/Atom"/>',
                  b'<?xml version="1.0"?><!ENTITY a "b"><feed xmlns="http://www.w3.org/2005/Atom"/>',
                  b'<?xml version="1.0"?><!DOCTYPE feed><feed xmlns="http://www.w3.org/2005/Atom"/>',
                  b'<?xml version="1.0"?><!DOCTYPE feed SYSTEM "http://evil.example/x.dtd"><feed xmlns="http://www.w3.org/2005/Atom"/>',
                  ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE feed [<!ENTITY x "y">]><feed xmlns="http://www.w3.org/2005/Atom">&x;'
                   '</feed>').encode("utf-16-le"),
                  '<?xml version="1.0" encoding="ISO-8859-1"?><feed xmlns="http://www.w3.org/2005/Atom"><title>caf\u00e9</title></feed>'
                  .encode("latin-1"),
                  b'<feed xmlns="http://www.w3.org/2005/Atom">' + bytes([0]) + b"</feed>",
                  '<feed xmlns="http://www.w3.org/2005/Atom"><title>'.encode() + bytes([0xff]) + b"</title></feed>",
                  '<?xml version="1.0" encoding="UTF-16"?><feed xmlns="http://www.w3.org/2005/Atom"/>'.encode("utf-16")]
        for body in bodies:
            with self.subTest(body=body[:40]):
                self.refused(ok(body))
                with self.assertRaises(Exception):  # the capture's own reader says no to the same bodies
                    capture_arxiv.parse_atom(body, "2401.00001", None)

    def test_a_refusal_that_the_client_raises_is_named_for_arxiv_and_keeps_its_reason(self):
        def refuse(url):
            raise srcopenalex.SourceRefused("the pace was too fast")

        error, _ = self.refused(refuse)
        self.assertEqual(str(error), "arXiv: the pace was too fast")

    def test_a_feed_with_over_20000_tags_is_a_refusal_wide_or_deep_and_under_the_size_limit(self):
        deep = b'<feed xmlns="http://www.w3.org/2005/Atom">' + b"<a>" * 100000 + b"</a>" * 100000 + b"</feed>"
        wide = b'<feed xmlns="http://www.w3.org/2005/Atom">' + b"<a/>" * 100000 + b"</feed>"
        for body in (deep, wide):
            self.assertLess(len(body), 1_000_000)  # the tag limit refuses them, not the size limit
            self.refused(ok(body))

    def test_a_feed_of_exactly_20000_tags_is_taken_and_one_more_is_not(self):
        head, tail = b'<feed xmlns="http://www.w3.org/2005/Atom">', b"</feed>"
        exact = head + b"<a/>" * 19998 + tail
        self.assertEqual(exact.count(b"<"), 20000)
        self.assertEqual(search(ok(exact))[0]["candidates"], [])
        self.refused(ok(head + b"<a/>" * 19999 + tail))

    def test_arxivs_own_error_entry_is_a_refusal_and_its_words_are_not_repeated(self):
        error, _ = self.refused(ok(fixture("arxiv_error.xml")))
        self.assertNotIn("1234.12345", str(error))
        self.assertNotIn("incorrect", str(error))

    def test_an_error_entry_among_papers_is_a_refusal_too(self):
        self.refused(ok(feed(entry("http://arxiv.org/abs/2401.00001v1"), entry("http://arxiv.org/api/errors#x"))))

    def test_the_content_type_is_checked_when_it_is_there(self):
        for ctype in ("text/html", "application/json", "text/plain", "application/atom+xml.evil", "image/png"):
            with self.subTest(ctype=ctype):
                self.refused(ok(fixture("arxiv_empty.xml"), ctype=ctype))
        for ctype in ("application/atom+xml", "application/atom+xml; charset=utf-8", "APPLICATION/ATOM+XML", "application/xml", "text/xml",
                      "text/xml; charset=UTF-8", None):
            with self.subTest(ctype=ctype):
                self.assertEqual(search(ok(fixture("arxiv_empty.xml"), ctype=ctype))[0]["candidates"], [])

    def test_the_name_of_the_content_type_header_is_read_in_any_case_and_its_value_with_spaces_round_the_parameters(self):
        for name in ("Content-Type", "CONTENT-TYPE", "content-type"):
            with self.subTest(name=name):
                self.refused((200, {name: "text/html"}, fixture("arxiv_empty.xml")))
        found, _ = search((200, {"content-type": "application/atom+xml ; charset=utf-8"}, fixture("arxiv_empty.xml")))
        self.assertEqual(found["candidates"], [])
        found, _ = search((200, {"content-type": "  text/xml  "}, fixture("arxiv_empty.xml")))
        self.assertEqual(found["candidates"], [])

    def test_headers_that_are_not_a_mapping_are_taken_as_none_and_a_content_type_that_is_not_text_is_a_refusal(self):
        self.assertEqual(search((200, None, fixture("arxiv_empty.xml")))[0]["candidates"], [])
        self.refused((200, {"content-type": 5}, fixture("arxiv_empty.xml")))
        self.assertEqual(search((200, {"Content-Type": ATOM}, fixture("arxiv_empty.xml")))[0]["candidates"], [])

    def test_an_answer_of_exactly_a_million_bytes_is_taken_and_one_byte_more_is_not(self):
        body = feed()
        exact = body[:-7] + b" " * (1_000_000 - len(body)) + b"</feed>"
        self.assertEqual(len(exact), 1_000_000)
        self.assertEqual(search(ok(exact))[0]["candidates"], [])
        self.refused(ok(exact + b" "))

    def test_a_body_that_is_not_bytes_and_a_status_that_is_not_a_number_are_refusals(self):
        for body in (None, "text", 5, ["x"]):
            with self.subTest(body=body):
                self.refused((200, {}, body))
        for status in (None, "200", 200.0, True):
            with self.subTest(status=status):
                self.refused((status, {}, fixture("arxiv_empty.xml")))

    def test_a_request_that_the_client_refuses_is_a_refusal_and_any_other_error_is_not_hidden(self):
        def fail(url):
            raise KbError("the address is not allowed")

        self.refused(fail)

        def crash(url):
            raise ZeroDivisionError()

        with self.assertRaises(ZeroDivisionError):
            search(crash)

    def test_the_reason_never_holds_what_the_server_sent(self):
        for reply in (ok(b"<html>SECRET-TOKEN-123 blocked</html>", 403), ok(b"SECRET-TOKEN-123"),
                      ok(b"<feed xmlns='http://www.w3.org/2005/Atom'><SECRET-TOKEN-123/>")):
            with self.subTest(reply=reply[2][:20]):
                error, _ = self.refused(reply)
                self.assertNotIn("SECRET", str(error))
                self.assertNotIn("SECRET", error.reason)
                self.assertLessEqual(len(error.reason), 200)


class PacerTest(unittest.TestCase):
    def test_the_first_request_waits_for_nothing(self):
        pace, clock = pacer()
        pace.wait()
        self.assertEqual(clock.slept, [])

    def test_a_second_request_at_once_waits_the_whole_pause(self):
        pace, clock = pacer()
        pace.wait()
        pace.wait()
        self.assertEqual(clock.slept, [3.0])

    def test_a_request_after_part_of_the_pause_waits_for_the_rest_and_one_after_all_of_it_waits_for_nothing(self):
        pace, clock = pacer()
        pace.wait()
        clock.now += 1.0
        pace.wait()
        self.assertEqual(clock.slept, [2.0])
        clock.now += 3.0
        pace.wait()
        self.assertEqual(clock.slept, [2.0])
        clock.now += 100.0
        pace.wait()
        self.assertEqual(clock.slept, [2.0])

    def test_a_wait_that_slept_is_the_start_of_the_next_pause(self):
        pace, clock = pacer()
        pace.wait()
        pace.wait()
        pace.wait()
        pace.wait()
        self.assertEqual(clock.slept, [3.0, 3.0, 3.0])
        self.assertEqual(clock.now, 1009.0)

    def test_the_pause_is_counted_from_the_start_of_the_last_request(self):
        pace, clock = pacer()
        pace.wait()
        clock.now += 2.9
        pace.wait()
        self.assertEqual([round(s, 6) for s in clock.slept], [0.1])
        clock.now += 3.0
        pace.wait()
        self.assertEqual(len(clock.slept), 1)

    def test_a_clock_that_goes_back_never_makes_it_wait_longer_than_the_pause(self):
        pace, clock = pacer()
        pace.wait()
        clock.now -= 500.0
        pace.wait()
        self.assertEqual(clock.slept, [3.0])

    def test_the_pause_cannot_be_set_under_the_three_seconds_arxiv_asks_for(self):
        for gap in (0, 2.9, -1, 2, True, "3", None, float("nan"), float("inf"), 3601):
            with self.subTest(gap=gap):
                with self.assertRaises(KbError):
                    srcarxiv.Pacer(gap)
        srcarxiv.Pacer(3)
        srcarxiv.Pacer(60.5)
        srcarxiv.Pacer(3600)

    def test_the_clock_and_the_sleep_must_be_functions(self):
        for kw in ({"clock": 5}, {"sleep": "later"}, {"clock": None}, {"sleep": None}):
            with self.subTest(kw=kw):
                with self.assertRaises(KbError):
                    srcarxiv.Pacer(3.0, **kw)

    def test_a_search_waits_before_each_request_and_never_after_it(self):
        pace, clock = pacer()
        order = []
        fake = Fake(lambda url: (order.append("get"), ok(fixture("arxiv_empty.xml")))[1])
        clock.events = order  # the sleeps and the requests, in one list
        srcarxiv.search("control theory", fake, 10, pace)
        srcarxiv.search("control theory", fake, 10, pace)
        srcarxiv.search("control theory", fake, 10, pace)
        self.assertEqual(order, ["get", ("sleep", 3.0), "get", ("sleep", 3.0), "get"])

    def test_a_refused_request_still_counts_for_the_pause(self):
        pace, clock = pacer()
        fake = Fake(ok(b"", 429))
        with self.assertRaises(srcopenalex.SourceRefused):
            srcarxiv.search("control theory", fake, 10, pace)
        with self.assertRaises(srcopenalex.SourceRefused):
            srcarxiv.search("control theory", fake, 10, pace)
        self.assertEqual(clock.slept, [3.0])

    def test_a_pacer_made_without_a_clock_uses_the_monotonic_clock_and_really_sleeps_nothing_the_first_time(self):
        import time

        pace = srcarxiv.Pacer(3.0)
        before = time.monotonic()
        pace.wait()
        self.assertLess(time.monotonic() - before, 1.0)


if __name__ == "__main__":
    unittest.main()
