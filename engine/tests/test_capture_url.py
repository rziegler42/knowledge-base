import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from engine.tests import ENGINE_DIR
from engine.tests.test_store import StoreCase

from kb import KbError, identity, library, stages
from kb import capture_url

def ids_new():
    from kb import ids
    return ids.new_book_id()


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "page.html")
with open(FIXTURE, "rb") as _f:
    PAGE = _f.read()


class Site:
    """A web server on the local machine, whose routes and request log the tests control."""

    def __init__(self):
        self.routes = {}   # path -> (status, headers, body, delay seconds)
        self.hits = []     # (path, headers) of every request

        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # the body ends when the connection closes unless a length is sent

            def do_GET(self):
                site.hits.append((self.path, dict(self.headers)))
                status, headers, body, delay = site.routes.get(self.path, (404, {}, b"not found", 0))
                if delay:
                    time.sleep(delay)
                try:
                    self.send_response(status)
                    for k, v in (headers.items() if isinstance(headers, dict) else headers):
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def add(self, path, body=PAGE, status=200, headers=None, delay=0, content_type="text/html; charset=utf-8"):
        h = {"Content-Type": content_type} if content_type else {}
        h.update(headers or {})
        self.routes[path] = (status, h, body, delay)

    def count(self, path=None):
        return len([h for h in self.hits if path is None or h[0] == path])

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class CaptureCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.site = Site()
        self.addCleanup(self.site.stop)
        self.ident = identity.Identity(self.index)

    def capture(self, path_or_url, **kw):
        address = path_or_url if "://" in path_or_url else self.site.url(path_or_url)
        kw.setdefault("allow_private", True)  # the test server is on the local machine
        return capture_url.capture(self.store, self.ident, address, **kw)


class NormalizeTest(unittest.TestCase):
    def test_an_address_is_made_canonical(self):
        n = identity.normalize_address
        self.assertEqual(n("HTTP://Example.COM:80/a#frag"), "http://example.com/a")
        self.assertEqual(n("https://example.com:443"), "https://example.com/")
        self.assertEqual(n("https://example.com:8443/x?b=1&a=2"), "https://example.com:8443/x?b=1&a=2")
        self.assertEqual(n("http://[::1]:8080/p"), "http://[::1]:8080/p")
        self.assertEqual(n("  https://example.com/a  "), "https://example.com/a")

    def test_unsafe_or_unusable_addresses_are_refused(self):
        for bad in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "http:///nohost", "example.com/x",
                    "http://user:pass@example.com/", "http://user@example.com/", "http://exa mple.com/",
                    "http://example.com/a\nb", "http://example.com:99999/", "", None, 5, "http://example.com:0/"):
            with self.assertRaises(KbError, msg=repr(bad)):
                identity.normalize_address(bad)


