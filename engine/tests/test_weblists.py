"""The owner's blacklist, the allow file and the public lists (`kb/weblists.py`, Increment D of the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`).

The line shapes in `fixtures/web/phishing-domains-sample.txt` are the ones seen in a real download of the Phishing.Database active-domains list on 2026-11-16 (11,023,128 bytes, 392,179 lines, one
host per line, no comment or header lines, 15 lines padded with spaces, 6 with a trailing dot, 615 that are not hostnames: underscores, `http://` addresses cut short, `%20`); the names are made up. Nothing here
touches the network: the downloader `get` is a fake.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_weblists`."""
import datetime
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)

from kb import webaddr, weblists, webclient

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "web")
with open(os.path.join(FIXTURES, "phishing-domains-sample.txt"), "rb") as _f:
    SAMPLE = _f.read()
PSL = ("// ===BEGIN ICANN DOMAINS===\ncom\nuk\nco.uk\n*.ck\n!www.ck\n// ===END ICANN DOMAINS===\n// ===BEGIN PRIVATE DOMAINS===\ngithub.io\n// ===END PRIVATE DOMAINS===\n").encode()
T0 = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)
REAL_FLOORS = dict(weblists.MIN_ENTRIES)    # as shipped, before the tests lower them
PHISH_URL = "https://lists.example/phishing-domains-ACTIVE.txt"
PSL_URL = "https://lists.example/public_suffix_list.dat"


def plan(**kw):
    base = {"phishing_domains": True, "phishing_domains_url": PHISH_URL, "public_suffix_url": PSL_URL}
    base.update(kw)
    return base


def hosts(n, prefix="h"):
    return "".join(f"{prefix}{i}.example\n" for i in range(n)).encode()


class Fake:
    """A downloader: `get(url, headers, max_bytes) -> (status, headers, body)`, answering from `answers` and recording each call."""

    def __init__(self, answers=None):
        self.answers, self.calls = dict(answers or {}), []

    def __call__(self, url, headers, max_bytes):
        self.calls.append((url, dict(headers), max_bytes))
        answer = self.answers.get(url)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer()
        if answer is None:
            return 404, {}, b""
        return answer


def ok(body, etag='"v1"', modified="Sun, 15 Nov 2026 20:28:50 GMT"):
    headers = {}
    if etag:
        headers["etag"] = etag
    if modified:
        headers["last-modified"] = modified
    return 200, headers, body


class Files(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.black = os.path.join(self.dir, "blacklist.txt")
        self.allow = os.path.join(self.dir, "allow.txt")
        self.lists = os.path.join(self.dir, "lists")
        floors = mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1, "public_suffix": 1})   # the real floors are checked by their own tests
        floors.start()
        self.addCleanup(floors.stop)

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def data(self, name):
        """The path of the stored data file of a list, from its record."""
        with open(os.path.join(self.lists, f"{name}.meta.json"), encoding="utf-8") as f:
            return os.path.join(self.lists, json.load(f)["file"])

    def matcher(self, pinned=("openalex.org", "arxiv.org", "wikipedia.org")):
        return weblists.Matcher(self.black, self.allow, self.lists, list(pinned))

    def stocked(self, body=SAMPLE, **kw):
        """A matcher whose phishing list holds `body`, loaded by a first update."""
        m = self.matcher(**kw)
        report = m.update(Fake({PHISH_URL: ok(body), PSL_URL: ok(PSL, etag='"p1"')}), T0, plan())
        self.assertFalse(report["stop"], report)
        return m


class Parsers(unittest.TestCase):
    def test_a_list_of_domains_is_read_as_the_real_one_is_shaped(self):
        found, ignored = weblists.parse_domains(SAMPLE.decode())
        self.assertIn("bad.example", found)
        self.assertIn("battle-case.example", found)           # padded with spaces in the file
        self.assertIn("case-batls.example", found)           # upper case in the file
        self.assertIn("trailing-dot.example", found)         # a trailing dot in the file
        self.assertIn("203.0.113.7", found)
        self.assertIn("2001:db8::7", found)
        self.assertEqual(len([h for h in found if h == "duplicate.example"]), 1)
        # the ones that are not hostnames are ignored and counted: an underscore, an address cut short, a URL, a percent escape
        self.assertEqual(ignored, 4)
        for bad in ("10000susan_gilbert.hosting.example", "%20mandrillapp.example"):
            self.assertNotIn(bad, found)

    def test_a_list_with_too_many_lines_is_refused_before_it_is_split(self):
        class Text(str):
            def split(self, *a, **k):
                raise AssertionError("split before the count")

        with mock.patch.object(weblists, "MAX_LINES", 5):
            for parse in (weblists.parse_domains, weblists.parse_urls):
                with self.assertRaises(weblists.ListError):
                    parse(Text("a.example\n" * 9))

    def test_comments_blank_lines_and_other_shapes(self):
        text = "# a comment\n// another\n; a third\n\n   \nEvil.COM.\nbücher.example\nsecond.example # trailing words are not a host\nok.example\r\nfor sale\n-x.example\nx..example\n"
        found, ignored = weblists.parse_domains(text)
        self.assertEqual(found, {"evil.com", "xn--bcher-kva.example", "ok.example"})
        self.assertEqual(ignored, 4)

    def test_the_lines_and_bytes_are_capped(self):
        with mock.patch.object(weblists, "MAX_LINES", 5):
            with self.assertRaises(weblists.ListError):
                weblists.parse_domains("a.example\n" * 6)
            self.assertEqual(len(weblists.parse_domains("a.example\n" * 5)[0]), 1)

    def test_a_url_list_keeps_exact_canonical_urls_and_finds_the_bare_addresses(self):
        text = "HTTP://Bad.example./a/b?utm_source=x&k=1#f\nhttps://github.com/owner/repo\nhttp://203.0.113.9/payload.exe\nhttp://[2001:db8::9]/x\nnot a url\nftp://x.example/\nhttp://bad.example:8080/\n\n"
        urls, bare, ignored = weblists.parse_urls(text)
        self.assertEqual(urls, {"http://bad.example/a/b?k=1", "https://github.com/owner/repo", "http://203.0.113.9/payload.exe", "http://[2001:db8::9]/x"})
        self.assertEqual(bare, {"203.0.113.9", "2001:db8::9"})
        self.assertEqual(ignored, 3)


