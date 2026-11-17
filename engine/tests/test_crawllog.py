"""The crawl's log (`kb/crawllog.py`, Increment C of the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`).

One JSON line per action in `<index root>/crawl/log/crawl-YYYY-MM-DD.jsonl` (the UTC day of the line), written with one `O_APPEND` write, in the spec's fields, steps and outcomes. Every test uses a temporary index root.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawllog`."""
import contextlib
import datetime
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, crawllog

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 16, 12, 30, 5, tzinfo=UTC)
FIELDS = ["ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds"]
SPEC_STEPS = ["run_start", "refuse", "list_update", "discover", "enqueue", "block", "fetch", "capture", "scan", "hold", "convert", "index", "judge", "reject", "card", "propose", "move", "fail",
              "breaker", "stop", "run_end", "report"]
SPEC_OUTCOMES = ["ok", "skipped", "rejected", "failed", "blocked", "held", "refused", "tripped"]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.index = os.path.join(os.path.realpath(self._tmp.name), "index")
        os.mkdir(self.index)
        self.addCleanup(self._unlock)
        self.log = crawllog.Log(self.index, "run-1")

    def _unlock(self):
        for folder, _names, files in os.walk(self.index):
            os.chmod(folder, 0o700)

    def path(self, day="2026-11-16"):
        return os.path.join(self.index, "crawl", "log", f"crawl-{day}.jsonl")

    def lines(self, day="2026-11-16"):
        with open(self.path(day), "rb") as f:
            data = f.read()
        self.assertTrue(data.endswith(b"\n") or data == b"")
        return [json.loads(line) for line in data.decode("utf-8").splitlines()]


