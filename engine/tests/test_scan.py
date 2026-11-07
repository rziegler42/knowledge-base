import base64
import json
import os
import random
import time
import unittest
import zlib
from unittest import mock

from engine.tests import bench_pdf
from engine.tests.test_capture_url import Site
from engine.tests.test_convert_run import PROBE, SandboxCase, approve

from kb import KbError, approvals, capture_url, convert_run, identity, scan, scan_tool, stages


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


def png_filter(raw, rowbytes, bpp=1, types=(0, 1, 2, 3, 4)):
    """PNG row filtering, written for the tests and independent of the scan's undoing: each row gets a type byte from `types`
    in turn and its bytes are replaced by their difference from the prediction."""
    out, prev = bytearray(), bytes(rowbytes)
    for n, start in enumerate(range(0, len(raw), rowbytes)):
        row, kind = raw[start:start + rowbytes], types[n % len(types)]
        out.append(kind)
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i] if i < len(prev) else 0
            c = prev[i - bpp] if i >= bpp and i < len(prev) else 0
            if kind == 0:
                guess = 0
            elif kind == 1:
                guess = a
            elif kind == 2:
                guess = b
            elif kind == 3:
                guess = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                guess = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            out.append((x - guess) & 255)
        prev = row
    return bytes(out)


def tiff_filter(raw, rowbytes, colors=1):
    """TIFF predictor 2 at 8 bits: each byte is replaced by its difference from the same colour of the pixel before it."""
    out = bytearray()
    for start in range(0, len(raw), rowbytes):
        row = raw[start:start + rowbytes]
        out += bytes((x - (row[i - colors] if i >= colors else 0)) & 255 for i, x in enumerate(row))
    return bytes(out)


SCRIPT = b"<< /S /JavaScript /JS (app.alert(1)) >> "


def script_rows(columns, rows=3):
    """The text of an action, padded with spaces to whole rows of `columns` bytes."""
    return (SCRIPT * 8).ljust(columns * rows, b" ")[:columns * rows]


def stream_object(dictionary, data, number=5):
    return f"{number} 0 obj\n".encode() + b"<< " + dictionary + b" >>\nstream\n" + data + b"\nendstream\nendobj\n"


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

    def test_a_file_attachment_without_embedded_file_text_is_an_embedded_file(self):
        self.approve_scan()
        cases = {
            "annotation with a file specification": (b"<< /Subtype /FileAttachment /FS << /EF << /F 5 0 R >> >> >>", {"embedded_files": 2}),
            "annotation alone": (b"<< /Subtype /FileAttachment /Contents (x) >>", {"embedded_files": 1}),
            "file specification alone": (b"<< /Type /Filespec /EF << /F 5 0 R >> >>", {"embedded_files": 1}),
            "escaped name": (b"<< /Subtype /File#41ttachment >>", {"embedded_files": 1}),
            "escaped key": (b"<< /Type /Filespec /E#46 5 0 R >>", {"embedded_files": 1}),
            "with the older spelling too": (b"<< /Subtype /FileAttachment >> << /Type /EmbeddedFile >>", {"embedded_files": 2}),
        }
        for label, (body, expected) in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
            self.assertEqual(kinds(result["caveats"]), expected, label)

    def test_the_new_names_follow_the_rule_of_the_binary_places(self):
        self.approve_scan()
        bare = b"\x01\x02\xfe" * 20 + b"/EF" + b"\xfe\x01" * 20 + b"/FileAttachment" + b"\xfe\x02" * 20  # no shape of a use
        shaped = b"some text here, then /EF (x) and /FileAttachment (y) in the data"
        for label, payload, expected in (("bare", bare, {"pattern_in_binary_data": 2}), ("shaped", shaped, {"embedded_files": 2})):
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(image(payload, extra=b"", compress=False)))
            self.assertEqual(kinds(result["caveats"]), expected, label)

    def test_names_that_only_start_like_an_attachment_are_not_findings(self):
        self.approve_scan()
        for body in (b"<< /FileAttachments 1 /FileAttachmen 2 /EFX 3 /Ef 4 /E#20F 5 /EF2 6 /EFF 7 >>", b"<< /E F 5 0 R >>"):
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
            self.assertEqual(result["caveats"], [], body)

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
                                                             + zlib.compress(png_filter(b"\x01\x00\x00\x10\x00" * 10, 5, types=(2,))) + b"\nendstream"),
            "an image with a PNG predictor": pdf(b"6 0 obj\n<< /Type /XObject /Subtype /Image /Filter /FlateDecode "
                                                 b"/DecodeParms << /Predictor 15 /Colors 3 /Columns 10 >> >>\nstream\n"
                                                 + zlib.compress(png_filter(bytes(range(90)) * 3, 30, bpp=3)) + b"\nendstream"),
            "an object stream": pdf(b"7 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n"
                                    + zlib.compress(b"8 0 << /A 1 >>") + b"\nendstream"),
        }
        for label, data in cases.items():
            _b, _v, result = self.scan_bytes("paper.pdf", data)
            self.assertEqual(result["caveats"], [], label)

    def test_a_stream_behind_a_predictor_is_read_wherever_it_is_and_one_whose_predicted_data_is_not_valid_is_incomplete(self):
        self.approve_scan()
        good = pdf(b"8 0 obj\n<< /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 3 >> >>\nstream\n"
                   + zlib.compress(png_filter(b"textabcdef", 3)) + b"\nendstream")
        _b, _v, result = self.scan_bytes("paper.pdf", good)
        self.assertEqual(result["caveats"], [])  # decoded, undone and read: nothing in it
        bad = pdf(b"8 0 obj\n<< /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 3 >> >>\nstream\n"
                  + zlib.compress(b"text") + b"\nendstream")  # 't' is not a row type
        _b, _v, result = self.scan_bytes("paper.pdf", bad)
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
            "ascii85 that is not ascii85": pdf(b"9 0 obj\n<< /Filter /ASCII85Decode >>\nstream\n" + b"zzzz{{{{}}}}" + b"\nendstream\nendobj\n"),
            "hex that is not hex": pdf(b"9 0 obj\n<< /Filter [/ASCIIHexDecode /FlateDecode] >>\nstream\nXYZ41424344>\nendstream\nendobj\n"),
            "run-length coding": pdf(b"9 0 obj\n<< /Filter /RunLengthDecode >>\nstream\nxxxx\nendstream\nendobj\n"),
            "a crypt filter": pdf(b"9 0 obj\n<< /Filter /Crypt >>\nstream\nxxxx\nendstream\nendobj\n"),
            "a made-up filter": pdf(b"9 0 obj\n<< /Filter /SomethingNew >>\nstream\nxxxx\nendstream\nendobj\n"),
            "lzw": pdf(b"9 0 obj\n<< /Filter /LZWDecode >>\nstream\nxxxx\nendstream\nendobj\n"),
            "a flate stream that is not flate": pdf(b"9 0 obj\n<< /Filter /FlateDecode >>\nstream\nthis is not deflate data\nendstream\nendobj\n"),
            "a flate stream cut short": pdf(b"9 0 obj\n<< /Filter /FlateDecode >>\nstream\n"
                                            + zlib.compress(b"hello world" * 500)[:30] + b"\nendstream\nendobj\n"),
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
            self.assertIn("javascript", found, f"{label}: the real stream was not read: {found}")  # read, not only flagged

    def test_a_real_stream_behind_a_decoy_is_still_found_when_its_filter_key_is_written_with_escapes(self):
        self.approve_scan()
        script = zlib.compress(b"<< /S /JavaScript /JS (x) >>")
        decoy = b"2 0 obj (<< >> stream\n) endobj\n"
        for key in (b"/Fil#74er", b"/F#69lter", b"/Filte#72", b"/#46#69#6c#74#65#72"):
            real = b"3 0 obj\n<< /Type /ObjStm " + key + b" /FlateDecode >>\nstream\n" + script + b"\nendstream\nendobj\n"
            _b, _v, result = self.scan_bytes("paper.pdf", pdf(decoy + real))
            found = kinds(result["caveats"])
            self.assertIn("javascript", found, f"{key!r}: the real stream was not read: {found}")

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
        jpeg = pdf(b"3 0 obj\n<< /Type /XObject /Subtype /Image /Filter /DCTDecode >>\nstream\n\xff\xd8\xff\xe0 binary \xff\xd9\nendstream\nendobj\n")
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
        for label, body in {"an object stream": b"9 0 obj\n<< /Type /ObjStm /N 1 /First 5 /Filter /FlateDecode >>\nstream\n",
                            "a form": b"9 0 obj\n<< /Type /XObject /Subtype /Form /Filter /FlateDecode >>\nstream\n",
                            "no type": b"9 0 obj\n<< /Filter /FlateDecode >>\nstream\n"}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(body + zlib.compress(b"\0" * BIG) + b"\nendstream\nendobj\n"))
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
        self.assertGreater(found.get("javascript", 0), 0, found)  # read through its own dictionary, the real stream is found
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

    def test_a_large_image_may_leave_out_its_type_but_one_it_gives_must_be_xobject_and_nothing_else(self):
        self.approve_scan()
        _b, _v, untyped = self.scan_bytes("paper.pdf", pdf(image(b"\0" * BIG, typed=b"")))  # the format makes the type of an image optional
        self.assertEqual(kinds(untyped["caveats"]), {"large_image_streams": 1})
        for label, typed in {"a form": b"/Type /Form ", "an object stream": b"/Type /ObjStm ",
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
        payload = base64.a85encode(zlib.compress(b"\0" * BIG)) + b"~>"  # a conforming stream ends with its end mark
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

    def test_the_scan_stage_accepts_pattern_in_binary_data_with_its_sentence_and_nothing_else(self):
        wrapped = lambda caveats: json.dumps({"format": 1, "kind": "pdf", "caveats": caveats})
        good = {"kind": "pattern_in_binary_data", "count": 24, "detail": scan.KINDS["pattern_in_binary_data"]}
        approve([self.fake("bad_scan", wrapped([good]))])
        _b, _v, result = self.scan_bytes("paper.pdf", CLEAN_PDF)
        self.assertEqual((result["status"], kinds(result["caveats"])), ("done", {"pattern_in_binary_data": 24}))
        self.assertIn("usually a coincidence", scan.KINDS["pattern_in_binary_data"])
        self.assertIn("not read as a viewer would", scan.KINDS["pattern_in_binary_data"])
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

    def test_a_pdf_with_thousands_of_streams_is_read_in_full_and_the_limit_on_their_number_is_in_limitstest(self):
        self.approve_scan()
        body = b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % (10 + k) + zlib.compress(b"x") + b"\nendstream\nendobj\n" for k in range(2500))
        _b, _v, result = self.scan_bytes("paper.pdf", pdf(body))
        self.assertEqual(result["status"], "done")
        self.assertEqual(kinds(result["caveats"]), {})


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


