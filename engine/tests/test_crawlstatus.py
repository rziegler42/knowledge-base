"""The reading side of `crawl-status` and `crawl-report` (`kb/crawlstatus.py`; `docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`).

Every test runs on a temporary index root and on hand-made fixture files in the spec's log format. No test opens a socket, reads the owner's
library, config, plan or keys, or writes outside its temporary folder. Hostile characters are made with `chr()` here, never typed."""

import collections
import datetime
import errno
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, crawlstatus as cs

REPO = Path(ENGINE_DIR).parent
SPEC = REPO / "docs" / "specs" / "population.md"
FIX = Path(ENGINE_DIR) / "tests" / "fixtures" / "crawlstatus"

ZWSP, JOINER, RLO, SHY, VS16, TAG_A = chr(0x200B), chr(0x200D), chr(0x202E), chr(0x00AD), chr(0xFE0F), chr(0xE0041)
HIDDEN = (ZWSP, JOINER, RLO, SHY, VS16, TAG_A)
HEADERS = ("Auth-Key", "Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie", "X-Api-Key", "X-Auth-Token")
PARAMS = ("key", "apikey", "api_key", "token", "access_token", "auth", "secret", "password", "passwd", "sig", "signature")


def record(drop=(), **over):
    base = {"ts": "2026-11-16T05:00:00Z", "run": "r1", "step": "fetch", "outcome": "ok", "candidate": None, "book": None, "host": None,
            "reason": None, "n": None, "seconds": None}
    base.update(over)
    for key in drop:
        del base[key]
    return base


def raw(drop=(), **over):
    return json.dumps(record(drop, **over)).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def within(self, fn, seconds=5):
        """Run `fn` in a thread and fail the test if it does not finish: a blocking open of a pipe must not hang the suite."""
        done, box = threading.Event(), {}

        def run():
            try:
                box["value"] = fn()
            except BaseException as e:  # reported below, in the test's own thread
                box["error"] = e
            done.set()

        threading.Thread(target=run, daemon=True).start()
        if not done.wait(seconds):
            self.fail("the call did not return: it waited on something")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def root_with_log(self, names=()):
        log = self.tmp / "crawl" / "log"
        log.mkdir(parents=True)
        for name in names:
            shutil.copy(FIX / "log" / name, log / name)
        return self.tmp


class ReadOnlyTest(unittest.TestCase):
    """The module is read only: its text holds no call that writes, creates, removes, renames, locks for writing, sends or starts a program."""

    def test_the_source_has_no_call_that_changes_anything_or_reaches_out(self):
        source = (Path(ENGINE_DIR) / "kb" / "crawlstatus.py").read_text(encoding="utf-8")
        for token in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "LOCK_EX", "os.write(", "os.unlink(", "os.remove(", "os.rename(",
                      "os.replace(", "os.mkdir(", "os.makedirs(", "os.rmdir(", "os.chmod(", "os.chown(", "os.symlink(", "os.link(", "os.utime(",
                      "os.truncate(", "os.fsync(", "shutil", ".write_text(", ".write_bytes(", ".touch(", ".mkdir(", ".unlink(", "socket", "urllib.request",
                      "http.client", "subprocess", "os.system(", "os.popen(", "sqlite3"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIsNone(re.search(r"(?<![.\w])open\(", source), "the builtin open")


class ReadFileTest(Base):
    def test_a_plain_file_is_read(self):
        p = self.tmp / "f"
        p.write_bytes(b"hello")
        r = cs.read_file(p, 100)
        self.assertEqual((r.data, r.status, r.reason, r.cut), (b"hello", "ok", None, False))

    def test_the_file_is_opened_for_reading_only_without_following_a_link_waiting_or_taking_a_terminal(self):
        p = self.tmp / "f"
        p.write_bytes(b"x")
        seen = []
        real = os.open

        def spy(path, flags, *args):
            seen.append(flags)
            return real(path, flags, *args)

        with mock.patch.object(os, "open", spy):
            cs.read_file(p, 10)
        self.assertEqual(len(seen), 1)
        flags = seen[0]
        for wanted in (os.O_NOFOLLOW, os.O_NONBLOCK, os.O_NOCTTY):
            self.assertTrue(flags & wanted, wanted)
        for forbidden in (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND):
            self.assertFalse(flags & forbidden, forbidden)
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)

    def test_a_missing_file_is_missing_and_not_an_error(self):
        r = cs.read_file(self.tmp / "nope", 100)
        self.assertEqual((r.data, r.status, r.cut), (None, "missing", False))

    def test_a_link_is_not_followed(self):
        (self.tmp / "real").write_bytes(b"secret")
        os.symlink(self.tmp / "real", self.tmp / "link")
        r = cs.read_file(self.tmp / "link", 100)
        self.assertEqual((r.data, r.status), (None, "bad"))
        self.assertNotIn("secret", repr(r))

    def test_a_pipe_is_not_waited_on(self):
        os.mkfifo(self.tmp / "pipe")
        r = self.within(lambda: cs.read_file(self.tmp / "pipe", 100))
        self.assertEqual((r.data, r.status), (None, "bad"))

    def test_a_folder_is_bad(self):
        (self.tmp / "d").mkdir()
        self.assertEqual(cs.read_file(self.tmp / "d", 100).status, "bad")

    def test_a_file_of_another_owner_is_bad(self):
        p = self.tmp / "f"
        p.write_bytes(b"x")
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            r = cs.read_file(p, 100)
        self.assertEqual((r.data, r.status), (None, "bad"))

    def test_a_file_over_the_limit_is_cut_at_the_limit_from_the_start(self):
        p = self.tmp / "f"
        p.write_bytes(b"0123456789" * 10)
        r = cs.read_file(p, 25)
        self.assertEqual((r.data, r.status, r.cut), (b"0123456789" * 2 + b"01234", "ok", True))

    def test_the_tail_choice_reads_the_end(self):
        p = self.tmp / "f"
        p.write_bytes(b"0123456789" * 10)
        r = cs.read_file(p, 25, tail=True)
        self.assertEqual((r.data, r.cut), (b"56789" + b"0123456789" * 2, True))

    def test_a_file_exactly_the_limit_is_not_cut(self):
        p = self.tmp / "f"
        p.write_bytes(b"x" * 25)
        r = cs.read_file(p, 25)
        self.assertEqual((len(r.data), r.cut), (25, False))

    def test_read_small_takes_a_whole_small_file_and_refuses_a_large_one(self):
        p = self.tmp / "f"
        p.write_bytes(b"0123456789")
        self.assertEqual(cs.read_small(p, 10).data, b"0123456789")
        r = cs.read_small(p, 9)
        self.assertEqual((r.data, r.status), (None, "bad"))
        self.assertIn("over", r.reason)

    def test_the_limit_must_be_a_positive_whole_number(self):
        p = self.tmp / "f"
        p.write_bytes(b"x")
        for bad in (0, -1, 1.5, "10", None, True):
            with self.subTest(limit=bad), self.assertRaises(KbError):
                cs.read_file(p, bad)

    def test_nothing_is_created_or_changed(self):
        before = sorted(os.listdir(self.tmp))
        cs.read_file(self.tmp / "nope", 10)
        self.assertEqual(sorted(os.listdir(self.tmp)), before)


class RedactTest(unittest.TestCase):
    def test_each_header_name_withholds_the_whole_value(self):
        for name in HEADERS:
            for variant in (name, name.lower(), name.upper()):
                for sep in (":", "=", " :", ": ", " = "):
                    with self.subTest(name=variant, sep=sep):
                        self.assertEqual(cs.redact(f"failed with {variant}{sep}abc123 and more"), cs.WITHHELD)

    def test_a_name_inside_a_longer_word_is_not_a_header(self):
        for text in ("three cookies: yes", "authorizations=2", "mycookie: x", "the cookie jar", "authorization was late"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), text)

    def test_a_bearer_token_is_withheld_and_a_short_word_after_bearer_is_not(self):
        for text in ("Bearer abcdefgh12345678", "bearer ABCDEFGH.12345678", "sent BEARER abcdefgh12345678 now"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), cs.WITHHELD)
        for text in ("the bearer of news", "Bearer short"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), text)

    def test_the_user_and_password_of_an_address_are_removed(self):
        self.assertEqual(cs.redact("https://user:pw@example.org/a"), "https://example.org/a")
        self.assertEqual(cs.redact("http://token@example.org/"), "http://example.org/")
        self.assertEqual(cs.redact("see https://u:p@h.example/x?y=1 now"), "see https://h.example/x?y=1 now")

    def test_each_parameter_name_of_the_list_is_hidden_in_a_query_and_in_a_fragment(self):
        for name in PARAMS:
            for variant in (name, name.upper()):
                with self.subTest(name=variant):
                    out = cs.redact(f"https://example.org/p?a=1&{variant}=HUNTER2X&b=2")
                    self.assertNotIn("HUNTER2X", out)
                    self.assertIn("[withheld]", out)
                    self.assertIn("a=1", out)
                    self.assertIn("b=2", out)
                    self.assertNotIn("HUNTER2X", cs.redact(f"https://example.org/p#{variant}=HUNTER2X"))

    def test_parameters_may_be_separated_by_a_semicolon(self):
        out = cs.redact("https://example.org/p?a=1;token=HUNTER2X;b=2")
        self.assertNotIn("HUNTER2X", out)
        self.assertIn("a=1", out)
        self.assertIn("b=2", out)

    def test_a_parameter_name_written_with_percent_escapes_is_still_hidden(self):
        self.assertNotIn("SECRET", cs.redact("https://example.org/?%74oken=SECRET&x=1"))

    def test_a_parameter_name_that_only_contains_a_listed_name_is_kept(self):
        for text in ("https://example.org/?keyword=cats&monkey=1", "https://example.org/?tokens=2&authors=a"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), text)

    def test_a_password_or_value_with_a_quote_or_a_bracket_in_it_is_still_removed(self):
        for ch in ("'", '"', "`", "<", ">"):
            with self.subTest(char=ch):
                self.assertEqual(cs.redact(f"https://user:pa{ch}ss@host/x"), "https://host/x")
                out = cs.redact(f"https://h/?token=ab{ch}cd&a=1")
                self.assertNotIn("cd", out)
                self.assertNotIn("ab", out)

    def test_an_address_of_another_scheme_has_its_user_and_password_removed_too(self):
        self.assertEqual(cs.redact("ftp://u:p@h.example/x"), "ftp://h.example/x")
        self.assertEqual(cs.redact("ssh://git:hunter@h.example"), "ssh://h.example")
        self.assertEqual(cs.redact("git+https://u:p@h.example/r"), "git+https://h.example/r")

    def test_a_header_name_may_be_closed_by_a_quote_before_the_colon(self):
        for text in ("{'Cookie': 'sid=abc'}", '{"Set-Cookie": "x"}', "{'X-Api-Key': 'k'}", '"Authorization": "Basic abcdef"',
                     "'Auth-Key' = 'k'", '"Proxy-Authorization" : "x"'):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), cs.WITHHELD)
        self.assertEqual(cs.redact("the cookie' jar and the 'authorization' form"), "the cookie' jar and the 'authorization' form")

    def test_what_the_rule_cannot_know_is_left_as_it_is(self):
        for text in ("api_key=SECRET with no address around it", "sk-live-abcdefghijklmnopqrstuvwx", "plain words"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), text)