class Form(Case):
    def test_the_steps_and_outcomes_are_exactly_the_specs(self):
        self.assertEqual(list(crawllog.STEPS), SPEC_STEPS)
        self.assertEqual(list(crawllog.OUTCOMES), SPEC_OUTCOMES)
        self.assertEqual(crawllog.FIELDS, tuple(FIELDS))

    def test_a_line_has_every_field_in_the_same_order_and_the_time_in_utc(self):
        self.log.write("fetch", "ok", now=NOW, candidate=7, book="b-1", host="example.org", reason="fine", n=1234, seconds=1.5)
        self.log.write("run_start", "ok", now=NOW)
        with open(self.path(), "rb") as f:
            raw = f.read().decode("utf-8").splitlines()
        self.assertEqual([list(json.loads(line)) for line in raw], [FIELDS, FIELDS])
        first, second = (json.loads(line) for line in raw)
        self.assertEqual(first, {"ts": "2026-11-16T12:30:05Z", "run": "run-1", "step": "fetch", "outcome": "ok", "candidate": 7, "book": "b-1", "host": "example.org", "reason": "fine", "n": 1234,
                                 "seconds": 1.5})
        self.assertEqual({k: v for k, v in second.items() if v is not None}, {"ts": "2026-11-16T12:30:05Z", "run": "run-1", "step": "run_start", "outcome": "ok"})

    def test_every_step_and_every_outcome_is_taken_and_nothing_else(self):
        for step in SPEC_STEPS:
            self.log.write(step, "ok", now=NOW)
        for outcome in SPEC_OUTCOMES:
            self.log.write("fetch", outcome, now=NOW)
        self.assertEqual(len(self.lines()), len(SPEC_STEPS) + len(SPEC_OUTCOMES))
        for bad in ("start", "FETCH", "", None, 5, "fetch ", "run_start\n"):
            with self.assertRaises(KbError):
                self.log.write(bad, "ok", now=NOW)
            with self.assertRaises(KbError):
                self.log.write("fetch", bad, now=NOW)
        self.assertEqual(len(self.lines()), len(SPEC_STEPS) + len(SPEC_OUTCOMES))

    def test_an_unknown_field_is_refused(self):
        with self.assertRaises(TypeError):
            self.log.write("fetch", "ok", now=NOW, address="https://example.org/")

    def test_the_day_of_the_file_is_the_utc_day_of_the_line(self):
        late = datetime.datetime(2026, 11, 16, 23, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))   # 04:30 UTC on the 17th
        self.log.write("run_start", "ok", now=late)
        self.assertEqual(os.listdir(os.path.dirname(self.path())), ["crawl-2026-11-17.jsonl"])
        self.assertEqual(self.lines("2026-11-17")[0]["ts"], "2026-11-17T04:30:00Z")
        self.log.write("run_end", "ok", now=NOW)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path()))), ["crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"])

    def test_a_time_without_a_zone_is_refused_and_the_clock_is_used_when_none_is_given(self):
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now=datetime.datetime(2026, 11, 16, 12, 0))
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now="2026-11-16")
        clocked = crawllog.Log(self.index, "run-2", clock=lambda: NOW)
        clocked.write("run_start", "ok")
        self.assertEqual(self.lines()[0]["run"], "run-2")
        real = crawllog.Log(self.index, "run-3")
        real.write("run_start", "ok")
        self.assertRegex(json.loads(open(os.path.join(self.index, "crawl", "log", sorted(os.listdir(os.path.join(self.index, "crawl", "log")))[-1])).read().splitlines()[-1])["ts"],
                         r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_run_name_is_checked_and_a_new_one_is_a_utc_stamp_and_random_letters(self):
        for bad in ("", "a b", "a\nb", "x" * 65, None, 5, "é", "a/b"):
            with self.assertRaises(KbError):
                crawllog.Log(self.index, bad)
        self.assertRegex(crawllog.new_run_id(NOW), r"^20261116T123005Z-[0-9a-f]{6}$")
        self.assertNotEqual(crawllog.new_run_id(NOW), crawllog.new_run_id(NOW))
        crawllog.Log(self.index, crawllog.new_run_id(NOW))

    def test_the_numbers_are_checked(self):
        for kwargs in ({"candidate": True}, {"candidate": "7"}, {"candidate": -1}, {"candidate": 2**63}, {"candidate": 1.5}, {"n": True}, {"n": -1}, {"n": 1.5}, {"n": "5"}, {"n": 2**63},
                       {"seconds": -0.1}, {"seconds": math.nan}, {"seconds": math.inf}, {"seconds": True}, {"seconds": "1"}, {"seconds": 10**400}, {"seconds": 10**10}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(KbError):
                    self.log.write("fetch", "ok", now=NOW, **kwargs)
        self.log.write("fetch", "ok", now=NOW, candidate=0, n=0, seconds=0)
        self.log.write("fetch", "ok", now=NOW, seconds=1.23456789)
        self.assertEqual([line["seconds"] for line in self.lines()], [0, 1.235])
        self.assertEqual(self.lines()[0]["candidate"], 0)
        self.assertEqual(self.lines()[0]["n"], 0)

    def test_strings_are_cleaned_of_control_and_direction_characters_and_cut(self):
        self.log.write("fail", "failed", now=NOW, reason="a\x1b[31m red\r\nline\u202e reversed\u200b\u2066 end", book="b\x00\x07k", host="Ex\u202eample.org")
        line = self.lines()[0]
        self.assertEqual(line["reason"], "a[31m red line reversed end")
        self.assertEqual(line["book"], "bk")
        self.assertEqual(line["host"], "Example.org")
        raw = open(self.path(), "rb").read()
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertNotIn(b"\x1b", raw)
        self.log.write("fail", "failed", now=NOW, reason="ww " * 2000, book="b" * 500, host="h" * 500)
        long = self.lines()[1]
        self.assertEqual((len(long["reason"]), len(long["book"]), len(long["host"])), (500, 120, 253))
        self.assertEqual(crawllog.LIMITS, {"reason": 500, "book": 120, "host": 253})
        self.log.write("fail", "failed", now=NOW, reason="", book=None, host="   ")
        self.assertEqual({k: v for k, v in self.lines()[2].items() if k in ("reason", "book", "host")}, {"reason": None, "book": None, "host": None})

    def test_text_that_is_not_a_string_is_refused(self):
        for bad in (5, b"x", ["a"], {"a": 1}, 1.5, True):
            with self.assertRaises(KbError):
                self.log.write("fail", "failed", now=NOW, reason=bad)


class Secrets(Case):
    def test_a_field_that_looks_like_a_header_or_a_key_is_refused_and_nothing_is_written(self):
        for text in ("Auth-Key: abcdef", "auth-key=abcdef", "Authorization: Bearer abc", "authorization:x", "Cookie: a=b", "set-cookie: a=b", "X-API-Key: k", "api_key=zzz", "apikey: z",
                     "Proxy-Authorization: Basic abc", "{'Auth-Key': 'abc'}", '"Authorization": "Basic xyz"', "['Cookie': 'sid=1']", "password=hunter2", "got a token: abc", "Bearer abcdefgh12345"):
            for field in ("reason", "book", "host"):
                with self.subTest(text=text[:20], field=field):
                    with self.assertRaises(KbError) as caught:
                        self.log.write("fail", "failed", now=NOW, **{field: text})
                    self.assertNotIn(text[:12], str(caught.exception))
        for text in ("see " + "Q1b2C3d4" * 6, "k" * 40, "a-b_c" * 10, "Zz9+/=" * 8):
            for field in ("reason", "book"):
                with self.subTest(text=text[:20], field=field):
                    with self.assertRaises(KbError):
                        self.log.write("fail", "failed", now=NOW, **{field: text})
        self.assertFalse(os.path.exists(self.path()))

    def test_ordinary_text_with_the_same_words_and_hex_digests_and_long_hostnames_are_taken(self):
        for text in ("the key of the table", "a token of thanks", "cookie banner found", "authorization needed from the site", "digest " + "0" * 32 + " ok", "sha " + "ab12" * 16,
                     "the password page returned 403", "x" * 39):
            self.log.write("fail", "failed", now=NOW, reason=text)
        self.log.write("fetch", "ok", now=NOW, host=".".join(["a" * 63] * 3 + ["example.org"])[:253])
        self.assertEqual(len(self.lines()), 9)

    def test_a_secret_the_caller_names_is_refused_wherever_it_is_and_in_any_field(self):
        guarded = crawllog.Log(self.index, "run-1", secrets=["s3cr3t-value", ""])
        for field in ("reason", "book", "host"):
            with self.assertRaises(KbError):
                guarded.write("fail", "failed", now=NOW, **{field: "before s3cr3t-value after"})
        with self.assertRaises(KbError):
            guarded.write("fail", "failed", now=NOW, reason="S3CR3T-VALUE")        # a different case is found too
        guarded.write("fail", "failed", now=NOW, reason="nothing here")
        self.assertEqual(len(self.lines()), 1)
        for bad in ("a string", 5, [5]):
            with self.assertRaises(KbError):
                crawllog.Log(self.index, "run-1", secrets=bad)

    def test_a_secret_split_by_a_hidden_character_is_still_found(self):
        guarded = crawllog.Log(self.index, "run-1", secrets=["s3cr3t-value"])
        with self.assertRaises(KbError):
            guarded.write("fail", "failed", now=NOW, reason="s3cr3t\u200b-value")
        with self.assertRaises(KbError):
            guarded.write("fail", "failed", now=NOW, reason="s3cr3t\n-value")


class Shapes(Case):
    """Finding F7: credential shapes the security review found in the log's net, and ordinary text that must not be caught."""

    REFUSED = ("https://s3.example.org/f?X-Amz-Signature=abcdef0123456789abcdef", "https://c.example.org/f?X-Goog-Signature=abcdef0123456789", "https://s3.example.org/f?x-amz-security-token=abcdefgh",
               "secret_key=abc123def", "SECRET-KEY: abc", "AWS_SECRET_ACCESS_KEY=abcdef", "access_key=abcd", "access-key: abcd", "private_key=abcd", "client_secret=abcd", "pwd=hunter2",
               "auth_token=abcd1234", "access_token: abcd1234", "refresh_token=abcd1234", "Basic dXNlcjpwYXNzd29yZA==", "basic QWxhZGRpbjpvcGVuIHNlc2FtZQ", "https://user:pass@example.org/x",
               "ftp://admin:s3cret@host/", "https://example.org/a?key=abcd1234", "https://example.org/a?x=1&sig=abcdef", "https://example.org/a?signature=abcdef12", "https://example.org/a?access_token=abcd",
               "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r", "AKIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE", "see " + "Q1b2C3d4" * 6)
    ALLOWED = ("basic input/output system", "basic client/server model", "basic read/write access", "https://example.org/a?auth=true", "the secret key of the table", "access key to the building", "a private key exchange protocol", "basic understanding of the methods", "the basic idea", "a page about the sig of a document",
               "see https://example.org/path?page=2&sort=asc", "https://example.org/a/b.html", "the key is under the mat", "user@example.org wrote", "a secret garden", "token of thanks", "AKIA is a prefix",
               "eyJ is how json starts in base64", "the tag eyJab.cd.ef is short", "digest " + "0" * 40)

    def test_each_shape_the_review_found_is_refused_in_the_reason_and_the_book_and_never_quoted(self):
        for text in self.REFUSED:
            for field in ("reason", "book"):
                with self.subTest(text=text[:24], field=field):
                    with self.assertRaises(KbError) as caught:
                        self.log.write("fail", "failed", now=NOW, **{field: text})
                    self.assertNotIn(text[:10], str(caught.exception))
        self.assertFalse(os.path.exists(self.path()))

    def test_the_same_words_in_ordinary_text_are_taken(self):
        for text in self.ALLOWED:
            self.log.write("fail", "failed", now=NOW, reason=text)
        self.assertEqual(len(self.lines()), len(self.ALLOWED))

    def test_a_host_field_is_checked_for_the_shapes_that_make_sense_there_and_a_long_label_is_still_taken(self):
        for text in ("user:pass@example.org", "secret_key=abc"):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW, host=text)
        self.log.write("fetch", "ok", now=NOW, host="a" * 63 + ".example.org")
        self.log.write("fetch", "ok", now=NOW, host="me@example.org")                    # an address with no password in it is not one

    def test_safe_gives_the_text_cleaned_or_a_fixed_reason_and_never_raises_for_what_a_page_said(self):
        guarded = crawllog.Log(self.index, "run-1", secrets=["hunter22"])
        self.assertEqual(guarded.safe("a plain\x1b[0m reason"), "a plain[0m reason")
        self.assertEqual(guarded.safe(None), None)
        for hostile in ("Authorization: Bearer abcdefgh12345", "see hunter22 here", "https://u:p@example.org/", "k" * 50, "secret_key=abc"):
            self.assertEqual(guarded.safe(hostile), crawllog.WITHHELD, hostile)
        self.assertEqual(guarded.safe("y " * 400), ("y " * 400)[:crawllog.LIMITS["reason"]].rstrip())
        for bad in (5, b"x", ["a"]):
            self.assertEqual(guarded.safe(bad), crawllog.WITHHELD)
        guarded.write("fail", "failed", now=NOW, reason=guarded.safe("Authorization: Bearer abcdefgh12345"))
        self.assertEqual(self.lines()[0]["reason"], "the text was withheld")
        self.assertEqual(guarded.safe("see hunter22 here", "book"), crawllog.WITHHELD)

    def test_safe_checks_the_field_it_is_asked_about(self):
        self.assertEqual(self.log.safe("a" * 600, "book"), "a" * crawllog.LIMITS["book"])
        with self.assertRaises(KbError):
            self.log.safe("x", "n")


class Cost(Case):
    """The reviewer's blocking finding: a hostile text must cost time in proportion to what is logged, not to what the page sent."""

    def test_200_kilobytes_of_near_matches_are_screened_in_well_under_a_second_in_every_text_field(self):
        import time
        hostile = {"letters": "a" * 200_000, "dashes": "eyJ-" * 50_000, "dots": "a." * 100_000, "colons": "a:" * 100_000, "ats": "a@" * 100_000, "base": "Basic " + "A" * 200_000,
                   "mixed": "x" * 100_000 + "://" + "y" * 100_000}
        for field in ("reason", "book", "host"):
            for name, text in hostile.items():
                started = time.perf_counter()
                try:
                    self.log._text(text, field)
                except KbError:
                    pass
                took = time.perf_counter() - started
                self.assertLess(took, 1.0, f"{field} {name} took {took:.2f}s")

    def test_the_patterns_never_see_more_than_the_field_limit_and_a_margin(self):
        seen = []

        class Spy:
            def __init__(self, real):
                self.real = real

            def search(self, text):
                seen.append(len(text))
                return self.real.search(text)

            def findall(self, text):
                seen.append(len(text))
                return self.real.findall(text)

        patterns = ("_HEADER", "_BEARER", "_BASIC", "_USERINFO", "_QUERY", "_JWT", "_AWS", "_HOSTUSER", "_LONG")
        with contextlib.ExitStack() as stack:
            for name in patterns:
                stack.enter_context(mock.patch.object(crawllog, name, Spy(getattr(crawllog, name))))
            for field in ("reason", "book", "host"):
                try:
                    self.log._text("w " * 400_000, field)
                except KbError:
                    pass
                self.assertLessEqual(max(seen), crawllog.LIMITS[field] + crawllog.MARGIN, field)
                seen.clear()

    def test_a_secret_far_beyond_the_cut_is_still_found_in_the_whole_text(self):
        guarded = crawllog.Log(self.index, "run-1", secrets=["hunter22"])
        with self.assertRaises(KbError):
            guarded.write("fail", "failed", now=NOW, reason="x " * 5000 + "hunter22")
        self.assertEqual(guarded.safe("x " * 5000 + "hunter22"), crawllog.WITHHELD)

    def test_a_credential_shape_that_starts_a_little_past_the_cut_is_seen_by_the_margin(self):
        text = "x " * 245 + "Authorization: Bearer abcdefgh12345"                     # starts at 490, the cut is at 500
        with self.assertRaises(KbError):
            self.log.write("fail", "failed", now=NOW, reason=text)
        self.assertEqual(self.log.safe(text), crawllog.WITHHELD)

    def test_what_safe_returns_is_always_taken_by_write_even_when_the_cut_makes_a_shape(self):
        edge = "x " * 240 + "AKIA" + "B" * 16 + "CCC"                              # the cut at 500 ends right after the key id, which makes it look whole
        with self.assertRaises(KbError):
            self.log.write("fail", "failed", now=NOW, reason=edge)
        shown = self.log.safe(edge)
        self.assertEqual(shown, crawllog.WITHHELD)
        self.log.write("fail", "failed", now=NOW, reason=shown)
        for text in ("y " * 400 + "token: abcdef", "k" * 495 + " and more " * 10, "Basic " + "A1" * 400, "a" * 495 + "AKIAIOSFODNN7EXAMPLE"):
            out = self.log.safe(text)
            self.log.write("fail", "failed", now=NOW, reason=out)                    # never raises, whatever safe gave back


class Repair(Case):
    """Finding F6: a log file that does not end in a line feed (a torn write) must not be fused with the next record."""

    def raw(self):
        return open(self.path(), "rb").read()

    def test_a_record_after_an_unfinished_line_starts_on_a_line_of_its_own_in_one_write(self):
        self.log.write("run_start", "ok", now=NOW)
        with open(self.path(), "ab") as f:
            f.write(b'{"ts":"2026-11-16T12:00:00Z","run":"run-1","step":"fet')                 # a torn write: no line feed
        writes = []
        real = os.write
        with mock.patch.object(crawllog.os, "write", lambda fd, data: (writes.append(bytes(data)), real(fd, data))[1]):
            self.log.write("fetch", "ok", now=NOW, n=7)
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith(b"\n{"))
        lines = self.raw().split(b"\n")
        self.assertEqual(lines[-1], b"")
        self.assertEqual(json.loads(lines[-2])["n"], 7)                                         # the new record is whole
        self.assertEqual(json.loads(lines[0])["step"], "run_start")
        with self.assertRaises(ValueError):
            json.loads(lines[1])                                                                # the stub stays a line of its own, which a reader skips

    def test_no_line_feed_is_added_to_an_empty_file_or_to_one_that_ends_in_one(self):
        writes = []
        real = os.write
        with mock.patch.object(crawllog.os, "write", lambda fd, data: (writes.append(bytes(data)), real(fd, data))[1]):
            self.log.write("run_start", "ok", now=NOW)
            self.log.write("fetch", "ok", now=NOW)
        self.assertEqual([w[:1] for w in writes], [b"{", b"{"])
        self.assertNotIn(b"\n\n", self.raw())

    def test_after_a_short_write_the_next_record_repairs_the_line(self):
        real = os.write
        with mock.patch.object(crawllog.os, "write", lambda fd, data: real(fd, bytes(data)[:20])):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW, n=1)
        self.assertFalse(self.raw().endswith(b"\n"))
        self.log.write("fetch", "ok", now=NOW, n=2)
        self.assertEqual(self.lines_skipping_bad(), [2])

    def lines_skipping_bad(self):
        out = []
        for line in self.raw().split(b"\n"):
            try:
                out.append(json.loads(line)["n"])
            except (ValueError, KeyError):
                pass
        return out

    def test_the_file_is_still_refused_when_it_cannot_be_read_for_the_last_byte(self):
        self.log.write("run_start", "ok", now=NOW)
        with mock.patch.object(crawllog.os, "pread", side_effect=OSError(5, "io")):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW)
        self.assertEqual(len(self.lines()), 1)

    def test_descriptors_are_not_left_open_by_the_repair(self):
        self.log.write("run_start", "ok", now=NOW)
        with open(self.path(), "ab") as f:
            f.write(b"stub")
        before = len(os.listdir("/dev/fd"))
        for _ in range(5):
            self.log.write("fetch", "ok", now=NOW)
        with mock.patch.object(crawllog.os, "pread", side_effect=OSError(5, "io")):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW)
        self.assertEqual(len(os.listdir("/dev/fd")), before)


