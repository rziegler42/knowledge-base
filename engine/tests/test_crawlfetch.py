"""The policy of a fetch of the unattended crawl (`kb/crawlfetch.py`, Increment F of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

`crawlfetch.build` makes the one `webclient.Policy` under which every candidate is fetched, from the approved plan, the matcher and the Public Suffix List that the `lists` step left; `crawlfetch.classify` says what
a failed fetch was (a block by the policy, a refusal by the site, a candidate to reject, or a failure). These tests run the real shared client (`webclient.get`, and `capture_url.capture` for the capture) against the
fake resolver and the fake server of `test_webclient`; nothing here touches the real network.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch`."""
import datetime
import json
import os
import socket
import tempfile
import threading
import types
import unittest
from urllib.parse import urlsplit
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests import test_crawllists, test_crawlrefill
from engine.tests.test_capture_policy import PAGE
from engine.tests.test_discover import Source
from engine.tests.test_store import StoreCase, make_writable
from engine.tests.test_weblists import Fake, ok as list_ok, plan as lists_plan
from engine.tests.test_webclient import PRIVATE, Net, PeerSock, redirect, reply

from kb import KbError, capture_url, crawlbooks, crawlfetch, crawlguard, crawllog, crawlplan, crawlqueue, crawlrefill, crawlrun, crawlstate, identity, library, store, webclient, weblists
from kb.capture_url import FetchError

NOW = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.timezone.utc)
SUFFIXES = frozenset({"com", "org", "uk", "co.uk", "test", "example"})
ALL_PUBLIC = "93.184.216.34"


class Case(Net):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)
        self.index = os.path.join(self.dir, "index")
        os.makedirs(os.path.join(self.index, "crawl"), mode=0o700)
        for name in ("evil.example", "www.evil.example", "notevil.example", "listed.example", "other.listed.example", "urlhost.example", "pinned.example", "ok.example", "xn--bcher-kva.example", "flip.test"):
            self.dns.setdefault(name, [ALL_PUBLIC])
        self.black = os.path.join(self.dir, "black.txt")
        self.allow = os.path.join(self.dir, "allow.txt")
        for path, text in ((self.black, "evil.example\nbücher.example\n"), (self.allow, "")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(path, 0o600)
        lists = os.path.join(self.dir, "lists")
        weblists.ensure_private_dir(lists)
        floors = mock.patch.dict(weblists.MIN_ENTRIES, {"phishing_domains": 1, "public_suffix": 1})
        floors.start()
        self.addCleanup(floors.stop)
        self.matcher = weblists.Matcher(self.black, self.allow, lists, ["pinned.example"])
        feed = b"listed.example\npinned.example\n"
        report = self.matcher.update(Fake({"https://lists.example/phishing-domains-ACTIVE.txt": list_ok(feed), "https://lists.example/public_suffix_list.dat": list_ok(b"com\nuk\nco.uk\ntest\nexample\n")}),
                                     NOW, lists_plan())
        self.assertFalse(report["stop"], report)
        self.matcher.set_urls("urlhaus_recent", ["http://urlhost.example/bad/page", "http://10.9.9.9/x"])
        self.plan = dict(crawlplan.defaults(), min_gap_s=0, jitter=0, fetch_timeout_s=20)

    def build(self, **plan):
        return crawlfetch.build(dict(self.plan, **plan), self.matcher, SUFFIXES, self.index)

    def fetch(self, address, fp=None, **kw):
        fp = fp or self.build()
        return webclient.get(address, policy=fp.policy, max_bytes=fp.max_bytes, timeout=fp.timeout, total_timeout=fp.total_timeout, **kw)

    def page(self, path="/p", body=b"<html><body>hello</body></html>", **kw):
        self.srv.routes[path] = reply(200, body=body, **kw)


class Fields(Case):
    def test_the_policy_has_the_plans_pacing_limits_and_the_page_types_and_no_credential(self):
        fp = self.build(min_gap_s=7, jitter=1.5, fetch_timeout_s=33)
        p = fp.policy
        self.assertEqual((p.gap, p.jitter, p.max_redirects, p.follow_redirects), (7, 1.5, 5, True))
        self.assertEqual(p.types, ("text/html", "application/xhtml+xml"))
        self.assertEqual((p.allow_private, p.credential_headers, p.credential_host, p.headers), (False, None, None, None))
        self.assertEqual(p.suffixes, SUFFIXES)
        self.assertTrue(callable(p.check))
        self.assertEqual((fp.total_timeout, fp.max_bytes), (33, crawlfetch.PAGE_MAX_BYTES))
        self.assertEqual(fp.timeout, capture_url.TIMEOUT)                   # one network operation: the capture's own limit, never over the whole time of a hop
        self.assertEqual(self.build(fetch_timeout_s=4).timeout, 4)
        self.assertEqual(crawlfetch.PAGE_MAX_BYTES, capture_url.MAX_BYTES)

    def test_the_user_agent_is_the_plans_choice_a_common_browsers_or_the_honest_generic_one(self):
        self.assertEqual(self.build(user_agent="browser").policy.user_agent, crawlfetch.BROWSER_AGENT)
        self.assertEqual(self.build(user_agent="generic").policy.user_agent, webclient.GENERIC_USER_AGENT)
        self.assertTrue(crawlfetch.BROWSER_AGENT.startswith("Mozilla/5.0 ("))
        self.assertNotIn("knowledge-base", crawlfetch.BROWSER_AGENT)
        self.page()
        self.fetch("http://a.test/p", self.build(user_agent="browser"))
        self.assertEqual(self.srv.hits[-1][1]["user-agent"], crawlfetch.BROWSER_AGENT)

    def test_a_user_agent_that_is_neither_is_refused(self):
        for bad in ("Mozilla/5.0", "", None, 3):
            with self.subTest(bad), self.assertRaises(KbError):
                self.build(user_agent=bad)

    def test_a_plan_with_a_missing_or_wrong_value_is_refused_and_a_matcher_is_required(self):
        for key, bad in (("min_gap_s", -1), ("min_gap_s", "8"), ("jitter", None), ("fetch_timeout_s", 0), ("fetch_timeout_s", True), ("min_gap_s", float("nan")), ("min_gap_s", True), ("jitter", False), ("fetch_timeout_s", 2.5)):
            with self.subTest((key, bad)), self.assertRaises(KbError):
                self.build(**{key: bad})
        with self.assertRaises(KbError):
            crawlfetch.build(self.plan, None, SUFFIXES, self.index)
        with self.assertRaises(KbError):
            crawlfetch.build({k: v for k, v in self.plan.items() if k != "fetch_timeout_s"}, self.matcher, SUFFIXES, self.index)

    def test_a_missing_public_suffix_list_is_said_loudly_and_the_policy_still_works_with_the_fallback(self):
        said, lines = [], []
        log = type("L", (), {"write": lambda self, *a, **k: lines.append((a, k)), "safe": staticmethod(lambda t, f=None: t)})()
        for none in (None, frozenset(), ()):
            said.clear()
            lines.clear()
            fp = crawlfetch.build(self.plan, self.matcher, none, self.index, log=log, warn=said.append, now=NOW)
            self.assertIsNone(fp.policy.suffixes)
            self.assertTrue(said and "Public Suffix List" in said[0])
            self.assertEqual(lines[0][0][:2], ("list_update", "failed"))
        said.clear()
        lines.clear()
        crawlfetch.build(self.plan, self.matcher, SUFFIXES, self.index, log=log, warn=said.append, now=NOW)
        self.assertEqual((said, lines), ([], []))


class Pacing(Case):
    def test_the_gap_and_the_jitter_are_kept_between_two_requests_to_one_site(self):
        slept, clock = [], [100.0]
        pacer = webclient.Pacer(clock=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)), rng=mock.Mock(uniform=lambda a, b: b))
        fp = crawlfetch.build(dict(self.plan, min_gap_s=8, jitter=2), self.matcher, SUFFIXES, self.index, pacer=pacer)
        self.page()
        self.fetch("http://a.test/p", fp)
        self.fetch("http://www.a.test/p", fp)                       # the same registrable domain
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], 8)
        self.assertLessEqual(slept[0], 10 + 1e-6)

    def test_one_request_at_a_time_goes_to_a_registrable_domain_and_to_an_address(self):
        def slow(conn, path, headers):
            threading.Event().wait(0.15)
            return reply(200, body=b"<html>x</html>")

        self.srv.routes["/s"] = slow
        fp = self.build()
        for names in (("a.test", "www.a.test"), ("a.test", "alias.test")):         # one domain; two names for one address
            self.srv.max_inflight = 0
            threads = [threading.Thread(target=self.fetch, args=(f"http://{h}/s", fp)) for h in names]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(self.srv.max_inflight, 1, names)


