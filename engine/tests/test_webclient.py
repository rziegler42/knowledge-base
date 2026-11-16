"""The shared web client (`kb/webclient.py`, Increment B of the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`).

Every request of the unattended crawl goes through `webclient.get`. The tests use a fake name resolver and a fake server on `127.0.0.1`; the one place the client dials is the module-level seam `webclient._dial`, which the tests
point at the fake server (the client accepts only ports 80 and 443, so a test cannot name the server's port). No test touches the real network.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_webclient`."""
import ipaddress
import random
import socket
import socketserver
import threading
import time
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)

from kb import capture_url, webclient

PUBLIC = {"a.test": "93.184.216.34", "www.a.test": "93.184.216.34", "alias.test": "93.184.216.34", "b.test": "93.184.216.35", "c.test": "93.184.216.36", "d.test": "93.184.216.37"}
PRIVATE = {"internal.test": "10.0.0.5", "metadata.test": "169.254.169.254", "loop.test": "127.0.0.1"}
CANARY = "CANARY-7f3a91-do-not-leak"


def reply(status=200, headers=(), body=b"", ctype="text/html", length=True):
    lines = [f"HTTP/1.1 {status} X"]
    if ctype is not None:
        lines.append(f"Content-Type: {ctype}")
    if length:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: close")
    lines += [f"{k}: {v}" for k, v in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def redirect(location, status=302):
    return reply(status, [("Location", location)], b"", ctype="text/html")


class Server:
    """A raw TCP server on the local machine that records each request and answers from `routes`: path -> bytes, or a function (connection, path, headers) that writes by itself."""

    def __init__(self):
        self.routes, self.hits = {}, []
        self.lock = threading.Lock()
        self.inflight = self.max_inflight = 0
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                conn = self.request
                conn.settimeout(5)
                data = b""
                try:
                    while b"\r\n\r\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                    head = data.split(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")
                    path = head[0].split(" ")[1]
                    headers = {}
                    for line in head[1:]:
                        key, _, value = line.partition(":")
                        headers[key.strip().lower()] = value.strip()
                    with outer.lock:
                        outer.hits.append((path, headers))
                        outer.inflight += 1
                        outer.max_inflight = max(outer.max_inflight, outer.inflight)
                    try:
                        route = outer.routes.get(path) or reply(404, body=b"not found")
                        out = route(conn, path, headers) if callable(route) else route
                        if out is not None:
                            conn.sendall(out)
                    finally:
                        with outer.lock:
                            outer.inflight -= 1
                except OSError:
                    pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class PeerSock:
    """A real connection to the fake server that reports the peer address the client asked for, as a real connection to that address would."""

    def __init__(self, sock, peer):
        self._sock, self._peer, self.closed = sock, peer, False

    def getpeername(self):
        return (self._peer, 80)

    def close(self):
        self.closed = True
        self._sock.close()

    def __getattr__(self, name):
        return getattr(self._sock, name)