class Writing(Case):
    def test_the_file_is_mode_600_in_folders_of_mode_700_made_for_it(self):
        self.log.write("run_start", "ok", now=NOW)
        self.assertEqual(stat.S_IMODE(os.stat(self.path()).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path())).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.index, "crawl")).st_mode), 0o700)
        old = os.umask(0)
        try:
            other = os.path.join(self.index, "other")
            os.mkdir(other)
            crawllog.Log(other, "r").write("run_start", "ok", now=NOW)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(other, "crawl", "log")).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(other, "crawl", "log", "crawl-2026-11-16.jsonl")).st_mode), 0o600)

    def test_lines_are_appended_and_an_existing_file_is_not_truncated(self):
        for i in range(3):
            self.log.write("fetch", "ok", now=NOW, n=i)
        again = crawllog.Log(self.index, "run-2")
        again.write("fetch", "ok", now=NOW, n=3)
        self.assertEqual([line["n"] for line in self.lines()], [0, 1, 2, 3])

    def test_each_line_is_one_write_of_the_whole_line_to_a_descriptor_opened_for_append(self):
        opened, written = [], []
        real_open, real_write = os.open, os.write

        def spy_open(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if str(path).endswith(".jsonl"):
                opened.append(flags)
            return fd

        def spy_write(fd, data):
            written.append(bytes(data))
            return real_write(fd, data)

        with mock.patch.object(crawllog.os, "open", spy_open), mock.patch.object(crawllog.os, "write", spy_write):
            self.log.write("fetch", "ok", now=NOW, reason="one")
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0] & os.O_APPEND)
        self.assertTrue(opened[0] & os.O_NOFOLLOW)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0], open(self.path(), "rb").read())
        self.assertTrue(written[0].endswith(b"\n"))

    def test_a_folder_made_by_another_process_in_the_meantime_is_taken_after_the_checks(self):
        real = os.mkdir

        def racing(path, mode=0o777, **kw):
            real(path, 0o700)                       # the other process was first
            raise FileExistsError(17, "File exists", path)

        with mock.patch.object(crawllog.os, "mkdir", racing):
            self.log.write("run_start", "ok", now=NOW)
        self.assertEqual(len(self.lines()), 1)

    def test_the_boundary_of_8_kib_is_exact_and_a_line_ends_with_one_line_feed_only(self):
        self.log.write("fail", "failed", now=NOW, reason="boundary")
        raw = open(self.path(), "rb").read()
        self.assertTrue(raw.endswith(b"}\n"))
        self.assertNotIn(b"\r", raw)
        size = len(raw)
        os.remove(self.path())
        with mock.patch.object(crawllog, "LINE_MAX", size):
            self.log.write("fail", "failed", now=NOW, reason="boundary")
        self.assertEqual(json.loads(open(self.path(), "rb").read())["reason"], "boundary")
        os.remove(self.path())
        with mock.patch.object(crawllog, "LINE_MAX", size - 1):
            self.log.write("fail", "failed", now=NOW, reason="boundary")
        self.assertTrue(json.loads(open(self.path(), "rb").read())["reason"].endswith(" [cut]"))

    def test_no_descriptor_is_left_open_by_a_write_or_by_one_that_fails(self):
        self.log.write("run_start", "ok", now=NOW)
        before = len(os.listdir("/dev/fd"))
        for _ in range(20):
            self.log.write("fetch", "ok", now=NOW)
        with mock.patch.object(crawllog.os, "write", side_effect=OSError(28, "No space left on device")):
            for _ in range(5):
                with self.assertRaises(KbError):
                    self.log.write("fetch", "ok", now=NOW)
        os.chmod(self.path(), 0o666)
        for _ in range(5):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW)
        os.chmod(self.path(), 0o600)
        self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_any_error_of_the_open_is_a_refusal_and_not_a_raw_error(self):
        for number in (6, 40, 2, 13):
            with mock.patch.object(crawllog.os, "open", side_effect=OSError(number, "refused")):
                with self.assertRaises(KbError):
                    self.log.write("fetch", "ok", now=NOW)

    def test_a_short_write_is_an_error(self):
        real = os.write
        with mock.patch.object(crawllog.os, "write", lambda fd, data: real(fd, bytes(data)[:10])):
            with self.assertRaises(KbError):
                self.log.write("fetch", "ok", now=NOW)

    def test_two_processes_writing_at_once_leave_whole_lines_only(self):
        script = (
            "import sys, datetime\n"
            "sys.path.insert(0, sys.argv[4])\n"
            "from kb import crawllog\n"
            "log = crawllog.Log(sys.argv[1], sys.argv[2])\n"
            "now = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)\n"
            "for i in range(150):\n"
            "    log.write('fetch', 'ok', now=now, candidate=i, reason=sys.argv[3] * 3000, book=sys.argv[2])\n")
        procs = [subprocess.Popen([sys.executable, "-I", "-c", script, self.index, name, char, ENGINE_DIR], stderr=subprocess.PIPE) for name, char in (("w1", "a"), ("w2", "b"))]
        errors = [p.communicate()[1] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], errors)
        lines = self.lines()
        self.assertEqual(len(lines), 300)
        for line in lines:
            self.assertEqual(set(line["reason"]), {"a" if line["run"] == "w1" else "b"})
        self.assertEqual(sorted(line["candidate"] for line in lines if line["run"] == "w1"), list(range(150)))

    def test_a_line_over_8_kib_is_cut_and_says_so(self):
        self.assertEqual(crawllog.LINE_MAX, 8192)
        crowded = crawllog.Log(self.index, "run-1")
        with mock.patch.dict(crawllog.LIMITS, {"reason": 5000, "book": 5000, "host": 5000}):
            crowded.write("fail", "failed", now=NOW, reason="\u00e9" * 4000, book="b" * 100)
        raw = open(self.path(), "rb").read()
        self.assertLessEqual(len(raw), 8192)
        line = json.loads(raw)
        self.assertEqual(crawllog.CUT, " [cut]")
        self.assertTrue(line["reason"].endswith(" [cut]"))
        self.assertEqual(line["book"], "b" * 100)
        self.assertEqual(line["step"], "fail")
        self.assertGreater(len(line["reason"]), 100)

    def test_a_line_that_cannot_be_made_short_enough_is_an_error_and_nothing_is_written(self):
        with mock.patch.object(crawllog, "LINE_MAX", 100):
            with self.assertRaises(KbError):
                self.log.write("fail", "failed", now=NOW, reason="ww " * 20)
        self.assertEqual(open(self.path(), "rb").read() if os.path.exists(self.path()) else b"", b"")

    def test_a_log_that_cannot_be_written_raises_and_does_not_hide_it(self):
        self.log.write("run_start", "ok", now=NOW)
        os.chmod(os.path.dirname(self.path()), 0o500)
        with self.assertRaises(KbError):                                    # a new day needs a new file, and the folder cannot take one
            self.log.write("run_end", "ok", now=NOW + datetime.timedelta(days=1))
        os.chmod(os.path.dirname(self.path()), 0o700)
        os.chmod(self.path(), 0o400)
        with self.assertRaises(KbError):
            self.log.write("run_end", "ok", now=NOW)
        os.chmod(self.path(), 0o600)
        with self.assertRaises(KbError):
            crawllog.Log(os.path.join(self.index, "no", "such", "root"), "r").write("run_start", "ok", now=NOW)
        with mock.patch.object(crawllog.os, "write", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(KbError):
                self.log.write("run_end", "ok", now=NOW)
        self.assertEqual(len(self.lines()), 1)

    def test_a_folder_or_file_that_is_a_link_a_folder_or_a_pipe_is_refused(self):
        elsewhere = os.path.join(os.path.dirname(self.index), "elsewhere")
        os.mkdir(elsewhere)
        os.symlink(elsewhere, os.path.join(self.index, "crawl"))
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now=NOW)
        self.assertEqual(os.listdir(elsewhere), [])
        os.remove(os.path.join(self.index, "crawl"))
        os.makedirs(os.path.join(self.index, "crawl"), mode=0o700)
        os.symlink(elsewhere, os.path.join(self.index, "crawl", "log"))
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now=NOW)
        self.assertEqual(os.listdir(elsewhere), [])
        os.remove(os.path.join(self.index, "crawl", "log"))
        os.mkdir(os.path.join(self.index, "crawl", "log"), 0o700)
        target = os.path.join(elsewhere, "target.jsonl")
        open(target, "w").close()
        os.symlink(target, self.path())
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now=NOW)
        self.assertEqual(os.path.getsize(target), 0)
        os.remove(self.path())
        os.mkdir(self.path())
        with self.assertRaises(KbError):
            self.log.write("run_start", "ok", now=NOW)
        os.rmdir(self.path())
        os.mkfifo(self.path())
        with self.assertRaises(KbError):                                     # it must refuse and not wait for a reader
            self.log.write("run_start", "ok", now=NOW)

    def test_a_folder_or_file_that_others_can_write_or_that_is_another_users_is_refused(self):
        self.log.write("run_start", "ok", now=NOW)
        os.chmod(self.path(), 0o666)
        with self.assertRaises(KbError):
            self.log.write("run_end", "ok", now=NOW)
        os.chmod(self.path(), 0o600)
        os.chmod(os.path.dirname(self.path()), 0o777)
        with self.assertRaises(KbError):
            self.log.write("run_end", "ok", now=NOW)
        os.chmod(os.path.dirname(self.path()), 0o700)
        os.chmod(os.path.join(self.index, "crawl"), 0o770)
        with self.assertRaises(KbError):
            self.log.write("run_end", "ok", now=NOW)
        os.chmod(os.path.join(self.index, "crawl"), 0o700)
        self.log.write("run_end", "ok", now=NOW)
        self.assertEqual(len(self.lines()), 2)

    def test_the_error_does_not_quote_the_text_it_was_given(self):
        with self.assertRaises(KbError) as caught:
            self.log.write("fail", "failed", now=NOW, reason="Auth-Key: SECRETVALUE")
        self.assertNotIn("SECRETVALUE", str(caught.exception))
        self.assertNotIn(self.index, str(caught.exception))


class Wiring(Case):
    def test_the_module_reads_no_environment_makes_no_request_and_does_not_import_the_models(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawllog.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib", "http.client", "subprocess", "os.environ", "getenv", "webclient", "models"):
            self.assertNotIn(word, source, word)
        self.assertEqual(len(re.findall(r"\bos\.write\(", source)), 1)


if __name__ == "__main__":
    unittest.main()