class CleanTest(unittest.TestCase):
    def test_an_escape_sequence_loses_its_escape_character(self):
        out = cs.clean("\x1b[31mred\x1b[0m", 100)
        self.assertNotIn("\x1b", out)
        self.assertIn("red", out)

    def test_direction_and_zero_width_characters_are_removed_and_lines_collapse(self):
        self.assertEqual(cs.clean("a" + RLO + "b" + ZWSP + "c", 10), "abc")
        self.assertEqual(cs.clean("a\nb\r\nc\t d", 20), "a b c d")

    def test_a_long_run_is_cut_to_the_limit(self):
        self.assertEqual(cs.clean("x" * 10000, 50), "x" * 50)

    def test_none_and_numbers(self):
        self.assertEqual(cs.clean(None, 5), "")
        self.assertEqual(cs.clean(12345, 3), "123")

    def test_the_limit_is_a_whole_number_from_1_to_2000(self):
        for bad in (0, -1, 2001, 1.5, "5", None):
            with self.subTest(limit=bad), self.assertRaises(KbError):
                cs.clean("a", bad)
        self.assertEqual(cs.clean("a", 2000), "a")

    def test_a_header_split_by_a_hidden_character_is_withheld(self):
        for h in HIDDEN:
            with self.subTest(char=hex(ord(h))):
                self.assertEqual(cs.clean("Auth" + h + "-Key: sekret", 200), cs.WITHHELD)
                self.assertEqual(cs.clean("Coo" + h + "kie=x", 200), cs.WITHHELD)
                self.assertEqual(cs.clean("Authoriz" + h + "ation: Bearer abc", 200), cs.WITHHELD)
                self.assertEqual(cs.clean("Bear" + h + "er abcdefgh12345678", 200), cs.WITHHELD)

    def test_a_parameter_name_split_by_a_hidden_character_is_hidden(self):
        for h in HIDDEN:
            with self.subTest(char=hex(ord(h))):
                out = cs.clean("https://example.org/?to" + h + "ken=SECRET&a=1", 200)
                self.assertNotIn("SECRET", out)
                self.assertIn("[withheld]", out)

    def test_a_cut_inside_a_key_never_prints_a_part_of_it(self):
        out = cs.clean("x" * 190 + " Authorization: Bearer abcdef0123456789", 200)
        self.assertEqual(out, cs.WITHHELD)
        out = cs.clean("https://example.org/p?a=" + "x" * 100 + "&token=SECRETSECRETSECRET", 136)
        self.assertNotIn("SEC", out)
        self.assertIn("&token=[w", out)

    def test_a_credential_split_by_the_cut_of_the_first_step_is_never_printed_in_part(self):
        out = cs.clean("x" * 1990 + " Bearer abcdefghijklmnop", 2000)  # the cut leaves "Bearer ab", too short for the rule
        self.assertEqual(out, "x" * 1990)
        out = cs.clean("x" * 1985 + " https://user:pa" + "ss@host.example/" + "z" * 100, 2000)  # the cut falls before the "@"
        self.assertEqual(out, "x" * 1985)
        out = cs.clean(ZWSP * 8090 + "Bearer abcdefghijklmnop", 2000)  # the cut of the raw text is made before the hidden characters go
        self.assertNotIn("Bearer", out)
        self.assertEqual(out, "")

    def test_a_bearer_word_with_seven_characters_left_by_the_cut_is_dropped_too(self):
        out = cs.clean("x" * 1985 + " Bearer abcdefghijklmnop", 2000)  # the cut leaves "Bearer abcdefg"
        self.assertEqual(out, "x" * 1985)

    def test_only_the_address_at_the_end_of_a_cut_text_is_dropped_and_an_earlier_one_stays(self):
        out = cs.clean("see https://ok.example/a " + "y" * 2100, 2000)
        self.assertTrue(out.startswith("see https://ok.example/a yyyy"))

    def test_a_text_that_was_not_cut_keeps_its_last_word_and_its_last_address(self):
        self.assertEqual(cs.clean("x" * 100 + " Bearer short", 200), "x" * 100 + " Bearer short")
        self.assertEqual(cs.clean("see https://u.example/ok", 100), "see https://u.example/ok")
        self.assertEqual(cs.clean("x" * 10000, 2000), "x" * 2000)

    def test_a_huge_text_costs_bounded_work_and_a_header_past_the_bound_is_not_in_the_output(self):
        start = time.process_time()
        out = cs.clean("a" * 1_000_000 + " Cookie: x", 100)
        self.assertLess(time.process_time() - start, 2.0)
        self.assertEqual(out, "a" * 100)

    def test_the_address_rule_applies_through_clean(self):
        self.assertEqual(cs.clean("https://u:pw@example.org/a?token=SECRET", 200), "https://example.org/a?token=[withheld]")


class ParseLineTest(unittest.TestCase):
    def test_a_good_line_has_exactly_the_ten_fields(self):
        rec, kind = cs.parse_line(raw(candidate="https://example.org/a", book="b-1", host="example.org", reason="x", n=5, seconds=0.5))
        self.assertIsNone(kind)
        self.assertEqual(set(rec), {"ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds"})
        self.assertEqual((rec["n"], rec["seconds"], rec["host"]), (5, 0.5, "example.org"))

    def test_a_field_that_is_not_in_the_spec_is_dropped_and_never_copied(self):
        rec, kind = cs.parse_line(raw(auth_key="SECRET", headers={"Cookie": "SECRET"}))
        self.assertIsNone(kind)
        self.assertNotIn("SECRET", repr(rec))
        self.assertNotIn("auth_key", rec)

    def test_the_optional_fields_may_be_absent_or_null(self):
        rec, kind = cs.parse_line(raw(drop=("candidate", "book", "host", "reason", "n", "seconds")))
        self.assertIsNone(kind)
        self.assertEqual([rec[k] for k in ("candidate", "book", "host", "reason", "n", "seconds")], [None] * 6)

    def test_every_step_and_outcome_of_the_spec_is_taken_and_no_other(self):
        text = SPEC.read_text(encoding="utf-8")
        steps = re.search(r"\*\*Steps:\*\* (.*?)\.\s", text).group(1)
        outcomes = re.search(r"\*\*Outcomes:\*\* (.*?)\.\s", text).group(1)
        spec_steps = tuple(re.findall(r"`([a-z_]+)`", steps))
        spec_outcomes = tuple(re.findall(r"`([a-z_]+)`", outcomes))
        self.assertEqual(cs.STEPS, spec_steps)
        self.assertEqual(cs.OUTCOMES, spec_outcomes)
        for step in spec_steps:
            self.assertIsNone(cs.parse_line(raw(step=step))[1])
        for outcome in spec_outcomes:
            self.assertIsNone(cs.parse_line(raw(outcome=outcome))[1])

    def test_each_kind_of_bad_line(self):
        cases = {
            "not_json": [b"not json", b"{", b"x", b"[" * 10000, b'{"ts": 1,}', b"\xef\xbb\xbf" + raw()],
            "not_object": [b"[1,2]", b'"text"', b"5", b"null"],
            "duplicate_key": [b'{"ts":"2026-11-16T05:00:00Z","ts":"2026-11-16T05:00:01Z","run":"r","step":"fetch","outcome":"ok"}'],
            "non_finite": [raw().replace(b'"seconds": null', b'"seconds": NaN'), raw().replace(b'"n": null', b'"n": Infinity'),
                           raw().replace(b'"seconds": null', b'"seconds": 1e999')],
            "bad_step": [raw(step="dance"), raw(step="FETCH"), raw(step=5)],
            "bad_outcome": [raw(outcome="maybe"), raw(outcome=None)],
            "bad_ts": [raw(ts="yesterday"), raw(ts="2026-13-40T00:00:00Z"), raw(ts="2026-11-16T05:00:00"), raw(ts="2026-11-16 05:00:00Z"),
                       raw(ts="2026-11-16T05:00:00.5Z"), raw(ts=5), raw(ts="2026-11-16T25:00:00Z"),
                       raw(ts="2026-1-6T5:0:0Z"), raw(ts=chr(0xFF12) + "026-11-16T05:00:00Z")],
            "missing_field": [raw(drop=("ts",)), raw(drop=("run",)), raw(drop=("step",)), raw(drop=("outcome",))],
            "bad_field": [raw(n="12"), raw(n=True), raw(n=-1), raw(n=1.5), raw(seconds="x"), raw(seconds=-1), raw(seconds=False),
                          raw(candidate=5), raw(host=["a"]), raw(book={"a": 1}), raw(reason=3), raw(run=None), raw(run=7),
                          raw(reason="x" * (cs.MAX_FIELD + 1)), raw(candidate="c" * (cs.MAX_FIELD + 1)),
                          b'{"ts":"2026-11-16T05:00:00Z","run":"r","step":"fetch","outcome":"ok","reason":"\\ud800"}'],
            "not_utf8": [b"\xff\xfe" + raw(), raw().replace(b"r1", b"\xff\xfe")],
            "nul": [raw().replace(b"r1", b"r\x001")],
            "too_long": [raw(reason="y" * (cs.MAX_LINE + 1))],
        }
        for expected, lines in cases.items():
            for line in lines:
                with self.subTest(kind=expected, line=line[:40]):
                    rec, kind = cs.parse_line(line)
                    self.assertEqual((rec, kind), (None, expected))

    def test_a_blank_line_is_blank_and_a_carriage_return_is_ignored(self):
        self.assertEqual(cs.parse_line(b"   "), (None, "blank"))
        self.assertEqual(cs.parse_line(b""), (None, "blank"))
        self.assertIsNone(cs.parse_line(raw() + b"\r")[1])

    def test_a_line_of_exactly_the_limit_is_taken_and_one_byte_more_is_too_long(self):
        line = raw()
        self.assertIsNone(cs.parse_line(line + b" " * (cs.MAX_LINE - len(line)))[1])
        self.assertEqual(cs.parse_line(line + b" " * (cs.MAX_LINE - len(line) + 1)), (None, "too_long"))

    def test_n_takes_the_whole_numbers_up_to_two_to_the_53(self):
        self.assertEqual(cs.parse_line(raw(n=2**53))[0]["n"], 2**53)
        self.assertEqual(cs.parse_line(raw(n=0))[0]["n"], 0)
        self.assertEqual(cs.parse_line(raw(n=2**53 + 1)), (None, "bad_field"))

    def test_seconds_takes_zero_and_whole_numbers_and_fractions(self):
        for value in (0, 0.0, 3, 0.25, 1e6):
            with self.subTest(seconds=value):
                self.assertEqual(cs.parse_line(raw(seconds=value))[0]["seconds"], value)

    def test_a_field_of_exactly_the_field_limit_is_taken(self):
        rec, kind = cs.parse_line(raw(reason="y" * cs.MAX_FIELD, candidate="c" * cs.MAX_FIELD))
        self.assertIsNone(kind)
        self.assertEqual(len(rec["reason"]), cs.MAX_FIELD)


