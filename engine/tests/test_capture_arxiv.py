import hashlib
import json
import os
import subprocess
import sys
import unittest
from unittest import mock
from xml.sax.saxutils import escape

from engine.tests import ENGINE_DIR
from engine.tests.test_capture_url import Site, ids_new
from engine.tests.test_store import StoreCase

from kb import KbError, capture_arxiv, capture_url, identity, stages

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


PDF1, PDF2 = fixture("paper-v1.pdf"), fixture("paper-v2.pdf")
ERROR_FEED = fixture("arxiv-error.xml")
ID = "2101.00001"


def atom(arxiv_id=ID, version=1, title="A Fixture Paper About Nothing", authors=("Ada Example", "Bo Sample"),
         published="2021-01-01T00:00:00Z", categories=("cs.AI", "cs.LG"), doi=None, summary="An abstract."):
    cats = "".join(f'<category term="{c}" scheme="http://arxiv.org/schemas/atom"/>' for c in categories)
    people = "".join(f"<author><name>{escape(a)}</name></author>" for a in authors)
    doi_el = f'<arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">{doi}</arxiv:doi>' if doi else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/{arxiv_id}v{version}</id>
    <updated>2021-02-0{version}T00:00:00Z</updated>
    <published>{published}</published>
    <title>{escape(title)}</title>
    <summary>{escape(summary)}</summary>
    {people}
    {doi_el}
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="{categories[0]}" scheme="http://arxiv.org/schemas/atom"/>
    {cats}
  </entry>
