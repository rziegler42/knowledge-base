"""URLhaus in recent mode (`kb/urlhaus.py`, Increment E of the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`).

The reply in `fixtures/web/urlhaus-recent-sample.json` is made by hand in the shape of the documented `urls/recent` answer (`query_status`, then a list of URLs with their status, host and date added); the names are
made up. **No test makes a real request and none reads the owner's key**: the key is a canary string in a temporary file, and the downloader is a fake or the shared client pointed at a fake server.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_urlhaus`."""
import datetime
import json
import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests.test_webclient import Net, reply, redirect

from kb import urlhaus, weblists, webclient
from kb.weblists import ListError

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "web")
with open(os.path.join(FIXTURES, "urlhaus-recent-sample.json"), "rb") as _f:
    SAMPLE = _f.read()
CANARY = "CANARY-key-5d1f0c2e-never-leak"
T0 = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)


def plan(**kw):
    base = {"urlhaus_recent": True}
    base.update(kw)
    return base


class FakeGet:
    """A stand-in for `webclient.get`: answers from `answers` in order, and records each call with its policy."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, *, policy, headers=None, max_bytes, timeout=10, total_timeout=30):
        self.calls.append({"url": url, "policy": policy, "headers": headers, "max_bytes": max_bytes})
        answer = self.answers.pop(0) if self.answers else (200, {}, SAMPLE)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def ok(body=SAMPLE, remaining="4999"):
    headers = {"content-type": "application/json"}
    if remaining is not None:
        headers["x-ratelimit-remaining"] = remaining
    return 200, headers, body


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.key_path = os.path.join(self.dir, "urlhaus.key")
        self.state = os.path.join(self.dir, "lists")
        self.write_key()

    def write_key(self, text=CANARY + "\n", mode=0o600):
        if os.path.lexists(self.key_path):
            os.chmod(self.key_path, 0o600)
        with open(self.key_path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(self.key_path, mode)

    def source(self):
        return urlhaus.Source(self.state, self.key_path)

    def matcher(self):
        return weblists.Matcher(os.path.join(self.dir, "black.txt"), os.path.join(self.dir, "allow.txt"), self.state, [])


class KeyFile(Case):
    def test_a_good_key_file_is_read_without_its_line_end(self):
        self.assertEqual(urlhaus.read_key(self.key_path), CANARY)
        self.write_key(CANARY)
        self.assertEqual(urlhaus.read_key(self.key_path), CANARY)
        self.write_key(CANARY + "\r\n")
        self.assertEqual(urlhaus.read_key(self.key_path), CANARY)

    def test_a_key_file_that_is_not_exactly_ours_alone_is_refused(self):
        for mode in (0o644, 0o640, 0o660, 0o700, 0o400, 0o666, 0o604):
            with self.subTest(oct(mode)):
                self.write_key(mode=mode)
                with self.assertRaises(urlhaus.UrlhausError):
                    urlhaus.read_key(self.key_path)

    def test_a_key_file_of_another_owner_is_refused(self):
        real = os.fstat

        def fstat(fd):
            info = real(fd)
            return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, os.getuid() + 1, info.st_gid, info.st_size, info.st_atime, info.st_mtime, info.st_ctime))

        with mock.patch.object(urlhaus.os, "fstat", fstat):
            with self.assertRaises(urlhaus.UrlhausError):
                urlhaus.read_key(self.key_path)

    def test_a_key_file_that_is_a_link_a_folder_a_pipe_or_missing_is_refused(self):
        target = os.path.join(self.dir, "real.key")
        os.rename(self.key_path, target)
        os.symlink(target, self.key_path)
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.read_key(self.key_path)
        os.remove(self.key_path)
        os.mkdir(self.key_path)
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.read_key(self.key_path)
        os.rmdir(self.key_path)
        os.mkfifo(self.key_path, 0o600)
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.read_key(self.key_path)
        os.remove(self.key_path)
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.read_key(self.key_path)
        for odd in (None, 5, b"x\x00y", "a\x00b"):
            with self.assertRaises(urlhaus.UrlhausError):
                urlhaus.read_key(odd)

    def test_a_key_file_with_no_key_more_than_one_line_or_odd_text_is_refused_and_the_message_holds_no_key(self):
        for text in ("", "\n", "   \n", CANARY + "\nsecond\n", CANARY + "\n\n", "\n" + CANARY, CANARY + " extra\n", "has space " + CANARY, "café-" + CANARY, CANARY + "\x00", CANARY + "\t",
                     "k" * 201):
            with self.subTest(repr(text)[:30]):
                self.write_key(text)
                with self.assertRaises(urlhaus.UrlhausError) as caught:
                    urlhaus.read_key(self.key_path)
                self.assertNotIn(CANARY, str(caught.exception))
                self.assertNotIn(CANARY, repr(caught.exception))
                self.assertNotIn(CANARY, repr(caught.exception.args))

    def test_the_longest_allowed_key_is_taken(self):
        self.write_key("k" * 200)
        self.assertEqual(urlhaus.read_key(self.key_path), "k" * 200)


class Parsing(Case):
    def test_the_documented_reply_gives_canonical_urls_with_the_dates_they_were_added(self):
        entries, ignored = urlhaus.parse_recent(SAMPLE, T0)
        self.assertEqual(entries, {"http://203.0.113.9/bins/payload.sh": "2026-11-16", "https://github.com/example-owner/example-repo/raw/main/payload.bin": "2026-11-16",
                                   "http://bad-files.example/dl/a.exe": "2026-11-13"})
        self.assertEqual(ignored, 1)

    def test_no_results_is_an_empty_answer_and_any_other_status_is_an_error(self):
        self.assertEqual(urlhaus.parse_recent(b'{"query_status": "no_results"}', T0), ({}, 0))
        for status in ("invalid_auth", "http_post_expected", "unknown", None, 5):
            with self.subTest(repr(status)):
                with self.assertRaises(urlhaus.UrlhausError):
                    urlhaus.parse_recent(json.dumps({"query_status": status, "urls": []}).encode(), T0)

    def test_a_reply_that_is_not_the_documented_shape_is_an_error_and_nothing_else(self):
        for body in (b"", b"not json", b"[]", b"null", b'"ok"', b'{"query_status": "ok"}', b'{"query_status": "ok", "urls": "x"}', b'{"query_status": "ok", "urls": {"a": 1}}', b"\xff\xfe",
                     b"[" * 9000 + b"]" * 9000, b'{"query_status": "ok", "urls": [' + b"[" * 9000 + b"]" * 9000 + b"]}", b"\x00", b'{"query_status": "ok", "urls": [1, "x", null, [], {"url": 5}, {"url": null}, {}]}'):
            with self.subTest(body[:20]):
                try:
                    entries, ignored = urlhaus.parse_recent(body, T0)
                except urlhaus.UrlhausError:
                    continue
                self.assertEqual(entries, {})        # only the last shape is a valid reply: with nothing usable in it

    def test_dates_that_are_missing_odd_or_in_the_future_are_taken_as_today(self):
        body = json.dumps({"query_status": "ok", "urls": [
            {"url": "http://a.example/1", "date_added": "2026-11-10 00:00:00 UTC"}, {"url": "http://a.example/2"}, {"url": "http://a.example/3", "date_added": "yesterday"},
            {"url": "http://a.example/4", "date_added": "2030-01-01 00:00:00 UTC"}, {"url": "http://a.example/5", "date_added": 5}]}).encode()
        entries, _ = urlhaus.parse_recent(body, T0)
        self.assertEqual(entries, {"http://a.example/1": "2026-11-10", "http://a.example/2": "2026-11-16", "http://a.example/3": "2026-11-16", "http://a.example/4": "2026-11-16",
                                   "http://a.example/5": "2026-11-16"})

    def test_a_date_that_is_not_a_real_day_is_taken_as_today(self):
        body = json.dumps({"query_status": "ok", "urls": [{"url": "http://a.example/1", "date_added": "2026-02-30 00:00:00 UTC"}, {"url": "http://a.example/2", "date_added": "2026-13-01 00:00:00 UTC"},
                                                         {"url": "http://a.example/3", "date_added": "2026-1-1 00:00:00 UTC"}, {"url": "http://a.example/4", "date_added": "2026-11-15"}]}).encode()
        entries, _ = urlhaus.parse_recent(body, T0)
        self.assertEqual(entries, {"http://a.example/1": "2026-11-16", "http://a.example/2": "2026-11-16", "http://a.example/3": "2026-11-16", "http://a.example/4": "2026-11-15"})

    def test_a_huge_reply_is_cut_by_the_entry_limit(self):
        body = json.dumps({"query_status": "ok", "urls": [{"url": f"http://a.example/{i}"} for i in range(30)]}).encode()
        with mock.patch.object(urlhaus, "MAX_REPLY_URLS", 10):
            with self.assertRaises(urlhaus.UrlhausError):
                urlhaus.parse_recent(body, T0)


class Request(Case):
    def test_the_request_carries_the_key_only_as_a_credential_header_for_one_host_and_follows_nothing(self):
        fake = FakeGet(ok())
        report = urlhaus.recent(fake, CANARY, T0, plan())
        self.assertEqual(report["status"], "ok")
        call = fake.calls[0]
        self.assertEqual(call["url"], "https://urlhaus-api.abuse.ch/v1/urls/recent/")
        policy = call["policy"]
        self.assertEqual(policy.credential_headers, {"Auth-Key": CANARY})
        self.assertEqual(policy.credential_host, "urlhaus-api.abuse.ch")
        self.assertFalse(policy.follow_redirects)
        self.assertFalse(policy.allow_private)
        self.assertEqual(policy.types, ("application/json",))
        self.assertIsNone(policy.headers)
        self.assertNotIn(CANARY, call["url"])
        self.assertNotIn(CANARY, repr(call["headers"]))
        self.assertIn("knowledge-base", policy.user_agent)
        self.assertEqual(call["max_bytes"], urlhaus.MAX_REPLY_BYTES)

    def test_a_blocking_hook_is_given_to_the_policy(self):
        hook = lambda url: None
        fake = FakeGet(ok())
        urlhaus.recent(fake, CANARY, T0, plan(), check=hook)
        self.assertIs(fake.calls[0]["policy"].check, hook)

    def test_the_rate_limit_header_at_zero_turns_the_source_off_for_the_day_but_the_reply_is_kept(self):
        report = urlhaus.recent(FakeGet(ok(remaining="0")), CANARY, T0, plan())
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["off_for_the_day"])
        self.assertEqual(len(report["entries"]), 3)
        self.assertFalse(urlhaus.recent(FakeGet(ok(remaining="7")), CANARY, T0, plan()).get("off_for_the_day"))
        for odd in ("abc", "", "-1", "1.5", None):
            self.assertFalse(urlhaus.recent(FakeGet(ok(remaining=odd)), CANARY, T0, plan()).get("off_for_the_day"), odd)

    def test_any_status_but_200_turns_it_off_for_the_day(self):
        for status in (301, 302, 307, 400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status):
                report = urlhaus.recent(FakeGet((status, {"x-ratelimit-remaining": "3"}, b"")), CANARY, T0, plan())
                self.assertEqual(report["status"], "refused")
                self.assertTrue(report["off_for_the_day"])
                self.assertIn(str(status), report["reason"])

    def test_a_refusal_by_the_client_turns_it_off_for_the_day_and_a_network_failure_does_not(self):
        report = urlhaus.recent(FakeGet(webclient.Refused("the server redirected, and this request follows no redirect")), CANARY, T0, plan())
        self.assertEqual((report["status"], report["off_for_the_day"]), ("refused", True))
        report = urlhaus.recent(FakeGet(webclient.FetchError("timed out")), CANARY, T0, plan())
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report.get("off_for_the_day"))

    def test_a_200_reply_that_is_not_the_documented_answer_is_a_refusal_for_the_day(self):
        for body in (b"<html>down</html>", b'{"query_status": "invalid_auth"}', b"", b"[]", b'{"query_status": "ok"}', b'{"query_status": "ok", "urls": 5}'):
            with self.subTest(body[:20]):
                report = urlhaus.recent(FakeGet(ok(body)), CANARY, T0, plan())
                self.assertEqual(report["status"], "refused")
                self.assertTrue(report["off_for_the_day"])

    def test_the_rate_limit_header_is_honoured_on_every_reply_even_an_unreadable_one(self):
        report = urlhaus.recent(FakeGet(ok(b"<html>x</html>", remaining="0")), CANARY, T0, plan())
        self.assertTrue(report["off_for_the_day"])
        report = urlhaus.recent(FakeGet((503, {"x-ratelimit-remaining": "0"}, b"")), CANARY, T0, plan())
        self.assertTrue(report["off_for_the_day"])

    def test_a_query_status_that_echoes_the_key_leaves_no_part_of_it_in_the_reason(self):
        for status in (CANARY, "x" * 30 + CANARY, CANARY.upper(), "y" * 50 + CANARY, [CANARY] * 5, {"a": CANARY}):
            with self.subTest(str(status)[:20]):
                body = json.dumps({"query_status": status, "urls": []}).encode()
                report = urlhaus.recent(FakeGet(ok(body)), CANARY, T0, plan())
                self.assertEqual(report["status"], "refused")
                self.assertNotIn(CANARY[:8].lower(), report["reason"].lower())
                self.assertNotIn("canary", report["reason"].lower())

    def test_a_query_status_is_never_copied_into_the_reason(self):
        body = json.dumps({"query_status": "<b>evil text from the server</b>", "urls": []}).encode()
        report = urlhaus.recent(FakeGet(ok(body)), CANARY, T0, plan())
        self.assertEqual(report["status"], "refused")
        self.assertNotIn("evil", report["reason"])

    def test_an_entry_that_holds_the_key_is_not_kept(self):
        body = json.dumps({"query_status": "ok", "urls": [{"url": f"http://a.example/{CANARY}"}, {"url": f"http://{CANARY.upper()}.example/x"}, {"url": "http://fine.example/x"}]}).encode()
        report = urlhaus.recent(FakeGet(ok(body)), CANARY, T0, plan())
        self.assertEqual(list(report["entries"]), ["http://fine.example/x"])
        self.assertEqual(report["ignored"], 2)

    def test_the_lists_plan_is_checked_like_the_lists_module_checks_it(self):
        with self.assertRaises(weblists.ListError):
            urlhaus.recent(FakeGet(), CANARY, T0, plan(unknown=1))
        with self.assertRaises(weblists.ListError):
            urlhaus.recent(FakeGet(), CANARY, T0, plan(urlhaus_keep_days=0))
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.recent(FakeGet(), CANARY, datetime.datetime(2026, 11, 16), plan())

    def test_a_key_that_is_not_a_plain_string_is_refused_before_a_request(self):
        fake = FakeGet()
        for bad in (None, "", 5, "two words", "a\r\nb"):
            with self.assertRaises(urlhaus.UrlhausError):
                urlhaus.recent(fake, bad, T0, plan())
        self.assertEqual(fake.calls, [])


class Keeping(Case):
    def test_the_first_update_reads_the_key_asks_once_keeps_the_urls_and_feeds_the_matcher(self):
        m = self.matcher()
        fake = FakeGet(ok())
        report = self.source().update(fake, T0, plan(), matcher=m)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["entries"], 3)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(m.blocked("http://203.0.113.9/bins/payload.sh").reason, "list:urlhaus_recent")
        self.assertEqual(m.blocked("http://203.0.113.9/anything").reason, "list:urlhaus_recent")      # a bare address blocks the host
        self.assertEqual(m.blocked("https://github.com/example-owner/example-repo/raw/main/payload.bin").reason, "list:urlhaus_recent")
        self.assertIsNone(m.blocked("https://github.com/other"))                                       # a whole site is not blocked by one of its URLs
        self.assertIsNone(m.blocked("github.com"))
        self.assertEqual(m.blocked("http://bad-files.example/dl/a.exe").reason, "list:urlhaus_recent")

    def test_it_is_asked_about_once_in_the_hour_and_not_off_when_the_plan_says_so(self):
        source = self.source()
        fake = FakeGet(ok(), ok(), ok())
        source.update(fake, T0, plan())
        self.assertEqual(source.update(fake, T0 + datetime.timedelta(minutes=59), plan())["status"], "not-due")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=1), plan())["status"], "ok")
        self.assertEqual(len(fake.calls), 2)
        off = FakeGet()
        os.remove(self.key_path)                                     # the key is not even looked for when the source is off
        self.assertEqual(self.source().update(off, T0, plan(urlhaus_recent=False))["status"], "off")
        self.assertEqual(self.source().update(off, T0, {})["status"], "off")
        self.assertEqual(off.calls, [])

    def test_a_refusal_keeps_the_key_from_being_sent_again_that_day_and_the_next_day_is_free(self):
        source = self.source()
        fake = FakeGet((302, {}, b""), ok())
        self.assertEqual(source.update(fake, T0, plan())["status"], "refused")
        for later in (T0 + datetime.timedelta(hours=2), T0 + datetime.timedelta(hours=11, minutes=59)):
            self.assertEqual(source.update(fake, later, plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)
        again = self.source()                                          # a new process the same day
        self.assertEqual(again.update(fake, T0 + datetime.timedelta(hours=5), plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(again.update(fake, T0 + datetime.timedelta(hours=12), plan())["status"], "ok")     # the next day (UTC)
        self.assertEqual(len(fake.calls), 2)

    def test_a_zero_remaining_count_keeps_what_came_and_stops_for_the_day(self):
        m = self.matcher()
        source = self.source()
        fake = FakeGet(ok(remaining="0"))
        report = source.update(fake, T0, plan(), matcher=m)
        self.assertEqual(report["status"], "ok")
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))
        self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=3), plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)

    def test_a_last_request_time_in_the_future_does_not_stop_the_asking(self):
        source = self.source()
        fake = FakeGet(ok(), ok())
        source.update(fake, T0, plan())
        self.assertEqual(source.update(fake, T0 - datetime.timedelta(days=2), plan())["status"], "ok")     # the clock went back

    def test_only_the_newest_entries_are_kept_when_there_are_too_many(self):
        source = self.source()
        with mock.patch.object(urlhaus, "MAX_KEPT", 2):
            report = source.update(FakeGet(ok()), T0, plan())
        self.assertEqual(report["entries"], 2)
        m = self.matcher()
        source.load_into(m)
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))          # the two of the 16th stay,
        self.assertIsNone(m.blocked("http://bad-files.example/dl/a.exe"))             # the one of the 13th goes

    def test_each_save_goes_through_a_temporary_name_of_its_own(self):
        names = []
        real = os.replace

        def replace(src, dst):
            names.append(os.path.basename(src))
            return real(src, dst)

        with mock.patch.object(urlhaus.os, "replace", replace):
            source = self.source()
            source.update(FakeGet(ok()), T0, plan())
            source.update(FakeGet(ok()), T0 + datetime.timedelta(hours=2), plan())
        self.assertEqual(len(names), 4)           # a save before each request and one after
        self.assertEqual(len(set(names)), 4)

    def test_a_state_file_with_bad_entries_keeps_only_the_good_ones(self):
        os.makedirs(self.state, mode=0o700)
        state = {"version": 1, "entries": {"http://good.example/a": "2026-11-16", "HTTP://Not.Canonical/a": "2026-11-16", "http://bad.example/date": "2026-13-45", "http://bad.example/shape": "16 Nov",
                                           "not a url": "2026-11-16", "http://bad.example/type": 5}, "last": None, "off_day": None}
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.chmod(path, 0o600)
        source = self.source()
        m = self.matcher()
        self.assertEqual(source.load_into(m), 1)
        self.assertEqual(source.update(FakeGet(ok()), T0, plan())["status"], "ok")

    def test_a_key_file_of_a_huge_size_is_refused_without_reading_it_all(self):
        with open(self.key_path, "wb") as f:
            f.write(b"k" * 100000)
        os.chmod(self.key_path, 0o600)
        sizes = []
        real = os.read

        def spy(fd, n):
            sizes.append(n)
            return real(fd, n)

        with mock.patch.object(urlhaus.os, "read", spy):
            with self.assertRaises(urlhaus.UrlhausError):
                urlhaus.read_key(self.key_path)
        self.assertTrue(sizes and max(sizes) <= urlhaus.MAX_KEY_BYTES + 4)

    def test_a_failure_is_tried_again_only_after_the_hour(self):
        for error in (webclient.FetchError("timed out"), RuntimeError("odd"), webclient.FetchError("the response is larger than 8388608 bytes")):
            with self.subTest(repr(error)[:30]):
                source = urlhaus.Source(os.path.join(self.dir, f"s{abs(hash(repr(error)))}"), self.key_path)
                fake = FakeGet(error, ok())
                self.assertEqual(source.update(fake, T0, plan())["status"], "failed")
                self.assertEqual(source.update(fake, T0 + datetime.timedelta(minutes=5), plan())["status"], "not-due")
                self.assertEqual(len(fake.calls), 1)
                self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=1), plan())["status"], "ok")

    def test_a_broken_200_reply_keeps_the_key_from_being_sent_again_that_day(self):
        source = self.source()
        fake = FakeGet(ok(b"<html>an error page</html>"), ok())
        self.assertEqual(source.update(fake, T0, plan())["status"], "refused")
        for hours in (1, 5, 11):
            self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=hours), plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)

    def test_the_kept_urls_serve_the_matcher_whether_or_not_a_request_is_made_and_obey_the_plan_and_the_days(self):
        m = self.matcher()
        source = self.source()
        source.update(FakeGet(ok()), T0, plan(urlhaus_keep_days=5))
        fresh = self.source()
        m2 = self.matcher()
        self.assertEqual(fresh.update(FakeGet(), T0 + datetime.timedelta(minutes=5), plan(urlhaus_keep_days=5), matcher=m2)["status"], "not-due")
        self.assertIsNotNone(m2.blocked("http://203.0.113.9/bins/payload.sh"))                 # not-due still gives the matcher what is kept
        m3 = self.matcher()
        self.assertEqual(self.source().update(FakeGet(), T0 + datetime.timedelta(days=2, hours=1), plan(urlhaus_keep_days=5, urlhaus_recent=False), matcher=m3)["status"], "off")
        self.assertIsNone(m3.blocked("http://203.0.113.9/bins/payload.sh"))                    # off: nothing is fed
        m4 = self.matcher()
        refused = FakeGet((429, {}, b""))
        self.assertEqual(self.source().update(refused, T0 + datetime.timedelta(days=2, hours=1), plan(urlhaus_keep_days=5), matcher=m4)["status"], "refused")
        self.assertIsNone(m4.blocked("http://bad-files.example/dl/a.exe"))                      # older than 5 days: not fed even though the request was refused
        self.assertIsNotNone(m4.blocked("http://203.0.113.9/bins/payload.sh"))
        m5 = self.matcher()
        self.assertEqual(self.source().load_into(m5, T0 + datetime.timedelta(days=1), plan(urlhaus_keep_days=1)), 0)
        self.assertEqual(self.source().load_into(m5, T0, plan()), 2)        # the entry of the 13th was dropped from the state by the refused step at keep_days=5
        m6 = self.matcher()
        self.assertEqual(self.source().load_into(m6, T0, plan(urlhaus_recent=False)), 0)       # the plan's switch is off: nothing is given
        self.assertIsNone(m6.blocked("http://203.0.113.9/bins/payload.sh"))

    def test_a_failed_write_of_the_state_leaves_no_temporary_file(self):
        source = self.source()
        real = os.write

        def write(fd, data):
            raise OSError(28, "No space left on device")

        fake = FakeGet(ok())
        with mock.patch.object(urlhaus.os, "write", write):
            report = source.update(fake, T0, plan())
        self.assertEqual((report["status"], fake.calls), ("failed", []))          # the state is written before the request, and without it no request is made
        self.assertEqual([n for n in os.listdir(self.state) if n.startswith(".")], [])

    def test_urls_are_kept_for_the_days_the_plan_says_and_older_ones_are_dropped(self):
        source = self.source()
        m = self.matcher()
        source.update(FakeGet(ok()), T0, plan(urlhaus_keep_days=5), matcher=m)
        self.assertIsNotNone(m.blocked("http://bad-files.example/dl/a.exe"))                  # added 2026-11-13, 3 days old
        later = T0 + datetime.timedelta(days=2, hours=1)                                       # 5 days old at 2026-11-18
        source.update(FakeGet(ok(b'{"query_status": "no_results"}')), later, plan(urlhaus_keep_days=5), matcher=m)
        self.assertIsNone(m.blocked("http://bad-files.example/dl/a.exe"))                      # older than 5 days at 2026-11-19
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))                  # added on the 16th
        much_later = T0 + datetime.timedelta(days=6)
        source.update(FakeGet(ok(b'{"query_status": "no_results"}')), much_later, plan(urlhaus_keep_days=5), matcher=m)
        self.assertIsNone(m.blocked("http://203.0.113.9/bins/payload.sh"))

    def test_the_kept_urls_are_loaded_by_a_new_process_and_the_state_holds_no_key(self):
        self.source().update(FakeGet(ok()), T0, plan())
        m = self.matcher()
        again = self.source()
        self.assertEqual(again.load_into(m), 3)
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))
        path = os.path.join(self.state, "urlhaus.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, encoding="utf-8") as f:
            self.assertNotIn(CANARY, f.read())
        self.assertEqual([n for n in os.listdir(self.state) if n.startswith(".")], [])

    def test_a_state_file_that_is_a_link_a_pipe_huge_or_odd_is_ignored_and_reported(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        real = path + ".real"
        os.rename(path, real)
        os.symlink(real, path)
        source = self.source()
        self.assertTrue(source.problems)
        self.assertEqual(source.load_into(self.matcher()), 0)
        os.remove(path)
        os.mkfifo(path, 0o600)
        self.assertTrue(self.source().problems)
        os.remove(path)
        for content in ("[]", "{}", '{"entries": 5}', '{"entries": {"http://a.example/": 5}}', "not json", '{"off_day": 5}', "[" * 9000 + "]" * 9000, '{"entries": {"x": "2026-11-16"}, "last": "never"}'):
            with self.subTest(content[:20]):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.chmod(path, 0o600)
                source = self.source()
                readable = content == '{"entries": {"http://a.example/": 5}}'              # a dictionary of entries with some bad ones is read, and the bad ones dropped
                self.assertEqual(source.update(FakeGet(ok()), T0 + datetime.timedelta(days=3), plan())["status"], "ok" if readable else "off-for-the-day")     # an unreadable state is a day without the key

    def test_a_key_file_that_is_wrong_fails_the_update_without_a_request_or_the_key_in_the_report(self):
        self.write_key(CANARY + "\nsecond\n")
        fake = FakeGet(ok())
        report = self.source().update(fake, T0, plan())
        self.assertEqual(report["status"], "failed")
        self.assertIn("key", report["reason"])
        self.assertNotIn(CANARY, json.dumps(report))
        self.assertEqual(fake.calls, [])
        os.chmod(self.key_path, 0o644)
        self.write_key(mode=0o644)
        self.assertEqual(self.source().update(fake, T0, plan())["status"], "failed")
        self.assertEqual(fake.calls, [])

    def test_the_key_is_in_no_report_no_state_no_exception_no_environment_and_no_address_even_when_the_downloader_blows_up(self):
        reports = []
        errors = [RuntimeError(f"boom {CANARY} boom"), RuntimeError(CANARY.upper()), webclient.FetchError(f"server said {CANARY.lower()}"), webclient.Refused(f"refused {CANARY}"),
                  OSError(f"{CANARY} at the door"), ValueError(CANARY)]
        for error in errors:
            reports.append(self.source().update(FakeGet(error), T0, plan()))
        reports.append(self.source().update(FakeGet((401, {"x-echo": CANARY}, CANARY.encode())), T0 + datetime.timedelta(days=1), plan()))
        reports.append(self.source().update(FakeGet(ok(CANARY.encode())), T0 + datetime.timedelta(days=2), plan()))
        for report in reports:
            self.assertNotIn(CANARY.lower(), json.dumps(report).lower())
            self.assertNotIn(CANARY.lower(), repr(report).lower())
        for name in os.listdir(self.state):
            with open(os.path.join(self.state, name), "rb") as f:
                self.assertNotIn(CANARY.lower().encode(), f.read().lower())
        for value in list(os.environ.values()):
            self.assertNotIn(CANARY, value)

    def test_the_module_never_prints_logs_or_puts_the_key_in_the_environment_or_a_command(self):
        with open(os.path.join(ENGINE_DIR, "kb", "urlhaus.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("print(", "logging", "os.environ", "os.putenv", "subprocess", "os.system", "argv", "import socket", "urllib.request", "http.client"):
            self.assertNotIn(word, source, word)


class FailClosed(Case):
    """Faults found by the security review of Increment E: the rules `no key after a refusal` and `once an hour` must hold when the state is lost, damaged or unwritable."""

    def refuse_once(self):
        source = self.source()
        self.assertEqual(source.update(FakeGet((403, {}, b"")), T0, plan())["status"], "refused")
        return os.path.join(self.state, "urlhaus.json")

    def test_a_state_that_cannot_be_read_means_no_request_that_day_and_a_fresh_start_the_next(self):
        path = self.refuse_once()
        for damage in ("garbage", "list", "empty-object", "fifo", "directory", "link", "mode", "huge"):
            with self.subTest(damage):
                if os.path.lexists(path):
                    if os.path.isdir(path) and not os.path.islink(path):
                        os.rmdir(path)
                    else:
                        os.chmod(path, 0o600) if not os.path.islink(path) else None
                        os.remove(path)
                if damage == "garbage":
                    open(path, "w").write("not json")
                elif damage == "list":
                    open(path, "w").write("[]")
                elif damage == "empty-object":
                    open(path, "w").write("{}")
                elif damage == "fifo":
                    os.mkfifo(path, 0o600)
                elif damage == "directory":
                    os.mkdir(path)
                elif damage == "link":
                    target = path + ".elsewhere"
                    open(target, "w").write("{}")
                    os.symlink(target, path)
                elif damage == "mode":
                    open(path, "w").write('{"entries": {}}')
                    os.chmod(path, 0o644)
                else:
                    with mock.patch.object(urlhaus, "MAX_STATE_BYTES", 10):
                        open(path, "w").write('{"entries": {}, "last": null, "off_day": null}')
                        fake = FakeGet(ok())
                        report = self.source().update(fake, T0 + datetime.timedelta(hours=3), plan())
                        self.assertEqual((report["status"], fake.calls), ("off-for-the-day", []))
                        continue
                fake = FakeGet(ok())
                report = self.source().update(fake, T0 + datetime.timedelta(hours=3), plan())
                self.assertEqual((report["status"], fake.calls), ("off-for-the-day", []))
        for leftover in (path, path + ".elsewhere"):
            if os.path.lexists(leftover):
                if os.path.isdir(leftover) and not os.path.islink(leftover):
                    os.rmdir(leftover)
                else:
                    os.remove(leftover)
        fake = FakeGet(ok())
        self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(hours=3), plan())["status"], "ok")        # a state that was never there is a first start

    def test_an_unreadable_state_is_asked_again_the_next_day(self):
        path = self.refuse_once()
        open(path, "w").write("not json")
        source = self.source()
        self.assertEqual(source.update(FakeGet(), T0 + datetime.timedelta(hours=3), plan())["status"], "off-for-the-day")
        fake = FakeGet(ok())
        self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(days=1), plan())["status"], "ok")
        self.assertEqual(len(fake.calls), 1)

    def test_a_folder_that_cannot_hold_the_state_means_no_request(self):
        elsewhere = os.path.join(self.dir, "elsewhere")
        os.mkdir(elsewhere)
        os.symlink(elsewhere, self.state)
        fake = FakeGet(ok())
        report = self.source().update(fake, T0, plan())
        self.assertEqual((report["status"], fake.calls), ("failed", []))
        self.assertEqual(os.listdir(elsewhere), [])

    def test_the_hour_is_written_down_before_the_request_so_a_stop_during_it_is_remembered(self):
        fake = FakeGet(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.source().update(fake, T0, plan())
        later = FakeGet(ok())
        self.assertEqual(self.source().update(later, T0 + datetime.timedelta(minutes=10), plan())["status"], "off-for-the-day")     # an outcome that is not known counts as a refusal
        self.assertEqual(later.calls, [])
        self.assertEqual(self.source().update(later, T0 + datetime.timedelta(days=1), plan())["status"], "ok")

    def test_a_state_that_cannot_be_written_before_the_request_means_no_request(self):
        fake = FakeGet(ok())
        with mock.patch.object(urlhaus.os, "write", side_effect=OSError(28, "No space left on device")):
            report = self.source().update(fake, T0, plan())
        self.assertEqual((report["status"], fake.calls), ("failed", []))

    def test_a_state_that_cannot_be_written_after_a_refusal_still_stops_the_day_in_this_process(self):
        source = self.source()
        real = urlhaus.Source._save
        calls = []

        def save(self_):
            calls.append(1)
            if len(calls) > 1:
                raise OSError(28, "No space left on device")
            return real(self_)

        fake = FakeGet((403, {}, b""), ok())
        with mock.patch.object(urlhaus.Source, "_save", save):
            self.assertEqual(source.update(fake, T0, plan())["status"], "refused")
            self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=2), plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)

    def test_a_time_with_another_zone_is_the_same_instant_for_the_hour_rule(self):
        for offset in (-8, 8, 0, 5.5):
            with self.subTest(offset):
                zone = datetime.timezone(datetime.timedelta(hours=offset))
                state = os.path.join(self.dir, f"z{offset}")
                local = T0.astimezone(zone)
                urlhaus.Source(state, self.key_path).update(FakeGet(ok()), local, plan())
                fake = FakeGet(ok())
                self.assertEqual(urlhaus.Source(state, self.key_path).update(fake, local + datetime.timedelta(minutes=30), plan())["status"], "not-due")
                self.assertEqual(fake.calls, [])
                self.assertEqual(urlhaus.Source(state, self.key_path).update(fake, local + datetime.timedelta(minutes=61), plan())["status"], "ok")

    def test_a_last_request_a_little_in_the_future_holds_the_hour_and_a_far_one_does_not(self):
        source = self.source()
        source.update(FakeGet(ok()), T0, plan())
        fake = FakeGet(ok())
        self.assertEqual(source.update(fake, T0 - datetime.timedelta(minutes=30), plan())["status"], "not-due")
        self.assertEqual(source.update(fake, T0 - datetime.timedelta(days=3), plan())["status"], "ok")
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state["last"] = "2999-01-01T00:00:00Z"
        state["off_day"] = None
        os.chmod(path, 0o600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.chmod(path, 0o600)
        self.assertEqual(self.source().update(FakeGet(ok()), T0 + datetime.timedelta(hours=5), plan())["status"], "ok")

    def test_entries_dated_in_the_far_future_are_not_kept(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state["entries"]["http://future.example/x"] = "2999-01-01"
        state["entries"]["http://tomorrow.example/x"] = "2026-11-17"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.chmod(path, 0o600)
        m = self.matcher()
        self.source().update(FakeGet(), T0 + datetime.timedelta(minutes=5), plan(), matcher=m)
        self.assertIsNone(m.blocked("http://future.example/x"))
        self.assertIsNotNone(m.blocked("http://tomorrow.example/x"))              # a day of clock difference is allowed

    def test_a_url_over_the_length_limit_is_not_kept_and_the_limits_are_as_agreed(self):
        long_url = "http://long.example/" + "a" * 2000
        body = json.dumps({"query_status": "ok", "urls": [{"url": long_url}, {"url": "http://short.example/x"}]}).encode()
        report = urlhaus.recent(FakeGet(ok(body)), CANARY, T0, plan())
        self.assertEqual(list(report["entries"]), ["http://short.example/x"])
        self.assertEqual(report["ignored"], 1)
        self.assertEqual((urlhaus.MAX_URL_LENGTH, urlhaus.MAX_KEPT), (1024, 200_000))
        self.assertLess(urlhaus.MAX_KEPT * (urlhaus.MAX_URL_LENGTH + 40), urlhaus.MAX_STATE_BYTES)

    def test_an_entry_that_holds_the_key_in_any_written_form_is_not_kept(self):
        key = "KEY{abc|def}0123456789"
        urls = [f"http://a.example/{key}", "http://b.example/KEY%7Babc%7Cdef%7D0123456789", "http://c.example/key%7babc%7cdef%7d0123456789", f"http://{key.upper()}.example/",
                "http://d.example/KEY%257Babc%257Cdef%257D0123456789", "http://e.example/KEY%25257Babc%25257Cdef%25257D0123456789", "http://ok.example/fine"]
        body = json.dumps({"query_status": "ok", "urls": [{"url": u} for u in urls]}).encode()
        report = urlhaus.recent(FakeGet(ok(body)), key, T0, plan())
        self.assertEqual(list(report["entries"]), ["http://ok.example/fine"])

    def test_a_key_that_is_too_short_is_refused(self):
        self.write_key("short")
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.read_key(self.key_path)
        with self.assertRaises(urlhaus.UrlhausError):
            urlhaus.recent(FakeGet(), "x" * 15, T0, plan())
        self.write_key("k" * 16)
        self.assertEqual(urlhaus.read_key(self.key_path), "k" * 16)

    def test_a_state_file_that_is_not_ours_is_not_trusted(self):
        self.source().update(FakeGet(ok()), T0, plan())       # a state with no off day: only the owner check can stop the next request
        path = os.path.join(self.state, "urlhaus.json")
        real = os.lstat

        def lstat(p, *a, **k):
            info = real(p, *a, **k)
            if p == path:
                return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, os.getuid() + 1, info.st_gid, info.st_size, info.st_atime, info.st_mtime, info.st_ctime))
            return info

        fake = FakeGet(ok())
        with mock.patch.object(urlhaus.os, "lstat", lstat):
            self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(hours=3), plan())["status"], "off-for-the-day")
        self.assertEqual(fake.calls, [])

    def test_a_state_entry_over_the_length_limit_is_not_loaded(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        state["entries"]["http://long.example/" + "a" * 2000] = "2026-11-16"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.chmod(path, 0o600)
        self.assertEqual(self.source().load_into(self.matcher()), 3)

    def test_a_last_request_exactly_a_day_ahead_still_holds_the_hour(self):
        source = self.source()
        source.update(FakeGet(ok()), T0, plan())
        fake = FakeGet(ok())
        self.assertEqual(source.update(fake, T0 - datetime.timedelta(days=1), plan())["status"], "not-due")
        self.assertEqual(fake.calls, [])

    def test_a_failed_save_after_a_good_reply_stops_the_day_in_this_process(self):
        source = self.source()
        real = urlhaus.Source._save
        calls = []

        def save(self_):
            calls.append(1)
            if len(calls) > 1:
                raise OSError(28, "No space left on device")
            return real(self_)

        fake = FakeGet(ok(), ok())
        with mock.patch.object(urlhaus.Source, "_save", save):
            self.assertEqual(source.update(fake, T0, plan())["status"], "ok")
            self.assertEqual(source.update(fake, T0 + datetime.timedelta(hours=2), plan())["status"], "off-for-the-day")
        self.assertEqual(len(fake.calls), 1)

    def test_a_source_made_before_another_writer_acted_sees_what_that_writer_wrote(self):
        early = self.source()
        self.source().update(FakeGet(ok()), T0, plan())
        fake = FakeGet(ok())
        self.assertEqual(early.update(fake, T0 + datetime.timedelta(minutes=10), plan())["status"], "not-due")
        self.assertEqual(fake.calls, [])

    def test_a_lock_that_cannot_be_opened_means_no_request(self):
        os.makedirs(self.state, mode=0o700)
        os.mkdir(os.path.join(self.state, "urlhaus.lock"))
        fake = FakeGet(ok())
        report = self.source().update(fake, T0, plan())
        self.assertEqual((report["status"], fake.calls), ("failed", []))

    def test_a_state_that_parses_but_holds_odd_times_or_a_version_is_unreadable(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, encoding="utf-8") as f:
            good = json.load(f)
        for change in ({"off_day": 20261116}, {"off_day": "2026-11-16 "}, {"off_day": "today"}, {"last": 5}, {"last": "2026-11-16 12:00"}, {"last": float("nan")}, {"version": 2}, {"version": "1"},
                       {"off_day": ["2026-11-16"]}, {"last": {"a": 1}}):
            with self.subTest(str(change)):
                state = {**good, "off_day": None, **change}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(state, f)
                os.chmod(path, 0o600)
                fake = FakeGet(ok())
                self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(hours=5), plan())["status"], "off-for-the-day")
                self.assertEqual(fake.calls, [])

    def test_a_kill_or_a_failed_save_after_a_refusal_still_means_no_key_that_day_in_a_new_process(self):
        source = self.source()
        real = urlhaus.Source._save
        calls = []

        def save(self_):
            calls.append(1)
            if len(calls) > 1:
                raise OSError(28, "No space left on device")
            return real(self_)

        with mock.patch.object(urlhaus.Source, "_save", save):
            self.assertEqual(source.update(FakeGet((403, {}, b"")), T0, plan())["status"], "refused")
        fake = FakeGet(ok())
        self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(hours=2), plan())["status"], "off-for-the-day")
        self.assertEqual(fake.calls, [])
        for error in (SystemExit(), KeyboardInterrupt()):
            with self.subTest(type(error).__name__):
                state = os.path.join(self.dir, f"k{type(error).__name__}")
                with self.assertRaises(type(error)):
                    urlhaus.Source(state, self.key_path).update(FakeGet(error), T0, plan())
                fake = FakeGet(ok())
                self.assertEqual(urlhaus.Source(state, self.key_path).update(fake, T0 + datetime.timedelta(hours=2), plan())["status"], "off-for-the-day")
                self.assertEqual(fake.calls, [])

    def test_a_good_reply_clears_the_day_and_the_hour_rule_then_applies_alone(self):
        source = self.source()
        fake = FakeGet(ok(), ok())
        self.assertEqual(source.update(fake, T0, plan())["status"], "ok")
        with open(os.path.join(self.state, "urlhaus.json"), encoding="utf-8") as f:
            self.assertIsNone(json.load(f)["off_day"])
        self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(minutes=30), plan())["status"], "not-due")
        self.assertEqual(self.source().update(fake, T0 + datetime.timedelta(hours=1), plan())["status"], "ok")
        fail = FakeGet(webclient.FetchError("timed out"))
        self.assertEqual(self.source().update(fail, T0 + datetime.timedelta(hours=3), plan())["status"], "failed")
        self.assertEqual(self.source().update(FakeGet(ok()), T0 + datetime.timedelta(hours=4), plan())["status"], "ok")      # a transport failure is not a refusal

    def test_the_kept_urls_survive_a_state_that_is_unreadable_for_its_mode_or_owner(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        os.chmod(path, 0o644)
        m = self.matcher()
        report = self.source().update(FakeGet(), T0 + datetime.timedelta(hours=3), plan(), matcher=m)
        self.assertEqual(report["status"], "off-for-the-day")
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))                 # the list is not emptied because the file was loose
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        m2 = self.matcher()
        self.assertEqual(self.source().load_into(m2), 3)

    def test_a_state_that_is_broken_is_moved_aside_and_not_overwritten(self):
        self.source().update(FakeGet(ok()), T0, plan())
        path = os.path.join(self.state, "urlhaus.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json at all")
        os.chmod(path, 0o600)
        self.assertEqual(self.source().update(FakeGet(), T0 + datetime.timedelta(hours=3), plan())["status"], "off-for-the-day")
        with open(path + ".bad", encoding="utf-8") as f:
            self.assertEqual(f.read(), "not json at all")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], 1)

    def test_a_state_path_that_is_a_folder_or_a_pipe_is_moved_aside_so_the_state_can_be_written_again(self):
        path = os.path.join(self.state, "urlhaus.json")
        for kind in ("folder", "pipe"):
            with self.subTest(kind):
                if os.path.lexists(path):
                    os.remove(path)
                if os.path.lexists(path + ".bad"):
                    shutil.rmtree(path + ".bad") if os.path.isdir(path + ".bad") else os.remove(path + ".bad")
                os.makedirs(self.state, mode=0o700, exist_ok=True)
                if kind == "folder":
                    os.mkdir(path)
                else:
                    os.mkfifo(path, 0o600)
                self.assertEqual(self.source().update(FakeGet(), T0, plan())["status"], "off-for-the-day")
                self.assertTrue(os.path.isdir(path + ".bad") if kind == "folder" else stat.S_ISFIFO(os.lstat(path + ".bad").st_mode))
                self.assertTrue(stat.S_ISREG(os.lstat(path).st_mode))
                self.assertEqual(self.source().update(FakeGet(ok()), T0 + datetime.timedelta(days=1), plan())["status"], "ok")

    def test_a_busy_lock_does_not_leak_a_descriptor(self):
        first = self.source()
        counts = []

        def during(self_, *a, **k):
            before = len(os.listdir("/dev/fd"))
            for _ in range(30):
                urlhaus.Source(first._dir, first._key_path).update(FakeGet(), T0, plan())
            counts.append(len(os.listdir("/dev/fd")) - before)
            return {"status": "ok"}

        with mock.patch.object(urlhaus.Source, "_step", during):
            first.update(FakeGet(), T0, plan())
        self.assertEqual(counts, [0])

    def test_the_matcher_is_fed_when_another_writer_is_busy_or_the_folder_is_unusable(self):
        self.source().update(FakeGet(ok()), T0, plan())
        first = self.source()
        real = urlhaus.Source._step

        def during(self_, *a, **k):
            m = self_._probe_matcher
            report = urlhaus.Source(first._dir, first._key_path).update(FakeGet(), T0 + datetime.timedelta(minutes=5), plan(), matcher=m)
            self_._busy_report = report
            return {"status": "ok"}

        first._probe_matcher = self.matcher()
        with mock.patch.object(urlhaus.Source, "_step", during):
            first.update(FakeGet(), T0 + datetime.timedelta(minutes=5), plan())
        self.assertEqual(first._busy_report["status"], "busy")
        self.assertIsNotNone(first._probe_matcher.blocked("http://203.0.113.9/bins/payload.sh"))
        m = self.matcher()
        with mock.patch.object(urlhaus, "ensure_private_dir", side_effect=ListError("not ours")):
            report = self.source().update(FakeGet(), T0 + datetime.timedelta(hours=2), plan(), matcher=m)
        self.assertEqual(report["status"], "failed")
        self.assertIsNotNone(m.blocked("http://203.0.113.9/bins/payload.sh"))

    def test_a_pipe_in_place_of_the_lock_file_does_not_hang_the_update(self):
        os.makedirs(self.state, mode=0o700)
        os.mkfifo(os.path.join(self.state, "urlhaus.lock"), 0o600)
        fake = FakeGet(ok())
        report = self.source().update(fake, T0, plan())
        self.assertEqual((report["status"], fake.calls), ("failed", []))

    def test_a_state_path_with_a_nul_or_that_is_not_text_is_a_failed_update_and_not_a_crash(self):
        fake = FakeGet(ok())
        self.assertEqual(urlhaus.Source(os.path.join(self.dir, "a\x00b"), self.key_path).update(fake, T0, plan())["status"], "failed")
        self.assertEqual(fake.calls, [])

    def test_old_temporary_files_of_the_state_are_swept_and_young_ones_are_not(self):
        os.makedirs(self.state, mode=0o700)
        old = os.path.join(self.state, ".urlhaus.json.0123456789ab.new")
        young = os.path.join(self.state, ".urlhaus.json.ba9876543210.new")
        other = os.path.join(self.state, ".notes.new")
        for path in (old, young, other):
            open(path, "w").write("x")
        long_ago = datetime.datetime.now().timestamp() - 7200
        os.utime(old, (long_ago, long_ago))
        os.utime(other, (long_ago, long_ago))
        self.source().update(FakeGet(ok()), T0, plan())
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))
        self.assertTrue(os.path.exists(other))

    def test_a_second_writer_does_not_ask_while_the_first_is_at_work(self):
        outcomes = []
        first = self.source()

        def during(*args, **kwargs):
            second = self.source()
            fake = FakeGet(ok())
            outcomes.append((second.update(fake, T0, plan())["status"], len(fake.calls)))
            return ok()

        class Spy:
            def __call__(self_, url, **kw):
                return during()

        first.update(Spy(), T0, plan())
        self.assertEqual(outcomes, [("busy", 0)])
        self.assertEqual(self.source().update(FakeGet(ok()), T0 + datetime.timedelta(hours=2), plan())["status"], "ok")     # the lock is let go

    def test_the_lock_is_not_a_file_that_others_can_hold_open_for_ever(self):
        self.source().update(FakeGet(ok()), T0, plan())
        lock = os.path.join(self.state, "urlhaus.lock")
        self.assertEqual(stat.S_IMODE(os.stat(lock).st_mode), 0o600)


class OverTheWire(Net):
    """The real shared client against a fake server: the key goes to one host over https, and a redirect to another host sees no key and ends the day."""

    API_HOST = "urlhaus-api.abuse.ch"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.key_path = os.path.join(self.dir, "urlhaus.key")
        with open(self.key_path, "w", encoding="utf-8") as f:
            f.write(CANARY + "\n")
        os.chmod(self.key_path, 0o600)
        self.dns[self.API_HOST] = ["93.184.216.80"]
        self.dns["evil.test"] = ["93.184.216.81"]
        patcher = mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = urlhaus.Source(os.path.join(self.dir, "lists"), self.key_path)

    def test_the_key_header_goes_to_the_api_host_over_https_and_the_reply_is_taken(self):
        self.srv.routes["/v1/urls/recent/"] = reply(200, [("X-RateLimit-Remaining", "4000")], SAMPLE, ctype="application/json")
        report = self.source.update(webclient.get, T0, plan())
        self.assertEqual(report["status"], "ok")
        path, headers = self.srv.hits[0]
        self.assertEqual((path, headers["auth-key"], headers["host"]), ("/v1/urls/recent/", CANARY, self.API_HOST))
        self.assertEqual(self.dials, [("93.184.216.80", 443)])

    def test_a_redirect_to_another_host_sees_no_key_and_the_key_is_not_sent_again_that_day(self):
        self.srv.routes["/v1/urls/recent/"] = redirect("https://evil.test/steal")
        self.srv.routes["/steal"] = reply(200, body=b"{}", ctype="application/json")
        report = self.source.update(webclient.get, T0, plan())
        self.assertEqual(report["status"], "refused")
        self.assertEqual([path for path, _ in self.srv.hits], ["/v1/urls/recent/"])           # the second host was never asked
        self.assertNotIn("evil.test", self.lookups)
        for _, headers in self.srv.hits[1:]:
            self.assertNotIn("auth-key", headers)
        self.assertEqual(self.source.update(webclient.get, T0 + datetime.timedelta(hours=3), plan())["status"], "off-for-the-day")
        self.assertEqual(len(self.srv.hits), 1)
        self.assertNotIn(CANARY, json.dumps(report))

    def test_a_server_that_echoes_the_key_into_a_header_does_not_get_it_into_the_report(self):
        self.srv.routes["/v1/urls/recent/"] = lambda conn, path, headers: conn.sendall(
            f"HTTP/1.1 200 X\r\nContent-Type: application/json\r\nETag: {headers['auth-key']}\r\nContent-Encoding: {headers['auth-key']}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}".encode("latin-1"))
        report = self.source.update(webclient.get, T0, plan())
        self.assertNotIn(CANARY.lower(), json.dumps(report).lower())

    def test_an_http_address_would_not_be_given_the_key_at_all(self):
        with mock.patch.object(urlhaus, "RECENT_URL", "http://urlhaus-api.abuse.ch/v1/urls/recent/"):
            report = self.source.update(webclient.get, T0, plan())
        self.assertEqual(self.srv.hits, [])
        self.assertIn(report["status"], ("refused", "failed"))


class Contract(unittest.TestCase):
    def test_the_constants_are_the_documented_ones(self):
        self.assertEqual(urlhaus.HOST, "urlhaus-api.abuse.ch")
        self.assertEqual(urlhaus.RECENT_URL, "https://urlhaus-api.abuse.ch/v1/urls/recent/")
        self.assertEqual(urlhaus.REFRESH_HOURS, 1)
        self.assertEqual(urlhaus.MAX_REPLY_URLS, 1000 * 5)


if __name__ == "__main__":
    unittest.main()
