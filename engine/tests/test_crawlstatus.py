"""The reading side of `crawl-status` and `crawl-report` (`kb/crawlstatus.py`; `docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`).

Every test runs on a temporary index root and on hand-made fixture files in the spec's log format. No test opens a socket, reads the owner's
library, config, plan or keys, or writes outside its temporary folder. Hostile characters are made with `chr()` here, never typed."""

import collections
import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unicodedata
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests import test_crawlapprove as crawlapprove_tests
from engine.tests.test_store import StoreCase

from kb import KbError, crawlbooks, crawlguard, crawllog, crawlplan, crawlqueue, crawlstate, crawlstatus as cs, textutil

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
                      "http.client", "subprocess", "os.system(", "os.popen("):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        self.assertIsNone(re.search(r"(?<![.\w])open\(", source), "the builtin open")

    def test_the_one_way_the_module_opens_a_database_is_read_only_and_its_statements_only_read(self):
        source = (Path(ENGINE_DIR) / "kb" / "crawlstatus.py").read_text(encoding="utf-8")
        connects = re.findall(r"sqlite3\.connect\([^\n]*", source)
        self.assertEqual(len(connects), 1)
        self.assertIn("mode=ro", source)
        self.assertIn("uri=True", connects[0])
        for word in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "VACUUM", "ATTACH", "journal_mode", "BEGIN", "COMMIT", "wal_checkpoint"):
            with self.subTest(word=word):
                self.assertNotIn(word, source)
        for statement in re.findall(r"\.execute\(\s*f?\"([^\"]*)\"", source):
            self.assertRegex(statement, r"^(SELECT|PRAGMA busy_timeout)\b")


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

    def test_the_more_shapes_of_a_secret_that_the_security_review_named_are_hidden(self):
        shapes = ["X-Goog-Api-Key: SECRET1", "api-key: SECRET2", "Authorization Basic SECRET3", "x-amz-security-token: SECRET4", "Private-Token: SECRET5",
                  "Ocp-Apim-Subscription-Key: SECRET6", "https://h/p?api-key=SECRET7", "https://h/p?client_secret=SECRET8&a=1", "https://h/p?refresh_token=SECRET9",
                  "https://h/p?auth_key=SECRET10", "https://h/p?x-amz-signature=SECRET11", "https://h/p?sessionid=SECRET12", "https://h/p?jwt=SECRET13",
                  "https://h/p?%256Bey=SECRET14", "https://h/p?id_token=SECRET15", "/cb?access_token=SECRET16", "client_secret=SECRET17", '{"api_key": "SECRET18"}',
                  "https://app/#/cb?access_token=SECRET19", "https://x/?redirect=https://y/?key=SECRET20", "//u:SECRET21@h/", "https://u:SECRET22@h/p",
                  "https://h/p?oauth_token=SECRET23", "https://h/p?secret_key=SECRET24"]
        for text in shapes:
            with self.subTest(text=text):
                self.assertNotIn("SECRET", cs.redact(text))
                self.assertNotIn("SECRET", cs.clean(text, 300))

    def test_ordinary_text_and_addresses_are_not_changed_by_the_wider_rules(self):
        for text in ("https://example.org/a?page=2&sort=date", "HTTP 503", "the token bucket was empty", "https://example.org/@user/post", "a monkey, a donkey",
                     "key figures were low", "secrets of the trade", "https://example.org/a#section-2", "tokens: ", "passwords were reset"):
            with self.subTest(text=text):
                self.assertEqual(cs.redact(text), text)

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
        for text in ("sk-live-abcdefghijklmnopqrstuvwx", "plain words"):
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
        rec, kind = cs.parse_line(raw(candidate=12, book="b-1", host="example.org", reason="x", n=5, seconds=0.5))
        self.assertIsNone(kind)
        self.assertEqual(set(rec), {"ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds"})
        self.assertEqual((rec["n"], rec["seconds"], rec["host"], rec["candidate"]), (5, 0.5, "example.org", 12))

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
                          raw(candidate="https://example.org/a"), raw(candidate=True), raw(candidate=-1), raw(candidate=1.5), raw(candidate=2 ** 63), raw(n=2 ** 63), raw(host=["a"]), raw(book={"a": 1}), raw(reason=3), raw(run=None), raw(run=7),
                          raw(reason="x" * (cs.MAX_FIELD + 1)),
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

    def test_n_takes_the_whole_numbers_up_to_what_the_log_writer_writes(self):
        self.assertEqual(cs.parse_line(raw(n=2**63 - 1))[0]["n"], 2**63 - 1)
        self.assertEqual(cs.parse_line(raw(n=0))[0]["n"], 0)
        self.assertEqual(cs.parse_line(raw(n=2**63)), (None, "bad_field"))

    def test_seconds_takes_zero_and_whole_numbers_and_fractions(self):
        for value in (0, 0.0, 3, 0.25, 1e6):
            with self.subTest(seconds=value):
                self.assertEqual(cs.parse_line(raw(seconds=value))[0]["seconds"], value)

    def test_a_field_of_exactly_the_field_limit_is_taken(self):
        rec, kind = cs.parse_line(raw(reason="y" * cs.MAX_FIELD, candidate=2 ** 63 - 1, n=2 ** 63 - 1))
        self.assertIsNone(kind)
        self.assertEqual((rec["candidate"], rec["n"]), (2 ** 63 - 1, 2 ** 63 - 1))
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

    def put_log(self, date, *records):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"crawl-{date}.jsonl").write_bytes(b"".join(raw(**r) + b"\n" for r in records))

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

    def test_a_number_that_is_not_finite_is_dropped_and_the_answer_stays_plain_data(self):
        self.approve()
        r = cs.approved_plan(self.tmp, lambda path: {"fetches_per_day": float("nan"), "per_domain_per_day": float("inf"), "cards_per_day": -float("inf"),
                                                     "bulk_floor_gb": 1.5, "filed_total": 7})
        self.assertEqual(r["values"], {"bulk_floor_gb": 1.5, "filed_total": 7})
        self.assertEqual(json.loads(json.dumps(r, allow_nan=False)), r)

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
    GIB = 10 ** 9  # the runner's guard reads a floor in decimal gigabytes

    def vfs(self, free_bytes, frsize=1000):
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


class IdleWindowTest(StateBase):
    """What the idle windows of a day did, from the `idle`, `themes`, `theme_vectors` and `weave` lines only."""
    DAY = datetime.date(2026, 11, 16)

    def window_lines(self):
        return [dict(ts="2026-11-16T05:05:00Z", run="r1", step="idle", outcome="ok", reason="deadline", n=9, seconds=300),
                dict(ts="2026-11-16T05:05:00Z", run="r1", step="themes", outcome="ok", book="01ARZ3NDEKTSV4RRFFQ69G5FAV", n=12, seconds=34),
                dict(ts="2026-11-16T05:05:00Z", run="r1", step="themes", outcome="failed", book="01ARZ3NDEKTSV4RRFFQ69G5FAW", reason="refused"),
                dict(ts="2026-11-16T05:05:00Z", run="r1", step="theme_vectors", outcome="ok", n=120, seconds=60),
                dict(ts="2026-11-16T05:05:00Z", run="r1", step="weave", outcome="skipped", reason="not due", n=40),
                dict(ts="2026-11-16T06:10:00Z", run="r2", step="idle", outcome="skipped", reason="nothing to do", n=0, seconds=4),
                dict(ts="2026-11-16T07:15:00Z", run="r3", step="idle", outcome="ok", reason="nothing to do", n=3, seconds=95),
                dict(ts="2026-11-16T07:15:00Z", run="r3", step="theme_vectors", outcome="ok", n=18, seconds=14),
                dict(ts="2026-11-16T07:15:00Z", run="r3", step="weave", outcome="ok", n=22, seconds=6)]

    def test_a_huge_number_in_a_line_cannot_break_the_sums_or_the_printing_of_the_part(self):
        # a line may hold any whole number or finite float that the reader takes; two of 3,000 digits sum past what `str` and `json` write, and two of 1e308 sum to infinity
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:00:00Z", run="r1", step="idle", outcome="ok", reason="deadline", n=1, seconds=10 ** 3000),
                     dict(ts="2026-11-16T06:00:00Z", run="r2", step="idle", outcome="ok", reason="deadline", n=1, seconds=10 ** 3000),
                     dict(ts="2026-11-16T07:00:00Z", run="r3", step="idle", outcome="ok", reason="deadline", n=1, seconds=1e308),
                     dict(ts="2026-11-16T08:00:00Z", run="r4", step="idle", outcome="ok", reason="deadline", n=1, seconds=1e308))
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["windows"], got["books_made"]), (4, 4))
        self.assertLessEqual(got["seconds"], 4 * cs.MAX_NUMBER)                # each line counts for at most a number that any real window is far under
        self.assertEqual(json.loads(json.dumps(got)), got)
        self.assertLessEqual(got["last"]["seconds"], cs.MAX_NUMBER)

    def test_the_windows_of_the_day_are_counted_with_their_seconds_books_and_reasons(self):
        self.put_log("2026-11-16", *self.window_lines())
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["windows"], got["seconds"], got["books_made"]), (3, 399, 12))
        self.assertEqual(got["by_reason"], {"deadline": 1, "nothing to do": 2})
        self.assertEqual(got["themes_failed"], 1)
        self.assertEqual((got["vector_texts"], got["vectors_failed"]), (138, 0))
        self.assertEqual((got["weave_repairs"], got["weave_themes_added"]), (1, 22))

    def test_the_last_window_is_the_newest_with_its_run_outcome_reason_books_and_seconds(self):
        self.put_log("2026-11-16", *self.window_lines())
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual(got["last"], {"ts": "2026-11-16T07:15:00Z", "run": "r3", "outcome": "ok", "reason": "nothing to do", "books_made": 3, "seconds": 95})

    def test_a_day_with_no_window_says_so_and_has_no_last_window(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:00:00Z", run="r1", step="run_start"))
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["windows"], got["seconds"], got["books_made"], got["last"], got["by_reason"]), (0, 0, 0, None, {}))

    def test_the_lines_of_another_day_are_not_counted(self):
        self.put_log("2026-11-16", *self.window_lines())
        self.put_log("2026-11-15", dict(ts="2026-11-15T23:00:00Z", run="r0", step="idle", outcome="ok", reason="deadline", n=50, seconds=600))
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["windows"], got["books_made"]), (3, 12))

    def test_a_failed_vector_step_and_a_failed_repair_are_counted_apart(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:05:00Z", run="r1", step="theme_vectors", outcome="failed", reason="the vectors could not be made"),
                     dict(ts="2026-11-16T05:05:00Z", run="r1", step="weave", outcome="failed", reason="the repair was refused"))
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["vectors_failed"], got["vector_texts"], got["weave_failed"], got["weave_repairs"]), (1, 0, 1, 0))

    def test_a_reason_is_cleaned_and_a_window_with_no_reason_is_named(self):
        self.put_log("2026-11-16", dict(ts="2026-11-16T05:05:00Z", run="r1", step="idle", outcome="ok", reason="dead" + ZWSP + "line", n=1, seconds=1),
                     dict(ts="2026-11-16T06:05:00Z", run="r2", step="idle", outcome="ok", n=1, seconds=1))
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual(got["by_reason"], {"deadline": 1, "(no reason)": 1})

    def test_the_bad_lines_and_a_log_that_is_a_link_are_reported_as_the_other_parts_report_them(self):
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        (folder / "crawl-2026-11-16.jsonl").write_bytes(b"junk\n" + raw(**self.window_lines()[0]) + b"\n")
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual((got["windows"], got["bad"]), (1, {"not_json": 1}))

    def test_the_answer_is_plain_data(self):
        self.put_log("2026-11-16", *self.window_lines())
        got = cs.idle_counts(self.tmp, self.DAY, "UTC")
        self.assertEqual(json.loads(json.dumps(got)), got)


class RunsTest(StateBase):
    NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)

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


class QueueBase(StateBase):
    NOW_TS = "2026-11-16T12:00:00Z"

    def make_queue(self):
        conn = crawlqueue.connect(self.tmp)
        self.addCleanup(self.close_quietly, conn)
        return conn

    @staticmethod
    def close_quietly(conn):
        try:
            conn.close()
        except sqlite3.Error:
            pass

    def put(self, conn, key, status="queued", updated=None, **extra):
        conn.execute("INSERT INTO candidates (identity_key, address, source, status, domain, reason, added, updated) VALUES (?,?,?,?,?,?,?,?)",
                     (key, f"https://example.org/{key}", "arxiv", status, extra.get("domain", "example.org"), extra.get("reason"),
                      updated or self.NOW_TS, updated or self.NOW_TS))

    def counter(self, conn, day, key, n):
        conn.execute("INSERT INTO counters (day, key, n) VALUES (?,?,?)", (day, key, n))

    def opened(self):
        result = cs.open_queue(self.tmp)
        if result.conn is not None:
            self.addCleanup(self.close_quietly, result.conn)
        return result

    def listing(self):
        return sorted((p.name, oct(p.stat().st_mode & 0o777), p.stat().st_size) for p in self.tmp.iterdir())

    def main_state(self):
        p = self.tmp / "candidates.sqlite"
        st = p.stat()
        return hashlib.sha256(p.read_bytes()).hexdigest(), st.st_mtime_ns, st.st_mode, st.st_size


SIDE_FILES = {"candidates.sqlite-wal", "candidates.sqlite-shm"}


