import json
import os
import time
import unittest
import zlib
from unittest import mock

from engine.tests.test_capture_url import Site
from engine.tests.test_convert_run import PROBE, SandboxCase, approve

from kb import KbError, approvals, capture_url, convert_run, identity, scan, stages


def pdf(body=b"", trailer=b"trailer << /Root 1 0 R >>"):
    return b"%PDF-1.4\n" + body + b"\n" + trailer + b"\n%%EOF\n"


def flate(payload):
    return b"2 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + zlib.compress(payload) + b"\nendstream\nendobj"


CLEAN_PDF = pdf(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
SCRIPT_HTML = (b'<html><body onload="x()"><script>EVIL INSTRUCTION</script><script src="a.js"></script>'
               b'<a href=" Java\tScript:alert(1)">x</a><meta http-equiv="refresh" content="0;url=http://x">'
               b'<iframe src="y"></iframe></body></html>')
HIDDEN_HTML = (b'<div style="display:none">twelve chars</div><p hidden>abc de</p><span style="font-size:0">zz</span>'
               b'<p>visible text</p>')


def kinds(caveats):
    return {c["kind"]: c["count"] for c in caveats}


class ScanCase(SandboxCase):
    def file_original(self, name, data, fetched=True):
        book = self.store.create_book(title="t", kind="web page")
        version = self.store.add_version(book)
        self.store.file_payload(book, version, "original", {name: data}, primary=name)
        if fetched:
            stages.mark(self.store, book, version, "fetched", "done")
        return book, version

    def approve_scan(self, **kw):
        entry = approvals.builtin_scan_entry()
        entry.update(kw)
        approve([entry])

    def fake(self, mode, *args, formats=("pdf", "html"), timeout=20, max_output=1_000_000):
        """An approved tool that goes by the scan tool's name and version but is the probe."""
        command = [self.exe, "-I", PROBE, "{input}", "{output}", mode, *map(str, args)]
        return approvals.describe(scan.TOOL_NAME, scan.TOOL_VERSION, command, reads=[self.prefix],
                                  formats=list(formats), timeout=timeout, max_output=max_output, pin=[PROBE])

    def scan_bytes(self, name, data):
        book, version = self.file_original(name, data)
        return book, version, scan.scan_version(self.store, book, version)


class PdfScanTest(ScanCase):
    def test_a_clean_pdf_has_no_caveats_and_its_output_is_filed_as_untrusted(self):
        self.approve_scan()
        book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result, {"status": "done", "caveats": []})
        v = self.store.read_version(book, version)
        self.assertEqual(v["caveats"], [])
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "done")
        manifest = self.store.verify_payload(book, version, "derived/kb-scan/1")
        self.assertTrue(manifest["untrusted"])
        self.assertEqual(manifest["tool"], scan.TOOL_LABEL)
        self.store.verify_payload(book, version, "original")

    def test_each_kind_of_pdf_finding_becomes_a_caveat_and_the_book_stays_filed(self):
        self.approve_scan()
        cases = {
            "encrypted": (pdf(trailer=b"trailer << /Root 1 0 R /Encrypt 5 0 R >>"), {"encrypted": 1}),
            "javascript": (pdf(b"1 0 obj << /S /JavaScript /JS (app.alert(1)) >> endobj"), {"javascript": 2}),
            "escaped name": (pdf(b"1 0 obj << /S /J#61vaScript >> endobj"), {"javascript": 1}),
            "inside a compressed stream": (pdf(flate(b"<< /S /JavaScript /JS (x) >>")), {"javascript": 2}),
            "embedded file": (pdf(b"<< /Type /EmbeddedFile >> << /Names [(a) 3 0 R] /EmbeddedFiles 4 0 R >>"),
                              {"embedded_files": 2}),
            "launch": (pdf(b"<< /S /Launch /F (calc.exe) >>"), {"launch_action": 1}),
            "xfa": (pdf(b"<< /XFA [(x)] >>"), {"xfa_forms": 1}),
            "not really a pdf": (b"just some text", {"malformed": 1}),
        }
        for label, (data, expected) in cases.items():
            book, version, result = self.scan_bytes("paper.pdf", data)
            self.assertEqual(result["status"], "done", label)
            self.assertEqual(kinds(result["caveats"]), expected, label)
            self.assertEqual(kinds(self.store.read_version(book, version)["caveats"]), expected, label)
            self.store.verify_payload(book, version, "original")  # the book is still filed, unchanged

    def test_names_that_only_start_like_a_finding_are_not_findings(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(b"<< /JSON 1 /Encryption 2 /Launcher 3 /EmbeddedFileX 4 >>"))
        self.assertEqual(result["caveats"], [])

    def test_a_compression_bomb_is_cut_off_quickly_and_reported_as_incomplete(self):
        self.approve_scan()
        started = time.monotonic()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(flate(b"\0" * 60_000_000)))
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result["status"], "done")
        self.assertIn("scan_incomplete", kinds(result["caveats"]))

    def test_a_file_made_of_stream_markers_with_no_end_is_scanned_in_linear_time(self):
        self.approve_scan()
        started = time.monotonic()
        book, version, result = self.scan_bytes("paper.pdf", pdf(b"stream\n" * 300_000 + b"<< /S /Launch >>"))
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(result["status"], "done", result)
        self.assertIn("launch_action", kinds(result["caveats"]))

    def test_markers_that_alternate_with_ends_are_scanned_in_linear_time_too(self):
        self.approve_scan()
        started = time.monotonic()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(b"endstream stream\n" * 150_000))
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(result["status"], "done", result)

    def test_ordinary_modern_pdf_structures_are_not_reported_as_incomplete(self):
        """Cross-reference streams and images use prediction filters; flagging them would flag nearly every paper."""
        self.approve_scan()
        cases = {
            "a cross-reference stream with a predictor": pdf(b"5 0 obj\n<< /Type /XRef /Filter /FlateDecode /W [1 3 1] "
                                                             b"/DecodeParms << /Columns 5 /Predictor 12 >> >>\nstream\n"
                                                             + zlib.compress(b"x" * 50) + b"\nendstream"),
            "an image with a PNG predictor": pdf(b"6 0 obj\n<< /Type /XObject /Subtype /Image /Filter /FlateDecode "
                                                 b"/DecodeParms << /Predictor 15 /Colors 3 >> >>\nstream\n"
                                                 + zlib.compress(b"y" * 80) + b"\nendstream"),
            "an object stream": pdf(b"7 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n"
                                    + zlib.compress(b"8 0 << /A 1 >>") + b"\nendstream"),
        }
        for label, data in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", data)
            self.assertEqual(result["caveats"], [], label)

    def test_a_prediction_filter_anywhere_else_still_counts_as_unreadable(self):
        self.approve_scan()
        data = pdf(b"8 0 obj\n<< /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 3 >> >>\nstream\n"
                   + zlib.compress(b"text") + b"\nendstream")
        _b, _v, result = self.scan_bytes("paper.pdf", data)
        self.assertIn("scan_incomplete", kinds(result["caveats"]))

    def test_the_older_text_encodings_are_decoded_and_read_instead_of_given_up_on(self):
        import base64
        import binascii
        self.approve_scan()
        body = zlib.compress(b"<< /S /JavaScript /JS (x) >>")
        cases = {
            "ascii85 then deflate": (b"[/ASCII85Decode /FlateDecode]", base64.a85encode(body) + b"~>"),
            "hex then deflate": (b"[/ASCIIHexDecode /FlateDecode]", binascii.hexlify(body) + b">"),
            "deflate twice": (b"[/FlateDecode /FlateDecode]", zlib.compress(body)),
        }
        for label, (filters, data) in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(b"9 0 obj\n<< /Filter " + filters + b" >>\nstream\n" + data + b"\nendstream"))
            self.assertIn("javascript", kinds(result["caveats"]), label)
            self.assertNotIn("scan_incomplete", kinds(result["caveats"]), label)

    def test_streams_the_scan_cannot_read_are_reported_as_incomplete_not_passed_silently(self):
        self.approve_scan()
        cases = {
            "ascii85 that is not ascii85": pdf(b"<< /Filter /ASCII85Decode >>\nstream\n" + b"zzzz{{{{}}}}" + b"\nendstream"),
            "hex that is not hex": pdf(b"<< /Filter [/ASCIIHexDecode /FlateDecode] >>\nstream\nXYZ41424344>\nendstream"),
            "run-length coding": pdf(b"<< /Filter /RunLengthDecode >>\nstream\nxxxx\nendstream"),
            "a crypt filter": pdf(b"<< /Filter /Crypt >>\nstream\nxxxx\nendstream"),
            "a made-up filter": pdf(b"<< /Filter /SomethingNew >>\nstream\nxxxx\nendstream"),
            "lzw": pdf(b"<< /Filter /LZWDecode >>\nstream\nxxxx\nendstream"),
            "a flate stream that is not flate": pdf(b"<< /Filter /FlateDecode >>\nstream\nthis is not deflate data\nendstream"),
            "a flate stream cut short": pdf(b"<< /Filter /FlateDecode >>\nstream\n"
                                            + zlib.compress(b"hello world" * 500)[:30] + b"\nendstream"),
        }
        for label, data in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", data)
            self.assertIn("scan_incomplete", kinds(result["caveats"]), label)

    def test_a_script_in_a_compressed_stream_is_not_hidden_by_the_shape_of_the_stream_dictionary(self):
        """Each of these once returned no caveat at all, not even an incomplete one."""
        self.approve_scan()
        script = b"<< /S /JavaScript /JS (app.alert(1)) >>"
        body = zlib.compress(script)
        cases = {
            "a dictionary longer than the old window": pdf(b"1 0 obj\n<< /Filter /FlateDecode /Pad (" + b"x" * 5000 + b") >>\nstream\n" + body + b"\nendstream"),
            "the text obj after the filter": pdf(b"1 0 obj\n<< /Filter /FlateDecode /Note (obj obj) >>\nstream\n" + body + b"\nendstream"),
            "double compression": pdf(b"1 0 obj\n<< /Filter [/FlateDecode /FlateDecode] >>\nstream\n" + zlib.compress(body) + b"\nendstream"),
            "a prediction filter": pdf(b"1 0 obj\n<< /Filter /FlateDecode /DecodeParms << /Predictor 10 /Columns 1 >> >>\nstream\n" + body + b"\nendstream"),
            "a space before the line end": pdf(b"1 0 obj\n<< /Filter /FlateDecode >>\nstream \n" + body + b"\nendstream"),
            "a lone carriage return": pdf(b"1 0 obj\n<< /Filter /FlateDecode >>\nstream\r" + body + b"\nendstream"),
            "a nested dictionary first": pdf(b"1 0 obj\n<< /DecodeParms << /Columns 1 >> /Filter /FlateDecode >>\nstream\n" + body + b"\nendstream"),
            "no end to the stream at all": pdf(b"1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + body),
            "the filter written with escapes": pdf(b"1 0 obj\n<< /Filter /Fl#61teDecode >>\nstream\n" + body + b"\nendstream"),
        }
        for label, data in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", data)
            found = kinds(result["caveats"])
            self.assertTrue(found, f"{label}: no caveat at all")
            self.assertTrue("javascript" in found or "scan_incomplete" in found, f"{label}: {found}")
        # the ones a viewer reads plainly should still be read, not only flagged as unreadable
        for label in ("a dictionary longer than the old window", "the text obj after the filter", "a space before the line end",
                      "a lone carriage return", "a nested dictionary first", "the filter written with escapes"):
            _b, _v, result = self.scan_bytes("paper.pdf", cases[label])
            self.assertIn("javascript", kinds(result["caveats"]), label)

    def test_decoy_stream_markers_cannot_swallow_a_real_stream_unnoticed(self):
        """A string that looks like a stream opener, put before a real stream, once made the scan read the real stream as
        part of the decoy's data; a second decoy then made the filter count come out even."""
        self.approve_scan()
        script = zlib.compress(b"<< /S /JavaScript /JS (x) >>")
        decoy_one = b"1 0 obj (<< /X << /Filter /DCTDecode >> stream\nq\nendstream >> stream\nq\nendstream) endobj\n"
        decoy_two = b"2 0 obj (<< >> stream\n) endobj\n"
        real = b"3 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n" + script + b"\nendstream\nendobj\n"
        for label, body in {"both decoys": decoy_one + decoy_two + real, "the second decoy alone": decoy_two + real,
                            "a decoy inside the dictionary": b"4 0 obj\n<< /Note (<<) /Filter /FlateDecode >>\nstream\n" + script + b"\nendstream\nendobj\n"}.items():
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
            found = kinds(result["caveats"])
            self.assertTrue("javascript" in found or "scan_incomplete" in found, f"{label}: {found}")

    def test_a_real_stream_behind_a_decoy_is_still_found_when_its_filter_key_is_written_with_escapes(self):
        self.approve_scan()
        script = zlib.compress(b"<< /S /JavaScript /JS (x) >>")
        decoy = b"2 0 obj (<< >> stream\n) endobj\n"
        for key in (b"/Fil#74er", b"/F#69lter", b"/Filte#72", b"/#46#69#6c#74#65#72"):
            real = b"3 0 obj\n<< /Type /ObjStm " + key + b" /FlateDecode >>\nstream\n" + script + b"\nendstream\nendobj\n"
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(decoy + real))
            found = kinds(result["caveats"])
            self.assertTrue("javascript" in found or "scan_incomplete" in found, f"{key!r}: {found}")

    def test_many_markers_each_with_a_long_run_of_brackets_before_it_cost_the_scan_little(self):
        """Without a budget on the look-back this takes minutes: every marker looks back over the same long run."""
        self.approve_scan()
        started = time.monotonic()
        data = pdf(b">>" * 8192 + b">>stream\nx\nendstream\n" * 100_000)
        _b, _v, result = self.scan_bytes("paper.pdf", data)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(result["status"], "done", result)
        self.assertIn("scan_incomplete", kinds(result["caveats"]))

    def test_a_filter_or_its_parameters_written_as_a_reference_cannot_hide_a_predictor(self):
        self.approve_scan()
        # with PNG predictor 10 and one column, every byte of the real content is preceded by a row tag, so the script's
        # names are never contiguous once the stream is inflated, and the dictionary says nothing about it
        predicted = b"".join(b"\x00" + bytes([c]) for c in b"<< /S /JavaScript /JS (x) >>")
        body = zlib.compress(predicted)
        definition = b"9 0 obj\n<< /Predictor 10 /Columns 1 >>\nendobj\n"
        for label, parms in {"an indirect reference": b"/DecodeParms 9 0 R", "a reference in an array": b"/DecodeParms [9 0 R]",
                             "the short name": b"/DP 9 0 R", "a reference as the predictor": b"/DecodeParms << /Predictor 9 0 R >>"}.items():
            data = pdf(definition + b"5 0 obj\n<< /Type /ObjStm /Filter /FlateDecode " + parms + b" >>\nstream\n" + body + b"\nendstream\nendobj\n")
            _b, _v, result = self.scan_bytes("paper.pdf", data)
            self.assertIn("scan_incomplete", kinds(result["caveats"]), f"{label}: the script was passed over in silence")

    def test_a_run_of_dictionary_ends_before_many_markers_is_scanned_in_reasonable_time(self):
        self.approve_scan()
        started = time.monotonic()
        data = pdf(b">>" * 8192 + b">> stream\nx\nendstream\n" * 4000)  # a 100 KB file that once cost the scan 13 seconds
        _b, _v, result = self.scan_bytes("paper.pdf", data)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["status"], "done", result)

    def test_a_filter_the_scan_did_not_tie_to_a_stream_it_read_is_reported_as_incomplete(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(b"<< /Filter /FlateDecode >> streamX binary data"))
        self.assertIn("scan_incomplete", kinds(result["caveats"]))

    def test_actions_that_leave_the_file_or_carry_code_are_reported(self):
        self.approve_scan()
        cases = {"external_actions": [b"<< /S /SubmitForm /F (http://x) >>", b"<< /S /GoToR /F (other.pdf) >>",
                                       b"<< /S /ImportData /F (x) >>", b"<< /S /GoToE /F (x) >>"],
                 "rich_media": [b"<< /Subtype /RichMedia >>"]}
        for kind, bodies in cases.items():
            for body in bodies:
                _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
                self.assertIn(kind, kinds(result["caveats"]), body)

    def test_image_streams_are_not_a_reason_to_call_the_scan_incomplete(self):
        self.approve_scan()
        jpeg = pdf(b"<< /Type /XObject /Subtype /Image /Filter /DCTDecode >>\nstream\n\xff\xd8\xff\xe0 binary \xff\xd9\nendstream")
        _b, _v, result = self.scan_bytes("paper.pdf", jpeg)
        self.assertEqual(result["caveats"], [])

    def test_a_good_flate_stream_is_not_incomplete(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(flate(b"hello world " * 100)))
        self.assertEqual(result["caveats"], [])

    def test_pathological_markup_is_scanned_in_reasonable_time(self):
        self.approve_scan()
        cases = {
            "comments": b"<!--" * 700_000,
            "unterminated cdata": b"<![CDATA[" * 300_000,
            "attributes": b"<a " + b"b=1 " * 700_000,
            "end tags": b"</div>" * 500_000,
            "unclosed scripts": b"<script>" * 300_000,
            "angle brackets": b"<" * 2_000_000,
            "deep open tags": b"<b>" * 600_000,
        }
        for label, data in cases.items():
            started = time.monotonic()
            _b, _v, result = self.scan_bytes("page.html", data)
            self.assertLess(time.monotonic() - started, 30, label)
            self.assertEqual(result["status"], "done", f"{label}: {result}")

    def test_a_pdf_with_thousands_of_streams_is_cut_off_and_reported_as_incomplete(self):
        self.approve_scan()
        body = b"".join(b"<< /Filter /FlateDecode >>\nstream\n" + zlib.compress(b"x") + b"\nendstream\n" for _ in range(2500))
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
        self.assertEqual(result["status"], "done")
        self.assertIn("scan_incomplete", kinds(result["caveats"]))