class Net(unittest.TestCase):
    def setUp(self):
        self.srv = Server()
        self.addCleanup(self.srv.close)
        self.dns = {name: [ip] for name, ip in {**PUBLIC, **PRIVATE}.items()}
        self.lookups, self.dials, self.socks = [], [], []
        webclient.PACER.reset()
        self.addCleanup(webclient.PACER.reset)

        def getaddrinfo(host, port, *a, **k):
            self.lookups.append(host)
            try:
                ips = [str(ipaddress.ip_address(host))]
            except ValueError:
                if host not in self.dns:
                    raise socket.gaierror(8, "no such name")
                ips = self.dns[host]
            return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port) if ":" not in ip else (ip, port, 0, 0)) for ip in ips]

        def dial(address, timeout):
            self.dials.append(address)
            sock = PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), address[0])
            self.socks.append(sock)
            return sock

        for patcher in (mock.patch("socket.getaddrinfo", getaddrinfo), mock.patch.object(webclient, "_dial", dial)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def policy(self, **kw):
        kw.setdefault("user_agent", "test-agent/1")
        kw.setdefault("gap", 0.0)
        kw.setdefault("jitter", 0.0)
        return webclient.Policy(**kw)

    def get(self, url, policy=None, **kw):
        kw.setdefault("max_bytes", 100_000)
        kw.setdefault("timeout", 3)
        return webclient.get(url, policy=policy or self.policy(), **kw)

    def ok(self, body=b"<html>hello</html>", **kw):
        return reply(200, body=body, **kw)


class Basics(Net):
    def test_a_page_comes_back_as_status_headers_and_body_with_the_final_address(self):
        self.srv.routes["/p"] = self.ok()
        status, headers, body = self.get("http://a.test/p")
        self.assertEqual((status, body), (200, b"<html>hello</html>"))
        self.assertEqual(headers["content-type"], "text/html")
        result = self.get("http://A.test./p#frag")
        self.assertEqual(result.final, "http://a.test/p")
        self.assertEqual(self.dials[-1], ("93.184.216.34", 80))

    def test_the_host_header_names_the_site_and_the_request_asks_for_an_unencoded_page(self):
        self.srv.routes["/p?x=1"] = self.ok()
        self.get("http://a.test/p?x=1&utm_source=z")
        path, headers = self.srv.hits[0]
        self.assertEqual(path, "/p?x=1")
        self.assertEqual((headers["host"], headers["accept-encoding"], headers["user-agent"]), ("a.test", "identity", "test-agent/1"))

    def test_a_status_other_than_200_comes_back_with_its_headers_and_no_body(self):
        self.srv.routes["/gone"] = reply(404, [("X-RateLimit-Remaining", "0")], b"nothing here")
        status, headers, body = self.get("http://a.test/gone")
        self.assertEqual((status, body, headers["x-ratelimit-remaining"]), (404, b"", "0"))


    def test_every_connection_is_closed_after_a_page_and_after_a_failure(self):
        self.srv.routes["/p"] = self.ok()
        self.srv.routes["/bad"] = reply(200, [("Content-Encoding", "gzip")], b"x")
        self.get("http://a.test/p")
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/bad")
        self.assertEqual(len(self.socks), 2)
        self.assertTrue(all(sock.closed for sock in self.socks))

    def test_no_descriptor_is_left_to_the_garbage_collector_after_a_refused_response(self):
        import gc
        import warnings
        self.srv.routes["/gz"] = reply(200, [("Content-Encoding", "gzip")], b"x")
        self.srv.routes["/img"] = reply(200, body=b"x" * 5000, ctype="image/png")
        self.srv.routes["/p"] = self.ok()
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            for path in ("/gz", "/img", "/p"):
                try:
                    self.get("http://a.test" + path)
                except webclient.FetchError:
                    pass
            self.socks.clear()
            gc.collect()
        self.assertEqual([str(w.message) for w in seen if issubclass(w.category, ResourceWarning)], [])

    def test_a_server_that_drops_the_connection_is_a_failure_with_a_fixed_message(self):
        self.srv.routes["/p"] = lambda conn, path, headers: None
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p")
        self.assertEqual(str(caught.exception), "network error: RemoteDisconnected")

    def test_an_ipv6_address_is_written_in_brackets_in_the_host_header(self):
        self.srv.routes["/p"] = self.ok()
        self.get("http://[2001:4860:4860::8888]/p")
        self.assertEqual(self.srv.hits[0][1]["host"], "[2001:4860:4860::8888]")

    def test_tls_is_started_for_the_name_asked_for(self):
        with mock.patch("ssl.create_default_context") as context:
            sentinel = object()
            context.return_value.wrap_socket.return_value = sentinel
            self.assertIs(webclient._tls_wrap("raw socket", "a.test"), sentinel)
        context.return_value.wrap_socket.assert_called_once_with("raw socket", server_hostname="a.test")

    def test_a_failed_tls_handshake_is_a_failed_fetch_and_the_raw_socket_is_closed(self):
        import ssl
        for error, text in ((ssl.SSLCertVerificationError(1, "bad certificate for secret-host"), "certificate"), (ssl.SSLError(1, "handshake failure"), "SSLError"),
                            (socket.timeout("slow"), "timed out"), (ConnectionResetError(54, "reset"), "ConnectionResetError")):
            with self.subTest(type(error).__name__):
                del self.socks[:]
                with mock.patch.object(webclient, "_tls_wrap", side_effect=error):
                    with self.assertRaises(webclient.FetchError) as caught:
                        self.get("https://a.test/p")
                self.assertIn(text, str(caught.exception))
                self.assertNotIn("secret-host", str(caught.exception))
                self.assertTrue(all(sock.closed for sock in self.socks) and self.socks)

    def test_the_checked_address_is_dialled_as_capture_url_dials_it(self):
        dialled = []
        answers = [["93.184.216.34"], ["10.0.0.5"]]

        def getaddrinfo(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers[0]]

        pair = socket.socketpair()
        self.addCleanup(pair[1].close)
        with mock.patch("socket.getaddrinfo", getaddrinfo):
            with mock.patch("socket.create_connection", lambda address, timeout: dialled.append(address) or pair[0]):
                capture_sock = capture_url._connect_checked("same.test", 80, 3, False, [])
                capture_sock.close()
            self.assertEqual(dialled, [("93.184.216.34", 80)])   # the address that was checked, as the client dials it in its own test above
            answers[0] = ["10.0.0.5"]
            with self.assertRaises(capture_url.PolicyError):
                capture_url._connect_checked("same.test", 80, 3, False, [])
            with self.assertRaises(webclient.Refused):
                self.get("http://same.test/p")
        self.assertEqual(self.dials, [])

    def test_a_peer_that_is_not_an_address_is_refused(self):
        def dial(address, timeout):
            return PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), "not-an-address")

        with mock.patch.object(webclient, "_dial", dial):
            with self.assertRaises(webclient.Refused):
                self.get("http://a.test/p")

    def test_a_user_agent_that_is_not_printable_text_is_refused_before_a_request(self):
        for bad in ("agent\r\nX-Evil: 1", "", None, 5, "caf\xe9"):
            with self.subTest(repr(bad)):
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/p", self.policy(user_agent=bad))
        self.assertEqual(self.dials, [])

    def test_an_address_that_is_not_canonical_or_not_http_is_refused_before_anything_happens(self):
        for bad in ("ftp://a.test/", "http://a.test:8080/", "http://user:pw@a.test/", "a.test/x", "http://a.test/" + "x" * 3000, ""):
            with self.subTest(bad[:40]):
                with self.assertRaises(webclient.Refused):
                    self.get(bad)
        self.assertEqual((self.lookups, self.dials), ([], []))

    def test_the_address_checks_are_the_ones_of_capture_url_and_not_copies(self):
        self.assertIs(webclient.resolve_checked, capture_url.resolve_checked)
        self.assertIs(webclient.is_public, capture_url.is_public)

    def test_a_name_that_does_not_resolve_is_a_failed_fetch_and_not_a_refusal(self):
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://nowhere.test/")
        self.assertNotIsInstance(caught.exception, webclient.Refused)

    def test_a_refusal_is_a_fetch_error_so_callers_that_catch_one_catch_both(self):
        self.assertTrue(issubclass(webclient.Refused, webclient.FetchError))
        self.assertTrue(issubclass(webclient.Refused, Exception))


class Addresses(Net):
    def test_a_dns_answer_that_changes_after_the_check_is_harmless(self):
        self.srv.routes["/p"] = self.ok()
        answers = iter([["93.184.216.34"], ["10.0.0.5"], ["127.0.0.1"]])
        real = socket.getaddrinfo

        def getaddrinfo(host, port, *a, **k):
            if host != "rebind.test":
                return real(host, port, *a, **k)   # the fake server's own address, looked up by the test's dial
            self.lookups.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in next(answers)]

        with mock.patch("socket.getaddrinfo", getaddrinfo):
            status, _, _ = self.get("http://rebind.test/p")
        self.assertEqual(status, 200)
        self.assertEqual(self.lookups.count("rebind.test"), 1)    # one lookup: nothing to rebind
        self.assertEqual(self.dials, [("93.184.216.34", 80)])     # the connection went to the address that was checked

    def test_a_connection_whose_peer_is_not_the_checked_address_is_refused(self):
        def dial(address, timeout):
            self.dials.append(address)
            return socket.create_connection(("127.0.0.1", self.srv.port), timeout)   # the peer is 127.0.0.1, not the address asked for

        with mock.patch.object(webclient, "_dial", dial):
            with self.assertRaises(webclient.Refused):
                self.get("http://a.test/p")
        self.assertEqual(self.srv.hits, [])

    def test_a_peer_written_another_way_is_the_same_peer(self):
        self.srv.routes["/p"] = self.ok()
        self.dns["v6.test"] = ["2001:4860:4860:0:0:0:0:8888"]

        def dial(address, timeout):
            self.dials.append(address)
            return PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), "2001:4860:4860::8888")

        with mock.patch.object(webclient, "_dial", dial):
            self.assertEqual(self.get("http://v6.test/p")[0], 200)

    def test_private_loopback_link_local_and_metadata_addresses_are_refused_in_every_spelling(self):
        for url in ("http://internal.test/", "http://metadata.test/latest/", "http://loop.test/", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/", "http://10.1.2.3/",
                    "http://192.168.0.1/", "http://[::ffff:127.0.0.1]/", "http://[fe80::1]/", "http://0.0.0.0/", "http://[fd00::1]/", "http://100.64.0.1/"):
            with self.subTest(url):
                with self.assertRaises(webclient.Refused):
                    self.get(url)
        self.assertEqual((self.dials, self.srv.hits), ([], []))

    def test_a_name_with_one_private_answer_among_public_ones_is_refused(self):
        self.dns["mixed.test"] = ["93.184.216.34", "10.0.0.5"]
        with self.assertRaises(webclient.Refused):
            self.get("http://mixed.test/")
        self.assertEqual(self.dials, [])

    def test_private_addresses_pass_only_where_the_policy_allows_them(self):
        self.srv.routes["/p"] = self.ok()
        self.assertEqual(self.get("http://127.0.0.1/p", self.policy(allow_private=True))[0], 200)

    def test_a_connection_failure_tries_the_next_checked_address(self):
        self.dns["two.test"] = ["93.184.216.34", "93.184.216.35"]
        self.srv.routes["/p"] = self.ok()
        calls = []

        def dial(address, timeout):
            calls.append(address[0])
            if address[0] == "93.184.216.34":
                raise OSError("refused")
            return PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), address[0])

        with mock.patch.object(webclient, "_dial", dial):
            self.assertEqual(self.get("http://two.test/p")[0], 200)
        self.assertEqual(calls, ["93.184.216.34", "93.184.216.35"])

    def test_https_wraps_the_checked_connection_for_the_name_asked_for(self):
        self.srv.routes["/p"] = self.ok()
        wrapped = []

        def wrap(sock, host):
            wrapped.append(host)
            return sock

        with mock.patch.object(webclient, "_tls_wrap", wrap):
            self.assertEqual(self.get("https://a.test/p")[0], 200)
        self.assertEqual((wrapped, self.dials), (["a.test"], [("93.184.216.34", 443)]))
        self.assertEqual(self.get("http://a.test/p")[0], 200)
        self.assertEqual(wrapped, ["a.test"])   # http is not wrapped
        self.assertEqual(self.dials[-1], ("93.184.216.34", 80))