class OpenQueueTest(QueueBase):
    def test_a_missing_queue_is_no_queue_and_is_not_made(self):
        r = cs.open_queue(self.tmp)
        self.assertEqual((r.conn, r.status), (None, "missing"))
        self.assertEqual(self.listing(), [])

    def test_a_side_file_of_the_queue_that_is_a_link_or_not_a_plain_file_is_refused_and_nothing_is_written_through_it(self):
        w = self.make_queue()
        self.put(w, "k")
        w.close()
        target = self.tmp / "victim.txt"
        target.write_bytes(b"VICTIM" * 50)
        for side in ("-wal", "-shm"):
            path = Path(str(self.tmp / crawlqueue.FILE) + side)
            path.unlink(missing_ok=True)
            for make in (lambda: os.symlink(target, path), lambda: os.mkfifo(path), lambda: path.mkdir()):
                make()
                with self.subTest(side=side, kind=make.__code__.co_names[-1]):
                    r = cs.open_queue(self.tmp)
                    self.assertEqual((r.conn, r.status), (None, "bad"))
                    self.assertNotIn(str(self.tmp), r.reason)
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
        self.assertEqual(target.read_bytes(), b"VICTIM" * 50)

    def test_a_queue_is_opened_and_its_rows_are_read(self):
        w = self.make_queue()
        for i in range(4):
            self.put(w, f"k{i}")
        w.close()
        r = self.opened()
        self.assertEqual((r.status, r.reason), ("ok", None))
        self.assertEqual(r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 4)

    def test_the_connection_cannot_write(self):
        self.make_queue().close()
        r = self.opened()
        for statement in ("INSERT INTO counters (day, key, n) VALUES ('d', 'k', 1)", "DELETE FROM candidates", "DROP TABLE counters",
                          "UPDATE candidates SET status = 'kept'", "CREATE TABLE t (a)"):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.OperationalError):
                r.conn.execute(statement)

    def test_it_is_opened_read_only_by_uri_with_a_short_wait(self):
        self.make_queue().close()
        seen = []
        real = sqlite3.connect

        def spy(*args, **kwargs):
            seen.append((args, kwargs))
            return real(*args, **kwargs)

        with mock.patch.object(cs.sqlite3, "connect", spy):
            self.opened()
        self.assertEqual(len(seen), 1)
        args, kwargs = seen[0]
        self.assertIn("mode=ro", args[0])
        self.assertTrue(kwargs.get("uri"))
        self.assertLessEqual(kwargs.get("timeout"), 2)

    def test_a_path_with_odd_characters_is_opened_as_a_path(self):
        odd = self.tmp / "a b#c?d"
        odd.mkdir()
        conn = crawlqueue.connect(odd)
        self.put_into(conn)
        conn.close()
        r = cs.open_queue(odd)
        self.addCleanup(self.close_quietly, r.conn)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)

    def put_into(self, conn):
        self.put(conn, "k1")

    def test_a_file_that_is_not_a_plain_queue_of_the_owner_is_refused_without_a_path_in_the_reason(self):
        path = self.tmp / "candidates.sqlite"
        real = self.tmp / "real.sqlite"
        crawlqueue.connect(self.tmp).close()
        shutil.move(path, real)
        for name, make in {
                "a link": lambda: os.symlink(real, path), "a folder": lambda: path.mkdir(), "a pipe": lambda: os.mkfifo(path),
                "mode 644": lambda: (shutil.copy(real, path), os.chmod(path, 0o644)),
                "not a database": lambda: (path.write_bytes(b"not a database at all" * 100), os.chmod(path, 0o600)),
                "empty": lambda: (path.write_bytes(b""), os.chmod(path, 0o600))}.items():
            with self.subTest(case=name):
                make()
                r = self.within(lambda: cs.open_queue(self.tmp))
                self.assertEqual((r.conn, r.status), (None, "bad"))
                self.assertNotIn(str(self.tmp), r.reason)
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()

    def test_a_queue_of_another_owner_or_version_or_shape_is_refused_and_left_as_it_was(self):
        self.make_queue().close()
        before = self.main_state()
        with mock.patch.object(crawlqueue.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(cs.open_queue(self.tmp).status, "bad")
        self.assertEqual(self.main_state(), before)
        path = self.tmp / "candidates.sqlite"
        for name, change in {"version 2": "PRAGMA user_version = 2", "an extra column": "ALTER TABLE counters ADD COLUMN x TEXT",
                             "an extra table": "CREATE TABLE extra (a)"}.items():
            with self.subTest(case=name):
                shutil.copy(path, self.tmp / "keep")
                with closing(sqlite3.connect(path)) as c:
                    c.execute(change)
                    c.commit()
                for side in SIDE_FILES:
                    (self.tmp / side).unlink(missing_ok=True)
                changed = self.main_state()
                r = cs.open_queue(self.tmp)
                self.assertEqual((r.conn, r.status), (None, "bad"))
                self.assertEqual(self.main_state(), changed)
                for side in SIDE_FILES:
                    (self.tmp / side).unlink(missing_ok=True)
                shutil.copy(self.tmp / "keep", path)

    def test_a_path_that_cannot_be_written_as_an_address_is_a_bad_queue_and_not_another_kind_of_error(self):
        self.make_queue().close()
        with mock.patch.object(cs, "quote", side_effect=UnicodeEncodeError("utf-8", chr(0xDC80), 0, 1, "surrogates not allowed")):
            r = cs.open_queue(self.tmp)
        self.assertEqual((r.conn, r.status), (None, "bad"))

    def test_a_queue_that_is_locked_is_busy_and_any_other_failure_is_bad(self):
        self.make_queue().close()
        with mock.patch.object(crawlqueue, "_check_shape", side_effect=sqlite3.OperationalError("database is locked")):
            r = cs.open_queue(self.tmp)
        self.assertEqual((r.conn, r.status), (None, "busy"))
        with mock.patch.object(crawlqueue, "_check_shape", side_effect=sqlite3.OperationalError("the database is busy")):
            self.assertEqual(cs.open_queue(self.tmp).status, "busy")
        with mock.patch.object(crawlqueue, "_check_shape", side_effect=sqlite3.OperationalError("unable to open database file")):
            self.assertEqual(cs.open_queue(self.tmp).status, "bad")
        with mock.patch.object(crawlqueue, "_check_shape", side_effect=sqlite3.DatabaseError("file is not a database")):
            r = cs.open_queue(self.tmp)
        self.assertEqual((r.conn, r.status), (None, "bad"))
        self.assertNotIn(str(self.tmp), r.reason)

    def test_the_rows_a_writer_has_committed_are_read_while_the_writer_is_open_and_nothing_uncommitted_is(self):
        w = self.make_queue()
        for i in range(5):
            self.put(w, f"k{i}")
        before_files, before_main = self.listing(), self.main_state()
        w.execute("BEGIN IMMEDIATE")
        self.put(w, "uncommitted")
        r = self.opened()
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 5)
        self.assertEqual((self.listing(), self.main_state()), (before_files, before_main))
        w.execute("ROLLBACK")

    def test_the_only_files_a_reader_adds_are_the_wal_and_the_shared_memory_file_and_the_queue_is_as_it_was(self):
        self.make_queue().close()
        self.assertEqual([n for n, _, _ in self.listing()], ["candidates.sqlite"])
        before = self.main_state()
        r = self.opened()
        r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()
        r.conn.close()
        names = {n for n, _, _ in self.listing()}
        self.assertEqual(names - {"candidates.sqlite"}, SIDE_FILES)
        modes = {n: m for n, m, _ in self.listing()}
        self.assertEqual({modes[n] for n in names}, {"0o600"})
        self.assertEqual(self.main_state(), before)
        sizes = {n: s for n, _, s in self.listing()}
        self.assertEqual(sizes["candidates.sqlite-wal"], 0)

    def test_a_writer_that_comes_after_a_reader_opens_the_queue_and_reads_the_same_rows(self):
        w = self.make_queue()
        for i in range(3):
            self.put(w, f"k{i}")
        w.close()
        r = self.opened()
        r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()
        r.conn.close()
        again = crawlqueue.connect(self.tmp)
        self.addCleanup(self.close_quietly, again)
        self.assertEqual(again.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 3)
        self.put(again, "k9")
        self.assertEqual(again.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 4)

    def test_a_queue_whose_writer_was_killed_is_read_with_the_rows_that_were_committed(self):
        code = ("import os, sys\n" f"sys.path.insert(0, {ENGINE_DIR!r})\n" "from kb import crawlqueue\n" f"c = crawlqueue.connect({str(self.tmp)!r})\n"
                "c.execute(\"INSERT INTO candidates (identity_key, address, source, status, added, updated) VALUES "
                "('k','https://e.org/k','arxiv','queued','2026-11-16T05:00:00Z','2026-11-16T05:00:00Z')\")\n" "os._exit(0)\n")
        subprocess.run([sys.executable, "-I", "-c", code], check=True, timeout=60)
        self.assertTrue({"candidates.sqlite-wal", "candidates.sqlite-shm"} <= {n for n, _, _ in self.listing()})
        before = self.main_state()
        r = self.opened()
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)
        self.assertEqual(self.main_state(), before)

    def test_the_rows_are_not_seen_if_the_wal_is_ignored_which_is_why_that_option_is_not_used(self):
        w = self.make_queue()
        for i in range(3):
            self.put(w, f"k{i}")
        with closing(sqlite3.connect(f"file:{self.tmp / 'candidates.sqlite'}?mode=ro&immutable=1", uri=True)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 0)
        r = self.opened()
        self.assertEqual(r.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 3)


class QueueCountsTest(QueueBase):
    def bounds(self, zone="America/New_York", day=datetime.date(2026, 11, 16)):
        return cs.day_bounds(day, zone)

    def test_the_counts_by_status_in_all_and_for_the_day_with_every_status_present(self):
        w = self.make_queue()
        self.put(w, "a", "queued", "2026-11-16T05:00:00Z")
        self.put(w, "b", "queued", "2026-11-17T04:59:59Z")
        self.put(w, "c", "kept", "2026-11-16T12:00:00Z")
        self.put(w, "d", "failed", "2026-11-16T04:59:59Z")
        self.put(w, "e", "rejected", "2026-11-17T05:00:00Z")
        self.put(w, "f", "blocked", "2026-11-10T00:00:00Z")
        r = self.opened()
        got = cs.queue_counts(r.conn, self.bounds())
        self.assertEqual(set(got["all"]), set(crawlqueue.STATUSES))
        self.assertEqual(got["all"], {"queued": 2, "fetching": 0, "kept": 1, "rejected": 1, "failed": 1, "blocked": 1})
        self.assertEqual(got["today"], {"queued": 2, "fetching": 0, "kept": 1, "rejected": 0, "failed": 0, "blocked": 0})
        self.assertEqual(got["total"], 6)

    def test_a_day_of_23_and_a_day_of_25_hours_take_the_rows_that_are_theirs(self):
        w = self.make_queue()
        for key, ts in (("a", "2026-03-28T23:59:59Z"), ("b", "2026-03-29T00:00:00Z"), ("c", "2026-03-29T22:59:59Z"), ("d", "2026-03-29T23:00:00Z"),
                        ("e", "2026-10-24T22:59:59Z"), ("f", "2026-10-24T23:00:00Z"), ("g", "2026-10-25T23:59:59Z"), ("h", "2026-10-26T00:00:00Z")):
            self.put(w, key, "queued", ts)
        r = self.opened()
        self.assertEqual(cs.queue_counts(r.conn, self.bounds("Europe/London", datetime.date(2026, 3, 29)))["today"]["queued"], 2)
        self.assertEqual(cs.queue_counts(r.conn, self.bounds("Europe/London", datetime.date(2026, 10, 25)))["today"]["queued"], 2)

    def test_a_status_that_is_not_one_of_ours_is_counted_apart_and_never_listed(self):
        w = self.make_queue()
        self.put(w, "a", "queued")
        self.put(w, "b", "Cookie: x" + chr(0x1b))
        self.put(w, "c", "x" * 5000)
        r = self.opened()
        got = cs.queue_counts(r.conn, self.bounds())
        self.assertEqual((got["all"]["queued"], got["other"], got["total"]), (1, 2, 3))
        self.assertNotIn("Cookie", repr(got))

    def test_an_empty_queue_has_zeros(self):
        self.make_queue().close()
        r = self.opened()
        got = cs.queue_counts(r.conn, self.bounds())
        self.assertEqual((sum(got["all"].values()), sum(got["today"].values()), got["total"], got["other"]), (0, 0, 0, 0))

    def test_the_bounds_are_two_times(self):
        self.make_queue().close()
        r = self.opened()
        for bad in (None, (1, 2), "x", (datetime.datetime(2026, 1, 1), datetime.datetime(2026, 1, 2))):
            with self.subTest(bounds=bad), self.assertRaises(KbError):
                cs.queue_counts(r.conn, bad)


class TodayInZoneTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 17, 3, 0, 0, tzinfo=UTC)

    def test_the_day_of_a_time_in_a_zone(self):
        self.assertEqual(cs.today_in_zone(self.NOW, "UTC"), datetime.date(2026, 11, 17))
        self.assertEqual(cs.today_in_zone(self.NOW, "America/New_York"), datetime.date(2026, 11, 16))
        self.assertEqual(cs.today_in_zone(self.NOW, "Pacific/Auckland"), datetime.date(2026, 11, 17))
        self.assertEqual(cs.today_in_zone(datetime.datetime(2026, 11, 16, 23, 30, tzinfo=UTC), "Pacific/Auckland"), datetime.date(2026, 11, 17))

    def test_the_local_zone_is_the_machines(self):
        old = os.environ.get("TZ")
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old is not None else os.environ.pop("TZ", None), time.tzset()))
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        self.assertEqual(cs.today_in_zone(self.NOW, "local"), datetime.date(2026, 11, 16))

    def test_a_zone_that_is_not_known_and_a_time_with_no_zone_are_refused(self):
        for zone in ("Mars/Olympus", "../x", None, 5):
            with self.subTest(zone=zone), self.assertRaises(KbError):
                cs.today_in_zone(self.NOW, zone)
        for now in (datetime.datetime(2026, 11, 17, 3, 0, 0), "2026-11-17", None):
            with self.subTest(now=now), self.assertRaises(KbError):
                cs.today_in_zone(now, "UTC")


