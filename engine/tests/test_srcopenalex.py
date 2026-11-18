"""OpenAlex as a source of candidates for the unattended crawl (`kb/srcopenalex.py`; `docs/specs/population.md`, "Discovery").

No test opens a socket: the `get` function is a fake that answers from the small fixtures in `fixtures/crawl/`, which are made by hand
from the field names of OpenAlex's documentation (read on 2026-11-16; the plan's Result gives the pages and their hashes)."""

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from engine.tests import ENGINE_DIR

from kb import KbError, crawlqueue, srcopenalex

FIXTURES = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawl"
SELECT = "id,type,cited_by_count,open_access,best_oa_location,locations"
NOW = "2026-11-16T10:00:00Z"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def ok(body, status=200):
    return status, {"content-type": "application/json; charset=utf-8"}, body


class Fake:
    """A stand-in for the shared web client: `get(url, headers=None, timeout=None) -> (status, headers, body)`. Every call is kept."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        return self.reply(url) if callable(self.reply) else self.reply

    @property
    def urls(self):
        return [c[0] for c in self.calls]


def query(url):
    parts = urlsplit(url)
    return parts.scheme + "://" + parts.netloc + parts.path, {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}


def work(number, *, oa=True, landing="https://journal.example.org/articles/x", pdf=None, locations=None, count=1, id_=None):
    loc = {"id": f"doi:10.1/{number}", "is_oa": oa, "landing_page_url": landing, "pdf_url": pdf, "version": "publishedVersion"}
    return {"id": id_ or f"https://openalex.org/W{number}", "type": "article", "cited_by_count": count,
            "open_access": {"is_oa": oa, "oa_status": "gold" if oa else "closed", "oa_url": landing},
            "best_oa_location": loc if oa else None, "locations": locations if locations is not None else [loc]}


def reply(*works):
    return ok(json.dumps({"meta": {"count": len(works)}, "results": list(works)}).encode())


def arxiv_work(number, url):
    loc = {"id": "pmh:oai:arXiv.org:x", "is_oa": True, "landing_page_url": url, "pdf_url": None, "version": "submittedVersion"}
    return work(number, landing=url, locations=[loc])


class SearchRequestTest(unittest.TestCase):
    def test_one_request_to_the_works_endpoint_with_the_query_the_filter_the_page_size_and_the_fields(self):
        fake = Fake(ok(fixture("openalex_search.json")))
        srcopenalex.search("control theory", fake, 25)
        self.assertEqual(len(fake.calls), 1)
        base, params = query(fake.urls[0])
        self.assertEqual(base, "https://api.openalex.org/works")
        self.assertEqual(params, {"search": "control theory", "filter": "open_access.is_oa:true", "per_page": "25", "select": SELECT})

    def test_the_query_is_encoded_and_cannot_add_a_parameter_or_a_filter(self):
        fake = Fake(reply())
        hostile = "a&filter=cited_by_count:>0&api_key=x#frag?x=1 \"quoted\" +plus %41"
        srcopenalex.search(hostile, fake, 5)
        base, params = query(fake.urls[0])
        self.assertEqual(params["search"], hostile)
        self.assertEqual(sorted(params), ["filter", "per_page", "search", "select"])
        self.assertEqual(params["filter"], "open_access.is_oa:true")
        self.assertNotIn("#", fake.urls[0])

    def test_no_key_and_no_contact_address_is_sent_and_the_agent_is_honest_and_generic(self):
        fake = Fake(ok(fixture("openalex_search.json")))
        srcopenalex.search("control theory", fake, 25)
        url, headers, timeout = fake.calls[0]
        self.assertNotIn("api_key", url)
        self.assertNotIn("mailto", url.lower())
        self.assertNotIn("@", url)
        self.assertEqual(headers["User-Agent"], srcopenalex.USER_AGENT)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertNotIn("@", " ".join(headers.values()))
        self.assertNotIn("Authorization", headers)
        self.assertNotRegex(srcopenalex.USER_AGENT.lower(), r"mozilla|chrome|safari|@|http")
        self.assertEqual(timeout, 30)

    def test_the_query_and_the_limit_are_checked(self):
        for q in ("", "   ", "a\x00b", "line\nbreak", "x" * 301, 5, None, b"x"):
            with self.subTest(query=q):
                with self.assertRaises(KbError):
                    srcopenalex.search(q, Fake(reply()), 5)
        for limit in (0, -1, 101, 1.5, True, "5", None):
            with self.subTest(limit=limit):
                with self.assertRaises(KbError):
                    srcopenalex.search("control theory", Fake(reply()), limit)
        fake = Fake(reply())
        for limit in (1, 100):
            srcopenalex.search("control theory", fake, limit)
        self.assertEqual([query(u)[1]["per_page"] for u in fake.urls], ["1", "100"])

    def test_nothing_is_asked_when_the_arguments_are_wrong(self):
        fake = Fake(reply())
        with self.assertRaises(KbError):
            srcopenalex.search("", fake, 5)
        with self.assertRaises(KbError):
            srcopenalex.search("control theory", "not a function", 5)
        self.assertEqual(fake.calls, [])


class SearchResolutionTest(unittest.TestCase):
    def found(self):
        return srcopenalex.search("control theory", Fake(ok(fixture("openalex_search.json"))), 25)

    def test_the_fixture_gives_two_candidates_and_one_rejected_work_and_skips_the_rest(self):
        found = self.found()
        self.assertEqual(sorted(found), ["candidates", "rejected"])
        self.assertEqual(found["candidates"], [
            {"address": "https://arxiv.org/abs/2401.00001", "identity_key": "arxiv:2401.00001", "source": "openalex",
             "source_id": "openalex:W1000001", "found_from": "control theory", "depth": 0},
            {"address": "https://journal.example.org/articles/w2", "source": "openalex", "source_id": "openalex:W1000002",
             "found_from": "control theory", "depth": 0},
        ])
        self.assertEqual(found["rejected"], [
            {"address": "https://repo.example.edu/files/w3.pdf", "source": "openalex", "source_id": "openalex:W1000003",
             "found_from": "control theory", "depth": 0},
        ])

    def test_what_comes_back_is_what_the_queue_takes(self):
        found = self.found()
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            kw = {"canon_address": lambda a: a, "site_of": lambda h: ".".join(h.split(".")[-2:]), "now": NOW}
            limits = {"queued_total": 10, "queued_per_domain": 10}
            for c in found["candidates"]:
                self.assertEqual(crawlqueue.enqueue(conn, c, limits=limits, **kw), "queued")
            for c in found["rejected"]:
                self.assertEqual(crawlqueue.insert_rejected(conn, c, "type", **kw), "rejected")
            self.assertEqual(crawlqueue.counts(conn)["queued"], 2)
            self.assertEqual(crawlqueue.counts(conn)["rejected"], 1)

    def test_a_work_with_an_arxiv_location_is_the_arxiv_paper_without_its_version(self):
        for url in ("https://arxiv.org/abs/2401.00001", "https://arxiv.org/abs/2401.00001v3", "http://arxiv.org/abs/2401.00001v1",
                    "https://www.arxiv.org/abs/2401.00001", "https://arxiv.org/pdf/2401.00001", "https://arxiv.org/pdf/2401.00001v2",
                    "https://arxiv.org/pdf/2401.00001v2.pdf", "https://arxiv.org/pdf/2401.00001.pdf"):
            with self.subTest(url=url):
                found = srcopenalex.search("q", Fake(reply(arxiv_work(7, url))), 5)
                self.assertEqual([(c["address"], c["identity_key"]) for c in found["candidates"]],
                                 [("https://arxiv.org/abs/2401.00001", "arxiv:2401.00001")])

    def test_the_old_form_of_an_arxiv_id_is_taken(self):
        for url, ident in (("https://arxiv.org/abs/cs/0112017", "cs/0112017"), ("https://arxiv.org/abs/hep-th/9901001v2", "hep-th/9901001"),
                           ("https://arxiv.org/abs/math.GT/0309136", "math.GT/0309136")):
            with self.subTest(url=url):
                found = srcopenalex.search("q", Fake(reply(arxiv_work(7, url))), 5)
                self.assertEqual([c["identity_key"] for c in found["candidates"]], ["arxiv:" + ident])

    def test_an_address_that_only_looks_like_arxiv_is_not_arxiv(self):
        for url in ("https://arxiv.org.evil.example/abs/2401.00001", "https://notarxiv.org/abs/2401.00001",
                    "https://evil.example/https://arxiv.org/abs/2401.00001", "https://arxiv.org/abs/2401.00001/extra",
                    "https://arxiv.org/abs/2413.00001", "https://arxiv.org/list/2401.00001", "https://user@arxiv.org/abs/2401.00001",
                    "https://arxiv.org:8443/abs/2401.00001", "ftp://arxiv.org/abs/2401.00001", "https://arxiv.org/abs/2401.00001?x=1",
                    "https://arxiv.org/abs/2401.00001.pdf",
                    "https://arxiv.org/abs/2401.00001#x"):
            with self.subTest(url=url):
                found = srcopenalex.search("q", Fake(reply(arxiv_work(7, url))), 5)
                self.assertNotIn("arxiv:2401.00001", [c.get("identity_key") for c in found["candidates"]])

    def test_the_arxiv_location_need_not_be_the_best_one_and_the_pdf_address_counts_too(self):
        loc = {"id": "pmh:oai:arXiv.org:x", "is_oa": True, "landing_page_url": None, "pdf_url": "https://arxiv.org/pdf/2402.00002v1",
               "version": "submittedVersion"}
        w = work(8, landing="https://journal.example.org/articles/w8", locations=[work(8)["best_oa_location"], loc])
        found = srcopenalex.search("q", Fake(reply(w)), 5)
        self.assertEqual([c["identity_key"] for c in found["candidates"]], ["arxiv:2402.00002"])

    def test_the_host_of_arxiv_is_taken_in_any_case(self):
        for url in ("https://ARXIV.org/abs/2401.00001", "https://www.Arxiv.Org/abs/2401.00001"):
            with self.subTest(url=url):
                found = srcopenalex.search("q", Fake(reply(arxiv_work(7, url))), 5)
                self.assertEqual([c["identity_key"] for c in found["candidates"]], ["arxiv:2401.00001"])

    def test_a_location_that_does_not_say_it_is_open_is_not_used(self):
        loc = {"id": "pmh:oai:arXiv.org:x", "landing_page_url": "https://arxiv.org/abs/2401.00001", "pdf_url": None}
        other = {"id": "doi:x", "is_oa": None, "landing_page_url": "https://journal.example.org/articles/unknown", "pdf_url": None}
        w = work(7, locations=[loc, other])
        w["best_oa_location"] = None
        self.assertEqual(srcopenalex.search("q", Fake(reply(w)), 5), {"candidates": [], "rejected": []})

    def test_of_two_pdf_only_locations_the_first_is_kept_and_it_is_the_pdf_address_that_is_kept(self):
        first = {"id": "a", "is_oa": True, "landing_page_url": "https://repo.example.edu/landing.pdf", "pdf_url": "https://repo.example.edu/real.pdf"}
        second = {"id": "b", "is_oa": True, "landing_page_url": "https://other.example.edu/b.pdf", "pdf_url": None}
        w = work(7, locations=[first, second])
        w["best_oa_location"] = None
        found = srcopenalex.search("q", Fake(reply(w)), 5)
        self.assertEqual([c["address"] for c in found["rejected"]], ["https://repo.example.edu/real.pdf"])

    def test_a_web_page_in_a_later_location_beats_a_pdf_only_one_before_it(self):
        pdf = {"id": "a", "is_oa": True, "landing_page_url": "https://repo.example.edu/a.pdf", "pdf_url": "https://repo.example.edu/a.pdf"}
        page = {"id": "b", "is_oa": True, "landing_page_url": "https://other.example.edu/b", "pdf_url": None}
        w = work(7, locations=[pdf, page])
        w["best_oa_location"] = None
        found = srcopenalex.search("q", Fake(reply(w)), 5)
        self.assertEqual([c["address"] for c in found["candidates"]], ["https://other.example.edu/b"])
        self.assertEqual(found["rejected"], [])

    def test_an_address_of_2048_characters_is_taken_and_one_of_2049_is_not(self):
        long = "https://example.org/" + "a" * (2048 - len("https://example.org/"))
        self.assertEqual(len(srcopenalex.search("q", Fake(reply(work(7, landing=long))), 5)["candidates"]), 1)
        self.assertEqual(srcopenalex.search("q", Fake(reply(work(7, landing=long + "a"))), 5), {"candidates": [], "rejected": []})

    def test_an_address_with_a_port_that_is_not_one_is_skipped(self):
        for url in ("https://example.org:99999999/a", "https://example.org:abc/a", "https://example.org:-1/a"):
            with self.subTest(url=url):
                self.assertEqual(srcopenalex.search("q", Fake(reply(work(7, landing=url))), 5), {"candidates": [], "rejected": []})

    def test_as_many_works_as_were_asked_for_is_not_too_many(self):
        found = srcopenalex.search("q", Fake(reply(*[work(i, landing=f"https://journal.example.org/a{i}") for i in range(40, 45)])), 5)
        self.assertEqual(len(found["candidates"]), 5)

    def test_a_work_that_says_it_is_not_open_access_is_skipped_whatever_its_locations_say(self):
        w = work(9)
        w["open_access"]["is_oa"] = False
        self.assertEqual(srcopenalex.search("q", Fake(reply(w)), 5), {"candidates": [], "rejected": []})
        w = arxiv_work(10, "https://arxiv.org/abs/2401.00001")
        w["open_access"]["is_oa"] = False
        self.assertEqual(srcopenalex.search("q", Fake(reply(w)), 5), {"candidates": [], "rejected": []})

    def test_a_work_that_is_not_open_access_is_skipped_even_with_an_arxiv_address(self):
        closed = work(9, oa=False, landing="https://arxiv.org/abs/2401.00009")
        found = srcopenalex.search("q", Fake(reply(closed)), 5)
        self.assertEqual(found, {"candidates": [], "rejected": []})

    def test_a_landing_page_that_is_html_is_the_address_and_a_pdf_only_work_is_rejected_for_its_type(self):
        html = work(10, landing="https://journal.example.org/articles/ten", pdf="https://journal.example.org/articles/ten.pdf")
        pdf_landing = work(11, landing="https://repo.example.edu/files/eleven.pdf", pdf=None)
        pdf_same = work(12, landing="https://repo.example.edu/files/twelve", pdf="https://repo.example.edu/files/twelve")
        pdf_query = work(13, landing="https://repo.example.edu/files/thirteen.PDF?download=1", pdf=None)
        pdf_only = work(14, landing=None, pdf="https://repo.example.edu/files/fourteen.pdf")
        found = srcopenalex.search("q", Fake(reply(html, pdf_landing, pdf_same, pdf_query, pdf_only)), 5)
        self.assertEqual([c["address"] for c in found["candidates"]], ["https://journal.example.org/articles/ten"])
        self.assertEqual([c["address"] for c in found["rejected"]],
                         ["https://repo.example.edu/files/eleven.pdf", "https://repo.example.edu/files/twelve",
                          "https://repo.example.edu/files/thirteen.PDF?download=1", "https://repo.example.edu/files/fourteen.pdf"])

    def test_an_open_location_other_than_the_best_one_is_used_when_there_is_no_best(self):
        w = work(15)
        w["best_oa_location"] = None
        found = srcopenalex.search("q", Fake(reply(w)), 5)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W15"])

    def test_an_address_that_is_not_a_plain_web_address_is_skipped(self):
        bad = ["javascript:alert(1)", "ftp://example.org/a", "file:///etc/passwd", "//example.org/a", "/relative/path", "example.org/a",
               "https://", "https:///nohost", "https://exa mple.org/a", "https://example.org/a\nb", "https://example.org/a\x00",
               "https://example.org/\u202ea", "https://example.org/" + "a" * 2100, "", "   ", 5, ["https://example.org/a"],
               "https://user:pw@example.org/a", "http://127.0.0.1/a", "http://10.0.0.5/a", "http://169.254.169.254/latest/meta-data",
               "http://192.168.1.1/a", "http://[::1]/a", "http://[fe80::1]/a", "http://[fd00::1]/a", "http://0.0.0.0/a", "http://224.0.0.1/a",
               "http://localhost/a", "http://LOCALHOST:8080/a", "http://service.localhost/a", "http://100.64.0.1/a",
               "http://localhost./a", "http://2130706433/a", "http://127.1/a", "http://0x7f.1/a", "http://0x7f000001/a", "http://1.2.3/a",
               "http://017700000001/a", "http://127.0.0.1./a"]
        for url in bad:
            with self.subTest(url=str(url)[:40]):
                found = srcopenalex.search("q", Fake(reply(work(16, landing=url))), 5)
                self.assertEqual(found, {"candidates": [], "rejected": []})

    def test_an_address_with_a_public_number_for_a_host_is_taken(self):
        for url in ("http://93.184.216.34/a", "https://[2606:2800:220:1::1]/a", "https://example.org:8443/a", "https://example.org./a",
                    "https://bad.cafe/a", "https://1password.example/a", "https://a1.b2.example/a", "https://xn--e1afmkfd.xn--p1ai/a"):
            with self.subTest(url=url):
                self.assertEqual(len(srcopenalex.search("q", Fake(reply(work(7, landing=url))), 5)["candidates"]), 1)

    def test_a_work_whose_id_is_not_an_openalex_work_id_is_skipped(self):
        for ident in ("https://openalexXorg/W123", "https://openalex.org/W12abc", "https://openalex.org/A123", "http://openalex.org/W123", "https://evil.example/W123",
                      "W123", "https://openalex.org/W", "https://openalex.org/W1234567890123", "https://openalex.org/W123/x", None, 5,
                      "https://openalex.org/W123\n"):
            with self.subTest(id=ident):
                w = work(17)
                w["id"] = ident
                self.assertEqual(srcopenalex.search("q", Fake(reply(w)), 5), {"candidates": [], "rejected": []})

    def test_a_work_with_a_field_of_the_wrong_kind_is_skipped_and_the_others_are_kept(self):
        broken = [work(18, landing="https://journal.example.org/a18"), work(19, landing="https://journal.example.org/a19"),
                  work(20, landing="https://journal.example.org/a20"), work(21, landing="https://journal.example.org/a21")]
        broken[0]["open_access"] = "yes"
        broken[1]["best_oa_location"] = "here"
        broken[1]["locations"] = "everywhere"
        broken[2]["locations"] = [5, None, "x"]
        broken[2]["best_oa_location"] = None
        good = work(22, landing="https://journal.example.org/a22")
        found = srcopenalex.search("q", Fake(reply(*broken, good)), 10)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W21", "openalex:W22"])

    def test_the_same_paper_twice_in_one_answer_is_one_candidate(self):
        found = srcopenalex.search("q", Fake(reply(arxiv_work(23, "https://arxiv.org/abs/2401.00001"),
                                                   arxiv_work(24, "https://arxiv.org/pdf/2401.00001v2"), work(25), work(25))), 10)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W23", "openalex:W25"])

    def test_the_query_that_found_a_work_is_kept_cleaned_and_bounded(self):
        found = srcopenalex.search("  control   theory  ", Fake(reply(work(26))), 5)
        self.assertEqual(found["candidates"][0]["found_from"], "control theory")

    def test_no_result_is_no_candidate_and_no_refusal(self):
        self.assertEqual(srcopenalex.search("q", Fake(reply()), 5), {"candidates": [], "rejected": []})


class RefusalTest(unittest.TestCase):
    def refused(self, fake, call=lambda f: srcopenalex.search("control theory", f, 5)):
        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            call(fake)
        return cm.exception

    def test_a_refusing_status_is_a_refusal_that_names_it_and_asks_nothing_more(self):
        for status in (400, 401, 403, 404, 429, 500, 503, 301, 204):
            with self.subTest(status=status):
                fake = Fake(ok(b"{}", status))
                error = self.refused(fake)
                self.assertIn(str(status), str(error))
                self.assertEqual(len(fake.calls), 1)

    def test_a_body_that_is_not_the_expected_json_is_a_refusal(self):
        bad = [b"", b"<html>blocked</html>", b"not json", b"[]", b"[1,2]", b"\"text\"", b"null", b"{}", b'{"results": null}',
               b'{"results": {}}', b'{"results": [5]}', b'{"results": ["x"]}', b'{"results": [null]}', b"\xff\xfe{}",
               b'{"results": [], "results": []}', b'{"results": [], "x": NaN}', b'{"results": [], "x": Infinity}',
               b"[" * 500000 + b"]" * 500000, b'{"a":' * 300000 + b"1" + b"}" * 300000, b'{"results": [], "x": "\xff"}']
        for body in bad:
            with self.subTest(body=body[:30]):
                self.refused(Fake(ok(body)))

    def test_more_results_than_were_asked_for_is_a_refusal(self):
        self.refused(Fake(reply(*[work(i) for i in range(30, 36)])), lambda f: srcopenalex.search("q", f, 5))

    def test_an_answer_of_exactly_two_million_bytes_is_taken_and_one_byte_more_is_not(self):
        body = reply(work(40))[2]
        exact = body[:-1] + b" " * (2_000_000 - len(body)) + b"}"
        self.assertEqual(len(exact), 2_000_000)
        self.assertEqual(len(srcopenalex.search("q", Fake(ok(exact)), 5)["candidates"]), 1)
        self.refused(Fake(ok(exact + b" ")))

    def test_an_answer_over_the_size_limit_is_a_refusal(self):
        body = reply(work(40))[2]
        padded = body[:-1] + b' ' * srcopenalex.MAX_BODY + b"}"
        self.refused(Fake(ok(padded)))
        self.assertEqual(len(srcopenalex.search("q", Fake(ok(body)), 5)["candidates"]), 1)

    def test_a_body_that_is_not_bytes_is_a_refusal(self):
        for body in (None, "text", 5, ["x"]):
            with self.subTest(body=body):
                self.refused(Fake((200, {}, body)))

    def test_a_status_that_is_not_a_number_is_a_refusal(self):
        for status in (None, "200", 200.0, True):
            with self.subTest(status=status):
                self.refused(Fake((status, {}, reply(work(7))[2])))

    def test_a_request_that_the_client_refuses_is_a_refusal_of_the_source(self):
        def fail(url):
            raise KbError("the address is not allowed")

        self.refused(Fake(fail))

    def test_any_other_error_of_the_client_is_not_hidden(self):
        def fail(url):
            raise ZeroDivisionError()

        with self.assertRaises(ZeroDivisionError):
            srcopenalex.search("q", Fake(fail), 5)

    def test_the_reason_never_holds_what_the_server_sent(self):
        error = self.refused(Fake(ok(b"<html>SECRET-TOKEN-123 blocked</html>", 403)))
        self.assertNotIn("SECRET", str(error))
        self.assertNotIn("SECRET", error.reason)
        error = self.refused(Fake(ok(b"SECRET-TOKEN-123")))
        self.assertNotIn("SECRET", str(error))
        self.assertLessEqual(len(error.reason), 200)

    def test_the_refusal_is_a_kb_error_and_carries_what_was_found_before_it(self):
        error = self.refused(Fake(ok(b"", 429)))
        self.assertIsInstance(error, KbError)
        self.assertEqual(error.partial, {"candidates": [], "rejected": []})


class RateLimitTest(unittest.TestCase):
    """A 429 is a refusal for the rest of the day unless its `X-RateLimit-Remaining` header says that budget is left, and then it is a refusal
    for this refill only. The web client keeps no body for a status other than 200, so only the headers decide, and only as plain numbers."""

    def limited(self, remaining=None, retry=None, status=429, name="x-ratelimit-remaining"):
        headers = {"content-type": "application/json"}
        if remaining is not None:
            headers[name] = remaining
        if retry is not None:
            headers["retry-after"] = retry
        return Fake((status, headers, b""))

    def refused(self, fake):
        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            srcopenalex.search("control theory", fake, 5)
        return cm.exception

    def test_a_refusal_is_for_the_day_unless_it_says_otherwise(self):
        self.assertTrue(srcopenalex.SourceRefused("status 500").for_day)
        self.assertFalse(srcopenalex.SourceRefused("status 429", for_day=False).for_day)

    def test_a_429_with_budget_left_is_a_refusal_for_this_refill_only(self):
        for remaining in ("0.07", "12", "3.5", "0.0001", "00012", " 7 "):
            with self.subTest(remaining=remaining):
                fake = self.limited(remaining)
                error = self.refused(fake)
                self.assertFalse(error.for_day)
                self.assertEqual(len(fake.calls), 1)  # nothing more is asked of it
                self.assertIn("429", str(error))

    def test_a_429_that_does_not_show_budget_left_is_a_refusal_for_the_day(self):
        for remaining in ("0", "0.0", "0.000", "", "-1", "-0.5", "abc", "1e3", "1,5", "3, 4", "1.", ".5", "5 5", "9, 9", "+3", "1" * 21, "123456789012345.12345", "0x10", "NaN", "inf", "１２"):
            with self.subTest(remaining=remaining):
                self.assertTrue(self.refused(self.limited(remaining)).for_day)
        self.assertTrue(self.refused(self.limited(None)).for_day)  # no such header

    def test_the_headers_are_read_in_any_case(self):
        self.assertFalse(self.refused(self.limited("4", name="X-RateLimit-Remaining")).for_day)
        self.assertFalse(self.refused(self.limited("4", name="X-RATELIMIT-REMAINING")).for_day)

    def test_a_header_given_twice_under_two_spellings_is_not_believed(self):
        fake = Fake((429, {"x-ratelimit-remaining": "9", "X-RateLimit-Remaining": "9"}, b""))
        self.assertTrue(self.refused(fake).for_day)

    def test_only_a_429_is_read_for_its_header(self):
        for status in (400, 401, 403, 404, 500, 503, 301, 204):
            with self.subTest(status=status):
                error = self.refused(self.limited("12", status=status))
                self.assertTrue(error.for_day)
                self.assertEqual(str(error), f"OpenAlex: status {status}")

    def test_the_reason_holds_the_two_plain_numbers_and_no_other_text_of_a_header(self):
        error = self.refused(self.limited("5", "2"))
        self.assertEqual(error.reason, "status 429 (remaining 5, retry-after 2)")
        error = self.refused(self.limited("0", "30"))
        self.assertEqual(error.reason, "status 429 (remaining 0, retry-after 30)")
        error = self.refused(self.limited("3", "Wed, 21 Oct 2026 07:28:00 GMT"))
        self.assertEqual(error.reason, "status 429 (remaining 3, retry-after none)")
        error = self.refused(self.limited("SECRET-TOKEN-123", "SECRET-TOKEN-456"))
        self.assertEqual(error.reason, "status 429 (remaining none, retry-after none)")
        self.assertNotIn("SECRET", str(error))
        self.assertEqual(self.refused(self.limited()).reason, "status 429 (remaining none, retry-after none)")

    def test_a_wander_that_is_limited_is_a_refusal_for_this_refill_and_keeps_what_was_found(self):
        inner = WanderTest().router().reply

        def route(url):
            base, params = query(url)
            if "cites:" in params.get("filter", ""):
                return 429, {"content-type": "application/json", "x-ratelimit-remaining": "9"}, b""
            return inner(url)

        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            srcopenalex.wander([("openalex:W1000001", 0), ("openalex:W1000002", 0)], Fake(route), 3, 2)
        self.assertFalse(cm.exception.for_day)
        self.assertEqual([c["source_id"] for c in cm.exception.partial["candidates"]], ["openalex:W2000001", "openalex:W2000003"])


class WanderTest(unittest.TestCase):
    def router(self, refs=None, batch=None, citing=None):
        batch = batch if batch is not None else ok(fixture("openalex_refs_batch.json"))
        citing = citing if citing is not None else ok(fixture("openalex_citing.json"))

        def route(url):
            base, params = query(url)
            if base.startswith("https://api.openalex.org/works/W"):
                if refs is not None:
                    return refs
                about = json.loads(fixture("openalex_work_refs.json"))  # the fixture, said of the work that was asked about
                about["id"] = "https://openalex.org/" + base.rsplit("/", 1)[1]
                return ok(json.dumps(about).encode())
            if params.get("filter", "").startswith("openalex:"):
                return batch
            if "cites:" in params.get("filter", ""):
                return citing
            raise AssertionError(f"an unexpected request: {url}")

        return Fake(route)

    def wander(self, fake=None, kept=(("openalex:W1000001", 0),), per_work=2, max_depth=2, **kw):
        fake = fake or self.router()
        return fake, srcopenalex.wander(list(kept), fake, per_work, max_depth, **kw)

    def test_for_a_kept_work_three_requests_are_made_in_order_and_each_is_the_documented_one(self):
        fake, _ = self.wander()
        self.assertEqual(len(fake.calls), 3)
        base, params = query(fake.urls[0])
        self.assertEqual((base, params), ("https://api.openalex.org/works/W1000001", {"select": "id,referenced_works"}))
        base, params = query(fake.urls[1])
        self.assertEqual(base, "https://api.openalex.org/works")
        self.assertEqual(params["filter"], "openalex:W2000001|W2000002|W2000003|W2000004|W2000005|W2000006,open_access.is_oa:true")
        self.assertEqual((params["per_page"], params["select"]), ("100", SELECT))
        self.assertEqual(sorted(params), ["filter", "per_page", "select"])
        base, params = query(fake.urls[2])
        self.assertEqual(base, "https://api.openalex.org/works")
        self.assertEqual(params, {"filter": "cites:W1000001,open_access.is_oa:true", "sort": "cited_by_count:desc", "per_page": "12",
                                  "select": SELECT})

    def test_the_request_for_the_works_that_cite_a_work_carries_the_sort_as_it_stands_on_the_wire_with_the_colon_as_it_is(self):
        fake, _ = self.wander()
        raw = fake.urls[2]
        self.assertIn("&sort=cited_by_count:desc&", raw)  # not %3A: the decoded parameters cannot tell the two apart
        self.assertNotIn("-cited_by_count", raw)
        self.assertNotIn("%3A", raw.split("?", 1)[1].split("sort=", 1)[1].split("&", 1)[0])

    def test_a_server_that_refuses_the_old_form_of_the_sort_as_openalex_does_leaves_the_walk_complete(self):
        inner = self.router().reply

        def route(url):
            if "sort=-cited_by_count" in url:  # what OpenAlex answers on 2026-11-18: 400, "_cited_by_count is not a valid field"
                return 400, {"content-type": "application/json"}, b'{"error":"Invalid query parameters error.","message":"_cited_by_count is not a valid field."}'
            return inner(url)

        fake, found = self.wander(Fake(route), per_work=6)
        self.assertEqual(len(fake.calls), 3)
        self.assertTrue([c for c in found["candidates"] if c["source_id"].startswith("openalex:W3")])  # the citing works came

    def test_the_works_it_cites_are_ranked_by_how_much_they_are_cited_then_by_id_and_the_strongest_are_taken(self):
        _, found = self.wander(per_work=6)
        outgoing = [c["source_id"] for c in found["candidates"] if c["source_id"].startswith("openalex:W2")]
        self.assertEqual(outgoing, ["openalex:W2000001", "openalex:W2000003", "openalex:W2000002"])

    def test_the_works_that_cite_it_are_ranked_the_same_way_and_the_work_itself_is_left_out(self):
        _, found = self.wander(per_work=6)
        incoming = [c["source_id"] for c in found["candidates"] + found["rejected"] if c["source_id"].startswith("openalex:W3")]
        self.assertEqual(incoming, ["openalex:W3000001", "openalex:W3000002", "openalex:W3000003"])
        self.assertNotIn("openalex:W1000001", [c["source_id"] for c in found["candidates"] + found["rejected"]])

    def test_at_most_per_work_works_are_taken_from_one_kept_work_in_all_the_odd_place_going_to_the_works_it_cites(self):
        for per_work, cites, citing in ((1, 1, 0), (2, 1, 1), (3, 2, 1), (4, 2, 2), (5, 3, 2), (6, 3, 3), (7, 4, 3)):
            with self.subTest(per_work=per_work):
                _, found = self.wander(per_work=per_work)
                everything = found["candidates"] + found["rejected"]
                outgoing = [c for c in everything if c["source_id"].startswith("openalex:W2")]
                incoming = [c for c in everything if c["source_id"].startswith("openalex:W3")]
                self.assertEqual((len(outgoing), len(incoming)), (cites, citing))
                self.assertEqual(len(everything), per_work)

    def test_a_pdf_only_work_takes_a_place_and_is_returned_as_rejected(self):
        _, found = self.wander(per_work=20)  # more than there is: five cited (one is closed) and three citing (the work itself is left out)
        everything = found["candidates"] + found["rejected"]
        self.assertEqual(len(everything), 8)
        self.assertEqual([c["source_id"] for c in found["rejected"]], ["openalex:W2000004", "openalex:W3000003"])

    def test_a_place_that_the_works_it_cites_cannot_fill_goes_to_the_works_that_cite_it(self):
        one = self.refs_of(["W2000001"])
        _, found = self.wander(self.router(refs=one), per_work=5)
        ids = [c["source_id"] for c in found["candidates"] + found["rejected"]]
        self.assertEqual(ids, ["openalex:W2000001", "openalex:W3000001", "openalex:W3000002", "openalex:W3000003"])

    def test_a_place_that_the_works_that_cite_it_cannot_fill_goes_to_the_works_it_cites(self):
        _, found = self.wander(self.router(citing=reply()), per_work=5)
        ids = [c["source_id"] for c in found["candidates"] + found["rejected"]]
        self.assertEqual(ids, ["openalex:W2000001", "openalex:W2000003", "openalex:W2000002", "openalex:W2000006", "openalex:W2000004"])

    def test_a_place_passed_to_the_other_side_gets_the_same_level_and_origin_and_never_a_work_the_other_side_took(self):
        twin = self.cited(3000009, 30, landing="https://journal.example.org/articles/r6")  # the page that W2000006 is, as a citing work
        _, found = self.wander(self.router(citing=reply(twin)), per_work=5)
        ids = [c["source_id"] for c in found["candidates"] + found["rejected"]]
        self.assertEqual(ids, ["openalex:W2000001", "openalex:W2000003", "openalex:W2000002", "openalex:W3000009", "openalex:W2000004"])
        for c in found["candidates"] + found["rejected"]:
            self.assertEqual((c["depth"], c["found_from"]), (1, "openalex:W1000001"))

    def test_a_citing_work_that_is_a_page_the_cited_side_already_took_is_left_out(self):
        twin = self.cited(3000009, 99, landing="https://journal.example.org/articles/r1")  # the page of W2000001, which is taken first
        _, found = self.wander(self.router(citing=reply(twin)), per_work=6)
        ids = [c["source_id"] for c in found["candidates"] + found["rejected"]]
        self.assertNotIn("openalex:W3000009", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_work_that_the_answer_holds_and_that_was_not_asked_for_is_left_out(self):
        _, found = self.wander(self.router(refs=self.refs_of(["W2000001"]), citing=reply()), per_work=5)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W2000001"])

    def test_each_is_found_from_the_kept_work_one_level_deeper_with_the_fields_of_a_candidate(self):
        _, found = self.wander(kept=(("openalex:W1000001", 1),), per_work=4)
        for c in found["candidates"] + found["rejected"]:
            self.assertEqual((c["found_from"], c["depth"], c["source"]), ("openalex:W1000001", 2, "openalex"))
            self.assertNotIn("topic", c)
            self.assertNotIn("weight", c)
        self.assertEqual(found["candidates"][1], {
            "address": "https://journal.example.org/articles/r3", "source": "openalex", "source_id": "openalex:W2000003",
            "found_from": "openalex:W1000001", "depth": 2})

    def test_an_arxiv_work_is_the_arxiv_paper_here_too(self):
        _, found = self.wander(per_work=5)
        keys = [c.get("identity_key") for c in found["candidates"]]
        self.assertIn("arxiv:2402.00002", keys)
        self.assertIn("arxiv:2403.00003", keys)

    def test_a_kept_work_at_the_depth_limit_is_not_wandered_from_and_no_request_is_made_for_it(self):
        fake, found = self.wander(kept=(("openalex:W1000001", 2),), max_depth=2)
        self.assertEqual((fake.calls, found), ([], {"candidates": [], "rejected": []}))
        fake, found = self.wander(kept=(("openalex:W1000001", 1),), max_depth=2)
        self.assertEqual(len(fake.calls), 3)
        self.assertTrue(all(c["depth"] == 2 for c in found["candidates"]))

    def test_nothing_kept_means_no_request(self):
        fake, found = self.wander(kept=())
        self.assertEqual((fake.calls, found), ([], {"candidates": [], "rejected": []}))

    def test_a_source_id_that_is_not_an_openalex_work_id_is_skipped_and_costs_no_request(self):
        for ident in ("openalex:W1234567890123", "openalex:W12abc", "openalex:A123", "arxiv:2401.00001", "W123", "openalex:", "openalex:W123/x", "openalex:W1\n",
                      None, 5, "https://openalex.org/W123"):
            with self.subTest(id=ident):
                fake, found = self.wander(kept=((ident, 0),))
                self.assertEqual((fake.calls, found), ([], {"candidates": [], "rejected": []}))

    def test_a_referenced_work_with_a_bad_id_is_not_asked_for_and_the_kept_work_itself_is_not_asked_for(self):
        fake, _ = self.wander()  # the fixture lists six work ids, then "not an id", then the kept work itself
        _, params = query(fake.urls[1])
        self.assertEqual(params["filter"], "openalex:W2000001|W2000002|W2000003|W2000004|W2000005|W2000006,open_access.is_oa:true")

    def test_the_works_it_cites_are_asked_for_in_batches_of_100_and_at_most_300_are_looked_at(self):
        refs = {"id": "https://openalex.org/W1000001", "referenced_works": [f"https://openalex.org/W{5000000 + i}" for i in range(350)]}
        empty = ok(json.dumps({"results": []}).encode())
        fake = self.router(refs=ok(json.dumps(refs).encode()), batch=empty, citing=empty)
        self.wander(fake)
        batches = [query(u)[1]["filter"] for u in fake.urls if query(u)[1].get("filter", "").startswith("openalex:")]
        self.assertEqual(len(batches), 3)
        self.assertEqual([b.split(",")[0].count("|") + 1 for b in batches], [100, 100, 100])

    def refs_of(self, ids):
        return ok(json.dumps({"id": "https://openalex.org/W1000001", "referenced_works": [f"https://openalex.org/{i}" for i in ids]}).encode())

    def cited(self, number, count, landing=None, arxiv=None):
        w = work(number, count=count, landing=landing or f"https://journal.example.org/c{number}", id_=f"https://openalex.org/W{number}")
        if arxiv:
            w = arxiv_work(number, arxiv)
            w["id"], w["cited_by_count"] = f"https://openalex.org/W{number}", count
        return w

    def test_works_with_the_same_number_of_citations_come_in_the_order_of_their_ids_whatever_order_they_were_sent_in(self):
        refs = self.refs_of(["W2000003", "W2000001"])
        batch = reply(self.cited(2000003, 5), self.cited(2000001, 5))
        _, found = self.wander(self.router(refs=refs, batch=batch, citing=reply()), per_work=4)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W2000001", "openalex:W2000003"])

    def test_ids_are_ordered_as_numbers_and_not_as_text(self):
        refs = self.refs_of(["W10", "W9"])
        batch = reply(self.cited(10, 5), self.cited(9, 5))
        _, found = self.wander(self.router(refs=refs, batch=batch, citing=reply()), per_work=4)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W9", "openalex:W10"])

    def test_a_count_that_is_not_a_plain_number_of_citations_counts_as_none(self):
        refs = self.refs_of(["W100", "W200", "W300", "W400", "W500"])
        odd = [self.cited(100, 0), self.cited(200, True), self.cited(300, -5), self.cited(400, "9"), self.cited(500, 9.0)]
        _, found = self.wander(self.router(refs=refs, batch=reply(*odd), citing=reply()), per_work=10)
        self.assertEqual([c["source_id"] for c in found["candidates"]], [f"openalex:W{n}" for n in (100, 200, 300, 400, 500)])

    def test_the_same_arxiv_paper_found_in_two_batches_is_taken_once_from_the_more_cited_work(self):
        ids = [f"W{6000000 + i}" for i in range(1, 151)]
        first = reply(self.cited(6000001, 5, arxiv="https://arxiv.org/abs/2405.00001"))
        second = reply(self.cited(6000101, 9, arxiv="https://arxiv.org/abs/2405.00001"))
        inner = self.router(refs=self.refs_of(ids), citing=reply()).reply

        def route(url):
            filter_ = query(url)[1].get("filter", "")
            if filter_.startswith("openalex:") and "W6000001|" in filter_:
                return first
            if filter_.startswith("openalex:"):
                return second
            return inner(url)

        _, found = self.wander(Fake(route), per_work=5)
        self.assertEqual([c["source_id"] for c in found["candidates"]], ["openalex:W6000101"])

    def test_only_the_first_3000_entries_of_a_list_of_references_are_looked_at(self):
        refs = self.refs_of(["junk"] * 3000 + [f"W{8000000 + i}" for i in range(5)])
        fake, _ = self.wander(self.router(refs=refs, citing=reply()))
        self.assertEqual(len(fake.calls), 2)  # the work, and who cites it

    def test_a_reference_that_is_more_than_a_work_id_is_not_asked_for(self):
        refs = self.refs_of(["W8000001garbage", "W8000002/extra", "W8000003"])
        fake, _ = self.wander(self.router(refs=refs, citing=reply()))
        self.assertEqual(query(fake.urls[1])[1]["filter"], "openalex:W8000003,open_access.is_oa:true")

    def test_the_3000th_entry_of_a_list_of_references_is_looked_at_and_the_3001st_is_not(self):
        looked = self.refs_of(["junk"] * 2999 + ["W8000001"])
        fake, _ = self.wander(self.router(refs=looked, citing=reply()))
        self.assertEqual(len(fake.calls), 3)
        past = self.refs_of(["junk"] * 3000 + ["W8000001"])
        fake, _ = self.wander(self.router(refs=past, citing=reply()))
        self.assertEqual(len(fake.calls), 2)

    def test_a_work_listed_twice_is_asked_for_once(self):
        fake, _ = self.wander(self.router(refs=self.refs_of(["W8000001", "W8000001", "W8000002"]), citing=reply()))
        self.assertEqual(query(fake.urls[1])[1]["filter"], "openalex:W8000001|W8000002,open_access.is_oa:true")

    def test_a_work_that_cites_nothing_is_still_asked_who_cites_it(self):
        none = ok(json.dumps({"id": "https://openalex.org/W1000001", "referenced_works": []}).encode())
        fake, found = self.wander(self.router(refs=none))
        self.assertEqual(len(fake.calls), 2)  # the work itself, and who cites it: no batch
        self.assertTrue(all(c["source_id"].startswith("openalex:W3") for c in found["candidates"] + found["rejected"]))

    def test_a_work_with_no_list_of_references_is_taken_as_citing_nothing_and_a_list_of_the_wrong_kind_is_a_refusal(self):
        missing = ok(json.dumps({"id": "https://openalex.org/W1000001"}).encode())
        fake, _ = self.wander(self.router(refs=missing))
        self.assertEqual(len(fake.calls), 2)
        for wrong in ('"W1"', "{}", "5", "null"):
            with self.subTest(wrong=wrong):
                body = ok(('{"id": "https://openalex.org/W1000001", "referenced_works": %s}' % wrong).encode())
                with self.assertRaises(srcopenalex.SourceRefused):
                    self.wander(self.router(refs=body))

    def test_the_answer_about_a_work_must_be_about_that_work(self):
        other = ok(json.dumps({"id": "https://openalex.org/W999", "referenced_works": []}).encode())
        with self.assertRaises(srcopenalex.SourceRefused):
            self.wander(self.router(refs=other))

    def test_two_kept_works_are_walked_in_turn_and_a_work_found_twice_is_taken_once(self):
        fake, found = self.wander(kept=(("openalex:W1000001", 0), ("openalex:W1000001", 0)), per_work=2)
        self.assertEqual(len(fake.calls), 3)  # the same kept work twice is asked about once
        both = self.router()
        _, found2 = self.wander(both, kept=(("openalex:W1000001", 0), ("openalex:W1000002", 0)), per_work=2)
        ids = [c["source_id"] for c in found2["candidates"] + found2["rejected"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_other_kept_works_and_the_works_it_is_told_it_has_seen_are_never_taken(self):
        _, found = self.wander(kept=(("openalex:W1000001", 0), ("openalex:W2000001", 0)), per_work=5, seen={"openalex:W3000002"})
        ids = {c["source_id"] for c in found["candidates"] + found["rejected"]}
        self.assertNotIn("openalex:W2000001", ids)
        self.assertNotIn("openalex:W3000002", ids)
        self.assertNotIn("openalex:W1000001", ids)

    def test_a_refusal_on_the_way_stops_at_once_and_carries_what_was_found_before_it(self):
        inner = self.router().reply

        def route(url):
            base, params = query(url)
            if "cites:" in params.get("filter", ""):
                return ok(b"", 429)
            return inner(url)

        fake = Fake(route)
        with self.assertRaises(srcopenalex.SourceRefused) as cm:
            srcopenalex.wander([("openalex:W1000001", 0), ("openalex:W1000002", 0)], fake, 3, 2)
        self.assertIn("429", str(cm.exception))
        self.assertEqual(len(fake.calls), 3)  # nothing is asked after the refused request, and the second kept work never is
        self.assertEqual([c["source_id"] for c in cm.exception.partial["candidates"]], ["openalex:W2000001", "openalex:W2000003"])

    def test_no_key_and_no_contact_address_is_sent_by_a_wander_either(self):
        fake, _ = self.wander()
        for url, headers, timeout in fake.calls:
            self.assertNotIn("api_key", url)
            self.assertNotIn("mailto", url.lower())
            self.assertEqual(headers["User-Agent"], srcopenalex.USER_AGENT)

    def test_the_arguments_are_checked(self):
        for kw in ({"per_work": 0}, {"per_work": 21}, {"per_work": True}, {"per_work": "2"}, {"max_depth": -1}, {"max_depth": 11},
                   {"max_depth": 1.5}, {"kept": "openalex:W1"}, {"kept": [("openalex:W1",)]}, {"kept": [("openalex:W1", -1)]},
                   {"kept": [("openalex:W1", "0")]}, {"seen": "openalex:W1"}):
            with self.subTest(kw=kw):
                with self.assertRaises(KbError):
                    self.wander(**kw)

    def test_what_comes_back_is_what_the_queue_takes(self):
        _, found = self.wander(per_work=5)
        with tempfile.TemporaryDirectory() as folder, closing(crawlqueue.connect(folder)) as conn:
            kw = {"canon_address": lambda a: a, "site_of": lambda h: ".".join(h.split(".")[-2:]), "now": NOW}
            limits = {"queued_total": 100, "queued_per_domain": 100}
            for c in found["candidates"]:
                self.assertEqual(crawlqueue.enqueue(conn, c, limits=limits, **kw), "queued", c)
            for c in found["rejected"]:
                self.assertEqual(crawlqueue.insert_rejected(conn, c, "type", **kw), "rejected", c)


if __name__ == "__main__":
    unittest.main()