class PredictorUndoTest(unittest.TestCase):
    """The predictors are undone exactly, and what cannot be undone is refused and not guessed at."""

    @property
    def UNREADABLE(self):
        return scan_tool._Unreadable

    def test_each_png_row_filter_is_undone_exactly_for_many_shapes_of_row(self):
        rng = random.Random(3)
        for colors, bpc, columns in [(1, 8, 7), (3, 8, 5), (4, 8, 3), (1, 16, 4), (3, 16, 2), (1, 1, 17), (1, 4, 9), (1, 2, 13), (2, 8, 11)]:
            rowbytes = (colors * bpc * columns + 7) // 8
            bpp = max(1, (colors * bpc + 7) // 8)
            raw = rng.randbytes(rowbytes * 9)
            for types in ((0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4), (4, 3, 2, 1, 0, 4)):
                parms = {"predictor": 15, "colors": colors, "bpc": bpc, "columns": columns}
                self.assertEqual(scan_tool._undo_predictor(png_filter(raw, rowbytes, bpp, types), parms), raw,
                                 (colors, bpc, columns, types))

    def test_the_predictor_numbers_ten_to_fifteen_are_all_read_by_the_type_byte_of_each_row(self):
        raw = random.Random(4).randbytes(60)
        enc = png_filter(raw, 6, 1)
        for number in range(10, 16):
            self.assertEqual(scan_tool._undo_predictor(enc, {"predictor": number, "colors": 1, "bpc": 8, "columns": 6}), raw, number)

    def test_the_tiff_predictor_is_undone_at_eight_bits_for_one_to_four_colours(self):
        rng = random.Random(5)
        for colors in (1, 2, 3, 4):
            columns = 6
            raw = rng.randbytes(colors * columns * 7)
            enc = tiff_filter(raw, colors * columns, colors)
            self.assertEqual(scan_tool._undo_predictor(enc, {"predictor": 2, "colors": colors, "bpc": 8, "columns": columns}), raw, colors)

    def test_no_predictor_and_predictor_one_leave_the_bytes_as_they_are(self):
        self.assertEqual(scan_tool._undo_predictor(b"abc", {"predictor": 1, "colors": 1, "bpc": 8, "columns": 1}), b"abc")

    def test_a_row_that_is_cut_short_is_undone_as_far_as_it_goes(self):
        raw = random.Random(6).randbytes(5 * 9)
        enc = png_filter(raw, 5, 1)
        parms = {"predictor": 15, "colors": 1, "bpc": 8, "columns": 5}
        for cut in (1, 2, 3, 4, 5, 6, 7, 11):
            part = enc[:-cut]
            out = scan_tool._undo_predictor(part, parms)
            rows = -(-len(part) // 6)  # one type byte for each row, the last perhaps alone
            self.assertEqual(len(out), len(part) - rows, cut)
            self.assertEqual(out, raw[:len(out)], cut)  # whatever comes out is the true start of the data

    def test_every_other_predictor_and_every_parameter_that_makes_no_sense_is_refused(self):
        ok = {"predictor": 12, "colors": 1, "bpc": 8, "columns": 4}
        for label, parms in {"predictor 3": dict(ok, predictor=3), "predictor 9": dict(ok, predictor=9), "predictor 16": dict(ok, predictor=16),
                             "predictor 0": dict(ok, predictor=0), "tiff at 16 bits": dict(ok, predictor=2, bpc=16),
                             "tiff at 4 bits": dict(ok, predictor=2, bpc=4), "bits 3": dict(ok, bpc=3), "bits 0": dict(ok, bpc=0),
                             "colors 0": dict(ok, colors=0), "colors 33": dict(ok, colors=33), "columns 0": dict(ok, columns=0),
                             "an enormous row": dict(ok, columns=10 ** 9)}.items():
            width = min(16, max(1, (parms["colors"] * parms["bpc"] * parms["columns"] + 7) // 8)) if parms["colors"] < 33 and parms["bpc"] else 4
            data = (b"\x00" + bytes(width)) * 3  # rows of type none, so that no refusal can come from the data and only the parameters
            with self.assertRaises(self.UNREADABLE, msg=label):
                scan_tool._undo_predictor(data, parms)

    def test_a_row_with_a_type_that_is_not_a_png_filter_is_refused(self):
        for kind in (5, 6, 7, 127, 255):
            with self.assertRaises(self.UNREADABLE, msg=kind):
                scan_tool._undo_predictor(bytes([kind]) + b"abcd", {"predictor": 12, "colors": 1, "bpc": 8, "columns": 4})

    def test_a_great_amount_of_predicted_data_is_undone_in_time_that_grows_with_its_size(self):
        raw = random.Random(7).randbytes(3000 * 700)  # about two million bytes
        enc = b"".join(b"\x04" + raw[i:i + 3000] for i in range(0, len(raw), 3000))  # Paeth on every row, whatever the bytes
        started = time.monotonic()
        scan_tool._undo_predictor(enc, {"predictor": 15, "colors": 3, "bpc": 8, "columns": 1000})
        self.assertLess(time.monotonic() - started, 8)

    def test_a_few_bytes_behind_a_very_wide_row_do_not_allocate_a_whole_row(self):
        import tracemalloc
        parms = {"predictor": 12, "colors": 1, "bpc": 8, "columns": 4_000_000}
        tracemalloc.start()
        try:
            for _ in range(20):
                scan_tool._undo_predictor(b"\x04abc", parms)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1_000_000)  # not the four million bytes of a row of zeros, for four bytes of data

    def test_parameters_written_in_every_ordinary_way_are_read(self):
        read = scan_tool._parms
        self.assertEqual(read(b"/Filter /FlateDecode", [b"FlateDecode"]), [None])
        direct = read(b"/Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 5 /Colors 3 /BitsPerComponent 4 >>", [b"FlateDecode"])
        self.assertEqual(direct, [{"predictor": 12, "colors": 3, "bpc": 4, "columns": 5}])
        self.assertEqual(read(b"/DP << /Predictor 15 >>", [b"FlateDecode"]), [{"predictor": 15, "colors": 1, "bpc": 8, "columns": 1}])
        both = read(b"/DecodeParms [null << /Predictor 2 /Columns 9 >>]", [b"ASCIIHexDecode", b"FlateDecode"])
        self.assertEqual(both, [None, {"predictor": 2, "colors": 1, "bpc": 8, "columns": 9}])
        self.assertEqual(read(b"/DecodeParms null", [b"FlateDecode"]), [None])
        self.assertEqual(read(b"/DecodeParms [ << /Predictor 12 /Columns 3 >> ]", [b"FlateDecode"])[0]["columns"], 3)
        self.assertEqual(read(b"/DecodeParms << /Predictor 12 /Columns 3 /Early 1 /K -1 >>", [b"FlateDecode"])[0]["predictor"], 12)  # keys of other filters are ignored

    def test_a_name_escape_that_makes_a_delimiter_or_white_space_is_left_as_it_is_in_the_text_the_structure_is_read_from(self):
        keep = scan_tool._unescape_regular
        self.assertEqual(keep(b"/Fil#74er /Pre#64ictor"), b"/Filter /Predictor")  # ordinary letters are read
        for escape in (b"#3E", b"#3C", b"#5B", b"#5D", b"#28", b"#29", b"#2F", b"#25", b"#20", b"#0A", b"#0D", b"#09", b"#00", b"#0C", b"#23",
                       b"#7B", b"#7D"):
            self.assertEqual(keep(b"/A" + escape + b"B"), b"/A" + escape + b"B", escape)  # not a delimiter, not a space, not a mark
        self.assertEqual(keep(b"#41#6a"), b"Aj")
        self.assertEqual(keep(b"#4"), b"#4")  # not an escape

    def test_parameters_that_cannot_be_read_with_certainty_are_refused(self):
        read = scan_tool._parms
        flate = [b"FlateDecode"]
        for label, (text, names) in {
                "a reference": (b"/DecodeParms 9 0 R", flate), "a reference in an array": (b"/DecodeParms [9 0 R]", flate),
                "the short name as a reference": (b"/DP 9 0 R", flate), "a reference as the predictor": (b"/DecodeParms << /Predictor 9 0 R >>", flate),
                "a reference as the columns": (b"/DecodeParms << /Predictor 12 /Columns 9 0 R >>", flate),
                "two keys": (b"/DecodeParms << /Predictor 12 >> /DP << /Predictor 1 >>", flate),
                "the same key twice": (b"/DecodeParms << /Predictor 12 /Predictor 1 >>", flate),
                "a real number": (b"/DecodeParms << /Predictor 12 /Columns 5.5 >>", flate),
                "a negative number": (b"/DecodeParms << /Predictor 12 /Columns -5 >>", flate),
                "a string": (b"/DecodeParms << /Predictor 12 /Columns (5) >>", flate),
                "a nested dictionary": (b"/DecodeParms << /Predictor 12 /X << /Columns 5 >> >>", flate),
                "more entries than filters": (b"/DecodeParms [null null]", flate),
                "a dictionary for two filters": (b"/DecodeParms << /Predictor 12 >>", [b"ASCIIHexDecode", b"FlateDecode"]),
                "an unclosed dictionary": (b"/DecodeParms << /Predictor 12", flate), "an unclosed array": (b"/DecodeParms [null", flate),
                "a name": (b"/DecodeParms /Predictor", flate), "a number": (b"/DecodeParms 12", flate),
                "a huge number": (b"/DecodeParms << /Predictor 12 /Columns 99999999999999999999 >>", flate),
                "a comment in the dictionary": (b"/DecodeParms << /Predictor 12 %c\n /Columns 5 >>", flate),
                "a comment that holds the closing brackets": (b"/DecodeParms << %>>\n/Predictor 12 >>", flate),
                "a comment in an array": (b"/DecodeParms [ %]\n << /Predictor 12 >> ]", flate),
                "a reference after a comment": (b"/DecodeParms << /Predictor 1 %c\n0 R >>", flate),
                "a number that runs into a letter": (b"/DecodeParms << /Predictor 12x >>", flate),
                "a number that runs into a hash": (b"/DecodeParms << /Predictor 12#41 >>", flate)}.items():
            with self.assertRaises(self.UNREADABLE, msg=label):
                read(text, names)

    def test_the_reading_of_parameters_costs_little_on_hostile_text(self):
        started = time.monotonic()
        for text in (b"/DecodeParms " + b"[" * 100_000, b"/DecodeParms " + b"<< " * 50_000, b"/DecodeParms [" + b"null " * 100_000 + b"]",
                     b"/DP " + b"(" * 100_000, b"/DecodeParms << " + b"/Predictor 12 " * 20_000 + b">>"):
            try:
                scan_tool._parms(text, [b"FlateDecode"])
            except scan_tool._Unreadable:
                pass
        self.assertLess(time.monotonic() - started, 5)


class PredictorScanTest(ScanCase):
    """Through the real scan tool, in its sandbox: what a claim in a dictionary used to skip is read now."""

    def hidden(self, dictionary, parms, predictor_number=12, columns=40, chain=b"/Filter /FlateDecode", wrap=zlib.compress):
        data = wrap(png_filter(script_rows(columns), columns, types=(0, 1, 2, 3, 4)))
        return pdf(stream_object(dictionary + b" " + chain + b" " + parms, data))

    def test_an_object_stream_behind_a_predictor_is_read_whatever_it_claims_to_be(self):
        self.approve_scan()
        keys = b"/N 1 /First 10 "
        claims = {"plain": b"/Type /ObjStm " + keys, "dressed as an image": b"/Type /XObject /Subtype /Image " + keys,
                  "the words in a string": b"/Type /ObjStm /X (/Subtype /Image) " + keys,
                  "dressed as a cross-reference stream": b"/Type /XRef /W [1 2 1] /Size 4 " + keys,
                  "with the keys of both": b"/Type /XRef /W [1 2 1] /Size 4 /Subtype /Image /Type /XObject " + keys}
        for label, claim in claims.items():
            for number in (10, 11, 12, 13, 14, 15):
                parms = b"/DecodeParms << /Predictor %d /Columns 40 >>" % number
                _b, _v, got = self.scan_bytes("paper.pdf", self.hidden(claim, parms))
                self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0, f"{label}, predictor {number}: {kinds(got['caveats'])}")

    def test_the_tiff_predictor_and_a_predictor_on_the_second_of_two_filters_are_read_too(self):
        self.approve_scan()
        claim = b"/Type /ObjStm /N 1 /First 10"
        tiff = pdf(stream_object(claim + b" /Filter /FlateDecode /DecodeParms << /Predictor 2 /Columns 40 >>",
                                 zlib.compress(tiff_filter(script_rows(40), 40))))
        _b, _v, got = self.scan_bytes("paper.pdf", tiff)
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)
        hexed = pdf(stream_object(claim + b" /Filter [/ASCIIHexDecode /FlateDecode] /DecodeParms [null << /Predictor 12 /Columns 40 >>]",
                                  zlib.compress(png_filter(script_rows(40), 40)).hex().encode() + b">"))
        _b, _v, got = self.scan_bytes("paper.pdf", hexed)
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)

    def test_parameters_the_scan_cannot_read_and_predictors_it_does_not_know_are_an_incomplete_scan_not_a_skip(self):
        self.approve_scan()
        claim = b"/Type /XRef /W [1 2 1] /Size 4 /N 1 /First 10"
        for label, parms in {"a reference": b"/DecodeParms 9 0 R", "a reference in an array": b"/DecodeParms [null 9 0 R]",
                             "a predictor it does not know": b"/DecodeParms << /Predictor 16 /Columns 40 >>",
                             "no columns for a wide row": b"/DecodeParms << /Predictor 12 /Columns 0 >>"}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", self.hidden(claim, parms))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), label)

    def test_what_is_decoded_before_a_predictor_that_cannot_be_undone_is_still_read(self):
        self.approve_scan()
        plain = zlib.compress(script_rows(40))  # not predicted at all, though the dictionary says so
        data = pdf(stream_object(b"/Type /XRef /W [1 2 1] /Size 4 /Filter /FlateDecode /DecodeParms << /Predictor 16 /Columns 40 >>", plain))
        _b, _v, got = self.scan_bytes("paper.pdf", data)
        found = kinds(got["caveats"])
        self.assertGreater(found.get("javascript", 0), 0, found)
        self.assertEqual(found.get("scan_incomplete"), 1, found)

    def test_a_real_image_and_a_real_cross_reference_stream_behind_a_predictor_give_no_caveat(self):
        self.approve_scan()
        picture = stream_object(b"/Type /XObject /Subtype /Image /Width 30 /Height 30 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                                b"/Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /Columns 30 >>",
                                zlib.compress(png_filter(random.Random(8).randbytes(90 * 30), 90, bpp=3)), 6)
        xref = stream_object(b"/Type /XRef /W [1 2 1] /Size 6 /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 4 >>",
                             zlib.compress(png_filter(bytes([1, 0, 15, 0] * 6), 4, types=(2,))), 7)
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(picture + xref))
        self.assertEqual(got["caveats"], [])

    def test_twenty_figures_with_predictors_and_fifteen_hundred_or_twenty_five_hundred_small_streams_give_no_caveat(self):
        self.approve_scan()
        figure = zlib.compress(png_filter(bytes(3000) * 316, 3000, bpp=3, types=(2, 4)))  # about 950,000 bytes decoded
        figures = b"".join(stream_object(b"/Type /XObject /Subtype /Image /Width 1000 /Height 316 /ColorSpace /DeviceRGB "
                                         b"/BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>",
                                         figure, 10 + n) for n in range(20))
        started = time.monotonic()
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(figures))
        self.assertEqual(got["caveats"], [])
        self.assertLess(time.monotonic() - started, 40)
        small = zlib.compress(png_filter(b"abcdefgh", 4))
        many = lambda n: pdf(b"".join(stream_object(b"/Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 4 >>", small, 10 + k) for k in range(n)))
        _b, _v, fifteen = self.scan_bytes("paper.pdf", many(1500))
        self.assertEqual(fifteen["caveats"], [])
        _b, _v, twentyfive = self.scan_bytes("paper.pdf", many(2500))
        self.assertEqual(twentyfive["caveats"], [])  # the limit on their number is 500,000 now; LimitsTest tests it with a small one

    def test_a_decoy_set_of_parameters_in_a_string_cannot_make_the_scan_garble_what_the_viewer_reads_as_it_is(self):
        self.approve_scan()
        script = SCRIPT * 2
        # the real stream has no predictor at all; a string in its dictionary holds one, and the scan, which does not parse strings,
        # takes it for the stream's own and undoes a Sub row on text that was never filtered. A viewer reads the text as it is.
        data = zlib.compress(b"\x01" + script)
        decoy = b"/Type /ObjStm /N 1 /First 10 /Note (/DecodeParms << /Predictor 12 /Columns 100000 >>) /Filter /FlateDecode"
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(decoy, data)))
        found = kinds(got["caveats"])
        self.assertGreater(found.get("javascript", 0), 0, found)  # the bytes before the predictor are read as well
        for nested in (b"/X << /DecodeParms << /Predictor 12 /Columns 100000 >> >>", b"/X [/DP << /Predictor 15 /Columns 100000 >>]"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(b"/Type /ObjStm /N 1 /First 10 " + nested + b" /Filter /FlateDecode", data)))
            self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0, nested)

    def test_a_decoy_filter_in_a_string_cannot_make_the_scan_take_a_deflate_stream_for_a_picture(self):
        self.approve_scan()
        # the first /Filter the scan reads says DCTDecode, an image codec the scan does not look into; the real one is deflate
        real = zlib.compress(SCRIPT * 2)
        cases = {"a decoy in a string before the real key": b"/Type /ObjStm /N 1 /First 10 /Note (/Filter /DCTDecode) /Filter /FlateDecode",
                 "a decoy in a nested dictionary before it": b"/Type /ObjStm /N 1 /First 10 /X << /Filter /DCTDecode >> /Filter /FlateDecode",
                 "a decoy written with an escape": b"/Type /ObjStm /N 1 /First 10 /Note (/Fil#74er /DCTDecode) /Filter /FlateDecode",
                 "a decoy after the real key": b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode /Note (/Filter /DCTDecode)",
                 "a decoy of no filter at all": b"/Type /ObjStm /N 1 /First 10 /Note (/Filter /Crypt) /Filter /FlateDecode"}
        for label, dictionary in cases.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(dictionary, real)))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), f"{label}: the stream was passed over in silence")

    def test_a_dictionary_that_names_its_filter_once_is_read_as_before(self):
        self.approve_scan()
        for dictionary in (b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode", b"/Type /ObjStm /N 1 /First 10 /Filter [/FlateDecode]",
                           b"/Type /ObjStm /N 1 /First 10 /Fil#74er /FlateDecode", b"/Type /ObjStm /N 1 /First 10 /FFilter /Foo /Filter /FlateDecode"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(dictionary, zlib.compress(SCRIPT * 2))))
            found = kinds(got["caveats"])
            self.assertGreater(found.get("javascript", 0), 0, dictionary)
            self.assertNotIn("scan_incomplete", found, dictionary)

    SUB = staticmethod(lambda: zlib.compress(png_filter(script_rows(40), 40, types=(1,))))  # the script, Sub-filtered: not text until undone

    def test_a_name_that_escapes_into_a_delimiter_cannot_close_the_parameters_early(self):
        self.approve_scan()
        base = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode "
        cases = {"an escaped closing bracket in a key": b"/DecodeParms<</A#3E#3E /Predictor 12 /Columns 40>>",
                 "an escaped closing bracket in a name value": b"/DecodeParms<</A /B#3E#3E /Predictor 12 /Columns 40>>",
                 "an escaped space": b"/DecodeParms<</Predictor#2012 /Columns 40>>",
                 "an escaped opening bracket": b"/DecodeParms<</A#3C#3C /Predictor 12 /Columns 40>>",
                 "an escaped comment mark": b"/DecodeParms<</A#25 /Predictor 12 /Columns 40>>"}
        for label, parms in cases.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + parms, self.SUB())))
            found = kinds(got["caveats"])
            self.assertTrue(found.get("javascript", 0) > 0 or "scan_incomplete" in found, f"{label}: the script was hidden: {found}")
        honest = b"/DecodeParms << /Predictor 12 /Columns 40 >>"
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + honest, self.SUB())))
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)
        spelled = b"/DecodeParms << /Pre#64ictor 12 /Co#6Cumns 40 >>"  # escapes of ordinary letters are still read
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + spelled, self.SUB())))
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)

    def test_a_comment_in_the_parameters_cannot_hide_the_predictor_or_a_reference(self):
        self.approve_scan()
        base = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode "
        cases = {"a comment that holds the closing brackets": b"%<<\n" + base + b"/DecodeParms<< %>>\n/Predictor 12 /Columns 40>>",
                 "a reference after a comment": base + b"/DecodeParms<</Predictor 1 %c\n0 R /Columns 40>>",
                 "a reference after a line end and a comment": base + b"/DecodeParms<</Predictor 1\n%c\n0 R /Columns 40>>",
                 "a geometry that is a reference": base + b"/DecodeParms<</Predictor 12 /Columns 40%c\n0 R>>",
                 "a geometry that is a reference after a space": base + b"/DecodeParms<</Predictor 12 /Columns 40 %c\n0 R>>",
                 "a comment before the key": base + b"/DecodeParms<< %c\n/Predictor 12 /Columns 40>>",
                 "a comment in an array of parameters": base + b"/DecodeParms[ %]\n<</Predictor 12 /Columns 40>>]"}
        for label, dictionary in cases.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(dictionary, self.SUB())))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), f"{label}: the script was hidden: {kinds(got['caveats'])}")

    def test_a_number_that_runs_into_letters_is_not_a_number(self):
        self.approve_scan()
        base = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode "
        for parms in (b"/DecodeParms<</Predictor 12x /Columns 40>>", b"/DecodeParms<</Predictor 12 /Columns 40abc>>",
                      b"/DecodeParms<</Predictor 12 /Columns 40#41>>"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + parms, self.SUB())))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), parms)
        close = b"/DecodeParms<</Predictor 12/Columns 40>>"  # no space, the last number against the closing brackets
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + close, self.SUB())))
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)

    def test_a_comment_in_the_filter_array_cannot_cut_the_chain_short(self):
        self.approve_scan()
        hexed = zlib.compress(SCRIPT.hex().encode() * 2 + b">")  # the text of the action, in hex, inside deflate: a chain of two filters
        base = b"/Type /ObjStm /N 1 /First 10 "
        for label, chain in {"a comment holding the closing bracket": b"/Filter[/FlateDecode %]\n/ASCIIHexDecode]",
                             "a comment with no space": b"/Filter[/FlateDecode%]\n/ASCIIHexDecode]"}.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + chain, hexed)))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), f"{label}: {kinds(got['caveats'])}")
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + b"/Filter [/FlateDecode /ASCIIHexDecode]", hexed)))
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)  # the honest chain reads the same text

    def test_a_filter_list_that_holds_anything_but_names_is_not_read_to_its_first_bracket(self):
        self.approve_scan()
        hexed = zlib.compress(SCRIPT.hex().encode() * 2 + b">")  # deflate, then hex: a viewer reads the action, a list cut at the first ] does not
        base = b"/Type /ObjStm /N 1 /First 10 "
        cases = {"a string that holds a bracket": b"/Filter[/FlateDecode (]) /ASCIIHexDecode]",
                 "an empty array inside it": b"/Filter[/FlateDecode [] /ASCIIHexDecode]",
                 "an array inside it": b"/Filter[/FlateDecode [/X] /ASCIIHexDecode]",
                 "a hex string inside it": b"/Filter[/FlateDecode <5D> /ASCIIHexDecode]",
                 "a number inside it": b"/Filter[/FlateDecode 5 /ASCIIHexDecode]",
                 "a dictionary inside it": b"/Filter[/FlateDecode <</A 1>> /ASCIIHexDecode]",
                 "a name with an escaped bracket": b"/Filter[/FlateDecode#5D /ASCIIHexDecode]",
                 "a name with a mark that is not a letter": b"/Filter[/FlateDecode /ASCIIHex-Decode]"}
        for label, chain in cases.items():
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + chain, hexed)))
            self.assertIn("scan_incomplete", kinds(got["caveats"]), f"{label}: the chain was cut short in silence: {kinds(got['caveats'])}")
        for chain in (b"/Filter [/FlateDecode /ASCIIHexDecode]", b"/Filter[/FlateDecode/ASCIIHexDecode]", b"/Filter [ /FlateDecode\n/ASCIIHexDecode ]",
                      b"/Filter [/Fl /AHx]"):
            _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(base + chain, hexed)))
            self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0, chain)  # an honest list is read as before
            self.assertNotIn("scan_incomplete", kinds(got["caveats"]), chain)

    def test_what_the_predictor_made_of_the_data_is_read_as_well_as_the_data_before_it(self):
        self.approve_scan()
        claim = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 40 >>"
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(stream_object(claim, zlib.compress(png_filter(script_rows(40), 40, types=(1, 2, 3, 4))))))
        self.assertGreater(kinds(got["caveats"]).get("javascript", 0), 0)  # filtered rows hide it from the bytes before the predictor

    def test_wide_pixels_make_the_rows_cost_more_of_the_budget_and_a_file_of_them_is_cut_short_in_time(self):
        self.approve_scan()
        # 32 colours: 33 bytes a row and 32 passes over each row for a Sub filter; the rows alone would be well under the budget
        rows = zlib.compress(b"\x01" + bytes(32) + (b"\x01" + bytes(32)) * 57_000)
        parms = b"/Filter /FlateDecode /DecodeParms << /Predictor 11 /Colors 32 /Columns 1 >>"
        wide = pdf(b"".join(stream_object(parms, rows, 5 + n) for n in range(4)))
        started = time.monotonic()
        _b, _v, got = self.scan_bytes("paper.pdf", wide)
        self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1})
        self.assertLess(time.monotonic() - started, 30)

    def test_the_budget_charges_a_row_for_the_passes_it_costs(self):
        rows = [10]
        parms = {"predictor": 11, "colors": 32, "bpc": 8, "columns": 1}
        with self.assertRaises(scan_tool._Unreadable):
            scan_tool._undo_predictor((b"\x01" + bytes(32)) * 1, parms, rows)  # one row of 32 passes against 10 left
        rows = [32]
        scan_tool._undo_predictor((b"\x01" + bytes(32)) * 1, parms, rows)
        self.assertEqual(rows, [0])
        rows = [100]
        scan_tool._undo_predictor(b"\x01\x02\x03" * 4, {"predictor": 2, "colors": 3, "bpc": 8, "columns": 1}, rows)
        self.assertEqual(rows, [100 - 4 * 3])  # the TIFF predictor charges a pass for each colour

    def test_streams_with_a_very_wide_row_and_hardly_any_data_cost_little(self):
        self.approve_scan()
        tiny = zlib.compress(b"\x00abc")
        parms = b"/Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 4000000 >>"
        started = time.monotonic()
        _b, _v, got = self.scan_bytes("paper.pdf", pdf(b"".join(stream_object(parms, tiny, 5 + n) for n in range(1800))))
        self.assertEqual(got["caveats"], [])
        self.assertLess(time.monotonic() - started, 20)

    def test_a_great_many_rows_of_one_byte_cost_a_bounded_time_and_are_an_incomplete_scan(self):
        self.approve_scan()
        # a row costs the same however short it is: 1.9 million bytes of one-column rows are 950,000 rows in each stream
        rows = zlib.compress(b"\x00a" * 950_000)
        parms = b"/Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 1 >>"
        one = pdf(stream_object(parms, rows))
        started = time.monotonic()
        _b, _v, got = self.scan_bytes("paper.pdf", one)
        self.assertEqual(got["caveats"], [])  # under the budget of rows, read in full
        three = pdf(b"".join(stream_object(parms, rows, 5 + n) for n in range(3)))
        _b, _v, got = self.scan_bytes("paper.pdf", three)
        self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1})  # three of them are more rows than the scan undoes in a file
        self.assertLess(time.monotonic() - started, 40)

    def test_a_large_picture_behind_a_predictor_is_a_large_picture_and_a_large_stream_of_anything_else_is_incomplete(self):
        self.approve_scan()
        rows = bytes(3000) * 1000  # three million bytes of zeros
        picture = pdf(stream_object(b"/Type /XObject /Subtype /Image /Width 1000 /Height 1000 /Filter /FlateDecode "
                                    b"/DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>", zlib.compress(png_filter(rows, 3000, bpp=3, types=(2,)))))
        _b, _v, got = self.scan_bytes("paper.pdf", picture)
        self.assertEqual(kinds(got["caveats"]), {"large_image_streams": 1})
        other = pdf(stream_object(b"/Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>",
                                  zlib.compress(png_filter(rows, 3000, bpp=3, types=(2,)))))
        _b, _v, got = self.scan_bytes("paper.pdf", other)
        self.assertEqual(kinds(got["caveats"]), {"scan_incomplete": 1})