class CountersTest(QueueBase):
    DAY, UTC_DAY = "2026-11-16", "2026-11-16"
    VALUES = {"fetches_per_day": 5, "per_domain_per_day": 3, "cards_per_day": 30, "domain_refusals": 3}

    def fill(self):
        w = self.make_queue()
        for key, n in (("fetch", 5), ("fetch:example.org", 2), ("fetch:other.net", 3), ("card", 4), ("refusal:example.org", 1), ("odd_key", 9)):
            self.counter(w, "2026-11-16", key, n)
        for key, n in (("fetch", 99), ("card", 99), ("fetch:example.org", 99)):
            self.counter(w, "2026-11-15", key, n)
        self.counter(w, "2026-11-16", "source_off:arxiv", 1)
        self.counter(w, "2026-11-16", "web_search_queries", 7)
        for i in range(3):
            self.counter(w, "permanent", f"walked:W{i}", 1)
        return w

    def report(self, values=VALUES, plan_day=DAY, utc_day=UTC_DAY):
        r = self.opened()
        return cs.counters_report(r.conn, plan_day, utc_day, values)

    def test_the_counters_of_the_plans_day_against_the_ceilings(self):
        self.fill()
        got = self.report()
        self.assertEqual((got["day"], got["ceilings_known"]), ("2026-11-16", True))
        self.assertEqual(got["fetch"], {"n": 5, "limit": 5, "at_or_over": True})
        self.assertEqual(got["card"], {"n": 4, "limit": 30, "at_or_over": False})
        by_domain = {d["domain"]: d for d in got["domains"]}
        self.assertEqual(by_domain["example.org"], {"domain": "example.org", "fetch": 2, "limit": 3, "at_or_over": False, "refusals": 1})
        self.assertEqual(by_domain["other.net"], {"domain": "other.net", "fetch": 3, "limit": 3, "at_or_over": True, "refusals": 0})
        self.assertEqual((got["domains_total"], got["domain_refusals"]), (2, 3))
        self.assertEqual(got["other"], [{"key": "odd_key", "n": 9}])

    def test_another_days_counters_are_not_counted(self):
        self.fill()
        got = self.report(plan_day="2026-11-15")
        self.assertEqual((got["fetch"]["n"], got["card"]["n"]), (99, 99))
        got = self.report(plan_day="2026-11-17")
        self.assertEqual((got["fetch"]["n"], got["card"]["n"], got["domains"], got["other"]), (0, 0, [], []))

    def test_without_an_approved_plan_the_counters_are_shown_without_ceilings(self):
        self.fill()
        got = self.report(values=None)
        self.assertEqual((got["ceilings_known"], got["fetch"], got["card"]), (False, {"n": 5, "limit": None, "at_or_over": None}, {"n": 4, "limit": None, "at_or_over": None}))
        self.assertTrue(all(d["limit"] is None and d["at_or_over"] is None for d in got["domains"]))
        self.assertIsNone(got["domain_refusals"])

    def test_a_ceiling_that_is_not_a_whole_number_is_unknown(self):
        self.fill()
        got = self.report(values={"fetches_per_day": "5", "per_domain_per_day": True, "cards_per_day": 2.5})
        self.assertEqual((got["fetch"]["limit"], got["card"]["limit"]), (None, None))
        self.assertTrue(all(d["limit"] is None for d in got["domains"]))

    def test_a_ceiling_is_reached_at_the_number_and_not_below_it(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch", 4)
        self.assertFalse(self.report()["fetch"]["at_or_over"])
        w.execute("UPDATE counters SET n = 5 WHERE key = 'fetch'")
        self.assertTrue(self.report()["fetch"]["at_or_over"])
        w.execute("UPDATE counters SET n = 6 WHERE key = 'fetch'")
        self.assertTrue(self.report()["fetch"]["at_or_over"])

    def test_the_rows_of_discovery_are_shown_as_discoverys_and_walked_rows_are_only_counted(self):
        self.fill()
        got = self.report()
        self.assertEqual(got["discovery"], {"day": "2026-11-16", "sources_off": ["arxiv"], "sources_off_total": 1, "web_search_queries": 7, "walked": 3})
        self.assertNotIn("source_off:arxiv", [o["key"] for o in got["other"]])
        self.assertNotIn("walked", repr(got["other"]))

    def test_discoverys_day_is_the_utc_day_and_the_plans_day_may_differ(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch", 2)
        self.counter(w, "2026-11-17", "source_off:wikipedia", 1)
        self.counter(w, "2026-11-17", "web_search_queries", 4)
        got = self.report(plan_day="2026-11-16", utc_day="2026-11-17")
        self.assertEqual((got["fetch"]["n"], got["discovery"]["sources_off"], got["discovery"]["web_search_queries"]), (2, ["wikipedia"], 4))
        self.assertEqual(got["other"], [])

    def test_a_discovery_key_on_a_day_that_is_not_the_utc_day_is_an_other_counter(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "web_search_queries", 4)
        got = self.report(plan_day="2026-11-16", utc_day="2026-11-17")
        self.assertEqual((got["discovery"]["web_search_queries"], got["other"]), (0, [{"key": "web_search_queries", "n": 4}]))

    def test_the_most_fetched_domains_are_listed_up_to_fifty_and_the_total_is_said(self):
        w = self.make_queue()
        for i in range(60):
            self.counter(w, "2026-11-16", f"fetch:d{i:02d}.example", i + 1)
        got = self.report()
        self.assertEqual((len(got["domains"]), got["domains_total"]), (50, 60))
        self.assertEqual(got["domains"][0]["domain"], "d59.example")
        self.assertEqual(got["domains"][-1]["domain"], "d10.example")

    def test_a_row_with_a_count_that_is_not_a_whole_number_is_skipped_and_counted(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch", "many")
        self.counter(w, "2026-11-16", "card", 2.5)
        self.counter(w, "2026-11-16", "fetch:a.example", -1)
        self.counter(w, "2026-11-16", "fetch:b.example", 3)
        got = self.report()
        self.assertEqual((got["fetch"]["n"], got["card"]["n"], got["bad_rows"]), (0, 0, 3))
        self.assertEqual([d["domain"] for d in got["domains"]], ["b.example"])

    def test_text_from_a_key_is_redacted_and_cleaned(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch:evil" + chr(0x1b) + "[31m" + RLO + ".example", 1)
        self.counter(w, "2026-11-16", "refusal:Cookie: sid=1.example", 1)
        self.counter(w, "2026-11-16", "other " + ZWSP + "key\nline", 1)
        got = self.report()
        text = json.dumps(got)
        self.assertNotIn(chr(0x1b), text)
        self.assertNotIn(RLO, text)
        self.assertNotIn("sid=1", text)
        self.assertIn(cs.WITHHELD, text)
        self.assertEqual(got["other"], [{"key": "other key line", "n": 1}])

    def test_the_rows_read_are_bounded_and_a_cut_is_said(self):
        w = self.make_queue()
        for i in range(30):
            self.counter(w, "2026-11-16", f"k{i:02d}", 1)
        with mock.patch.object(cs, "MAX_COUNTER_ROWS", 10):
            got = self.report()
        self.assertTrue(got["truncated"])
        self.assertFalse(self.report()["truncated"])

    def test_the_ceiling_counters_are_read_by_name_and_are_never_lost_to_the_bound_on_the_rows(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch", 1)
        self.counter(w, "2026-11-16", "card", 2)
        self.counter(w, "2026-11-16", "web_search_queries", 3)
        for i in range(12):
            self.counter(w, "2026-11-16", f"big{i:02d}", 1000 + i)
            self.counter(w, "2026-11-16", f"fetch:d{i:02d}.example", 500 + i)
        with mock.patch.object(cs, "MAX_COUNTER_ROWS", 5):
            got = self.report()
        self.assertTrue(got["truncated"])
        self.assertEqual((got["fetch"]["n"], got["card"]["n"], got["discovery"]["web_search_queries"]), (1, 2, 3))

    def test_the_sources_discovery_turned_off_are_listed_up_to_fifty_and_the_total_is_said(self):
        w = self.make_queue()
        for i in range(60):
            self.counter(w, "2026-11-16", f"source_off:source{i:02d}", 1)
        got = self.report()["discovery"]
        self.assertEqual((len(got["sources_off"]), got["sources_off_total"]), (50, 60))
        self.assertEqual((got["sources_off"][0], got["sources_off"][-1]), ("source00", "source49"))

    def test_a_key_that_is_not_text_is_skipped_and_counted(self):
        w = self.make_queue()
        w.execute("INSERT INTO counters (day, key, n) VALUES (?, ?, ?)", ("2026-11-16", b"blob key", 4))
        w.execute("INSERT INTO counters (day, key, n) VALUES (?, ?, ?)", ("2026-11-16", None, 4))
        self.counter(w, "2026-11-16", "fetch", 2)
        got = self.report()
        self.assertEqual((got["fetch"]["n"], got["bad_rows"], got["other"]), (2, 2, []))

    def test_the_name_of_a_source_that_discovery_turned_off_is_cleaned(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "source_off:ar" + chr(0x1b) + "[31m" + RLO + "xiv", 1)
        self.counter(w, "2026-11-16", "source_off:Cookie: sid=1", 1)
        off = self.report()["discovery"]["sources_off"]
        self.assertEqual(sorted(off), sorted(["ar[31mxiv", cs.WITHHELD]))

    def test_a_ceiling_that_is_negative_is_unknown(self):
        self.make_queue().close()
        got = self.report(values={"fetches_per_day": -1, "per_domain_per_day": -1, "cards_per_day": -1, "domain_refusals": -1})
        self.assertEqual((got["fetch"]["limit"], got["card"]["limit"], got["domain_refusals"]), (None, None, None))

    def test_a_source_that_discovery_counted_with_zero_is_not_off(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "source_off:wikipedia", 0)
        self.counter(w, "2026-11-16", "source_off:arxiv", 2)
        self.assertEqual(self.report()["discovery"]["sources_off"], ["arxiv"])

    def test_a_domain_that_is_empty_after_cleaning_is_named(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch:", 1)
        self.counter(w, "2026-11-16", "refusal:" + RLO, 2)
        got = self.report()
        self.assertEqual([(d["domain"], d["fetch"], d["refusals"]) for d in got["domains"]], [("(none)", 1, 2)])

    def test_domains_with_the_same_fetches_are_ordered_by_refusals_and_then_by_name(self):
        w = self.make_queue()
        for key, n in (("fetch:b.example", 2), ("fetch:a.example", 2), ("fetch:c.example", 2), ("refusal:c.example", 1), ("refusal:b.example", 1)):
            self.counter(w, "2026-11-16", key, n)
        self.assertEqual([d["domain"] for d in self.report()["domains"]], ["b.example", "c.example", "a.example"])

    def test_the_other_counters_are_the_biggest_fifty_and_the_total_is_said(self):
        w = self.make_queue()
        for i in range(60):
            self.counter(w, "2026-11-16", f"other{i:02d}", i + 1)
        got = self.report()
        self.assertEqual((len(got["other"]), got["other_total"]), (50, 60))
        self.assertEqual((got["other"][0], got["other"][-1]), ({"key": "other59", "n": 60}, {"key": "other10", "n": 11}))

    def test_a_ceiling_of_zero_is_a_ceiling(self):
        w = self.make_queue()
        self.counter(w, "2026-11-16", "fetch", 0)
        got = self.report(values={"fetches_per_day": 0, "per_domain_per_day": 0, "cards_per_day": 0})
        self.assertEqual((got["fetch"], got["card"]), ({"n": 0, "limit": 0, "at_or_over": True}, {"n": 0, "limit": 0, "at_or_over": True}))

    def test_the_walked_rows_are_those_of_the_permanent_day_with_that_name_only(self):
        w = self.make_queue()
        self.counter(w, "permanent", "walked:W1", 1)
        self.counter(w, "permanent", "other:W2", 1)
        self.counter(w, "2026-11-16", "walked:W3", 1)
        got = self.report()
        self.assertEqual(got["discovery"]["walked"], 1)
        self.assertEqual(got["other"], [{"key": "walked:W3", "n": 1}])

    def test_the_permanent_day_is_the_one_discovery_uses(self):
        from kb import discover
        self.assertEqual(cs.PERMANENT_DAY, discover.PERMANENT)

    def test_exactly_the_rows_allowed_are_read(self):
        w = self.make_queue()
        for i in range(30):
            self.counter(w, "2026-11-16", f"k{i:02d}", 1)
        with mock.patch.object(cs, "MAX_COUNTER_ROWS", 10):
            got = self.report()
        self.assertEqual((got["other_total"], got["truncated"]), (10, True))
        with mock.patch.object(cs, "MAX_COUNTER_ROWS", 30):
            got = self.report()
        self.assertEqual((got["other_total"], got["truncated"]), (30, False))

    def test_the_day_must_be_a_day(self):
        self.make_queue().close()
        r = self.opened()
        for bad in ("2026-11-1", "yesterday", None, 5, "2026-13-40", datetime.datetime(2026, 11, 16, 1, 0), "20261116", "2026-W46-1", "2026-11-16\n", " 2026-11-16"):
            with self.subTest(day=bad), self.assertRaises(KbError):
                cs.counters_report(r.conn, bad, "2026-11-16", None)
            with self.subTest(utc_day=bad), self.assertRaises(KbError):
                cs.counters_report(r.conn, "2026-11-16", bad, None)

    def test_only_selects_are_made_and_the_database_is_as_it_was(self):
        self.fill().close()
        before = self.main_state()
        r = self.opened()
        cs.counters_report(r.conn, self.DAY, self.UTC_DAY, self.VALUES)
        cs.queue_counts(r.conn, cs.day_bounds(datetime.date(2026, 11, 16), "UTC"))
        r.conn.close()
        self.assertEqual(self.main_state(), before)
        self.assertEqual({n for n, _, _ in self.listing()} - {"candidates.sqlite"}, SIDE_FILES)


class CrawlBooksTest(StoreCase):
    within = Base.within

    def book(self, *, auto=True, found=True, events=(), **kw):
        book = self.store.create_book(title="A page", kind="preprint", auto_filed=auto, **kw)
        for name, data in events:
            self.store.append_event(book, name, **data)
        if found:
            self.store.append_event(book, "crawl_found", candidate="https://example.org/a", source="arxiv")
        return book

    def count(self, **kw):
        return cs.crawl_books(self.store, **kw)

    def test_the_books_filed_by_the_crawl_and_the_books_not_yet_reviewed_are_counted(self):
        self.book()
        self.book(events=[("note", {"text": "x"})])
        self.book(found=False)
        self.book(auto=False, found=False)
        self.book(auto=False, found=False, events=[("placement_proposed", {"answer": "x"})])
        got = self.count()
        self.assertEqual((got["filed_total"], got["unreviewed"], got["books_scanned"], got["events_read"]), (2, 3, 5, 3))
        self.assertEqual((got["unreadable"], got["cut"], got["problem"]), (0, False, None))
        self.assertIn("auto_filed", got["basis"])

    def test_only_a_flag_that_is_exactly_true_counts_as_unreviewed_and_a_filing_is_counted_whatever_the_flag(self):
        for value in ("yes", 1, "true", [True], {"a": 1}, None, 0, False):
            with self.subTest(value=value):
                book = self.book(found=True)
                path = Path(self.store.book_file(book))
                root = json.loads(path.read_text())
                root["auto_filed"] = value
                path.write_text(json.dumps(root))
        got = self.count()
        self.assertEqual((got["unreviewed"], got["filed_total"], got["events_read"]), (0, 8, 8))

    def test_a_book_the_owner_has_reviewed_is_still_a_filing_of_the_crawl(self):
        self.book(auto=False, found=True)
        self.book(auto=True, found=True)
        got = self.count()
        self.assertEqual((got["filed_total"], got["unreviewed"]), (2, 1))

    def test_a_root_file_that_is_another_books_is_unreadable_and_is_not_counted_twice(self):
        a, b = self.book(), self.book()
        shutil.copy(self.store.book_file(a), self.store.book_file(b))
        got = self.count()
        self.assertEqual((got["unreadable"], got["filed_total"], got["unreviewed"]), (1, 1, 1))

    def test_the_bytes_read_in_all_are_bounded_and_the_cut_is_said(self):
        books = [self.book() for _ in range(5)]
        size = os.path.getsize(self.store.events_file(books[0]))
        got = self.count(max_total_bytes=size * 2)
        self.assertEqual((got["books_scanned"], got["cut"], got["stopped_by"], got["filed_total"]), (2, True, "max_bytes", 2))
        got = self.count(max_total_bytes=size * 5 + 1)
        self.assertEqual((got["books_scanned"], got["cut"], got["stopped_by"], got["filed_total"]), (5, False, "no_more_books", 5))
        for bad in (0, -1, 1.5, None, True):
            with self.subTest(max_total_bytes=bad), self.assertRaises(KbError):
                self.count(max_total_bytes=bad)

    def test_a_crawl_found_that_is_only_text_in_another_event_is_not_a_filing(self):
        self.book(found=False, events=[("note", {"text": 'it says "crawl_found" in it', "event2": "crawl_found"})])
        self.assertEqual(self.count()["filed_total"], 0)

    def test_an_event_whose_name_only_contains_the_name_is_not_a_filing(self):
        self.book(found=False, events=[("my_crawl_found", {"text": "crawl_found"}), ("crawl_found_again", {"text": "crawl_found"})])
        self.assertEqual(self.count()["filed_total"], 0)

    def test_a_root_file_with_a_duplicate_key_is_unreadable(self):
        book = self.book()
        Path(self.store.book_file(book)).write_text('{"book_id": "%s", "auto_filed": true, "auto_filed": false}' % book)
        got = self.count()
        self.assertEqual((got["unreadable"], got["unreviewed"], got["filed_total"]), (1, 0, 0))

    def test_a_line_that_is_not_json_does_not_stop_the_count_of_the_log(self):
        book = self.book(found=False)
        path = self.store.events_file(book)
        with open(path, "ab") as f:
            f.write(b'garbage "crawl_found" not json\n{"event": "crawl_found", "at": "2026-11-16T05:00:00Z"}\n')
        self.assertEqual(self.count()["filed_total"], 1)

    def test_a_book_whose_root_file_cannot_be_read_is_counted_as_unreadable_and_the_rest_go_on(self):
        a, b, _c = self.book(), self.book(), self.book()
        Path(self.store.book_file(a)).write_text("not json")
        Path(self.store.book_file(b)).write_text("[]")
        got = self.count()
        self.assertEqual((got["unreadable"], got["filed_total"], got["books_scanned"]), (2, 1, 3))

    def test_a_root_file_that_is_a_link_or_over_the_size_is_not_read(self):
        a, b, d = (self.book() for _ in range(3))
        real = Path(self.store.book_file(a))
        path_b = Path(self.store.book_file(b))
        path_b.unlink()
        os.symlink(real, path_b)
        Path(self.store.book_file(d)).write_text(json.dumps({"book_id": d, "auto_filed": True, "pad": "x" * (cs.MAX_ROOT_BYTES + 10)}))
        got = self.count()
        self.assertEqual((got["unreadable"], got["filed_total"], got["books_scanned"]), (2, 1, 3))

    def test_a_root_file_that_is_a_pipe_is_not_waited_on_even_if_the_library_lists_it(self):
        os.mkfifo(Path(self.bulk) / "pipe")
        store = types.SimpleNamespace(list_books=lambda: ["x"], book_file=lambda book_id: str(Path(self.bulk) / "pipe"),
                                      events_file=lambda book_id: str(Path(self.bulk) / "nope"))
        got = self.within(lambda: cs.crawl_books(store))
        self.assertEqual((got["unreadable"], got["filed_total"], got["books_scanned"]), (1, 0, 1))

    def test_a_store_that_gives_a_bad_path_does_not_stop_the_count(self):
        def refuse(book_id):
            raise KbError("not an id")

        store = types.SimpleNamespace(list_books=lambda: ["x", "y"], book_file=refuse, events_file=refuse)
        got = cs.crawl_books(store)
        self.assertEqual((got["unreadable"], got["books_scanned"]), (2, 2))

    def test_an_events_log_that_is_over_the_size_or_a_link_or_a_pipe_makes_the_book_unreadable_and_not_filed(self):
        a, b, c, d = (self.book() for _ in range(4))
        big = Path(self.store.events_file(a))
        big.write_bytes(b'{"event": "crawl_found"}\n' + b" " * 1000)
        link = Path(self.store.events_file(b))
        link.unlink()
        os.symlink(big, link)
        pipe = Path(self.store.events_file(c))
        pipe.unlink()
        os.mkfifo(pipe)
        got = self.within(lambda: self.count(max_events_bytes=500))
        self.assertEqual((got["unreadable"], got["filed_total"], got["unreviewed"]), (3, 1, 4))

    def test_a_book_with_no_events_log_is_not_filed_and_not_unreadable(self):
        book = self.book(found=False)
        self.assertFalse(os.path.exists(self.store.events_file(book)))
        got = self.count()
        self.assertEqual((got["filed_total"], got["unreadable"], got["unreviewed"]), (0, 0, 1))

    def test_the_books_scanned_are_bounded_and_a_cut_is_said(self):
        for _ in range(5):
            self.book()
        got = self.count(max_books=3)
        self.assertEqual((got["books_scanned"], got["cut"], got["stopped_by"]), (3, True, "max_books"))
        self.assertEqual((self.count(max_books=5)["cut"], self.count(max_books=5)["stopped_by"]), (False, "no_more_books"))
        for bad in (0, -1, 1.5, "3", None, True):
            with self.subTest(max_books=bad), self.assertRaises(KbError):
                self.count(max_books=bad)
        with self.assertRaises(KbError):
            self.count(max_events_bytes=0)

    def test_a_library_that_cannot_be_listed_is_a_problem_and_zero_counts(self):
        store = types.SimpleNamespace(list_books=mock.Mock(side_effect=OSError(errno.EACCES, "denied")))
        got = cs.crawl_books(store)
        self.assertEqual((got["books_scanned"], got["filed_total"], got["unreviewed"]), (0, 0, 0))
        self.assertTrue(got["problem"])

    def test_nothing_is_written_and_only_the_root_file_and_the_events_log_are_opened(self):
        for _ in range(3):
            self.book()
        self.book(auto=False, found=False)

        def listing():
            return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in Path(self.bulk).rglob("*"))

        before = listing()
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(os.path.basename(str(path)))
            return real(path, *a, **k)

        with mock.patch.object(os, "open", spy):
            self.count()
        self.assertEqual(listing(), before)
        self.assertTrue(set(opened) <= {"book.json", "events.jsonl"}, set(opened))

    def test_the_text_of_an_event_is_never_in_the_result(self):
        self.book(events=[("note", {"text": "Cookie: sid=1" + RLO})])
        self.assertNotIn("sid=1", repr(self.count()))


class ListsBase(StateBase):
    NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
    DATA = b"a.example\nb.example\nc.example\n"
    ON = {"phishing_domains": True, "urlhaus_recent": True}

    def lists_dir(self):
        folder = self.tmp / "crawl" / "lists"
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        return folder

    def put_list(self, name="phishing_domains", ext="txt", data=None, **over):
        data = self.DATA if data is None else data
        sha = hashlib.sha256(data).hexdigest()
        fname = f"{name}.{sha[:16]}.{ext}"
        folder = self.lists_dir()
        (folder / fname).write_bytes(data)
        meta = {"source": "https://example.org/list.txt", "retrieved": "2026-11-16T06:00:00Z", "checked": "2026-11-16T09:00:00Z", "sha256": sha,
                "bytes": len(data), "entries": 3, "etag": None, "last_modified": None, "file": fname}
        meta.update(over)
        (folder / f"{name}.meta.json").write_text(json.dumps(meta))
        return meta, fname


class PublicListsTest(ListsBase):
    def report(self, values=None):
        return cs.public_lists(self.tmp, self.ON if values is None else values, self.NOW)

    def by_name(self, got):
        return {e["name"]: e for e in got["lists"]}

    def test_the_constants_are_the_list_modules(self):
        from kb import weblists
        self.assertEqual(cs.MAX_META_BYTES, weblists.MAX_META_BYTES)
        self.assertEqual(cs.MAX_STORED_BYTES, weblists.MAX_STORED_BYTES)
        self.assertEqual(tuple((n, weblists.EXTENSIONS[n], req) for n, _k, _u, req in weblists.LISTS), cs.PUBLIC_LISTS)

    def test_a_good_record_gives_its_times_ages_counts_and_the_start_of_its_hash(self):
        meta, _ = self.put_list()
        got = self.by_name(self.report())["phishing_domains"]
        self.assertEqual(got, {"name": "phishing_domains", "on": True, "required": True, "status": "ok", "reason": None,
                               "checked": "2026-11-16T09:00:00Z", "retrieved": "2026-11-16T06:00:00Z", "age_hours": 3.0, "retrieved_age_hours": 6.0,
                               "entries": 3, "bytes": len(self.DATA), "sha256_12": meta["sha256"][:12], "data": "ok"})

    def test_both_lists_are_given_in_order_and_the_suffix_list_is_always_on(self):
        self.put_list("public_suffix", "dat")
        got = self.report({"phishing_domains": False})
        self.assertEqual([e["name"] for e in got["lists"]], ["phishing_domains", "public_suffix"])
        names = self.by_name(got)
        self.assertEqual((names["phishing_domains"]["status"], names["phishing_domains"]["on"]), ("off", False))
        self.assertEqual((names["public_suffix"]["status"], names["public_suffix"]["on"], names["public_suffix"]["required"]), ("ok", True, False))

    def test_a_list_that_is_off_is_not_read(self):
        self.put_list()
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)

        with mock.patch.object(os, "open", spy):
            got = self.by_name(self.report({"phishing_domains": False}))["phishing_domains"]
        self.assertEqual((got["status"], got["checked"], got["entries"]), ("off", None, None))
        self.assertFalse([p for p in opened if "phishing_domains" in p])

    def test_a_list_that_has_no_copy_says_what_the_runner_does_about_it(self):
        got = self.by_name(self.report())
        self.assertEqual((got["phishing_domains"]["status"], got["public_suffix"]["status"]), ("no_copy", "no_copy"))
        self.assertIn("the runner would stop", got["phishing_domains"]["reason"])
        self.assertIn("optional", got["public_suffix"]["reason"])
        self.assertNotIn("stop", got["public_suffix"]["reason"])

    def test_a_plan_that_does_not_say_is_read_all_the_same_and_the_state_is_unknown(self):
        self.put_list()
        got = self.by_name(self.report({}))["phishing_domains"]
        self.assertEqual((got["on"], got["status"]), (None, "ok"))

    def test_a_record_that_cannot_be_read_is_a_bad_record_and_says_no_more(self):
        meta, _ = self.put_list()
        good = json.dumps(meta)
        sha = meta["sha256"]
        cases = [b"", b"not json", b"[]", b'"text"', b"null", b"{", b"\xff\xfe" + good.encode(), good.encode() + b" " * cs.MAX_META_BYTES,
                 json.dumps({**meta, "sha256": sha.upper()}).encode(), json.dumps({**meta, "sha256": sha[:63]}).encode(),
                 json.dumps({**meta, "sha256": sha.upper(), "file": meta["file"].replace(sha[:16], sha[:16].upper())}).encode(),
                 json.dumps({k: v for k, v in meta.items() if k != "sha256"}).encode(), json.dumps({**meta, "checked": "yesterday"}).encode(),
                 json.dumps({k: v for k, v in meta.items() if k != "checked"}).encode(), json.dumps({**meta, "file": "other.txt"}).encode(),
                 json.dumps({**meta, "file": 5}).encode(), json.dumps({k: v for k, v in meta.items() if k != "file"}).encode(),
                 json.dumps({**meta, "file": "../" + meta["file"]}).encode(),
                 b'{"sha256": "%s", "sha256": "%s", "checked": "2026-11-16T09:00:00Z", "file": "%s"}' % (sha.encode(), sha.encode(), meta["file"].encode()),
                 good.replace('"bytes"', '"bytes": NaN, "x"').encode()]
        for data in cases:
            with self.subTest(data=data[:50]):
                (self.tmp / "crawl" / "lists" / "phishing_domains.meta.json").write_bytes(data)
                got = self.by_name(self.report())["phishing_domains"]
                self.assertEqual((got["status"], got["checked"], got["entries"], got["sha256_12"]), ("bad_record", None, None, None))
                self.assertNotIn("SECRET", repr(got))

    def test_a_record_that_is_a_link_a_folder_or_a_pipe_is_not_read(self):
        folder = self.lists_dir()
        (self.tmp / "real.json").write_text(json.dumps(self.put_list()[0]))
        for make in (lambda p: os.symlink(self.tmp / "real.json", p), lambda p: p.mkdir(), lambda p: os.mkfifo(p)):
            path = folder / "phishing_domains.meta.json"
            path.unlink()
            make(path)
            got = self.within(lambda: self.by_name(self.report())["phishing_domains"])
            self.assertEqual(got["status"], "bad_record")
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
            path.write_text("{}")

    def test_a_data_file_that_is_missing_of_another_size_or_not_a_plain_file_is_bad_data(self):
        meta, fname = self.put_list()
        data = self.lists_dir() / fname
        data.write_bytes(self.DATA + b"x")
        self.assertEqual(self.by_name(self.report())["phishing_domains"]["data"], "size_differs")
        data.unlink()
        self.assertEqual(self.by_name(self.report())["phishing_domains"]["data"], "missing")
        os.symlink(self.tmp / "nowhere", data)
        self.assertEqual(self.by_name(self.report())["phishing_domains"]["data"], "not_a_plain_file")
        data.unlink()
        data.mkdir()
        got = self.by_name(self.report())["phishing_domains"]
        self.assertEqual((got["status"], got["data"]), ("bad_data", "not_a_plain_file"))
        self.assertEqual((got["checked"], got["entries"]), ("2026-11-16T09:00:00Z", 3))

    def test_a_data_file_over_the_size_the_matcher_reads_is_bad_data_whatever_the_record_says(self):
        self.put_list()
        with mock.patch.object(cs, "MAX_STORED_BYTES", len(self.DATA) - 1):
            got = self.by_name(self.report())["phishing_domains"]
        self.assertEqual((got["status"], got["data"]), ("bad_data", "too_large"))
        with mock.patch.object(cs, "MAX_STORED_BYTES", len(self.DATA)):
            self.assertEqual(self.by_name(self.report())["phishing_domains"]["status"], "ok")

    def test_the_data_file_is_not_read_and_nothing_of_the_list_is_in_the_answer(self):
        data = b"SECRETHOST.example\nother.example\n"
        _, fname = self.put_list(data=data)
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(os.path.basename(str(path)))
            return real(path, *a, **k)

        with mock.patch.object(os, "open", spy):
            got = self.report()
        self.assertNotIn(fname, opened)
        self.assertNotIn("SECRETHOST", json.dumps(got))

    def test_the_ages_come_from_the_record_and_a_time_in_the_future_has_no_age(self):
        self.put_list(checked="2026-11-16T11:30:00Z", retrieved="2026-11-13T12:00:00Z")
        got = self.by_name(self.report())["phishing_domains"]
        self.assertEqual((got["age_hours"], got["retrieved_age_hours"]), (0.5, 72.0))
        self.put_list(checked="2026-11-16T13:00:00Z", retrieved="2026-11-16T14:00:00Z")
        got = self.by_name(self.report())["phishing_domains"]
        self.assertEqual((got["age_hours"], got["retrieved_age_hours"]), (None, None))

    def test_a_count_or_size_that_is_not_a_whole_number_is_unknown_and_does_not_make_the_record_bad(self):
        for entries, size in (("many", -5), (True, False), (1.5, [3]), (None, {"a": 1})):
            with self.subTest(entries=entries, size=size):
                self.put_list(entries=entries, bytes=size, retrieved="soon")
                got = self.by_name(self.report())["phishing_domains"]
                self.assertEqual((got["status"], got["entries"], got["bytes"], got["retrieved"], got["data"]), ("ok", None, None, None, "ok"))

    def test_a_lists_folder_that_is_a_link_or_not_the_owners_or_under_a_crawl_that_is_a_link_is_not_read(self):
        real = self.tmp / "elsewhere"
        real.mkdir()
        self.put_list()
        shutil.move(str(self.tmp / "crawl" / "lists"), str(real / "lists"))
        os.symlink(real / "lists", self.tmp / "crawl" / "lists")
        got = self.report()
        self.assertTrue(got["problem"])
        self.assertEqual({e["status"] for e in got["lists"]}, {"bad_folder"})
        os.unlink(self.tmp / "crawl" / "lists")
        shutil.move(str(real / "lists"), str(self.tmp / "crawl" / "lists"))
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            self.assertTrue(self.report()["problem"])
        shutil.move(str(self.tmp / "crawl"), str(real / "crawl"))
        os.symlink(real / "crawl", self.tmp / "crawl")
        got = self.report()
        self.assertTrue(got["problem"])
        self.assertEqual({e["status"] for e in got["lists"]}, {"bad_folder"})

    def test_no_crawl_folder_is_no_copy_and_no_problem(self):
        got = self.report()
        self.assertEqual((got["problem"], {e["status"] for e in got["lists"]}), (None, {"no_copy"}))

    def test_a_list_made_by_the_real_updater_is_read_in_the_form_it_wrote(self):
        from kb import weblists
        body = "".join(f"h{i}.example\n" for i in range(100_500)).encode()
        suffixes = "".join(f"s{i}\n" for i in range(6_000)).encode()

        def get(url, *args, **kwargs):
            return 200, {"etag": '"v1"'}, (suffixes if "suffix" in url else body)

        matcher = weblists.Matcher(self.tmp / "black.txt", self.tmp / "allow.txt", self.lists_dir(), ["openalex.org"])
        made = matcher.update(get, self.NOW - datetime.timedelta(hours=2), {})
        self.assertEqual(made["lists"]["phishing_domains"]["status"], "updated", made)
        got = self.by_name(self.report())
        self.assertEqual((got["phishing_domains"]["status"], got["phishing_domains"]["data"]), ("ok", "ok"))
        self.assertEqual((got["phishing_domains"]["entries"], got["phishing_domains"]["bytes"], got["phishing_domains"]["age_hours"]), (100_500, len(body), 2.0))
        self.assertEqual((got["public_suffix"]["status"], got["public_suffix"]["bytes"]), ("ok", len(suffixes)))

    def test_nothing_is_written(self):
        self.put_list()
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*"))
        self.report()
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*")), before)


class UrlhausStateTest(ListsBase):
    def put_state(self, **over):
        path = self.lists_dir() / "urlhaus.json"
        shutil.copy(FIX / "lists" / "urlhaus.json", path)
        os.chmod(path, 0o600)
        if over:
            obj = json.loads(path.read_text())
            for key, value in over.items():
                if value is cs:
                    obj.pop(key, None)
                else:
                    obj[key] = value
            path.write_text(json.dumps(obj))
        return path

    def report(self, values=None):
        return cs.urlhaus_state(self.tmp, self.ON if values is None else values, self.NOW)

    def test_the_constants_are_the_modules(self):
        from kb import urlhaus
        self.assertEqual(cs.URLHAUS_STATE, urlhaus.STATE_FILE)

    def test_off_in_the_plan_is_off_and_the_file_is_not_read(self):
        self.put_state()
        opened = []
        real = os.open

        def spy(path, *a, **k):
            opened.append(os.path.basename(str(path)))
            return real(path, *a, **k)

        with mock.patch.object(os, "open", spy):
            got = self.report({"urlhaus_recent": False})
        self.assertEqual((got["on"], got["state"]), (False, "off"))
        self.assertNotIn("urlhaus.json", opened)

    def test_on_with_no_state_file_has_made_no_request_yet(self):
        got = self.report()
        self.assertEqual((got["on"], got["state"], got["kept_urls"]), (True, "no_state_file", None))

    def test_a_good_state_gives_the_time_of_the_last_request_and_its_age_and_the_kept_urls_as_a_number(self):
        self.put_state()
        got = self.report()
        self.assertEqual((got["state"], got["last_request"], got["age_s"], got["off_day"], got["off_for_the_day"]),
                         ("ok", "2026-11-16T11:30:00Z", 1800, None, False))
        self.assertEqual((got["kept_urls"], got["newest_kept"]), (3, "2026-11-16"))
        self.assertNotIn("example", json.dumps(got))

    def test_the_source_is_off_for_the_day_only_when_its_off_day_is_the_utc_day_of_now(self):
        self.put_state(off_day="2026-11-16")
        self.assertEqual((self.report()["off_day"], self.report()["off_for_the_day"]), ("2026-11-16", True))
        self.put_state(off_day="2026-11-15")
        self.assertEqual((self.report()["off_day"], self.report()["off_for_the_day"]), ("2026-11-15", False))

    def test_a_last_request_in_the_future_has_no_age(self):
        self.put_state(last="2026-11-16T13:00:00Z")
        got = self.report()
        self.assertEqual((got["state"], got["last_request"], got["age_s"]), ("ok", "2026-11-16T13:00:00Z", None))

    def test_the_off_day_is_compared_with_the_utc_day_whatever_the_zone_of_now(self):
        self.put_state(off_day="2026-11-16")
        new_york = datetime.timezone(datetime.timedelta(hours=-5))
        now = datetime.datetime(2026, 11, 15, 22, 0, 0, tzinfo=new_york)  # 2026-11-16T03:00:00Z
        self.assertEqual(cs.urlhaus_state(self.tmp, self.ON, now)["off_for_the_day"], True)
        now = datetime.datetime(2026, 11, 16, 20, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))  # 2026-11-17T01:00:00Z
        self.assertEqual(cs.urlhaus_state(self.tmp, self.ON, now)["off_for_the_day"], False)

    def test_a_state_with_no_last_request_or_no_version_is_taken_as_urlhaus_takes_it(self):
        self.put_state(last=None, version=cs)
        got = self.report()
        self.assertEqual((got["state"], got["last_request"], got["age_s"]), ("ok", None, None))

    def test_entries_that_are_not_a_url_and_a_date_are_not_counted(self):
        self.put_state(entries={"https://a.example/x": "2026-11-10", "https://b.example/y": "not a date", 5: "2026-11-11", "https://c.example/z": 7,
                                "https://d.example/" + "x" * 2000: "2026-11-12"})
        got = self.report()
        self.assertEqual((got["kept_urls"], got["newest_kept"]), (1, "2026-11-10"))

    def test_a_state_that_cannot_be_trusted_is_damaged_and_says_the_source_makes_no_request(self):
        good = json.loads((FIX / "lists" / "urlhaus.json").read_text())
        cases = [b"", b"not json", b"[]", b"null", b'{"entries": []}', json.dumps({**good, "entries": ["a"]}).encode(),
                 json.dumps({k: v for k, v in good.items() if k != "entries"}).encode(), json.dumps({**good, "version": 2}).encode(),
                 json.dumps({**good, "version": True}).encode(), json.dumps({**good, "version": "1"}).encode(),
                 json.dumps({**good, "last": "yesterday"}).encode(), json.dumps({**good, "last": 5}).encode(),
                 json.dumps({**good, "off_day": "2026-13-40"}).encode(), json.dumps({**good, "off_day": 5}).encode(),
                 b'{"entries": {}, "version": 1, "version": 1}', b'{"entries": {}, "last": NaN}', b"\xff\xfe" + json.dumps(good).encode()]
        for data in cases:
            with self.subTest(data=data[:50]):
                path = self.put_state()
                path.write_bytes(data)
                got = self.report()
                self.assertEqual((got["state"], got["kept_urls"], got["last_request"]), ("damaged", None, None))
                self.assertIn("the source makes no request today", got["detail"])
                self.assertNotIn("SECRET", repr(got))

    def test_a_state_that_is_a_link_a_folder_a_pipe_loose_or_of_another_owner_is_damaged_and_not_read(self):
        folder = self.lists_dir()
        shutil.copy(FIX / "lists" / "urlhaus.json", self.tmp / "real.json")
        for name, make in {"link": lambda p: os.symlink(self.tmp / "real.json", p), "folder": lambda p: p.mkdir(), "pipe": lambda p: os.mkfifo(p),
                           "loose": lambda p: (shutil.copy(self.tmp / "real.json", p), os.chmod(p, 0o644)),
                           "group": lambda p: (shutil.copy(self.tmp / "real.json", p), os.chmod(p, 0o640))}.items():
            with self.subTest(case=name):
                path = folder / "urlhaus.json"
                make(path)
                got = self.within(lambda: self.report())
                self.assertEqual((got["state"], got["kept_urls"]), ("damaged", None))
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
        self.put_state()
        with mock.patch.object(cs, "_me", return_value=os.getuid() + 1):
            self.assertEqual(self.report()["state"], "damaged")

    def test_a_state_over_the_size_is_not_read_and_its_size_is_said(self):
        path = self.put_state()
        size = path.stat().st_size
        reads = []
        real = os.pread

        def spy(fd, n, offset):
            reads.append(n)
            return real(fd, n, offset)

        with mock.patch.object(cs, "MAX_URLHAUS_BYTES", size - 1), mock.patch.object(os, "pread", spy):
            got = self.report()
        self.assertEqual((got["state"], got["size_bytes"], got["kept_urls"], got["last_request"]), ("too_large", size, None, None))
        self.assertEqual(reads, [])
        with mock.patch.object(cs, "MAX_URLHAUS_BYTES", size):
            self.assertEqual(self.report()["state"], "ok")

    def test_the_key_file_is_never_opened_and_its_path_is_never_looked_at(self):
        self.put_state()
        (self.tmp / "urlhaus.key").write_text("K" * 40)
        (self.tmp / "urlhaus.key").chmod(0o600)
        seen = []
        real_open, real_lstat = os.open, os.lstat

        def spy_open(path, *a, **k):
            seen.append(str(path))
            return real_open(path, *a, **k)

        def spy_lstat(path, *a, **k):
            seen.append(str(path))
            return real_lstat(path, *a, **k)

        with mock.patch.object(os, "open", spy_open), mock.patch.object(os, "lstat", spy_lstat), mock.patch("builtins.open", side_effect=AssertionError):
            self.report()
        self.assertFalse([p for p in seen if p.endswith(".key")])

    def test_a_lists_folder_that_is_a_link_gives_a_state_that_cannot_be_read(self):
        real = self.tmp / "elsewhere"
        real.mkdir()
        shutil.copy(FIX / "lists" / "urlhaus.json", real / "urlhaus.json")
        (self.tmp / "crawl").mkdir()
        os.symlink(real, self.tmp / "crawl" / "lists")
        got = self.report()
        self.assertEqual((got["state"], got["kept_urls"]), ("damaged", None))

    def test_nothing_is_written(self):
        self.put_state()
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*"))
        self.report()
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.tmp.rglob("*")), before)


class ReasonsTest(QueueBase):
    def rows(self, conn, status, count, reason="r", start=0):
        for i in range(count):
            self.put(conn, f"{status}{start + i:03d}", status, f"2026-11-{10 + (start + i) // 24:02d}T{(start + i) % 24:02d}:00:00Z", reason=f"{reason}{start + i}")

    def test_the_ten_most_recent_rows_of_each_status_newest_first(self):
        w = self.make_queue()
        self.rows(w, "failed", 12)
        self.rows(w, "rejected", 3)
        self.rows(w, "queued", 5)
        got = cs.queue_reasons(self.opened().conn)
        self.assertEqual(set(got), {"rejected", "failed", "blocked"})
        recent = got["failed"]["recent"]
        self.assertEqual(len(recent), 10)
        self.assertEqual([r["reason"] for r in recent], [f"r{i}" for i in range(11, 1, -1)])
        self.assertEqual((len(got["rejected"]["recent"]), got["blocked"]["recent"]), (3, []))

    def test_a_row_shows_its_address_source_reason_tries_and_time(self):
        w = self.make_queue()
        self.put(w, "a", "failed", "2026-11-16T10:00:00Z", reason="HTTP 503")
        w.execute("UPDATE candidates SET tries = 2 WHERE identity_key = 'a'")
        got = cs.queue_reasons(self.opened().conn)["failed"]["recent"]
        self.assertEqual(got, [{"address": "https://example.org/a", "source": "arxiv", "reason": "HTTP 503", "tries": 2, "updated": "2026-11-16T10:00:00Z"}])

    def test_a_row_with_no_reason_shows_none_and_a_row_with_an_empty_one_shows_the_empty_text(self):
        w = self.make_queue()
        self.put(w, "a", "failed", "2026-11-16T10:00:00Z", reason=None)
        self.put(w, "b", "failed", "2026-11-16T09:00:00Z", reason="")
        got = cs.queue_reasons(self.opened().conn)["failed"]["recent"]
        self.assertEqual([r["reason"] for r in got], [None, ""])

    def test_rows_with_the_same_time_are_newest_id_first(self):
        w = self.make_queue()
        for key in ("first", "second", "third"):
            self.put(w, key, "failed", "2026-11-16T10:00:00Z", reason=key)
        got = cs.queue_reasons(self.opened().conn)["failed"]["recent"]
        self.assertEqual([r["reason"] for r in got], ["third", "second", "first"])

    def test_the_commonest_reasons_with_their_counts_merged_after_cleaning(self):
        w = self.make_queue()
        for i, reason in enumerate(["HTTP 503"] * 4 + ["HTTP" + ZWSP + " 503"] * 2 + ["timeout"] * 3 + [None, ""]):
            self.put(w, f"k{i}", "failed", reason=reason)
        for i in range(12):
            self.put(w, f"u{i}", "failed", reason=f"unique {i:02d}")
        got = cs.queue_reasons(self.opened().conn)["failed"]["commonest"]
        self.assertEqual(len(got), 10)
        self.assertEqual(got[0], {"reason": "HTTP 503", "n": 6})
        self.assertEqual(got[1], {"reason": "timeout", "n": 3})
        self.assertEqual(got[2], {"reason": "(no reason)", "n": 2})
        self.assertEqual([g["n"] for g in got[3:]], [1] * 7)

    def test_text_from_a_row_is_redacted_cleaned_and_cut(self):
        w = self.make_queue()
        self.put(w, "a", "rejected", reason="Cookie: sid=1" + RLO)
        self.put(w, "b", "rejected", reason="x" * 5000)
        self.put(w, "c", "rejected", reason="a" + chr(0x1b) + "[31m" + ZWSP + "b\nc")
        w.execute("UPDATE candidates SET address = ? WHERE identity_key = 'a'", ("https://user:pw@example.org/p?token=ABC&a=1" + "y" * 400,))
        w.execute("UPDATE candidates SET source = ? WHERE identity_key = 'b'", ("s" * 100,))
        got = cs.queue_reasons(self.opened().conn)["rejected"]["recent"]
        by = {r["address"].split("/")[-1][:1]: r for r in got}
        text = json.dumps(got)
        self.assertNotIn("sid=1", text)
        self.assertNotIn("ABC", text)
        self.assertNotIn("user:pw", text)
        self.assertIn(cs.WITHHELD, text)
        reasons = sorted(r["reason"] for r in got)
        self.assertIn("a[31mb c", reasons)
        self.assertTrue(all(len(r["address"]) <= 200 and len(r["reason"]) <= 300 and len(r["source"]) <= 20 for r in got))
        self.assertEqual(len(by), len(got))

    def test_a_row_with_odd_types_is_shown_cleanly_and_does_not_stop_the_rest(self):
        w = self.make_queue()
        self.put(w, "a", "failed")
        w.execute("UPDATE candidates SET tries = 'many', reason = x'414243', updated = 5 WHERE identity_key = 'a'")
        self.put(w, "b", "failed", reason="fine")
        got = cs.queue_reasons(self.opened().conn)["failed"]["recent"]
        self.assertEqual(len(got), 2)
        odd = [r for r in got if r["reason"] != "fine"][0]
        self.assertIsNone(odd["tries"])
        self.assertEqual(odd["updated"], "5")

    def test_a_time_with_hostile_text_is_cleaned(self):
        w = self.make_queue()
        self.put(w, "a", "failed", "2026-11-16T10:00:00Z" + RLO + chr(0x1b) + "[31m" + "x" * 50)
        got = cs.queue_reasons(self.opened().conn)["failed"]["recent"]
        self.assertNotIn(RLO, got[0]["updated"])
        self.assertNotIn(chr(0x1b), got[0]["updated"])
        self.assertLessEqual(len(got[0]["updated"]), 20)

    def test_only_selects_are_made(self):
        self.make_queue().close()
        before = self.main_state()
        cs.queue_reasons(self.opened().conn)
        self.assertEqual(self.main_state(), before)


class HoldsTest(StateBase):
    def hold(self, ts, **kw):
        return dict(ts=ts, run="r1", step="hold", outcome="held", **kw)

    def test_the_ten_newest_holds_across_the_newest_files_with_their_reason_book_and_host(self):
        for day in (13, 14, 15):
            self.put_log(f"2026-11-{day}", *[self.hold(f"2026-11-{day}T0{i}:00:00Z", book=f"b{day}-{i}", host=f"h{i}.example", reason=f"javascript {i}") for i in range(5)])
        got = cs.recent_holds(self.tmp)
        self.assertEqual(len(got["holds"]), 10)
        self.assertEqual(got["holds"][0], {"ts": "2026-11-15T04:00:00Z", "book": "b15-4", "host": "h4.example", "reason": "javascript 4"})
        self.assertEqual(got["holds"][-1]["ts"], "2026-11-14T00:00:00Z")
        self.assertEqual((got["files_read"], got["problem"]), (2, None))

    def test_holds_with_the_same_time_are_newest_line_first_and_across_files_bad_lines_add_up(self):
        self.put_log("2026-11-15", self.hold("2026-11-15T05:00:00Z", book="old-1"), self.hold("2026-11-15T05:00:00Z", book="old-2"))
        self.put_log("2026-11-16", self.hold("2026-11-16T05:00:00Z", book="new-1"), self.hold("2026-11-16T05:00:00Z", book="new-2"))
        for day in ("15", "16"):
            with open(self.tmp / "crawl" / "log" / f"crawl-2026-11-{day}.jsonl", "ab") as f:
                f.write(b"junk\n")
        got = cs.recent_holds(self.tmp)
        self.assertEqual([h["book"] for h in got["holds"]], ["new-2", "new-1", "old-2", "old-1"])
        self.assertEqual(got["bad"], {"not_json": 2})

    def test_a_log_file_that_cannot_be_read_is_not_counted_among_the_files_read_and_the_others_are_still_searched(self):
        self.no_root_powers()
        self.put_log("2026-11-14", self.hold("2026-11-14T05:00:00Z", book="older"))
        self.put_log("2026-11-15", self.hold("2026-11-15T05:00:00Z", book="newer"))
        path = self.tmp / "crawl" / "log" / "crawl-2026-11-15.jsonl"
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        got = cs.recent_holds(self.tmp)
        self.assertEqual(([h["book"] for h in got["holds"]], got["searched_files"], got["files_read"]), (["older"], 2, 1))

    def test_other_steps_and_refusals_are_not_holds(self):
        self.put_log("2026-11-16", self.hold("2026-11-16T05:00:00Z", book="b1", reason="encrypted"),
                     dict(ts="2026-11-16T06:00:00Z", run="", step="refuse", outcome="refused", reason="the stop file exists"),
                     dict(ts="2026-11-16T07:00:00Z", run="r1", step="reject", outcome="rejected", reason="not a document"),
                     dict(ts="2026-11-16T08:00:00Z", run="r1", step="scan", outcome="held", reason="scan failed"))
        got = cs.recent_holds(self.tmp)["holds"]
        self.assertEqual([h["book"] for h in got], ["b1"])

    def test_the_search_goes_back_only_as_far_as_it_must_and_no_further_than_the_bound(self):
        for day in range(1, 8):
            self.put_log(f"2026-11-{day:02d}", self.hold(f"2026-11-{day:02d}T05:00:00Z", book=f"b{day}"))
        got = cs.recent_holds(self.tmp)
        self.assertEqual((len(got["holds"]), got["searched_files"]), (5, 5))
        self.assertEqual(got["holds"][0]["book"], "b7")
        got = cs.recent_holds(self.tmp, max_files=2, limit=1)
        self.assertEqual(([h["book"] for h in got["holds"]], got["searched_files"]), (["b7"], 1))

    def test_text_is_redacted_and_cleaned(self):
        self.put_log("2026-11-16", self.hold("2026-11-16T05:00:00Z", book="b" + RLO + "1", host="h" + chr(0x1b) + ".example", reason="Auth-Key: abc"))
        got = cs.recent_holds(self.tmp)["holds"][0]
        self.assertEqual((got["book"], got["host"], got["reason"]), ("b1", "h.example", cs.WITHHELD))

    def test_a_hold_with_no_reason_book_or_host_is_shown_with_none(self):
        self.put_log("2026-11-16", self.hold("2026-11-16T05:00:00Z"))
        self.assertEqual(cs.recent_holds(self.tmp)["holds"], [{"ts": "2026-11-16T05:00:00Z", "book": None, "host": None, "reason": None}])

    def test_bad_lines_and_a_cut_are_passed_on_and_no_log_is_no_holds(self):
        self.assertEqual(cs.recent_holds(self.tmp)["holds"], [])
        folder = self.tmp / "crawl" / "log"
        folder.mkdir(parents=True)
        lines = [raw(**self.hold(f"2026-11-16T05:{i:02d}:00Z", book=f"b{i}")) for i in range(40)]
        (folder / "crawl-2026-11-16.jsonl").write_bytes(b"\n".join(lines) + b"\njunk\n")
        got = cs.recent_holds(self.tmp, limit=3, per_file_limit=1500)
        self.assertEqual((got["cut"], got["bad"], len(got["holds"])), (True, {"not_json": 1}, 3))
        self.assertEqual([h["book"] for h in got["holds"]], ["b39", "b38", "b37"])

    def test_bounds_are_whole_numbers_of_at_least_one(self):
        for name in ("max_files", "limit", "per_file_limit"):
            for bad in (0, -1, 1.5, "3", None, True):
                with self.subTest(name=name, value=bad), self.assertRaises(KbError):
                    cs.recent_holds(self.tmp, **{name: bad})


class StatusTest(StoreCase):
    within = Base.within
    NOW = datetime.datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
    VALUES = {"fetches_per_day": 5, "per_domain_per_day": 3, "cards_per_day": 30, "filed_total": 2, "timezone": "UTC", "bulk_floor_gb": 1,
              "index_floor_gb": 1, "domain_refusals": 3, "phishing_domains": True, "urlhaus_recent": True}

    def setUp(self):
        super().setUp()
        self.root = Path(self.index)
        (self.root / "crawl").mkdir(exist_ok=True)

    def vfs(self, path):
        return types.SimpleNamespace(f_bavail=50 * 1024 * 1024, f_frsize=4096)

    def reader(self, values=None):
        return lambda path: dict(self.VALUES if values is None else values)

    def approve(self):
        shutil.copytree(FIX / "approved", self.root / "crawl" / "approved")

    def breaker_ok(self):
        shutil.copy(FIX / "state" / "breaker-not-tripped.json", self.root / "crawl" / "breaker.json")

    def queue(self):
        conn = crawlqueue.connect(self.root)
        self.addCleanup(conn.close)
        return conn

    def put(self, conn, key, status, updated="2026-11-16T05:00:00Z", reason=None):
        conn.execute("INSERT INTO candidates (identity_key, address, source, status, domain, reason, added, updated) VALUES (?,?,?,?,?,?,?,?)",
                     (key, f"https://example.org/{key}", "arxiv", status, "example.org", reason, updated, updated))

    def status(self, read_plan=None, **kw):
        return cs.status(self.index, self.bulk, read_plan=read_plan or self.reader(), store=self.store, now=kw.pop("now", self.NOW),
                         statvfs=kw.pop("statvfs", self.vfs), **kw)

    def strings(self, obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for key, value in obj.items():
                yield from self.strings(key)
                yield from self.strings(value)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                yield from self.strings(item)

    def test_every_part_is_there_and_the_whole_is_plain_data(self):
        self.approve()
        self.breaker_ok()
        got = self.status()
        for key in ("generated", "notes", "plan", "state", "queue", "books", "last_run", "runs_today", "idle_today", "disk", "lists", "holds", "log"):
            self.assertIn(key, got)
        self.assertEqual(json.loads(json.dumps(got)), got)
        self.assertEqual(got["generated"], "2026-11-16T12:00:00Z")

    def test_an_approved_plan_shows_its_zone_ceilings_and_floors_and_no_defaults(self):
        self.approve()
        self.breaker_ok()
        w = self.queue()
        self.put(w, "a", "failed", reason="HTTP 503")
        w.execute("INSERT INTO counters (day, key, n) VALUES ('2026-11-16', 'fetch', 5)")
        got = self.status()
        self.assertEqual((got["plan"]["status"], got["plan"]["zone"], got["plan"]["zone_problem"], got["plan"]["defaults_used"]), ("approved", "UTC", None, False))
        self.assertEqual(got["plan"]["digest"], "0123456789ab")
        self.assertEqual(got["queue"]["status"], "ok")
        self.assertEqual(got["queue"]["counters"]["fetch"], {"n": 5, "limit": 5, "at_or_over": True})
        self.assertEqual(got["queue"]["counts"]["all"]["failed"], 1)
        self.assertEqual(got["queue"]["reasons"]["failed"]["recent"][0]["reason"], "HTTP 503")
        self.assertEqual(got["disk"]["bulk"]["floor_bytes"], 10 ** 9)
        self.assertEqual(got["state"]["state"], "idle")
        self.assertEqual(got["notes"], [])

    def test_no_approved_plan_says_so_shows_the_counters_without_ceilings_and_uses_the_defaults_and_says_it(self):
        self.breaker_ok()
        w = self.queue()
        w.execute("INSERT INTO counters (day, key, n) VALUES (?, 'fetch', 5)", (self.NOW.date().isoformat(),))
        got = self.status()
        self.assertEqual((got["plan"]["status"], got["plan"]["defaults_used"], got["plan"]["zone"]), ("none", True, "local"))
        self.assertEqual(got["queue"]["counters"]["fetch"], {"n": 5, "limit": None, "at_or_over": None})
        self.assertFalse(got["queue"]["counters"]["ceilings_known"])
        self.assertTrue(got["notes"][0].startswith("no approved plan"))
        self.assertEqual((got["disk"]["bulk"]["floor_bytes"], got["disk"]["index"]["floor_bytes"]), (50 * 10 ** 9, 10 * 10 ** 9))
        self.assertTrue(any("no approved plan" in n for n in got["notes"]))
        self.assertEqual(got["books"]["filed"]["limit"], None)
        names = {e["name"]: e for e in got["lists"]["public"]["lists"]}
        self.assertEqual((names["phishing_domains"]["on"], got["lists"]["urlhaus"]["on"]), (True, False))

    def test_a_plan_that_cannot_be_read_says_why_and_the_other_parts_go_on(self):
        self.approve()
        self.breaker_ok()
        got = self.status(read_plan=mock.Mock(side_effect=KbError("the crawl plan: line 3: bad value")))
        self.assertEqual(got["plan"]["status"], "unreadable")
        self.assertIn("line 3", got["plan"]["reason"])
        self.assertEqual(got["plan"]["zone"], "local")
        self.assertTrue(got["plan"]["zone_problem"])
        self.assertTrue(got["plan"]["defaults_used"])
        self.assertTrue(got["notes"][0].startswith("the approved plan cannot be read"))
        self.assertEqual(got["state"]["state"], "idle")

    def test_a_zone_the_system_lacks_is_local_with_its_problem_shown(self):
        self.approve()
        self.breaker_ok()
        got = self.status(read_plan=self.reader({**self.VALUES, "timezone": "Mars/Olympus"}))
        self.assertEqual(got["plan"]["zone"], "local")
        self.assertIn("not one the system knows", got["plan"]["zone_problem"])
        self.assertIn(got["plan"]["zone_problem"], got["notes"])

    def test_the_text_values_of_the_plan_are_cleaned_when_they_are_shown(self):
        self.approve()
        self.breaker_ok()
        got = self.status(read_plan=self.reader({**self.VALUES, "timezone": "Mars" + RLO + chr(0x1b) + "[31m/" + "x" * 300}))
        shown = got["plan"]["values"]["timezone"]
        self.assertNotIn(RLO, shown)
        self.assertNotIn(chr(0x1b), shown)
        self.assertLessEqual(len(shown), 100)

    def test_a_plan_part_that_itself_fails_is_an_unreadable_plan_and_the_rest_stands(self):
        self.approve()
        self.breaker_ok()
        with mock.patch.object(cs, "approved_plan", side_effect=RuntimeError("it broke: Cookie: sid=1")):
            got = self.status()
        self.assertEqual((got["plan"]["status"], got["plan"]["reason"], got["plan"]["defaults_used"]), ("unreadable", cs.WITHHELD, True))
        self.assertEqual(got["state"]["state"], "idle")

    def test_the_queue_is_closed_when_the_parts_are_made_and_when_one_of_them_fails(self):
        self.approve()
        self.breaker_ok()
        conn = mock.Mock()
        with mock.patch.object(cs, "open_queue", return_value=cs.QueueOpen(conn, "ok", None)), \
                mock.patch.object(cs, "queue_counts", side_effect=sqlite3.DatabaseError("malformed")), \
                mock.patch.object(cs, "counters_report", return_value={}), mock.patch.object(cs, "queue_reasons", return_value={}):
            self.status()
        conn.close.assert_called_once_with()

    def test_a_queue_that_cannot_even_be_opened_is_bad_and_the_rest_stands(self):
        self.approve()
        self.breaker_ok()
        with mock.patch.object(cs, "open_queue", side_effect=RuntimeError("it broke: Cookie: sid=1")):
            got = self.status()["queue"]
        self.assertEqual((got["status"], got["reason"], got["counts"]), ("bad", cs.WITHHELD, None))

    def test_the_bad_lines_of_the_files_the_last_run_and_the_holds_read_are_shown_apart_from_the_days(self):
        self.approve()
        self.breaker_ok()
        folder = self.root / "crawl" / "log"
        folder.mkdir()
        (folder / "crawl-2026-11-15.jsonl").write_bytes(
            b"junk\n" + raw(ts="2026-11-15T05:00:00Z", run="r0", step="run_start") + b"\n" +
            raw(ts="2026-11-15T06:00:00Z", run="r0", step="hold", outcome="held", book="b") + b"\n[1]\n")
        got = self.status()["log"]
        self.assertEqual((got["bad_lines"], got["by_kind"], got["cut"]), (0, {}, False))
        self.assertEqual(got["last_run_files"], {"bad": {"not_json": 1, "not_object": 1}, "cut": False})
        self.assertEqual(got["hold_files"], {"bad": {"not_json": 1, "not_object": 1}, "cut": False})

    def test_the_cut_of_the_files_the_holds_and_the_last_run_read_is_said(self):
        self.approve()
        self.breaker_ok()
        parts = {"found": False, "searched_files": 1, "files_read": 1, "bytes_read": 1, "stopped_by": "no_more_files", "bad": {}, "cut": True,
                 "problem": None}
        holds = {"holds": [], "searched_files": 1, "files_read": 1, "bad": {}, "cut": True, "problem": None}
        with mock.patch.object(cs, "last_run", return_value=parts), mock.patch.object(cs, "recent_holds", return_value=holds):
            got = self.status()["log"]
        self.assertEqual((got["last_run_files"]["cut"], got["hold_files"]["cut"], got["cut"]), (True, True, False))

    def test_the_cut_of_the_days_log_is_said(self):
        self.approve()
        self.breaker_ok()
        cut = {"day": "2026-11-16", "started": 0, "ended": 0, "ended_by_outcome": {}, "refused": 0, "refused_by_reason": {}, "bad": {}, "cut": True,
               "unreadable": 0, "problem": None, "first": None, "last": None}
        with mock.patch.object(cs, "run_counts", return_value=cut):
            self.assertTrue(self.status()["log"]["cut"])
        self.assertFalse(self.status()["log"]["cut"])

    def test_the_time_generated_is_the_utc_time_whatever_the_zone_of_now(self):
        self.approve()
        self.breaker_ok()
        now = datetime.datetime(2026, 11, 16, 7, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        self.assertEqual(self.status(now=now)["generated"], "2026-11-16T12:00:00Z")

    def test_the_day_is_the_plans_day_in_its_zone(self):
        self.approve()
        self.breaker_ok()
        w = self.queue()
        self.put(w, "in", "queued", "2026-11-16T05:00:00Z")
        self.put(w, "out", "queued", "2026-11-16T04:59:59Z")
        got = self.status(read_plan=self.reader({**self.VALUES, "timezone": "America/New_York"}))
        self.assertEqual(got["queue"]["counts"]["today"]["queued"], 1)
        self.assertEqual(got["queue"]["counters"]["day"], "2026-11-16")
        got = self.status(read_plan=self.reader({**self.VALUES, "timezone": "America/New_York"}), now=datetime.datetime(2026, 11, 17, 3, 0, 0, tzinfo=UTC))
        self.assertEqual(got["queue"]["counters"]["day"], "2026-11-16")
        self.assertEqual(got["queue"]["counters"]["discovery"]["day"], "2026-11-17")

    def test_the_filings_are_shown_against_the_ceiling_with_what_the_count_could_not_read(self):
        self.approve()
        self.breaker_ok()
        for _ in range(2):
            book = self.store.create_book(title="A", kind="preprint", auto_filed=True)
            self.store.append_event(book, "crawl_found", candidate="x")
        got = self.status()["books"]
        self.assertEqual((got["filed"], got["unreviewed"], got["unreadable"], got["cut"], got["stopped_by"]),
                         ({"n": 2, "limit": 2, "at_or_over": True}, 2, 0, False, "no_more_books"))

    def test_a_missing_queue_is_said_and_the_other_parts_go_on(self):
        self.approve()
        self.breaker_ok()
        got = self.status()
        self.assertEqual((got["queue"]["status"], got["queue"]["counts"], got["queue"]["counters"], got["queue"]["reasons"]), ("missing", None, None, None))
        self.assertEqual(got["state"]["state"], "idle")
        self.assertIn("filed", got["books"])

    def test_a_queue_that_is_busy_or_bad_is_said_with_its_reason_and_the_other_parts_go_on(self):
        self.approve()
        self.breaker_ok()
        for status in ("busy", "bad"):
            with self.subTest(status=status), mock.patch.object(cs, "open_queue", return_value=cs.QueueOpen(None, status, "the queue is " + status)):
                got = self.status()
                self.assertEqual((got["queue"]["status"], got["queue"]["reason"], got["queue"]["counts"]), (status, "the queue is " + status, None))
                self.assertIn("disk", got)

    def test_a_queue_that_fails_after_it_was_opened_is_a_fault_of_that_part_and_the_rest_stand(self):
        self.approve()
        self.breaker_ok()
        w = self.queue()
        self.put(w, "a", "failed")
        for name in ("queue_counts", "counters_report", "queue_reasons"):
            with self.subTest(part=name), mock.patch.object(cs, name, side_effect=sqlite3.DatabaseError("database disk image is malformed")):
                got = self.status()["queue"]
                self.assertEqual(got["status"], "ok")
                failed = {"queue_counts": "counts", "counters_report": "counters", "queue_reasons": "reasons"}[name]
                self.assertIn("error", got[failed])
                others = {"counts", "counters", "reasons"} - {failed}
                self.assertTrue(all("error" not in got[o] for o in others))

    def test_every_other_part_that_fails_is_a_fault_of_that_part_alone(self):
        self.approve()
        self.breaker_ok()
        for name, key in (("disk", "disk"), ("last_run", "last_run"), ("run_counts", "runs_today"), ("idle_counts", "idle_today"), ("crawl_books", "books"), ("public_lists", None),
                          ("urlhaus_state", None), ("recent_holds", "holds"), ("state", "state")):
            with self.subTest(part=name), mock.patch.object(cs, name, side_effect=RuntimeError("it broke: Cookie: sid=1")):
                got = self.status()
                self.assertEqual(json.loads(json.dumps(got)), got)
                if key:
                    self.assertEqual(set(got[key]), {"error"})
                    self.assertEqual(got[key]["error"], cs.WITHHELD)
                self.assertNotIn("sid=1", json.dumps(got))
                self.assertEqual(got["plan"]["status"], "approved")

    def test_a_log_that_is_a_link_is_a_problem_of_the_log_parts_and_not_of_the_others(self):
        self.approve()
        self.breaker_ok()
        real = self.root / "elsewhere"
        real.mkdir()
        os.symlink(real, self.root / "crawl" / "log")
        got = self.status()
        self.assertTrue(got["last_run"]["problem"])
        self.assertTrue(got["runs_today"]["problem"])
        self.assertTrue(got["holds"]["problem"])
        self.assertEqual(got["state"]["state"], "idle")

    def test_the_bad_lines_of_the_days_log_are_counted(self):
        self.approve()
        self.breaker_ok()
        folder = self.root / "crawl" / "log"
        folder.mkdir()
        (folder / "crawl-2026-11-16.jsonl").write_bytes(b"junk\n" + raw(ts="2026-11-16T05:00:00Z", step="run_start") + b"\nmore junk\n[1]\n")
        got = self.status()
        self.assertEqual((got["log"]["bad_lines"], got["log"]["by_kind"]), (3, {"not_json": 2, "not_object": 1}))
        self.assertEqual(got["runs_today"]["started"], 1)

    def test_every_text_is_cleaned_and_no_planted_secret_is_in_the_answer(self):
        self.approve()
        evil = "evil" + RLO + chr(0x1b) + "[31m" + ZWSP
        (self.root / "crawl" / "breaker.json").write_text(json.dumps({"tripped": True, "reason": "Cookie: sid=SECRET1 " + evil, "kind": "stage_bound",
                                                                       "at": "2026-11-16T05:00:00Z", "run": "r" + evil}))
        w = self.queue()
        self.put(w, "a", "failed", reason="Auth-Key: SECRET2 " + evil)
        w.execute("UPDATE candidates SET address = ? WHERE identity_key = 'a'", ("https://user:SECRET3@example.org/p?token=SECRET4&x=" + evil,))
        w.execute("INSERT INTO counters (day, key, n) VALUES ('2026-11-16', ?, 3)", ("fetch:" + evil + "Authorization: Bearer SECRET5SECRET5",))
        folder = self.root / "crawl" / "log"
        folder.mkdir()
        (folder / "crawl-2026-11-16.jsonl").write_bytes(
            raw(ts="2026-11-16T05:00:00Z", run="r" + evil, step="run_start") + b"\n" +
            raw(ts="2026-11-16T05:30:00Z", run="r" + evil, step="hold", outcome="held", book="b" + evil, host="h" + evil, reason="javascript X-Api-Key: SECRET6 " + evil) + b"\n")
        got = self.status(read_plan=mock.Mock(side_effect=KbError("bad Cookie: SECRET7")))
        text = json.dumps(got)
        for n in range(1, 8):
            self.assertNotIn(f"SECRET{n}", text)
        for value in self.strings(got):
            for char in value:
                self.assertFalse(textutil._hidden(char) or unicodedata.category(char) in ("Cc", "Zl", "Zp"), repr(value))

    def test_nothing_is_written_beyond_the_side_files_of_the_queue_and_no_socket_is_opened(self):
        self.approve()
        self.breaker_ok()
        self.queue().close()
        folder = self.root / "crawl" / "log"
        folder.mkdir()
        (folder / "crawl-2026-11-16.jsonl").write_bytes(raw(ts="2026-11-16T05:00:00Z", step="run_start") + b"\n")

        def listing():
            return {str(p): (p.stat().st_mtime_ns, p.stat().st_mode, p.stat().st_size) for p in self.root.rglob("*")}

        before = listing()
        with mock.patch("socket.socket.connect", side_effect=AssertionError("a socket was used")):
            self.status()
        after = listing()
        added = set(after) - set(before)
        self.assertEqual({os.path.basename(p) for p in added}, SIDE_FILES)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)

    def test_the_time_must_be_a_time_with_a_zone(self):
        for bad in (datetime.datetime(2026, 11, 16, 12, 0, 0), "2026-11-16T12:00:00Z", None):
            with self.subTest(now=bad), self.assertRaises(KbError):
                self.status(now=bad)


class WiringTest(crawlapprove_tests.Case):
    """The status reads what the runner's own code writes, through the runner's own plan reader (Increment G). Every file here is made by the real writer in a
    temporary folder: the approval by `crawlapprove`, the log by `crawllog`, the breaker and the lock by `crawlguard`, the counters by `crawlstate`."""
    NOW = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)

    def runTest(self):  # the base class is a fixture; its own tests are in test_crawlapprove
        pass

    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o077))

    def test_a_plan_approved_by_the_real_approval_is_read_through_the_real_reader(self):
        self.approved()
        got = cs.approved_plan(self.index, crawlplan.read_plan)
        self.assertEqual((got["status"], got["reason"]), ("approved", None))
        self.assertEqual(got["digest"], self.digest())
        self.assertEqual((got["values"]["fetches_per_day"], got["values"]["timezone"], got["values"]["phishing_domains"]), (12, "local", True))

    def test_every_key_the_status_takes_from_a_plan_is_a_key_of_the_real_plan_with_a_plain_value(self):
        defaults = crawlplan.defaults()
        for key in cs.PLAN_VALUES:
            with self.subTest(key=key):
                self.assertIn(key, defaults)
                self.assertIn(type(defaults[key]), (int, float, str, bool))
        for key, value in cs.DEFAULT_VALUES.items():
            with self.subTest(default=key):
                self.assertEqual(value, defaults[key])

    def test_a_floor_is_in_decimal_gigabytes_as_the_runners_guard_reads_it(self):
        self.assertEqual(cs.GIB, crawlguard.GB)

    def test_the_status_of_a_real_approval_is_idle_with_the_ceilings_of_the_plan_and_the_breaker_the_approval_made(self):
        self.approved()
        store = types.SimpleNamespace(list_books=lambda: [])
        got = cs.status(self.index, self.dir, read_plan=crawlplan.read_plan, store=store, now=self.NOW, statvfs=lambda path: types.SimpleNamespace(f_bavail=10 ** 9, f_frsize=4096))
        self.assertEqual((got["plan"]["status"], got["plan"]["defaults_used"], got["plan"]["values"]["fetches_per_day"]), ("approved", False, 12))
        self.assertEqual((got["state"]["state"], got["state"]["breaker"]["state"]), ("idle", "not_tripped"))

    def test_the_log_the_real_writer_makes_is_read_whole(self):
        log = crawllog.Log(self.index, "20261116T120000Z-abc123")
        for step, outcome, kw in (("run_start", "ok", {}), ("fetch", "ok", dict(candidate=7, host="example.org", n=2048, seconds=1.2)),
                                  ("capture", "ok", dict(candidate=7, book="b-1", host="example.org")), ("fail", "failed", dict(candidate=8, reason="HTTP 503", n=1)),
                                  ("refuse", "refused", dict(reason="a run is in progress")), ("breaker", "tripped", dict(reason="8 failures in a row")),
                                  ("run_end", "ok", dict(n=1, seconds=3))):
            log.write(step, outcome, now=self.NOW, **kw)
        found = cs.lines_of_day(self.index, datetime.date(2026, 11, 16), "UTC")
        self.assertEqual((len(found["lines"]), found["bad"]), (7, {}))
        self.assertEqual([r["candidate"] for r in found["lines"] if r["candidate"] is not None], [7, 7, 8])
        runs = cs.count_runs(found)
        self.assertEqual((runs["started"], runs["ended"], runs["refused"]), (1, 1, 1))

    def test_a_breaker_and_a_lock_the_real_guard_writes_are_read(self):
        self.approved()  # the approval makes the breaker file, not tripped
        self.assertEqual(cs.breaker_state(self.index)["state"], "not_tripped")
        crawlguard.trip(self.index, "consecutive_failures", "8 failures in a row", "r1", now=self.NOW)
        state = cs.breaker_state(self.index)
        self.assertEqual((state["state"], state["paused"], state["kind"], state["at"]), ("tripped", True, "consecutive_failures", "2026-11-16T12:00:00Z"))
        crawlguard.clear(self.index, True, is_tty=lambda: True, now=self.NOW)
        self.assertEqual(cs.breaker_state(self.index)["state"], "not_tripped")
        held = crawlguard.acquire_run_lock(self.index, now=self.NOW, pid=4242)
        self.assertIsNotNone(held)
        try:
            lock = cs.lock_state(self.index)
        finally:
            held.release()
        self.assertEqual((lock["held"], lock["holder"]), (True, {"pid": 4242, "since": "2026-11-16T12:00:00Z"}))

    def test_the_counters_the_real_runner_state_keeps_are_shown_against_the_plans_ceilings(self):
        conn = crawlqueue.connect(self.index)
        self.addCleanup(conn.close)
        plan = {"cards_per_day": 3, "timezone": "UTC"}
        for _ in range(2):
            self.assertTrue(crawlstate.reserve_card(conn, plan, self.NOW))
        day = crawlplan.day_of(self.NOW, "UTC")
        report = cs.counters_report(conn, day, day, {"cards_per_day": 3})
        self.assertEqual(report["card"], {"n": 2, "limit": 3, "at_or_over": False})

    def test_the_day_of_the_plan_is_the_day_the_status_and_the_report_read(self):
        zones = ("UTC", "local", "America/New_York", "Pacific/Auckland", "Asia/Kolkata", "Europe/London", "Pacific/Kiritimati", "America/St_Johns")
        times = [datetime.datetime(2026, 11, 16, h, m, tzinfo=datetime.timezone.utc) for h in (0, 5, 11, 12, 13, 23) for m in (0, 59)]
        times += [datetime.datetime(2026, 3, 8, 6, 59, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 3, 8, 7, 0, tzinfo=datetime.timezone.utc),
                  datetime.datetime(2026, 10, 25, 0, 59, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 10, 25, 1, 0, tzinfo=datetime.timezone.utc),
                  datetime.datetime(2026, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)]
        for zone in zones:
            for when in times:
                with self.subTest(zone=zone, when=when.isoformat()):
                    day = crawlplan.day_of(when, zone)
                    self.assertEqual(cs.today_in_zone(when, zone).isoformat(), day)
                    low, high = cs.day_bounds(datetime.date.fromisoformat(day), zone)
                    self.assertTrue(low <= when < high)


