"""The policy of a fetch of the unattended crawl (`kb/crawlfetch.py`, Increment F of the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`).

`crawlfetch.build` makes the one `webclient.Policy` under which every candidate is fetched, from the approved plan, the matcher and the Public Suffix List that the `lists` step left; `crawlfetch.classify` says what
a failed fetch was (a block by the policy, a refusal by the site, a candidate to reject, or a failure). These tests run the real shared client (`webclient.get`, and `capture_url.capture` for the capture) against the
fake resolver and the fake server of `test_webclient`; nothing here touches the real network.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch`."""
import datetime
import os
import socket
import tempfile
import threading
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)
from engine.tests import test_crawllists, test_crawlrefill
from engine.tests.test_capture_policy import PAGE
from engine.tests.test_discover import Source
from engine.tests.test_store import StoreCase
from engine.tests.test_weblists import Fake, ok as list_ok, plan as lists_plan
from engine.tests.test_webclient import PRIVATE, Net, PeerSock, redirect, reply

from kb import KbError, capture_url, crawlfetch, crawlplan, crawlrefill, crawlrun, identity, webclient, weblists
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


if __name__ == "__main__":
    unittest.main()