class ReadLogTest(Base):
    def write(self, name, data):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def lines(self, count, start=0):
        return [raw(ts=f"2026-11-16T05:{(start + i) // 60:02d}:{(start + i) % 60:02d}Z", run=f"r{start + i}") for i in range(count)]

    def test_good_lines_come_in_order_with_the_first_and_last_ts(self):
        p = self.write("log", b"\n".join(self.lines(5)) + b"\n")
        r = cs.read_log(p)
        self.assertEqual((r["status"], r["bad"], r["cut"]), ("ok", {}, False))
        self.assertEqual([x["run"] for x in r["lines"]], [f"r{i}" for i in range(5)])
        self.assertEqual((r["first"], r["last"]), ("2026-11-16T05:00:00Z", "2026-11-16T05:00:04Z"))

    def test_the_first_and_last_ts_are_the_smallest_and_the_largest_whatever_the_order(self):
        data = b"\n".join([raw(ts="2026-11-16T07:00:00Z"), raw(ts="2026-11-16T05:00:00Z"), raw(ts="2026-11-16T09:00:00Z"),
                           raw(ts="2026-11-16T06:00:00Z")]) + b"\n"
        r = cs.read_log(self.write("log", data))
        self.assertEqual((r["first"], r["last"]), ("2026-11-16T05:00:00Z", "2026-11-16T09:00:00Z"))

    def test_bad_lines_are_skipped_and_counted_by_kind(self):
        data = b"\n".join([raw(), b"not json", raw(step="dance"), b"[1]", b"also not json", raw(run="r2"), b"\xff"]) + b"\n"
        r = cs.read_log(self.write("log", data))
        self.assertEqual([x["run"] for x in r["lines"]], ["r1", "r2"])
        self.assertEqual(r["bad"], {"not_json": 2, "bad_step": 1, "not_object": 1, "not_utf8": 1})

    def test_blank_lines_are_skipped_and_not_counted(self):
        r = cs.read_log(self.write("log", raw() + b"\n\n   \n" + raw(run="r2") + b"\n"))
        self.assertEqual((len(r["lines"]), r["bad"]), (2, {}))

    def test_the_last_line_without_a_line_feed_is_still_a_line(self):
        r = cs.read_log(self.write("log", raw() + b"\n" + raw(run="r2")))
        self.assertEqual([x["run"] for x in r["lines"]], ["r1", "r2"])

    def test_a_missing_file_a_link_a_pipe_and_a_folder(self):
        os.symlink(self.tmp / "nowhere", self.tmp / "link")
        os.mkfifo(self.tmp / "pipe")
        (self.tmp / "dir").mkdir()
        self.assertEqual(cs.read_log(self.tmp / "nope")["status"], "missing")
        for name in ("link", "pipe", "dir"):
            with self.subTest(name=name):
                r = self.within(lambda n=name: cs.read_log(self.tmp / n))
                self.assertEqual((r["status"], r["lines"]), ("bad", []))

    def test_a_file_over_the_limit_is_read_to_the_limit_and_the_cut_line_is_dropped_not_counted(self):
        lines = self.lines(100)
        data = b"\n".join(lines) + b"\n"
        limit = sum(len(x) + 1 for x in lines[:60]) + 20  # in the middle of the 61st line
        r = cs.read_log(self.write("log", data), limit=limit)
        self.assertEqual((len(r["lines"]), r["cut"], r["bad"]), (60, True, {}))
        self.assertEqual(r["lines"][-1]["run"], "r59")

    def test_the_tail_choice_keeps_the_newest_lines_and_drops_the_cut_first_line(self):
        lines = self.lines(100)
        data = b"\n".join(lines) + b"\n"
        limit = sum(len(x) + 1 for x in lines[-40:]) + 20  # in the middle of the 60th line from the end
        r = cs.read_log(self.write("log", data), limit=limit, tail=True)
        self.assertEqual((len(r["lines"]), r["cut"], r["bad"]), (40, True, {}))
        self.assertEqual(r["lines"][-1]["run"], "r99")

    def test_the_fixture_day_is_read_whole(self):
        r = cs.read_log(FIX / "log" / "crawl-2026-11-16.jsonl")
        self.assertEqual((len(r["lines"]), r["bad"], r["cut"]), (6, {}, False))
        self.assertEqual([x["step"] for x in r["lines"]], ["run_start", "run_start", "refuse", "fetch", "capture", "run_end"])

    def test_a_planted_key_in_an_unknown_field_does_not_reach_the_lines(self):
        r = cs.read_log(self.write("log", raw(authorization="Bearer SECRETSECRET1") + b"\n"))
        self.assertNotIn("SECRET", repr(r))


class LogFilesTest(Base):
    def make(self):
        log = self.tmp / "crawl" / "log"
        log.mkdir(parents=True)
        for name in ("crawl-2026-11-15.jsonl", "crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"):
            (log / name).write_text("x\n")
        for name in ("crawl-2026-13-45.jsonl", "crawl-2026-11-16.jsonl.bak", "notes.txt", "crawl-26-11-16.jsonl", "xcrawl-2026-11-16.jsonl"):
            (log / name).write_text("x\n")
        os.symlink(log / "crawl-2026-11-15.jsonl", log / "crawl-2026-11-18.jsonl")
        (log / "crawl-2026-11-19.jsonl").mkdir()
        os.mkfifo(log / "crawl-2026-11-20.jsonl")
        return log

    def dates(self, files):
        return [d.isoformat() for d, _ in files]

    def test_only_well_named_plain_files_are_listed_oldest_first(self):
        self.make()
        files, problem = self.within(lambda: cs.log_files(self.tmp))
        self.assertIsNone(problem)
        self.assertEqual(self.dates(files), ["2026-11-15", "2026-11-16", "2026-11-17"])
        self.assertEqual(files[0][1], self.tmp / "crawl" / "log" / "crawl-2026-11-15.jsonl")

    def test_newest_first_and_the_range_is_inclusive(self):
        self.make()
        d = datetime.date
        files, _ = cs.log_files(self.tmp, newest_first=True)
        self.assertEqual(self.dates(files), ["2026-11-17", "2026-11-16", "2026-11-15"])
        files, _ = cs.log_files(self.tmp, d(2026, 11, 16), d(2026, 11, 17))
        self.assertEqual(self.dates(files), ["2026-11-16", "2026-11-17"])
        files, _ = cs.log_files(self.tmp, d(2026, 11, 16), d(2026, 11, 16))
        self.assertEqual(self.dates(files), ["2026-11-16"])
        self.assertEqual(cs.log_files(self.tmp, d(2027, 1, 1), d(2027, 1, 2))[0], [])

    def test_no_log_folder_is_nothing_to_read_and_no_problem(self):
        self.assertEqual(cs.log_files(self.tmp), ([], None))
        (self.tmp / "crawl").mkdir()
        self.assertEqual(cs.log_files(self.tmp), ([], None))

    def test_a_log_folder_that_is_a_link_or_a_crawl_folder_that_is_a_file_is_a_problem_and_is_not_read(self):
        real = self.tmp / "elsewhere"
        real.mkdir()
        (real / "crawl-2026-11-16.jsonl").write_text("x\n")
        (self.tmp / "crawl").mkdir()
        os.symlink(real, self.tmp / "crawl" / "log")
        files, problem = cs.log_files(self.tmp)
        self.assertEqual(files, [])
        self.assertTrue(problem)
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        (other / "crawl").write_text("x")
        self.assertEqual(cs.log_files(other)[0], [])
        self.assertTrue(cs.log_files(other)[1])

    def test_a_folder_of_another_owner_is_a_problem_and_is_not_read(self):
        self.make()
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            files, problem = cs.log_files(self.tmp)
        self.assertEqual(files, [])
        self.assertTrue(problem)

    def test_the_dates_must_be_dates(self):
        for bad in ("2026-11-16", 5, datetime.datetime(2026, 11, 16)):
            with self.subTest(first=bad), self.assertRaises(KbError):
                cs.log_files(self.tmp, bad, None)