class MatcherAtEveryHop(Case):
    def refused(self, address, fp=None):
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch(address, fp)
        return str(caught.exception)

    def test_the_owners_blacklist_blocks_a_host_and_its_subdomains_and_not_a_similar_name(self):
        for h in ("evil.example", "www.evil.example"):
            self.assertIn("owner", self.refused(f"http://{h}/p"))
        self.assertEqual(self.dials, [])
        self.page()
        self.assertEqual(self.fetch("http://notevil.example/p")[0], 200)

    def test_a_public_host_list_blocks_that_exact_host_only(self):
        self.assertIn("list:", self.refused("http://listed.example/p"))
        self.page()
        self.assertEqual(self.fetch("http://other.listed.example/p")[0], 200)

    def test_a_url_list_blocks_that_url_and_not_others_on_its_host_unless_the_host_is_a_bare_ip(self):
        self.assertIn("list:", self.refused("http://urlhost.example/bad/page"))
        self.page("/other")
        self.assertEqual(self.fetch("http://urlhost.example/other")[0], 200)
        self.assertIn("list:", self.refused("http://10.9.9.9/anything"))

    def test_a_pinned_source_host_is_never_blocked_by_a_public_list_but_is_by_the_owners_blacklist(self):
        self.page()
        self.assertEqual(self.fetch("http://pinned.example/p")[0], 200)
        with open(self.black, "a", encoding="utf-8") as f:
            f.write("pinned.example\n")
        self.matcher.reload()
        self.assertIn("owner", self.refused("http://pinned.example/p"))

    def test_a_canonical_form_of_a_blocked_host_is_the_same_key(self):
        for form in ("http://EVIL.example./p", "http://Evil.Example/p#frag", "http://www.EVIL.example./p", "http://xn--bcher-kva.example/p", "http://bücher.example/p"):
            with self.subTest(form):
                self.assertIn("owner", self.refused(form))
        self.assertEqual(self.dials, [])

    def test_a_redirect_to_a_blocked_host_is_refused_at_that_hop_and_nothing_is_dialled_for_it(self):
        for target in ("http://evil.example/x", "http://listed.example/x", "http://urlhost.example/bad/page"):
            with self.subTest(target):
                self.srv.routes["/go"] = redirect(target)
                before = len(self.dials)
                self.assertRaises(webclient.Refused, self.fetch, "http://a.test/go")
                self.assertEqual(len(self.dials), before + 1)                        # the first hop only

    def test_every_rule_is_applied_at_a_redirect_hop_with_its_reason_and_a_similar_name_goes_through(self):
        blocked = (("http://EVIL.example./x", "owner"), ("http://sub.evil.example/x", "owner"), ("http://xn--bcher-kva.example/x", "owner"), ("http://listed.example/x", "list:"),
                   ("http://urlhost.example/bad/page", "list:"), ("http://93.184.216.99/anything", "list:"))
        self.matcher.set_urls("urlhaus_recent", ["http://urlhost.example/bad/page", "http://93.184.216.99/x"])
        for target, why in blocked:
            with self.subTest(target):
                self.srv.routes["/go"] = redirect(target)
                before = len(self.dials)
                with self.assertRaises(webclient.Refused) as caught:
                    self.fetch("http://a.test/go")
                self.assertIn(why, str(caught.exception))
                self.assertEqual(len(self.dials), before + 1)
        self.page("/x")
        for target in ("http://notevil.example/x", "http://other.listed.example/x", "http://urlhost.example/x", "http://pinned.example/x"):
            with self.subTest(target):
                self.srv.routes["/go"] = redirect(target)
                self.assertEqual(self.fetch("http://a.test/go")[0], 200)
        with open(self.black, "a", encoding="utf-8") as f:
            f.write("pinned.example\n")
        self.matcher.reload()
        self.srv.routes["/go"] = redirect("http://pinned.example/x")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/go")
        self.assertIn("owner", str(caught.exception))

    def test_an_address_found_by_discovery_gets_the_same_verdict_from_the_same_matcher(self):
        fp = self.build()
        for address in ("http://EVIL.example./p", "http://www.evil.example/x", "http://listed.example/x", "http://urlhost.example/bad/page", "http://10.9.9.9/z"):
            self.assertTrue(self.matcher.blocked(address), address)
            self.assertIsNotNone(fp.policy.check(address), address)
        for address in ("http://notevil.example/x", "http://other.listed.example/x", "http://urlhost.example/other", "http://pinned.example/x"):
            self.assertFalse(self.matcher.blocked(address), address)
            self.assertIsNone(fp.policy.check(address), address)


class Connection(Case):
    def test_a_host_that_resolves_to_a_private_loopback_link_local_or_metadata_address_is_refused_at_the_first_hop(self):
        for name in PRIVATE:
            with self.subTest(name):
                self.assertRaises(webclient.Refused, self.fetch, f"http://{name}/p")
        self.assertEqual(self.dials, [])

    def test_a_redirect_to_a_private_address_is_refused_at_that_hop(self):
        for name in PRIVATE:
            with self.subTest(name):
                self.srv.routes["/go"] = redirect(f"http://{name}/p")
                before = len(self.dials)
                self.assertRaises(webclient.Refused, self.fetch, "http://a.test/go")
                self.assertEqual(len(self.dials), before + 1)

    def test_an_answer_that_changes_between_the_check_and_the_connect_is_harmless_because_the_checked_address_is_dialled(self):
        self.page()
        real = webclient.resolve_checked
        calls = []

        def flipping(host, port, allow_private):
            found = real(host, port, allow_private)
            calls.append(host)
            self.dns["flip.test"] = ["10.0.0.5"]                    # every later lookup says private
            return found

        with mock.patch.object(webclient, "resolve_checked", flipping):
            self.assertEqual(self.fetch("http://flip.test/p")[0], 200)
        self.assertEqual(self.dials, [(ALL_PUBLIC, 80)])

    def test_a_connected_peer_that_is_not_the_checked_address_is_refused(self):
        def dial(address, timeout):
            sock = PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), "10.0.0.5")
            self.socks.append(sock)
            return sock

        self.page()
        with mock.patch.object(webclient, "_dial", dial), self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/p")
        self.assertIn("did not reach the address that was checked", str(caught.exception))

    def test_only_ports_80_and_443_are_fetched_and_a_candidate_with_another_is_refused_before_a_dial(self):
        for address in ("http://a.test:8080/p", "http://a.test:22/p", "https://a.test:8443/p", "ftp://a.test/p", "file:///etc/passwd", "http://user:pw@a.test/p"):
            with self.subTest(address):
                self.assertRaises(webclient.Refused, self.fetch, address)
        self.assertEqual(self.dials, [])

    def test_at_most_five_redirects_are_followed(self):
        for i in range(5):
            self.srv.routes[f"/r{i}"] = redirect(f"http://a.test/r{i + 1}")
        self.page("/r5")
        self.assertEqual(self.fetch("http://a.test/r0")[0], 200)                     # five hops, then the page
        for i in range(6):
            self.srv.routes[f"/q{i}"] = redirect(f"http://a.test/q{i + 1}")
        self.page("/q6")
        self.assertRaises(webclient.Refused, self.fetch, "http://a.test/q0")          # six hops


class Shared(Case):
    """The same client, with the same guarantees, is the one that capture, discovery and the list refresh use."""

    def test_the_capture_of_a_candidate_through_the_policy_refuses_a_private_address_and_makes_no_book(self):
        class Holder(StoreCase):
            def runTest(self):
                pass

        holder = Holder()
        holder.setUp()
        self.addCleanup(holder.tearDown)
        ident = identity.Identity(holder.index)
        fp = self.build()
        with self.assertRaises(webclient.Refused):
            capture_url.capture(holder.store, ident, "http://internal.test/p", policy=fp.policy, types=fp.policy.types, auto_filed=True)
        self.assertEqual(holder.store.list_books(), [])
        self.assertEqual(self.dials, [])
        self.page(body=PAGE)
        result = capture_url.capture(holder.store, ident, "http://a.test/p", policy=fp.policy, types=fp.policy.types, auto_filed=True, max_bytes=fp.max_bytes)
        self.assertEqual(result["status"], "filed")
        self.assertEqual(self.srv.hits[-1][1]["user-agent"], fp.policy.user_agent)

    def test_the_policy_of_a_fetch_is_the_one_client_with_no_private_address_allowed(self):
        fp = self.build()
        self.assertIs(fp.policy.allow_private, False)
        for address in ("http://10.0.0.5/p", "http://127.0.0.1/p", "http://169.254.169.254/p", "http://[::1]/p", "http://[fe80::1]/p"):
            with self.subTest(address), self.assertRaises(webclient.Refused):
                self.fetch(address, fp)
        self.assertEqual(self.dials, [])


class TypeGate(Case):
    def test_a_page_and_an_xhtml_page_are_taken(self):
        self.page()
        self.page("/x", ctype="application/xhtml+xml; charset=utf-8")
        self.assertEqual(self.fetch("http://a.test/p")[0], 200)
        self.assertEqual(self.fetch("http://a.test/x")[0], 200)

    def test_a_response_with_no_content_type_or_another_type_or_a_body_that_disagrees_with_its_type_is_refused(self):
        self.page("/none", ctype=None)
        self.page("/json", ctype="application/json", body=b"{}")
        self.page("/lie", body=b"%PDF-1.7\n1 0 obj")
        self.page("/zip", body=b"PK\x03\x04binary")
        self.page("/nul", body=b"<html>\x00\x00</html>")
        for path in ("/none", "/json", "/lie", "/zip", "/nul"):
            with self.subTest(path):
                self.assertRaises(webclient.Refused, self.fetch, f"http://a.test{path}")

    def test_a_pdf_is_refused_with_the_reason_pdf_not_safe_to_convert(self):
        self.srv.routes["/doc"] = reply(200, body=b"%PDF-1.7\nbody", ctype="application/pdf")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/doc")
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason), ("rejected", "pdf not safe to convert"))

    def test_a_page_whose_bytes_disagree_with_its_type_is_rejected_as_not_a_web_page(self):
        for path, body in (("/lie", b"%PDF-1.7\nbody"), ("/zip", b"PK\x03\x04binary"), ("/nul", b"<html>\x00</html>")):
            with self.subTest(path):
                self.srv.routes[path] = reply(200, body=body, ctype="text/html")
                with self.assertRaises(webclient.Refused) as caught:
                    self.fetch(f"http://a.test{path}")
                got = crawlfetch.classify(caught.exception)
                self.assertEqual((got.kind, got.reason, got.retry), ("rejected", "not a web page", False))
        self.srv.routes["/none"] = reply(200, body=b"<html></html>", ctype=None)
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/none")
        self.assertEqual(crawlfetch.classify(caught.exception).kind, "rejected")

    def test_a_page_over_the_size_limit_is_rejected_and_not_retried(self):
        self.page("/big", body=b"<html>" + b"x" * 5000 + b"</html>")
        fp = self.build()
        fp.max_bytes = 1000
        with self.assertRaises(FetchError) as caught:
            self.fetch("http://a.test/big", fp)
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason), ("rejected", "over the size limit"))
        self.assertFalse(got.retry)

    def test_a_page_that_takes_too_long_is_a_failure_that_may_be_tried_again(self):
        self.srv.routes["/slow"] = lambda conn, path, headers: threading.Event().wait(3)
        fp = self.build(fetch_timeout_s=1)
        fp.timeout = 0.3
        with self.assertRaises(FetchError) as caught:
            self.fetch("http://a.test/slow", fp)
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason, got.retry), ("failed", "timed out", True))


