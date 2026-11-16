"""The capture functions under a policy (Increment C of the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`).

`capture_url.capture` and `capture_arxiv.capture` take `policy`, `types` and `auto_filed`. With none given they behave as before (their own tests, unchanged, show that). With a policy every request goes through the shared
client (`webclient.get`), a refusal by the policy raises `webclient.Refused` **before any book or index entry is made**, and a book filed with `auto_filed=True` says so in its root file.
The tests reuse the fake resolver and fake server of `test_webclient`; nothing here touches the real network.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_capture_policy`."""
import os
import unittest
from unittest import mock
from xml.sax.saxutils import escape

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_capture_arxiv import PDF1, atom
from engine.tests.test_store import StoreCase
from engine.tests.test_webclient import Net, redirect, reply

from kb import KbError, capture_arxiv, capture_url, identity, webclient

PAGE = b"<html><head><title>A page</title></head><body>Some words on a page.</body></html>"


class PolicyCase(Net, StoreCase):
    def setUp(self):
        Net.setUp(self)
        StoreCase.setUp(self)
        self.ident = identity.Identity(self.index)

    def capture(self, address, **kw):
        kw.setdefault("policy", self.policy())
        return capture_url.capture(self.store, self.ident, address, **kw)

    def books(self):
        return self.store.list_books()

    def assert_nothing_made(self):
        self.assertEqual(self.books(), [])
        self.assertEqual(self.ident.lookup("url", "http://a.test/p"), None)