class OwnerFiles(Files):
    def test_the_blacklist_blocks_the_host_and_every_host_below_it_in_every_spelling(self):
        self.write(self.black, "evil.com\n# a note\nbücher.example\n")
        m = self.matcher()
        for target in ("evil.com", "evil.com.", "EVIL.com", "a.evil.com", "a.b.evil.com", "http://evil.com:80/x", "https://EVIL.com./p?q=1", "evil.com:80", "xn--bcher-kva.example", "bücher.example",
                       "www.XN--BCHER-KVA.example"):
            with self.subTest(target):
                block = m.blocked(target)
                self.assertIsNotNone(block)
                self.assertEqual(block.reason, "owner")
        for target in ("notevil.com", "evil.com.au", "com", "evil.co", "http://notevil.com/", "example.com"):
            with self.subTest(target):
                self.assertIsNone(m.blocked(target))

    def test_blacklisting_a_subdomain_does_not_block_its_parent(self):
        self.write(self.black, "a.evil.com\n")
        m = self.matcher()
        self.assertIsNone(m.blocked("evil.com"))
        self.assertIsNone(m.blocked("b.evil.com"))
        self.assertIsNotNone(m.blocked("x.a.evil.com"))

    def test_a_missing_file_is_an_empty_list_and_an_empty_one_blocks_nothing(self):
        m = self.matcher()
        self.assertIsNone(m.blocked("evil.com"))
        self.write(self.black, "")
        self.write(self.allow, "")
        m.reload()
        self.assertIsNone(m.blocked("evil.com"))

    def test_a_host_added_to_the_blacklist_is_blocked_at_the_next_reload_and_one_removed_is_freed(self):
        self.write(self.black, "old.com\n")
        m = self.matcher()
        self.assertIsNone(m.blocked("new.com"))
        self.write(self.black, "old.com\nnew.com\n")
        self.assertIsNone(m.blocked("new.com"))      # not before the reload
        m.reload()
        self.assertEqual(m.blocked("new.com").reason, "owner")
        self.write(self.black, "new.com\n")
        m.reload()
        self.assertIsNone(m.blocked("old.com"))

    def test_a_bad_line_in_the_owners_file_is_an_error_naming_the_line_and_the_old_list_stays(self):
        self.write(self.black, "evil.com\n")
        m = self.matcher()
        self.write(self.black, "evil.com\nbad host here\nsecond.com\nunder_score.com\n")
        with self.assertRaises(weblists.ListError) as caught:
            m.reload()
        self.assertIn("2", str(caught.exception))
        self.assertIn("4", str(caught.exception))
        self.assertNotIn("bad host here", str(caught.exception))
        self.assertIsNotNone(m.blocked("evil.com"))
        self.assertIsNone(m.blocked("second.com"))
        self.write(self.black, "bad host here\n")
        with self.assertRaises(weblists.ListError):
            self.matcher()

    def test_a_file_that_is_a_link_a_folder_a_pipe_or_too_large_is_refused(self):
        real = os.path.join(self.dir, "real.txt")
        self.write(real, "evil.com\n")
        os.symlink(real, self.black)
        with self.assertRaises(weblists.ListError):
            self.matcher()
        os.remove(self.black)
        os.mkdir(self.black)
        with self.assertRaises(weblists.ListError):
            self.matcher()
        os.rmdir(self.black)
        os.mkfifo(self.black)
        with self.assertRaises(weblists.ListError):
            self.matcher()
        os.remove(self.black)
        self.write(self.black, "a.example\n" * 200)
        with mock.patch.object(weblists, "MAX_OWNER_BYTES", 500):
            with self.assertRaises(weblists.ListError):
                self.matcher()
        self.assertIsNone(self.matcher().blocked("zzz.example"))
        self.write(self.allow, "ok.example\n")
        os.remove(self.allow)
        os.symlink(real, self.allow)
        with self.assertRaises(weblists.ListError):
            self.matcher()

    def test_a_file_with_bytes_that_are_not_utf8_is_refused(self):
        with open(self.black, "wb") as f:
            f.write(b"evil.com\n\xff\xfe\n")
        with self.assertRaises(weblists.ListError):
            self.matcher()

    def test_the_pinned_hosts_are_checked_before_they_are_used(self):
        for bad in (["bad host"], ["x.example/y"], "openalex.org", "openalex", [5], None):
            with self.subTest(repr(bad)):
                with self.assertRaises(weblists.ListError):
                    weblists.Matcher(self.black, self.allow, self.lists, bad)


class PublicLists(Files):
    def test_a_public_host_list_blocks_that_exact_hostname_only(self):
        m = self.stocked()
        for target in ("bad.example", "BAD.example.", "http://bad.example:80/page", "sub.bad.example", "203.0.113.7", "http://[2001:db8::7]/", "xn--bcher-kva.example", "bücher.example"):
            with self.subTest(target):
                block = m.blocked(target)
                self.assertIsNotNone(block)
                self.assertEqual(block.reason, "list:phishing_domains")
        for target in ("below.sub.bad.example", "example", "other.example", "xbad.example", "203.0.113.8"):
            with self.subTest(target):
                self.assertIsNone(m.blocked(target))

    def test_the_owners_blacklist_wins_over_everything_and_is_named_first(self):
        self.write(self.black, "bad.example\n")
        self.write(self.allow, "bad.example\n")
        m = self.stocked()
        self.assertEqual(m.blocked("bad.example").reason, "owner")
        self.assertEqual(m.blocked("x.bad.example").reason, "owner")

    def test_the_pinned_hosts_are_never_blocked_by_a_public_list_but_the_blacklist_still_can(self):
        m = self.stocked()                     # the sample lists openalex.org and api.openalex.org
        self.assertIsNone(m.blocked("openalex.org"))
        self.assertIsNone(m.blocked("api.openalex.org"))
        self.assertIsNone(m.blocked("http://api.openalex.org/works?x=1"))
        self.assertEqual(m.blocked("github.com").reason, "list:phishing_domains")    # not pinned
        self.write(self.black, "openalex.org\n")
        m.reload()
        self.assertEqual(m.blocked("api.openalex.org").reason, "owner")

    def test_the_allow_file_overrides_a_public_list_for_that_host_only(self):
        self.write(self.allow, "bad.example\n")
        m = self.stocked()
        self.assertIsNone(m.blocked("bad.example"))
        self.assertIsNone(m.blocked("http://bad.example/x"))
        self.assertIsNotNone(m.blocked("sub.bad.example"))     # a host below an allowed one is not allowed by it
        self.write(self.allow, "sub.bad.example\n")
        m.reload()
        self.assertIsNotNone(m.blocked("bad.example"))
        self.assertIsNone(m.blocked("sub.bad.example"))

    def test_a_url_list_blocks_that_exact_url_and_a_whole_host_only_for_a_bare_address(self):
        m = self.matcher()
        m.set_urls("urlhaus_recent", ["http://bad.example/a?k=1", "https://github.com/owner/repo", "http://203.0.113.9/payload.exe"])
        self.assertEqual(m.blocked("http://bad.example/a?k=1").reason, "list:urlhaus_recent")
        self.assertEqual(m.blocked("HTTP://BAD.example./a?k=1&utm_source=z#f").reason, "list:urlhaus_recent")
        self.assertIsNone(m.blocked("http://bad.example/a"))
        self.assertIsNone(m.blocked("http://bad.example/"))
        self.assertIsNone(m.blocked("bad.example"))
        self.assertEqual(m.blocked("https://github.com/owner/repo").reason, "list:urlhaus_recent")
        self.assertIsNone(m.blocked("https://github.com/other"))
        self.assertIsNone(m.blocked("github.com"))
        self.assertEqual(m.blocked("http://203.0.113.9/anything/else").reason, "list:urlhaus_recent")
        self.assertEqual(m.blocked("203.0.113.9").reason, "list:urlhaus_recent")
        self.assertIsNone(m.blocked("203.0.113.10"))

    def test_a_url_list_does_not_override_pinned_hosts_the_allow_file_or_the_blacklist_order(self):
        self.write(self.allow, "bad.example\n")
        m = self.matcher()
        m.set_urls("urlhaus_recent", ["http://bad.example/a", "https://arxiv.org/abs/1", "http://203.0.113.9/p"])
        self.assertIsNone(m.blocked("http://bad.example/a"))
        self.assertIsNone(m.blocked("https://arxiv.org/abs/1"))
        self.assertIsNotNone(m.blocked("http://203.0.113.9/p"))

    def test_input_that_is_not_an_address_or_host_is_blocked_and_not_passed(self):
        m = self.matcher()
        for bad in ("", "bad host", "http://", "ftp://x.example/", "http://a.example:8080/", None, 5, b"x.example", "x" * 3000):
            with self.subTest(repr(bad)[:30]):
                block = m.blocked(bad)
                self.assertIsNotNone(block)
                self.assertEqual(block.reason, "unusable")

    def test_an_address_written_as_an_ipv4_one_inside_an_ipv6_one_is_the_same_entry(self):
        self.write(self.black, "1.2.3.4\n")
        m = self.matcher()
        for spelling in ("http://[::ffff:1.2.3.4]/", "http://[::ffff:102:304]/", "[::ffff:102:304]", "::ffff:1.2.3.4", "http://[64:ff9b::102:304]/", "http://[2002:102:304::1]/", "http://[::102:304]/", "http://[::ffff:0:102:304]/"):
            with self.subTest(spelling):
                self.assertEqual(m.blocked(spelling).reason, "owner")
        self.assertIsNone(m.blocked("http://[::ffff:1.2.3.5]/"))
        self.assertIsNone(m.blocked("http://[::1]/"))
        self.assertIsNone(m.blocked("http://[::]/"))

    def test_the_ipv6_loopback_and_the_unspecified_address_are_not_read_as_ipv4_addresses(self):
        self.write(self.black, "0.0.0.1\n0.0.0.0\n")
        m = self.matcher()
        self.assertIsNone(m.blocked("http://[::1]/"))
        self.assertIsNone(m.blocked("http://[::]/"))

    def test_an_owner_entry_or_a_bare_url_entry_written_inside_an_ipv6_address_is_the_ipv4_one(self):
        self.write(self.black, "::ffff:1.2.3.4\n")
        m = self.matcher()
        self.assertEqual(m.blocked("http://1.2.3.4/").reason, "owner")
        m.set_urls("urlhaus_recent", ["http://[::ffff:5.6.7.8]/x"])
        self.assertEqual(m.blocked("http://5.6.7.8/anything").reason, "list:urlhaus_recent")

    def test_a_list_entry_written_inside_an_ipv6_address_blocks_the_ipv4_one(self):
        m = self.stocked(body=b"::ffff:5.6.7.8\n2002:909:90a::\nother.example\n")
        self.assertEqual(m.blocked("http://5.6.7.8/").reason, "list:phishing_domains")
        self.assertEqual(m.blocked("http://9.9.9.10/").reason, "list:phishing_domains")

    def test_a_block_reads_as_its_reason(self):
        block = weblists.Block("list:x")
        self.assertEqual((block.reason, str(block), bool(block)), ("list:x", "list:x", True))