class HostGuardTest(unittest.TestCase):
    def test_private_loopback_and_link_local_addresses_are_refused_unless_allowed(self):
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.5", "172.16.0.9", "169.254.169.254", "0.0.0.0", "::1",
                   "::ffff:127.0.0.1", "fe80::1", "fc00::1", "224.0.0.1"):
            with self.assertRaises(capture_url.FetchError, msg=ip):
                capture_url.check_host_allowed(ip, 80, allow_private=False)
            capture_url.check_host_allowed(ip, 80, allow_private=True)
        capture_url.check_host_allowed("8.8.8.8", 80, allow_private=False)

    def test_is_public_judges_every_form_by_the_address_it_carries(self):
        import ipaddress
        cases = {"::ffff:7f00:1": False, "::ffff:a00:1": False, "::ffff:808:808": True, "64:ff9b::808:808": True,
                 "64:ff9b::7f00:1": False, "2002:808:808::1": True, "2002:7f00:1::1": False, "::7f00:1": False,
                 "2001::1": False, "fec0::1": False, "2606:4700:4700::1111": True, "8.8.8.8": True, "127.0.0.1": False,
                 "224.0.0.1": False, "100.64.0.1": False, "169.254.169.254": False}
        for text, expected in cases.items():
            self.assertEqual(capture_url.is_public(ipaddress.ip_address(text)), expected, text)

    def test_each_layer_refuses_a_host_written_with_percent_escapes_on_its_own(self):
        with self.assertRaises(KbError):
            identity.normalize_address("http://%31%32%37.0.0.1/")
        with self.assertRaises(capture_url.PolicyError):
            capture_url.resolve_checked("%31%32%37.0.0.1", 80, allow_private=False)
        with self.assertRaises(capture_url.PolicyError):
            capture_url.resolve_checked("%31%32%37.0.0.1", 80, allow_private=True)  # even where private hosts are allowed
        handler = capture_url.make_redirect_handler(allow_private=True, max_redirects=5)
        req = urllib.request.Request("http://8.8.8.8/start")
        with mock.patch.object(capture_url, "check_host_allowed"):  # even if the later check were silent
            with self.assertRaises(capture_url.FetchError):
                handler.redirect_request(req, None, 302, "Found", {}, "http://%31%32%37.0.0.1/x")

    def test_addresses_hidden_inside_other_ipv6_forms_are_judged_by_the_address_they_hide(self):
        hidden_private = ("::7f00:1", "::a00:1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::c0a8:101",
                          "2002:7f00:1::1", "2002:c0a8:101::1", "2002:a9fe:a9fe::1", "64:ff9b:1::1", "2001::1", "fec0::1")
        for ip in hidden_private:
            with self.assertRaises(capture_url.FetchError, msg=ip):
                capture_url.check_host_allowed(ip, 80, allow_private=False)
        for ip in ("64:ff9b::808:808", "2002:808:808::1", "2606:4700:4700::1111"):
            capture_url.check_host_allowed(ip, 80, allow_private=False)  # public ones inside the same forms are fine

    def test_a_name_that_resolves_to_a_private_address_is_refused(self):
        fake = [(2, 1, 6, "", ("10.1.2.3", 80))]
        with mock.patch("socket.getaddrinfo", return_value=fake):
            with self.assertRaises(capture_url.FetchError):
                capture_url.check_host_allowed("internal.example", 80, allow_private=False)

    def test_one_private_address_among_several_refuses_the_name(self):
        fake = [(2, 1, 6, "", ("8.8.8.8", 80)), (2, 1, 6, "", ("127.0.0.1", 80))]
        with mock.patch("socket.getaddrinfo", return_value=fake):
            with self.assertRaises(capture_url.FetchError):
                capture_url.check_host_allowed("mixed.example", 80, allow_private=False)

    def test_a_redirect_to_another_scheme_or_a_private_host_is_refused(self):
        handler = capture_url.make_redirect_handler(allow_private=False, max_redirects=5)
        req = urllib.request.Request("http://8.8.8.8/start")
        for target in ("file:///etc/passwd", "ftp://8.8.8.8/x", "http://127.0.0.1/admin", "http://10.0.0.1/"):
            with self.assertRaises(capture_url.FetchError, msg=target):
                handler.redirect_request(req, None, 302, "Found", {}, target)
        ok = handler.redirect_request(req, None, 302, "Found", {}, "http://8.8.4.4/next")
        self.assertEqual(ok.full_url, "http://8.8.4.4/next")

    def test_a_redirect_carrying_credentials_is_refused(self):
        handler = capture_url.make_redirect_handler(allow_private=False, max_redirects=5)
        req = urllib.request.Request("http://8.8.8.8/start")
        with self.assertRaises(capture_url.FetchError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://user:pw@8.8.4.4/next")


class FiledPageTest(CaptureCase):
    def test_a_normal_page_is_stored_unchanged_with_its_manifest(self):
        self.site.add("/page", headers={"Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT", "ETag": '"abc"',
                                        "Set-Cookie": "session=secret", "X-Other": "ignored"})
        result = self.capture("/page")
        self.assertEqual(result["status"], "filed")
        book, version = result["book_id"], result["version_id"]
        self.assertEqual(self.site.count("/page"), 1)
        original = os.path.join(self.store.payload_dir(book, version, "original"), "page.html")
        with open(original, "rb") as f:
            self.assertEqual(f.read(), PAGE)
        digest = hashlib.sha256(PAGE).hexdigest()
        v = self.store.read_version(book, version)
        src = v["source"]
        self.assertEqual(src["address_asked"], self.site.url("/page"))
        self.assertEqual(src["address_final"], self.site.url("/page"))
        self.assertEqual(src["http_status"], 200)
        self.assertEqual(src["sha256"], digest)
        self.assertRegex(src["retrieved"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertEqual(src["headers"]["content-type"], "text/html; charset=utf-8")
        self.assertEqual(src["headers"]["etag"], '"abc"')
        self.assertNotIn("set-cookie", src["headers"])
        self.assertNotIn("x-other", src["headers"])
        self.assertEqual(v["primary"], "page.html")
        manifest = self.store.verify_payload(book, version, "original")
        self.assertEqual(manifest["files"]["page.html"]["sha256"], digest)
        root = self.store.read_book(book)
        self.assertEqual(root["kind"], "web page")
        self.assertEqual(root["identity_keys"]["url"], self.site.url("/page"))
        self.assertEqual(root["identity_keys"]["sha256"], [digest])
        state = stages.read(self.store, book, version)["stages"]
        self.assertEqual((state["fetched"]["status"], state["scanned"]["status"]), ("done", "pending"))
        self.assertEqual([e["event"] for e in self.store.read_events(book)], ["filed"])

    def test_the_request_is_honest_and_plain(self):
        self.site.add("/page")
        self.capture("/page")
        _path, headers = self.site.hits[0]
        self.assertTrue(headers["User-Agent"].startswith("knowledge-base/"), headers["User-Agent"])
        self.assertNotIn("@", headers["User-Agent"])
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)

    def test_a_redirect_is_followed_and_both_addresses_are_recorded(self):
        self.site.add("/page")
        self.site.add("/old", body=b"", status=302, headers={"Location": self.site.url("/page")}, content_type=None)
        result = self.capture("/old")
        self.assertEqual(result["status"], "filed")
        src = self.store.read_version(result["book_id"], result["version_id"])["source"]
        self.assertEqual(src["address_asked"], self.site.url("/old"))
        self.assertEqual(src["address_final"], self.site.url("/page"))
        root = self.store.read_book(result["book_id"])
        self.assertEqual(root["identity_keys"]["url"], self.site.url("/page"))
        self.assertIn(self.site.url("/old"), root["identity_keys"]["url_alias"])
        self.assertEqual(self.ident.lookup("url", self.site.url("/old")), result["book_id"])
        self.assertEqual(self.ident.lookup("url", self.site.url("/page")), result["book_id"])

    def test_a_redirect_loop_is_stopped(self):
        self.site.add("/a", body=b"", status=302, headers={"Location": self.site.url("/b")}, content_type=None)
        self.site.add("/b", body=b"", status=302, headers={"Location": self.site.url("/a")}, content_type=None)
        result = self.capture("/a")
        self.assertEqual(result["status"], "failed")
        self.assertIn("redirect", result["reason"])


class DuplicateTest(CaptureCase):
    def test_a_repeated_address_is_not_downloaded_again(self):
        self.site.add("/page")
        first = self.capture("/page")
        second = self.capture("/page")
        self.assertEqual(second["status"], "held")
        self.assertEqual(second["book_id"], first["book_id"])
        self.assertEqual(self.site.count("/page"), 1)
        self.assertEqual(self.store.list_books(), [first["book_id"]])

    def test_the_final_address_of_a_redirect_counts_as_held(self):
        self.site.add("/page")
        self.site.add("/old", body=b"", status=302, headers={"Location": self.site.url("/page")}, content_type=None)
        first = self.capture("/old")
        again = self.capture("/page")
        self.assertEqual((again["status"], again["book_id"]), ("held", first["book_id"]))
        self.assertEqual(self.site.count("/page"), 1)

    def test_a_redirect_to_a_held_final_address_is_a_sighting_not_a_new_book(self):
        self.site.add("/page")
        self.site.add("/short", body=b"", status=301, headers={"Location": self.site.url("/page")}, content_type=None)
        first = self.capture("/page")
        second = self.capture("/short")
        self.assertEqual((second["status"], second["book_id"]), ("duplicate", first["book_id"]))
        self.assertEqual(self.store.list_books(), [first["book_id"]])
        events = self.store.read_events(first["book_id"])
        self.assertEqual([e["event"] for e in events], ["filed", "sighting"])
        self.assertEqual(events[1]["address_asked"], self.site.url("/short"))
        self.assertEqual(self.ident.lookup("url", self.site.url("/short")), first["book_id"])
        again = self.capture("/short")  # now held by its alias: no download at all
        self.assertEqual(again["status"], "held")

    def test_a_held_final_address_with_changed_bytes_is_still_a_sighting_not_a_new_book(self):
        self.site.add("/page")
        self.site.add("/short", body=b"", status=301, headers={"Location": self.site.url("/page")}, content_type=None)
        first = self.capture("/page")
        changed = PAGE + b"<!-- the page was edited -->"
        self.site.add("/page", body=changed)
        second = self.capture("/short")
        self.assertEqual((second["status"], second["book_id"]), ("duplicate", first["book_id"]))
        self.assertEqual(self.store.list_books(), [first["book_id"]])
        sighting = self.store.read_events(first["book_id"])[-1]
        self.assertFalse(sighting["same_bytes"])
        self.assertEqual(sighting["sha256"], hashlib.sha256(changed).hexdigest())
        self.assertIn(hashlib.sha256(changed).hexdigest(), self.store.read_book(first["book_id"])["identity_keys"]["sha256"])

    def test_a_page_at_a_held_address_with_the_bytes_of_another_book_does_not_take_that_books_hash(self):
        a_bytes, b_bytes = PAGE + b"<!-- A -->", PAGE + b"<!-- B -->"
        self.site.add("/a", body=a_bytes)
        self.site.add("/b", body=b_bytes)
        x, y = self.capture("/a"), self.capture("/b")
        self.site.add("/a", body=b_bytes)  # the page at /a now holds the bytes that /b has
        self.site.add("/short", body=b"", status=301, headers={"Location": self.site.url("/a")}, content_type=None)
        third = self.capture("/short")
        self.assertEqual((third["status"], third["book_id"]), ("duplicate", x["book_id"]))
        digest_b = hashlib.sha256(b_bytes).hexdigest()
        self.assertNotIn(digest_b, self.store.read_book(x["book_id"])["identity_keys"]["sha256"])
        self.assertEqual(self.ident.lookup("sha256", digest_b), y["book_id"])
        self.assertFalse(self.store.read_events(x["book_id"])[-1]["same_bytes"])

    def test_another_address_with_identical_bytes_is_a_sighting_on_the_existing_book(self):
        self.site.add("/page")
        self.site.add("/copy")  # the same bytes at another address
        first = self.capture("/page")
        second = self.capture("/copy")
        self.assertEqual((second["status"], second["book_id"]), ("duplicate", first["book_id"]))
        self.assertEqual(self.store.list_books(), [first["book_id"]])
        self.assertEqual(self.store.version_ids(first["book_id"]), ["v1"])
        sighting = self.store.read_events(first["book_id"])[-1]
        self.assertEqual(sighting["event"], "sighting")
        self.assertEqual(sighting["sha256"], hashlib.sha256(PAGE).hexdigest())
        self.assertEqual(sighting["address_final"], self.site.url("/copy"))
        root = self.store.read_book(first["book_id"])
        self.assertIn(self.site.url("/copy"), root["identity_keys"]["url_alias"])
        self.assertEqual(self.capture("/copy")["status"], "held")
        self.assertEqual(self.site.count("/copy"), 1)

    def test_different_bytes_at_a_new_address_are_a_new_book(self):
        self.site.add("/page")
        self.site.add("/other", body=PAGE + b"<!-- different -->")
        a, b = self.capture("/page"), self.capture("/other")
        self.assertEqual(b["status"], "filed")
        self.assertNotEqual(a["book_id"], b["book_id"])

    def test_the_identity_index_can_be_rebuilt_from_the_books(self):
        self.site.add("/page")
        self.site.add("/copy")
        a = self.capture("/page")
        self.capture("/copy")
        os.remove(os.path.join(self.index, "identity.sqlite"))
        self.ident = identity.Identity(self.index)
        self.assertIsNone(self.ident.lookup("url", self.site.url("/page")))
        self.ident.rebuild(self.store)
        for key in (("url", self.site.url("/page")), ("url", self.site.url("/copy")),
                    ("sha256", hashlib.sha256(PAGE).hexdigest())):
            self.assertEqual(self.ident.lookup(*key), a["book_id"], key)


class NetworkGuardTest(CaptureCase):
    """The address that was checked is the address that is connected to, and a name that cannot be checked is not fetched."""

    @staticmethod
    def fetch_thread_ends(seconds=4.0):
        """Whether every thread the fetch started (named kb-fetch) has ended within a few seconds of the deadline."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not [t for t in threading.enumerate() if t.name == "kb-fetch" and t.is_alive()]:
                return True
            time.sleep(0.05)
        return False

    def test_a_host_written_with_percent_escapes_is_refused_before_any_request(self):
        self.site.add("/page")
        for host in ("%31%32%37.0.0.1", "localhost%2e", "127%2e0%2e0%2e1", "%6c%6f%63%61%6c%68%6f%73%74", "exa%6dple.com"):
            with self.assertRaises(KbError, msg=host):
                capture_url.capture(self.store, self.ident, f"http://{host}:{self.site.port}/page")
        self.assertEqual(self.site.count(), 0)
        self.assertEqual(self.store.list_books(), [])

    def test_a_redirect_to_a_host_with_percent_escapes_is_refused(self):
        handler = capture_url.make_redirect_handler(allow_private=False, max_redirects=5)
        req = urllib.request.Request("http://8.8.8.8/start")
        for target in ("http://%31%32%37.0.0.1/x", "http://localhost%2e/x", "http://127%2e0%2e0%2e1/"):
            with self.assertRaises(capture_url.FetchError, msg=target):
                handler.redirect_request(req, None, 302, "Found", {}, target)

    def test_a_name_that_answers_differently_the_second_time_is_never_connected_to_at_the_private_address(self):
        answers = iter([[(2, 1, 6, "", ("93.184.216.34", 80))]])

        def getaddrinfo(host, port, *a, **k):
            return next(answers, [(2, 1, 6, "", ("127.0.0.1", port))])  # every later lookup says loopback

        targets = []

        def create_connection(address, *a, **k):
            targets.append(address[0])
            raise ConnectionRefusedError("no real connection in a test")

        with mock.patch("socket.getaddrinfo", getaddrinfo), mock.patch("socket.create_connection", create_connection):
            result = capture_url.capture(self.store, self.ident, "http://rebind.example/page")
        self.assertNotIn("127.0.0.1", targets, "the connection went to the private address")
        self.assertEqual(result["status"], "failed")
        self.assertIn("private", result["reason"])

    def test_the_connection_uses_the_address_it_checked_and_looks_the_name_up_only_once(self):
        lookups, targets = [], []

        def getaddrinfo(host, port, *a, **k):
            lookups.append(host)
            return [(2, 1, 6, "", ("93.184.216.34", port))]

        def create_connection(address, *a, **k):
            targets.append(address)
            raise ConnectionRefusedError("no real connection in a test")

        with mock.patch("socket.getaddrinfo", getaddrinfo), mock.patch("socket.create_connection", create_connection):
            with self.assertRaises(capture_url.FetchError):  # the stand-in connection always refuses
                capture_url.fetch("http://pinned.example/page", allow_private=False, total_timeout=5)
        self.assertEqual(targets, [("93.184.216.34", 80)])
        self.assertEqual(lookups, ["pinned.example"], "the name must be looked up once, by the connection itself")

    def test_a_name_that_cannot_be_resolved_is_not_fetched_even_when_the_second_lookup_would_succeed(self):
        calls = []

        def getaddrinfo(host, port, *a, **k):
            calls.append(host)
            if len(calls) == 1:
                raise socket.gaierror(8, "no such name")
            return [(2, 1, 6, "", ("127.0.0.1", self.site.port))]

        self.site.add("/page")
        with mock.patch("socket.getaddrinfo", getaddrinfo):
            result = capture_url.capture(self.store, self.ident, f"http://flaky.example:{self.site.port}/page")
        self.assertEqual(self.site.count(), 0)
        self.assertEqual(result["status"], "failed")

    def test_a_name_with_one_private_answer_among_public_ones_is_not_connected_to_at_all(self):
        targets = []

        def refuse(address, *a, **k):
            targets.append(address)
            raise OSError("no real connection in a test")

        fake = [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.0.0.5", 80))]
        with mock.patch("socket.getaddrinfo", return_value=fake), mock.patch("socket.create_connection", refuse):
            with self.assertRaises(KbError) as cm:
                capture_url.capture(self.store, self.ident, "http://mixed.example/page")
        self.assertIn("private", str(cm.exception))
        self.assertEqual(targets, [])
        self.assertEqual(self.store.list_books(), [])

    def test_a_server_that_trickles_its_headers_does_not_keep_a_thread_alive_after_the_deadline(self):
        class Trickle(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                try:
                    self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                    for i in range(200):
                        self.wfile.write(b"X-Slow-%d: y\r\n" % i)
                        self.wfile.flush()
                        time.sleep(0.4)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
        server.daemon_threads = True
        threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        result = self.capture(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5, total_timeout=1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("timed out", result["reason"])
        self.assertTrue(self.fetch_thread_ends(), "the fetch's thread is still alive")

    def test_a_server_that_trickles_over_https_does_not_keep_a_thread_alive_after_the_deadline(self):
        import ssl
        cert, key = os.path.join(self.base, "cert.pem"), os.path.join(self.base, "key.pem")
        self.assertFalse([t for t in threading.enumerate() if t.name == "kb-fetch"])  # nothing left over from another test
        made = subprocess.run(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
                               "-out", cert, "-days", "1", "-subj", "/CN=127.0.0.1", "-addext",
                               "subjectAltName=IP:127.0.0.1"], capture_output=True, timeout=60)
        self.assertEqual(made.returncode, 0, made.stderr)

        class Trickle(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                try:
                    self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                    for i in range(200):
                        self.wfile.write(b"X-Slow-%d: y\r\n" % i)
                        self.wfile.flush()
                        time.sleep(0.4)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Trickle)
        server.daemon_threads = True
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert, key)
        server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client_ctx = ssl.create_default_context(cafile=cert)  # trust the test certificate and nothing else
        before = threading.active_count()
        with mock.patch("http.client._create_https_context", lambda version: client_ctx):
            result = self.capture(f"https://127.0.0.1:{server.server_address[1]}/", timeout=5, total_timeout=1)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("timed out", result["reason"])
        self.assertTrue(self.fetch_thread_ends(), "the fetch's thread is still alive behind https")

    def test_header_values_that_are_kept_are_cleaned(self):
        self.site.add("/page", headers={"ETag": '"\x1b[31mred\x07"', "Last-Modified": "Mon\x01, 01 Jan 2024", "Cache-Control": "a­" + "b" * 600})
        result = self.capture("/page")
        kept = self.store.read_version(result["book_id"], result["version_id"])["source"]["headers"]
        for value in kept.values():
            for bad in ("\x1b", "\x07", "\x01", "­"):
                self.assertNotIn(bad, value)
            self.assertLessEqual(len(value), 300)
        self.assertEqual(kept["etag"], '"[31mred"')

    def test_a_content_length_written_in_other_digits_is_a_failed_fetch_not_a_crash(self):
        for value in ("²", "1e3", "-5", " ", "12 34"):
            self.site.add("/odd", headers={"Content-Length": value}, body=b"x")
            result = self.capture("/odd")
            self.assertEqual(result["status"], "failed", value)

    def test_conflicting_content_length_headers_are_refused_and_repeated_equal_ones_are_not(self):
        self.site.add("/conflict", body=b"12345", headers={})
        h = self.site.routes["/conflict"]
        self.site.routes["/conflict"] = (h[0], list(h[1].items()) + [("Content-Length", "3"), ("Content-Length", "5")], h[2], h[3])
        result = self.capture("/conflict")
        self.assertEqual(result["status"], "failed")
        self.assertIn("conflicting", result["reason"])
        self.site.add("/same", body=b"12345", headers={})
        h = self.site.routes["/same"]
        self.site.routes["/same"] = (h[0], list(h[1].items()) + [("Content-Length", "5"), ("Content-Length", "5")], h[2], h[3])
        self.assertEqual(self.capture("/same")["status"], "filed")

    def test_two_content_encoding_headers_are_refused_if_any_is_not_identity(self):
        self.site.add("/twice", headers={"Content-Encoding": "identity"})
        h = self.site.routes["/twice"]
        self.site.routes["/twice"] = (h[0], list(h[1].items()) + [("Content-Encoding", "gzip")], h[2], h[3])
        result = self.capture("/twice")
        self.assertEqual(result["status"], "failed")
        self.assertIn("encoded", result["reason"])

    def test_a_body_that_is_compressed_or_binary_is_not_taken_for_a_page(self):
        for label, body in {"gzip": b"\x1f\x8b\x08\x00" + b"x" * 50, "binary": b"<html>\x00\x01\x02" + b"\xff" * 100}.items():
            self.site.add(f"/{label}", body=body, content_type=None)
            result = self.capture(f"/{label}")
            self.assertEqual(result["status"], "failed", label)
            self.assertIn("binary", result["reason"], label)

    def test_text_from_the_server_is_cleaned_before_it_is_stored_as_a_reason(self):
        self.site.add("/evil", body=b"x", content_type="application/\x1b[31mred ")
        result = self.capture("/evil")
        self.assertEqual(result["status"], "failed")
        stored = stages.read(self.store, result["book_id"], result["version_id"])["stages"]["fetched"]["reason"]
        for text in (result["reason"], stored):
            self.assertNotIn("\x1b", text)
        self.assertIn("not a web page", stored)


class IdentityIndexTest(CaptureCase):
    def test_the_first_book_to_claim_a_key_keeps_it(self):
        self.ident.register("url", "http://x/", "BOOK-ONE")
        self.ident.register("url", "http://x/", "BOOK-TWO")
        self.assertEqual(self.ident.lookup("url", "http://x/"), "BOOK-ONE")
        self.ident.reassign("url", "http://x/", "BOOK-TWO")
        self.assertEqual(self.ident.lookup("url", "http://x/"), "BOOK-TWO")

    def test_a_rebuild_ignores_books_that_are_not_active(self):
        first = self.store.create_book(title="", kind="web page", identity_keys={"url": "http://same/"})
        second = self.store.create_book(title="", kind="web page", identity_keys={"url": "http://other/",
                                                                                   "url_alias": ["http://same/"]})
        self.store.set_state(first, "duplicate")  # the earlier book is a duplicate and must not claim the address
        self.ident.rebuild(self.store)
        self.assertEqual(self.ident.lookup("url", "http://same/"), second)


class RefusalTest(CaptureCase):
    def assert_failed_and_recorded(self, result, fragment):
        self.assertEqual(result["status"], "failed")
        self.assertIn(fragment, result["reason"])
        book, version = result["book_id"], result["version_id"]
        entry = stages.read(self.store, book, version)["stages"]["fetched"]
        self.assertEqual(entry["status"], "failed")
        self.assertIn(fragment, entry["reason"])
        self.assertIsNone(self.store.payload_dir(book, version, "original"))

    def test_a_page_over_the_size_cap_is_refused_with_the_reason(self):
        self.site.add("/big", body=b"x" * 5000, headers={"Content-Length": "5000"})
        result = self.capture("/big", max_bytes=1000)
        self.assert_failed_and_recorded(result, "larger than")

    def test_a_declared_length_over_the_cap_is_refused_before_the_body_is_read(self):
        self.site.add("/claims", body=b"tiny", headers={"Content-Length": str(10 ** 9)})
        result = self.capture("/claims", max_bytes=1000)
        self.assert_failed_and_recorded(result, "larger than")
        self.assertIn("says", result["reason"])  # refused on the header, not after reading

    def test_a_body_shorter_than_its_declared_length_is_refused_not_stored_as_a_page(self):
        self.site.add("/cut", body=b"z" * 300, headers={"Content-Length": "1000"})
        result = self.capture("/cut")
        self.assert_failed_and_recorded(result, "ended early")
        self.assertEqual(self.capture("/cut")["status"], "failed")  # and it is retried, not held as complete

    def test_a_response_that_stalls_before_its_headers_end_hits_the_total_deadline(self):
        class Stall(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                try:
                    self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                    self.wfile.flush()
                    time.sleep(2)
                    self.wfile.write(b"Content-Type: text/html\r\n\r\nhi")
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Stall)
        server.daemon_threads = True
        threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        started = time.monotonic()
        result = self.capture(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5, total_timeout=0.6)
        self.assertLess(time.monotonic() - started, 1.6)
        self.assert_failed_and_recorded(result, "timed out")

    def test_a_response_that_arrives_encoded_is_refused_because_none_was_asked_for(self):
        self.site.add("/zipped", body=b"\x1f\x8b not really gzip", headers={"Content-Encoding": "gzip"})
        self.assert_failed_and_recorded(self.capture("/zipped"), "encoded")
        self.site.add("/plain", headers={"Content-Encoding": "identity"})
        filed = self.capture("/plain")
        self.assertEqual(filed["status"], "filed")
        kept = self.store.read_version(filed["book_id"], filed["version_id"])["source"]["headers"]
        self.assertEqual(kept["content-encoding"], "identity")

    def test_a_page_that_grows_past_the_cap_without_a_length_is_refused(self):
        self.site.add("/stream", body=b"y" * 5000)  # no Content-Length: read until the connection closes
        result = self.capture("/stream", max_bytes=1000)
        self.assert_failed_and_recorded(result, "larger than")

    def test_a_slow_server_times_out(self):
        self.site.add("/slow", delay=3)
        started = time.monotonic()
        result = self.capture("/slow", timeout=0.4, total_timeout=1)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assert_failed_and_recorded(result, "timed out")

    def test_a_server_that_drips_bytes_hits_the_total_deadline(self):
        class Drip(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Drip)
        server.daemon_threads = True
        threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        started = time.monotonic()
        result = self.capture(f"http://127.0.0.1:{server.server_address[1]}/", timeout=2, total_timeout=0.8)
        self.assertLess(time.monotonic() - started, 4)
        self.assert_failed_and_recorded(result, "timed out")

    def test_an_error_status_is_a_recorded_failure(self):
        self.site.add("/gone", status=404, body=b"no")
        self.assert_failed_and_recorded(self.capture("/gone"), "HTTP 404")

    def test_something_that_is_not_a_web_page_is_refused(self):
        self.site.add("/doc", body=b"%PDF-1.4", content_type="application/pdf")
        self.assert_failed_and_recorded(self.capture("/doc"), "not a web page")

    def test_a_page_with_no_content_type_is_accepted(self):
        self.site.add("/bare", content_type=None)
        self.assertEqual(self.capture("/bare")["status"], "filed")

    def test_a_failed_fetch_is_retried_into_the_same_book(self):
        self.site.add("/flaky", status=503, body=b"later")
        failed = self.capture("/flaky")
        self.assertEqual(failed["status"], "failed")
        self.site.add("/flaky")
        again = self.capture("/flaky")
        self.assertEqual(again["status"], "filed")
        self.assertEqual((again["book_id"], again["version_id"]), (failed["book_id"], failed["version_id"]))
        self.assertEqual(self.store.list_books(), [failed["book_id"]])
        self.assertEqual(stages.read(self.store, again["book_id"], again["version_id"])["stages"]["fetched"]["status"], "done")
        self.assertEqual(self.store.read_book(again["book_id"])["identity_keys"]["url"], self.site.url("/flaky"))
        self.assertEqual(self.site.count("/flaky"), 2)

    def test_a_stop_after_the_page_is_filed_but_before_its_stage_is_marked_is_adopted_without_a_second_download(self):
        self.site.add("/page")
        with mock.patch.object(capture_url.stages, "mark", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("/page")
        (book,) = self.store.list_books()
        version = self.store.read_book(book)["current_version"]
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "pending")
        self.assertIsNotNone(self.store.payload_dir(book, version, "original"))
        again = self.capture("/page")
        self.assertEqual((again["status"], again["book_id"]), ("held", book))
        self.assertEqual(self.site.count("/page"), 1)  # not fetched a second time
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertEqual(self.ident.lookup("sha256", hashlib.sha256(PAGE).hexdigest()), book)
        self.store.verify_payload(book, version, "original")

    def test_a_stop_after_a_redirected_page_is_filed_is_resumed_and_not_taken_for_a_duplicate(self):
        self.site.add("/page")
        self.site.add("/old", body=b"", status=302, headers={"Location": self.site.url("/page")}, content_type=None)
        # stop after the page is filed and before the addresses and hash are recorded
        with mock.patch.object(capture_url, "_register_from_source", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("/old")
        (book,) = self.store.list_books()
        again = self.capture("/old")  # the address that was asked for must lead back to the unfinished book
        self.assertEqual((again["status"], again["book_id"]), ("held", book))
        self.assertEqual(self.site.count("/page"), 1)
        self.assertEqual(self.store.list_books(), [book])
        version = self.store.read_book(book)["current_version"]
        self.assertEqual(stages.read(self.store, book, version)["stages"]["fetched"]["status"], "done")
        self.assertNotIn("sighting", [e["event"] for e in self.store.read_events(book)])
        self.assertEqual(self.capture("/page")["status"], "held")

    def test_another_address_that_redirects_to_a_failed_candidate_fills_it_in_rather_than_duplicating_it(self):
        self.site.add("/target", status=503, body=b"later")
        failed = self.capture("/target")
        self.assertEqual(failed["status"], "failed")
        self.site.add("/target")
        self.site.add("/via", body=b"", status=302, headers={"Location": self.site.url("/target")}, content_type=None)
        result = self.capture("/via")
        self.assertEqual((result["status"], result["book_id"]), ("filed", failed["book_id"]))
        self.assertEqual(self.store.list_books(), [failed["book_id"]])
        self.assertNotIn("sighting", [e["event"] for e in self.store.read_events(failed["book_id"])])
        self.assertEqual(self.ident.lookup("url", self.site.url("/via")), failed["book_id"])
        self.assertEqual(self.capture("/via")["status"], "held")

    def test_a_stop_after_the_book_is_made_but_before_its_version_resumes_into_the_same_book(self):
        self.site.add("/page")
        with mock.patch.object(self.store, "add_version", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("/page")
        (book,) = self.store.list_books()
        self.assertIsNone(self.store.read_book(book)["current_version"])
        again = self.capture("/page")
        self.assertEqual((again["status"], again["book_id"]), ("filed", book))
        self.assertEqual(self.store.list_books(), [book])

    def test_a_stale_index_entry_for_a_book_that_was_never_made_is_ignored(self):
        self.site.add("/page")
        self.ident.register("url", self.site.url("/page"), ids_new())
        result = self.capture("/page")
        self.assertEqual(result["status"], "filed")
        self.assertEqual(self.ident.lookup("url", self.site.url("/page")), result["book_id"])

    def test_a_filed_copy_that_fails_its_check_is_reported_and_not_overwritten(self):
        self.site.add("/page")
        with mock.patch.object(capture_url.stages, "mark", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("/page")
        (book,) = self.store.list_books()
        version = self.store.read_book(book)["current_version"]
        path = self.store.payload_dir(book, version, "original")
        os.chmod(path, 0o700)
        os.chmod(os.path.join(path, "page.html"), 0o600)
        with open(os.path.join(path, "page.html"), "wb") as f:
            f.write(b"damaged")
        result = self.capture("/page")
        self.assertEqual(result["status"], "failed")
        self.assertIn("page.html", result["reason"])
        with open(os.path.join(path, "page.html"), "rb") as f:
            self.assertEqual(f.read(), b"damaged")

    def test_a_resumed_page_capture_gets_a_filed_event_once(self):
        self.site.add("/page")
        with mock.patch.object(self.store, "append_event", side_effect=OSError("stopped")):
            with self.assertRaises(OSError):
                self.capture("/page")
        (book,) = self.store.list_books()
        self.assertEqual(self.store.read_events(book), [])
        self.capture("/page")
        events = self.store.read_events(book)
        self.assertEqual([e["event"] for e in events], ["filed"])
        self.assertTrue(events[0]["resumed"])
        self.capture("/page")
        self.assertEqual(len(self.store.read_events(book)), 1)

    def test_a_retry_that_turns_out_to_duplicate_another_book_is_skipped_not_filed_twice(self):
        self.site.add("/page")
        held = self.capture("/page")
        self.site.add("/later", status=503, body=b"x")
        failed = self.capture("/later")
        self.site.add("/later")  # now the same bytes as /page
        result = self.capture("/later")
        self.assertEqual((result["status"], result["book_id"]), ("duplicate", held["book_id"]))
        entry = stages.read(self.store, failed["book_id"], failed["version_id"])["stages"]["fetched"]
        self.assertEqual(entry["status"], "skipped")
        self.assertIn(held["book_id"], entry["reason"])
        self.assertEqual(self.store.read_book(failed["book_id"])["state"], "duplicate")
        self.assertEqual(self.ident.lookup("url", self.site.url("/later")), held["book_id"])
        self.ident.rebuild(self.store)  # the duplicate candidate no longer claims the address
        self.assertEqual(self.ident.lookup("url", self.site.url("/later")), held["book_id"])

    def test_a_loopback_address_is_refused_by_default_before_anything_is_recorded(self):
        self.site.add("/page")
        with self.assertRaises(KbError) as cm:
            capture_url.capture(self.store, self.ident, self.site.url("/page"))
        self.assertIn("private", str(cm.exception))
        self.assertEqual(self.site.count(), 0)
        self.assertEqual(self.store.list_books(), [])

    def test_a_bad_address_is_refused_before_anything_is_recorded(self):
        for bad in ("file:///etc/passwd", "http://user:pw@example.com/", "ftp://example.com/"):
            with self.assertRaises(KbError):
                self.capture(bad)
        self.assertEqual(self.store.list_books(), [])

    def test_a_failing_write_guard_refuses_before_any_request(self):
        self.site.add("/page")
        os.remove(os.path.join(self.bulk, library.MARKER))
        with self.assertRaises(KbError):
            self.capture("/page")
        self.assertEqual(self.site.count(), 0)


class CommandLineTest(CaptureCase):
    def run_kb(self, *args):
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR,
                              env=dict(os.environ, KB_CONFIG_DIR=self.cfg), capture_output=True, text=True, timeout=60)

    def test_capture_through_the_command_line(self):
        self.site.add("/page")
        first = self.run_kb("capture-url", self.site.url("/page"), "--allow-private")
        self.assertEqual(first.returncode, 0, first.stderr)
        out = json.loads(first.stdout)
        self.assertEqual(out["status"], "filed")
        second = self.run_kb("capture-url", self.site.url("/page"), "--allow-private")
        self.assertEqual(json.loads(second.stdout)["status"], "held")
        self.assertEqual(self.site.count("/page"), 1)

    def test_a_private_address_is_refused_without_the_flag(self):
        self.site.add("/page")
        done = self.run_kb("capture-url", self.site.url("/page"))
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr.startswith("refused: "), done.stderr)
        self.assertEqual(self.site.count(), 0)

    def test_a_failed_fetch_exits_nonzero_and_says_why(self):
        self.site.add("/gone", status=404, body=b"no")
        done = self.run_kb("capture-url", self.site.url("/gone"), "--allow-private")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(json.loads(done.stdout)["status"], "failed")
        self.assertIn("HTTP 404", done.stderr)


class StoreAdditionsTest(StoreCase):
    def test_events_are_appended_and_read_back_in_order(self):
        book = self.store.create_book(title="t", kind="web page")
        self.store.append_event(book, "filed", note="one")
        self.store.append_event(book, "sighting", note="two")
        events = self.store.read_events(book)
        self.assertEqual([(e["event"], e["note"]) for e in events], [("filed", "one"), ("sighting", "two")])
        self.assertTrue(all("at" in e for e in events))
        with self.assertRaises(KbError):
            self.store.append_event(book, "bad name!")

    def test_identity_keys_are_merged_without_losing_earlier_ones(self):
        book = self.store.create_book(title="t", kind="web page", identity_keys={"url": "http://a/"})
        self.store.merge_identity_keys(book, set_keys={"url": "http://b/"}, add_keys={"url_alias": ["http://a/"]})
        self.store.merge_identity_keys(book, add_keys={"url_alias": ["http://a/", "http://c/"], "sha256": ["ab"]})
        keys = self.store.read_book(book)["identity_keys"]
        self.assertEqual(keys, {"url": "http://b/", "url_alias": ["http://a/", "http://c/"], "sha256": ["ab"]})

    def test_a_book_can_be_made_under_an_id_chosen_beforehand_but_never_a_used_one(self):
        chosen = ids_new()
        self.assertEqual(self.store.create_book(title="t", kind="web page", book_id=chosen), chosen)
        with self.assertRaises(KbError) as cm:
            self.store.create_book(title="t", kind="web page", book_id=chosen)
        self.assertIn("already used", str(cm.exception))
        with self.assertRaises(KbError):
            self.store.create_book(title="t", kind="web page", book_id="../x")
        self.assertEqual(self.store.list_books(), [chosen])

    def test_a_version_source_can_be_replaced(self):
        book = self.store.create_book(title="t", kind="web page")
        version = self.store.add_version(book, source={"a": 1})
        self.store.set_version_source(book, version, {"b": 2})
        self.assertEqual(self.store.read_version(book, version)["source"], {"b": 2})


if __name__ == "__main__":
    unittest.main()
