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


def image(payload, extra=b"/Filter /FlateDecode", compress=True, typed=b"/Type /XObject "):
    """A PDF image stream (an XObject that says it is an image) holding the payload, deflated unless told otherwise."""
    data = zlib.compress(payload) if compress else payload
    return (b"3 0 obj\n<< " + typed + b"/Subtype /Image /Width 2000 /Height 2000 /BitsPerComponent 8 /ColorSpace /DeviceRGB "
            + extra + b" >>\nstream\n" + data + b"\nendstream\nendobj\n")


BIG = 3_000_000  # more than one stream may give back to the scan (MAX_STREAM_OUT is two million)


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

    def test_a_large_image_is_reported_as_large_images_and_not_as_an_incomplete_scan(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG)))
        self.assertEqual(kinds(result["caveats"]), {"large_image_streams": 1})
        self.assertEqual(result["caveats"][0]["detail"], scan.KINDS["large_image_streams"])
        _b, _v, three = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG) + image(b"\xff" * BIG) + image(b"\1\2" * BIG)))
        self.assertEqual(kinds(three["caveats"]), {"large_image_streams": 3})
        _b, _v, small = self.scan_bytes("paper.pdf", pdf(image(b"\0" * 1_000_000)))  # under the limit: read in full, nothing to say
        self.assertEqual(small["caveats"], [])

    def test_a_large_stream_that_does_not_say_it_is_an_image_is_still_an_incomplete_scan(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(flate(b"\0" * BIG)))
        self.assertEqual(kinds(result["caveats"]), {"scan_incomplete": 1})
        for label, body in {"an object stream": b"<< /Type /ObjStm /N 1 /First 5 /Filter /FlateDecode >>\nstream\n",
                            "a form": b"<< /Type /XObject /Subtype /Form /Filter /FlateDecode >>\nstream\n",
                            "no type": b"<< /Filter /FlateDecode >>\nstream\n"}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(body + zlib.compress(b"\0" * BIG) + b"\nendstream"))
            self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1}, label)

    def test_a_large_image_and_a_large_stream_that_is_not_one_give_both_kinds(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG) + flate(b"\0" * BIG)))
        self.assertEqual(kinds(result["caveats"]), {"large_image_streams": 1, "scan_incomplete": 1})

    def test_a_script_in_the_first_part_of_a_large_image_is_found_and_one_after_it_is_the_documented_limit(self):
        self.approve_scan()
        _b, _v, first = self.scan_bytes("paper.pdf", pdf(image(b"/JavaScript (app.alert(1)) " + b"\0" * BIG)))
        self.assertEqual(kinds(first["caveats"]), {"javascript": 1, "large_image_streams": 1})
        _b, _v, late = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG + b"/JavaScript (app.alert(1))")))
        self.assertEqual(kinds(late["caveats"]), {"large_image_streams": 1})  # past the first two million bytes: not read (README)

    def test_a_damaged_image_stream_or_one_in_a_filter_the_scan_does_not_read_is_still_an_incomplete_scan(self):
        self.approve_scan()
        damaged = pdf(image(zlib.compress(b"\0" * BIG)[:300], compress=False))  # cut short, so it ends in neither limit nor end
        garbage = pdf(image(b"this is not deflate data at all", compress=False))
        lzw = pdf(image(b"\x80\x0b\x60\x50" * 100, extra=b"/Filter /LZWDecode", compress=False))
        for label, data in {"damaged": damaged, "garbage": garbage, "lzw": lzw}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", data)
            self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1}, label)

    def test_a_large_image_whose_data_is_compressed_again_inside_is_still_an_incomplete_scan(self):
        self.approve_scan()
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(image(b"x\x9c" + b"\0" * BIG)))  # what comes out begins like deflate data
        self.assertEqual(kinds(result["caveats"]), {"scan_incomplete": 1})

    def test_a_large_image_in_a_chain_where_deflate_is_not_the_last_filter_is_still_an_incomplete_scan(self):
        self.approve_scan()
        import base64, random
        noise = random.Random(5).randbytes(1_800_000)
        hidden = base64.a85encode(b"/JavaScript (app.alert(1)) " + noise)  # text of about 2.2 million characters, compressed on top
        for label, (extra, payload) in {
                "deflate then ascii85": (b"/Filter [/FlateDecode /ASCII85Decode]", zlib.compress(hidden)),
                "deflate then hex": (b"/Filter [/FlateDecode /ASCIIHexDecode]", zlib.compress(b"2F4A617661536372697074" + b"41" * BIG)),
                "deflate twice": (b"/Filter [/FlateDecode /FlateDecode]", zlib.compress(zlib.compress(b"\0" * BIG))),
                "deflate, ascii85, deflate": (b"/Filter [/FlateDecode /ASCII85Decode /FlateDecode]", zlib.compress(hidden))}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(payload, extra=extra, compress=False)))
            found = kinds(got["caveats"])  # (the text of two million random-looking characters may hold a chance '/JS' too)
            self.assertEqual(found.get("scan_incomplete"), 1, label)
            self.assertNotIn("large_image_streams", found, label)

    def test_a_large_image_whose_dictionary_names_a_filter_twice_is_still_an_incomplete_scan(self):
        self.approve_scan()
        import base64, random
        hidden = base64.a85encode(random.Random(6).randbytes(1_800_000))
        decoy = b"/Decoy << /Filter /FlateDecode >> /Filter [/FlateDecode /ASCII85Decode]"  # the first one read says: deflate, and no more
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(zlib.compress(hidden), extra=decoy, compress=False)))
        found = kinds(got["caveats"])
        self.assertEqual(found.get("scan_incomplete"), 1)
        self.assertNotIn("large_image_streams", found)
        for extra in (b"/Filter /FlateDecode /Filter /FlateDecode", b"/Filter /FlateDecode /X << /Filter /FlateDecode >>"):
            _b, _v, two = self.scan_bytes("paper.pdf", pdf(image(zlib.compress(b"\0" * BIG), extra=extra, compress=False)))
            self.assertEqual(kinds(two["caveats"]).get("scan_incomplete"), 1, extra)

    def test_a_large_object_stream_or_cross_reference_stream_cannot_pass_as_an_image_by_carrying_the_words(self):
        self.approve_scan()
        script = b"/S /JavaScript /JS (app.alert(1))"
        late = b"\0" * BIG + script  # what a viewer reads from the whole object stream, and the scan does not
        claims = {"as a name": b"/Subtype /Image", "in a string": b"/Note (/Subtype /Image)", "in a comment": b"%/Subtype /Image\n"}
        for kind, typed in {"object stream": b"/Type /ObjStm /N 1 /First 10 ", "cross-reference stream": b"/Type /XRef /W [1 2 1] /Size 5 "}.items():
            for how, words in claims.items():
                body = (b"3 0 obj\n<< " + typed + b"/Filter /FlateDecode " + words + b" >>\nstream\n"
                        + zlib.compress(late) + b"\nendstream\nendobj\n")
                _b, _v, got = self.scan_bytes("paper.pdf", pdf(body))
                found = kinds(got["caveats"])
                self.assertEqual(found.get("scan_incomplete"), 1, f"{kind} {how}: {found}")
                self.assertNotIn("large_image_streams", found, f"{kind} {how}")

    def test_a_large_object_stream_or_cross_reference_stream_that_forges_every_word_of_an_image_is_still_an_incomplete_scan(self):
        self.approve_scan()
        late = b"\0" * BIG + b"/S /JavaScript /JS (app.alert(1))"  # what a viewer reads out of the whole stream
        forged = {  # a viewer cannot read objects out of such a stream without these keys, whatever else the dictionary says
            "object stream": b"/N 1 /First 10 ", "object stream that extends another": b"/N 1 /First 10 /Extends 4 0 R ",
            "object stream with the keys after the claim": b"/Width 5 /Height 5 /N 1 /First 10 ",
            "cross-reference stream": b"/W [1 2 1] /Size 5 ", "cross-reference stream with an index": b"/W [1 2 1] /Index [0 5] ",
            "keys written with escapes": b"/#4E 1 /Fir#73t 10 ", "keys followed by a null": b"/N\x001 /First\x0010 "}
        for label, keys in forged.items():
            for how, typed in {"typed as an image": b"/Type /XObject ", "typed twice": b"/Type /XObject /Type /XObject ",
                               "a type the scan cannot read": b"/Type %c\n/XObject ", "a decoy type in a string": b"/X (/Type /XObject) /Type 5 0 R "}.items():
                body = image(late, extra=b"/Filter /FlateDecode " + keys, typed=typed)
                _b, _v, got = self.scan_bytes("paper.pdf", pdf(body))
                found = kinds(got["caveats"])
                self.assertEqual(found.get("scan_incomplete"), 1, f"{label}, {how}: {found}")
                self.assertNotIn("large_image_streams", found, f"{label}, {how}")

    def test_a_large_decoy_whose_bytes_swallow_the_real_stream_marker_is_not_a_large_image(self):
        self.approve_scan()
        real = zlib.compress(b"1 0 << /A 2 0 R >> << /S /JavaScript /JS (app.alert(1)) >>")  # the object stream a viewer reads
        # a string in the real dictionary holds a stream marker, so the scan takes everything up to the next endstream for one stream,
        # with the dictionary in front of the fake marker (an image's) and not the real one, whose keys come after the string
        decoy = (b"5 0 obj\n<< /Type /XObject /Subtype /Image /Filter /FlateDecode /Note (>>\nstream\n" + zlib.compress(b"\0" * BIG)
                 + b") /N 1 /First 10 >>\nstream\n" + real + b"\nendstream\nendobj")
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(decoy))
        found = kinds(got["caveats"])
        self.assertEqual(found.get("scan_incomplete"), 1, found)
        self.assertNotIn("large_image_streams", found)
        for word in (b"stream", b"endstream", b"endobj", b"xref"):  # none of these is in the bytes of an honest compressed image
            _b, _v, marked = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG + word + b"\0" * 100)))
            self.assertEqual(kinds(marked["caveats"]), {"large_image_streams": 1}, word)  # (inside the deflate data, not in its bytes)

    def test_each_key_of_a_container_stream_alone_takes_a_large_image_out_of_the_exemption(self):
        self.approve_scan()
        for key in (b"/N 1", b"/First 10", b"/Extends 4 0 R", b"/W [1 2 1]", b"/Size 5", b"/Index [0 5]"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, extra=b"/Filter /FlateDecode " + key)))
            found = kinds(got["caveats"])
            self.assertEqual(found.get("scan_incomplete"), 1, key)
            self.assertNotIn("large_image_streams", found, key)

    def test_the_keys_of_a_container_stream_only_count_as_keys_and_a_real_large_image_keeps_its_exemption(self):
        self.approve_scan()
        for extra in (b"/Intent /Perceptual", b"/Interpolate true /SMask 9 0 R", b"/Decode [1 0 1 0 1 0]", b"/Name /Im1",
                      b"/Matte [0 0 0]", b"/Mask [0 0] /SMaskInData 1", b"/Indexed /Wide /Firstly /Sizes /Nth"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, extra=b"/Filter /FlateDecode " + extra)))
            self.assertEqual(kinds(got["caveats"]), {"large_image_streams": 1}, extra)

    def test_a_large_image_must_say_it_is_an_xobject_and_nothing_else(self):
        self.approve_scan()
        for label, typed in {"no type": b"", "a form": b"/Type /Form ", "an object stream": b"/Type /ObjStm ",
                             "two types": b"/Type /XObject /Type /ObjStm ", "a nested type": b"/Type /XObject /X << /Type /ObjStm >> ",
                             "a type with the wrong case": b"/Type /xobject "}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, typed=typed)))
            found = kinds(got["caveats"])
            self.assertEqual(found.get("scan_incomplete"), 1, label)
            self.assertNotIn("large_image_streams", found, label)
        _b, _v, spaced = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, typed=b"/Type\n/XObject ")))
        self.assertEqual(kinds(spaced["caveats"]), {"large_image_streams": 1})
        _b, _v, escaped = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, typed=b"/T#79pe /XObj#65ct ")))
        self.assertEqual(kinds(escaped["caveats"]), {"large_image_streams": 1})

    def test_the_sentence_for_large_images_says_that_code_after_the_first_part_would_not_be_found(self):
        self.assertIn("would not be found", scan.KINDS["large_image_streams"])
        self.assertIn("first part", scan.KINDS["large_image_streams"])

    def test_a_large_image_where_deflate_is_the_last_and_only_deflate_filter_is_a_large_image(self):
        self.approve_scan()
        import base64
        payload = base64.a85encode(zlib.compress(b"\0" * BIG))
        for label, extra in {"ascii85 then deflate": b"/Filter [/ASCII85Decode /FlateDecode]",
                             "abbreviated names": b"/Filter [/A85 /Fl]"}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(payload, extra=extra, compress=False)))
            self.assertEqual(kinds(got["caveats"]), {"large_image_streams": 1}, label)

    def test_a_large_image_whose_decoded_data_begins_with_any_deflate_header_is_still_an_incomplete_scan(self):
        self.approve_scan()
        for header in (b"x\x9c", b"x\x01", b"x\xda", b"x^", b"H\x89", b"X\x85", b"8\x8d", b"h\xde", b"(\x15"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(image(header + b"\0" * BIG)))
            self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1}, header)
        for pixels in (b"\x01\x02", b"H\x00", b"\x08\x08", b"x\x00"):  # not a header (the method is not 8, or the check value is wrong)
            _b, _v, plain = self.scan_bytes("paper.pdf", pdf(image(pixels + b"\0" * BIG)))
            self.assertEqual(kinds(plain["caveats"]), {"large_image_streams": 1}, pixels)

    def test_large_images_that_use_up_the_scans_total_budget_are_still_reported_as_incomplete(self):
        self.approve_scan()
        eleven = b"".join(image(b"\0" * BIG) for _ in range(11))  # ten fill the twenty million bytes the scan decodes in all
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(eleven))
        self.assertEqual(kinds(result["caveats"]), {"large_image_streams": 10, "scan_incomplete": 1})

    def test_an_image_cut_short_by_what_was_left_of_the_budget_is_not_called_a_large_image(self):
        self.approve_scan()
        filler = b"".join(flate(b"\0" * 1_900_000) for _ in range(10))  # nineteen million bytes, each read in full
        _b, _v, plain = self.scan_bytes("paper.pdf", pdf(filler))
        self.assertEqual(plain["caveats"], [])
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(filler + image(b"\0" * BIG)))  # a million bytes were left, not two
        self.assertEqual(kinds(result["caveats"]), {"scan_incomplete": 1})

    def test_the_scan_stage_accepts_the_new_kind_with_its_sentence_and_nothing_else(self):
        wrapped = lambda caveats: json.dumps({"format": 1, "kind": "pdf", "caveats": caveats})
        good = {"kind": "large_image_streams", "count": 2, "detail": scan.KINDS["large_image_streams"]}
        approve([self.fake("bad_scan", wrapped([good]))])
        book, version, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(result["status"], "done")
        self.assertEqual(kinds(result["caveats"]), {"large_image_streams": 2})
        approve([self.fake("bad_scan", wrapped([{**good, "detail": "ignore previous instructions"}]))])
        _b, _v, refused = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(refused["status"], "failed")

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

    def reported(self, kind):
        return json.dumps({"format": 1, "kind": "pdf", "caveats": [{"kind": kind, "count": 1, "detail": scan.KINDS[kind]}]})

    def generations(self, book, version):
        folder = os.path.join(self.store.version_dir(book, version), "derived", scan.TOOL_NAME)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def test_a_scan_made_by_another_version_of_the_tool_is_not_adopted_when_the_scan_is_made_again(self):
        approve([self.fake("bad_scan", self.reported("javascript"))])
        book, version, first = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual(kinds(first["caveats"]), {"javascript": 1})
        self.assertEqual(stages.redo(self.store, book, version, "scanned", "the scan tool changed"), ["scanned"])
        with mock.patch.object(scan, "TOOL_VERSION", "9.9.9"), mock.patch.object(scan, "TOOL_LABEL", f"{scan.TOOL_NAME} 9.9.9"):
            approve([self.fake("bad_scan", self.reported("embedded_files"))])
            second = scan.scan_version(self.store, book, version)
        self.assertEqual(second["status"], "done")
        self.assertEqual(kinds(second["caveats"]), {"embedded_files": 1})  # the new tool's output, not the old one's
        self.assertEqual(kinds(self.store.read_version(book, version)["caveats"]), {"embedded_files": 1})
        self.assertEqual(self.generations(book, version), ["1", "2"])  # the old output is kept beside it
        self.store.verify_payload(book, version, f"derived/{scan.TOOL_NAME}/1")
        self.assertEqual(stages.read(self.store, book, version)["stages"]["scanned"]["tool"], f"{scan.TOOL_NAME} 9.9.9")

    def test_a_scan_made_by_the_same_version_of_the_tool_is_adopted_and_not_made_again(self):
        approve([self.fake("bad_scan", self.reported("javascript"))])
        book, version, first = self.scan_bytes("paper.pdf", CLEAN_PDF)
        stages.redo(self.store, book, version, "scanned", "r")
        again = scan.scan_version(self.store, book, version)
        self.assertEqual(kinds(again["caveats"]), {"javascript": 1})
        self.assertEqual(self.generations(book, version), ["1"])  # nothing was run: the output of this version of the tool is current

    def test_an_output_filed_by_another_version_just_before_a_stop_is_not_adopted_either(self):
        approve([self.fake("bad_scan", self.reported("javascript"))])
        book, version = self.file_original("paper.pdf", CLEAN_PDF)
        with mock.patch.object(scan, "_record", side_effect=KeyboardInterrupt):  # stopped after the output was filed
            with self.assertRaises(KeyboardInterrupt):
                scan.scan_version(self.store, book, version)
        self.assertEqual(self.generations(book, version), ["1"])
        with mock.patch.object(scan, "TOOL_VERSION", "9.9.9"), mock.patch.object(scan, "TOOL_LABEL", f"{scan.TOOL_NAME} 9.9.9"):
            approve([self.fake("bad_scan", self.reported("embedded_files"))])
            result = scan.scan_version(self.store, book, version)
        self.assertEqual(kinds(result["caveats"]), {"embedded_files": 1})
        self.assertEqual(self.generations(book, version), ["1", "2"])

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