class Redirects(Net):
    def test_a_redirect_is_followed_and_the_final_address_is_reported(self):
        self.srv.routes["/old"] = redirect("http://b.test/new")
        self.srv.routes["/new"] = self.ok(b"<html>new</html>")
        result = self.get("http://a.test/old")
        self.assertEqual((result[0], result[2], result.final), (200, b"<html>new</html>", "http://b.test/new"))
        self.assertEqual([d[0] for d in self.dials], ["93.184.216.34", "93.184.216.35"])

    def test_a_relative_redirect_is_resolved_against_the_address(self):
        self.srv.routes["/dir/old"] = redirect("../new?utm_source=x&k=1")
        self.srv.routes["/new?k=1"] = self.ok()
        self.assertEqual(self.get("http://a.test/dir/old").final, "http://a.test/new?k=1")

    def test_a_redirect_to_a_private_or_odd_target_is_refused_at_any_hop(self):
        targets = ("http://127.0.0.1/x", "http://10.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://metadata.test/", "http://internal.test/", "http://[::1]/", "http://[::ffff:10.0.0.1]/",
                   "file:///etc/passwd", "ftp://b.test/x", "data:text/html,hi", "javascript:alert(1)", "http://b.test:8080/", "https://b.test:8443/", "http://b.test:22/", "http://user:pw@b.test/",
                   "http://%31%32%37.0.0.1/", "http://2130706433/", "http://b.test/" + "x" * 3000, "")
        for target in targets:
            for depth in (0, 2):
                with self.subTest(target[:50], depth=depth):
                    self.srv.hits.clear()
                    del self.dials[:]
                    self.srv.routes["/start"] = redirect("http://b.test/mid") if depth else redirect(target)
                    self.srv.routes["/mid"] = redirect("http://c.test/last")
                    self.srv.routes["/last"] = redirect(target)
                    with self.assertRaises(webclient.Refused):
                        self.get("http://a.test/start")
                    self.assertEqual(len(self.dials), 3 if depth else 1)   # never dialled the refused target

    def test_a_redirect_with_no_location_or_two_locations_is_a_failure(self):
        self.srv.routes["/none"] = reply(302)
        self.srv.routes["/two"] = reply(302, [("Location", "http://b.test/"), ("Location", "http://c.test/")])
        for path in ("/none", "/two"):
            with self.subTest(path):
                with self.assertRaises(webclient.FetchError):
                    self.get("http://a.test" + path)

    def test_at_most_five_redirects_are_followed(self):
        self.srv.routes["/loop"] = redirect("http://a.test/loop")
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/loop")
        self.assertEqual(len(self.srv.hits), 6)       # the first request and five redirects
        self.srv.hits.clear()
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/loop", self.policy(max_redirects=2))
        self.assertEqual(len(self.srv.hits), 3)

    def test_five_redirects_and_then_a_page_succeed(self):
        for n in range(5):
            self.srv.routes[f"/r{n}"] = redirect(f"http://a.test/r{n + 1}")
        self.srv.routes["/r5"] = self.ok()
        self.assertEqual(self.get("http://a.test/r0")[0], 200)

    def test_a_policy_that_follows_none_refuses_any_redirect_and_sends_no_second_request(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status):
                self.srv.hits.clear()
                self.srv.routes["/r"] = redirect("http://b.test/", status)
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/r", self.policy(follow_redirects=False))
                self.assertEqual(len(self.srv.hits), 1)

    def test_extra_headers_go_only_to_the_host_they_were_first_sent_to(self):
        self.srv.routes["/old"] = redirect("http://b.test/mid")
        self.srv.routes["/mid"] = redirect("http://a.test/back")
        self.srv.routes["/back"] = self.ok()
        self.get("http://a.test/old", self.policy(headers={"X-Custom": "one"}), headers={"X-Call": "two"})
        by_path = dict((path, headers) for path, headers in self.srv.hits)
        self.assertEqual((by_path["/old"]["x-custom"], by_path["/old"]["x-call"]), ("one", "two"))
        self.assertNotIn("x-custom", by_path["/mid"])        # another host
        self.assertNotIn("x-call", by_path["/mid"])
        self.assertEqual(by_path["/back"]["x-custom"], "one")   # back to the first host
        for headers in by_path.values():
            self.assertEqual(headers["user-agent"], "test-agent/1")
            self.assertEqual(headers["accept-encoding"], "identity")