class DayTest(Base):
    D = datetime.date

    def utc(self, text):
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)

    def test_the_bounds_of_a_day_in_utc_and_in_other_zones(self):
        cases = [("UTC", self.D(2026, 11, 16), "2026-11-16T00:00:00Z", "2026-11-17T00:00:00Z"),
                 ("America/New_York", self.D(2026, 11, 16), "2026-11-16T05:00:00Z", "2026-11-17T05:00:00Z"),
                 ("Pacific/Auckland", self.D(2026, 11, 16), "2026-11-15T11:00:00Z", "2026-11-16T11:00:00Z")]
        for zone, day, start, end in cases:
            with self.subTest(zone=zone):
                self.assertEqual(cs.day_bounds(day, zone), (self.utc(start), self.utc(end)))

    def test_a_day_with_a_change_of_clock_is_23_or_25_hours_long(self):
        for day, hours in ((self.D(2026, 3, 29), 23), (self.D(2026, 10, 25), 25), (self.D(2026, 3, 28), 24)):
            with self.subTest(day=day):
                start, end = cs.day_bounds(day, "Europe/London")
                self.assertEqual((end - start).total_seconds() / 3600, hours)

    def test_the_local_zone_is_the_machines(self):
        old = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old is not None else os.environ.pop("TZ", None), time.tzset()))
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        self.assertEqual(cs.day_bounds(self.D(2026, 11, 16), "local"), (self.utc("2026-11-16T05:00:00Z"), self.utc("2026-11-17T05:00:00Z")))

    def test_a_zone_that_is_not_known_or_not_a_name_is_refused(self):
        for zone in ("Mars/Olympus", "../etc/passwd", "", None, 5, "America/New_York\n", "a" * 500):
            with self.subTest(zone=zone), self.assertRaises(KbError):
                cs.day_bounds(self.D(2026, 11, 16), zone)

    def test_the_day_must_be_a_date(self):
        for bad in ("2026-11-16", None, datetime.datetime(2026, 11, 16, 1, 0)):
            with self.subTest(day=bad), self.assertRaises(KbError):
                cs.day_bounds(bad, "UTC")

    def test_the_lines_of_a_local_day_come_from_two_utc_day_files_and_are_counted_by_their_ts(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertEqual([x["ts"] for x in r["lines"]], [
            "2026-11-16T05:00:00Z", "2026-11-16T05:00:05Z", "2026-11-16T05:01:00Z", "2026-11-16T05:01:02Z",
            "2026-11-16T12:00:00Z", "2026-11-16T23:59:59Z", "2026-11-17T04:59:59Z"])
        self.assertEqual([d.isoformat() for d in r["dates"]], ["2026-11-16", "2026-11-17"])
        self.assertEqual((r["bad"], r["cut"], r["problem"]), ({}, False, None))
        self.assertEqual((r["first"], r["last"]), ("2026-11-16T05:00:00Z", "2026-11-17T04:59:59Z"))

    def test_a_line_exactly_at_the_start_belongs_to_the_day_and_one_exactly_at_the_end_to_the_next(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        first = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertIn("2026-11-16T05:00:00Z", [x["ts"] for x in first["lines"]])
        self.assertNotIn("2026-11-17T05:00:00Z", [x["ts"] for x in first["lines"]])
        second = cs.lines_of_day(root, self.D(2026, 11, 17), "America/New_York")
        self.assertEqual([x["run"] for x in second["lines"]], ["r3"])

    def test_the_day_is_the_plans_zone_and_not_the_file_name(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        r = cs.lines_of_day(root, self.D(2026, 11, 15), "America/New_York")  # 05:00Z on the 15th to 05:00Z on the 16th
        self.assertEqual([x["run"] for x in r["lines"]], ["r1"])
        self.assertEqual([d.isoformat() for d in r["dates"]], ["2026-11-15", "2026-11-16"][1:])  # only the 16th file exists

    def test_a_day_of_23_hours_and_a_day_of_25_hours_take_the_lines_that_are_theirs(self):
        for day, files, inside, outside in (
                (self.D(2026, 3, 29), ("2026-03-29", "2026-03-30"),
                 ("2026-03-29T00:00:00Z", "2026-03-29T22:59:59Z"), ("2026-03-28T23:59:59Z", "2026-03-29T23:00:00Z")),
                (self.D(2026, 10, 25), ("2026-10-24", "2026-10-25", "2026-10-26"),
                 ("2026-10-24T23:00:00Z", "2026-10-25T23:59:59Z"), ("2026-10-24T22:59:59Z", "2026-10-26T00:00:00Z"))):
            with self.subTest(day=day):
                root = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, root, True)
                (root / "crawl" / "log").mkdir(parents=True)
                for name in files:
                    stamps = [t for t in inside + outside if t.startswith(name)]
                    (root / "crawl" / "log" / f"crawl-{name}.jsonl").write_bytes(
                        b"".join(raw(ts=t, run=t) + b"\n" for t in stamps))
                r = cs.lines_of_day(root, day, "Europe/London")
                self.assertEqual(sorted(x["ts"] for x in r["lines"]), sorted(inside))

    def test_files_outside_the_range_are_not_read(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "UTC")
        self.assertEqual([d.isoformat() for d in r["dates"]], ["2026-11-16"])
        self.assertNotIn("r3", [x["run"] for x in r["lines"]])

    def test_lines_are_in_order_of_ts_across_files(self):
        root = self.root_with_log()
        log = root / "crawl" / "log"
        (log / "crawl-2026-11-16.jsonl").write_bytes(raw(ts="2026-11-16T23:00:00Z", run="late") + b"\n")
        (log / "crawl-2026-11-17.jsonl").write_bytes(raw(ts="2026-11-16T22:00:00Z", run="early") + b"\n")
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertEqual([x["run"] for x in r["lines"]], ["early", "late"])

    def test_bad_lines_are_counted_over_all_the_files_read(self):
        root = self.root_with_log()
        log = root / "crawl" / "log"
        (log / "crawl-2026-11-16.jsonl").write_bytes(b"junk\n" + raw(ts="2026-11-16T23:00:00Z") + b"\n")
        (log / "crawl-2026-11-17.jsonl").write_bytes(b"junk\n" + raw(step="dance") + b"\n")
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertEqual((len(r["lines"]), r["bad"]), (1, {"not_json": 2, "bad_step": 1}))

    def test_a_file_over_the_limit_is_said_to_be_cut(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl",))
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "UTC", limit=300)
        self.assertTrue(r["cut"])

    def test_the_cut_of_any_one_file_is_kept_when_a_later_file_is_not_cut(self):
        root = self.root_with_log()
        log = root / "crawl" / "log"
        many = b"\n".join(raw(ts="2026-11-16T23:00:00Z", run=f"r{i}") for i in range(50)) + b"\n"
        (log / "crawl-2026-11-16.jsonl").write_bytes(many)
        (log / "crawl-2026-11-17.jsonl").write_bytes(raw(ts="2026-11-17T01:00:00Z") + b"\n")
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York", limit=len(raw()) + 5)
        self.assertTrue(r["cut"])

    def test_a_file_that_cannot_be_read_is_counted_and_the_others_are_still_read(self):
        if os.getuid() == 0:
            self.skipTest("the superuser reads any file")
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        os.chmod(root / "crawl" / "log" / "crawl-2026-11-16.jsonl", 0)
        self.addCleanup(os.chmod, root / "crawl" / "log" / "crawl-2026-11-16.jsonl", 0o600)
        r = cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertEqual(r["unreadable"], 1)
        self.assertEqual([d.isoformat() for d in r["dates"]], ["2026-11-17"])

    def test_no_log_is_an_empty_day_and_a_link_folder_is_a_problem(self):
        r = cs.lines_of_day(self.tmp, self.D(2026, 11, 16), "UTC")
        self.assertEqual((r["lines"], r["problem"], r["dates"]), ([], None, []))
        (self.tmp / "elsewhere").mkdir()
        (self.tmp / "crawl").mkdir()
        os.symlink(self.tmp / "elsewhere", self.tmp / "crawl" / "log")
        r = cs.lines_of_day(self.tmp, self.D(2026, 11, 16), "UTC")
        self.assertEqual(r["lines"], [])
        self.assertTrue(r["problem"])

    def test_nothing_is_written(self):
        root = self.root_with_log(("crawl-2026-11-16.jsonl", "crawl-2026-11-17.jsonl"))
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in root.rglob("*"))
        cs.lines_of_day(root, self.D(2026, 11, 16), "America/New_York")
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in root.rglob("*")), before)


UTC = datetime.timezone.utc
DIGEST = "0123456789abcdef0123456789abcdef"
HOLDER = """
import fcntl, os, sys
path, content, mode = sys.argv[1], bytes.fromhex(sys.argv[2]), sys.argv[3]
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, (fcntl.LOCK_EX if mode == "ex" else fcntl.LOCK_SH) | fcntl.LOCK_NB)
if content:
    os.write(fd, content)
print("ready", flush=True)
sys.stdin.read()
"""
GOOD_BREAKER = {"tripped": True, "reason": "r", "kind": "stage_bound", "at": "2026-11-16T05:30:00Z", "run": "r2"}


def breaker_with(**over):
    d = dict(GOOD_BREAKER)
    d.update(over)
    return d


def breaker_without(key):
    d = dict(GOOD_BREAKER)
    del d[key]
    return d


class StateBase(Base):
    def crawl(self):
        folder = self.tmp / "crawl"
        folder.mkdir(exist_ok=True)
        return folder

    def put_breaker(self, data):
        (self.crawl() / "breaker.json").write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    def good_breaker(self):
        shutil.copy(FIX / "state" / "breaker-not-tripped.json", self.crawl() / "breaker.json")

    def no_root_powers(self):
        if os.getuid() == 0:
            self.skipTest("the superuser is not stopped by a folder's permissions")

    def hold(self, content=b"", mode="ex"):
        """A real second process that holds `crawl.lock` (exclusively, or shared) and writes `content` into it."""
        proc = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, str(self.tmp / "crawl.lock"), content.hex(), mode],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def stop():
            proc.stdin.close()
            proc.wait(10)
            proc.stdout.close()
            proc.stderr.close()

        self.addCleanup(stop)
        line = self.within(proc.stdout.readline)
        if line.strip() != "ready":
            self.fail("the second process did not take the lock")
        return proc