class ReaderTest(unittest.TestCase):
    """The scan finds a stream through its own object, read forward with strings and comments known. These go straight to the scan
    function, which is what the tool runs; a few are run through the sandboxed tool in PredictorScanTest and ScanStageTest."""
    REAL_DICT = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode"

    def real(self, number=9, dictionary=None):
        """An object stream with the action in it (deflate): what a viewer reads and the scan must not miss."""
        return stream_object(self.REAL_DICT if dictionary is None else dictionary, zlib.compress(b"1 0 " + SCRIPT * 2), number)

    def found(self, data):
        return kinds(scan_tool.scan_pdf(data))

    def assert_not_hidden(self, data, message=""):
        found = self.found(data)
        self.assertTrue(found.get("javascript", 0) > 0 or "scan_incomplete" in found, f"{message}: the action was hidden: {found}")
        return found

    def assert_read(self, data, message=""):
        found = self.found(data)
        self.assertGreater(found.get("javascript", 0), 0, f"{message}: {found}")
        self.assertNotIn("scan_incomplete", found, message)

    # -- what used to steer the scan
    def test_a_stream_marker_in_a_string_of_a_dictionary_is_part_of_the_string_and_the_real_stream_is_read(self):
        decoy = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode /Note (>>\nstream\nFAKEDATA\n) /More 1"
        self.assert_read(pdf(stream_object(decoy, zlib.compress(b"1 0 " + SCRIPT * 2))), "a small decoy")

    def test_a_fake_endstream_in_a_string_with_the_brackets_balanced_is_part_of_the_string(self):
        decoy = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode /Note (>>\nstream\nFAKE\nendstream << ) /More 1"
        self.assert_read(pdf(stream_object(decoy, zlib.compress(b"1 0 " + SCRIPT * 2))), "balanced")
        decoy = b"/Type /ObjStm /N 1 /First 10 /Note (endstream endobj) /Filter /FlateDecode"
        self.assertTrue(self.found(pdf(stream_object(decoy, zlib.compress(b"1 0 " + SCRIPT * 2)))).get("javascript", 0) > 0)

    def test_a_fake_object_header_in_a_string_cannot_hide_the_real_stream(self):
        carrier = b"4 0 obj\n<< /Note (6 0 obj << /Filter /FlateDecode >> stream\nXX\nendstream) >>\nendobj\n"
        string_object = b"4 0 obj\n(6 0 obj << /Filter /FlateDecode >> stream\nXX\nendstream)\nendobj\n"
        array = b"4 0 obj\n[(6 0 obj << >> stream\n) <363020> (endobj)]\nendobj\n"
        trailer = b"trailer\n<< /Info (7 0 obj << >> stream\nZ\nendstream) >>\n"
        for label, data in {"in a string of a dictionary": carrier + self.real(), "in an object that is a string": string_object + self.real(),
                            "in an array": array + self.real(), "in a trailer": self.real() + trailer + self.real(10)}.items():
            found = self.found(pdf(data))
            self.assertGreater(found.get("javascript", 0), 0, f"{label}: the real stream was not read: {found}")  # read, whatever else
            self.assertIn("scan_incomplete", found, label)  # and the file is reported: it holds text that looks like another object

    def test_a_fake_object_header_in_a_comment_is_reported(self):
        for label, comment in {"a whole fake object": b"% 9 0 obj << /Filter /FlateDecode >> stream\nFAKEDATA\nendstream\n",
                               "a header and an open string": b"% 9 0 obj (\n",
                               "after other words": b"%%EOF 9 0 obj <</Filter/FlateDecode>>stream\nXXXX\nendstream\n"}.items():
            found = self.assert_not_hidden(pdf(comment + self.real()), label)
            self.assertIn("scan_incomplete", found, label)

    def test_a_fake_object_in_plain_junk_that_would_swallow_the_real_stream_is_reported(self):
        fake = b"junk 9 0 obj << /Filter /FlateDecode >>\nstream\nXX\n"  # no endstream of its own: it runs into the next real one
        found = self.assert_not_hidden(pdf(fake + self.real(10)), "junk")
        self.assertIn("scan_incomplete", found)
        fake = b"9 0 obj (\n"  # an open string that a later parenthesis would close, swallowing what lies between
        late = b"11 0 obj\n(close)\nendobj\n"
        found = self.assert_not_hidden(pdf(fake + self.real(10) + late), "an open string")
        self.assertIn("scan_incomplete", found)

    def test_a_fake_header_in_the_data_of_a_stream_is_only_data_and_the_real_stream_after_it_is_read(self):
        fake = stream_object(b"/Length 99", b"7 0 obj << /A 1 >> stream\nQ", 5)
        self.assert_read(pdf(fake + self.real(10)), "in stream data")

    def test_a_stream_keyword_outside_every_object_is_reported(self):
        found = self.found(pdf(self.real() + b"stream\nSOMETHING\nendstream\n"))
        self.assertIn("scan_incomplete", found)
        found = self.found(pdf(b"<< /A 1 >>\nstream\nXX\nendstream\n" + self.real()))
        self.assertIn("scan_incomplete", found)
        self.assertGreater(found.get("javascript", 0), 0)

    def test_a_whole_real_object_wrapped_in_a_string_of_another_objects_dictionary_is_reported(self):
        hexed = stream_object(b"/Type /ObjStm /N 1 /First 10 /Filter /ASCIIHexDecode", (b"1 0 " + SCRIPT * 2).hex().encode() + b">", 9)
        # the carrier is a stream with a valid hex body, so nothing else about it is wrong; the real object sits inside a string
        carrier = b"8 0 obj\n<< /Filter /ASCIIHexDecode /Note (" + hexed.replace(b"/Filter /ASCIIHexDecode", b"/F2 /X") + b") >>\nstream\n4142>\nendstream\nendobj\n"
        self.assertIn("scan_incomplete", self.found(pdf(carrier)))
        unwrapped = pdf(hexed)
        self.assertGreater(self.found(unwrapped).get("javascript", 0), 0)  # the real object read for itself is found

    def test_a_real_object_with_a_header_written_in_an_unusual_way_and_wrapped_in_a_string_is_reported(self):
        for label, header in {"a comment between the numbers": b"9 %c\n0 obj", "many digits": b"00000000000009 0 obj", "a long generation": b"9 000000 obj",
                              "a comment and line ends": b"9\n%x\n0\nobj", "glued to a word": b"endobj9 0 obj"}.items():
            hexed = (header + b"\n<< /Type /ObjStm /N 1 /First 10 /F2 /X >>\nstream\n" + (b"1 0 " + SCRIPT * 2).hex().encode() + b">\nendstream\n")  # no endobj: viewers do not need one
            carrier = b"8 0 obj\n<< /Filter /ASCIIHexDecode /Note (" + hexed + b") >>\nstream\n4142>\nendstream\nendobj\n"
            self.assertIn("scan_incomplete", self.found(pdf(carrier)), label)

    def test_a_header_with_no_white_space_before_obj_is_still_a_header(self):
        for label, header in {"0obj": b"9 0obj", "0obj with a comment": b"9 %c\n0obj", "endobj glued to a digit": b"0endobj 9 0obj"}.items():
            hexed = (header + b"<< /Type /ObjStm /N 1 /First 10 /F2 /X >>\nstream\n" + (b"1 0 " + SCRIPT * 2).hex().encode() + b">\nendstream\n")
            carrier = b"8 0 obj\n<< /Filter /ASCIIHexDecode /Note (" + hexed + b") >>\nstream\n4142>\nendstream\nendobj\n"
            self.assertIn("scan_incomplete", self.found(pdf(carrier)), label)

    def test_ascii85_text_that_spells_endstream_does_not_cut_a_stream_short_unnoticed(self):
        # the letters of endstream are all ASCII85 digits, so a stream a viewer reads whole by its /Length can hold them: the scan cuts
        # it there, and what it cut off holds the action. An ASCII85 stream with no ~> in what the scan has is reported.
        payload = b"1 0 " + SCRIPT * 2
        payload += b" " * (-len(payload) % 4)
        junk = base64.a85decode(b"endst") + base64.a85decode(b"ream!")
        text = base64.a85encode(b"AAAA" + junk + payload) + b"~>"
        self.assertIn(b"endstream", text)

        def make(data, extra=b""):
            return b"9 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Length %d /Filter /ASCII85Decode %s>>\nstream\n" % (len(data), extra) + data + b"\nendstream\nendobj\n"

        self.assertIn("scan_incomplete", self.found(pdf(make(text))))
        for label, data in {"without the ~>": text[:-2], "a chain": text}.items():
            self.assertIn("scan_incomplete", self.found(pdf(make(data))), label)
        honest = base64.a85encode(b"AAAA" + b"BBBBBBBB" + payload) + b"~>"
        found = self.found(pdf(make(honest)))
        self.assertGreater(found.get("javascript", 0), 0)  # the honest twin is read, as before
        self.assertNotIn("scan_incomplete", found)
        found = self.found(pdf(make(b"<~" + honest)))  # the opening mark is allowed
        self.assertGreater(found.get("javascript", 0), 0)

    def test_hex_text_that_spells_endstream_or_has_no_end_mark_does_not_cut_a_stream_short_unnoticed(self):
        # a viewer reads hex by /Length and skips what is not a digit (n s t r m), so text with the word in it and a script after it
        # reads on; the scan cuts at the word and what is left has no >
        payload = (b"1 0 " + SCRIPT * 2).hex().encode()

        def make(data):
            return b"9 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Length %d /Filter /ASCIIHexDecode >>\nstream\n" % len(data) + data + b"\nendstream\nendobj\n"

        cut = b"41414141" + b"endstream" + payload + b">"
        self.assertIn("scan_incomplete", self.found(pdf(make(cut))))
        self.assertIn("scan_incomplete", self.found(pdf(make(b"41414141" + payload))))  # no end mark at all
        honest = self.found(pdf(make(b"41414141" + payload + b">")))
        self.assertGreater(honest.get("javascript", 0), 0)  # the honest twin is read, as before
        self.assertNotIn("scan_incomplete", honest)

    def test_anything_but_white_space_after_the_end_of_a_streams_data_is_reported(self):
        payload = b"1 0 " + SCRIPT * 2
        ends = {"deflate": (b"/FlateDecode", zlib.compress(payload)),
                "ascii85": (b"/ASCII85Decode", base64.a85encode(payload + b" " * (-len(payload) % 4)) + b"~>"),
                "hex": (b"/ASCIIHexDecode", payload.hex().encode() + b">"),
                "ascii85 then deflate": (b"[/ASCII85Decode /FlateDecode]", base64.a85encode(zlib.compress(payload)) + b"~>"),
                "hex then deflate": (b"[/ASCIIHexDecode /FlateDecode]", zlib.compress(payload).hex().encode() + b">"),
                "deflate then hex": (b"[/FlateDecode /ASCIIHexDecode]", zlib.compress(payload.hex().encode() + b">"))}

        def make(filt, data):
            return b"9 0 obj\n<< /Type /ObjStm /N 1 /First 4 /Length %d /Filter %s >>\nstream\n" % (len(data), filt) + data + b"\nendstream\nendobj\n"

        for label, (filt, data) in ends.items():
            plain = self.found(pdf(make(filt, data)))
            self.assertGreater(plain.get("javascript", 0), 0, label)
            self.assertNotIn("scan_incomplete", plain, label)
            for white in (b" ", b"\n", b"\r\n", b"\r", b"\t \x00\x0c\n"):  # what a writer puts before endstream
                found = self.found(pdf(make(filt, data + white)))
                self.assertGreater(found.get("javascript", 0), 0, f"{label} + {white!r}")
                self.assertNotIn("scan_incomplete", found, f"{label} + {white!r}")
            for extra in (b"x", b" x", b"\x00\x01", b"%", b"\n\n\x01"):
                self.assertIn("scan_incomplete", self.found(pdf(make(filt, data + extra))), f"{label} + {extra!r}")
        # a deflate stream cut short is still reported
        self.assertIn("scan_incomplete", self.found(pdf(make(b"/FlateDecode", zlib.compress(payload)[:-6]))))

    def test_a_large_image_is_the_same_with_bytes_after_the_end_of_its_data(self):
        # the decoder stops at its limit, so what lies past the end is never reached: nothing here to hide, and nothing new to report
        flat = zlib.compress(b"\0" * BIG)
        for tail in (b"", b"\n", b"junk"):
            got = self.found(pdf(image(flat + tail, extra=b"/Filter /FlateDecode", compress=False)))
            self.assertEqual(got, {"large_image_streams": 1}, tail)

    def test_a_real_object_whose_header_has_no_white_space_before_obj_is_read_not_only_reported(self):
        script = zlib.compress(b"<< /S /JavaScript /JS (x) >>")
        real = b"9 0obj\n<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n" + script + b"\nendstream\nendobj\n"
        found = self.found(pdf(real))
        self.assertGreater(found.get("javascript", 0), 0)
        self.assertNotIn("scan_incomplete", found)

    def test_comments_with_no_line_end_after_many_objects_cost_in_proportion_to_the_file(self):
        data = pdf(b"1 0 obj<<>>%" * 50_000).replace(b"\n", b" ")
        started = time.monotonic()
        self.found(data)
        took = time.monotonic() - started
        self.assertLess(took, 5, f"{took:.1f} s for {len(data) / 1e6:.1f} MB")  # 60 s when each object searches to the end of the file

    def test_an_object_whose_value_is_the_header_of_the_next_object_is_reported_and_the_next_one_is_read(self):
        found = self.found(pdf(b"8 0 obj " + self.real(9)))
        self.assertIn("scan_incomplete", found)
        self.assertGreater(found.get("javascript", 0), 0)
        self.assertEqual(self.found(pdf(b"8 0 obj 42 endobj 9 0 obj 7 endobj")), {})  # a number as a value is fine

    def test_a_closed_string_or_dictionary_that_wraps_the_real_object_is_reported(self):
        for label, wrap_open, wrap_close in (("a string", b"9 0 obj (\n", b")\nendobj\n"), ("a string in a dictionary", b"9 0 obj <<\n/X (\n", b")\n>>\nendobj\n"),
                                              ("a string in an array", b"9 0 obj [(\n", b")]\nendobj\n")):
            found = self.found(pdf(wrap_open + self.real(10) + wrap_close))
            self.assertIn("scan_incomplete", found, label)

    def test_an_object_whose_value_starts_with_a_delimiter_it_cannot_read_is_reported(self):
        for value in (b")", b">>", b"]", b"}", b">"):
            found = self.found(pdf(b"9 0 obj\n" + value + b"\nendobj\n" + self.real(10)))
            self.assertIn("scan_incomplete", found, value)
            self.assertGreater(found.get("javascript", 0), 0, value)  # and the object after it is still read

    def test_an_honest_trailer_whose_string_holds_the_word_stream_is_not_a_stream_outside_an_object(self):
        trailer = b"trailer\n<< /Root 1 0 R /Info (made with the stream\ntool) >>\n"
        self.assert_read(pdf(self.real() + trailer), "a string with the word stream and a line end")
        self.assertIn("scan_incomplete", self.found(pdf(self.real() + b"made with the stream\ntool\n")))  # outside a trailer it is not allowed

    # -- the strings the reader must get right
    def test_strings_with_escapes_nesting_and_look_alike_brackets_are_read_to_their_real_end(self):
        notes = [b"(a\\)b >> stream\nc\\(d)", b"(a (b >> stream\n) c)", b"(\\051 >> stream\n)", b"(line\\\n>> stream\n continues)",
                 b"(back\\\\) /Z 1", b"(\\(\\(\\( >> stream\n)", b"<3E3E> /K (<<) /L (>>)", b"<3C3C0A73747265616D0A>",
                 b"(>> stream\r\n) /A#28 (x)", b"()", b"((()))", b"(a%b >> stream\n)"]
        notes += [b"(x (y) >> stream\n z)", b"(x (y (z) >> w) >> v)", b"(1 (2) 3) (4 (5) >> 6)"]
        for note in notes:
            before = b"/Type /ObjStm /N 1 /First 10 /Filter /FlateDecode /Note " + note
            after = b"/Type /ObjStm /N 1 /First 10 /Note " + note + b" /Filter /FlateDecode"  # what comes after the note must not be lost
            for dictionary in (before, after):
                self.assert_read(pdf(stream_object(dictionary, zlib.compress(b"1 0 " + SCRIPT * 2))), repr(dictionary))

    def test_a_percent_sign_inside_a_string_is_not_a_comment_and_one_outside_is(self):
        in_string = b"/Type /ObjStm /N 1 /First 10 /Note (100% sure) /Filter /FlateDecode"
        self.assert_read(pdf(stream_object(in_string, zlib.compress(b"1 0 " + SCRIPT * 2))), "in a string")
        comment = b"/Type /ObjStm /N 1 /First 10 %a comment (with a bracket\n/Filter /FlateDecode"
        self.assert_read(pdf(stream_object(comment, zlib.compress(b"1 0 " + SCRIPT * 2))), "a comment with an open parenthesis")

    # -- the limits
    def test_an_object_that_never_closes_is_reported_and_the_objects_after_it_are_still_read(self):
        for label, broken in {"a dictionary": b"3 0 obj\n<< /A 1 /B [1 2\n", "a string": b"3 0 obj\n<< /A (never\n", "an array": b"3 0 obj\n[1 2 3\n",
                              "a hex string": b"3 0 obj\n<48656C\n", "mismatched brackets": b"3 0 obj\n<< /A [1 >> ]\n",
                              "an open hex string in a dictionary": b"3 0 obj\n<< /A <48 >>\nendobj\n"}.items():
            found = self.found(pdf(broken + self.real()))
            self.assertIn("scan_incomplete", found, label)
            if label != "a hex string":  # an open hex string runs to the next > which is in the real object: read as a viewer would
                self.assertGreater(found.get("javascript", 0), 0, label)

    def test_nesting_up_to_the_limit_is_read_and_one_past_it_is_reported(self):
        depth = scan_tool.MAX_DEPTH
        for opener, closer, label, per in ((b"[", b"]", "arrays", 1), (b"<<", b">>", "dictionaries", 1), (b"<< /A [", b"] >>", "both", 2)):
            reps = depth // per  # nesting of exactly the limit (2 * 50 for the mixed one)
            one = pdf(b"3 0 obj\n" + opener * reps + closer * reps + b"\nendobj\n" + self.real())
            self.assertNotIn("scan_incomplete", self.found(one), f"{label}: nothing wrong at the limit")
            past = pdf(b"3 0 obj\n" + opener * (reps + 1) + closer * (reps + 1) + b"\nendobj\n" + self.real())
            found = self.found(past)
            self.assertIn("scan_incomplete", found, label)
            self.assertGreater(found.get("javascript", 0), 0, label)

    def test_a_stream_dictionary_up_to_the_size_limit_is_read_and_one_past_it_is_reported(self):
        base = b"<< " + self.REAL_DICT + b" /Pad ("
        room = scan_tool.MAX_DICT - len(base) - len(b") >>")
        at = base + b"x" * room + b") >>"
        self.assertEqual(len(at), scan_tool.MAX_DICT)
        self.assert_read(pdf(b"9 0 obj\n" + at + b"\nstream\n" + zlib.compress(b"1 0 " + SCRIPT * 2) + b"\nendstream\nendobj\n"), "at the limit")
        past = base + b"x" * (room + 1) + b") >>"
        found = self.found(pdf(b"9 0 obj\n" + past + b"\nstream\n" + zlib.compress(b"1 0 " + SCRIPT * 2) + b"\nendstream\nendobj\n"))
        self.assertIn("scan_incomplete", found)

    # -- honest files
    def test_honest_shapes_are_read_without_a_caveat(self):
        data = zlib.compress(b"1 0 " + SCRIPT * 2)
        shapes = {
            "no white space between tokens": b"1 0 obj<</Type/ObjStm/N 1/First 10/Filter/FlateDecode>>stream\n" + data + b"\nendstream endobj",
            "a stream keyword and a carriage return": b"1 0 obj\n<< " + self.REAL_DICT + b" >>\nstream\r" + data + b"\rendstream\rendobj\r",
            "a carriage return and a line feed": b"1 0 obj\r\n<< " + self.REAL_DICT + b" >>\r\nstream\r\n" + data + b"\r\nendstream\r\nendobj\r\n",
            "a space after the stream keyword": b"1 0 obj\n<< " + self.REAL_DICT + b" >>\nstream \n" + data + b"\nendstream\nendobj\n",
            "a comment between the header and the dictionary": b"1 0 obj % an object\n<< " + self.REAL_DICT + b" >>\nstream\n" + data + b"\nendstream\nendobj\n",
            "a comment between the dictionary and the stream": b"1 0 obj\n<< " + self.REAL_DICT + b" >> % data follows\nstream\n" + data + b"\nendstream\nendobj\n",
            "comments between objects": b"% a comment\n" + stream_object(self.REAL_DICT, data, 1) + b"% another, about an obj\n% 1 2\n",
        }
        for label, body in shapes.items():
            self.assert_read(b"%PDF-1.5\n" + body + b"\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n", label)
        full = (b"junk before the header\n%PDF-1.5\n%\xe2\xe3\xcf\xd3\n" + stream_object(self.REAL_DICT, data, 1) + b"xref\n0 2\n0000000000 65535 f \n0000000015 00000 n \n"
                b"trailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n123\n%%EOF\n" + b"3 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n3 1\n0000000999 00000 n \n"
                b"trailer\n<< /Size 4 /Prev 123 >>\nstartxref\n456\n%%EOF\njunk after the end \x00\x01\x02 with no keyword\n")
        self.assert_read(full, "junk, a header comment, two cross-reference sections and trailers")

    def test_an_honest_object_stream_a_cross_reference_stream_and_plain_objects_give_no_caveat(self):
        body = (stream_object(b"/Type /XRef /W [1 2 1] /Size 4 /Filter /FlateDecode", zlib.compress(bytes(40)), 4)
                + stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode", zlib.compress(b"8 0 << /A 1 >>"), 5)
                + b"6 0 obj\n<< /Type /Page /MediaBox [0 0 612 792] /Contents 7 0 R /Parent 2 0 R /Title (Page (one)) >>\nendobj\n"
                + stream_object(b"/Length 20", b"BT /F1 12 Tf (Hi) Tj ET", 7) + b"8 0 obj\n42\nendobj\n9 0 obj\n/Name\nendobj\n10 0 obj\n(a string)\nendobj\n"
                + b"11 0 obj\n[1 2 [3 4] <</A 1>> (x)]\nendobj\n12 0 obj\n<0A0B>\nendobj\n13 0 obj\ntrue\nendobj\n14 0 obj\nnull\nendobj\n")
        self.assertEqual(self.found(pdf(body)), {})

    def test_a_stream_with_no_endstream_is_reported(self):
        found = self.found(pdf(b"9 0 obj\n<< /Length 5 >>\nstream\nabcde"))
        self.assertIn("scan_incomplete", found)
        found = self.found(pdf(self.real() + b"10 0 obj\n<< /A 1 >>\nstream\nabcde"))
        self.assertIn("scan_incomplete", found)
        self.assertGreater(found.get("javascript", 0), 0)

    def test_a_stream_keyword_without_a_line_end_is_reported(self):
        self.assertIn("scan_incomplete", self.found(pdf(b"9 0 obj\n<< /A 1 >>\nstream XXXX\nendstream\nendobj\n")))

    def test_the_filter_key_check_is_by_exact_position(self):
        # a /Filter anywhere that is not in a stream dictionary the reader read is still reported
        self.assertIn("scan_incomplete", self.found(pdf(b"3 0 obj\n<< /Filter /Standard /V 1 >>\nendobj\n")))
        self.assertIn("scan_incomplete", self.found(pdf(self.real() + b"trailer\n<< /Filter /FlateDecode >>\n")))
        self.assertEqual(self.found(pdf(b"3 0 obj\n<< /A 1 >>\nendobj\n")), {})

    # -- cost
    def timed(self, data, limit):
        started = time.monotonic()
        scan_tool.scan_pdf(data)
        took = time.monotonic() - started
        self.assertLess(took, limit)
        return took

    def test_a_file_of_a_great_many_small_objects_is_read_in_time_that_grows_with_its_size(self):
        make = lambda n: pdf(b"".join(b"%d 0 obj\n<</Type/Page/MediaBox[0 0 612 792]/Count %d>>\nendobj\n" % (k, k) for k in range(1, n + 1)))
        small, large = self.timed(make(50_000), 15), self.timed(make(200_000), 40)
        self.assertLess(large, 8 * max(small, 0.25))

    def test_a_great_many_decoys_cost_in_proportion(self):
        decoy = lambda k: b"%d 0 obj\n<< /Note (>>\nstream\nFAKE\nendstream\n7 0 obj << /Filter /X >>) /Filter /Fake >>\nendobj\n" % k
        small = self.timed(pdf(b"".join(decoy(k) for k in range(1, 10_001))), 20)
        self.assertLess(self.timed(pdf(b"".join(decoy(k) for k in range(1, 40_001))), 60), 8 * max(small, 0.25))

    def test_nesting_to_the_limit_over_and_over_and_past_it_costs_in_proportion(self):
        depth = scan_tool.MAX_DEPTH
        one = lambda k: b"%d 0 obj\n" % k + b"[" * depth + b"]" * depth + b"\nendobj\n"
        past = lambda k: b"%d 0 obj\n" % k + b"[" * (depth + 5) + b"\nendobj\n"
        self.timed(pdf(b"".join(one(k) for k in range(1, 6_000))), 20)
        self.timed(pdf(b"".join(past(k) for k in range(1, 6_000))), 20)

    def test_a_long_run_of_comments_and_one_very_long_comment_cost_little(self):
        self.timed(pdf(b"".join(b"%% comment number %d about nothing\n" % k for k in range(300_000))), 20)
        self.timed(pdf(b"1 0 obj\n" + b"%" + b"x" * 8_000_000 + b"\n<< /A 1 >>\nendobj\n"), 20)
        self.timed(pdf(b"%" + b"x" * 8_000_000), 20)  # a comment that never ends
        self.timed(pdf(b"".join(b"%% 1 0 obj %d\n" % k for k in range(200_000))), 30)  # comments that look like headers

    def test_one_very_long_string_and_a_great_many_short_ones_cost_in_proportion(self):
        self.timed(pdf(b"1 0 obj\n(" + b"a" * 10_000_000 + b")\nendobj\n"), 20)
        self.timed(pdf(b"1 0 obj\n(" + b"\\)" * 2_000_000 + b")\nendobj\n"), 30)
        self.timed(pdf(b"1 0 obj\n[" + b"(x)" * 1_000_000 + b"]\nendobj\n"), 30)
        self.timed(pdf(b"1 0 obj\n(" + b"(" * 3_000_000), 20)  # nested and never closed

    def test_stream_keywords_and_header_look_alikes_scattered_everywhere_cost_in_proportion(self):
        self.timed(pdf(b"stream\n" * 600_000), 20)
        self.timed(pdf(b"1 0 " * 1_500_000), 20)  # numbers that never become a header
        self.timed(pdf(b"1" * 6_000_000 + b" 0 obj"), 20)  # a long run of digits
        self.timed(pdf(b"1 0 obj " * 400_000), 40)  # headers with nothing after them
        self.timed(pdf(b"1 0 obj\n<< /A 1 >>\nstream\n" * 100_000), 40)  # streams that never end

    def test_a_file_with_more_objects_than_the_scan_reads_is_reported_and_so_is_one_that_takes_more_steps_than_it_may(self):
        many = pdf(b"".join(b"%d 0 obj\n<< /A 1 >>\nendobj\n" % k for k in range(1, 11)))
        self.assertEqual(self.found(many), {})
        with mock.patch.object(scan_tool, "MAX_OBJECTS", 5):
            self.assertIn("scan_incomplete", self.found(many))
        with mock.patch.object(scan_tool, "MAX_READ_STEPS", 12):
            self.assertIn("scan_incomplete", self.found(many))
        strings = pdf(b"1 0 obj\n(" + b"\\)" * 50 + b")\nendobj\n")
        self.assertEqual(self.found(strings), {})
        with mock.patch.object(scan_tool, "MAX_READ_STEPS", 20):
            self.assertIn("scan_incomplete", self.found(strings))

    def test_objects_that_each_open_something_that_never_closes_cost_in_proportion_to_the_file_and_are_reported(self):
        # every header opens a hex string, an array with a hex string, or a string that nothing closes: each one used to search
        # the rest of the file again (a 4 MB file of the last kind took 44 seconds)
        cases = {"hex strings": pdf(b"1 0 obj <\n" * 300_000), "arrays with hex strings": pdf(b"1 0 obj [<\n" * 200_000),
                 "strings": pdf((b"1 0 obj (" + b"x" * 1000 + b"\n") * 4_000),
                 "dictionaries with strings": pdf((b"1 0 obj << /A (" + b"x" * 1000 + b"\n") * 4_000),
                 "comments inside arrays": pdf((b"1 0 obj [ %" + b"x" * 1000 + b"\n") * 4_000)}
        for label, data in cases.items():
            started = time.monotonic()
            found = self.found(data)
            took = time.monotonic() - started
            self.assertLess(took, 6, f"{label}: {took:.1f} s for {len(data) / 1e6:.1f} MB")  # about a second; 17 to 44 s without the cap
            self.assertIn("scan_incomplete", found, label)

    def test_the_scan_stops_reading_objects_after_a_number_it_cannot_finish_and_says_so(self):
        broken = lambda k: b"%d 0 obj\n<< /A (never closed\n" % k
        limit = scan_tool.MAX_UNFINISHED
        below = pdf(b"".join(broken(k) for k in range(1, limit)) + b"\n)" + b"\n)" * 4 + b"\n" + self.real(900))
        found = self.found(below)
        self.assertIn("scan_incomplete", found)
        # many broken objects, each closed by a later parenthesis, then a real one: below the limit the real one is still read
        closers = b"".join(b"%d 0 obj\n<< /A (broken\n" % k + b")\n>>\nendobj\n" for k in range(1, limit - 1))
        self.assertGreater(self.found(pdf(closers + self.real(900))).get("javascript", 0), 0)
        # past the limit the reading stops at the limit; the file is reported, and the plain bytes are still searched
        past = pdf(b"".join(broken(k) for k in range(1, limit + 20)) + b"\n" + self.real(900))
        found = self.found(past)
        self.assertIn("scan_incomplete", found)
        self.assertEqual(found.get("javascript", 0), 0)  # the reading stopped at the limit, so the real object after it was not read

    def test_the_real_paper_and_the_fixtures_give_what_they_gave(self):
        import glob
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
        for path in sorted(glob.glob(os.path.join(here, "*.pdf"))):
            with open(path, "rb") as f:
                self.assertEqual(self.found(f.read()), {}, os.path.basename(path))