class HtmlScanTest(ScanCase):
    def test_a_clean_page_has_no_caveats(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("page.html", b"<html><body><h1>Hello</h1><p>text</p></body></html>")
        self.assertEqual(result, {"status": "done", "caveats": []})

    def test_scripts_handlers_javascript_addresses_refresh_and_frames_are_counted(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("page.html", SCRIPT_HTML)
        self.assertEqual(kinds(result["caveats"]), {"script_elements": 2, "event_handlers": 1, "javascript_urls": 1,
                                                    "meta_refresh": 1, "embedded_content": 1})

    def test_other_script_schemes_and_comments_inside_a_style_are_seen(self):
        self.approve_scan()
        page = (b'<a href="vbscript:run()">a</a><a href=" data:text/html,<b>x</b>">b</a><a href="JAVA\nSCRIPT:x">c</a>'
                b'<div style="display/**/:none">hidden words</div><div style="DISPLAY : NONE">more hidden</div>')
        _b, _v, result = self.scan_bytes("page.html", page)
        found = kinds(result["caveats"])
        self.assertEqual(found.get("javascript_urls"), 3)
        self.assertEqual(found.get("hidden_text"), len("hiddenwords") + len("morehidden"))

    def test_a_page_larger_than_the_scan_reads_is_reported_as_incomplete_and_the_scan_stays_fast(self):
        self.approve_scan()
        started = time.monotonic()
        _b, _v, result = self.scan_bytes("page.html", b"<p>x</p>" * 7_500_000)  # 60 MB: parsing all of it takes about 30 s
        self.assertLess(time.monotonic() - started, 12)  # reading only the first 10 MB takes about 5
        self.assertEqual(result["status"], "done", result)
        self.assertIn("scan_incomplete", kinds(result["caveats"]))

    def test_hidden_text_is_counted_by_its_characters(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("page.html", HIDDEN_HTML)
        self.assertEqual(kinds(result["caveats"]), {"hidden_text": 11 + 5 + 2})

    def test_text_after_a_hidden_element_closes_is_visible_again(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("page.html", b"<div hidden><p>aa</p><p>bb</p></div><p>after it</p>")
        self.assertEqual(kinds(result["caveats"]), {"hidden_text": 4})

    def test_a_caveat_never_carries_text_from_the_page(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("page.html", SCRIPT_HTML)
        shown = json.dumps(result)
        for text in ("EVIL", "INSTRUCTION", "alert", "calc"):
            self.assertNotIn(text, shown)
        self.assertEqual({c["detail"] for c in result["caveats"]} - set(scan.KINDS.values()), set())

    def test_hostile_markup_is_scanned_without_trouble(self):
        self.approve_scan()
        hostile = (b"<div>" * 100_000 + b"x" + b"\x00\x00<!-- never closed <script>" + b"<p a=" + b'"' + b"y" * 500_000)
        started = time.monotonic()
        _b, _v, result = self.scan_bytes("page.html", hostile)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(result["status"], "done")

    def test_a_page_captured_from_a_server_is_scanned_in_the_same_way(self):
        self.approve_scan()
        site = Site()
        self.addCleanup(site.stop)
        site.add("/page", body=SCRIPT_HTML)
        captured = capture_url.capture(self.store, identity.Identity(self.index), site.url("/page"), allow_private=True)
        result = scan.scan_version(self.store, captured["book_id"], captured["version_id"])
        self.assertEqual(result["status"], "done")
        self.assertEqual(kinds(result["caveats"])["script_elements"], 2)
        self.assertEqual(stages.read(self.store, captured["book_id"], captured["version_id"])["stages"]["fetched"]["status"], "done")


class ScanStageTest(ScanCase):
    def test_a_tool_that_is_not_approved_fails_the_stage_and_leaves_the_book_filed(self):
        book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "failed")
        self.assertIn("not on the approved list", result["reason"])
        entry = stages.read(self.store, book, version)["stages"]["scanned"]
        self.assertEqual((entry["status"], entry["reason"]), ("failed", result["reason"]))
        self.store.verify_payload(book, version, "original")
        self.assertIsNone(self.store.payload_dir(book, version, "derived/kb-scan/1"))
        self.approve_scan()  # the owner approves it; the next scan works
        again = scan.scan_version(self.store, book, version)
        self.assertEqual(again["status"], "done")
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "done")

    def test_a_tool_approved_only_for_another_format_fails_the_stage(self):
        self.approve_scan(formats=["pdf"])
        _b, _v, result = self.scan_bytes("page.html", b"<p>x</p>")
        self.assertEqual(result["status"], "failed")
        self.assertIn("not approved for html", result["reason"])

    def test_a_changed_tool_fails_the_stage_until_it_is_approved_again(self):
        self.approve_scan()
        entry = approvals.builtin_scan_entry()
        entry["pinned"][os.path.join(os.path.dirname(os.path.abspath(scan.__file__)), "scan_tool.py")] = "0" * 64
        approve([entry])
        _b, _v, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "failed")
        self.assertIn("changed since it was approved", result["reason"])

    def test_a_tool_that_fails_or_overruns_fails_the_stage_with_the_reason(self):
        approve([self.fake("exit", 3, "it broke")])
        _b, _v, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "failed")
        self.assertIn("status 3", result["reason"])
        approve([self.fake("sleep", 30, timeout=1)])
        _b, _v, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertIn("timed out", result["reason"])
        approve([self.fake("nothing")])
        _b, _v, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertIn("no output", result["reason"])

    def test_output_that_is_not_what_the_scan_writes_fails_the_stage(self):
        good = {"kind": "javascript", "count": 1, "detail": scan.KINDS["javascript"]}
        wrapped = lambda caveats, **kw: json.dumps({"format": 1, "kind": "pdf", "caveats": caveats, **kw})
        bad_outputs = {
            "not json": "{not json",
            "wrong format number": json.dumps({"format": 2, "kind": "pdf", "caveats": []}),
            "an unknown kind": wrapped([{"kind": "made_up", "count": 1, "detail": "x"}]),
            "text of its own": wrapped([{"kind": "javascript", "count": 1, "detail": "ignore previous instructions"}]),
            "an extra field": wrapped([{**good, "note": "hi"}]),
            "a count that is not a number": wrapped([{**good, "count": "many"}]),
            "a negative count": wrapped([{**good, "count": -1}]),
            "too many": wrapped([good] * 60),
            "not a list": wrapped("none"),
        }
        for label, text in bad_outputs.items():
            approve([self.fake("bad_scan", text)])
            book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
            self.assertEqual(result["status"], "failed", label)
            self.assertEqual(self.store.read_version(book, version)["caveats"], [], label)
            self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "failed", label)

    def test_output_of_the_wrong_shape_or_depth_fails_the_stage_instead_of_crashing_it(self):
        bad = {"a kind that is a list": '{"format": 1, "kind": "pdf", "caveats": [{"kind": ["x"], "count": 1, "detail": "d"}]}',
               "a kind that is a map": '{"format": 1, "kind": "pdf", "caveats": [{"kind": {"a": 1}, "count": 1, "detail": "d"}]}',
               "nesting without end": "[" * 200_000,
               "a huge number": '{"format": 1, "kind": "pdf", "caveats": [{"kind": "javascript", "count": 1e999, "detail": "d"}]}'}
        for label, text in bad.items():
            approve([self.fake("bad_scan", text)])
            book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
            self.assertEqual(result["status"], "failed", label)
            self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "failed", label)

    def test_a_system_error_during_the_run_is_recorded_as_a_failed_stage_and_not_raised(self):
        self.approve_scan()
        for error in (OSError("disk full"), ValueError("odd value")):
            book, version = self.file_original("paper.pdf", CLEAN_PDF)
            with mock.patch.object(scan.convert_run, "run_to_payload", side_effect=error):
                result = scan.scan_version(self.store, book, version)
            self.assertEqual(result["status"], "failed", repr(error))
            self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "failed")

    def test_a_sandbox_that_cannot_be_started_fails_the_stage_with_the_reason(self):
        self.approve_scan()
        with mock.patch.object(convert_run, "SANDBOX", "/nonexistent/sandbox-exec"):
            book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "failed")
        self.assertIn("could not be started", result["reason"])

    def test_the_built_in_scan_tool_starts_without_the_site_module_so_nothing_in_the_runtime_folder_runs_at_startup(self):
        entry = approvals.builtin_scan_entry()
        self.assertEqual(entry["command"][1:3], ["-I", "-S"])

    def test_after_unusable_output_the_next_scan_is_a_new_generation_beside_it(self):
        approve([self.fake("bad_scan", "{not json")])
        book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "failed")
        bad = self.store.payload_dir(book, version, "derived/kb-scan/1")
        self.assertIsNotNone(bad)
        self.approve_scan()
        again = scan.scan_version(self.store, book, version)
        self.assertEqual(again["status"], "done")
        self.store.verify_payload(book, version, "derived/kb-scan/2")
        self.store.verify_payload(book, version, "derived/kb-scan/1")  # the unusable one is untouched

    def test_a_file_of_a_kind_with_no_scanner_is_skipped_and_not_scanned_again(self):
        self.approve_scan()
        book, version, result = self.scan_bytes("notes.txt", b"hello")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "skipped")
        with mock.patch.object(convert_run, "run", side_effect=AssertionError("ran again")):
            self.assertEqual(scan.scan_version(self.store, book, version)["status"], "skipped")

    def test_a_version_that_was_not_fetched_cannot_be_scanned_yet(self):
        self.approve_scan()
        book, version = self.file_original("paper.pdf", CLEAN_PDF, fetched=False)
        with self.assertRaises(KbError) as cm:
            scan.scan_version(self.store, book, version)
        self.assertIn("not been fetched", str(cm.exception))

    def test_a_scan_that_is_done_is_not_run_again(self):
        self.approve_scan()
        book, version, first = self.scan_bytes("paper.pdf", pdf(b"<< /S /Launch >>"))
        with mock.patch.object(convert_run, "run", side_effect=AssertionError("ran again")):
            again = scan.scan_version(self.store, book, version)
        self.assertEqual(kinds(again["caveats"]), kinds(first["caveats"]))

    def test_a_stop_after_the_output_is_filed_is_resumed_without_running_the_tool_again(self):
        self.approve_scan()
        book, version = self.file_original("paper.pdf", pdf(b"<< /S /Launch >>"))
        with mock.patch.object(scan.stages, "mark", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                scan.scan_version(self.store, book, version)
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "pending")
        self.assertIsNotNone(self.store.payload_dir(book, version, "derived/kb-scan/1"))
        with mock.patch.object(convert_run, "run", side_effect=AssertionError("ran again")):
            result = scan.scan_version(self.store, book, version)
        self.assertEqual(kinds(result["caveats"]), {"launch_action": 1})
        self.assertEqual(kinds(self.store.read_version(book, version)["caveats"]), {"launch_action": 1})
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["status"], "done")
        self.assertEqual(self.store.read_version(book, version)["payloads"]["derived/kb-scan/1"]["tool"], scan.TOOL_LABEL)

    def test_the_scan_never_changes_the_original(self):
        self.approve_scan()
        book, version = self.file_original("page.html", SCRIPT_HTML)
        before = self.store.verify_payload(book, version, "original")
        scan.scan_version(self.store, book, version)
        self.assertEqual(self.store.verify_payload(book, version, "original"), before)

    def test_a_version_with_no_primary_file_is_skipped_not_left_pending(self):
        self.approve_scan()
        book = self.store.create_book(title="t", kind="web page")
        version = self.store.add_version(book)
        self.store.set_version_label(book, version, "v1")
        stages.mark(self.store, book, version, "fetched", "done")
        # no original was filed, and the version names no primary file
        result = scan.scan_version(self.store, book, version)
        self.assertEqual(result["status"], "skipped")