class BreakerTest(StateBase):
    def test_a_missing_file_is_paused_as_missing_and_so_is_a_missing_crawl_folder(self):
        for make in (lambda: None, lambda: self.crawl()):
            make()
            r = cs.breaker_state(self.tmp)
            self.assertEqual((r["state"], r["paused"]), ("missing", True))
            self.assertEqual([r[k] for k in ("reason", "kind", "at", "run")], [None] * 4)

    def test_a_file_that_vanishes_between_the_look_and_the_read_is_missing(self):
        self.good_breaker()
        with mock.patch.object(cs, "read_small", return_value=cs.FileRead(None, "missing", None, False)):
            r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"]), ("missing", True))

    def test_a_run_id_as_long_as_a_log_field_is_taken(self):
        self.put_breaker(breaker_with(run="r" * cs.MAX_FIELD))
        r = cs.breaker_state(self.tmp)
        self.assertEqual(r["state"], "tripped")
        self.assertEqual(len(r["run"]), 200)  # shown cut, as every text is

    def test_a_crawl_folder_that_is_a_link_or_not_the_owners_is_not_trusted(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        shutil.copy(FIX / "state" / "breaker-not-tripped.json", elsewhere / "breaker.json")
        os.symlink(elsewhere, self.tmp / "crawl")
        r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"]), ("cannot_examine", True))
        os.unlink(self.tmp / "crawl")
        self.good_breaker()
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"]), ("cannot_examine", True))

    def test_a_file_that_cannot_be_examined_is_paused(self):
        self.no_root_powers()
        self.good_breaker()
        folder = self.tmp / "crawl"
        os.chmod(folder, 0)
        self.addCleanup(os.chmod, folder, 0o700)
        r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"]), ("cannot_examine", True))

    def test_a_crawl_that_is_a_file_cannot_be_examined_either(self):
        (self.tmp / "crawl").write_text("x")
        r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"]), ("cannot_examine", True))

    def test_a_file_that_cannot_be_read_in_the_form_is_paused(self):
        cases = [b"", b"   \n", b"not json", b"[]", b"5", b'"text"', b"null", b"{", b"SECRET not json",
                 json.dumps({"reason": "x"}).encode()]
        cases += [json.dumps(breaker_with(tripped=v)).encode() for v in ("true", "false", 0, 1, None, [], {})]
        cases += [json.dumps(breaker_without(k)).encode() for k in ("tripped", "reason", "kind", "at", "run")]
        cases += [json.dumps(breaker_with(**{k: v})).encode() for k in ("reason", "kind", "at", "run") for v in (None, 5, True, [], {})]
        cases += [json.dumps(breaker_with(reason="x" * 301)).encode(), json.dumps(breaker_with(kind="other")).encode(),
                  json.dumps(breaker_with(kind="CONSECUTIVE_FAILURES")).encode(), json.dumps(breaker_with(at="2026-11-16")).encode(),
                  json.dumps(breaker_with(at="yesterday")).encode(), json.dumps(breaker_with(at="2026-11-16T05:30:00.5Z")).encode(),
                  json.dumps(breaker_with(run="r" * (cs.MAX_FIELD + 1))).encode(),
                  b'{"tripped": false, "reason": "", "kind": "", "at": "", "run": "", "extra": NaN}',
                  b'{"tripped": false, "reason": "", "kind": "", "at": "", "run": "", "extra": 1, "extra": 2}',
                  json.dumps(breaker_with(at="2026-1-6T5:0:0Z")).encode(),
                  json.dumps(breaker_with(at=chr(0xFF12) + "026-11-16T05:30:00Z")).encode(),
                  json.dumps(breaker_with(at="2026-13-45T05:30:00Z")).encode(),
                  json.dumps(GOOD_BREAKER).encode() + b" " * cs.MAX_SMALL,
                  b'{"tripped": true, "tripped": false, "reason": "", "kind": "", "at": "", "run": ""}',
                  b'{"tripped": NaN, "reason": "", "kind": "", "at": "", "run": ""}',
                  b'{"tripped": false, "reason": "\\ud800", "kind": "", "at": "", "run": ""}',
                  b"\xff\xfe" + json.dumps(GOOD_BREAKER).encode(), json.dumps(GOOD_BREAKER).encode().replace(b"r2", b"r\x002"),
                  b" " * (cs.MAX_SMALL + 1)]
        for data in cases:
            with self.subTest(data=data[:60]):
                self.put_breaker(data)
                r = cs.breaker_state(self.tmp)
                self.assertEqual((r["state"], r["paused"]), ("cannot_read", True))
                self.assertNotIn("SECRET", repr(r))

    def test_a_link_a_folder_and_a_pipe_cannot_be_read(self):
        crawl = self.crawl()
        (self.tmp / "real.json").write_text(json.dumps(GOOD_BREAKER))
        for make in (lambda p: os.symlink(self.tmp / "real.json", p), lambda p: os.symlink(self.tmp / "nowhere", p),
                     lambda p: p.mkdir(), lambda p: os.mkfifo(p)):
            path = crawl / "breaker.json"
            make(path)
            r = self.within(lambda: cs.breaker_state(self.tmp))
            self.assertEqual((r["state"], r["paused"]), ("cannot_read", True))
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()

    def test_a_file_that_says_tripped_true_is_paused_with_its_fields_for_each_kind(self):
        for kind in ("consecutive_failures", "failure_share", "model_down", "stage_bound", ""):
            with self.subTest(kind=kind):
                self.put_breaker(breaker_with(kind=kind))
                r = cs.breaker_state(self.tmp)
                self.assertEqual((r["state"], r["paused"], r["kind"]), ("tripped", True, kind))
                self.assertEqual((r["reason"], r["at"], r["run"]), ("r", "2026-11-16T05:30:00Z", "r2"))

    def test_the_fixture_that_says_tripped_true(self):
        self.crawl()
        shutil.copy(FIX / "state" / "breaker-tripped.json", self.tmp / "crawl" / "breaker.json")
        r = cs.breaker_state(self.tmp)
        self.assertEqual((r["state"], r["paused"], r["reason"], r["kind"], r["run"]), ("tripped", True, "8 failures in a row", "consecutive_failures", "r2"))

    def test_only_a_file_that_says_tripped_false_is_not_paused(self):
        for name in ("breaker-not-tripped.json", "breaker-cleared.json"):
            with self.subTest(name=name):
                self.crawl()
                shutil.copy(FIX / "state" / name, self.tmp / "crawl" / "breaker.json")
                r = cs.breaker_state(self.tmp)
                self.assertEqual((r["state"], r["paused"]), ("not_tripped", False))
        self.assertEqual(r["reason"], "cleared by the owner")

    def test_the_old_wording_is_wrong_a_file_that_exists_is_not_paused_and_a_missing_one_is(self):
        self.good_breaker()
        self.assertFalse(cs.breaker_state(self.tmp)["paused"])
        (self.tmp / "crawl" / "breaker.json").unlink()
        self.assertTrue(cs.breaker_state(self.tmp)["paused"])

    def test_the_fields_of_a_tripped_file_are_redacted_and_cleaned_and_other_keys_are_not_shown(self):
        self.put_breaker({**breaker_with(reason="a" + RLO + "b\nc" + ZWSP, run="r" + chr(0x1b) + "2"), "extra": "SECRET"})
        r = cs.breaker_state(self.tmp)
        self.assertEqual((r["reason"], r["run"]), ("ab c", "r2"))
        self.assertNotIn("SECRET", repr(r))
        self.put_breaker(breaker_with(reason="Cookie: sid=abc"))
        self.assertEqual(cs.breaker_state(self.tmp)["reason"], cs.WITHHELD)

    def test_the_file_is_opened_once_and_nothing_is_written(self):
        self.put_breaker(GOOD_BREAKER)
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in self.tmp.rglob("*"))
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)

        with mock.patch.object(os, "open", spy):
            cs.breaker_state(self.tmp)
        self.assertEqual([x for x in opened if x.endswith("breaker.json")], [str(self.tmp / "crawl" / "breaker.json")])
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in self.tmp.rglob("*")), before)


class LockTest(StateBase):
    LINE = b"4242 2026-11-16T05:00:00Z\n"

    def test_a_lock_held_by_another_process_is_running_and_its_line_names_the_holder(self):
        self.hold(self.LINE)
        r = cs.lock_state(self.tmp)
        self.assertEqual((r["held"], r["fault"]), (True, None))
        self.assertEqual(r["holder"], {"pid": 4242, "since": "2026-11-16T05:00:00Z"})

    def test_a_line_without_a_final_line_feed_is_taken(self):
        self.hold(b"4242 2026-11-16T05:00:00Z")
        self.assertEqual(cs.lock_state(self.tmp)["holder"], {"pid": 4242, "since": "2026-11-16T05:00:00Z"})

    def test_a_line_that_is_missing_or_wrong_still_means_held_and_the_holder_is_unknown(self):
        cases = [b"", b"\n", b"garbage\n", b"4242\n", b"4242 2026-11-16T05:00:00Z extra\n", b"abc 2026-11-16T05:00:00Z\n",
                 b"0 2026-11-16T05:00:00Z\n", b"-5 2026-11-16T05:00:00Z\n", b"4242 2026-13-45T05:00:00Z\n", b"4242 2026-11-16T05:00:00\n",
                 b"4242 2026-11-16T05:00:00Z\n4243 2026-11-16T06:00:00Z\n", b"x" * 1000, b"\xff\xfe\n", b"99999999999 2026-11-16T05:00:00Z\n",
                 b"4242 2026-11-16T05:00:00Z\r\n", b" 4242 2026-11-16T05:00:00Z\n", b"4242  2026-11-16T05:00:00Z\n",
                 b"4242 2026-11-16T05:00:00Z\n\n", b"4242 2026-11-16T05:00:00Z\nx",
                 b"4242 2026-11-16T05:00:00Z" + b" " * 300, b"\x004242 2026-11-16T05:00:00Z\n"]
        for content in cases:
            with self.subTest(content=content[:40]):
                proc = self.hold(content)
                r = cs.lock_state(self.tmp)
                self.assertEqual((r["held"], r["holder"], r["fault"]), (True, "unknown", None))
                proc.stdin.close()
                proc.wait(10)
                (self.tmp / "crawl.lock").unlink()

    def test_at_most_256_bytes_of_the_line_are_read(self):
        self.hold(b"4" * 10_000)
        sizes = []
        real = os.pread

        def spy(fd, n, offset):
            sizes.append(n)
            return real(fd, n, offset)

        with mock.patch.object(os, "pread", spy):
            r = cs.lock_state(self.tmp)
        self.assertEqual(r["holder"], "unknown")
        self.assertTrue(sizes and max(sizes) <= 257, sizes)

    def test_a_free_lock_is_not_held_and_a_line_left_in_it_is_not_read(self):
        (self.tmp / "crawl.lock").write_bytes(self.LINE)
        r = cs.lock_state(self.tmp)
        self.assertEqual((r["held"], r["holder"], r["fault"]), (False, None, None))

    def test_no_lock_file_is_not_held_and_is_not_made(self):
        r = cs.lock_state(self.tmp)
        self.assertEqual((r["held"], r["holder"], r["fault"]), (False, None, None))
        self.assertFalse((self.tmp / "crawl.lock").exists())

    def test_the_shared_attempt_is_let_go_at_once(self):
        (self.tmp / "crawl.lock").write_bytes(b"")
        cs.lock_state(self.tmp)
        fd = os.open(self.tmp / "crawl.lock", os.O_RDONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if the status still holds its shared lock

    def test_a_process_that_only_reads_the_lock_does_not_make_it_look_held(self):
        self.hold(b"", mode="sh")
        self.assertEqual(cs.lock_state(self.tmp)["held"], False)

    def test_a_link_a_folder_and_a_pipe_are_not_opened_and_are_a_fault_and_not_running(self):
        (self.tmp / "real").write_bytes(self.LINE)
        for make in (lambda p: os.symlink(self.tmp / "real", p), lambda p: p.mkdir(), lambda p: os.mkfifo(p)):
            path = self.tmp / "crawl.lock"
            make(path)
            r = self.within(lambda: cs.lock_state(self.tmp))
            self.assertEqual((r["held"], r["holder"]), (False, None))
            self.assertTrue(r["fault"])
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()

    def test_a_lock_of_another_owner_is_a_fault(self):
        (self.tmp / "crawl.lock").write_bytes(b"")
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            r = cs.lock_state(self.tmp)
        self.assertEqual((r["held"], r["holder"]), (False, None))
        self.assertTrue(r["fault"])

    def test_a_lock_the_system_cannot_try_is_unknown_and_not_running(self):
        (self.tmp / "crawl.lock").write_bytes(b"")
        with mock.patch.object(fcntl, "flock", side_effect=OSError(errno.ENOLCK, "no locks")):
            r = cs.lock_state(self.tmp)
        self.assertEqual((r["held"], r["holder"]), (None, None))
        self.assertTrue(r["fault"])

    def test_the_file_is_opened_read_only_and_never_created(self):
        (self.tmp / "crawl.lock").write_bytes(b"")
        seen = []
        real = os.open

        def spy(path, flags, *a, **k):
            seen.append(flags)
            return real(path, flags, *a, **k)

        with mock.patch.object(os, "open", spy):
            cs.lock_state(self.tmp)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0] & os.O_ACCMODE, os.O_RDONLY)
        for forbidden in (os.O_CREAT, os.O_TRUNC, os.O_APPEND, os.O_WRONLY, os.O_RDWR):
            self.assertFalse(seen[0] & forbidden)
        self.assertTrue(seen[0] & os.O_NOFOLLOW and seen[0] & os.O_NONBLOCK)