class Limits(Net):
    def test_an_endless_stream_is_cut_by_the_size_limit(self):
        def endless(conn, path, headers):
            conn.sendall(b"HTTP/1.1 200 X\r\nContent-Type: text/html\r\n\r\n")
            while True:
                conn.sendall(b"a" * 4096)

        self.srv.routes["/p"] = endless
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p", max_bytes=50_000)
        self.assertIn("larger", str(caught.exception))

    def test_a_declared_size_over_the_limit_is_refused_before_the_body_is_read(self):
        self.srv.routes["/p"] = reply(200, [("Content-Length", "999999999")], b"x", length=False)
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p", max_bytes=1000)
        self.assertIn("larger", str(caught.exception))

    def test_a_slow_body_runs_out_of_time(self):
        def slow(conn, path, headers):
            conn.sendall(b"HTTP/1.1 200 X\r\nContent-Type: text/html\r\n\r\n")
            for _ in range(60):
                conn.sendall(b"a")
                time.sleep(0.1)

        self.srv.routes["/p"] = slow
        started = time.monotonic()
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p", total_timeout=0.6)
        self.assertIn("timed out", str(caught.exception))
        self.assertLess(time.monotonic() - started, 3)

    def test_a_stalled_download_is_cut_at_the_deadline_and_its_thread_and_socket_end(self):
        def stall(conn, path, headers):
            conn.sendall(b"HTTP/1.1 200 X\r\nContent-Type: text/html\r\nContent-Length: 50\r\n\r\nabc")
            time.sleep(3)

        self.srv.routes["/p"] = stall
        started = time.monotonic()
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/p", timeout=10, total_timeout=0.4)
        self.assertLess(time.monotonic() - started, 1.5)
        for _ in range(40):
            if not any(th.name == "kb-webclient" and th.is_alive() for th in threading.enumerate()):
                break
            time.sleep(0.05)
        self.assertFalse(any(th.name == "kb-webclient" and th.is_alive() for th in threading.enumerate()))
        self.assertTrue(all(sock.closed for sock in self.socks))

    def test_a_trickling_body_is_reported_by_the_reader_and_not_only_by_the_thread_limit(self):
        def slow(conn, path, headers):
            conn.sendall(b"HTTP/1.1 200 X\r\nContent-Type: text/html\r\n\r\n")
            for _ in range(60):
                conn.sendall(b"a")
                time.sleep(0.05)

        self.srv.routes["/p"] = slow
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p", total_timeout=0.5)
        self.assertIn("reading", str(caught.exception))

    def test_a_name_lookup_that_stalls_runs_out_of_time(self):
        def stuck(host, port, *a, **k):
            time.sleep(2)
            return []

        started = time.monotonic()
        with mock.patch("socket.getaddrinfo", stuck):
            with self.assertRaises(webclient.FetchError):
                self.get("http://slowdns.test/p", total_timeout=0.4)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_server_that_never_answers_runs_out_of_time(self):
        self.srv.routes["/p"] = lambda conn, path, headers: time.sleep(2)
        started = time.monotonic()
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/p", timeout=0.3, total_timeout=0.6)
        self.assertLess(time.monotonic() - started, 3)

    def test_an_encoded_response_is_refused_and_identity_is_not(self):
        self.srv.routes["/gz"] = reply(200, [("Content-Encoding", "gzip")], b"<html></html>")
        self.srv.routes["/two"] = reply(200, [("Content-Encoding", "identity"), ("Content-Encoding", "br")], b"<html></html>")
        self.srv.routes["/id"] = reply(200, [("Content-Encoding", "identity")], b"<html></html>")
        for path in ("/gz", "/two"):
            with self.subTest(path):
                with self.assertRaises(webclient.FetchError) as caught:
                    self.get("http://a.test" + path)
                self.assertIn("encoded", str(caught.exception))
        self.assertEqual(self.get("http://a.test/id")[0], 200)

    def test_conflicting_or_bad_content_lengths_are_refused(self):
        self.srv.routes["/c"] = reply(200, [("Content-Length", "5"), ("Content-Length", "6")], b"<html>", length=False)
        self.srv.routes["/n"] = reply(200, [("Content-Length", "abc")], b"<html>", length=False)
        self.srv.routes["/u"] = reply(200, [("Content-Length", "\xb2")], b"<html>", length=False)
        for path in ("/c", "/n", "/u"):
            with self.subTest(path):
                with self.assertRaises(webclient.FetchError):
                    self.get("http://a.test" + path)

    def test_a_body_that_ends_early_is_a_failure(self):
        self.srv.routes["/p"] = reply(200, [("Content-Length", "100")], b"<html>", length=False)
        with self.assertRaises(webclient.FetchError) as caught:
            self.get("http://a.test/p")
        self.assertIn("ended early", str(caught.exception))

    def test_too_many_headers_are_a_failure_and_not_a_crash(self):
        self.srv.routes["/p"] = reply(200, [(f"X-H{n}", "v") for n in range(500)], b"<html></html>")
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/p")

    def test_a_reply_that_is_not_http_is_a_failure(self):
        self.srv.routes["/p"] = b"\x00\x01garbage with no status line\r\n\r\n"
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/p")

    def test_the_body_may_be_exactly_the_limit_and_not_one_more(self):
        self.srv.routes["/p"] = self.ok(b"a" * 1000)
        self.assertEqual(len(self.get("http://a.test/p", max_bytes=1000)[2]), 1000)
        with self.assertRaises(webclient.FetchError):
            self.get("http://a.test/p", max_bytes=999)


class TypeGate(Net):
    def test_a_response_with_no_content_type_is_refused(self):
        self.srv.routes["/p"] = reply(200, body=b"<html></html>", ctype=None)
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/p")

    def test_a_type_outside_the_policys_types_is_refused_and_a_parameter_is_ignored(self):
        self.srv.routes["/img"] = reply(200, body=b"<html></html>", ctype="image/png")
        self.srv.routes["/cs"] = reply(200, body=b"<html></html>", ctype="Text/HTML; charset=utf-8")
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/img")
        self.assertEqual(self.get("http://a.test/cs")[0], 200)

    def test_a_body_that_is_not_what_its_type_says_is_refused(self):
        bodies = {"pdf": b"%PDF-1.7 not a page", "gzip": b"\x1f\x8bXYZ packed", "zip": b"PK\x03\x04 zipped", "nul": b"<html>\x00\x00</html>"}
        for name, body in bodies.items():
            with self.subTest(name):
                self.srv.routes["/p"] = self.ok(body)
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/p")

    def test_a_pdf_must_start_like_one_and_a_page_posing_as_a_pdf_is_refused(self):
        policy = self.policy(types=("application/pdf",))
        self.srv.routes["/real"] = reply(200, body=b"%PDF-1.7\n...", ctype="application/pdf")
        self.srv.routes["/fake"] = reply(200, body=b"<html>not a pdf</html>", ctype="application/pdf")
        self.srv.routes["/page"] = reply(200, body=b"<html></html>", ctype="text/html")
        self.assertEqual(self.get("http://a.test/real", policy)[0], 200)
        for path in ("/fake", "/page"):
            with self.subTest(path):
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test" + path, policy)

    def test_json_and_xml_must_look_like_json_and_xml(self):
        policy = self.policy(types=("application/json", "application/atom+xml", "text/xml"))
        self.srv.routes["/j"] = reply(200, body=b' \n{"a": 1}', ctype="application/json")
        self.srv.routes["/jl"] = reply(200, body=b"[1, 2]", ctype="application/json")
        self.srv.routes["/x"] = reply(200, body=b'\n<?xml version="1.0"?><feed/>', ctype="application/atom+xml")
        self.srv.routes["/bad"] = reply(200, body=b"<html>not json</html>", ctype="application/json")
        self.srv.routes["/badx"] = reply(200, body=b"{not xml}", ctype="text/xml")
        for path in ("/j", "/jl", "/x"):
            with self.subTest(path):
                self.assertEqual(self.get("http://a.test" + path, policy)[0], 200)
        for path in ("/bad", "/badx"):
            with self.subTest(path):
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test" + path, policy)

    def test_a_refusal_by_the_gate_does_not_read_the_whole_body(self):
        def big(conn, path, headers):
            conn.sendall(b"HTTP/1.1 200 X\r\nContent-Type: image/png\r\nContent-Length: 99999999\r\n\r\n")
            conn.sendall(b"a" * 1000)
            time.sleep(1)

        self.srv.routes["/p"] = big
        started = time.monotonic()
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/p")
        self.assertLess(time.monotonic() - started, 0.8)