class Classify(Case):
    def classify_status(self, status):
        self.srv.routes["/s"] = reply(status, body=b"no")
        with self.assertRaises(FetchError) as caught:
            capture_url.policy_fetch(self.build().policy, "http://a.test/s", 100_000, 3, 5)
        return crawlfetch.classify(caught.exception)

    def test_a_refusal_by_a_site_is_a_refusal_for_the_caller_and_not_a_failure(self):
        for status in (401, 403, 429, 451):
            with self.subTest(status):
                got = self.classify_status(status)
                self.assertEqual((got.kind, got.reason, got.retry), ("refused", f"the site refused (HTTP {status})", False))

    def test_other_statuses_are_failures_and_say_the_status(self):
        for status in (404, 410, 500, 502, 503):
            with self.subTest(status):
                got = self.classify_status(status)
                self.assertEqual((got.kind, got.reason, got.retry), ("failed", f"HTTP {status}", True))

    def test_a_block_by_the_policy_is_blocked_and_says_who_blocked_it(self):
        for address, reason in (("http://evil.example/p", "owner"), ("http://listed.example/p", "list")):
            with self.subTest(address), self.assertRaises(webclient.Refused) as caught:
                self.fetch(address)
            got = crawlfetch.classify(caught.exception)
            self.assertEqual(got.kind, "blocked")
            self.assertIn(reason, got.reason)
            self.assertFalse(got.retry)

    def test_a_private_address_and_an_unusable_address_are_blocked_with_a_fixed_reason(self):
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://internal.test/p")
        self.assertEqual(crawlfetch.classify(caught.exception).kind, "blocked")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test:8080/p")
        self.assertEqual(crawlfetch.classify(caught.exception).kind, "blocked")

    def test_the_reason_is_a_fixed_text_that_never_holds_what_the_server_said(self):
        self.srv.routes["/s"] = reply(403, [("X-Note", "SECRETWORD-from-the-server")], b"SECRETWORD page")
        with self.assertRaises(FetchError) as caught:
            capture_url.policy_fetch(self.build().policy, "http://a.test/s", 100_000, 3, 5)
        got = crawlfetch.classify(caught.exception)
        self.assertNotIn("SECRETWORD", got.reason)
        self.assertNotIn("a.test", got.reason)
        self.srv.routes["/c"] = reply(200, body=b"<html></html>", ctype="SECRETWORD/odd")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/c")
        self.assertNotIn("SECRETWORD", crawlfetch.classify(caught.exception).reason)

    def test_an_error_that_is_not_a_fetch_error_is_not_classified_away(self):
        for error in (ValueError("x"), KeyError("k"), KbError("k")):
            with self.subTest(error), self.assertRaises(type(error)):
                crawlfetch.classify(error)

    def test_a_block_that_the_hook_calls_unusable_and_a_type_that_is_not_a_pdf_have_their_own_reasons(self):
        got = crawlfetch.classify(webclient.Refused("refused: unusable"))
        self.assertEqual((got.kind, got.reason, got.retry), ("blocked", "the address is not usable", False))
        self.srv.routes["/j"] = reply(200, body=b"{}", ctype="application/json")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/j")
        self.assertEqual(crawlfetch.classify(caught.exception).reason, "not a web page")

    def test_a_status_text_that_is_not_three_digits_is_a_failure_and_not_a_status(self):
        for text in ("HTTP 12345", "HTTP 40", "HTTP 4x3", "HTTP "):
            got = crawlfetch.classify(FetchError(text))
            self.assertEqual((got.kind, got.reason), ("failed", "the fetch failed"), text)

    def test_a_server_cannot_choose_its_class_by_what_it_puts_into_a_message(self):
        for text in ("the server sent the page encoded (x larger than y) although none was asked for", "the server sent the page encoded (timed out) although none was asked for",
                     "network error while reading: HTTP 429", "cannot connect to larger than.example: timed out"):
            got = crawlfetch.classify(FetchError(text))
            self.assertEqual((got.kind, got.reason, got.retry), ("failed", "the fetch failed", True), text)
        for ctype in ("text/x-pdf", "application/x-pdf", "pdf/application", "application/pdf-not"):
            with self.subTest(ctype):
                got = crawlfetch.classify(webclient.Refused(f"not an expected type: its content type is {ctype}"))
                self.assertEqual((got.kind, got.reason), ("rejected", "not a web page"))

    def test_a_redirect_loop_a_redirect_without_a_location_and_a_failed_address_check_are_failures_that_can_be_tried_again(self):
        self.srv.routes["/loop"] = redirect("http://a.test/loop")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/loop")
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason, got.retry), ("failed", "a redirect was refused", True))
        self.srv.routes["/nowhere"] = reply(302, body=b"", ctype="text/html")
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/nowhere")
        self.assertEqual(crawlfetch.classify(caught.exception).kind, "failed")

        def broken(address):
            raise RuntimeError("the matcher broke")

        fp = self.build()
        fp.policy.check = broken
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/p", fp)
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason, got.retry), ("failed", "the address check failed", True))

    def test_a_redirect_to_an_address_the_client_will_not_take_is_blocked(self):
        for target in ("javascript:alert(1)", "ftp://a.test/x", "http://user:pw@a.test/x"):
            with self.subTest(target):
                self.srv.routes["/go"] = redirect(target)
                with self.assertRaises(webclient.Refused) as caught:
                    self.fetch("http://a.test/go")
                self.assertIn(crawlfetch.classify(caught.exception).kind, ("blocked", "failed"))

    def test_the_wording_of_the_clients_messages_that_decide_the_class_is_pinned(self):
        for text, kind in (("HTTP 429", "refused"), ("HTTP 500", "failed"), ("timed out", "failed"), ("the response is larger than 5 bytes", "rejected"),
                           ("the response is larger than 5 bytes (it says 9)", "rejected")):
            self.assertEqual(crawlfetch.classify(FetchError(text)).kind, kind, text)


class StopFile(Case):
    def test_the_stop_file_is_looked_at_before_each_request_and_each_hop(self):
        self.page()
        fp = self.build()
        self.assertIsNone(fp.policy.check("http://a.test/p"))
        stop = os.path.join(self.index, "crawl.stop")
        open(stop, "w").close()
        self.assertIn("stop file", str(fp.policy.check("http://a.test/p")))
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/p", fp)
        self.assertIn("stop file", str(caught.exception))
        self.assertEqual(self.dials, [])
        os.remove(stop)

        def drops_the_stop_file(conn, path, headers):
            open(stop, "w").close()
            return redirect("http://b.test/p")

        self.srv.routes["/go"] = drops_the_stop_file
        self.page("/p")
        before = len(self.dials)
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/go", fp)
        self.assertIn("stop file", str(caught.exception))
        self.assertEqual(len(self.dials), before + 1)                              # the second hop was not dialled


class SharedLists(test_crawllists.Case):
    """The `lists` step makes its requests through the shared client under its own policy, which allows no private address."""

    def test_the_policy_the_list_refresh_builds_refuses_a_private_address_and_nothing_is_dialled(self):
        seen = []

        def spy(url, *, policy, **kw):
            seen.append(policy)
            return webclient.get(url, policy=policy, **kw)

        with mock.patch.object(webclient, "_dial", side_effect=AssertionError("dialled")):
            for address in ("https://10.0.0.5/l", "https://127.0.0.1/l", "https://169.254.169.254/l"):
                with self.subTest(address), self.assertRaises(crawlrun.StepRefused):
                    self.step(self.ctx(dict(self.plan, phishing_domains_url=address)), fetch=spy)
        self.assertTrue(seen)
        self.assertEqual({p.allow_private for p in seen}, {False})


class SharedRefill(test_crawlrefill.Case):
    """Discovery makes its requests through the shared client under its own policy, which allows no private address."""

    def test_the_policy_discovery_builds_refuses_a_private_address_and_nothing_is_dialled(self):
        seen, answers = [], []

        def spy(url, *, policy, headers=None, **kw):
            seen.append(policy)
            return webclient.get(url, policy=policy, headers=headers, **kw)

        class Asking(Source):
            def search(inner, query, get, limit, *more):
                for address in ("http://10.0.0.5/x", "http://127.0.0.1/x", "http://169.254.169.254/x"):
                    try:
                        get(address)
                        answers.append("answered")
                    except KbError as e:
                        answers.append(str(e))
                return {"candidates": [], "rejected": []}

        self.sources["openalex"] = Asking("openalex")
        with mock.patch.object(webclient, "_dial", side_effect=AssertionError("dialled")):
            crawlrefill.make_step(fetch=spy, sources=self.sources, call=self.call)(self.ctx())
        self.assertTrue(answers)
        self.assertEqual(set(answers), {"the request was refused or failed"})
        self.assertEqual({p.allow_private for p in seen}, {False})


class StopClass(Case):
    def test_a_refusal_because_of_the_stop_file_is_stopped_and_is_tried_again_later(self):
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        with self.assertRaises(webclient.Refused) as caught:
            self.fetch("http://a.test/p")
        got = crawlfetch.classify(caught.exception)
        self.assertEqual((got.kind, got.reason, got.retry), ("stopped", "the stop file is present", True))