class LimitsTest(unittest.TestCase):
    """The scan's limits on work: how much it decodes in all, how many streams, and what it keeps while it works. They are tested in
    this process, with the constants patched where a test needs a small limit (the scan stage runs the tool in a sandbox)."""

    def scan(self, data):
        return kinds(scan_tool.scan_pdf(data))

    def test_the_limits_are_the_numbers_the_owner_confirmed(self):
        self.assertEqual((scan_tool.MAX_TOTAL_OUT, scan_tool.MAX_STREAMS, scan_tool.MAX_STREAM_OUT), (2_500_000_000, 500_000, 2_000_000))

    def test_a_hundred_large_images_are_a_hundred_large_images_and_nothing_else(self):
        found = self.scan(pdf(b"".join(image(b"\0" * BIG) for _ in range(100))))  # 200 million bytes decoded at the 2 MB window
        self.assertEqual(found, {"large_image_streams": 100})

    def test_what_the_scan_decodes_is_not_kept_while_it_works(self):
        import tracemalloc
        data = pdf(b"".join(image(b"\0" * BIG) for _ in range(60)))  # 120 million bytes decoded, one piece at a time
        tracemalloc.start()
        try:
            self.assertEqual(self.scan(data), {"large_image_streams": 60})
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 40_000_000, peak)  # a piece, its unescaped copy and the file; keeping the pieces would be over 120 million

    def test_work_past_the_limit_is_an_incomplete_scan_whatever_brought_it_there(self):
        with mock.patch.object(scan_tool, "MAX_TOTAL_OUT", 10_000_000):
            six = pdf(b"".join(image(b"\0" * BIG) for _ in range(6)))
            self.assertEqual(self.scan(six), {"large_image_streams": 5, "scan_incomplete": 1})
            five = pdf(b"".join(image(b"\0" * BIG) for _ in range(5)))
            self.assertEqual(self.scan(five), {"large_image_streams": 5})  # exactly the limit is not past it
            mixed = pdf(b"".join(flate(b"\0" * 1_900_000) for _ in range(5)) + image(b"\0" * BIG))  # a million bytes left, not two
            self.assertEqual(self.scan(mixed), {"scan_incomplete": 1})
            expanding = pdf(bench_pdf.expanding_streams(300_000)[len(b"%PDF-1.4\n"):])  # about 150 streams that each expand to 2 MB
            self.assertEqual(self.scan(expanding), {"scan_incomplete": 1})

    def test_a_file_with_thousands_of_small_streams_is_not_incomplete_and_one_past_the_stream_limit_is(self):
        many = lambda n: pdf(b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % (10 + k) + zlib.compress(b"x") + b"\nendstream\nendobj\n"
                                      for k in range(n)))
        self.assertEqual(self.scan(many(10_000)), {})
        with mock.patch.object(scan_tool, "MAX_STREAMS", 100):
            self.assertEqual(self.scan(many(100)), {})
            self.assertEqual(self.scan(many(101)), {"scan_incomplete": 1})

    def test_an_image_with_no_type_is_an_image_and_one_with_a_type_other_than_xobject_or_a_container_key_is_not(self):
        late = b"\0" * BIG
        self.assertEqual(self.scan(pdf(image(late, typed=b""))), {"large_image_streams": 1})
        self.assertEqual(self.scan(pdf(image(late, typed=b"/Type /XObject "))), {"large_image_streams": 1})
        for label, typed, keys in (("a form", b"/Type /Form ", b""), ("an object stream", b"/Type /ObjStm ", b""), ("two types", b"/Type /XObject /Type /ObjStm ", b""),
                                   ("a wrong case", b"/Type /xobject ", b""), ("no type but the keys of an object stream", b"", b"/N 1 /First 10 "),
                                   ("no type but the keys of a cross-reference stream", b"", b"/W [1 2 1] /Size 5 "),
                                   ("no type, keys written with escapes", b"", b"/#4E 1 /Fir#73t 10 ")):
            found = self.scan(pdf(image(late, typed=typed, extra=b"/Filter /FlateDecode " + keys)))
            self.assertEqual(found, {"scan_incomplete": 1}, label)

    def test_a_script_in_the_first_part_of_an_image_with_no_type_is_found_and_the_count_is_the_same_as_for_one_with_a_type(self):
        script = b"/S /JavaScript /JS (app.alert(1)) "
        for typed in (b"", b"/Type /XObject "):
            found = self.scan(pdf(image(script + b"\0" * BIG, typed=typed)))
            self.assertEqual(found, {"javascript": 2, "large_image_streams": 1}, typed)

    def paeth_figures(self, n):
        figure = zlib.compress(png_filter(bytes(3000) * 1000, 3000, bpp=3, types=(4,)))  # 3 MB decoded, 1000 rows, every row Paeth
        d = (b"/Type /XObject /Subtype /Image /Width 1000 /Height 1000 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
             b"/DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>")
        return pdf(b"".join(stream_object(d, figure, 10 + k) for k in range(n)))

    def test_the_bytes_a_predictor_is_undone_over_are_a_bound_of_their_own_because_that_work_is_slow(self):
        self.assertEqual(scan_tool.MAX_PREDICTED_BYTES, 20_000_000)  # the work limit alone would allow 2,500 MB of it, a few minutes
        with mock.patch.object(scan_tool, "MAX_PREDICTED_BYTES", 5_000_000):
            self.assertEqual(self.scan(self.paeth_figures(2)), {"large_image_streams": 2})
            # 6 MB are over 5 MB: the third figure's predictor is not undone, what was decoded before it is read, and it is reported as
            # a picture of which only the first part was checked (not as an incomplete scan: honest pictures with PNG predictors are common)
            self.assertEqual(self.scan(self.paeth_figures(3)), {"large_image_streams": 3})
        parms = {"predictor": 12, "colors": 1, "bpc": 8, "columns": 4}
        volume = [10]
        scan_tool._undo_predictor(b"\x01abcd", parms, None, volume)
        self.assertEqual(volume, [5])  # five bytes charged
        with self.assertRaises(scan_tool._Unreadable):
            scan_tool._undo_predictor(b"\x01abcd" * 2, parms, None, volume)

    def test_many_figures_with_a_slow_predictor_cost_a_bounded_time_and_are_reported(self):
        started = time.monotonic()
        found = self.scan(self.paeth_figures(40))  # 80 million bytes to undo at 0.15 s a megabyte, were it not bounded: over 12 s
        took = time.monotonic() - started
        self.assertLess(took, 8, f"{took:.1f} s")
        self.assertEqual(found, {"large_image_streams": 40})

    def test_figures_with_a_predictor_past_the_bytes_the_scan_undoes_are_pictures_and_not_an_incomplete_scan(self):
        figure = zlib.compress(png_filter(bytes(3000) * 316, 3000, bpp=3, types=(0, 1, 2)))  # about 950,000 bytes decoded, cheap rows
        d = (b"/Type /XObject /Subtype /Image /Width 1000 /Height 316 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
             b"/DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>")
        found = self.scan(pdf(b"".join(stream_object(d, figure, 10 + k) for k in range(25))))  # 23.7 million bytes, 20 million are undone
        self.assertNotIn("scan_incomplete", found)
        self.assertGreater(found.get("large_image_streams", 0), 0)
        # and an object stream behind the same predictor, past the budget, is still reported as incomplete: it is not a picture
        with mock.patch.object(scan_tool, "MAX_PREDICTED_BYTES", 10):
            body = stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 8 >>",
                                 zlib.compress(png_filter(b"abcdefgh" * 4, 8, types=(0,))))
            self.assertEqual(self.scan(pdf(body)), {"scan_incomplete": 1})

    def test_the_rows_budget_is_spent_the_same_way_a_picture_is_a_picture_and_an_object_stream_is_incomplete(self):
        with mock.patch.object(scan_tool, "MAX_PREDICTED_ROWS", 1500):  # 667 rows of 3-byte pixels (a 2 MB window) cost 2001 passes
            self.assertEqual(self.scan(self.paeth_figures(1)), {"large_image_streams": 1})
            body = stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /Columns 1000 >>",
                                 zlib.compress(png_filter(bytes(3000) * 1000, 3000, bpp=3, types=(4,))))
            self.assertEqual(self.scan(pdf(body)), {"scan_incomplete": 1})

    def test_the_input_of_every_layer_after_the_first_is_charged_because_it_is_decoded_though_it_may_give_nothing(self):
        # layer one turns 5 KB into two million bytes of empty deflate blocks, layer two reads them and returns nothing (0.1 s a stream)
        two = bench_pdf.nested_empty_blocks(10)
        with mock.patch.object(scan_tool, "MAX_TOTAL_OUT", 100_000_000):  # a stream is charged 20 units for each of 1.9 million bytes
            self.assertEqual(self.scan(two), {"scan_incomplete": 1})
            one = bench_pdf.nested_empty_blocks(2)
            self.assertEqual(self.scan(one), {})  # two of them fit
        self.assertEqual(self.scan(bench_pdf.nested_empty_blocks(2)), {})
        self.assertEqual(scan_tool.LAYER_UNITS, 20)

    def test_a_layer_is_charged_once_a_deflate_has_come_before_it_and_not_before(self):
        # only a deflate can turn a small blob into a large input: text filters first (ASCII85, hex) are bounded by the blob itself
        script = b"1 0 " + SCRIPT
        a85 = base64.a85encode(zlib.compress(script)) + b"~>"
        cost = lambda blob, names: (lambda layers: (scan_tool._decode_chain(blob, names, 2_000_000, layers=layers), layers[0])[1])([0])
        self.assertEqual(cost(a85, [b"ASCII85Decode", b"FlateDecode"]), 0)  # the common old chain: the flate reads what the blob decoded to
        self.assertEqual(cost(a85.hex().encode() + b">", [b"ASCIIHexDecode", b"ASCII85Decode", b"FlateDecode"]), 0)
        twice = zlib.compress(zlib.compress(script))
        self.assertEqual(cost(twice, [b"FlateDecode", b"FlateDecode"]), 20 * len(zlib.compress(script)))
        text = base64.a85encode(zlib.compress(script)) + b"~>"
        after = zlib.compress(text)  # a flate, then ASCII85, then flate: the middle layer's input and the last one's are both charged
        self.assertEqual(cost(after, [b"FlateDecode", b"ASCII85Decode", b"FlateDecode"]), 20 * len(text) + 20 * len(zlib.compress(script)))
        self.assertEqual(cost(zlib.compress(script), [b"FlateDecode"]), 0)  # one layer: the blob is bounded by the file

    def test_seven_hundred_two_layer_streams_in_four_megabytes_are_stopped_in_time_and_reported(self):
        data = bench_pdf.nested_empty_blocks(700)  # 72 seconds when the layers were not charged
        started = time.monotonic()
        found = self.scan(data)
        took = time.monotonic() - started
        self.assertLess(took, 20, f"{took:.1f} s")
        self.assertEqual(found, {"scan_incomplete": 1})

    def test_a_scan_that_has_run_longer_than_its_deadline_stops_between_streams_and_says_so(self):
        self.assertEqual(scan_tool.MAX_SECONDS, 25)
        many = pdf(b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % (10 + k) + zlib.compress(b"x") + b"\nendstream\nendobj\n" for k in range(50)))
        self.assertEqual(self.scan(many), {})
        with mock.patch.object(scan_tool, "MAX_SECONDS", -1):  # already past it when the first stream is reached
            self.assertEqual(self.scan(many), {"scan_incomplete": 1})
            self.assertEqual(self.scan(CLEAN_PDF), {})  # a file with no stream has nothing to stop

    def test_a_chain_of_many_filters_is_refused_because_each_layer_costs_and_only_the_last_is_charged(self):
        self.assertEqual(scan_tool.MAX_FILTERS, 8)
        script = SCRIPT * 2
        layers = script
        for _ in range(8):
            layers = zlib.compress(layers)
        eight = pdf(stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter [" + b" /Fl" * 8 + b" ]", layers))
        self.assertGreater(self.scan(eight).get("javascript", 0), 0)  # eight layers are read through
        layers = zlib.compress(layers)
        nine = pdf(stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter [" + b" /Fl" * 9 + b" ]", layers))
        self.assertEqual(self.scan(nine), {"scan_incomplete": 1})  # nine are not decoded at all
        thousands = pdf(stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter [" + b" /Fl" * 4000 + b" ]", layers))
        self.assertEqual(self.scan(thousands), {"scan_incomplete": 1})

    def test_the_matches_in_a_piece_are_counted_without_being_kept(self):
        import tracemalloc
        data = pdf(b"/JS " * 3_000_000)  # 12 MB, three million matches: a list of them would be some 150 MB
        tracemalloc.start()
        try:
            self.assertEqual(self.scan(data), {"javascript": 3_000_000})
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 60_000_000, peak)

    def test_work_is_counted_in_bytes_and_more_for_the_bytes_that_are_slow_to_read(self):
        self.assertEqual(scan_tool._work(b"abc"), 3)
        self.assertEqual(scan_tool._work(b"#41"), 3 + 135)  # an escape is unescaped one at a time (and may spell a slash)
        self.assertEqual(scan_tool._work(b"/JS"), 3 + 35)  # every pattern begins with a slash and each match is collected
        self.assertEqual(scan_tool._work(b""), 0)
        self.assertEqual(scan_tool._work(b"/JS", True), 3 + 70)  # pixels are read twice, to place each match: a slash costs twice as much
        self.assertEqual(scan_tool._work(b"abc", True), 3)

    def test_streams_of_escapes_cost_a_bounded_time_because_the_work_limit_counts_them_heavily(self):
        dense = zlib.compress(b"#41" * 666_666)  # 2 MB that is all escapes, about 0.17 s to read
        data = pdf(b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % (10 + k) + dense + b"\nendstream\nendobj\n" for k in range(60)))
        started = time.monotonic()
        found = self.scan(data)
        took = time.monotonic() - started
        self.assertLess(took, 15, f"{took:.1f} s")  # without the weight: 60 x 0.17 s, and a hostile file could have a thousand
        self.assertEqual(found, {"scan_incomplete": 1})  # 36 of them fill the 2,500 million units

    def test_pictures_made_of_matches_cost_a_bounded_time_with_or_without_the_shape_of_a_use(self):
        for content, kind in ((b"/JS " * 500_000, "javascript"), (b"/JS/JS" * 333_333, "pattern_in_binary_data")):
            dense = zlib.compress(content)
            data = pdf(b"".join(image(dense, compress=False, typed=b"") for _ in range(40)))  # each is 2 MB of matches once decoded
            with mock.patch.object(scan_tool, "MAX_TOTAL_OUT", 800_000_000):
                # a piece is 37 to 48 million units (the slashes count twice in a picture), so about 20 of them fill this; at the cost of a
                # page, 19 to 25 million, all forty would have fitted
                started = time.monotonic()
                found = self.scan(data)
                took = time.monotonic() - started
            self.assertLess(took, 14, f"{kind}: {took:.1f} s")
            self.assertEqual(found.get("scan_incomplete"), 1, kind)
            self.assertGreater(found.get(kind, 0), 500_000, kind)

    def test_streams_made_of_matches_cost_a_bounded_time_and_every_match_is_counted(self):
        dense = zlib.compress(b"/JS " * 500_000)  # 2 MB, a match in every four bytes
        data = pdf(b"".join(b"%d 0 obj\n<< /Filter /FlateDecode >>\nstream\n" % (10 + k) + dense + b"\nendstream\nendobj\n" for k in range(10)))
        started = time.monotonic()
        found = self.scan(data)
        took = time.monotonic() - started
        self.assertLess(took, 8, f"{took:.1f} s")
        self.assertEqual(found, {"javascript": 5_000_000})

    def test_the_bytes_before_a_predictor_are_still_read_when_the_predictor_is_not_undone(self):
        with mock.patch.object(scan_tool, "MAX_PREDICTED_BYTES", 10):
            script = b"/S /JavaScript /JS (app.alert(1)) "
            data = zlib.compress(png_filter(script + bytes(100), len(script) + 100, types=(0,)))
            body = stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns %d >>" % (len(script) + 100), data)
            found = self.scan(pdf(body))
            self.assertEqual(found.get("scan_incomplete"), 1)  # not undone: said so
            self.assertEqual(found.get("javascript"), 2)  # and what was decoded before the predictor is read

    def test_a_hundred_thousand_tiny_streams_cost_in_proportion_to_their_number(self):
        data = bench_pdf.tiny_streams(15_000_000, seed=2)  # about 80,000 streams
        started = time.monotonic()
        self.scan(data)
        took = time.monotonic() - started
        self.assertLess(took, 10, f"{took:.1f} s")
        # not asserted: whether it is incomplete. The generator's streams hold random bytes, and about one in sixteen thousand begins
        # like another zlib stream, which the scan reports as compressed again inside (a rule older than the limits)


class BinaryTallyTest(unittest.TestCase):
    """_tally_binary gives the names it always gave, and costs about what the plain tally costs (a look-behind at the start of a
    regex makes the engine try every position: about a hundred times the plain cost, so the shape is checked on each match instead)."""

    @staticmethod
    def reference(haystack):
        """The first definition: a regex with the shape in it, run beside the plain one."""
        import re
        padded = scan_tool._PAD + haystack + scan_tool._END
        counts, other = {}, 0
        for kind, pattern in scan_tool._PATTERNS.items():
            strong = re.compile(rb"(?<=[\t\n\x0c\r\x20-\x7e]{12})" + pattern + rb"(?=[\t\n\x0c\r (<])")
            every = len(re.findall(pattern, padded))
            shaped = len(strong.findall(padded))
            counts[kind] = shaped
            other += every - shaped
        return {k: v for k, v in counts.items() if v}, other

    def tally(self, haystack):
        counts, binary = {kind: 0 for kind in scan_tool._PATTERNS}, [0]
        scan_tool._tally_binary(counts, binary, haystack)
        return {k: v for k, v in counts.items() if v}, binary[0]

    def test_the_names_are_those_of_the_first_definition_on_random_bytes(self):
        rng = random.Random(7)
        words = [b"/JS", b"/JavaScript", b"/Launch", b"/EmbeddedFile", b"/EmbeddedFiles", b"/XFA", b"/GoToR", b"/RichMedia",
                 b"/Encrypt", b"/Launcher", b"/JS7", b" ", b"(", b"<", b"\n", b"\x00", b"\xff", b"/", b"#", b"a", b"abcdefghijkl"]
        for _ in range(3000):
            piece = b"".join(rng.choice(words) for _ in range(rng.randint(0, 40)))
            self.assertEqual(self.tally(piece), self.reference(piece), piece)

    def test_a_name_at_either_end_of_the_data_is_judged_as_before(self):
        for piece in (b"/JS", b"/JS ", b" /JS", b"abcdefghijkl/JS ", b"abcdefghijk/JS ", b"/Launch", b"/Launch/Launch "):
            self.assertEqual(self.tally(piece), self.reference(piece), piece)

    def test_it_costs_about_the_plain_tally_not_a_hundred_times_it(self):
        piece = (b"a" * 1000 + b" /JS /Launch /EmbeddedFile /XFA /GoToR /RichMedia /Encrypt ") * 10000  # all seven kinds, 10 MB
        started = time.monotonic()
        self.tally(piece)
        self.assertLess(time.monotonic() - started, 1.0)  # the first definition took more than 2.5 s here


class UnescapeChunksTest(unittest.TestCase):
    """_unescape_names works in pieces so that the list a substitution keeps for each escape is the size of a piece, not of the file.
    A piece is cut only before a `#`, which starts a match or fails to, whatever is before it, so the result is that of the whole."""

    @staticmethod
    def whole(data):
        import re
        return re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), data)

    def test_the_result_is_that_of_the_whole_for_every_piece_size_on_random_bytes(self):
        rng = random.Random(11)
        words = [b"#", b"#4", b"#41", b"#2F", b"#2FJS ", b"#zz", b"##", b"#1", b"4", b"1", b"F", b"/JS", b" ", b"\xff", b"a", b"G"]
        for _ in range(1500):
            data = b"".join(rng.choice(words) for _ in range(rng.randint(0, 60)))
            for size in (4, 5, 7, 16):
                with mock.patch.object(scan_tool, "_CHUNK", size):
                    self.assertEqual(scan_tool._unescape_names(data), self.whole(data), (size, data))

    def test_an_escape_is_not_cut_wherever_the_piece_ends(self):
        for size in (4, 5, 6, 7, 8):
            for before in range(0, 12):
                data = b"a" * before + b"#2FJS" + b"b" * 9 + b"#41#42#4#4G#"
                with mock.patch.object(scan_tool, "_CHUNK", size):
                    self.assertEqual(scan_tool._unescape_names(data), self.whole(data), (size, before))

    def test_a_long_run_of_marks_and_a_data_without_any_are_handled(self):
        with mock.patch.object(scan_tool, "_CHUNK", 4):
            for data in (b"#" * 50, b"#4" * 50, b"#41" * 50, b"plain text with no mark at all", b""):
                self.assertEqual(scan_tool._unescape_names(data), self.whole(data), data)

    def test_the_memory_held_is_that_of_a_piece_not_of_a_million_escapes(self):
        import tracemalloc
        data = b"#41" * 3_000_000
        tracemalloc.start()
        try:
            out = scan_tool._unescape_names(data)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(out, b"A" * 3_000_000)
        self.assertLess(peak, 60_000_000)  # a piece of 1 MB holds about 35 MB; the substitution over the whole kept about 270 MB here

    def test_ascii85_and_hex_output_is_cut_at_the_limit_like_a_deflate_output(self):
        text = b"#41" * 400_000  # 1.2 MB
        for name, blob in ((b"ASCII85Decode", base64.a85encode(text) + b"~>"), (b"ASCIIHexDecode", text.hex().encode() + b">")):
            out, state = scan_tool._decode_chain(blob, [name], 100_000)
            self.assertEqual((len(out), state), (100_000, "limit"), name)
            self.assertEqual(out, text[:100_000], name)
            out, state = scan_tool._decode_chain(blob, [name], 2_000_000)
            self.assertEqual((out, state), (text, "ok"), name)
            out, state = scan_tool._decode_chain(blob, [name], len(text))
            self.assertEqual((out, state), (text, "ok"), name)  # exactly the limit is not past it
            out, state = scan_tool._decode_chain(blob, [name], len(text) - 1)
            self.assertEqual((out, state), (text[:-1], "limit"), name)  # and one byte past it is