class UrlUnderPolicy(PolicyCase):
    def test_a_page_is_fetched_by_the_shared_client_under_the_policys_agent_and_headers(self):
        self.srv.routes["/p"] = self.ok(PAGE)
        result = self.capture("http://a.test/p", policy=self.policy(user_agent="Mozilla/5.0 (policy)", headers={"X-One": "1"}))
        self.assertEqual(result["status"], "filed")
        headers = self.srv.hits[0][1]
        self.assertEqual((headers["user-agent"], headers["x-one"]), ("Mozilla/5.0 (policy)", "1"))
        self.assertEqual(self.dials, [("93.184.216.34", 80)])
        book = self.store.read_book(result["book_id"])
        self.assertEqual(book["identity_keys"]["url"], "http://a.test/p")
        version = self.store.read_version(result["book_id"], result["version_id"])
        self.assertEqual(version["source"]["address_final"], "http://a.test/p")
        self.assertEqual(version["source"]["http_status"], 200)
        self.assertIn("content-type", version["source"]["headers"])

    def test_the_address_is_made_canonical_the_way_the_crawl_does(self):
        self.srv.routes["/p"] = self.ok(PAGE)
        result = self.capture("HTTP://A.test./p?utm_source=x#top")
        keys = self.store.read_book(result["book_id"])["identity_keys"]
        self.assertEqual(keys["url"], "http://a.test/p")
        self.assertFalse(keys.get("url_alias"))     # what was asked for is already the canonical address
        self.assertEqual(self.ident.lookup("url", "http://a.test/p"), result["book_id"])

    def test_a_page_held_already_is_not_requested_again(self):
        self.srv.routes["/p"] = self.ok(PAGE)
        first = self.capture("http://a.test/p")
        hits = len(self.srv.hits)
        again = self.capture("http://a.test/p")
        self.assertEqual((again["status"], again["book_id"]), ("held", first["book_id"]))
        self.assertEqual(len(self.srv.hits), hits)

    def test_a_redirect_is_followed_and_both_addresses_point_at_the_book(self):
        self.srv.routes["/old"] = redirect("http://b.test/new")
        self.srv.routes["/new"] = self.ok(PAGE)
        result = self.capture("http://a.test/old")
        self.assertEqual(result["status"], "filed")
        self.assertEqual(self.ident.lookup("url", "http://b.test/new"), result["book_id"])
        self.assertEqual(self.ident.lookup("url", "http://a.test/old"), result["book_id"])

    def test_an_address_the_hook_blocks_makes_no_request_no_book_and_no_index_entry(self):
        with self.assertRaises(webclient.Refused) as caught:
            self.capture("http://a.test/p", policy=self.policy(check=lambda url: "on the owner's blacklist"))
        self.assertIn("blacklist", str(caught.exception))
        self.assertEqual((self.lookups, self.dials, self.srv.hits), ([], [], []))
        self.assert_nothing_made()

    def test_a_redirect_to_a_blocked_address_makes_no_book(self):
        self.srv.routes["/p"] = redirect("http://b.test/x")
        with self.assertRaises(webclient.Refused):
            self.capture("http://a.test/p", policy=self.policy(check=lambda url: "blocked" if "b.test" in url else None))
        self.assert_nothing_made()
        self.assertEqual(self.ident.lookup("url", "http://b.test/x"), None)

    def test_a_private_address_is_refused_by_the_policy_without_the_old_prompt_to_allow_it(self):
        with self.assertRaises(webclient.Refused):
            self.capture("http://internal.test/p")
        self.assertEqual(self.books(), [])

    def test_a_response_the_policy_refuses_for_its_type_makes_no_book(self):
        self.srv.routes["/p"] = reply(200, body=b"x", ctype="image/png")
        with self.assertRaises(webclient.Refused):
            self.capture("http://a.test/p")
        self.srv.routes["/q"] = self.ok(b"%PDF-1.7 not a page")
        with self.assertRaises(webclient.Refused):
            self.capture("http://a.test/q")
        self.assertEqual(self.books(), [])
        self.assertEqual(self.ident.lookup("url", "http://a.test/q"), None)

    def test_a_failed_fetch_is_recorded_as_before_and_is_not_a_refusal(self):
        self.srv.routes["/gone"] = reply(404, body=b"nothing")
        result = self.capture("http://a.test/gone")
        self.assertEqual(result["status"], "failed")
        self.assertIn("404", result["reason"])
        self.assertEqual(len(self.books()), 1)
        self.srv.routes["/enc"] = reply(200, [("Content-Encoding", "gzip")], b"x")
        self.assertEqual(self.capture("http://a.test/enc")["status"], "failed")
        self.srv.routes["/drop"] = lambda conn, path, headers: None
        self.assertEqual(self.capture("http://a.test/drop")["status"], "failed")

    def test_a_page_that_is_binary_or_compressed_is_still_a_failed_fetch(self):
        self.srv.routes["/p"] = self.ok(b"<html>\x00\x00</html>")
        with self.assertRaises(webclient.Refused):    # the client's own sniff catches it first
            self.capture("http://a.test/p")
        self.assertEqual(self.books(), [])

    def test_the_types_argument_decides_what_is_taken(self):
        self.srv.routes["/t"] = reply(200, body=b"plain words", ctype="text/plain")
        with self.assertRaises(webclient.Refused):
            self.capture("http://a.test/t")
        result = self.capture("http://a.test/t", types=("text/plain",))
        self.assertEqual(result["status"], "filed")

    def test_a_call_leaves_the_callers_policy_as_it_was(self):
        self.srv.routes["/t"] = reply(200, body=b"plain words", ctype="text/plain")
        policy = self.policy()
        before = (policy.types, policy.accept)
        self.capture("http://a.test/t", policy=policy, types=("text/plain",))
        self.assertEqual((policy.types, policy.accept), before)

    def test_the_types_argument_is_used_without_a_policy_too(self):
        class Fetched:
            final, status, headers, body = "http://a.test/t", 200, {}, b"plain words"

        with mock.patch.object(capture_url, "fetch", return_value=Fetched) as fetch:
            with mock.patch.object(capture_url, "require_allowed"):
                capture_url.capture(self.store, self.ident, "http://a.test/t", types=("text/plain",))
        self.assertEqual(fetch.call_args.kwargs["types"], ("text/plain",))

    def test_the_old_call_makes_no_use_of_the_shared_client(self):
        class Fetched:
            final, status, headers, body = "http://a.test/p", 200, {}, PAGE

        with mock.patch.object(capture_url, "fetch", return_value=Fetched) as fetch, mock.patch.object(webclient, "get", side_effect=AssertionError("used")):
            with mock.patch.object(capture_url, "require_allowed"):
                result = capture_url.capture(self.store, self.ident, "http://a.test/p")
        self.assertEqual(result["status"], "filed")
        self.assertNotIn("types", fetch.call_args.kwargs)

    def test_auto_filed_marks_the_book_and_the_default_does_not(self):
        self.srv.routes["/p"] = self.ok(PAGE)
        self.srv.routes["/q"] = self.ok(PAGE + b"<!-- two -->")
        self.srv.routes["/gone"] = reply(404, body=b"nothing")
        marked = self.capture("http://a.test/p", auto_filed=True)
        plain = self.capture("http://a.test/q")
        failed = self.capture("http://a.test/gone", auto_filed=True)     # a book made for a failure is the crawl's too
        self.assertIs(self.store.read_book(marked["book_id"])["auto_filed"], True)
        self.assertIs(self.store.read_book(plain["book_id"])["auto_filed"], False)
        self.assertIs(self.store.read_book(failed["book_id"])["auto_filed"], True)

    def test_a_duplicate_sighting_does_not_change_the_marked_book(self):
        self.srv.routes["/p"] = self.ok(PAGE)
        self.srv.routes["/same"] = self.ok(PAGE)
        first = self.capture("http://a.test/p", auto_filed=True)
        second = self.capture("http://b.test/same", auto_filed=True)
        self.assertEqual((second["status"], second["book_id"]), ("duplicate", first["book_id"]))
        self.assertEqual(len(self.books()), 1)