class Wiring(Case):
    def test_the_module_makes_no_request_of_its_own_and_reads_no_environment_variable(self):
        with open(os.path.join(ENGINE_DIR, "kb", "crawlfetch.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("socket", "urllib.request", "http.client", "subprocess", "os.environ", "getenv", "open("):
            self.assertNotIn(word, source, word)


# ---- Increment G: the `fetch` step

DIGEST = "c" * 32
APPROVED = {DIGEST}


class Boom(BaseException):
    """A death of the process, injected where a test says."""


def roomy(path):
    return types.SimpleNamespace(f_bavail=10**9, f_frsize=4096)


class StepCase(Case):
    """A temporary library and queue, the fake network of `Case`, and a context like the runner's."""

    def setUp(self):
        super().setUp()
        self.cfgdir, self.bulk, self.libindex = (os.path.join(self.dir, n) for n in ("cfg", "bulk", "libindex"))
        saved = os.environ.get("KB_CONFIG_DIR")
        os.environ["KB_CONFIG_DIR"] = self.cfgdir
        self.addCleanup(lambda: os.environ.pop("KB_CONFIG_DIR", None) if saved is None else os.environ.__setitem__("KB_CONFIG_DIR", saved))
        library.setup(self.bulk, self.libindex, allow_main_disk=True)
        self.addCleanup(make_writable, self.dir)
        self.index = self.libindex
        os.makedirs(os.path.join(self.index, "crawl"), mode=0o700, exist_ok=True)
        self.store = store.Store.open()
        self.ident = identity.Identity(self.index)
        self.conn = crawlqueue.connect(self.index)
        self.addCleanup(self.conn.close)
        self.now = NOW
        self.log = crawllog.Log(self.index, "run-1", clock=lambda: self.now)
        self.plan.update(batch=50, retries=3, per_domain_per_day=100, fetches_per_day=500, filed_total=500, consecutive_failures=1000, window=1000, domain_refusals=3, timezone="UTC")
        self.rows_added = 0
        self.tripped = []

    # -- the fixture
    def add(self, path="/p", host="a.test", source="openalex", **kw):
        self.rows_added += 1
        address = f"http://{host}{path}"
        site = host.split(".", 1)[1] if host.count(".") > 1 else host
        self.dns.setdefault(host, [ALL_PUBLIC])
        added = f"2026-11-16T10:{self.rows_added // 60:02d}:{self.rows_added % 60:02d}Z"
        self.conn.execute("INSERT INTO candidates(identity_key, address, source, found_from, topic, domain, weight, status, added, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (address, address, source, kw.get("found_from", "openalex:W1"), kw.get("topic", "verification"), kw.get("domain", site), 1, "queued", added, added))
        return self.conn.execute("SELECT id FROM candidates WHERE identity_key = ?", (address,)).fetchone()[0]

    def doc(self, path, text=None):
        self.srv.routes[path] = reply(200, body=f"<html><head><title>{path}</title></head><body>{text or path} words on a page</body></html>".encode())

    def ctx(self):
        ctx = types.SimpleNamespace(cfg={"bulk_root": self.bulk, "index_root": self.index}, index_root=self.index, plan=self.plan, conn=self.conn, log=self.log, clock=lambda: self.now, secrets=(), run="run-1", matcher=self.matcher,
                                    suffixes=SUFFIXES, plan_digest=DIGEST, tripped=False, steps={})

        def trip(kind, reason):
            ctx.tripped = True
            self.tripped.append((kind, reason))
            return crawlguard.trip(self.index, kind, reason, "run-1", now=self.now, log=self.log)

        ctx.trip = trip
        return ctx

    def run_step(self, ctx=None, **kw):
        ctx = ctx or self.ctx()
        kw.setdefault("statvfs", roomy)
        crawlfetch.make_step(**kw)(ctx)
        return ctx

    def row(self, ident):
        cur = self.conn.execute("SELECT * FROM candidates WHERE id = ?", (ident,))
        return dict(zip([d[0] for d in cur.description], cur.fetchone()))

    def counters(self):
        return dict(((day, key), n) for day, key, n in self.conn.execute("SELECT day, key, n FROM counters"))

    def lines(self):
        folder = os.path.join(self.index, "crawl", "log")
        out = []
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out += [json.loads(line) for line in f.read().splitlines()]
        return out

    def active_books(self):
        return [b for b in self.store.list_books() if self.store.read_book(b)["state"] == "active"]

    def names(self, book):
        return [e["event"] for e in self.store.read_events(book)]

    def later(self, **delta):
        self.now = self.now + datetime.timedelta(**delta)


class OneCandidate(StepCase):
    def test_a_filed_page_is_a_book_with_auto_filed_and_its_found_event_the_row_kept_and_the_log_lines(self):
        self.doc("/p")
        ident = self.add("/p", source="openalex")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"]), ("kept", 1))
        book = row["book_id"]
        root = self.store.read_book(book)
        self.assertEqual((root["auto_filed"], root["state"], root["identity_keys"]["url"]), (True, "active", "http://a.test/p"))
        found = [e for e in self.store.read_events(book) if e["event"] == "crawl_found"]
        self.assertEqual(len(found), 1)
        self.assertEqual({k: found[0][k] for k in ("candidate", "source", "found_from", "topic", "run", "plan_digest")},
                         {"candidate": ident, "source": "openalex", "found_from": "openalex:W1", "topic": "verification", "run": "run-1", "plan_digest": DIGEST})
        self.assertIn("filed", self.names(book))
        self.assertEqual(crawlbooks.crawl_books(self.store, APPROVED), [book])
        self.assertEqual(self.counters()[("2026-11-16", "fetch")], 1)
        lines = [(x["step"], x["outcome"], x["candidate"], x["book"], x["host"]) for x in self.lines() if x["step"] in ("fetch", "capture") and x["candidate"] is not None]
        self.assertEqual(lines, [("capture", "ok", ident, book, "a.test"), ("fetch", "ok", ident, book, "a.test")])
        self.assertEqual(crawlbooks.filed_count(self.store), 1)

    def test_the_source_and_the_places_it_came_from_are_the_candidates_own_and_the_capture_gets_the_plans_timeouts_and_the_row_is_finished_by_this_run(self):
        self.doc("/w")
        ident = self.add("/w", source="wikipedia", found_from="wikipedia:Q1", topic="logic")
        seen, finished = [], []
        real, real_finish = capture_url.capture, crawlstate.finish

        def spy(*a, **k):
            seen.append((k["timeout"], k["total_timeout"]))
            return real(*a, **k)

        def spy_finish(*a, **k):
            finished.append(k.get("run"))
            return real_finish(*a, **k)

        with mock.patch.object(capture_url, "capture", spy), mock.patch.object(crawlstate, "finish", spy_finish):
            self.run_step()
        found = [e for e in self.store.read_events(self.row(ident)["book_id"]) if e["event"] == "crawl_found"][0]
        self.assertEqual((found["source"], found["found_from"], found["topic"]), ("wikipedia", "wikipedia:Q1", "logic"))
        self.assertEqual(seen, [(capture_url.TIMEOUT, 20)])
        self.assertEqual(finished, ["run-1"])

    def test_the_order_of_one_candidate_is_the_disk_floor_the_stop_file_the_reserve_and_then_the_capture_then_the_found_event_then_the_row(self):
        self.doc("/p")
        ident = self.add("/p")
        order = []
        real_capture, real_found, real_finish = capture_url.capture, crawlbooks.record_found, crawlstate.finish

        def spy_capture(*a, **k):
            order.append(("capture", self.row(ident)["status"], k["auto_filed"], k["policy"].types, k["max_bytes"]))
            return real_capture(*a, **k)

        def spy_found(*a, **k):
            order.append(("found", self.row(ident)["status"]))
            return real_found(*a, **k)

        def spy_finish(*a, **k):
            order.append("finish")
            return real_finish(*a, **k)

        with mock.patch.object(crawlguard, "check_disk", side_effect=lambda *a, **k: order.append("disk")), mock.patch.object(crawlguard, "stop_requested", side_effect=lambda root: order.append("stop") or False), \
                mock.patch.object(capture_url, "capture", spy_capture), mock.patch.object(crawlbooks, "record_found", spy_found), mock.patch.object(crawlstate, "finish", spy_finish):
            self.run_step()
        steps = [x if isinstance(x, str) else x[0] for x in order]
        first = steps.index("capture")
        self.assertLess(steps.index("disk"), first)
        self.assertLess(steps.index("stop"), first)
        self.assertEqual([x for x in steps[first:] if x != "stop"][:3], ["capture", "found", "finish"])      # (the hook asks the stop file at each hop of the capture)
        capture = order[first]
        self.assertEqual(capture[1:], ("fetching", True, ("text/html", "application/xhtml+xml"), crawlfetch.PAGE_MAX_BYTES))
        self.assertIn(("found", "fetching"), order[first:])

    def test_an_address_the_library_holds_already_is_rejected_as_held_with_the_books_id_and_the_owners_book_is_untouched(self):
        self.doc("/mine")
        held = capture_url.capture(self.store, self.ident, "http://a.test/mine", policy=self.build().policy)["book_id"]
        before = self.store.read_events(held)
        hits = len(self.srv.hits)
        ident = self.add("/mine")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["book_id"], row["reason"]), ("rejected", held, "already held"))
        self.assertEqual(len(self.srv.hits), hits)
        self.assertEqual(self.store.read_events(held), before)
        self.assertEqual(crawlbooks.crawl_books(self.store, APPROVED), [])
        self.assertEqual(crawlbooks.filed_count(self.store), 0)

    def test_the_same_bytes_at_another_address_are_rejected_as_a_duplicate_of_the_book_that_holds_them(self):
        self.doc("/one", "same")
        self.srv.routes["/two"] = self.srv.routes["/one"]
        first, second = self.add("/one"), self.add("/two", host="b.test")
        self.run_step()
        a, b = self.row(first), self.row(second)
        self.assertEqual(a["status"], "kept")
        self.assertEqual((b["status"], b["book_id"], b["reason"]), ("rejected", a["book_id"], "already held"))
        self.assertEqual(self.active_books(), [a["book_id"]])
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [True, True])         # a duplicate was fetched: a request that worked

    def test_a_page_of_a_hundred_thousand_links_over_ten_thousand_subdomains_is_stored_as_one_book_and_adds_no_candidate(self):
        links = "".join(f'<a href="http://s{i % 10000}.big.example/{i}">x</a>' for i in range(100_000))
        body = ("<html><head><title>links</title></head><body>" + links + "</body></html>").encode()
        self.assertGreater(len(body), 3_000_000)
        self.srv.routes["/big"] = reply(200, body=body)
        ident = self.add("/big")
        before = self.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], before)   # the links of a page are not followed: the spec leaves that out of the first version
        self.assertEqual(len(self.srv.hits), 1)
        self.assertEqual(len(self.active_books()), 1)

    def test_a_page_over_the_size_limit_is_rejected_for_its_size_and_makes_no_active_book(self):
        self.srv.routes["/huge"] = reply(200, body=b"x" * 10, headers=[("X-Pad", "1")])
        self.srv.routes["/huge"] = self.srv.routes["/huge"].replace(b"Content-Length: 10", b"Content-Length: %d" % (crawlfetch.PAGE_MAX_BYTES + 1))
        ident = self.add("/huge")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "over the size limit"))
        self.assertEqual(self.active_books(), [])


class BadAddresses(StepCase):
    def test_an_address_that_cannot_be_read_is_rejected_for_that_and_not_as_a_pdf_and_nothing_is_requested(self):
        ident = self.add("/x")
        self.conn.execute("UPDATE candidates SET address = 'http://[bad/x', identity_key = 'bad' WHERE id = ?", (ident,))
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "the address is not usable"))
        self.assertEqual((self.srv.hits, self.store.list_books()), ([], []))