class PlacesTest(unittest.TestCase):
    """Where a match sits decides its name. Binary places: the raw and decoded bytes of image-shaped streams, the raw bytes of image
    codecs, and the raw bytes of any stream the scan decoded. Everything else is a text place. A match in a text place, or in a binary
    place with the shape of a use (twelve printable bytes before it, a byte after it that can begin a value), is its own kind; any
    other match in a binary place is pattern_in_binary_data. Nothing is dropped."""

    HIGH = bytes(range(0x80, 0x90))  # not printable: bytes that no syntax has in front of a name
    KINDS = {"javascript": b"/JavaScript ", "embedded_files": b"/EmbeddedFile ", "launch_action": b"/Launch ", "xfa_forms": b"/XFA ",
             "external_actions": b"/SubmitForm ", "rich_media": b"/RichMedia ", "encrypted": b"/Encrypt "}

    def scan(self, data):
        return kinds(scan_tool.scan_pdf(data))

    def test_the_new_kind_has_a_sentence_that_says_what_it_is(self):
        self.assertIn("pattern_in_binary_data", scan_tool.KINDS)
        self.assertIn("coincidence", scan_tool.KINDS["pattern_in_binary_data"])

    def test_three_bytes_in_the_compressed_data_of_a_large_image_are_not_a_script(self):
        pixels = self.HIGH + b"/JS(" + self.HIGH + bytes(BIG)
        found = self.scan(pdf(image(pixels, typed=b"")))
        self.assertEqual(found, {"large_image_streams": 1, "pattern_in_binary_data": 1})  # the decoded pixels; the compressed bytes hold none
        stored = pdf(image(zlib.compress(pixels, 0), compress=False, typed=b"/Type /XObject "))  # stored blocks: the bytes are in the file as they are
        self.assertEqual(self.scan(stored), {"large_image_streams": 1, "pattern_in_binary_data": 2})  # in the raw bytes and in the pixels

    def test_a_picture_that_spells_the_pattern_is_not_a_script_with_or_without_a_type(self):
        flat = b"\x2fJS" * 100 + b"\xff" * 50  # the colour #2F4A53 in a flat region, then another colour
        for typed in (b"", b"/Type /XObject "):
            found = self.scan(pdf(image(flat + bytes(BIG), typed=typed)))
            self.assertEqual(found, {"large_image_streams": 1, "pattern_in_binary_data": 100}, typed)

    def test_the_same_bytes_in_a_text_place_are_a_script(self):
        script = b"<< /S /JavaScript /JS (app.alert(1)) >>"
        places = {
            "outside the streams": pdf(b"7 0 obj\n" + script + b"\nendobj\n"),
            "a stream dictionary": pdf(stream_object(b"/Note (/JS (x)) /Filter /FlateDecode", zlib.compress(b"hello"))),
            "an unfiltered stream": pdf(stream_object(b"/Length 40", script)),
            "the decoded content of an object stream": pdf(stream_object(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode", zlib.compress(b"1 0 " + script))),
            "the decoded content of a plain stream": pdf(stream_object(b"/Filter /FlateDecode", zlib.compress(self.HIGH + b"/JS (x)"))),
            "a stream with a filter the scan does not read": pdf(stream_object(b"/Filter /LZWDecode", self.HIGH + b"/JS (x)")),
        }
        for label, data in places.items():
            self.assertGreater(self.scan(data).get("javascript", 0), 0, label)
            self.assertNotIn("pattern_in_binary_data", self.scan(data), label)

    def test_a_real_action_in_a_binary_place_keeps_its_own_kind_because_it_has_the_shape_of_a_use(self):
        script = b"<< /S /JavaScript /JS (app.alert(1)) >>"
        places = {
            "the data of an image codec stream": pdf(stream_object(b"/Filter /DCTDecode", self.HIGH + script)),
            "an unfiltered image": pdf(image(self.HIGH + script, extra=b"", compress=False)),
            "a deflated image": pdf(image(self.HIGH + script + bytes(100))),
            "a stored-deflate image": pdf(image(zlib.compress(self.HIGH + script, 0), compress=False)),
        }
        for label, data in places.items():
            found = self.scan(data)
            self.assertGreater(found.get("javascript", 0), 0, f"{label}: {found}")

    def test_a_real_action_in_a_binary_place_without_the_shape_of_a_use_is_reported_under_the_weaker_name_and_never_silent(self):
        junk = self.HIGH + b"/JavaScript (x)"  # sixteen bytes that are not syntax right in front
        places = {
            "the data of an image codec stream": pdf(stream_object(b"/Filter /DCTDecode", junk)),
            "an unfiltered image": pdf(image(junk, extra=b"", compress=False)),
            "a deflated image": pdf(image(junk + bytes(100))),
        }
        for label, data in places.items():
            found = self.scan(data)
            self.assertEqual(found.get("pattern_in_binary_data"), 1, f"{label}: {found}")
            self.assertNotIn("javascript", found, label)

    def test_the_compressed_bytes_of_a_stream_the_scan_decoded_are_not_text(self):
        # the last two bytes of the content are "/J" and the first byte of the stream's checksum is "S": the three bytes are in the file
        # as it is (the block is stored), though the content holds no "/JS" and the stream is not a picture. Found by a search, once.
        content = bytes.fromhex("4062d4da30fb8abf019e6f659fa05e6168ba115b0c09d80ca5aa45371206fa6cfb623780e5a4aa3ac89877329f2741df5fd0095d9b4c103f61ed2f4a")
        compressed = zlib.compress(content, 6)
        self.assertIn(b"/JS", compressed)
        self.assertNotIn(b"/JS", content)
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /FlateDecode", compressed))), {"pattern_in_binary_data": 1})
        # and it is only the compressed bytes: the same three bytes in what the stream decodes to are a text place
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /FlateDecode", zlib.compress(b"a" * 12 + b"/JS (x)")))), {"javascript": 1})

    def test_every_pattern_follows_the_same_rule(self):
        for kind, name in self.KINDS.items():
            weak = self.scan(pdf(stream_object(b"/Filter /DCTDecode", self.HIGH + name)))
            self.assertEqual(weak, {"pattern_in_binary_data": 1}, kind)
            strong = self.scan(pdf(stream_object(b"/Filter /DCTDecode", b"<< /S /X " + name + b">>")))
            self.assertEqual(strong, {kind: 1}, kind)
            text = self.scan(pdf(stream_object(b"/Length 20", self.HIGH + name)))
            self.assertEqual(text, {kind: 1}, kind)

    def test_the_shape_of_a_use_is_twelve_printable_bytes_before_and_a_value_start_after(self):
        before = lambda b: self.scan(pdf(stream_object(b"/Filter /DCTDecode", b + b"/JS (x)")))
        self.assertEqual(before(b"a" * 12), {"javascript": 1})
        self.assertEqual(before(b"\x80" + b"a" * 11), {"pattern_in_binary_data": 1})  # the twelfth byte back is not printable
        self.assertEqual(before(b"\x80" + b"a" * 12), {"javascript": 1})  # only twelve are looked at
        self.assertEqual(before(b""), {"javascript": 1})  # the start of the data counts as printable
        after = lambda b: self.scan(pdf(stream_object(b"/Filter /DCTDecode", b"a" * 12 + b"/JS" + b)))
        for ok in (b" x", b"\nx", b"\rx", b"\tx", b"(x", b"<x", b"\x0cx"):
            self.assertEqual(after(ok), {"javascript": 1}, ok)
        for no in (b"/x", b"\x00x", b"\xffx", b">x"):  # a slash, a null, a high byte, a closing bracket
            self.assertEqual(after(no), {"pattern_in_binary_data": 1}, no)
        self.assertEqual(after(b""), {"javascript": 1})  # the data of a stream ends with the line end before endstream: white space
        for not_a_match in (b"Ax", b"7x", b"#41"):  # these continue the name: it is another name, and not a match of any kind
            self.assertEqual(after(not_a_match), {}, not_a_match)

    def test_neighbouring_streams_do_not_lend_each_other_a_shape(self):
        raw = lambda number, data: b"%d 0 obj\n<< /Filter /DCTDecode >>\nstream\n" % number + data + b"endstream\nendobj\n"  # no line end before endstream
        # a name that ends the data of one stream (with printable bytes before it), right before another whose data begins with white space
        found = self.scan(pdf(raw(5, b"a" * 12 + b"/JS") + raw(6, b" x" + self.HIGH)))
        self.assertEqual(found, {"pattern_in_binary_data": 1})
        # a name at the start of a stream is printable-before even though the stream before it ends in bytes that are not
        found = self.scan(pdf(raw(5, self.HIGH) + raw(6, b"/JS (x)")))
        self.assertEqual(found, {"javascript": 1})

    def test_a_stream_that_is_not_decoded_to_its_end_or_is_skipped_is_a_text_place(self):
        script = b"<< /S /JavaScript /JS (x) >>"
        # a deflate stream with a real object after its end: the decode is refused (bad), so its bytes are text, kept at full strength
        after_the_end = zlib.compress(b"x") + self.HIGH + script
        found = self.scan(pdf(stream_object(b"/Filter /FlateDecode", after_the_end)))
        self.assertGreater(found.get("javascript", 0), 0)
        self.assertNotIn("pattern_in_binary_data", found)
        self.assertIn("scan_incomplete", found)
        # a stream the scan never reached (out of time) keeps its bytes in the text: even a match that would be weak in a binary place
        weak = pdf(stream_object(b"/Filter /DCTDecode", self.HIGH + b"/JavaScript (x)"))
        self.assertEqual(self.scan(weak), {"pattern_in_binary_data": 1})
        with mock.patch.object(scan_tool, "MAX_SECONDS", -1):
            self.assertEqual(self.scan(weak), {"javascript": 1, "scan_incomplete": 1})

    def test_the_shape_is_judged_on_the_text_after_escapes_are_undone(self):
        # what a viewer reads: a name written with escapes is the name, and bytes written with escapes are the bytes
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /DCTDecode", b"#80" * 12 + b"/JS (x)"))), {"pattern_in_binary_data": 1})
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /DCTDecode", b"#41" * 12 + b"/JS (x)"))), {"javascript": 1})

    def test_a_match_spelled_with_escapes_is_placed_the_same_way(self):
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /DCTDecode", self.HIGH + b"/J#53 (x)"))), {"pattern_in_binary_data": 1})
        self.assertEqual(self.scan(pdf(stream_object(b"/Filter /DCTDecode", b"a" * 12 + b"/J#53 (x)"))), {"javascript": 1})

    def test_the_counts_of_a_file_with_no_binary_place_are_what_they_were(self):
        data = pdf(b"1 0 obj << /S /JavaScript /JS (x) /A /Launch >> endobj\n" + stream_object(b"/Length 5", b"/XFA ") + flate(b"/RichMedia /Encrypt"))
        self.assertEqual(self.scan(data), {"encrypted": 1, "javascript": 2, "launch_action": 1, "xfa_forms": 1, "rich_media": 1})

    def test_pieces_of_binary_data_full_of_matches_cost_a_bounded_time(self):
        for label, content in (("with the shape of a use", b"/JS " * 500_000), ("without", b"/JS/JS" * 333_333)):
            data = pdf(b"".join(image(content, typed=b"") for _ in range(8)))
            started = time.monotonic()
            found = self.scan(data)
            took = time.monotonic() - started
            self.assertLess(took, 12, f"{label}: {took:.1f} s")
            self.assertEqual(found.get("scan_incomplete"), None, label)
            self.assertGreater(sum(found.get(k, 0) for k in ("javascript", "pattern_in_binary_data")), 1_000_000, label)


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