def feed_route(body):
    return reply(200, body=body, ctype="application/atom+xml")


class ArxivUnderPolicy(PolicyCase):
    API = "https://api.arxiv.test/api/query"
    PDF = "https://pdf.arxiv.test/pdf"

    def setUp(self):
        super().setUp()
        self.dns["api.arxiv.test"], self.dns["pdf.arxiv.test"] = ["93.184.216.70"], ["93.184.216.71"]
        patcher = mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, version=1, pdf=PDF1, arxiv_id="2101.00001", **meta):
        self.srv.routes[f"/api/query?id_list={arxiv_id}v{version}"] = feed_route(atom(arxiv_id, version, **meta))
        self.srv.routes[f"/pdf/{arxiv_id}v{version}"] = reply(200, body=pdf, ctype="application/pdf")

    def arxiv(self, arxiv_id="2101.00001v1", **kw):
        kw.setdefault("policy", self.policy())
        kw.setdefault("api_base", self.API)
        kw.setdefault("pdf_base", self.PDF)
        return capture_arxiv.capture(self.store, self.ident, arxiv_id, **kw)

    def test_the_metadata_and_the_file_are_both_fetched_by_the_shared_client_under_the_policy(self):
        self.serve()
        result = self.arxiv(policy=self.policy(user_agent="knowledge-base/test (scholarly)", headers={"X-One": "1"}))
        self.assertEqual(result["status"], "filed")
        self.assertEqual([path for path, _ in self.srv.hits], ["/api/query?id_list=2101.00001v1", "/pdf/2101.00001v1"])
        for _, headers in self.srv.hits:
            self.assertEqual((headers["user-agent"], headers["x-one"]), ("knowledge-base/test (scholarly)", "1"))
        self.assertEqual([d[0] for d in self.dials], ["93.184.216.70", "93.184.216.71"])
        self.assertEqual(self.srv.hits[0][1]["accept"], "application/atom+xml, application/xml;q=0.9")
        self.assertEqual(self.srv.hits[1][1]["accept"], "application/pdf")
        book = self.store.read_book(result["book_id"])
        self.assertEqual(book["title"], "A Fixture Paper About Nothing")
        self.assertEqual([h for h in self.lookups if h != "127.0.0.1"], ["api.arxiv.test", "pdf.arxiv.test"])    # the client looked each name up once; nothing else did

    def test_the_metadata_and_file_types_are_the_arxiv_ones_whatever_the_policy_allows(self):
        self.serve()
        self.srv.routes["/pdf/2101.00001v1"] = self.ok(PDF1)    # a PDF served as a page
        with self.assertRaises(webclient.Refused):
            self.arxiv(policy=self.policy(types=("text/html", "application/pdf")))
        self.assertEqual(self.books(), [])

    def test_a_blocked_api_or_file_address_makes_no_book_and_no_index_entry(self):
        self.serve()
        for blocked in ("api.arxiv.test", "pdf.arxiv.test"):
            with self.subTest(blocked):
                with self.assertRaises(webclient.Refused):
                    self.arxiv(policy=self.policy(check=lambda url, blocked=blocked: "blocked" if blocked in url else None))
                self.assertEqual(self.books(), [])
                self.assertIsNone(self.ident.lookup("arxiv", "2101.00001"))

    def test_a_failed_fetch_is_recorded_as_before(self):
        self.srv.routes["/api/query?id_list=2101.00001v1"] = reply(500, body=b"error")
        result = self.arxiv()
        self.assertEqual(result["status"], "failed")
        self.assertIn("500", result["reason"])
        self.assertEqual(len(self.books()), 1)

    def test_a_version_already_held_is_not_requested(self):
        self.serve()
        self.arxiv()
        hits = len(self.srv.hits)
        self.assertEqual(self.arxiv()["status"], "held")
        self.assertEqual(len(self.srv.hits), hits)

    def test_auto_filed_marks_the_book(self):
        self.serve()
        marked = self.arxiv(auto_filed=True)
        self.assertIs(self.store.read_book(marked["book_id"])["auto_filed"], True)
        self.serve(arxiv_id="2102.00002")
        plain = self.arxiv("2102.00002v1")
        self.assertIs(self.store.read_book(plain["book_id"])["auto_filed"], False)
        self.srv.routes["/api/query?id_list=2103.00003v1"] = reply(500, body=b"error")
        failed = self.arxiv("2103.00003v1", auto_filed=True)
        self.assertEqual(failed["status"], "failed")
        self.assertIs(self.store.read_book(failed["book_id"])["auto_filed"], True)
        self.srv.routes["/api/query?id_list=2104.00004v1"] = feed_route(atom("2104.00004", 1))
        self.srv.routes["/pdf/2104.00004v1"] = reply(500, body=b"error")      # the metadata came, the file did not
        late = self.arxiv("2104.00004v1", auto_filed=True)
        self.assertEqual(late["status"], "failed")
        self.assertIs(self.store.read_book(late["book_id"])["auto_filed"], True)

    def test_a_pdf_that_does_not_start_like_one_is_refused_by_the_sniff_and_makes_no_book(self):
        self.serve(pdf=b"<html>not a pdf</html>")
        with self.assertRaises(webclient.Refused):
            self.arxiv()
        self.assertEqual(self.books(), [])

    def test_the_old_call_still_makes_no_use_of_the_shared_client(self):
        with mock.patch.object(webclient, "get", side_effect=AssertionError("used")):
            with mock.patch.object(capture_url, "fetch", side_effect=capture_url.FetchError("down")):
                with mock.patch.object(capture_url, "require_allowed"):
                    result = capture_arxiv.capture(self.store, self.ident, "2101.00001v1")
        self.assertEqual(result["status"], "failed")


class Contract(unittest.TestCase):
    def test_the_new_arguments_have_the_agreed_names_and_defaults(self):
        import inspect
        for fn in (capture_url.capture, capture_arxiv.capture):
            params = inspect.signature(fn).parameters
            self.assertIsNone(params["policy"].default, fn.__module__)
            self.assertIs(params["auto_filed"].default, False, fn.__module__)
        self.assertIsNone(inspect.signature(capture_url.capture).parameters["types"].default)

    def test_capture_url_imports_the_shared_client_only_inside_a_function(self):
        with open(os.path.join(ENGINE_DIR, "kb", "capture_url.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotRegex(source, r"(?m)^(from \. import .*\bwebclient\b|import .*webclient|from \.webclient)")


if __name__ == "__main__":
    unittest.main()