class FailedCaptures(StepCase):
    def test_a_failed_capture_leaves_no_active_book_and_the_row_waits_and_is_tried_again(self):
        ident = self.add("/gone")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["reason"]), ("queued", 1, "HTTP 404"))
        self.assertEqual(row["next_try"], "2026-11-16T13:00:00Z")
        self.assertEqual(self.active_books(), [])
        made = self.store.list_books()
        self.assertEqual(len(made), 1)
        self.assertEqual(self.store.read_book(made[0])["state"], "weeded")
        self.assertIn("capture_failed", self.names(made[0]))
        self.assertNotIn("crawl_found", self.names(made[0]))
        self.assertEqual((crawlbooks.crawl_books(self.store, APPROVED), crawlbooks.filed_count(self.store)), ([], 0))

    def test_a_second_failure_of_the_same_address_leaves_the_weeded_book_as_it_is(self):
        self.add("/gone")
        self.run_step()
        self.later(hours=2)
        self.run_step()
        book = self.store.list_books()[0]
        self.assertEqual(self.names(book).count("capture_failed"), 1)
        self.assertEqual(self.store.read_book(book)["state"], "weeded")

    def test_a_retry_that_succeeds_files_into_the_same_book_and_makes_it_active_with_its_found_event(self):
        ident = self.add("/later")
        self.run_step()
        failed_book = self.store.list_books()[0]
        self.later(hours=2)
        self.doc("/later")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["book_id"]), ("kept", 2, failed_book))
        self.assertEqual(self.store.list_books(), [failed_book])
        self.assertEqual(self.store.read_book(failed_book)["state"], "active")
        self.assertEqual(crawlbooks.crawl_books(self.store, APPROVED), [failed_book])
        self.assertEqual(crawlbooks.filed_count(self.store), 1)

    def test_a_row_that_fails_retries_times_is_failed_and_final_and_its_book_stays_weeded(self):
        ident = self.add("/never")
        for _ in range(3):
            self.run_step()
            self.later(hours=30)
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"]), ("failed", 3))
        self.assertIn("failed 3 times", row["reason"])
        self.assertEqual(self.active_books(), [])
        hits = len(self.srv.hits)
        self.run_step()
        self.assertEqual(len(self.srv.hits), hits)

    def test_over_a_hundred_dead_addresses_leave_the_count_of_active_books_unchanged(self):
        self.doc("/alive")
        alive = self.add("/alive")
        self.run_step()
        before = self.active_books()
        self.assertEqual(len(before), 1)
        self.plan["batch"] = 120
        for i in range(105):
            self.add(f"/dead{i}", host=f"h{i}.test")
        self.run_step(ctx=self.ctx())
        self.assertEqual(self.active_books(), before)
        self.assertEqual(crawlbooks.filed_count(self.store), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'queued' AND tries = 1").fetchone()[0], 105)
        self.assertEqual(self.row(alive)["status"], "kept")

    def test_the_reason_kept_is_a_fixed_text_that_holds_nothing_the_server_said(self):
        self.srv.routes["/odd"] = reply(500, body=b"SECRET-SERVER-TEXT")
        ident = self.add("/odd")
        self.run_step()
        text = json.dumps([self.row(ident), self.lines()])
        self.assertNotIn("SECRET-SERVER-TEXT", text)
        self.assertEqual(self.row(ident)["reason"], "HTTP 500")


class Refusals(StepCase):
    def test_a_refusal_of_a_site_counts_for_the_site_waits_a_day_and_is_not_a_failure_of_the_breaker(self):
        self.srv.routes["/no"] = reply(403, body=b"no")
        ident = self.add("/no")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["tries"], row["next_try"]), ("queued", 1, "2026-11-17T12:00:00Z"))
        self.assertEqual(self.counters()[("2026-11-16", "refusal:a.test")], 1)
        state, restarted = crawlguard.load_state(self.index)
        self.assertEqual(state["history"], [])
        self.assertEqual([x["outcome"] for x in self.lines() if x["step"] == "fetch" and x["candidate"] is not None], ["refused"])
        self.assertEqual(self.active_books(), [])

    def test_every_status_the_policy_calls_a_refusal_is_one(self):
        for status in (401, 403, 429, 451):
            with self.subTest(status):
                path = f"/s{status}"
                self.srv.routes[path] = reply(status, body=b"x")
                ident = self.add(path, host=f"site{status}.test")
                self.run_step()
                self.assertEqual(self.counters()[("2026-11-16", f"refusal:site{status}.test")], 1)
                self.assertEqual(self.row(ident)["next_try"], "2026-11-17T12:00:00Z")

    def test_after_domain_refusals_the_site_is_skipped_by_the_next_reserve_and_other_sites_go_on(self):
        for i in range(3):
            self.srv.routes[f"/no{i}"] = reply(429, body=b"slow")
        first = [self.add(f"/no{i}", host=f"x{i}.a.test", domain="a.test") for i in range(3)]
        fourth = self.add("/fourth", host="y.a.test", domain="a.test")
        other = self.add("/other", host="c.test")
        self.doc("/other")
        self.doc("/fourth")
        self.run_step()
        hits = [p for p, _ in self.srv.hits]
        self.assertEqual(sorted(p for p in hits if p.startswith("/no")), ["/no0", "/no1", "/no2"])
        self.assertNotIn("/fourth", hits)
        self.assertEqual((self.row(fourth)["status"], self.row(fourth)["tries"]), ("queued", 0))
        self.assertEqual(self.row(other)["status"], "kept")
        self.assertEqual(self.counters()[("2026-11-16", "refusal:a.test")], 3)

    def test_a_policy_block_is_rejected_for_its_reason_with_no_request_and_no_book(self):
        for host, reason in (("evil.example", "blocked by the owner's blacklist"), ("listed.example", "blocked by a public list")):
            with self.subTest(host):
                ident = self.add("/p", host=host)
                hits = len(self.srv.hits)
                self.run_step()
                row = self.row(ident)
                self.assertEqual((row["status"], row["reason"]), ("rejected", reason))
                self.assertEqual(len(self.srv.hits), hits)
        self.assertEqual(self.store.list_books(), [])
        state, _ = crawlguard.load_state(self.index)
        self.assertEqual(state["history"], [])

    def test_a_blocked_redirect_target_is_rejected_and_the_book_is_not_made(self):
        self.srv.routes["/go"] = redirect("http://evil.example/page")
        ident = self.add("/go")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "blocked by the owner's blacklist"))
        self.assertEqual(self.store.list_books(), [])

    def test_a_private_address_is_rejected_and_never_dialled(self):
        self.dns["private.test"] = ["10.1.2.3"]
        ident = self.add("/p", host="private.test")
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "rejected")
        self.assertEqual(self.dials, [])
        self.assertEqual(self.store.list_books(), [])


class Pdfs(StepCase):
    def test_an_arxiv_candidate_is_rejected_as_a_pdf_without_a_request_or_a_book(self):
        ident = self.add("/abs", host="arxiv.test", source="arxiv")
        hits = len(self.srv.hits)
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "pdf not safe to convert"))
        self.assertEqual((len(self.srv.hits), self.store.list_books(), self.dials), (hits, [], []))

    def test_an_address_that_names_a_pdf_is_rejected_without_a_request(self):
        ident = self.add("/paper.PDF")
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["reason"]), ("rejected", "pdf not safe to convert"))
        self.assertEqual(self.srv.hits, [])

    def test_a_response_that_says_it_is_a_pdf_is_rejected_and_makes_no_book(self):
        self.srv.routes["/doc"] = reply(200, body=b"%PDF-1.4 x", ctype="application/pdf")
        ident = self.add("/doc")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "pdf not safe to convert"))
        self.assertEqual(self.store.list_books(), [])

    def test_a_pdf_served_as_html_and_a_response_with_no_content_type_are_refused_and_make_no_book(self):
        self.srv.routes["/sneaky"] = reply(200, body=b"%PDF-1.4 sneaky", ctype="text/html")
        self.srv.routes["/bare"] = reply(200, body=b"<html>x</html>", ctype=None)
        a, b = self.add("/sneaky"), self.add("/bare")
        self.run_step()
        self.assertEqual((self.row(a)["status"], self.row(b)["status"]), ("rejected", "rejected"))
        self.assertEqual(self.store.list_books(), [])


class Breaker(StepCase):
    def test_each_fetch_is_passed_to_the_breaker_and_a_trip_ends_the_run_with_the_breaker_tripped(self):
        self.plan.update(consecutive_failures=2)
        rows = [self.add(f"/dead{i}", host=f"h{i}.test") for i in range(4)]
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_step()
        self.assertEqual([r for r in rows if self.row(r)["tries"]], rows[:2])
        self.assertEqual(self.row(rows[2])["status"], "queued")
        self.assertEqual(self.tripped[0][0], "consecutive_failures")
        self.assertTrue(crawlguard.read_breaker(self.index)["tripped"])
        state, _ = crawlguard.load_state(self.index)
        self.assertEqual(state["history"], [False, False])

    def test_the_history_of_fetches_is_kept_between_runs_so_failures_in_a_row_add_up(self):
        self.plan.update(consecutive_failures=2)
        self.add("/dead1", host="h1.test")
        self.run_step()
        self.add("/dead2", host="h2.test")
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_step()
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [False, False])

    def test_a_page_filed_is_a_success_in_the_history_and_a_failure_after_it_is_a_failure(self):
        self.doc("/ok")
        self.add("/ok", host="a.test")
        self.add("/dead", host="b.test")
        self.run_step()
        state, _ = crawlguard.load_state(self.index)
        self.assertEqual(state["history"], [True, False])

    def test_the_share_of_failures_over_the_window_trips_it(self):
        self.plan.update(window=4, failure_share=0.5, consecutive_failures=100)
        self.doc("/a")
        self.doc("/b")
        for path, host in (("/a", "a.test"), ("/dead1", "b.test"), ("/b", "c.test"), ("/dead2", "d.test"), ("/dead3", "e.test")):
            self.add(path, host=host)
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_step()
        self.assertEqual(self.tripped[0][0], "failure_share")

    def test_the_report_and_the_closing_line_are_written_when_the_breaker_trips(self):
        self.plan.update(consecutive_failures=1)
        self.add("/dead")
        ctx = self.ctx()
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_step(ctx)
        self.assertEqual(ctx.fetch_report["ended"], "the circuit breaker was tripped")
        self.assertEqual([x["reason"] for x in self.lines() if x["step"] == "fetch" and x["candidate"] is None], ["the circuit breaker was tripped"])

    def test_a_trip_leaves_the_row_it_was_noted_for_finished_and_the_guard_state_saved(self):
        self.plan.update(consecutive_failures=1)
        ident = self.add("/dead")
        with self.assertRaises(crawlrun.BreakerTripped):
            self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["tries"]), ("queued", 1))
        state, restarted = crawlguard.load_state(self.index)
        self.assertEqual((state["history"], restarted), ([False], False))

    def test_blocks_stops_and_rejections_are_not_fetches_the_breaker_counts(self):
        self.plan.update(consecutive_failures=1)
        self.add("/p", host="evil.example")
        self.add("/p", host="arxiv.test", source="arxiv")
        self.srv.routes["/pdf"] = reply(200, body=b"%PDF", ctype="application/pdf")
        self.add("/pdf", host="d.test")
        self.run_step()
        state, _ = crawlguard.load_state(self.index)
        self.assertEqual((state["history"], self.tripped), ([], []))