class BooksContractTest(StoreCase):
    """The report reads the events the runner's own writers (`crawlbooks`) make."""

    def test_the_events_the_real_writers_make_are_read_by_the_report(self):
        from kb import crawlreport
        digest = "0" * 32
        source = crawlqueue.SOURCES[0]

        def crawl_book(n):
            book = self.store.create_book(title=f"A page {n}", kind="preprint", auto_filed=True)
            crawlbooks.record_found(self.store, book, candidate=n, source=source, found_from=None, topic=None, run="r1", plan_digest=digest)
            return book

        held, rejected, unplaced, plain = (crawl_book(n) for n in range(1, 5))
        crawlbooks.record_held(self.store, held, ["javascript", "embedded_files"])
        crawlbooks.record_rejected(self.store, rejected, "below the threshold", 0.31, "judge")
        crawlbooks.record_unplaced(self.store, unplaced, "no shelf fits")
        got = crawlreport.book_facts(self.store, [held, rejected, unplaced, plain])
        self.assertEqual([e["kinds"] for e in got["held"]], [["javascript", "embedded_files"]])
        self.assertEqual([(e["reason"], e["score"]) for e in got["rejected"]], [("below the threshold", 0.31)])
        self.assertEqual(sorted(e["book"] for e in got["left_default"]), sorted([unplaced, plain]))
        self.assertEqual(crawlreport.unreviewed(self.store)["unreviewed"], 4)


if __name__ == "__main__":
    unittest.main()