class DescribeToolTest(ScanCase):
    def test_the_built_in_entry_pins_the_program_and_the_script_and_reads_only_the_runtime(self):
        entry = approvals.builtin_scan_entry()
        script = os.path.join(os.path.dirname(os.path.abspath(scan.__file__)), "scan_tool.py")
        self.assertEqual((entry["name"], entry["version"]), (scan.TOOL_NAME, scan.TOOL_VERSION))
        self.assertEqual(set(entry["pinned"]), {entry["executable"], script})
        self.assertEqual(entry["reads"], [self.prefix])
        self.assertEqual(entry["command"][:2], [entry["executable"], "-I"])
        approvals.validate_entry(entry)


class CommandLineTest(ScanCase):
    def run_kb(self, *args):
        import subprocess
        import sys
        from engine.tests import ENGINE_DIR
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR,
                              env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=60)

    def test_describe_tool_prints_the_entry_and_changes_nothing(self):
        with open(os.path.join(self.cfg, "config.json")) as f:
            before = f.read()
        done = self.run_kb("describe-tool")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), approvals.builtin_scan_entry())
        with open(os.path.join(self.cfg, "config.json")) as f:
            self.assertEqual(f.read(), before)

    def test_the_printed_entry_can_be_pasted_into_the_config_and_then_runs(self):
        approve([json.loads(self.run_kb("describe-tool").stdout)])
        _b, _v, result = self.scan_bytes("page.html", SCRIPT_HTML)
        self.assertEqual(result["status"], "done")

    def test_tools_lists_what_is_approved_and_whether_it_still_matches(self):
        done = self.run_kb("tools")
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, []))
        self.approve_scan()
        done = self.run_kb("tools")
        rows = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual([(r["name"], r["version"], r["status"]) for r in rows], [(scan.TOOL_NAME, scan.TOOL_VERSION, "ok")])
        entry = approvals.builtin_scan_entry()
        entry["pinned"][entry["executable"]] = "0" * 64
        approve([entry])
        done = self.run_kb("tools")
        self.assertEqual(done.returncode, 1)
        self.assertIn("changed since it was approved", json.loads(done.stdout)[0]["status"])


if __name__ == "__main__":
    unittest.main()