class Bounds(StepCase):
    def test_the_fetch_ceiling_ends_new_fetches_and_the_step_returns_so_the_later_steps_run(self):
        self.plan["fetches_per_day"] = 2
        for i in range(4):
            self.doc(f"/p{i}")
            self.add(f"/p{i}", host=f"h{i}.test")
        ctx = self.run_step()
        self.assertEqual(len(self.srv.hits), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'queued'").fetchone()[0], 2)
        skipped = [x for x in self.lines() if x["step"] == "fetch" and x["outcome"] == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("fetches_per_day", skipped[0]["reason"])
        self.assertFalse(ctx.tripped)

    def test_the_filed_total_ceiling_counts_the_books_the_crawl_filed_and_an_unfinished_orphan(self):
        self.plan["filed_total"] = 2
        self.doc("/orphan")
        orphan = capture_url.capture(self.store, self.ident, "http://a.test/orphan", policy=self.build().policy, auto_filed=True)["book_id"]     # filed by the crawl, found event never written: the process died
        self.assertNotIn("crawl_found", self.names(orphan))
        for i in range(3):
            self.doc(f"/p{i}")
            self.add(f"/p{i}", host=f"h{i}.test")
        self.run_step()
        self.assertEqual(len(self.active_books()), 2)             # the orphan counted as one of the two
        skipped = [x for x in self.lines() if x["step"] == "fetch" and x["outcome"] == "skipped"]
        self.assertTrue(skipped and "filed_total" in skipped[0]["reason"])

    def test_the_batch_bounds_the_candidates_of_one_run(self):
        self.plan["batch"] = 2
        for i in range(4):
            self.doc(f"/p{i}")
            self.add(f"/p{i}", host=f"h{i}.test")
        self.run_step()
        self.assertEqual(len(self.srv.hits), 2)
        self.assertEqual([x["outcome"] for x in self.lines() if x["step"] == "fetch" and x["outcome"] == "skipped"], ["skipped"])

    def test_the_disk_floor_refuses_every_fetch_before_a_row_is_taken_and_the_run_goes_on(self):
        self.doc("/p")
        ident = self.add("/p")
        asked = []

        def full(path):
            asked.append(path)
            return types.SimpleNamespace(f_bavail=1, f_frsize=4096)

        ctx = self.run_step(statvfs=full)
        self.assertEqual(sorted(asked), sorted([self.bulk, self.index]))
        self.assertEqual((self.row(ident)["status"], self.row(ident)["tries"], self.counters()), ("queued", 0, {}))
        self.assertEqual(self.srv.hits, [])
        self.assertFalse(ctx.tripped)
        line = [x for x in self.lines() if x["step"] == "fetch"][0]
        self.assertEqual(line["outcome"], "skipped")
        self.assertIn("floor", line["reason"])

    def test_nothing_queued_is_a_quiet_step_with_one_line(self):
        self.run_step()
        self.assertEqual([(x["step"], x["outcome"]) for x in self.lines()], [("fetch", "skipped")])

    def test_a_book_is_never_fetched_twice(self):
        self.doc("/p")
        ident = self.add("/p")
        self.run_step()
        hits = len(self.srv.hits)
        self.run_step()
        self.run_step()
        self.assertEqual(len(self.srv.hits), hits)
        self.assertEqual(self.row(ident)["tries"], 1)
        again = self.add("/p?utm_source=x", host="a.test")           # another address that names the same page
        self.run_step()
        self.assertEqual(len(self.srv.hits), hits)
        self.assertEqual((self.row(again)["status"], self.row(again)["reason"]), ("rejected", "already held"))


class TheTimeBudget(StepCase):
    def test_no_candidate_is_taken_when_the_budget_of_the_run_is_spent_and_the_line_says_so(self):
        self.doc("/p")
        ident = self.add("/p")
        ctx = self.ctx()
        ctx.deadline = self.now
        self.run_step(ctx=ctx)
        self.assertEqual((self.row(ident)["tries"], self.counters(), self.srv.hits), (0, {}, []))
        self.assertEqual(ctx.fetch_report["ended"], "the time budget of the run is spent")

    def test_the_budget_is_looked_at_before_each_candidate(self):
        for i in range(3):
            self.doc(f"/p{i}")
            self.add(f"/p{i}", host=f"h{i}.test")
        ctx = self.ctx()
        real = capture_url.capture

        def spending(*a, **k):
            out = real(*a, **k)
            ctx.deadline = self.now
            return out

        with mock.patch.object(capture_url, "capture", spending):
            self.run_step(ctx=ctx)
        self.assertEqual([p for p, _ in self.srv.hits], ["/p0"])


class StopFile(StepCase):
    def test_a_stop_file_at_the_start_takes_no_row_and_makes_no_request(self):
        self.doc("/p")
        ident = self.add("/p")
        open(os.path.join(self.index, "crawl.stop"), "w").close()
        self.run_step()
        self.assertEqual((self.row(ident)["tries"], self.counters(), self.srv.hits), (0, {}, []))
        self.assertEqual([x["reason"] for x in self.lines() if x["step"] == "fetch" and x["outcome"] == "skipped"], ["the stop file is present"])

    def test_a_stop_file_made_in_the_middle_of_the_batch_ends_it_before_the_next_request(self):
        for i in range(3):
            self.doc(f"/p{i}")
            self.add(f"/p{i}", host=f"h{i}.test")
        real = capture_url.capture

        def stopping(*a, **k):
            out = real(*a, **k)
            open(os.path.join(self.index, "crawl.stop"), "w").close()
            return out

        with mock.patch.object(capture_url, "capture", stopping):
            self.run_step()
        self.assertEqual([p for p, _ in self.srv.hits], ["/p0"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidates WHERE tries = 0").fetchone()[0], 2)

    def test_a_stop_file_between_the_hops_of_one_fetch_ends_it_as_a_stop_and_not_a_failure_and_the_batch_ends(self):
        self.srv.routes["/go"] = redirect("http://b.test/new")
        self.doc("/new")
        first, second = self.add("/go"), self.add("/other", host="c.test")
        real = capture_url.capture

        def stopping(*a, **k):
            pol = k["policy"]
            inner = pol.check

            def check(address):
                if "b.test" in address:
                    open(os.path.join(self.index, "crawl.stop"), "w").close()
                return inner(address)
            pol.check = check
            return real(*a, **k)

        with mock.patch.object(capture_url, "capture", stopping):
            self.run_step()
        self.assertEqual(self.row(first)["status"], "queued")
        self.assertEqual(self.row(first)["reason"], "the stop file is present")
        self.assertEqual((self.row(second)["tries"], self.store.list_books()), (0, []))
        state, _ = crawlguard.load_state(self.index)
        self.assertEqual(state["history"], [])
        self.assertEqual(self.counters().get(("2026-11-16", "refusal:b.test")), None)


class Crashes(StepCase):
    def test_a_death_between_the_capture_and_the_found_event_is_adopted_by_the_next_run_with_no_second_fetch_and_no_second_book(self):
        self.doc("/p")
        ident = self.add("/p")
        with mock.patch.object(crawlbooks, "record_found", side_effect=Boom), self.assertRaises(Boom):
            self.run_step()
        book = self.store.list_books()[0]
        self.assertNotIn("crawl_found", self.names(book))
        self.assertEqual(self.row(ident)["status"], "fetching")
        self.later(minutes=31)
        crawlstate.requeue_stale(self.conn, self.plan, self.now)
        self.later(hours=2)                                  # the swept row waits its hour
        hits = len(self.srv.hits)
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["book_id"]), ("kept", book))
        self.assertEqual((len(self.srv.hits), self.store.list_books()), (hits, [book]))
        self.assertEqual(crawlbooks.crawl_books(self.store, APPROVED), [book])
        self.assertEqual(self.names(book).count("crawl_found"), 1)

    def test_a_death_between_the_found_event_and_the_row_is_finished_by_the_next_run_with_no_second_fetch(self):
        self.doc("/p")
        ident = self.add("/p")
        with mock.patch.object(crawlstate, "finish", side_effect=Boom), self.assertRaises(Boom):
            self.run_step()
        book = self.store.list_books()[0]
        self.assertEqual(self.names(book).count("crawl_found"), 1)
        self.later(minutes=31)
        crawlstate.requeue_stale(self.conn, self.plan, self.now)
        self.later(hours=2)                                  # the swept row waits its hour
        hits = len(self.srv.hits)
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["book_id"]), ("kept", book))
        self.assertEqual((len(self.srv.hits), self.names(book).count("crawl_found")), (hits, 1))

    def test_an_adopted_orphan_is_counted_once_so_the_ceiling_leaves_room_for_the_next_book_and_it_is_no_new_fetch_for_the_breaker(self):
        self.plan["filed_total"] = 2
        self.doc("/o")
        ident = self.add("/o", host="a.test")
        with mock.patch.object(crawlbooks, "record_found", side_effect=Boom), self.assertRaises(Boom):
            self.run_step()
        self.later(minutes=31)
        crawlstate.requeue_stale(self.conn, self.plan, self.now)
        self.later(hours=2)
        self.doc("/n")
        other = self.add("/n", host="b.test")
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(other)["status"]), ("kept", "kept"))
        self.assertEqual(len(self.active_books()), 2)
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [True])       # the book of the earlier try made no request now: only the new page did

    def test_a_book_found_for_this_candidate_that_was_weeded_since_is_not_kept(self):
        self.doc("/p")
        ident = self.add("/p")
        with mock.patch.object(crawlstate, "finish", side_effect=Boom), self.assertRaises(Boom):
            self.run_step()
        book = self.store.list_books()[0]
        self.store.set_state(book, "weeded")
        self.later(minutes=31)
        crawlstate.requeue_stale(self.conn, self.plan, self.now)
        self.later(hours=2)
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["reason"]), ("rejected", "already held"))

    def test_the_owners_unfinished_capture_that_a_redirect_leads_to_never_gets_a_found_event(self):
        owners = capture_url.capture(self.store, self.ident, "http://a.test/new", policy=self.build().policy)
        self.assertEqual(owners["status"], "failed")
        self.srv.routes["/go"] = redirect("http://a.test/new")
        self.doc("/new")
        ident = self.add("/go", host="b.test")
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["reason"]), ("rejected", "already held"))
        self.assertNotIn("crawl_found", self.names(owners["book_id"]))
        self.assertFalse(self.store.read_book(owners["book_id"])["auto_filed"])

    def test_a_death_in_the_middle_of_weeding_a_failed_capture_leaves_the_event_and_the_next_sweep_finishes_it(self):
        ident = self.add("/gone")
        with mock.patch.object(self.store.__class__, "set_state", side_effect=Boom), self.assertRaises(Boom):
            self.run_step()
        book = self.store.list_books()[0]
        self.assertEqual((self.store.read_book(book)["state"], self.names(book).count("capture_failed")), ("active", 1))
        self.later(minutes=31)
        crawlstate.requeue_stale(self.conn, self.plan, self.now)
        self.later(hours=2)
        self.doc("/gone")
        self.run_step()                                       # the sweep weeds it, and the retry that works revives it
        self.assertEqual((self.row(ident)["status"], self.row(ident)["book_id"]), ("kept", book))
        self.assertEqual(self.names(book).count("crawl_found"), 1)

    def test_an_orphan_whose_fetch_never_worked_is_weeded_at_the_start_and_one_whose_payload_was_filed_is_left_to_be_adopted(self):
        dead = capture_url.capture(self.store, self.ident, "http://a.test/dead", policy=self.build().policy, auto_filed=True)       # a 404: the book is made and the process died before it was weeded
        self.doc("/filed")
        filed = capture_url.capture(self.store, self.ident, "http://a.test/filed", policy=self.build().policy, auto_filed=True)
        self.assertEqual((dead["status"], filed["status"]), ("failed", "filed"))
        self.assertEqual(crawlbooks.filed_count(self.store), 2)
        self.run_step()
        self.assertEqual(self.store.read_book(dead["book_id"])["state"], "weeded")
        self.assertIn("capture_failed", self.names(dead["book_id"]))
        self.assertEqual(self.store.read_book(filed["book_id"])["state"], "active")
        self.assertNotIn("capture_failed", self.names(filed["book_id"]))
        self.assertEqual(crawlbooks.filed_count(self.store), 1)

    def test_a_book_found_for_another_candidate_is_not_taken_over(self):
        self.doc("/p")
        first = self.add("/p")
        self.run_step()
        book = self.row(first)["book_id"]
        other = self.add("/p?x=1", host="a.test")
        self.conn.execute("UPDATE candidates SET address = 'http://a.test/p', identity_key = 'second' WHERE id = ?", (other,))
        self.run_step()
        self.assertEqual((self.row(other)["status"], self.row(other)["reason"], self.row(other)["book_id"]), ("rejected", "already held", book))
        self.assertEqual(self.names(book).count("crawl_found"), 1)

    def test_a_book_the_owner_filed_without_auto_filed_is_never_given_a_found_event(self):
        self.doc("/mine")
        mine = capture_url.capture(self.store, self.ident, "http://a.test/mine", policy=self.build().policy)["book_id"]
        ident = self.add("/mine")
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "rejected")
        self.assertNotIn("crawl_found", self.names(mine))

    def test_an_error_that_is_not_a_fetch_error_ends_the_step_and_leaves_the_row_for_the_stale_sweep(self):
        self.doc("/p")
        ident = self.add("/p")
        ctx = self.ctx()
        with mock.patch.object(capture_url, "capture", side_effect=RuntimeError("boom")), self.assertRaises(RuntimeError):
            self.run_step(ctx)
        self.assertEqual(self.row(ident)["status"], "fetching")
        self.assertEqual(ctx.fetch_report["ended"], "the step failed")