class StateTest(StateBase):
    def test_idle_needs_a_breaker_file_that_says_not_tripped(self):
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"]), ("paused", False))  # no breaker file reads as tripped
        self.good_breaker()
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"], r["stop"]["present"]), ("idle", False, False))
        self.assertEqual(r["breaker"]["state"], "not_tripped")

    def test_running_when_another_process_holds_the_lock(self):
        self.good_breaker()
        self.hold(b"4242 2026-11-16T05:00:00Z\n")
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"]), ("running", True))
        self.assertEqual(r["lock"]["holder"], {"pid": 4242, "since": "2026-11-16T05:00:00Z"})

    def test_running_with_an_unknown_holder_is_still_running(self):
        self.good_breaker()
        self.hold(b"")
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["lock"]["holder"]), ("running", "unknown"))

    def test_a_tripped_breaker_is_paused_even_while_a_run_holds_the_lock(self):
        self.put_breaker(GOOD_BREAKER)
        self.hold(b"4242 2026-11-16T05:00:00Z\n")
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"], r["breaker"]["state"]), ("paused", True, "tripped"))

    def test_the_stop_file_is_stopped_before_everything_else_and_the_other_facts_stay(self):
        self.put_breaker(GOOD_BREAKER)
        self.hold(b"4242 2026-11-16T05:00:00Z\n")
        (self.tmp / "crawl.stop").write_text("")
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"], r["stop"]["present"], r["breaker"]["paused"]), ("stopped", True, True, True))

    def test_the_stop_file_counts_by_its_presence_whatever_it_is(self):
        self.good_breaker()
        for make in (lambda p: p.write_text("text"), lambda p: p.write_text(""), lambda p: os.symlink(self.tmp / "nowhere", p),
                     lambda p: p.mkdir(), lambda p: os.mkfifo(p)):
            path = self.tmp / "crawl.stop"
            make(path)
            r = self.within(lambda: cs.state(self.tmp))
            self.assertEqual((r["state"], r["stop"]["present"]), ("stopped", True))
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()

    def test_a_stop_file_that_cannot_be_looked_for_is_a_fault_and_is_not_claimed(self):
        self.no_root_powers()
        self.good_breaker()
        os.chmod(self.tmp, 0)
        self.addCleanup(os.chmod, self.tmp, 0o700)
        r = cs.state(self.tmp)
        self.assertIsNone(r["stop"]["present"])
        self.assertNotEqual(r["state"], "stopped")
        self.assertTrue(r["faults"])

    def test_a_lock_the_system_cannot_tell_about_is_not_called_running(self):
        self.good_breaker()
        with mock.patch.object(cs, "lock_state", return_value={"held": None, "holder": None, "fault": "the lock cannot be tried"}):
            r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"]), ("idle", False))
        self.assertIn("the lock cannot be tried", r["faults"])

    def test_a_lock_that_is_a_fault_is_not_running_and_is_listed(self):
        self.good_breaker()
        (self.tmp / "crawl.lock").mkdir()
        r = cs.state(self.tmp)
        self.assertEqual((r["state"], r["running"]), ("idle", False))
        self.assertTrue(any("lock" in f for f in r["faults"]))

    def test_nothing_is_written(self):
        self.good_breaker()
        (self.tmp / "crawl.lock").write_bytes(b"")
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*"))
        cs.state(self.tmp)
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*")), before)


class ApprovedPlanTest(StateBase):
    VALUES = {"fetches_per_day": 20, "per_domain_per_day": 3, "cards_per_day": 30, "filed_total": 200, "timezone": "Europe/London",
              "bulk_floor_gb": 50, "index_floor_gb": 10.5, "domain_refusals": 3, "phishing_domains": True, "urlhaus_recent": False,
              "threshold": 0.4, "secret_key": "SECRET", "pinned_hosts": ["a.org"]}

    def reader(self):
        calls = []

        def read_plan(path):
            calls.append(path)
            return dict(self.VALUES)

        read_plan.calls = calls
        return read_plan

    def approve(self):
        shutil.copytree(FIX / "approved", self.tmp / "crawl" / "approved")

    def test_an_approved_plan_is_read_through_the_injected_reader(self):
        self.approve()
        read_plan = self.reader()
        r = cs.approved_plan(self.tmp, read_plan)
        self.assertEqual((r["status"], r["digest"], r["reason"]), ("approved", DIGEST, None))
        self.assertEqual(read_plan.calls, [str(self.tmp / "crawl" / "approved" / DIGEST / "plan.txt")])

    def test_only_the_values_the_status_uses_are_kept_and_only_plain_ones(self):
        self.approve()
        r = cs.approved_plan(self.tmp, self.reader())
        self.assertEqual(set(r["values"]), set(cs.PLAN_VALUES) & set(self.VALUES))
        self.assertEqual(r["values"]["timezone"], "Europe/London")
        self.assertNotIn("SECRET", repr(r))
        self.assertNotIn("threshold", r["values"])
        self.assertNotIn("pinned_hosts", r["values"])

    def test_a_value_the_plan_lacks_is_absent_and_not_guessed(self):
        self.approve()
        r = cs.approved_plan(self.tmp, lambda path: {"fetches_per_day": 5})
        self.assertEqual(r["values"], {"fetches_per_day": 5})

    def test_a_value_of_another_kind_is_dropped(self):
        self.approve()
        r = cs.approved_plan(self.tmp, lambda path: {"fetches_per_day": [5], "timezone": {"a": 1}, "filed_total": None, "cards_per_day": 7})
        self.assertEqual(r["values"], {"cards_per_day": 7})

    def test_no_approved_plan_in_each_case_and_the_reader_is_not_called(self):
        def fresh():
            shutil.rmtree(self.tmp / "crawl", ignore_errors=True)
            self.approve()
            return self.tmp / "crawl" / "approved"

        cases = {
            "no folder": lambda a: shutil.rmtree(a),
            "no current": lambda a: (a / "current").unlink(),
            "empty current": lambda a: (a / "current").write_text(""),
            "blank current": lambda a: (a / "current").write_text("\n"),
            "two lines": lambda a: (a / "current").write_text(DIGEST + "\n" + DIGEST + "\n"),
            "a blank second line": lambda a: (a / "current").write_text(DIGEST + "\n\n"),
            "the approved folder is a link": lambda a: (shutil.move(str(a), str(self.tmp / "real-approved")), os.symlink(self.tmp / "real-approved", a)),
            "an upper case folder and digest": lambda a: (shutil.move(str(a / DIGEST), str(a / DIGEST.upper())), (a / "current").write_text(DIGEST.upper() + "\n")),
            "a digest of 31 characters with a folder": lambda a: (shutil.move(str(a / DIGEST), str(a / DIGEST[:31])), (a / "current").write_text(DIGEST[:31])),
            "upper case": lambda a: (a / "current").write_text(DIGEST.upper() + "\n"),
            "31 characters": lambda a: (a / "current").write_text(DIGEST[:31] + "\n"),
            "33 characters": lambda a: (a / "current").write_text(DIGEST + "0\n"),
            "spaces": lambda a: (a / "current").write_text(DIGEST + " \n"),
            "a path": lambda a: (a / "current").write_text("../" * 8 + "etc\n"),
            "not utf-8": lambda a: (a / "current").write_bytes(b"\xff\xfe" + DIGEST.encode()),
            "a folder that is not there": lambda a: (a / "current").write_text("f" * 32 + "\n"),
            "no plan file": lambda a: (a / DIGEST / "plan.txt").unlink(),
            "plan file is a folder": lambda a: ((a / DIGEST / "plan.txt").unlink(), (a / DIGEST / "plan.txt").mkdir()),
            "plan file is a link": lambda a: ((a / DIGEST / "plan.txt").unlink(), os.symlink(self.tmp / "elsewhere", a / DIGEST / "plan.txt")),
            "digest folder is a link": lambda a: (shutil.move(str(a / DIGEST), str(self.tmp / "moved")), os.symlink(self.tmp / "moved", a / DIGEST)),
            "current is a link": lambda a: ((a / "current").unlink(), os.symlink(self.tmp / "elsewhere", a / "current")),
            "current is a folder": lambda a: ((a / "current").unlink(), (a / "current").mkdir()),
        }
        (self.tmp / "elsewhere").write_text(DIGEST + "\n")
        for name, damage in cases.items():
            with self.subTest(case=name):
                read_plan = self.reader()
                damage(fresh())
                r = cs.approved_plan(self.tmp, read_plan)
                self.assertEqual((r["status"], r["digest"], r["values"]), ("none", None, None))
                self.assertTrue(r["reason"])
                self.assertEqual(read_plan.calls, [])

    def test_a_reader_that_fails_is_an_unreadable_plan_with_its_message_cleaned(self):
        self.approve()
        r = cs.approved_plan(self.tmp, mock.Mock(side_effect=KbError("the crawl plan: line 3: bad value")))
        self.assertEqual((r["status"], r["digest"], r["values"]), ("unreadable", DIGEST, None))
        self.assertIn("line 3", r["reason"])
        r = cs.approved_plan(self.tmp, mock.Mock(side_effect=RuntimeError("Cookie: abc" + RLO)))
        self.assertEqual((r["status"], r["reason"]), ("unreadable", cs.WITHHELD))
        for bad in (None, [], "text", 5):
            with self.subTest(result=bad):
                r = cs.approved_plan(self.tmp, lambda path, b=bad: b)
                self.assertEqual((r["status"], r["values"]), ("unreadable", None))

    def test_nothing_is_written(self):
        self.approve()
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in self.tmp.rglob("*"))
        cs.approved_plan(self.tmp, self.reader())
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode) for p in self.tmp.rglob("*")), before)

    def test_a_crawl_folder_that_is_a_link_leads_to_no_approved_plan(self):
        (self.tmp / "elsewhere").mkdir()
        shutil.copytree(FIX / "approved", self.tmp / "elsewhere" / "approved")
        os.symlink(self.tmp / "elsewhere", self.tmp / "crawl")
        read_plan = self.reader()
        r = cs.approved_plan(self.tmp, read_plan)
        self.assertEqual((r["status"], r["values"]), ("none", None))
        self.assertEqual(read_plan.calls, [])

    def test_the_zone_of_a_plan_that_cannot_be_read_or_names_a_zone_the_system_lacks_is_local_with_a_problem(self):
        self.approve()
        zone, problem = cs.zone_of(cs.approved_plan(self.tmp, mock.Mock(side_effect=KbError("bad line"))))
        self.assertEqual(zone, "local")
        self.assertTrue(problem)
        zone, problem = cs.zone_of(cs.approved_plan(self.tmp, lambda p: {"timezone": "Mars/Olympus"}))
        self.assertEqual(zone, "local")
        self.assertTrue(problem)
        self.assertEqual(cs.zone_of(cs.approved_plan(self.tmp, lambda p: {"timezone": "local"})), ("local", None))
        self.assertEqual(cs.zone_of(cs.approved_plan(self.tmp, lambda p: {"timezone": "UTC"})), ("UTC", None))

    def test_the_zone_is_the_plans_and_local_without_one(self):
        self.approve()
        self.assertEqual(cs.zone_of(cs.approved_plan(self.tmp, self.reader())), ("Europe/London", None))
        self.assertEqual(cs.zone_of(cs.approved_plan(self.tmp, lambda p: {"fetches_per_day": 5})), ("local", None))
        self.assertEqual(cs.zone_of({"status": "none", "values": None}), ("local", None))
        zone, problem = cs.zone_of(cs.approved_plan(self.tmp, lambda p: {"timezone": 5}))
        self.assertEqual(zone, "local")
        self.assertIn("not text", problem)
        self.assertEqual(cs.zone_of({"status": "unreadable", "values": None})[0], "local")
        self.assertTrue(cs.zone_of({"status": "unreadable", "values": None})[1])