class Headers(Net):
    def test_the_user_agent_and_extra_headers_are_exactly_what_the_caller_chose(self):
        self.srv.routes["/p"] = self.ok()
        self.get("http://a.test/p", self.policy(user_agent="Mozilla/5.0 (test)", headers={"Accept-Language": "en"}), headers={"X-One": "1"})
        headers = self.srv.hits[0][1]
        self.assertEqual((headers["user-agent"], headers["accept-language"], headers["x-one"]), ("Mozilla/5.0 (test)", "en", "1"))
        self.assertNotIn("cookie", headers)
        self.assertNotIn("authorization", headers)

    def test_headers_that_would_change_what_the_client_checks_are_refused(self):
        for name in ("Host", "host", "Accept-Encoding", "User-Agent", "Content-Length", "Transfer-Encoding", "Connection", "Upgrade", "Proxy-Authorization"):
            with self.subTest(name):
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/p", headers={name: "x"})
        self.assertEqual(self.dials, [])

    def test_a_header_with_a_line_break_a_bad_name_or_a_bad_type_is_refused_before_a_request(self):
        for headers in ({"X-A": "a\r\nX-B: b"}, {"X-A": "a\nb"}, {"X-A": "a\x00"}, {"X A": "a"}, {"": "a"}, {"X-A": 5}, {5: "a"}, {"X-A:": "a"}):
            with self.subTest(repr(headers)):
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/p", headers=headers)
        self.assertEqual(self.dials, [])

    def credentials(self, **kw):
        base = dict(credential_headers={"Auth-Key": CANARY}, credential_host="a.test", follow_redirects=False)
        base.update(kw)
        return self.policy(**base)

    def test_a_credential_is_refused_unless_every_condition_holds(self):
        cases = {
            "follows redirects": self.credentials(follow_redirects=True),
            "no credential host": self.credentials(credential_host=None),
            "another host": self.credentials(credential_host="b.test"),
            "a host not in canonical form": self.credentials(credential_host="A.test."),
            "a host with a port": self.credentials(credential_host="a.test:443"),
        }
        for what, policy in cases.items():
            with self.subTest(what):
                with self.assertRaises(webclient.Refused):
                    self.get("https://a.test/p", policy)
        with self.assertRaises(webclient.Refused):     # an http address
            self.get("http://a.test/p", self.credentials())
        with self.assertRaises(webclient.Refused):     # the address is another host than the credential host
            self.get("https://www.a.test/p", self.credentials())
        with self.assertRaises(webclient.Refused):     # carried in the ordinary headers of the call
            self.get("https://a.test/p", self.credentials(credential_headers={"Host": CANARY}))
        self.assertEqual((self.lookups, self.dials, self.srv.hits), ([], [], []))

    def test_a_credential_is_sent_over_https_to_its_host_when_every_condition_holds(self):
        self.srv.routes["/p"] = self.ok()
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            self.assertEqual(self.get("https://a.test/p", self.credentials())[0], 200)
        self.assertEqual(self.srv.hits[0][1]["auth-key"], CANARY)

    def test_a_credential_is_not_sent_on_a_redirect_which_is_refused_and_the_canary_is_in_no_error(self):
        self.srv.routes["/r"] = redirect("https://b.test/p")
        self.srv.routes["/gone"] = reply(500, body=b"error")
        self.srv.routes["/enc"] = reply(200, [("Content-Encoding", "gzip")], b"x")
        self.srv.routes["/big"] = reply(200, [("Content-Length", "99999999")], b"x", length=False)
        self.srv.routes["/ct"] = reply(200, body=b"x", ctype="image/png")
        caught = []
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            for path in ("/r", "/enc", "/big", "/ct", "/none"):
                try:
                    self.get("https://a.test" + path, self.credentials(), max_bytes=1000)
                except Exception as e:   # every failure path
                    caught.append(e)
            for bad in (self.credentials(follow_redirects=True), self.credentials(credential_host="b.test")):
                try:
                    self.get("https://a.test/p", bad)
                except Exception as e:
                    caught.append(e)
            with mock.patch.object(webclient, "_dial", side_effect=OSError(CANARY[:0] + "connection refused")):
                try:
                    self.get("https://a.test/p", self.credentials())
                except Exception as e:
                    caught.append(e)
        self.assertGreaterEqual(len(caught), 7)
        self.assertEqual([path for path, headers in self.srv.hits if path == "/p" and "auth-key" in headers], [])
        for exc in caught:
            seen, stack = [], [exc]
            while stack:
                e = stack.pop()
                if e is None or id(e) in seen:
                    continue
                seen.append(id(e))
                for text in (str(e), repr(e), repr(e.args)):
                    self.assertNotIn(CANARY, text)
                stack += [e.__cause__, e.__context__]
        for _, headers in self.srv.hits:
            if headers.get("host") != "a.test":
                self.assertNotIn("auth-key", headers)

    def test_a_credential_cannot_be_passed_as_an_ordinary_header(self):
        for name in ("Authorization", "authorization", "Cookie", "Proxy-Authorization"):
            for where in ("call", "policy"):
                with self.subTest(name, where=where):
                    with self.assertRaises(webclient.Refused):
                        if where == "call":
                            self.get("http://a.test/p", headers={name: "Bearer x"})
                        else:
                            self.get("http://a.test/p", self.policy(headers={name: "Bearer x"}))
        self.assertEqual(self.dials, [])

    def test_extra_headers_do_not_follow_a_step_down_from_https_to_http_on_one_host(self):
        self.srv.routes["/s"] = redirect("http://a.test/clear")
        self.srv.routes["/clear"] = self.ok()
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            self.get("https://a.test/s", self.policy(headers={"X-Custom": "one"}))
        by_path = dict(self.srv.hits)
        self.assertEqual(by_path["/s"]["x-custom"], "one")
        self.assertNotIn("x-custom", by_path["/clear"])