</feed>
""".encode()


class ArxivCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.site = Site()
        self.addCleanup(self.site.stop)
        self.ident = identity.Identity(self.index)
        self.api = self.site.url("/api/query")
        self.pdf = self.site.url("/pdf")

    def serve(self, arxiv_id=ID, version=1, pdf=PDF1, **meta):
        """Serve one version of a paper: its metadata at the API and its file under /pdf."""
        self.site.add(f"/api/query?id_list={arxiv_id}v{version}", body=atom(arxiv_id, version, **meta),
                      content_type="application/atom+xml")
        self.site.add(f"/pdf/{arxiv_id}v{version}", body=pdf, content_type="application/pdf")

    def serve_latest(self, arxiv_id=ID, version=2, **meta):
        self.site.add(f"/api/query?id_list={arxiv_id}", body=atom(arxiv_id, version, **meta),
                      content_type="application/atom+xml")

    def capture(self, arxiv_id=ID, **kw):
        kw.setdefault("allow_private", True)  # the test server is on the local machine
        kw.setdefault("api_base", self.api)
        kw.setdefault("pdf_base", self.pdf)
        return capture_arxiv.capture(self.store, self.ident, arxiv_id, **kw)

    def requests(self):
        return [p for p, _h in self.site.hits]


class ParseIdTest(unittest.TestCase):
    def test_valid_ids_are_split_into_the_paper_and_the_version(self):
        p = capture_arxiv.parse_id
        self.assertEqual(p("2101.00001"), ("2101.00001", None))
        self.assertEqual(p("2101.00001v2"), ("2101.00001", 2))
        self.assertEqual(p("1706.03762"), ("1706.03762", None))
        self.assertEqual(p("0704.0001v10"), ("0704.0001", 10))
        self.assertEqual(p("arXiv:2101.00001v1"), ("2101.00001", 1))
        self.assertEqual(p("ARXIV:2101.00001"), ("2101.00001", None))
        self.assertEqual(p("cs/0112017"), ("cs/0112017", None))
        self.assertEqual(p("math.GT/0309136v2"), ("math.GT/0309136", 2))
        self.assertEqual(p("hep-th/9901001"), ("hep-th/9901001", None))

    def test_digits_from_other_scripts_are_not_digits_here(self):
        for bad in ("\uff12\uff11\uff10\uff11.00001", "2101.\u0660\u0660\u0660\u0660\u0661", "2101.00001v\u0662"):
            with self.assertRaises(KbError, msg=repr(bad)):
                capture_arxiv.parse_id(bad)

    def test_the_default_api_address_is_encrypted(self):
        self.assertTrue(capture_arxiv.API_BASE.startswith("https://"))
        self.assertTrue(capture_arxiv.PDF_BASE.startswith("https://"))

    def test_an_id_of_the_wrong_shape_is_refused(self):
        for bad in ("", "abc", "2101.0001x", "21013.00001", "2113.00001", "2100.00001", "2101.000001", "2101.00001v0",
                    "2101.00001v", "2101.00001v1.1", "../x", "2101.00001/../x", "http://arxiv.org/abs/2101.00001",
                    "2101.00001\n", "\n2101.00001", " 2101.00001", "2101.00001 ", "cs/012345", "CS/0112017", "cs.AI/0112017x", None, 5, "2101.00001 v1",
                    "2101.00001v1000000"):
            with self.assertRaises(KbError, msg=repr(bad)):
                capture_arxiv.parse_id(bad)


class FiledPaperTest(ArxivCase):
    def test_a_paper_is_stored_with_its_metadata(self):
        self.serve(doi="10.1000/example.1")
        result = self.capture(f"{ID}v1")
        self.assertEqual(result["status"], "filed")
        book, version = result["book_id"], result["version_id"]
        self.assertEqual(self.requests(), [f"/api/query?id_list={ID}v1", f"/pdf/{ID}v1"])
        with open(os.path.join(self.store.payload_dir(book, version, "original"), "paper.pdf"), "rb") as f:
            self.assertEqual(f.read(), PDF1)
        root = self.store.read_book(book)
        self.assertEqual((root["title"], root["authors"], root["year"], root["kind"]),
                         ("A Fixture Paper About Nothing", ["Ada Example", "Bo Sample"], 2021, "preprint"))
        keys = root["identity_keys"]
        self.assertEqual((keys["arxiv"], keys["doi"]), (ID, "10.1000/example.1"))
        self.assertEqual(keys["sha256"], [hashlib.sha256(PDF1).hexdigest()])
        v = self.store.read_version(book, version)
        self.assertEqual(v["label"], "v1")
        self.assertEqual(v["primary"], "paper.pdf")
        src = v["source"]
        self.assertEqual((src["arxiv_id"], src["label"], src["http_status"]), (ID, "v1", 200))
        self.assertEqual(src["categories"], ["cs.AI", "cs.LG"])
        self.assertEqual(src["primary_category"], "cs.AI")
        self.assertEqual(src["abstract"], "An abstract.")
        self.assertEqual(src["sha256"], hashlib.sha256(PDF1).hexdigest())
        self.assertEqual(src["address_pdf"], f"{self.pdf}/{ID}v1")
        self.assertRegex(src["retrieved"], r"^\d{4}-\d\d-\d\dT")
        self.store.verify_payload(book, version, "original")
        state = stages.read(self.store, book, version)["stages"]
        self.assertEqual((state["fetched"]["status"], state["scanned"]["status"]), ("done", "pending"))
        self.assertEqual([e["event"] for e in self.store.read_events(book)], ["filed"])
        self.assertEqual(self.ident.lookup("arxiv", ID), book)
        self.assertEqual(self.ident.lookup("doi", "10.1000/example.1"), book)
        self.assertEqual(self.ident.lookup("sha256", hashlib.sha256(PDF1).hexdigest()), book)

    def test_the_requests_are_honest_and_plain(self):
        self.serve()
        self.capture(f"{ID}v1")
        for _path, headers in self.site.hits:
            self.assertTrue(headers["User-Agent"].startswith("knowledge-base/"), headers["User-Agent"])
            self.assertNotIn("Cookie", headers)

    def test_text_from_the_source_is_cleaned_and_bounded(self):
        self.serve(title="  A   title\nspread   over\tlines  " + "x" * 800, authors=tuple(f"Author {i}" for i in range(400)),
                   summary="line one\n\n  line   two  ")
        result = self.capture(f"{ID}v1")
        root = self.store.read_book(result["book_id"])
        self.assertNotIn("\n", root["title"])
        self.assertTrue(root["title"].startswith("A title spread over lines xxx"))
        self.assertLessEqual(len(root["title"]), 500)
        self.assertEqual(len(root["authors"]), 200)
        src = self.store.read_version(result["book_id"], result["version_id"])["source"]
        self.assertEqual(src["abstract"], "line one line two")

    def test_a_malformed_doi_is_dropped(self):
        bad_dois = ("not a doi", "10.1/x", "10.1000/" + "x" * 300, "doi:10.1000/abc", "10.1000/has space")
        for i, bad in enumerate(bad_dois):
            arxiv_id = f"2101.0001{i}"
            self.serve(arxiv_id=arxiv_id, doi=bad)
            result = self.capture(f"{arxiv_id}v1")
            self.assertEqual(result["status"], "filed", bad)
            self.assertNotIn("doi", self.store.read_book(result["book_id"])["identity_keys"], bad)

    def test_digits_from_other_scripts_in_the_year_or_doi_are_dropped(self):
        self.serve(published="\u0662\u0660\u0662\u0661-01-01T00:00:00Z", doi="10.\u0661\u0662\u0663\u0664/x")
        result = self.capture(f"{ID}v1")
        root = self.store.read_book(result["book_id"])
        self.assertIsNone(root["year"])
        self.assertNotIn("doi", root["identity_keys"])

    def test_direction_marks_and_control_characters_are_removed_from_text_taken_from_the_source(self):
        self.serve(title="Safe\u202e title\u200b with\x9b marks", authors=("Ada\u2066 Example",), summary="an\u202d abstract")
        result = self.capture(f"{ID}v1")
        root = self.store.read_book(result["book_id"])
        self.assertEqual(root["title"], "Safe title with marks")
        self.assertEqual(root["authors"], ["Ada Example"])
        src = self.store.read_version(result["book_id"], result["version_id"])["source"]
        self.assertEqual(src["abstract"], "an abstract")

    def test_a_doi_already_held_by_another_book_is_not_taken_over(self):
        self.serve(arxiv_id="2101.00001", doi="10.1000/shared.1")
        self.serve(arxiv_id="2101.00002", doi="10.1000/shared.1", pdf=PDF2)
        a, b = self.capture("2101.00001v1"), self.capture("2101.00002v1")
        self.assertEqual(self.ident.lookup("doi", "10.1000/shared.1"), a["book_id"])
        self.assertEqual(self.store.read_book(a["book_id"])["identity_keys"]["doi"], "10.1000/shared.1")
        self.assertNotIn("doi", self.store.read_book(b["book_id"])["identity_keys"])
        os.remove(os.path.join(self.index, "identity.sqlite"))
        self.ident = identity.Identity(self.index)
        self.ident.rebuild(self.store)  # the rebuilt index agrees with the live one
        self.assertEqual(self.ident.lookup("doi", "10.1000/shared.1"), a["book_id"])

    def test_a_missing_year_or_doi_is_left_out_not_invented(self):
        self.serve(published="not a date")
        result = self.capture(f"{ID}v1")
        root = self.store.read_book(result["book_id"])
        self.assertIsNone(root["year"])
        self.assertNotIn("doi", root["identity_keys"])


class VersionsTest(ArxivCase):
    def test_a_version_already_held_is_not_downloaded_again(self):
        self.serve()
        first = self.capture(f"{ID}v1")
        before = self.requests()
        again = self.capture(f"{ID}v1")
        self.assertEqual((again["status"], again["book_id"], again["version_id"]),
                         ("held", first["book_id"], first["version_id"]))
        self.assertEqual(self.requests(), before)  # not even the metadata was asked for
        self.assertEqual(self.store.list_books(), [first["book_id"]])

    def test_a_new_label_adds_a_version_and_makes_it_current_and_keeps_the_old_one(self):
        self.serve(version=1, pdf=PDF1)
        first = self.capture(f"{ID}v1")
        old = self.store.verify_payload(first["book_id"], first["version_id"], "original")
        self.serve(version=2, pdf=PDF2, title="A Fixture Paper, Corrected")
        second = self.capture(f"{ID}v2")
        self.assertEqual(second["status"], "filed")
        book = first["book_id"]
        self.assertEqual(second["book_id"], book)
        self.assertEqual(self.store.list_books(), [book])
        self.assertEqual(self.store.version_ids(book), ["v1", "v2"])
        root = self.store.read_book(book)
        self.assertEqual(root["current_version"], second["version_id"])
        self.assertEqual(root["title"], "A Fixture Paper, Corrected")
        self.assertEqual(root["identity_keys"]["sha256"], [hashlib.sha256(PDF1).hexdigest(), hashlib.sha256(PDF2).hexdigest()])
        self.assertEqual(self.store.read_version(book, second["version_id"])["label"], "v2")
        self.assertEqual(self.store.verify_payload(book, first["version_id"], "original"), old)  # v1 is unchanged
        with open(os.path.join(self.store.payload_dir(book, first["version_id"], "original"), "paper.pdf"), "rb") as f:
            self.assertEqual(f.read(), PDF1)

    def test_an_older_label_captured_later_does_not_become_current(self):
        self.serve(version=2, pdf=PDF2, title="Newest title")
        newest = self.capture(f"{ID}v2")
        self.serve(version=1, pdf=PDF1, title="Oldest title")
        older = self.capture(f"{ID}v1")
        self.assertEqual(older["status"], "filed")
        root = self.store.read_book(newest["book_id"])
        self.assertEqual(root["current_version"], newest["version_id"])
        self.assertEqual(root["title"], "Newest title")
        self.assertEqual(self.store.read_version(newest["book_id"], older["version_id"])["label"], "v1")

    def test_no_label_asks_for_the_latest_and_is_held_without_the_file_when_it_is_already_stored(self):
        self.serve(version=2, pdf=PDF2)
        self.serve_latest(version=2)
        first = self.capture(ID)  # the latest is v2
        self.assertEqual(first["status"], "filed")
        self.assertEqual(self.store.read_version(first["book_id"], first["version_id"])["label"], "v2")
        pdf_requests = [p for p in self.requests() if p.startswith("/pdf/")]
        again = self.capture(ID)
        self.assertEqual((again["status"], again["book_id"]), ("held", first["book_id"]))
        self.assertEqual([p for p in self.requests() if p.startswith("/pdf/")], pdf_requests)  # no second file download
        self.assertEqual(self.requests()[-1], f"/api/query?id_list={ID}")  # but the metadata was asked for

    def test_a_newer_label_whose_file_failed_does_not_become_current(self):
        self.serve(version=1, pdf=PDF1, title="Old title")
        first = self.capture(f"{ID}v1")
        self.site.add(f"/api/query?id_list={ID}v2", body=atom(ID, 2, title="New title"), content_type="application/atom+xml")
        self.site.add(f"/pdf/{ID}v2", status=503, body=b"later", content_type="text/plain")
        failed = self.capture(f"{ID}v2")
        self.assertEqual(failed["status"], "failed")
        root = self.store.read_book(first["book_id"])
        self.assertEqual(root["current_version"], first["version_id"])  # the one that was fetched stays current
        self.assertEqual(root["title"], "Old title")
        self.site.add(f"/pdf/{ID}v2", body=PDF2, content_type="application/pdf")
        done = self.capture(f"{ID}v2")
        self.assertEqual((done["status"], done["version_id"]), ("filed", failed["version_id"]))
        root = self.store.read_book(first["book_id"])
        self.assertEqual((root["current_version"], root["title"]), (done["version_id"], "New title"))

    def test_a_stop_after_a_new_version_is_added_leaves_the_fetched_one_current(self):
        self.serve(version=1, pdf=PDF1)
        first = self.capture(f"{ID}v1")
        self.serve(version=2, pdf=PDF2)
        with mock.patch.object(self.store, "file_payload", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v2")
        self.assertEqual(self.store.version_ids(first["book_id"]), ["v1", "v2"])
        self.assertEqual(self.store.read_book(first["book_id"])["current_version"], first["version_id"])

    def test_an_edit_of_the_title_survives_later_requests_until_a_newer_version_arrives(self):
        self.serve(version=1, pdf=PDF1, title="Source title one")
        first = self.capture(f"{ID}v1")
        self.store.set_metadata(first["book_id"], title="The owner's own title")
        self.assertEqual(self.capture(f"{ID}v1")["status"], "held")
        self.assertEqual(self.store.read_book(first["book_id"])["title"], "The owner's own title")
        self.serve(version=2, pdf=PDF2, title="Source title two")
        self.capture(f"{ID}v2")
        self.assertEqual(self.store.read_book(first["book_id"])["title"], "Source title two")

    def test_a_resumed_capture_gets_one_filed_event_not_none_and_not_two(self):
        self.serve()
        with mock.patch.object(capture_arxiv.stages, "mark", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v1")
        (book,) = self.store.list_books()
        self.assertEqual([e["event"] for e in self.store.read_events(book)], ["filed"])  # written before the stop
        self.capture(f"{ID}v1")
        self.assertEqual([e["event"] for e in self.store.read_events(book)], ["filed"])
        # and when the stop came before the event was written
        self.serve(arxiv_id="2101.00002", pdf=PDF2)
        with mock.patch.object(self.store, "append_event", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("2101.00002v1")
        other = [b for b in self.store.list_books() if b != book][0]
        self.assertEqual(self.store.read_events(other), [])
        self.capture("2101.00002v1")
        events = self.store.read_events(other)
        self.assertEqual([e["event"] for e in events], ["filed"])
        self.assertTrue(events[0]["resumed"])

    def test_a_stop_before_the_title_is_updated_is_repaired_by_the_next_call(self):
        self.serve(version=1, pdf=PDF1, title="Old title")
        first = self.capture(f"{ID}v1")
        self.serve(version=2, pdf=PDF2, title="New title")
        with mock.patch.object(capture_arxiv, "_finish", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v2")
        self.assertEqual(self.store.read_book(first["book_id"])["title"], "Old title")
        before = self.requests()
        again = self.capture(f"{ID}v2")
        self.assertEqual(again["status"], "held")
        self.assertEqual(self.requests(), before)
        repaired = self.store.read_book(first["book_id"])
        self.assertEqual((repaired["current_version"], repaired["title"]), (again["version_id"], "New title"))

    def test_an_older_label_filed_after_a_newer_one_never_becomes_current_even_if_the_capture_stops(self):
        self.serve(version=2, pdf=PDF2, title="New title")
        newest = self.capture(f"{ID}v2")
        self.serve(version=1, pdf=PDF1, title="Old title")
        with mock.patch.object(capture_arxiv, "_finish", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v1")
        root = self.store.read_book(newest["book_id"])
        self.assertEqual((root["current_version"], root["title"]), (newest["version_id"], "New title"))
        self.assertEqual(self.capture(f"{ID}v1")["status"], "held")
        root = self.store.read_book(newest["book_id"])
        self.assertEqual((root["current_version"], root["title"]), (newest["version_id"], "New title"))

    def test_two_papers_with_the_same_bytes_stay_two_books(self):
        self.serve(arxiv_id="2101.00001", pdf=PDF1)
        self.serve(arxiv_id="2101.00002", pdf=PDF1)
        a, b = self.capture("2101.00001v1"), self.capture("2101.00002v1")
        self.assertNotEqual(a["book_id"], b["book_id"])
        self.assertEqual(self.ident.lookup("sha256", hashlib.sha256(PDF1).hexdigest()), a["book_id"])  # first claim kept
        self.assertEqual(self.store.read_book(b["book_id"])["identity_keys"].get("sha256"), [hashlib.sha256(PDF1).hexdigest()])


class RefusalTest(ArxivCase):
    def assert_failed_and_recorded(self, result, fragment):
        self.assertEqual(result["status"], "failed", result)
        self.assertIn(fragment, result["reason"])
        entry = stages.read(self.store, result["book_id"], result["version_id"])["stages"]["fetched"]
        self.assertEqual(entry["status"], "failed")
        self.assertIn(fragment, entry["reason"])
        self.assertIsNone(self.store.payload_dir(result["book_id"], result["version_id"], "original"))

    def test_an_id_of_the_wrong_shape_is_refused_before_anything_is_requested_or_recorded(self):
        for bad in ("not-an-id", "2101.00001v0", "http://127.0.0.1/x"):
            with self.assertRaises(KbError):
                self.capture(bad)
        self.assertEqual(self.site.count(), 0)
        self.assertEqual(self.store.list_books(), [])

    def test_something_that_is_not_a_pdf_is_refused(self):
        self.serve(pdf=b"<html>a login page</html>")
        self.site.add(f"/pdf/{ID}v1", body=b"<html>a login page</html>", content_type="text/html")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "not a PDF")

    def test_a_file_that_calls_itself_a_pdf_but_does_not_start_like_one_is_refused(self):
        self.serve(pdf=b"<html>a login page</html>")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "not a PDF")

    def test_real_pdf_bytes_served_with_the_wrong_content_type_are_refused(self):
        self.serve()
        self.site.add(f"/pdf/{ID}v1", body=PDF1, content_type="text/html")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "not a PDF")

    def test_a_pdf_over_the_size_cap_is_refused(self):
        self.serve(pdf=b"%PDF-1.4\n" + b"x" * 5000)
        self.assert_failed_and_recorded(self.capture(f"{ID}v1", max_bytes=1000), "larger than")

    def test_a_pdf_shorter_than_its_declared_length_is_refused(self):
        self.serve()
        self.site.add(f"/pdf/{ID}v1", body=PDF1[:40], content_type="application/pdf",
                      headers={"Content-Length": str(len(PDF1))})
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "ended early")

    def test_an_error_answer_from_the_api_is_a_recorded_failure_with_arxivs_reason(self):
        self.site.add(f"/api/query?id_list={ID}v1", body=ERROR_FEED, content_type="application/atom+xml")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "incorrect id format")
        self.assertEqual(self.site.count(f"/pdf/{ID}v1"), 0)

    def test_an_answer_with_no_entry_means_the_paper_was_not_found(self):
        self.site.add(f"/api/query?id_list={ID}v1", content_type="application/atom+xml",
                      body=b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "not found")

    def test_an_answer_about_another_paper_or_version_is_refused(self):
        self.site.add(f"/api/query?id_list={ID}v1", body=atom("2101.99999", 1), content_type="application/atom+xml")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "another paper")
        self.site.add(f"/api/query?id_list={ID}v2", body=atom(ID, 1), content_type="application/atom+xml")
        result = self.capture(f"{ID}v2")
        self.assertEqual(result["status"], "failed")
        self.assertIn("version", result["reason"])

    def test_malformed_metadata_is_a_failure_not_a_crash(self):
        self.site.add(f"/api/query?id_list={ID}v1", body=b"<feed><entry>", content_type="application/atom+xml")
        self.assert_failed_and_recorded(self.capture(f"{ID}v1"), "metadata")

    def test_metadata_that_declares_entities_is_refused_without_being_parsed(self):
        bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
                b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>&b;</id></entry></feed>')
        self.site.add(f"/api/query?id_list={ID}v1", body=bomb, content_type="application/atom+xml")
        with mock.patch("xml.etree.ElementTree.fromstring", side_effect=AssertionError("parsed")):
            result = self.capture(f"{ID}v1")
        self.assert_failed_and_recorded(result, "declaration")

    def test_metadata_in_another_encoding_is_refused_so_the_entity_check_cannot_be_walked_around(self):
        bomb = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">]>'
                '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>&a;</id></entry></feed>').encode("utf-16")
        self.site.add(f"/api/query?id_list={ID}v1", body=bomb, content_type="application/atom+xml")
        with mock.patch("xml.etree.ElementTree.fromstring", side_effect=AssertionError("parsed")):
            result = self.capture(f"{ID}v1")
        self.assert_failed_and_recorded(result, "UTF-8")
        # UTF-16 with no byte-order mark is valid UTF-8 (it is full of NUL bytes), and a parser still reads it
        bomb_le = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">]>'
                   '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>&a;</id></entry></feed>').encode("utf-16-le")
        self.site.add(f"/api/query?id_list={ID}v1", body=bomb_le, content_type="application/atom+xml")
        with mock.patch("xml.etree.ElementTree.fromstring", side_effect=AssertionError("parsed")):
            result = self.capture(f"{ID}v1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("NUL", result["reason"])
        # bytes that are not UTF-8 and have no NUL
        self.site.add(f"/api/query?id_list={ID}v1", body=b"<feed>\xff</feed>", content_type="application/atom+xml")
        result = self.capture(f"{ID}v1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("not valid UTF-8", result["reason"])

    def test_metadata_over_its_size_cap_is_refused(self):
        self.serve()
        self.site.add(f"/api/query?id_list={ID}v1", body=atom(summary="s" * 5000), content_type="application/atom+xml")
        result = self.capture(f"{ID}v1", metadata_max_bytes=2000)
        self.assert_failed_and_recorded(result, "larger than")

    def test_a_failed_file_fetch_is_retried_into_the_same_version(self):
        self.serve()
        self.site.add(f"/pdf/{ID}v1", status=503, body=b"later", content_type="text/plain")
        failed = self.capture(f"{ID}v1")
        self.assert_failed_and_recorded(failed, "HTTP 503")
        self.assertEqual(self.store.read_version(failed["book_id"], failed["version_id"])["label"], "v1")
        self.site.add(f"/pdf/{ID}v1", body=PDF1, content_type="application/pdf")
        again = self.capture(f"{ID}v1")
        self.assertEqual((again["status"], again["book_id"], again["version_id"]),
                         ("filed", failed["book_id"], failed["version_id"]))
        self.assertEqual(self.store.version_ids(again["book_id"]), ["v1"])
        self.assertEqual(self.store.list_books(), [again["book_id"]])
        root = self.store.read_book(again["book_id"])
        self.assertEqual((root["title"], root["year"]), ("A Fixture Paper About Nothing", 2021))

    def test_a_failed_metadata_fetch_is_retried_into_the_same_book(self):
        self.site.add(f"/api/query?id_list={ID}v1", status=500, body=b"down", content_type="text/plain")
        failed = self.capture(f"{ID}v1")
        self.assertEqual(failed["status"], "failed")
        self.serve()
        again = self.capture(f"{ID}v1")
        self.assertEqual((again["status"], again["book_id"]), ("filed", failed["book_id"]))
        self.assertEqual(self.store.version_ids(again["book_id"]), ["v1"])

    def test_a_failed_request_for_the_latest_is_retried_into_the_same_unlabelled_version(self):
        self.site.add(f"/api/query?id_list={ID}", status=500, body=b"down", content_type="text/plain")
        failed = self.capture(ID)
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(self.store.read_version(failed["book_id"], failed["version_id"])["label"])
        self.serve(version=2, pdf=PDF2)
        self.serve_latest(version=2)
        again = self.capture(ID)
        self.assertEqual((again["status"], again["book_id"], again["version_id"]),
                         ("filed", failed["book_id"], failed["version_id"]))
        self.assertEqual(self.store.read_version(again["book_id"], again["version_id"])["label"], "v2")
        self.assertEqual(self.store.version_ids(again["book_id"]), ["v1"])

    def test_a_stop_after_the_file_is_stored_but_before_its_stage_is_marked_is_adopted_without_a_download(self):
        self.serve()
        with mock.patch.object(capture_arxiv.stages, "mark", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v1")
        (book,) = self.store.list_books()
        before = self.requests()
        again = self.capture(f"{ID}v1")
        self.assertEqual((again["status"], again["book_id"]), ("held", book))
        self.assertEqual(self.requests(), before)  # nothing was asked for again
        version = again["version_id"]
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertEqual(self.ident.lookup("sha256", hashlib.sha256(PDF1).hexdigest()), book)
        self.store.verify_payload(book, version, "original")

    def test_a_stop_after_the_book_is_made_resumes_into_the_same_book(self):
        self.serve()
        with mock.patch.object(self.store, "add_version", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture(f"{ID}v1")
        (book,) = self.store.list_books()
        again = self.capture(f"{ID}v1")
        self.assertEqual((again["status"], again["book_id"]), ("filed", book))
        self.assertEqual(self.store.list_books(), [book])

    def test_a_stale_index_entry_is_ignored(self):
        self.serve()
        self.ident.register("arxiv", ID, ids_new())
        result = self.capture(f"{ID}v1")
        self.assertEqual(result["status"], "filed")
        self.assertEqual(self.ident.lookup("arxiv", ID), result["book_id"])

    def test_a_private_address_is_refused_by_default_before_anything_is_requested(self):
        self.serve()
        with self.assertRaises(KbError) as cm:
            capture_arxiv.capture(self.store, self.ident, f"{ID}v1", api_base=self.api, pdf_base=self.pdf)
        self.assertIn("private", str(cm.exception))
        self.assertEqual(self.site.count(), 0)
        self.assertEqual(self.store.list_books(), [])

    def test_a_base_address_that_is_not_http_is_refused(self):
        for bad in ("file:///etc/", "ftp://example.org/pdf", "http://user:pw@example.org/pdf"):
            with self.assertRaises(KbError):
                self.capture(f"{ID}v1", pdf_base=bad)
        self.assertEqual(self.site.count(), 0)

    def test_a_failing_write_guard_refuses_before_any_request(self):
        self.serve()
        os.remove(os.path.join(self.bulk, ".kb-library"))
        with self.assertRaises(KbError):
            self.capture(f"{ID}v1")
        self.assertEqual(self.site.count(), 0)


class IndexAndCommandLineTest(ArxivCase):
    def test_the_index_rebuilds_with_the_arxiv_id_the_doi_and_the_hashes(self):
        self.serve(doi="10.1000/example.1")
        result = self.capture(f"{ID}v1")
        os.remove(os.path.join(self.index, "identity.sqlite"))
        self.ident = identity.Identity(self.index)
        self.ident.rebuild(self.store)
        for key in (("arxiv", ID), ("doi", "10.1000/example.1"), ("sha256", hashlib.sha256(PDF1).hexdigest())):
            self.assertEqual(self.ident.lookup(*key), result["book_id"], key)

    def run_kb(self, *args):
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR,
                              env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=60)

    def test_capture_through_the_command_line(self):
        self.serve()
        args = ["capture-arxiv", f"{ID}v1", "--allow-private", "--api-base", self.api, "--pdf-base", self.pdf]
        first = self.run_kb(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "filed")
        second = self.run_kb(*args)
        self.assertEqual(json.loads(second.stdout)["status"], "held")

    def test_a_wrong_id_is_refused_with_exit_code_two(self):
        done = self.run_kb("capture-arxiv", "nonsense", "--allow-private")
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr.startswith("refused: "), done.stderr)

    def test_a_failed_fetch_exits_nonzero_and_says_why(self):
        self.site.add(f"/api/query?id_list={ID}v1", body=ERROR_FEED, content_type="application/atom+xml")
        done = self.run_kb("capture-arxiv", f"{ID}v1", "--allow-private", "--api-base", self.api, "--pdf-base", self.pdf)
        self.assertEqual(done.returncode, 1)
        self.assertIn("incorrect id format", done.stderr)


class StoreAdditionsTest(StoreCase):
    def test_the_current_version_can_be_set_to_an_existing_version_only(self):
        book = self.store.create_book(title="t", kind="preprint")
        self.store.add_version(book, label="v1")
        self.store.add_version(book, label="v2")
        self.store.set_current_version(book, "v1")
        self.assertEqual(self.store.read_book(book)["current_version"], "v1")
        with self.assertRaises(KbError):
            self.store.set_current_version(book, "v9")
        with self.assertRaises(KbError):
            self.store.set_current_version(book, "../v1")

    def test_the_version_the_metadata_came_from_can_be_recorded(self):
        book = self.store.create_book(title="t", kind="preprint")
        self.store.set_metadata(book, metadata_source="v2")
        self.assertEqual(self.store.read_book(book)["metadata_source"], "v2")
        with self.assertRaises(KbError):
            self.store.set_metadata(book, metadata_source=5)

    def test_a_versions_label_can_be_set(self):
        book = self.store.create_book(title="t", kind="preprint")
        version = self.store.add_version(book)
        self.assertIsNone(self.store.read_version(book, version)["label"])
        self.store.set_version_label(book, version, "v3")
        self.assertEqual(self.store.read_version(book, version)["label"], "v3")
        with self.assertRaises(KbError):
            self.store.set_version_label(book, version, 3)

    def test_metadata_fields_can_be_changed_and_nothing_else(self):
        book = self.store.create_book(title="old", kind="preprint", authors=["A"], year=2020)
        self.store.set_metadata(book, title="new", authors=["B", "C"], year=2021, language="en")
        root = self.store.read_book(book)
        self.assertEqual((root["title"], root["authors"], root["year"], root["language"]), ("new", ["B", "C"], 2021, "en"))
        self.store.set_metadata(book, year=None)
        self.assertIsNone(self.store.read_book(book)["year"])
        for bad in ({"state": "removed"}, {"book_id": "x"}, {"title": 5}, {"authors": "A"}, {"year": "2021"}):
            with self.assertRaises(KbError, msg=repr(bad)):
                self.store.set_metadata(book, **bad)


if __name__ == "__main__":
    unittest.main()
