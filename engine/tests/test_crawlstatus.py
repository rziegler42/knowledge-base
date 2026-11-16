"""The reading side of `crawl-status` and `crawl-report` (`kb/crawlstatus.py`; `docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`).

Every test runs on a temporary index root and on hand-made fixture files in the spec's log format. No test opens a socket, reads the owner's
library, config, plan or keys, or writes outside its temporary folder. Hostile characters are made with `chr()` here, never typed."""

import datetime
import json
import os
import re
import shutil
import tempfile
import threading
import time
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


if __name__ == "__main__":
    unittest.main()