class Hook(Net):
    def test_the_hook_sees_the_canonical_address_before_the_first_request_and_at_every_hop(self):
        seen = []
        self.srv.routes["/old"] = redirect("http://b.test/mid?utm_source=q")
        self.srv.routes["/mid"] = redirect("/end#frag")
        self.srv.routes["/end"] = self.ok()
        self.get("HTTP://A.test./old#f", self.policy(check=lambda url: seen.append((url, len(self.dials))) and None))
        self.assertEqual(seen, [("http://a.test/old", 0), ("http://b.test/mid", 1), ("http://b.test/end", 2)])

    def test_a_blocked_first_address_makes_no_lookup_and_no_request(self):
        policy = self.policy(check=lambda url: "on the owner's blacklist")
        with self.assertRaises(webclient.Refused) as caught:
            self.get("http://a.test/p", policy)
        self.assertIn("blacklist", str(caught.exception))
        self.assertEqual((self.lookups, self.dials, self.srv.hits), ([], [], []))

    def test_a_block_object_with_a_reason_is_a_refusal_too(self):
        class Block:
            reason = "a listed host"

        with self.assertRaises(webclient.Refused) as caught:
            self.get("http://a.test/p", self.policy(check=lambda url: Block()))
        self.assertIn("a listed host", str(caught.exception))

    def test_a_blocked_redirect_target_is_refused_without_a_request_to_it(self):
        self.srv.routes["/old"] = redirect("http://b.test/x")
        self.get_calls = 0
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/old", self.policy(check=lambda url: "blocked" if "b.test" in url else None))
        self.assertEqual(len(self.srv.hits), 1)
        self.assertEqual(self.dials, [("93.184.216.34", 80)])
        self.assertNotIn("b.test", self.lookups)

    def test_a_hook_that_fails_blocks_the_request(self):
        def broken(url):
            raise RuntimeError("the list is unreadable")

        with self.assertRaises(webclient.Refused):
            self.get("http://a.test/p", self.policy(check=broken))
        self.assertEqual(self.dials, [])

    def test_the_hook_is_not_asked_about_an_address_the_client_already_refused(self):
        seen = []
        with self.assertRaises(webclient.Refused):
            self.get("http://a.test:8080/", self.policy(check=lambda url: seen.append(url)))
        self.assertEqual(seen, [])


class FakeClock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class PacerUnit(unittest.TestCase):
    def setUp(self):
        self.t = FakeClock()
        self.pacer = webclient.Pacer(clock=self.t.clock, sleep=self.t.sleep, rng=random.Random(5))

    def use(self, *keys, gap=2.0, jitter=1.0):
        with self.pacer.slot(keys, gap, jitter):
            pass

    def test_the_next_request_to_a_key_waits_the_gap_plus_a_jitter_in_range(self):
        waits = []
        for _ in range(20):
            before = len(self.t.slept)
            self.use("site:a.test")
            waits.append(sum(self.t.slept[before:]))
        self.assertEqual(waits[0], 0)
        for w in waits[1:]:
            self.assertGreaterEqual(w, 2.0)
            self.assertLessEqual(w, 3.0)
        self.assertGreater(len({round(w, 6) for w in waits[1:]}), 3)   # the jitter varies

    def test_other_keys_are_not_delayed_and_a_shared_key_delays_both(self):
        self.use("site:a.test", "ip:1")
        self.use("site:b.test", "ip:2")
        self.assertEqual(self.t.slept, [])
        self.use("site:c.test", "ip:1")      # another site on the same address
        self.assertEqual(len(self.t.slept), 1)
        self.assertGreaterEqual(self.t.slept[0], 2.0)

    def test_time_that_has_passed_counts(self):
        self.use("site:a.test")
        self.t.now += 10
        self.use("site:a.test")
        self.assertEqual(self.t.slept, [])

    def test_reset_clears_every_wait(self):
        self.use("site:a.test")
        self.pacer.reset()
        self.use("site:a.test")
        self.assertEqual(self.t.slept, [])

    def test_whatever_happens_inside_a_slot_leaves_an_entry(self):
        for error in (webclient.Refused("wrong type"), webclient.FetchError("timed out"), RuntimeError("crash")):
            self.pacer.reset()
            del self.t.slept[:]
            with self.assertRaises(type(error)):
                with self.pacer.slot(["site:a.test"], 2.0, 1.0):
                    raise error
            self.use("site:a.test")
            self.assertEqual(len(self.t.slept), 1, repr(error))

    def test_a_gap_of_zero_and_no_jitter_never_waits(self):
        for _ in range(5):
            self.use("site:a.test", gap=0, jitter=0)
        self.assertEqual(self.t.slept, [])

    def test_two_threads_never_hold_one_key_together_and_keys_in_other_orders_do_not_deadlock(self):
        pacer = webclient.Pacer(clock=time.monotonic, sleep=lambda s: None, rng=random.Random(1))
        inside, worst = [0], [0]
        lock = threading.Lock()

        def work(keys):
            for _ in range(30):
                with pacer.slot(keys, 0, 0):
                    with lock:
                        inside[0] += 1
                        worst[0] = max(worst[0], inside[0])
                    time.sleep(0.001)
                    with lock:
                        inside[0] -= 1

        threads = [threading.Thread(target=work, args=(k,)) for k in (["x", "y"], ["y", "x"], ["x", "y"])]
        for th in threads:
            th.start()
        for th in threads:
            th.join(10)
        self.assertFalse(any(th.is_alive() for th in threads))
        self.assertEqual(worst[0], 1)


class Pacing(Net):
    def setUp(self):
        super().setUp()
        self.t = FakeClock()
        self.pacer = webclient.Pacer(clock=self.t.clock, sleep=self.t.sleep, rng=random.Random(3))
        self.srv.routes["/p"] = self.ok()

    def paced(self, **kw):
        return self.policy(gap=2.0, jitter=1.0, pacer=self.pacer, **kw)

    def test_two_requests_to_one_registrable_domain_are_separated(self):
        self.get("http://a.test/p", self.paced())
        self.assertEqual(self.t.slept, [])
        self.get("http://www.a.test/p", self.paced())    # the same site by the last two labels
        self.assertEqual(len(self.t.slept), 1)
        self.assertTrue(2.0 <= self.t.slept[0] <= 3.0)

    def test_two_hosts_of_one_site_on_different_addresses_are_paced_together(self):
        self.dns["m1.s.test"], self.dns["m2.s.test"] = ["93.184.216.50"], ["93.184.216.51"]
        self.get("http://m1.s.test/p", self.paced())
        self.get("http://m2.s.test/p", self.paced())
        self.assertEqual(len(self.t.slept), 1)

    def test_two_names_for_one_address_count_as_one_site_for_the_pacer(self):
        self.get("http://a.test/p", self.paced())
        self.get("http://alias.test/p", self.paced())    # another site, the same address
        self.assertEqual(len(self.t.slept), 1)

    def test_other_domains_and_addresses_are_not_delayed_by_each_other(self):
        for host in ("a.test", "b.test", "c.test", "d.test"):
            self.get(f"http://{host}/p", self.paced())
        self.assertEqual(self.t.slept, [])

    def test_each_hop_of_a_redirect_takes_its_own_slot(self):
        self.srv.routes["/r"] = redirect("http://a.test/p")
        self.get("http://a.test/r", self.paced())        # the second hop goes to the same site
        self.assertEqual(len(self.t.slept), 1)

    def test_a_response_that_is_refused_after_the_request_still_paces_the_next_one(self):
        self.srv.routes["/img"] = reply(200, body=b"x", ctype="image/png")
        self.srv.routes["/pdf"] = self.ok(b"%PDF-1.7 posing as a page")
        for path in ("/img", "/pdf"):
            with self.assertRaises(webclient.Refused):
                self.get("http://a.test" + path, self.paced())
        self.assertEqual(len(self.t.slept), 1)
        self.get("http://a.test/p", self.paced())
        self.assertEqual(len(self.t.slept), 2)

    def test_a_request_refused_before_it_is_sent_makes_no_entry(self):
        for url, kw in (("http://a.test:8080/", {}), ("http://internal.test/", {}), ("http://a.test/p", {"check": lambda url: "no"})):
            with self.assertRaises(webclient.Refused):
                self.get(url, self.paced(**kw))
        self.get("http://a.test/p", self.paced())
        self.assertEqual(self.t.slept, [])

    def test_the_shared_pacer_is_the_default_and_can_be_reset(self):
        self.assertIsInstance(webclient.PACER, webclient.Pacer)
        policy = self.policy(gap=5.0, jitter=0.0)
        self.assertIsNone(policy.pacer)
        with mock.patch.object(webclient.PACER, "_sleep", self.t.sleep), mock.patch.object(webclient.PACER, "_clock", self.t.clock):
            self.get("http://a.test/p", policy)
            self.get("http://a.test/p", policy)
            self.assertEqual(self.t.slept, [5.0])
            webclient.PACER.reset()
            self.get("http://a.test/p", policy)
            self.assertEqual(self.t.slept, [5.0])

    def test_one_request_at_a_time_to_a_site_even_from_two_threads_and_two_sites_run_together(self):
        self.srv.routes["/slow"] = lambda conn, path, headers: (time.sleep(0.3), conn.sendall(self.ok()))[1]
        real = webclient.Pacer()
        policy = self.policy(pacer=real)

        def run(host):
            self.get(f"http://{host}/slow", policy)

        for hosts in (("a.test", "www.a.test"), ("a.test", "b.test")):
            self.srv.max_inflight = 0
            threads = [threading.Thread(target=run, args=(h,)) for h in hosts]
            for th in threads:
                th.start()
            for th in threads:
                th.join(10)
            self.assertEqual(self.srv.max_inflight, 1 if hosts[1] == "www.a.test" else 2, hosts)