class Redirects(StepCase):
    def redirectors(self, n, target="http://victim.test/p"):
        self.dns.setdefault("victim.test", [ALL_PUBLIC])
        for i in range(n):
            self.srv.routes[f"/r{i}"] = redirect(target)
        return [self.add(f"/r{i}", host=f"r{i}.test") for i in range(n)]

    def test_a_redirect_to_a_site_that_refuses_is_charged_to_that_site_and_the_site_is_then_left_alone_by_every_redirector(self):
        self.plan.update(per_domain_per_day=1, domain_refusals=1)
        self.srv.routes["/p"] = reply(403, body=b"no")
        rows = self.redirectors(4)
        self.run_step()
        self.assertEqual(len([1 for p, _ in self.srv.hits if p == "/p"]), 1)           # one request reached the victim; the other three were not made
        counters = self.counters()
        self.assertEqual(counters[("2026-11-16", "refusal:victim.test")], 1)
        self.assertEqual(counters[("2026-11-16", "hop:victim.test")], 1)                 # counted apart from the units of the site's own candidates
        self.assertNotIn(("2026-11-16", "fetch:victim.test"), counters)
        later = [self.row(r) for r in rows[1:]]
        self.assertEqual([(r["status"], r["tries"]) for r in later], [("queued", 1)] * 3)
        self.assertTrue(all(r["reason"] == "the site it leads to is stopped for the day" for r in later))
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [])       # deferred, not failed: nothing for the breaker

    def test_a_refusal_by_the_site_a_redirect_led_to_is_not_counted_against_the_site_that_led_to_it(self):
        self.plan.update(per_domain_per_day=5, domain_refusals=3, batch=10, fetches_per_day=10)
        for n in range(3):                                   # three different publishers, each reached through one resolver, each refusing
            host = f"pub{n}.test"
            self.dns.setdefault(host, [ALL_PUBLIC])
            self.srv.routes[f"/r{n}"] = redirect(f"http://{host}/p{n}")
            self.srv.routes[f"/p{n}"] = reply(403, body=b"no")
        rows = [self.add(f"/r{n}", host="resolver.test") for n in range(3)]
        self.run_step()
        counters = self.counters()
        self.assertEqual([counters.get(("2026-11-16", f"refusal:pub{n}.test")) for n in range(3)], [1, 1, 1])
        self.assertNotIn(("2026-11-16", "refusal:resolver.test"), counters)                  # the resolver is not stopped by what its publishers do
        self.assertEqual([self.row(r)["status"] for r in rows], ["queued"] * 3)
        later = {self.row(r)["next_try"] for r in rows}
        self.assertTrue(all(later))                                                            # each still waits before its next try

    def test_a_refusal_by_the_first_site_itself_is_counted_against_it_once(self):
        self.plan.update(per_domain_per_day=5, domain_refusals=3)
        self.srv.routes["/p"] = reply(403, body=b"no")
        ident = self.add("/p", host="a.test")
        self.run_step()
        counters = self.counters()
        self.assertEqual(counters[("2026-11-16", "refusal:a.test")], 1)
        self.assertEqual(self.row(ident)["status"], "queued")

    def test_redirects_to_a_site_cannot_use_the_units_that_its_own_candidates_would_have_used(self):
        self.plan.update(per_domain_per_day=2, batch=10, fetches_per_day=10)
        self.dns.setdefault("victim.test", [ALL_PUBLIC])
        redirectors = []
        for i in range(3):
            self.doc(f"/page{i}", f"distinct text number {i} of the page")
            self.srv.routes[f"/r{i}"] = redirect(f"http://victim.test/page{i}")
            redirectors.append(self.add(f"/r{i}", host=f"r{i}.test"))
        self.doc("/own", "the victim's own page, with its own words")
        own = self.add("/own", host="victim.test")                                       # a real candidate of the victim's own, queued after the redirectors
        self.run_step()
        rows = [self.row(r) for r in redirectors]
        self.assertEqual([r["status"] for r in rows[:2]], ["kept", "kept"])              # two hops were let through
        self.assertEqual((rows[2]["status"], rows[2]["reason"]), ("queued", "the site it leads to is at its limit for the day"))     # the third was refused: the hop count is the limit
        self.assertEqual(self.row(own)["status"], "kept")                                 # and the site's own candidate still had its units
        counters = self.counters()
        self.assertEqual((counters[("2026-11-16", "hop:victim.test")], counters[("2026-11-16", "fetch:victim.test")]), (2, 1))

    def chain(self, *steps, first="r0.test", limit=None):
        """A candidate at `first` whose address redirects through `steps` (full addresses, the last the page) and the row of it."""
        if limit is not None:
            self.plan.update(per_domain_per_day=limit)
        hosts = {urlsplit(s).hostname for s in steps}
        for host in hosts:
            self.dns.setdefault(host, [ALL_PUBLIC])
        self.srv.routes["/r0"] = redirect(steps[0])
        for here, there in zip(steps, steps[1:]):
            self.srv.routes[urlsplit(here).path] = redirect(there)
        self.doc(urlsplit(steps[-1]).path, "the page at the end of the chain with its own words")
        return self.add("/r0", host=first)

    def hops(self):
        return {k[4:]: n for (_d, k), n in self.counters().items() if k.startswith("hop:")}

    def test_two_requests_to_one_other_site_take_one_unit_and_the_candidate_is_kept_where_it_was_deferred_before(self):
        ident = self.chain("http://victim.test/m1", "http://www.victim.test/m2", "http://victim.test/page", limit=1)
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual(self.hops(), {"victim.test": 1})

    def test_a_chain_through_two_other_sites_takes_one_unit_for_each(self):
        ident = self.chain("http://victim.test/m1", "http://other.test/m2", "http://third.test/page", limit=1)
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual(self.hops(), {"victim.test": 1, "other.test": 1, "third.test": 1})

    def test_a_chain_that_returns_to_a_site_it_left_takes_one_unit_for_it_and_the_first_site_is_never_charged(self):
        ident = self.chain("http://victim.test/m1", "http://other.test/m2", "http://victim.test/m3", "http://r0.test/m4", "http://other.test/page", limit=1)
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual(self.hops(), {"victim.test": 1, "other.test": 1})

    def test_a_site_already_at_its_hop_limit_is_still_refused_at_the_first_visit_of_the_next_candidate(self):
        first = self.chain("http://victim.test/m1", "http://victim.test/page", limit=1)
        self.run_step()
        self.assertEqual(self.row(first)["status"], "kept")
        self.srv.routes["/r1"] = redirect("http://victim.test/m1")
        second = self.add("/r1", host="r1.test")
        self.run_step()
        self.assertEqual((self.row(second)["status"], self.row(second)["reason"]), ("queued", "the site it leads to is at its limit for the day"))
        self.assertEqual(self.hops(), {"victim.test": 1})

    def test_a_refusal_after_two_requests_to_a_site_is_one_hop_and_one_refusal_of_that_site(self):
        self.plan.update(per_domain_per_day=3, domain_refusals=3)
        self.dns.setdefault("victim.test", [ALL_PUBLIC])
        self.dns.setdefault("www.victim.test", [ALL_PUBLIC])
        self.srv.routes["/r0"] = redirect("http://victim.test/m1")
        self.srv.routes["/m1"] = redirect("http://www.victim.test/p")
        self.srv.routes["/p"] = reply(403, body=b"no")
        ident = self.add("/r0", host="r0.test")
        self.run_step()
        counters = self.counters()
        self.assertEqual((counters[("2026-11-16", "hop:victim.test")], counters[("2026-11-16", "refusal:victim.test")]), (1, 1))
        self.assertEqual(self.row(ident)["status"], "queued")

    def test_a_hostile_chain_between_two_sites_makes_at_most_the_redirect_limit_of_requests_and_charges_each_site_once(self):
        self.dns.setdefault("victim.test", [ALL_PUBLIC])
        self.dns.setdefault("other.test", [ALL_PUBLIC])
        self.srv.routes["/r0"] = redirect("http://victim.test/a")
        self.srv.routes["/a"] = redirect("http://other.test/b")
        self.srv.routes["/b"] = redirect("http://victim.test/a")
        ident = self.add("/r0", host="r0.test")
        before = len(self.srv.hits)
        self.run_step()
        self.assertLessEqual(len(self.srv.hits) - before, capture_url.MAX_REDIRECTS + 1)
        self.assertEqual(self.hops(), {"victim.test": 1, "other.test": 1})
        self.assertNotEqual(self.row(ident)["status"], "kept")

    def test_a_public_address_that_is_an_ip_is_its_own_site_and_is_counted_once_however_often_it_is_asked(self):
        self.srv.routes["/r0"] = redirect("http://8.8.8.8/m1")
        self.srv.routes["/m1"] = redirect("http://8.8.8.8/page")
        self.doc("/page", "the page at a public address, with its own words")
        ident = self.add("/r0", host="r0.test")
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual(self.hops(), {"8.8.8.8": 1})

    def test_a_redirect_to_a_site_at_its_daily_limit_is_deferred_with_its_own_reason(self):
        self.plan.update(per_domain_per_day=1)
        self.doc("/p")
        rows = self.redirectors(2)
        self.run_step()
        self.assertEqual(self.row(rows[0])["status"], "kept")
        self.assertEqual((self.row(rows[1])["status"], self.row(rows[1])["reason"]), ("queued", "the site it leads to is at its limit for the day"))
        self.assertEqual(len([1 for p, _ in self.srv.hits if p == "/p"]), 1)

    def test_a_redirect_inside_the_same_site_is_not_charged_as_another_site(self):
        self.plan.update(per_domain_per_day=1)
        self.srv.routes["/old"] = redirect("http://www.a.test/new")
        self.doc("/new")
        ident = self.add("/old", host="a.test")
        self.run_step()
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertEqual({k for _d, k in self.counters()}, {"fetch", "fetch:a.test"})

    def test_the_sites_of_the_hops_are_found_with_the_public_suffix_list(self):
        self.plan.update(per_domain_per_day=1)
        self.dns.setdefault("victim.co.uk", [ALL_PUBLIC])
        self.srv.routes["/ra"] = redirect("http://victim.co.uk/p")
        self.srv.routes["/rb"] = redirect("http://victim.co.uk/p")
        self.doc("/p")
        first, second = self.add("/ra", host="ra.co.uk", domain="ra.co.uk"), self.add("/rb", host="rb.co.uk", domain="rb.co.uk")
        self.run_step()
        self.assertEqual((self.row(first)["status"], self.row(second)["status"]), ("kept", "queued"))
        self.assertEqual(self.row(second)["reason"], "the site it leads to is at its limit for the day")

    def test_a_redirect_to_an_address_with_no_usable_site_name_is_a_block_and_not_a_failure_for_the_breaker(self):
        self.srv.routes["/v6"] = redirect("http://[2606:4700:4700::1111]/p")
        ident = self.add("/v6")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "the address is not usable"))
        self.assertEqual(crawlguard.load_state(self.index)[0]["history"], [])
        self.assertEqual(self.store.list_books(), [])

    def test_a_refusal_at_the_first_hop_is_charged_once_to_that_site_and_not_twice(self):
        self.srv.routes["/no"] = reply(429, body=b"slow")
        self.add("/no", host="a.test")
        self.run_step()
        self.assertEqual(self.counters()[("2026-11-16", "refusal:a.test")], 1)

    def test_a_deferred_row_is_not_a_reason_to_end_the_batch(self):
        self.plan.update(per_domain_per_day=1)
        self.doc("/p")
        self.doc("/mine")
        self.redirectors(2)
        other = self.add("/mine", host="m.test")
        self.run_step()
        self.assertEqual(self.row(other)["status"], "kept")