class Updates(Files):
    def test_the_first_update_downloads_each_list_stores_it_privately_and_starts_using_it(self):
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL, etag='"p1"')})
        m = self.matcher()
        report = m.update(fake, T0, plan())
        self.assertFalse(report["stop"])
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        self.assertEqual(report["lists"]["public_suffix"]["status"], "updated")
        self.assertEqual([c[0] for c in fake.calls], [PHISH_URL, PSL_URL])
        self.assertEqual(fake.calls[0][2], 50 * 1024 * 1024)                    # list_max_mb
        self.assertEqual(fake.calls[0][1], {})                                   # nothing to be conditional on yet
        self.assertIsNotNone(m.blocked("bad.example"))
        self.assertEqual(m.suffixes(), webaddr.load_suffixes(self.data("public_suffix")))
        self.assertEqual(webaddr.site_of("a.b.example.co.uk", m.suffixes()), "example.co.uk")
        self.assertEqual(stat.S_IMODE(os.stat(self.lists).st_mode), 0o700)
        for name in os.listdir(self.lists):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.lists, name)).st_mode), 0o600, name)
        with open(os.path.join(self.lists, "phishing_domains.meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["sha256"], hashlib.sha256(SAMPLE).hexdigest())
        self.assertEqual((meta["retrieved"], meta["etag"], meta["source"]), ("2026-11-16T12:00:00Z", '"v1"', PHISH_URL))
        self.assertEqual(meta["entries"], len(weblists.parse_domains(SAMPLE.decode())[0]))
        self.assertEqual(sorted(os.listdir(self.lists)), sorted(["phishing_domains.meta.json", os.path.basename(self.data("phishing_domains")), "public_suffix.meta.json", os.path.basename(self.data("public_suffix"))]))
        self.assertRegex(os.path.basename(self.data("phishing_domains")), r"^phishing_domains\.[0-9a-f]{16}\.txt$")
        self.assertIn(meta["sha256"][:16], os.path.basename(self.data("phishing_domains")))

    def test_a_new_process_finds_the_stored_copies(self):
        self.stocked()
        again = self.matcher()
        self.assertIsNotNone(again.blocked("bad.example"))
        self.assertTrue(again.suffixes())
        self.assertEqual(again.problems, [])

    def test_a_list_is_asked_for_at_most_once_in_the_refresh_hours_and_then_conditionally(self):
        m = self.stocked()
        fake = Fake({PHISH_URL: (304, {"etag": '"v1"'}, b""), PSL_URL: (304, {}, b"")})
        report = m.update(fake, T0 + datetime.timedelta(hours=11, minutes=59), plan())
        self.assertEqual(fake.calls, [])
        self.assertEqual({report["lists"][n]["status"] for n in ("phishing_domains", "public_suffix")}, {"not-due"})
        report = m.update(fake, T0 + datetime.timedelta(hours=12), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "unchanged")
        headers = dict((c[0], c[1]) for c in fake.calls)
        self.assertEqual(headers[PHISH_URL], {"If-None-Match": '"v1"', "If-Modified-Since": "Sun, 15 Nov 2026 20:28:50 GMT"})
        self.assertEqual(headers[PSL_URL], {"If-None-Match": '"p1"', "If-Modified-Since": "Sun, 15 Nov 2026 20:28:50 GMT"})
        self.assertIsNotNone(m.blocked("bad.example"))
        later = T0 + datetime.timedelta(hours=23)         # the 304 counted as a check at hour 12
        fake.calls.clear()
        m.update(fake, later, plan())
        self.assertEqual(fake.calls, [])
        m.update(fake, T0 + datetime.timedelta(hours=35, minutes=59), plan(refresh_hours=24))
        self.assertEqual(len(fake.calls), 0)
        m.update(fake, T0 + datetime.timedelta(hours=36), plan(refresh_hours=24))
        self.assertEqual(len(fake.calls), 2)

    def test_a_changed_list_replaces_the_copy(self):
        m = self.stocked()
        new = SAMPLE + b"fresh-phish.example\n"
        report = m.update(Fake({PHISH_URL: ok(new, etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        self.assertIsNotNone(m.blocked("fresh-phish.example"))
        with open(os.path.join(self.lists, "phishing_domains.meta.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["etag"], '"v2"')

    def test_a_failed_download_a_refusal_or_a_bad_status_leaves_the_last_copy_in_use(self):
        later = T0 + datetime.timedelta(hours=13)
        for answer in (webclient.FetchError("timed out"), webclient.Refused("refused: private address"), OSError("boom"), (500, {}, b""), (503, {}, b"<html>down</html>"), (404, {}, b""),
                       (302, {"location": "http://x.example/"}, b"")):
            with self.subTest(repr(answer)[:40]):
                m = self.stocked()
                report = m.update(Fake({PHISH_URL: answer, PSL_URL: (304, {}, b"")}), later, plan())
                self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
                self.assertFalse(report["stop"])
                self.assertIsNotNone(m.blocked("bad.example"))
                self.assertIsNotNone(self.matcher().blocked("bad.example"))

    def test_a_required_list_with_no_copy_stops_and_an_optional_one_is_skipped(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: webclient.FetchError("timed out"), PSL_URL: (500, {}, b"")}), T0, plan())
        self.assertTrue(report["stop"])
        self.assertIn("phishing_domains", report["stop_reason"])
        self.assertEqual(report["lists"]["public_suffix"]["status"], "failed")
        self.assertEqual(m.suffixes(), frozenset())
        m2 = self.matcher()
        report = m2.update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: (500, {}, b"")}), T0, plan())
        self.assertFalse(report["stop"])                 # the suffix list is optional
        self.assertEqual(report["lists"]["public_suffix"]["status"], "failed")

    def test_a_list_that_is_off_is_not_asked_for_and_does_not_stop_the_run(self):
        m = self.matcher()
        fake = Fake({PSL_URL: ok(PSL)})
        report = m.update(fake, T0, plan(phishing_domains=False))
        self.assertFalse(report["stop"])
        self.assertEqual([c[0] for c in fake.calls], [PSL_URL])
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "off")

    def test_urlhaus_is_not_handled_here(self):
        m = self.matcher()
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)})
        report = m.update(fake, T0, plan(urlhaus_recent=True))
        self.assertEqual(report["lists"]["urlhaus_recent"]["status"], "skipped")
        self.assertNotIn("urlhaus", " ".join(c[0] for c in fake.calls))

    def test_a_list_over_the_size_limit_is_refused_and_the_old_copy_stays(self):
        m = self.stocked()
        big = hosts(500)
        report = m.update(Fake({PHISH_URL: ok(big), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan(list_max_mb=0.001))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIn("size", report["lists"]["phishing_domains"]["reason"])
        self.assertIsNotNone(m.blocked("bad.example"))
        self.assertIsNone(m.blocked("h1.example"))

    def test_a_list_that_has_become_far_smaller_is_refused(self):
        m = self.matcher()
        m.update(Fake({PHISH_URL: ok(hosts(100)), PSL_URL: ok(PSL)}), T0, plan())
        later = T0 + datetime.timedelta(hours=13)
        report = m.update(Fake({PHISH_URL: ok(hosts(49), etag='"v2"'), PSL_URL: (304, {}, b"")}), later, plan(list_min_share=0.5, list_max_change=1.0))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIn("smaller", report["lists"]["phishing_domains"]["reason"])
        self.assertIsNotNone(m.blocked("h99.example"))
        report = m.update(Fake({PHISH_URL: ok(hosts(50), etag='"v2"'), PSL_URL: (304, {}, b"")}), later, plan(list_min_share=0.5, list_max_change=1.0))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")

    def test_a_list_that_changes_too_much_in_one_refresh_is_refused(self):
        m = self.matcher()
        m.update(Fake({PHISH_URL: ok(hosts(100)), PSL_URL: ok(PSL)}), T0, plan())
        later = T0 + datetime.timedelta(hours=13)
        swapped = hosts(100, "z")
        report = m.update(Fake({PHISH_URL: ok(swapped, etag='"v2"'), PSL_URL: (304, {}, b"")}), later, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIn("changed", report["lists"]["phishing_domains"]["reason"])
        self.assertIsNotNone(m.blocked("h5.example"))
        self.assertIsNone(m.blocked("z5.example"))
        # 100 entries, 30 removed and none added is a change of 0.30: allowed; 31 is not
        small = hosts(70)
        report = m.update(Fake({PHISH_URL: ok(small, etag='"v3"'), PSL_URL: (304, {}, b"")}), later, plan(list_min_share=0.1))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        m3 = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "lists3"), [])
        m3.update(Fake({PHISH_URL: ok(hosts(100)), PSL_URL: ok(PSL)}), T0, plan())
        report = m3.update(Fake({PHISH_URL: ok(hosts(69), etag='"v3"'), PSL_URL: (304, {}, b"")}), later, plan(list_min_share=0.1))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")

    def test_a_first_download_is_not_held_to_the_size_and_change_rules_but_must_hold_hosts(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: ok(hosts(3)), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        for body in (b"", b"<html><body>Not found</body></html>", b"# only a comment\n", b"\x00\x01\x02", "only bad_names.example\n".encode()):
            with self.subTest(body[:20]):
                m4 = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "fresh", str(abs(hash(body)))), [])
                report = m4.update(Fake({PHISH_URL: ok(body), PSL_URL: ok(PSL)}), T0, plan())
                self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
                self.assertTrue(report["stop"])

    def test_a_download_that_cannot_be_written_into_place_leaves_the_old_copy_and_no_temporary_file(self):
        m = self.stocked()
        before = sorted(os.listdir(self.lists))
        with mock.patch.object(weblists.os, "replace", side_effect=OSError("disk full")):
            report = m.update(Fake({PHISH_URL: ok(SAMPLE + b"new.example\n", etag='"v9"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
        self.assertEqual(sorted(os.listdir(self.lists)), before)
        self.assertIsNone(m.blocked("new.example"))
        self.assertIsNotNone(m.blocked("bad.example"))

    def test_a_stored_copy_that_was_changed_on_disk_is_not_trusted(self):
        self.stocked()
        with open(self.data("phishing_domains"), "a", encoding="utf-8") as f:
            f.write("tampered.example\n")
        m = self.matcher()
        self.assertIsNone(m.blocked("tampered.example"))
        self.assertIsNone(m.blocked("bad.example"))
        self.assertTrue(any("phishing_domains" in p for p in m.problems))
        report = m.update(Fake({PHISH_URL: webclient.FetchError("down"), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertTrue(report["stop"])        # a copy that cannot be trusted is no copy

    def test_a_stored_copy_that_is_a_link_is_not_read(self):
        self.stocked()
        path = self.data("phishing_domains")
        target = os.path.join(self.dir, "elsewhere.txt")
        os.rename(path, target)
        os.symlink(target, path)
        m = self.matcher()
        self.assertIsNone(m.blocked("bad.example"))
        self.assertTrue(m.problems)

    def test_the_plan_is_checked(self):
        m = self.matcher()
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)})
        bad_plans = [plan(unknown_key=1), plan(refresh_hours=0), plan(refresh_hours=-1), plan(list_min_share=1.5), plan(list_max_change=-0.1), plan(list_max_mb=0), plan(phishing_domains="maybe"),
                     plan(phishing_domains_url="ftp://x.example/list"), plan(phishing_domains_url="http://x.example:8080/list"), plan(public_suffix_url=""), plan(phishing_domains_format="xml"),
                     plan(pinned_hosts="openalex.org"), plan(pinned_hosts=["bad host"]), plan(urlhaus_keep_days=0), plan(refresh_hours=True)]
        for bad in bad_plans:
            with self.subTest(repr(bad)[-60:]):
                with self.assertRaises(weblists.ListError):
                    m.update(fake, T0, bad)
        self.assertEqual(fake.calls, [])
        with self.assertRaises(weblists.ListError):
            m.update(fake, "2026-11-16", plan())
        with self.assertRaises(weblists.ListError):
            m.update(fake, datetime.datetime(2026, 11, 16), plan())      # a time without a zone
        with self.assertRaises(weblists.ListError):
            m.update(fake, T0, "not a dict")

    def test_the_limits_may_be_zero_and_one_but_not_beyond_and_not_not_a_number(self):
        m = self.matcher()
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)})
        for good in (plan(list_min_share=0, list_max_change=0), plan(list_min_share=1, list_max_change=1), plan(phishing_domains="on"), plan(phishing_domains="off"), plan(urlhaus_recent="off")):
            m.update(fake, T0, good)
        for bad in (plan(list_min_share=float("nan")), plan(list_max_change=float("inf")), plan(list_max_mb=float("nan")), plan(refresh_hours=float("nan")), plan(refresh_hours="12"), plan(list_min_share="0.5")):
            with self.subTest(repr(bad)[-50:]):
                with self.assertRaises(weblists.ListError):
                    m.update(fake, T0, bad)

    def test_a_phishing_list_that_is_switched_off_by_text_is_off(self):
        m = self.matcher()
        fake = Fake({PSL_URL: ok(PSL)})
        report = m.update(fake, T0, plan(phishing_domains="off"))
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "off")
        self.assertEqual([c[0] for c in fake.calls], [PSL_URL])

    def test_the_folder_is_made_private_even_if_it_existed(self):
        os.makedirs(self.lists, mode=0o755)
        os.chmod(self.lists, 0o755)
        self.stocked()
        self.assertEqual(stat.S_IMODE(os.stat(self.lists).st_mode), 0o700)

    def test_a_304_with_no_copy_is_a_failure_and_a_304_is_remembered_by_the_next_process(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
        self.assertTrue(report["stop"])
        m = self.stocked()
        m.update(Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=12), plan())
        fake = Fake()
        self.matcher().update(fake, T0 + datetime.timedelta(hours=23), plan())       # a new process: the check at hour 12 was written down
        self.assertEqual(fake.calls, [])

    def test_a_download_that_is_not_bytes_is_a_failure(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: (200, {}, "some text"), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")

    def test_a_download_of_exactly_the_size_limit_is_taken_and_one_byte_more_is_not(self):
        limit = int(0.001 * 1024 * 1024)
        body = b"a.example\n" + b"#" * (limit - 10 - 1) + b"\n"
        self.assertEqual(len(body), limit)
        m = self.matcher()
        self.assertEqual(m.update(Fake({PHISH_URL: ok(body), PSL_URL: ok(PSL)}), T0, plan(list_max_mb=0.001))["lists"]["phishing_domains"]["status"], "updated")
        m2 = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "lists2"), [])
        self.assertEqual(m2.update(Fake({PHISH_URL: ok(body + b"#"), PSL_URL: ok(PSL)}), T0, plan(list_max_mb=0.001))["lists"]["phishing_domains"]["status"], "refused")

    def test_a_list_that_grows_too_much_is_refused_as_well(self):
        m = self.matcher()
        m.update(Fake({PHISH_URL: ok(hosts(100)), PSL_URL: ok(PSL)}), T0, plan())
        report = m.update(Fake({PHISH_URL: ok(hosts(150), etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIn("changed", report["lists"]["phishing_domains"]["reason"])
        report = m.update(Fake({PHISH_URL: ok(hosts(130), etag='"v3"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")

    def test_a_stored_copy_with_a_missing_data_file_or_a_bad_record_is_not_used(self):
        self.stocked()
        os.remove(self.data("phishing_domains"))
        m = self.matcher()
        self.assertTrue(any("data file is missing" in p for p in m.problems))
        self.assertIsNone(m.blocked("bad.example"))
        self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        for content in ("[]", '{"sha256": 5, "checked": "2026-11-16T12:00:00Z"}', "not json", '{"sha256": "abc", "checked": "yesterday"}', "{}"):
            with self.subTest(content):
                self.stocked()
                with open(meta, "w", encoding="utf-8") as f:
                    f.write(content)
                m = self.matcher()
                self.assertTrue(any("phishing_domains" in p for p in m.problems), m.problems)
                self.assertIsNone(m.blocked("bad.example"))

    def test_a_record_with_the_right_hash_but_an_unreadable_time_is_not_used(self):
        self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        info["checked"] = "yesterday"
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(info, f)
        m = self.matcher()
        self.assertTrue(any("record cannot be read" in p for p in m.problems), m.problems)
        report = m.update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())      # and the next update does not trip on it
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")

    def test_a_crash_between_the_new_data_and_the_new_record_leaves_the_old_copy_whole(self):
        m = self.stocked()
        real = os.replace
        calls = []

        def replace(src, dst):
            calls.append(dst)
            if dst.endswith(".meta.json"):
                raise OSError("power cut")
            return real(src, dst)

        with mock.patch.object(weblists.os, "replace", replace):
            report = m.update(Fake({PHISH_URL: ok(SAMPLE + b"new.example\n", etag='"v9"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
        again = self.matcher()
        self.assertEqual(again.problems, [])                      # the old record and the old data still agree
        self.assertIsNotNone(again.blocked("bad.example"))
        self.assertIsNone(again.blocked("new.example"))
        self.assertEqual([n for n in os.listdir(self.lists) if n.startswith(".")], [])
        self.assertEqual(len([n for n in os.listdir(self.lists) if n.startswith("phishing_domains.") and not n.endswith(".json")]), 1)    # the new data file was taken away again

    def test_a_failed_record_write_for_the_same_content_does_not_take_away_the_data_file_in_use(self):
        m = self.stocked()
        real = os.replace

        def replace(src, dst):
            if dst.endswith(".meta.json"):
                raise OSError("power cut")
            return real(src, dst)

        with mock.patch.object(weblists.os, "replace", replace):
            m.update(Fake({PHISH_URL: ok(SAMPLE, etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertTrue(os.path.exists(self.data("phishing_domains")))
        self.assertEqual(self.matcher().problems, [])

    def test_the_old_data_file_is_removed_once_the_new_record_is_in_place(self):
        m = self.stocked()
        old = self.data("phishing_domains")
        m.update(Fake({PHISH_URL: ok(SAMPLE + b"new.example\n", etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertNotEqual(self.data("phishing_domains"), old)
        self.assertFalse(os.path.exists(old))
        self.assertEqual(len([n for n in os.listdir(self.lists) if n.startswith("phishing_domains.") and not n.endswith(".json")]), 1)

    def test_a_record_cannot_name_a_file_outside_its_own_pattern(self):
        self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        for name in ("../elsewhere.txt", "/etc/passwd", "phishing_domains.txt", "public_suffix.0123456789abcdef.dat", "phishing_domains.0123456789abcdef.txt/../x", "", 5, None):
            with self.subTest(repr(name)):
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump({**info, "file": name}, f)
                m = self.matcher()
                self.assertTrue(any("phishing_domains" in p for p in m.problems), m.problems)
                self.assertIsNone(m.blocked("bad.example"))

    def test_a_record_that_names_a_file_with_the_right_content_elsewhere_is_still_not_used(self):
        self.stocked()
        planted = os.path.join(self.dir, "planted.txt")
        with open(planted, "wb") as f:
            f.write(SAMPLE)
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({**info, "file": "../planted.txt"}, f)
        m = self.matcher()
        self.assertTrue(any("record cannot be read" in p for p in m.problems), m.problems)
        self.assertIsNone(m.blocked("bad.example"))

    def test_a_download_with_the_same_content_keeps_its_data_file(self):
        m = self.stocked()
        before = self.data("phishing_domains")
        report = m.update(Fake({PHISH_URL: ok(SAMPLE, etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        self.assertEqual(self.data("phishing_domains"), before)
        self.assertTrue(os.path.exists(before))
        again = self.matcher()
        self.assertEqual(again.problems, [])
        self.assertIsNotNone(again.blocked("bad.example"))

    def test_a_suffix_list_that_cannot_be_read_back_is_not_used(self):
        self.stocked()
        with mock.patch.object(weblists.webaddr, "parse_suffixes", side_effect=webaddr.AddressError("too many rules")):
            m = self.matcher()
        self.assertTrue(any("public_suffix" in p for p in m.problems), m.problems)
        self.assertEqual(m.suffixes(), frozenset())

    def test_a_stored_copy_with_no_valid_entry_is_not_a_copy(self):
        self.stocked()
        body = b"only_underscores.example\n"
        digest = hashlib.sha256(body).hexdigest()
        name = f"phishing_domains.{digest[:16]}.txt"
        with open(os.path.join(self.lists, name), "wb") as f:
            f.write(body)
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({**info, "sha256": digest, "file": name}, f)
        m = self.matcher()
        self.assertTrue(any("no valid entry" in p for p in m.problems), m.problems)
        report = m.update(Fake({PHISH_URL: webclient.FetchError("down"), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertTrue(report["stop"])

    def test_a_record_that_makes_the_reader_raise_something_odd_is_just_not_used(self):
        self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        for content in (json.dumps({**info, "checked": 5}), "[" * 9000 + "]" * 9000, json.dumps({**info, "checked": None}), json.dumps({**info, "sha256": ["x"]})):
            with self.subTest(content[:30]):
                with open(meta, "w", encoding="utf-8") as f:
                    f.write(content)
                m = self.matcher()
                self.assertTrue(any("phishing_domains" in p for p in m.problems), m.problems)

    def test_a_stored_copy_with_too_many_lines_is_not_used_and_does_not_break_the_reload(self):
        self.stocked()
        with mock.patch.object(weblists, "MAX_LINES", 3):
            m = self.matcher()
        self.assertTrue(any("phishing_domains" in p for p in m.problems), m.problems)

    def test_reload_holds_the_lock_while_it_reads(self):
        m = self.stocked()
        seen = []
        real = m._load_stored
        m._load_stored = lambda: (seen.append(m._lock._is_owned()), real())[1]
        m.reload()
        self.assertEqual(seen, [True])

    def test_a_check_time_in_the_future_does_not_stop_the_refresh(self):
        m = self.stocked()
        fake = Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")})
        m.update(fake, T0 - datetime.timedelta(days=3), plan())     # the clock went back
        self.assertEqual(len(fake.calls), 2)

    def test_numbers_that_would_overflow_or_outgrow_what_can_be_read_back_are_refused(self):
        m = self.matcher()
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)})
        for bad in (plan(refresh_hours=float("inf")), plan(refresh_hours=24 * 366), plan(list_max_mb=float("inf")), plan(list_max_mb=251), plan(urlhaus_keep_days=float("inf")), plan(urlhaus_keep_days=3651)):
            with self.subTest(repr(bad)[-50:]):
                with self.assertRaises(weblists.ListError):
                    m.update(fake, T0, bad)
        m.update(fake, T0, plan(list_max_mb=250, refresh_hours=24 * 365, urlhaus_keep_days=3650))

    def test_set_urls_drops_what_is_not_one_address_to_a_line(self):
        m = self.matcher()
        count = m.set_urls("urlhaus_recent", ["http://a.example/x\nhttp://b.example/y", 5, None, "http://c.example/z", "not an address"])
        self.assertEqual(count, 1)
        self.assertIsNotNone(m.blocked("http://c.example/z"))
        self.assertIsNone(m.blocked("http://a.example/x"))
        self.assertIsNone(m.blocked("http://b.example/y"))

    def test_the_defaults_of_the_spec_apply_to_missing_keys(self):
        self.assertEqual(weblists.DEFAULTS["refresh_hours"], 12)
        self.assertEqual(weblists.DEFAULTS["list_max_mb"], 50)
        self.assertEqual(weblists.DEFAULTS["list_min_share"], 0.5)
        self.assertEqual(weblists.DEFAULTS["list_max_change"], 0.3)
        self.assertEqual(weblists.DEFAULTS["urlhaus_keep_days"], 30)
        self.assertEqual(weblists.DEFAULTS["phishing_domains"], True)
        self.assertEqual(weblists.DEFAULTS["urlhaus_recent"], False)
        self.assertEqual(weblists.DEFAULTS["phishing_domains_format"], "domains")
        self.assertEqual(weblists.DEFAULTS["public_suffix_url"], "https://publicsuffix.org/list/public_suffix_list.dat")
        self.assertEqual(weblists.DEFAULTS["phishing_domains_url"], "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt")
        self.assertEqual(weblists.DEFAULTS["pinned_hosts"], ["openalex.org", "arxiv.org", "wikipedia.org"])
        m = self.matcher()
        fake = Fake({weblists.DEFAULTS["phishing_domains_url"]: ok(SAMPLE), weblists.DEFAULTS["public_suffix_url"]: ok(PSL)})
        self.assertFalse(m.update(fake, T0, {})["stop"])
        self.assertEqual(len(fake.calls), 2)

    def test_the_pinned_hosts_of_the_plan_replace_those_the_matcher_was_made_with(self):
        m = self.stocked(pinned=())
        self.assertIsNotNone(m.blocked("openalex.org"))
        m.update(Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan(pinned_hosts=["openalex.org"]))
        self.assertIsNone(m.blocked("openalex.org"))

    def test_the_report_and_the_files_carry_no_list_text_beyond_counts_and_reasons(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        text = json.dumps(report)
        for word in ("bad.example", "sub.bad.example", "github.com"):
            self.assertNotIn(word, text)
        self.assertEqual(report["lists"]["phishing_domains"]["ignored"], 4)

    def test_a_reason_made_from_what_a_server_said_is_cleaned(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: webclient.FetchError("bad \x1b[31mred\x00 text " + "x" * 1000), PSL_URL: ok(PSL)}), T0, plan())
        reason = report["lists"]["phishing_domains"]["reason"]
        self.assertNotIn("\x1b", reason)
        self.assertNotIn("\x00", reason)
        self.assertLessEqual(len(reason), 300)

    def test_blocked_can_be_asked_while_an_update_runs(self):
        m = self.stocked()
        stop = threading.Event()
        errors = []

        def ask():
            while not stop.is_set():
                try:
                    block = m.blocked("bad.example")
                    if block is None or block.reason != "list:phishing_domains":
                        errors.append(block)
                except Exception as e:
                    errors.append(e)

        thread = threading.Thread(target=ask)
        thread.start()
        try:
            for n in range(5):
                m.update(Fake({PHISH_URL: ok(SAMPLE + f"n{n}.example\n".encode(), etag=f'"n{n}"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13 * (n + 1)), plan())
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual(errors, [])


class SecurityFixes(Files):
    """Faults found by the security review of Increment D, each shown by a test that failed before the fix."""

    def test_the_real_floors_are_a_good_deal_under_the_real_lists(self):
        self.assertEqual(REAL_FLOORS, {"phishing_domains": 100_000, "public_suffix": 5_000})    # the real lists: 391,548 hosts and 10,453 rules on 2026-11-16

    def test_a_first_copy_that_is_a_page_or_a_stub_is_refused_and_cannot_lock_the_real_list_out(self):
        with mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1000, "public_suffix": 1000}):
            for body in (b"ok\n", b"<html><body><h1>Login</h1>\nSorry\n</body></html>\n", hosts(999), b"login\nsearch\ncom\n" * 400):
                with self.subTest(body[:20]):
                    m = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, f"first{abs(hash(body))}"), [])
                    report = m.update(Fake({PHISH_URL: ok(body), PSL_URL: ok(PSL)}), T0, plan())
                    self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
                    self.assertTrue(report["stop"])
            m = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "real"), [])
            self.assertEqual(m.update(Fake({PHISH_URL: ok(hosts(1000)), PSL_URL: ok(PSL * 1)}), T0, plan())["lists"]["phishing_domains"]["status"], "updated")

    def test_a_list_that_is_mostly_not_hostnames_is_refused(self):
        body = b"".join(f"not_a_host_{i}\n".encode() for i in range(30)) + hosts(10)
        report = self.matcher().update(Fake({PHISH_URL: ok(body), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")
        self.assertIn("not hostnames", report["lists"]["phishing_domains"]["reason"])

    def test_a_list_that_is_exactly_half_not_hostnames_is_taken_and_one_more_line_is_not(self):
        valid = hosts(10)
        junk = lambda n: b"".join(f"junk_{i}\n".encode() for i in range(n))
        m = self.matcher()
        self.assertEqual(m.update(Fake({PHISH_URL: ok(valid + junk(10)), PSL_URL: ok(PSL)}), T0, plan())["lists"]["phishing_domains"]["status"], "updated")
        m2 = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "l2"), [])
        self.assertEqual(m2.update(Fake({PHISH_URL: ok(valid + junk(11)), PSL_URL: ok(PSL)}), T0, plan())["lists"]["phishing_domains"]["status"], "refused")

    def test_a_record_that_is_gone_or_a_damaged_suffix_list_does_not_switch_off_what_is_in_use(self):
        m = self.stocked()
        os.remove(os.path.join(self.lists, "phishing_domains.meta.json"))
        m.reload()
        self.assertIsNotNone(m.blocked("bad.example"))
        record = os.path.join(self.lists, "public_suffix.meta.json")
        data = self.data("public_suffix")
        shutil.copy(record, record + ".saved")
        os.remove(record)
        m.reload()
        self.assertTrue(m.suffixes())                       # the record is gone, the rules in use stay
        shutil.move(record + ".saved", record)
        with open(data, "ab") as f:
            f.write(b"tampered\n")
        before = m.suffixes()
        m.reload()
        self.assertTrue(before)
        self.assertEqual(m.suffixes(), before)
        self.assertTrue(any("public_suffix" in p for p in m.problems), m.problems)

    def test_the_stored_suffix_list_is_parsed_from_the_bytes_that_were_checked(self):
        self.stocked()
        with mock.patch.object(weblists.webaddr, "load_suffixes", side_effect=AssertionError("read the file a second time")):
            m = self.matcher()
        self.assertTrue(m.suffixes())
        self.assertEqual(m.problems, [])

    def test_a_name_with_no_dot_is_not_a_host_entry(self):
        found, ignored = weblists.parse_domains("com\nlogin\nok.example\n203.0.113.5\n2001:db8::1\n")
        self.assertEqual(found, {"ok.example", "203.0.113.5", "2001:db8::1"})
        self.assertEqual(ignored, 2)

    def test_a_damaged_stored_copy_does_not_unblock_what_is_in_use(self):
        m = self.stocked()
        with open(self.data("phishing_domains"), "a", encoding="utf-8") as f:
            f.write("tampered.example\n")
        m.reload()
        self.assertTrue(any("phishing_domains" in p for p in m.problems), m.problems)
        self.assertIsNotNone(m.blocked("bad.example"))               # the copy in use stays
        report = m.update(Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertFalse(report["stop"])
        with mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1000}):
            report = m.update(Fake({PHISH_URL: ok(hosts(5000, "x"), etag='"v9"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=26), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "refused")     # still held to the rules of a replacement
        self.assertIsNotNone(m.blocked("bad.example"))

    def test_the_lists_folder_must_be_a_real_folder_of_ours_and_is_not_followed(self):
        elsewhere = os.path.join(self.dir, "elsewhere")
        os.mkdir(elsewhere)
        os.chmod(elsewhere, 0o755)
        os.symlink(elsewhere, self.lists)
        m = self.matcher()
        with self.assertRaises(weblists.ListError):
            m.update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(stat.S_IMODE(os.stat(elsewhere).st_mode), 0o755)
        self.assertEqual(os.listdir(elsewhere), [])
        os.remove(self.lists)
        with open(self.lists, "w") as f:
            f.write("a file")
        with self.assertRaises(weblists.ListError):
            self.matcher().update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())

    def test_a_folder_that_belongs_to_someone_else_is_refused(self):
        os.mkdir(self.lists)
        real = os.lstat

        def lstat(path, *a, **k):
            info = real(path, *a, **k)
            if path == self.lists:
                return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, os.getuid() + 1, info.st_gid, info.st_size, info.st_atime, info.st_mtime, info.st_ctime))
            return info

        with mock.patch.object(weblists.os, "lstat", lstat):
            with self.assertRaises(weblists.ListError):
                self.matcher().update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())

    def test_a_folder_of_ours_with_a_loose_mode_is_tightened_and_a_missing_one_is_made(self):
        os.mkdir(self.lists)
        os.chmod(self.lists, 0o777)
        self.matcher().update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(stat.S_IMODE(os.stat(self.lists).st_mode), 0o700)
        deep = os.path.join(self.dir, "a", "b", "lists")
        weblists.Matcher(self.black, self.allow, deep, []).update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(stat.S_IMODE(os.stat(deep).st_mode), 0o700)

    def test_two_writers_do_not_share_a_temporary_name(self):
        names = []
        real = weblists.Matcher._write_file

        def spy(self_, path, data):
            names.append(os.path.basename(path))
            return real(self_, path, data)

        with mock.patch.object(weblists.Matcher, "_write_file", spy):
            self.stocked()
            self.stocked()
        temps = [n for n in names if n.startswith(".")]
        self.assertEqual(len(temps), len(set(temps)))
        self.assertTrue(all(len(n) > 24 for n in temps))

    def test_a_list_address_must_be_https_and_the_downloader_gets_the_canonical_form(self):
        m = self.matcher()
        for bad in ("http://lists.example/phish.txt", "HTTP://lists.example/phish.txt"):
            with self.assertRaises(weblists.ListError):
                m.update(Fake(), T0, plan(phishing_domains_url=bad))
        fake = Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)})
        m.update(fake, T0, plan(phishing_domains_url="HTTPS://Lists.Example./phishing-domains-ACTIVE.txt#top"))
        self.assertEqual([c[0] for c in fake.calls], [PHISH_URL, PSL_URL])

    def test_a_scheme_is_never_read_as_a_host(self):
        self.write(self.black, "http\nfile\nx\n")
        m = self.matcher()
        for text in ("http:/evil.example", "https:/evil.example", "file:/etc/passwd", "javascript:/x", "http:", "x:/evil.example", "HTTP:evil.example/", "a-b.c:/p"):
            with self.subTest(text):
                self.assertEqual(m.blocked(text).reason, "unusable")
        self.assertIsNone(m.blocked("evil.example:80"))                   # a host and a port is still read
        self.assertIsNone(m.blocked("evil.example:80/path"))
        self.assertEqual(m.blocked("http.example.com"), None)

    def test_a_stored_validator_that_is_not_plain_is_not_sent(self):
        m = self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        info["etag"] = '"a"\r\nX-Evil: 1'
        info["last_modified"] = "x" * 5000
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(info, f)
        m = self.matcher()
        fake = Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")})
        report = m.update(fake, T0 + datetime.timedelta(hours=13), plan())
        sent = dict((c[0], c[1]) for c in fake.calls)
        self.assertEqual(sent[PHISH_URL], {})
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")        # a 304 to a request with no validator is not believed

    def test_a_304_to_a_request_that_sent_no_validator_is_not_believed(self):
        m = self.stocked()
        meta = os.path.join(self.lists, "phishing_domains.meta.json")
        with open(meta, encoding="utf-8") as f:
            info = json.load(f)
        info["etag"] = None
        info["last_modified"] = None
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(info, f)
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
        self.assertIn("validator", report["lists"]["phishing_domains"]["reason"])

    def test_orphan_data_files_are_swept_when_a_new_copy_is_installed(self):
        m = self.stocked()
        orphan = os.path.join(self.lists, "phishing_domains.0123456789abcdef.txt")
        other = os.path.join(self.lists, "public_suffix.0123456789abcdef.dat")
        stray = os.path.join(self.lists, "notes.txt")
        for path in (orphan, other, stray):
            with open(path, "w") as f:
                f.write("x")
        m.update(Fake({PHISH_URL: ok(SAMPLE + b"new.example\n", etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertFalse(os.path.exists(orphan))
        self.assertTrue(os.path.exists(other))           # another list's file is left to that list
        self.assertTrue(os.path.exists(stray))           # and a file that is not a list's is not touched

    def test_a_download_whose_headers_are_not_a_dict_or_that_makes_the_parser_raise_is_a_failed_list(self):
        m = self.matcher()
        report = m.update(Fake({PHISH_URL: (200, ["etag", "x"], SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        m2 = weblists.Matcher(self.black, self.allow, os.path.join(self.dir, "l2"), [])
        with mock.patch.object(weblists, "parse_domains", side_effect=RuntimeError("boom")):
            report = m2.update(Fake({PHISH_URL: ok(SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")

    def test_a_stored_copy_under_the_floor_is_not_used_and_is_reported(self):
        self.stocked()
        with mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 10_000}):
            m = self.matcher()
        self.assertTrue(any("fewer than" in p for p in m.problems), m.problems)
        self.assertIsNone(m.blocked("bad.example"))

    def test_the_sweep_keeps_the_data_file_that_the_record_on_disk_names(self):
        a = self.stocked()
        other = weblists.Matcher(self.black, self.allow, self.lists, [])
        real_sweep = a._sweep

        def sweep(name, keep):
            # another process installs a newer copy between this one's install and its sweep
            other.update(Fake({PHISH_URL: ok(SAMPLE + b"theirs.example\n", etag='"v3"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=40), plan())
            return real_sweep(name, keep)

        a._sweep = sweep
        a.update(Fake({PHISH_URL: ok(SAMPLE + b"mine.example\n", etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        fresh = self.matcher()
        self.assertEqual(fresh.problems, [])
        self.assertTrue(os.path.exists(self.data("phishing_domains")))

    def test_old_temporary_files_are_swept_and_young_ones_are_left_alone(self):
        m = self.stocked()
        old = os.path.join(self.lists, ".phishing_domains.data.0123456789ab.new")
        young = os.path.join(self.lists, ".phishing_domains.meta.json.ba9876543210.new")
        other = os.path.join(self.lists, ".notes.new")
        for path in (old, young, other):
            with open(path, "w") as f:
                f.write("x")
        long_ago = time.time() - 7200
        os.utime(old, (long_ago, long_ago))
        os.utime(other, (long_ago, long_ago))
        recent = time.time() - 1800
        os.utime(young, (recent, recent))
        m.update(Fake({PHISH_URL: ok(SAMPLE + b"new.example\n", etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=13), plan())
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))       # it may belong to a writer that is still at work
        self.assertTrue(os.path.exists(other))       # not a temporary file of a list

    def test_a_304_is_not_believed_when_the_stored_copy_is_gone_and_no_validator_is_sent_then(self):
        m = self.stocked()
        os.remove(self.data("phishing_domains"))
        fake = Fake({PHISH_URL: (304, {}, b""), PSL_URL: (304, {}, b"")})
        report = m.update(fake, T0 + datetime.timedelta(hours=13), plan())
        self.assertEqual(dict((c[0], c[1]) for c in fake.calls)[PHISH_URL], {})      # asked for the whole list again
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")
        self.assertIsNotNone(m.blocked("bad.example"))                               # the copy in memory still serves
        report = m.update(Fake({PHISH_URL: ok(SAMPLE, etag='"v2"'), PSL_URL: (304, {}, b"")}), T0 + datetime.timedelta(hours=26), plan())
        self.assertEqual(report["lists"]["phishing_domains"]["status"], "updated")
        self.assertEqual(self.matcher().problems, [])

    def test_a_record_and_data_that_vanish_are_reported(self):
        m = self.stocked()
        os.remove(os.path.join(self.lists, "phishing_domains.meta.json"))
        m.reload()
        self.assertTrue(any("phishing_domains" in p and "missing" in p for p in m.problems), m.problems)
        self.assertIsNotNone(m.blocked("bad.example"))

    def test_a_folder_that_is_not_ours_is_not_read(self):
        self.stocked()
        real = os.lstat

        def lstat(path, *a, **k):
            info = real(path, *a, **k)
            if path == self.lists:
                return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink, os.getuid() + 1, info.st_gid, info.st_size, info.st_atime, info.st_mtime, info.st_ctime))
            return info

        with mock.patch.object(weblists.os, "lstat", lstat):
            m = self.matcher()
        self.assertTrue(any("folder" in p for p in m.problems), m.problems)
        self.assertIsNone(m.blocked("bad.example"))

    def test_a_status_that_is_not_a_number_is_a_failed_list(self):
        class Odd:
            def __str__(self):
                raise RuntimeError("no")

        for status in (Odd(), None, "200", True, 200.0):
            with self.subTest(repr(status)[:20]):
                report = self.matcher().update(Fake({PHISH_URL: (status, {}, SAMPLE), PSL_URL: ok(PSL)}), T0, plan())
                self.assertEqual(report["lists"]["phishing_domains"]["status"], "failed")

    def test_a_pinned_host_with_no_dot_is_refused_and_so_are_tiny_intervals(self):
        for bad in (["com"], ["openalex.org", "org"], ["localhost"]):
            with self.assertRaises(weblists.ListError):
                weblists.Matcher(self.black, self.allow, self.lists, bad)
        m = self.matcher()
        for bad in (plan(refresh_hours=0.5), plan(refresh_hours=1e-300), plan(list_max_mb=1e-300), plan(list_max_mb=0.0005), plan(pinned_hosts=["com"])):
            with self.subTest(repr(bad)[-40:]):
                with self.assertRaises(weblists.ListError):
                    m.update(Fake(), T0, bad)

    def test_an_unknown_plan_key_is_named_without_its_control_characters(self):
        with self.assertRaises(weblists.ListError) as caught:
            self.matcher().update(Fake(), T0, plan(**{"bad\x1b[31mkey\x00": 1}))
        self.assertNotIn("\x1b", str(caught.exception))
        self.assertNotIn("\x00", str(caught.exception))


class Contract(unittest.TestCase):
    def test_the_module_makes_no_request_itself(self):
        with open(os.path.join(ENGINE_DIR, "kb", "weblists.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("import socket", "urllib.request", "http.client", "import ssl", "urlopen", "subprocess", "import requests", "webclient"):
            self.assertNotIn(word, source, word)


if __name__ == "__main__":
    unittest.main()