class SecurityFixes(Net):
    """Faults found by the security review of Increment B, each shown by a test that failed before the fix."""

    def test_a_name_that_lists_other_sites_addresses_does_not_hold_them(self):
        self.dns["evil.test"] = ["93.184.216.60", "93.184.216.35"]    # the second is b.test's address
        self.srv.routes["/slow"] = lambda conn, path, headers: (time.sleep(0.8), conn.sendall(self.ok()))[1]
        self.srv.routes["/p"] = self.ok()
        policy = self.policy(pacer=webclient.Pacer())
        first = threading.Thread(target=lambda: self.get("http://evil.test/slow", policy))
        first.start()
        time.sleep(0.2)
        started = time.monotonic()
        self.get("http://b.test/p", policy)
        waited = time.monotonic() - started
        first.join(10)
        self.assertLess(waited, 0.4)

    def test_a_long_list_of_answers_is_cut_to_a_few_addresses(self):
        self.dns["many.test"] = [f"93.184.217.{n}" for n in range(1, 11)]
        calls = []

        def dial(address, timeout):
            calls.append(address[0])
            raise OSError("no route")

        with mock.patch.object(webclient, "_dial", dial):
            with self.assertRaises(webclient.FetchError):
                self.get("http://many.test/p")
        self.assertEqual(calls, [f"93.184.217.{n}" for n in range(1, 5)])    # the first four answers and no more

    def test_the_address_key_is_the_same_for_a_mapped_and_a_plain_spelling(self):
        self.assertEqual(webclient._ip_key("::ffff:93.184.216.34"), webclient._ip_key("93.184.216.34"))
        self.assertNotEqual(webclient._ip_key("93.184.216.34"), webclient._ip_key("93.184.216.35"))

    def test_a_request_is_not_sent_after_the_deadline_has_passed(self):
        self.dns["dead.test"] = [f"93.184.218.{n}" for n in range(1, 5)]
        order = []

        def dial(address, timeout):
            order.append((address[0], round(timeout, 1)))
            if address[0] != "93.184.218.4":
                time.sleep(0.3)
                raise OSError("no route")
            return PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), address[0])

        self.srv.routes["/p"] = self.ok()
        with mock.patch.object(webclient, "_dial", dial):
            with self.assertRaises(webclient.FetchError):
                self.get("http://dead.test/p", total_timeout=0.5)
            time.sleep(1.5)
        self.assertEqual(self.srv.hits, [])           # nothing was sent after get() gave up
        self.assertLess(len(order), 4)                # and the worker stopped dialling

    def test_the_time_to_connect_is_bounded_by_the_deadline(self):
        seen = []

        def dial(address, timeout):
            seen.append(timeout)
            return PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), timeout), address[0])

        self.srv.routes["/p"] = self.ok()
        with mock.patch.object(webclient, "_dial", dial):
            self.get("http://a.test/p", timeout=30, total_timeout=2)
        self.assertLessEqual(seen[0], 2.0)

    def test_a_credential_reflected_by_the_server_is_not_in_the_error(self):
        for header in ("Content-Encoding", "Content-Type"):
            with self.subTest(header):
                self.srv.routes["/p"] = lambda conn, path, headers, header=header: conn.sendall(
                    f"HTTP/1.1 200 X\r\n{header}: {headers['auth-key']}\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx".encode("latin-1"))
                caught = []
                with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
                    try:
                        self.get("https://a.test/p", self.policy(credential_headers={"Auth-Key": CANARY}, credential_host="a.test", follow_redirects=False))
                    except Exception as e:
                        caught.append(e)
                self.assertEqual(len(caught), 1)
                for text in (str(caught[0]), repr(caught[0]), repr(caught[0].args)):
                    self.assertNotIn(CANARY.lower(), text.lower())

    def test_an_address_that_embeds_a_private_one_or_is_the_cloud_service_address_is_refused(self):
        for url in ("http://[::ffff:0:7f00:1]/", "http://[::ffff:0:a00:1]/", "http://168.63.129.16/"):
            with self.subTest(url):
                with self.assertRaises(webclient.Refused):
                    self.get(url)
        self.assertEqual(self.dials, [])

    def test_one_unacceptable_answer_among_good_ones_refuses_the_name(self):
        self.dns["mixed2.test"] = ["93.184.216.34", "::ffff:0:7f00:1"]
        with self.assertRaises(webclient.Refused):
            self.get("http://mixed2.test/p")
        self.assertEqual(self.dials, [])

    def test_a_connection_that_finishes_after_the_request_was_cut_is_closed_and_nothing_is_sent(self):
        def slow_dial(address, timeout):
            time.sleep(1.0)
            sock = PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), 3), address[0])
            self.socks.append(sock)
            return sock

        self.srv.routes["/p"] = self.ok()
        with mock.patch.object(webclient, "_dial", slow_dial):
            with self.assertRaises(webclient.FetchError):
                self.get("http://a.test/p", total_timeout=0.3, timeout=5)
            time.sleep(1.3)
        self.assertEqual(self.srv.hits, [])
        self.assertTrue(self.socks and all(sock.closed for sock in self.socks))

    def test_a_lock_that_cannot_be_taken_does_not_leave_the_others_held(self):
        pacer = webclient.Pacer(clock=time.monotonic, sleep=lambda s: None)

        class Broken:
            def acquire(self):
                raise KeyboardInterrupt

            def release(self):
                raise AssertionError("released a lock that was never held")

        pacer._locks["b"] = Broken()
        with self.assertRaises(KeyboardInterrupt):
            with pacer.slot(["a", "b"], 0, 0):
                pass
        self.assertTrue(pacer._locks["a"].acquire(blocking=False))

    def test_old_entries_do_not_pile_up(self):
        t = FakeClock()
        pacer = webclient.Pacer(clock=t.clock, sleep=t.sleep, rng=random.Random(1))
        for n in range(3000):
            with pacer.slot([f"k{n}"], 1.0, 0.0):
                pass
        t.now += 100
        with pacer.slot(["fresh"], 1.0, 0.0):
            pass
        self.assertLess(len(pacer._next), 100)

    def test_a_pdf_with_leading_white_space_or_an_image_posing_as_a_page_is_refused(self):
        for name, body in {"pdf": b"   \n\r\n%PDF-1.7 hidden", "png": b"\x89PNG\r\n\x1a\n...", "gif": b"GIF89a....", "jpeg": b"\xff\xd8\xff\xe0...."}.items():
            with self.subTest(name):
                self.srv.routes["/p"] = self.ok(body)
                with self.assertRaises(webclient.Refused):
                    self.get("http://a.test/p")

    def test_a_page_that_talks_about_pdf_files_is_not_refused(self):
        self.srv.routes["/p"] = self.ok(b"<html><p>A file starts with %PDF- and then a version.</p></html>")
        self.assertEqual(self.get("http://a.test/p")[0], 200)