class NotTheCrawls(StepCase):
    def test_an_unfinished_capture_of_the_owners_is_not_fetched_into_by_the_crawl(self):
        owners = capture_url.capture(self.store, self.ident, "http://a.test/half", policy=self.build().policy)       # the owner's own capture, which failed and left its book
        self.assertEqual(owners["status"], "failed")
        self.doc("/half")
        hits = len(self.srv.hits)
        ident = self.add("/half")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"], row["book_id"]), ("rejected", "already held", owners["book_id"]))
        self.assertEqual(len(self.srv.hits), hits)
        self.assertEqual(self.names(owners["book_id"]), ["found"])

    def test_a_crawl_book_weeded_by_someone_else_is_not_revived(self):
        self.doc("/w")
        made = capture_url.capture(self.store, self.ident, "http://a.test/w", policy=self.build().policy, auto_filed=True)["book_id"]
        self.store.set_state(made, "weeded")
        ident = self.add("/w")
        self.run_step()
        self.assertEqual((self.row(ident)["status"], self.row(ident)["reason"]), ("rejected", "already held"))
        self.assertEqual(self.store.read_book(made)["state"], "weeded")
        self.assertNotIn("crawl_found", self.names(made))

    def test_a_body_that_is_binary_data_under_a_page_type_is_rejected_as_not_a_web_page_and_leaves_no_active_book(self):
        self.srv.routes["/bin"] = reply(200, body=b"<html>\x00\x01\x02 binary</html>")
        ident = self.add("/bin")
        self.run_step()
        row = self.row(ident)
        self.assertEqual((row["status"], row["reason"]), ("rejected", "not a web page"))
        self.assertEqual(self.active_books(), [])

    def test_the_report_of_the_step_counts_what_happened_and_what_ended_it(self):
        self.doc("/ok")
        self.add("/ok", host="a.test")
        self.add("/dead", host="b.test")
        ctx = self.run_step()
        self.assertEqual(ctx.fetch_report, {"ok": 1, "failed": 1, "filed": 1, "ended": "nothing is queued that can be taken now"})
        closing = [x for x in self.lines() if x["step"] == "fetch" and x["candidate"] is None]
        self.assertEqual([(x["outcome"], x["n"], x["reason"]) for x in closing], [("skipped", 2, "nothing is queued that can be taken now")])


class ClassifyMore(Case):
    def test_the_messages_of_a_capture_that_failed_after_the_client_gave_a_response_have_their_classes(self):
        for text, kind, reason in (("the page is larger than 5 bytes", "rejected", "over the size limit"),
                                   ("the response looks like binary or compressed data, not a web page", "rejected", "not a web page"),
                                   ("the final address is not usable: x", "failed", "the fetch failed")):
            with self.subTest(text):
                got = crawlfetch.classify(FetchError(text))
                self.assertEqual((got.kind, got.reason), (kind, reason))


class ClassifyDeferred(Case):
    def test_a_hop_refused_for_the_day_is_deferred_and_the_texts_are_the_policys_own(self):
        for text in ("refused: the site is stopped for the day", "refused: the site is at its limit for the day"):
            got = crawlfetch.classify(webclient.Refused(text))
            self.assertEqual((got.kind, got.retry), ("deferred", True))
        self.assertEqual(crawlfetch.classify(webclient.Refused("refused: the site is stopped for the day")).reason, "the site it leads to is stopped for the day")
        self.assertEqual(crawlfetch.classify(webclient.Refused("refused: the site is at its limit for the day")).reason, "the site it leads to is at its limit for the day")
        self.assertEqual(crawlfetch.classify(webclient.Refused("refused: owner")).kind, "blocked")


class Preconditions(StepCase):
    def test_the_step_needs_the_matcher_and_the_plan_digest_of_the_run(self):
        for missing in ("matcher", "plan_digest"):
            with self.subTest(missing):
                ctx = self.ctx()
                setattr(ctx, missing, None)
                with self.assertRaises(crawlrun.StepRefused):
                    self.run_step(ctx)

    def test_a_missing_public_suffix_list_is_said_loudly_in_the_log_and_the_step_goes_on(self):
        self.doc("/p")
        ident = self.add("/p")
        ctx = self.ctx()
        ctx.suffixes = None
        self.run_step(ctx)
        self.assertEqual(self.row(ident)["status"], "kept")
        self.assertTrue([x for x in self.lines() if x["step"] == "list_update" and x["outcome"] == "failed" and "Public Suffix List" in x["reason"]])

    def test_the_policy_is_built_once_for_the_step_from_the_approved_plan_the_matcher_and_the_suffix_list(self):
        self.doc("/p")
        self.add("/p")
        built = []
        real = crawlfetch.build

        def spy(*a, **k):
            built.append((a, k))
            return real(*a, **k)

        with mock.patch.object(crawlfetch, "build", spy):
            self.run_step()
        self.assertEqual(len(built), 1)
        plan, matcher, suffixes, index_root = built[0][0]
        self.assertEqual((plan is self.plan, matcher is self.matcher, suffixes, index_root), (True, True, SUFFIXES, self.index))

    def test_a_plan_the_policy_refuses_is_a_refusal_of_the_run(self):
        self.plan["user_agent"] = "neither"
        self.add("/p")
        with self.assertRaises(crawlrun.StepRefused):
            self.run_step()

    def test_the_default_step_opens_the_library_and_the_identity_index_by_itself(self):
        self.doc("/p")
        ident = self.add("/p")
        with mock.patch.object(crawlguard, "check_disk"):
            crawlfetch.step(self.ctx())
        self.assertEqual(self.row(ident)["status"], "kept")


if __name__ == "__main__":
    unittest.main()