class DiskTest(Base):
    GIB = 1024 ** 3

    def vfs(self, free_bytes, frsize=4096):
        return types.SimpleNamespace(f_bavail=free_bytes // frsize, f_bfree=free_bytes * 2 // frsize, f_frsize=frsize)

    def test_the_free_bytes_are_what_a_user_can_use_times_the_block_size(self):
        r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": 1, "index_floor_gb": 1},
                    statvfs=lambda path: types.SimpleNamespace(f_bavail=5, f_bfree=99, f_frsize=1024))
        self.assertEqual((r["bulk"]["free_bytes"], r["index"]["free_bytes"]), (5120, 5120))

    def test_the_edge_of_a_floor(self):
        floors = {"bulk_floor_gb": 1, "index_floor_gb": 1}
        for free, below, at_or_under in ((self.GIB + 4096, False, False), (self.GIB, False, True), (self.GIB - 4096, True, True)):
            with self.subTest(free=free):
                r = cs.disk(self.tmp, self.tmp, floors, statvfs=lambda path, f=free: self.vfs(f))
                for side in ("bulk", "index"):
                    self.assertEqual((r[side]["floor_bytes"], r[side]["below_floor"], r[side]["at_or_under_floor"]), (self.GIB, below, at_or_under))

    def test_each_root_has_its_own_floor(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        free = {str(self.tmp): 60 * self.GIB, str(other): 5 * self.GIB}
        r = cs.disk(self.tmp, other, {"bulk_floor_gb": 50, "index_floor_gb": 10}, statvfs=lambda path: self.vfs(free[str(path)]))
        self.assertEqual((r["bulk"]["below_floor"], r["index"]["below_floor"]), (False, True))
        self.assertEqual((r["bulk"]["floor_bytes"], r["index"]["floor_bytes"]), (50 * self.GIB, 10 * self.GIB))

    def test_a_fraction_of_a_gigabyte_is_a_floor(self):
        r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": 0.5, "index_floor_gb": 0}, statvfs=lambda path: self.vfs(self.GIB))
        self.assertEqual((r["bulk"]["floor_bytes"], r["index"]["floor_bytes"]), (self.GIB // 2, 0))
        self.assertEqual((r["index"]["below_floor"], r["index"]["at_or_under_floor"]), (False, False))

    def test_a_reading_that_fails_is_unknown_and_says_why(self):
        def broken(path):
            raise OSError(errno.ENOENT, "No such file" + RLO)

        r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": 1, "index_floor_gb": 1}, statvfs=broken)
        for side in ("bulk", "index"):
            self.assertEqual((r[side]["free_bytes"], r[side]["below_floor"], r[side]["at_or_under_floor"]), (None, None, None))
            self.assertIn("No such file", r[side]["reason"])
            self.assertNotIn(RLO, r[side]["reason"])

    def test_a_floor_that_is_not_known_is_none_and_the_free_bytes_are_still_given(self):
        r = cs.disk(self.tmp, self.tmp, {}, statvfs=lambda path: self.vfs(self.GIB))
        self.assertEqual((r["bulk"]["free_bytes"], r["bulk"]["floor_bytes"], r["bulk"]["below_floor"]), (self.GIB, None, None))
        r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": "50", "index_floor_gb": True}, statvfs=lambda path: self.vfs(self.GIB))
        self.assertEqual((r["bulk"]["floor_bytes"], r["index"]["floor_bytes"]), (None, None))

    def test_a_floor_that_is_negative_or_not_a_number_is_not_a_floor(self):
        for bad in (-1, -0.5, float("inf"), float("nan")):
            with self.subTest(floor=bad):
                r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": bad, "index_floor_gb": bad}, statvfs=lambda path: self.vfs(self.GIB))
                self.assertEqual((r["bulk"]["floor_bytes"], r["bulk"]["below_floor"]), (None, None))

    def test_two_roots_on_one_device_are_said_to_be_one(self):
        other = self.tmp / "sub"
        other.mkdir()
        self.assertTrue(cs.disk(self.tmp, other, {}, statvfs=lambda path: self.vfs(1))["same_device"])
        with mock.patch.object(cs.os, "stat", side_effect=[types.SimpleNamespace(st_dev=1), types.SimpleNamespace(st_dev=2)]):
            self.assertFalse(cs.disk(self.tmp, other, {}, statvfs=lambda path: self.vfs(1))["same_device"])

    def test_the_real_reading_is_used_by_default_and_gives_numbers(self):
        r = cs.disk(self.tmp, self.tmp, {"bulk_floor_gb": 0, "index_floor_gb": 0})
        self.assertIsInstance(r["bulk"]["free_bytes"], int)
        self.assertGreater(r["bulk"]["free_bytes"], 0)


class RunsTest(StateBase):
    NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)

    def put_log(self, date, *records):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"crawl-{date}.jsonl").write_bytes(b"".join(raw(**r) + b"\n" for r in records))

    def run_lines(self, with_refusals):
        lines = [dict(ts="2026-11-16T05:00:00Z", run="r1", step="run_start"), dict(ts="2026-11-16T05:10:00Z", run="r1", step="run_end", n=3),
                 dict(ts="2026-11-16T06:00:00Z", run="r2", step="run_start"),
                 dict(ts="2026-11-16T06:20:00Z", run="r2", step="run_end", outcome="failed", reason="the breaker tripped", n=1, seconds=1200.5)]
        if with_refusals:
            lines += [dict(ts="2026-11-16T04:00:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress"),
                      dict(ts="2026-11-16T05:05:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress"),
                      dict(ts="2026-11-16T05:30:00Z", run="", step="refuse", outcome="refused", reason="the stop file exists"),
                      dict(ts="2026-11-16T07:00:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress"),
                      dict(ts="2026-11-16T08:00:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress" + ZWSP)]
        return sorted(lines, key=lambda r: r["ts"])

    def test_the_last_run_is_the_newest_run_start_with_its_end_line(self):
        self.put_log("2026-11-16", *self.run_lines(False))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["found"], r["run"], r["start"], r["status"]), (True, "r2", "2026-11-16T06:00:00Z", "ended"))
        self.assertEqual((r["end"], r["end_outcome"], r["end_reason"], r["end_n"]), ("2026-11-16T06:20:00Z", "failed", "the breaker tripped", 1))
        self.assertEqual(r["age_s"], 6 * 3600)

    def test_a_run_with_no_end_line_says_so(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="r2", step="run_start"))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["run"], r["status"], r["end"]), ("r2", "no end line", None))

    def test_refused_firings_are_not_runs_they_change_neither_the_last_run_nor_the_counts(self):
        plain, with_refusals = self.tmp, Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, with_refusals, True)
        self.put_log("2026-11-16", *self.run_lines(False))
        folder = with_refusals / "crawl" / "log"
        folder.mkdir(parents=True)
        (folder / "crawl-2026-11-16.jsonl").write_bytes(b"".join(raw(**r) + b"\n" for r in self.run_lines(True)))
        run_fields = ("found", "run", "start", "end", "status", "end_outcome", "end_reason", "end_n", "end_seconds", "age_s", "stopped_by")
        a, b = cs.last_run(plain, self.NOW), cs.last_run(with_refusals, self.NOW)
        self.assertEqual({k: a[k] for k in run_fields}, {k: b[k] for k in run_fields})
        self.assertEqual(a["run"], "r2")
        a = cs.run_counts(plain, datetime.date(2026, 11, 16), "UTC")
        b = cs.run_counts(with_refusals, datetime.date(2026, 11, 16), "UTC")
        self.assertEqual((a["started"], a["ended"]), (2, 2))
        self.assertEqual((b["started"], b["ended"], b["ended_by_outcome"]), (2, 2, {"ok": 1, "failed": 1}))
        self.assertEqual(a["refused"], 0)
        self.assertEqual((b["refused"], b["refused_by_reason"]), (5, {"a run is in progress": 4, "the stop file exists": 1}))

    def test_a_refusal_newer_than_the_last_run_does_not_become_the_last_run(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="r2", step="run_start"),
                     dict(ts="2026-11-16T11:00:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress"))
        self.assertEqual(cs.last_run(self.tmp, self.NOW)["run"], "r2")

    def test_an_end_line_with_no_start_in_the_files_read_is_ignored(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:20:00Z", run="r0", step="run_end"))
        self.assertEqual(cs.last_run(self.tmp, self.NOW), {**cs.last_run(self.tmp, self.NOW), "found": False})
        self.assertFalse(cs.last_run(self.tmp, self.NOW)["found"])

    def test_a_run_with_two_end_lines_has_the_newest_as_its_end(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="r2", step="run_start"),
                     dict(ts="2026-11-16T06:20:00Z", run="r2", step="run_end", reason="first"),
                     dict(ts="2026-11-16T06:25:00Z", run="r2", step="run_end", reason="second"))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["end"], r["end_reason"]), ("2026-11-16T06:25:00Z", "second"))

    def test_a_log_file_that_cannot_be_read_is_not_counted_among_the_files_read(self):
        self.no_root_powers()
        self.put_log("2026-11-14", dict(ts="2026-11-14T06:00:00Z", run="r1", step="run_start"))
        self.put_log("2026-11-15", dict(ts="2026-11-15T06:00:00Z", run="r2", step="run_start"))
        path = self.tmp / "crawl" / "log" / "crawl-2026-11-15.jsonl"
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["files_read"], r["run"]), (1, "r1"))

    def test_an_end_line_of_another_run_is_not_the_end_of_this_one(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:00:00Z", run="r1", step="run_start"),
                     dict(ts="2026-11-16T06:00:00Z", run="r2", step="run_start"), dict(ts="2026-11-16T06:30:00Z", run="r1", step="run_end"))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["run"], r["status"]), ("r2", "no end line"))

    def test_an_end_line_older_than_its_start_is_not_its_end(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:00:00Z", run="r1", step="run_end"), dict(ts="2026-11-16T06:00:00Z", run="r1", step="run_start"))
        self.assertEqual(cs.last_run(self.tmp, self.NOW)["status"], "no end line")

    def test_two_starts_at_the_same_second_the_later_line_wins(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="first", step="run_start"), dict(ts="2026-11-16T06:00:00Z", run="second", step="run_start"))
        self.assertEqual(cs.last_run(self.tmp, self.NOW)["run"], "second")

    def test_the_newest_run_may_be_in_the_older_file_when_the_newer_has_none(self):
        self.put_log("2026-11-15", dict(ts="2026-11-15T23:00:00Z", run="r9", step="run_start"))
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="", step="refuse", outcome="refused", reason="a run is in progress"))
        self.assertEqual(cs.last_run(self.tmp, self.NOW)["run"], "r9")

    def refusals_only(self, first_day, last_day):
        for day in range(first_day, last_day + 1):
            self.put_log(f"2026-11-{day:02d}", dict(ts=f"2026-11-{day:02d}T06:00:00Z", run="", step="refuse", outcome="refused", reason="the stop file exists"))

    def test_newer_files_that_hold_only_refused_firings_do_not_hide_an_older_run(self):
        self.put_log("2026-11-05", dict(ts="2026-11-05T06:00:00Z", run="r9", step="run_start"), dict(ts="2026-11-05T06:10:00Z", run="r9", step="run_end"))
        self.refusals_only(6, 15)
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["found"], r["run"], r["status"], r["stopped_by"], r["searched_files"]), (True, "r9", "ended", "found", 11))

    def test_the_search_stops_at_the_newest_file_that_has_a_run_and_reads_no_older_one(self):
        self.put_log("2026-11-01", dict(ts="2026-11-01T06:00:00Z", run="old", step="run_start"))
        self.put_log("2026-11-14", dict(ts="2026-11-14T06:00:00Z", run="mid", step="run_start"))
        self.put_log("2026-11-15", dict(ts="2026-11-15T06:00:00Z", run="new", step="run_start"))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["run"], r["stopped_by"], r["searched_files"], r["files_read"]), ("new", "found", 1, 1))

    def test_the_search_is_bounded_by_the_number_of_files_and_says_so(self):
        self.put_log("2026-11-05", dict(ts="2026-11-05T06:00:00Z", run="r9", step="run_start"))
        self.refusals_only(6, 15)
        r = cs.last_run(self.tmp, self.NOW, max_files=3)
        self.assertEqual((r["found"], r["stopped_by"], r["searched_files"]), (False, "max_files", 3))
        r = cs.last_run(self.tmp, self.NOW, max_files=11)
        self.assertEqual((r["found"], r["stopped_by"]), (True, "found"))

    def test_the_search_is_bounded_by_the_bytes_read_and_says_so(self):
        self.put_log("2026-11-05", dict(ts="2026-11-05T06:00:00Z", run="r9", step="run_start"))
        self.refusals_only(6, 15)
        size = (self.tmp / "crawl" / "log" / "crawl-2026-11-15.jsonl").stat().st_size
        r = cs.last_run(self.tmp, self.NOW, max_bytes=size * 3)
        self.assertEqual((r["found"], r["stopped_by"], r["searched_files"]), (False, "max_bytes", 3))

    def test_refused_firings_only_is_no_run_and_says_all_the_files_were_searched(self):
        self.refusals_only(13, 15)
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["found"], r["stopped_by"], r["searched_files"], r["files_read"]), (False, "no_more_files", 3, 3))

    def test_the_bounds_are_whole_numbers_of_at_least_one(self):
        for name in ("max_files", "max_bytes", "limit"):
            for bad in (0, -1, 1.5, "3", None, True):
                with self.subTest(name=name, value=bad), self.assertRaises(KbError):
                    cs.last_run(self.tmp, self.NOW, **{name: bad})

    def test_no_log_is_no_run(self):
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["found"], r["files_read"], r["searched_files"], r["stopped_by"], r["problem"]), (False, 0, 0, "no_more_files", None))

    def test_now_must_be_a_time_with_a_zone(self):
        for bad in (datetime.datetime(2026, 11, 16, 12, 0, 0), "2026-11-16T12:00:00Z", None, 5):
            with self.subTest(now=bad), self.assertRaises(KbError):
                cs.last_run(self.tmp, bad)

    def test_the_commonest_reasons_are_the_ones_listed_and_a_missing_reason_is_said(self):
        lines = [dict(ts=f"2026-11-16T05:{i:02d}:00Z", run="", step="refuse", outcome="refused", reason=f"rare {i}") for i in range(11)]
        lines += [dict(ts=f"2026-11-16T06:{i:02d}:00Z", run="", step="refuse", outcome="refused", reason="common") for i in range(5)]
        lines += [dict(ts="2026-11-16T07:00:00Z", run="", step="refuse", outcome="refused", reason=None),
                  dict(ts="2026-11-16T07:01:00Z", run="", step="refuse", outcome="refused", reason="")]
        self.put_log("2026-11-16", *lines)
        a = cs.run_counts(self.tmp, datetime.date(2026, 11, 16), "UTC")
        self.assertEqual(a["refused"], 18)
        self.assertEqual(len(a["refused_by_reason"]), 10)
        self.assertEqual(a["refused_by_reason"]["common"], 5)
        self.assertEqual(a["refused_by_reason"]["(no reason)"], 2)
        self.assertEqual(list(a["refused_by_reason"])[:2], ["common", "(no reason)"])

    def test_a_start_in_the_future_has_no_age(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T13:00:00Z", run="r2", step="run_start"))
        self.assertIsNone(cs.last_run(self.tmp, self.NOW)["age_s"])

    def test_bad_lines_and_a_cut_are_passed_on_and_the_end_of_a_big_file_is_read(self):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        many = [raw(ts="2026-11-16T05:00:00Z", run=f"r{i}", step="fetch") for i in range(300)]
        tail = [raw(ts="2026-11-16T06:00:00Z", run="rz", step="run_start"), b"junk"]
        (folder / "crawl-2026-11-16.jsonl").write_bytes(b"\n".join(many + tail) + b"\n")
        r = cs.last_run(self.tmp, self.NOW, limit=3000)
        self.assertEqual((r["run"], r["cut"], r["bad"]), ("rz", True, {"not_json": 1}))

    def test_bad_lines_are_counted_over_all_the_files_read_and_one_cut_file_is_said(self):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        big = (b"".join(raw(ts="2026-11-14T05:00:00Z", run=f"r{i}", step="fetch") + b"\n" for i in range(40))
               + raw(ts="2026-11-14T06:00:00Z", run="r1", step="run_start") + b"\njunk\n")
        small = raw(ts="2026-11-15T06:00:00Z", run="", step="refuse", outcome="refused", reason="x") + b"\njunk\n"
        (folder / "crawl-2026-11-14.jsonl").write_bytes(big)
        (folder / "crawl-2026-11-15.jsonl").write_bytes(small)
        r = cs.last_run(self.tmp, self.NOW, limit=len(small) + 20)
        self.assertEqual((r["run"], r["bad"], r["cut"], r["files_read"]), ("r1", {"not_json": 2}, True, 2))

    def test_a_cut_in_the_newest_file_is_said_even_when_an_older_file_that_is_whole_is_read_last(self):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        big = b"".join(raw(ts="2026-11-15T05:00:00Z", run="", step="refuse", outcome="refused", reason="x" * 20) + b"\n" for i in range(60))
        small = raw(ts="2026-11-14T06:00:00Z", run="r1", step="run_start") + b"\n"
        (folder / "crawl-2026-11-15.jsonl").write_bytes(big)
        (folder / "crawl-2026-11-14.jsonl").write_bytes(small)
        r = cs.last_run(self.tmp, self.NOW, limit=len(small) + 100)
        self.assertEqual((r["run"], r["cut"], r["files_read"]), ("r1", True, 2))

    def test_the_end_of_a_run_in_a_newer_file_than_its_start_is_its_end_and_the_search_goes_on_past_it(self):
        self.put_log("2026-11-14", dict(ts="2026-11-14T23:50:00Z", run="r1", step="run_start"))
        self.put_log("2026-11-15", dict(ts="2026-11-15T00:10:00Z", run="r1", step="run_end", outcome="ok", n=7))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["found"], r["run"], r["status"], r["end"], r["end_n"], r["searched_files"]), (True, "r1", "ended", "2026-11-15T00:10:00Z", 7, 2))

    def test_the_text_of_a_reason_and_a_run_is_redacted_and_cleaned(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T06:00:00Z", run="r" + RLO + "2", step="run_start"),
                     dict(ts="2026-11-16T06:10:00Z", run="r" + RLO + "2", step="run_end", reason="Cookie: sid=1"))
        r = cs.last_run(self.tmp, self.NOW)
        self.assertEqual((r["run"], r["end_reason"]), ("r2", cs.WITHHELD))

    def test_the_counts_are_of_the_plans_day_by_ts_and_not_by_the_file(self):
        shutil.copytree(FIX / "log", self.tmp / "crawl" / "log")
        a = cs.run_counts(self.tmp, datetime.date(2026, 11, 16), "America/New_York")
        self.assertEqual((a["started"], a["ended"], a["refused"], a["refused_by_reason"]), (1, 1, 1, {"a run is in progress": 1}))
        b = cs.run_counts(self.tmp, datetime.date(2026, 11, 17), "America/New_York")
        self.assertEqual((b["started"], b["ended"], b["refused"]), (1, 0, 0))

    def test_the_counts_say_what_was_cut_or_bad_or_wrong(self):
        shutil.copytree(FIX / "log", self.tmp / "crawl" / "log")
        (self.tmp / "crawl" / "log" / "crawl-2026-11-16.jsonl").write_bytes(b"junk\n" + (FIX / "log" / "crawl-2026-11-16.jsonl").read_bytes())
        a = cs.run_counts(self.tmp, datetime.date(2026, 11, 16), "America/New_York")
        self.assertEqual(a["bad"], {"not_json": 1})
        self.assertIsNone(a["problem"])
        self.assertIn("cut", a)

    def test_only_the_top_ten_reasons_are_listed(self):
        self.put_log("2026-11-16", *[dict(ts=f"2026-11-16T05:{i:02d}:00Z", run="", step="refuse", outcome="refused", reason=f"reason {i}") for i in range(15)])
        a = cs.run_counts(self.tmp, datetime.date(2026, 11, 16), "UTC")
        self.assertEqual((a["refused"], len(a["refused_by_reason"])), (15, 10))


if __name__ == "__main__":
    unittest.main()