class SecondLook(Net):
    """Faults found when the fixes of the security review were read again."""

    def test_the_platform_address_is_refused_in_every_embedded_form(self):
        for ip in ("::ffff:168.63.129.16", "::ffff:a83f:8110", "::ffff:0:a83f:8110", "64:ff9b::a83f:8110", "2002:a83f:8110::", "::a83f:8110"):
            with self.subTest(ip):
                self.assertFalse(webclient._acceptable(ip))
        for ip in ("93.184.216.34", "::ffff:93.184.216.34", "2001:4860:4860::8888", "64:ff9b::5db8:d822"):
            with self.subTest(ip):
                self.assertTrue(webclient._acceptable(ip))

    def test_a_dial_that_ends_after_the_deadline_sends_nothing_even_before_the_cut(self):
        def late_dial(address, timeout):
            time.sleep(0.45)
            sock = PeerSock(socket.create_connection(("127.0.0.1", self.srv.port), 3), address[0])
            self.socks.append(sock)
            return sock

        self.srv.routes["/p"] = self.ok()
        with mock.patch.object(webclient, "_dial", late_dial):
            with self.assertRaises(webclient.FetchError):
                self.get("http://a.test/p", total_timeout=0.3, timeout=5)
            time.sleep(0.5)
        self.assertEqual(self.srv.hits, [])

    def test_a_reflected_credential_is_scrubbed_from_the_returned_headers_and_from_a_long_value(self):
        def echo(conn, path, headers):
            secret = headers["auth-key"]
            conn.sendall(f"HTTP/1.1 200 X\r\nContent-Type: text/html\r\nETag: {secret}\r\nX-Echo: {secret}\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx".encode("latin-1"))

        self.srv.routes["/p"] = echo
        policy = self.policy(credential_headers={"Auth-Key": CANARY}, credential_host="a.test", follow_redirects=False)
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            status, headers, body = self.get("https://a.test/p", policy)
        self.assertEqual(status, 200)
        self.assertNotIn(CANARY.lower(), repr(headers).lower())
        # a secret that the 80-character cut of a message would split is removed before the cut
        padded = "t" * 70 + CANARY
        self.srv.routes["/q"] = lambda conn, path, headers: conn.sendall(f"HTTP/1.1 200 X\r\nContent-Type: {padded}\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx".encode("latin-1"))
        policy = self.policy(credential_headers={"Auth-Key": CANARY}, credential_host="a.test", follow_redirects=False)
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            with self.assertRaises(webclient.Refused) as caught:
                self.get("https://a.test/q", policy)
        self.assertNotIn(CANARY[:10].lower(), str(caught.exception).lower())
        self.srv.routes["/e"] = lambda conn, path, headers: conn.sendall(f"HTTP/1.1 200 X\r\nContent-Type: text/html\r\nContent-Encoding: {'t' * 30}{CANARY}\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx".encode("latin-1"))
        with mock.patch.object(webclient, "_tls_wrap", lambda sock, host: sock):
            with self.assertRaises(webclient.FetchError) as caught:
                self.get("https://a.test/e", policy)
        self.assertNotIn(CANARY[:10].lower(), str(caught.exception).lower())

    def test_the_lock_table_stays_small_and_a_key_in_use_keeps_its_lock(self):
        pacer = webclient.Pacer(clock=time.monotonic, sleep=lambda s: None)
        with mock.patch.object(webclient, "MAX_PACER_LOCKS", 50):
            for n in range(500):
                with pacer.slot([f"k{n}"], 0, 0):
                    pass
            self.assertLessEqual(len(pacer._locks), 50)
            with pacer.slot(["held"], 0, 0):
                held = pacer._locks["held"]
                for n in range(500, 700):
                    with pacer.slot([f"k{n}"], 0, 0):
                        pass
                self.assertIs(pacer._locks["held"], held)
            self.assertNotIn("held", pacer._users)
            self.assertEqual(pacer._users, {})


class Policies(unittest.TestCase):
    def test_the_defaults_are_safe(self):
        policy = webclient.Policy()
        self.assertFalse(policy.allow_private)
        self.assertTrue(policy.follow_redirects)
        self.assertEqual(policy.max_redirects, 5)
        self.assertIsNone(policy.credential_headers)
        self.assertEqual((policy.gap, policy.jitter), (1.0, 1.0))   # a caller that forgets to set them is still polite
        self.assertIsNone(policy.check)
        self.assertTrue(policy.user_agent)

    def test_a_policy_takes_only_the_fields_it_knows(self):
        with self.assertRaises(TypeError):
            webclient.Policy(follows_redirects=False)

    def test_the_module_imports_no_third_party_code_and_never_builds_a_message_from_a_header_value(self):
        import os
        with open(os.path.join(ENGINE_DIR, "kb", "webclient.py"), encoding="utf-8") as f:
            source = f.read()
        for word in ("import requests", "urllib.request", "import urllib3", "HTTPRedirectHandler"):
            self.assertNotIn(word, source, word)


if __name__ == "__main__":
    unittest.main()
