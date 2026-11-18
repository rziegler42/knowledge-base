"""The shared web client of the unattended crawl (`docs/specs/population.md`, "Pacing, the type gate and the shared client"; the plan
`2026-11-16-harden-the-fetch-for-the-unattended-crawl`, Increment B).

`get(url, policy=...)` makes every request the crawl makes. For each hop it: canonicalises the address (`webaddr`), asks the policy's hook whether the address may be fetched, resolves the host **once** and checks every answer
(`capture_url.resolve_checked`, imported and not copied), waits for its turn at the registrable domain and at the resolved addresses (the pacer), connects to **the address that was checked**, and refuses the connection
unless the socket's peer is that address. Only ports 80 and 443 are used (`webaddr` refuses the rest). Redirects are followed here, one hop at a time, and not by urllib: every hop is checked afresh, a policy can
follow none, and extra headers go only to the host they were first sent to. **A credential header is sent only through `Policy.credential_headers`, and only when the call follows no redirect, names one canonical
`credential_host`, and asks for an `https` address on exactly that host; it is never copied anywhere and is never written into an error.** An error message is built from this module's own text and from nothing the
caller passed in a header.

The response is bounded in size and time, must carry a `Content-Type` in the policy's `types`, must not be encoded, and its first bytes must agree with its type (`_sniff`). `get` returns `(status, headers, body)`,
as a tuple that also has `.final`, the canonical address the body came from. A status other than 200 that is not followed comes back with its headers and an empty body.

Nothing here parses what it downloads."""
import contextlib
import http.client
import ipaddress
import random
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit

from . import __version__, textutil, webaddr
from .capture_url import (MAX_BYTES, MAX_REDIRECTS, PAGE_TYPES, TIMEOUT, TOTAL_TIMEOUT, FetchError, PolicyError, _with_deadline,
                          is_public, resolve_checked)

GENERIC_USER_AGENT = f"knowledge-base/{__version__} (research library; single GET)"
ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
MAX_ADDRESSES = 4            # the answers of a name that are used: an attacker's name can list as many as it likes
MAX_PACER_LOCKS = 4096       # key locks kept; a lock nobody is using is dropped above this
MAX_PACER_ENTRIES = 2048     # waiting turns kept before the ones that have passed are dropped
_SIIT = ipaddress.ip_network("::ffff:0:0:0/96")   # IPv4-translated: the last 32 bits are an IPv4 address
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPATIBLE = ipaddress.ip_network("::/96")
_SIXTOFOUR = ipaddress.ip_network("2002::/16")
_NEVER_PUBLIC = (ipaddress.ip_network("168.63.129.16/32"),)   # a cloud platform's service address, which looks global
_BINARY_MAGIC = (b"\x89PNG", b"GIF87a", b"GIF89a", b"\xff\xd8\xff")
FORBIDDEN_HEADERS = frozenset(("host", "accept", "accept-encoding", "user-agent", "content-length", "transfer-encoding", "connection", "upgrade", "te", "keep-alive", "expect",
                               "proxy-authorization", "proxy-connection", "trailer", "authorization", "cookie"))
# a credential header may be named `Authorization` (a bearer key is sent only so), and nothing else of the list above; a policy or a call may not carry it
CREDENTIAL_FORBIDDEN_HEADERS = FORBIDDEN_HEADERS - {"authorization"}
MAX_CREDENTIAL_VALUE = 512   # and at most this: a key is far shorter, and a longer value could be cut by the first clean of a server's text and leave a part of itself after the scrub
MIN_CREDENTIAL_VALUE = 8     # a credential value (a whole header value, `Bearer <key>` included) is at least this long: an empty one, spaces, or a letter would be sent as it is and would blank ordinary text in every message
MIN_TOKEN_SCRUB = 8          # the token after a scheme is scrubbed alone only from this length: a key is longer, and a shorter text would blank ordinary words
MAX_POST_BYTES = 4096        # the body of one POST: a small JSON request
_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_HEADER_KEYS = ("content-type", "content-length", "content-encoding", "content-language", "last-modified", "etag", "location", "date", "cache-control", "retry-after", "x-ratelimit-limit",
                "x-ratelimit-remaining", "x-ratelimit-reset", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")


class Refused(FetchError):
    """A request the policy refuses, or a response it will not take. The reason is safe to log: it holds no header value the caller passed."""


class Result(tuple):
    """`(status, headers, body)` that also says `.final`, the canonical address the body came from."""

    def __new__(cls, status, headers, body, final):
        obj = tuple.__new__(cls, (status, headers, body))
        obj.final = final
        return obj


class Policy:
    """How one kind of request is made. A plain object: unknown fields are an error."""

    def __init__(self, *, user_agent=GENERIC_USER_AGENT, headers=None, gap=1.0, jitter=1.0, max_redirects=MAX_REDIRECTS, follow_redirects=True, types=PAGE_TYPES, check=None,
                 allow_private=False, credential_headers=None, credential_host=None, suffixes=None, pacer=None, accept=ACCEPT):
        self.user_agent, self.headers, self.gap, self.jitter = user_agent, headers, gap, jitter
        self.max_redirects, self.follow_redirects, self.types, self.check = max_redirects, follow_redirects, tuple(types), check
        self.allow_private, self.credential_headers, self.credential_host = allow_private, credential_headers, credential_host
        self.suffixes, self.pacer, self.accept = suffixes, pacer, accept


class Pacer:
    """One request at a time to a key (a registrable domain, a resolved address), and a gap plus a random jitter between one request and the next. The clock, the sleeper and the random source are injectable."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep, rng=None):
        self._clock, self._sleep, self._rng = clock, sleep, rng or random.Random()
        self._state = threading.Lock()
        self._locks, self._next, self._users = {}, {}, {}

    def reset(self):
        with self._state:
            self._next.clear()

    def _enter(self, keys):
        """The locks of the keys, which stay in the table while anyone uses them."""
        with self._state:
            for key in keys:
                self._users[key] = self._users.get(key, 0) + 1
            return [self._locks.setdefault(key, threading.Lock()) for key in keys]

    def _leave(self, keys):
        with self._state:
            for key in keys:
                self._users[key] -= 1
                if self._users[key] == 0:
                    del self._users[key]
                    if len(self._locks) > MAX_PACER_LOCKS:
                        del self._locks[key]

    def _record(self, keys, gap, jitter):
        delay = gap + (self._rng.uniform(0, jitter) if jitter else 0)
        with self._state:
            now = self._clock()
            for key in keys:
                self._next[key] = now + delay
            if len(self._next) > MAX_PACER_ENTRIES:   # a turn that has passed is the same as no turn
                for key in [k for k, v in self._next.items() if v <= now]:
                    del self._next[key]

    @contextlib.contextmanager
    def slot(self, keys, gap, jitter):
        """Hold every key, wait until the latest of their turns, run the request, and leave the next turn a gap and a jitter away. Whatever happens inside, even a refusal of the response, has reached the
        server and so leaves an entry; a request refused before the slot (the hook, the address, the lookup) never gets here and leaves none."""
        keys = sorted(set(keys))
        locks = self._enter(keys)
        held = []
        try:
            for lock in locks:
                lock.acquire()
                held.append(lock)
            with self._state:
                ready = max((self._next.get(key, 0.0) for key in keys), default=0.0)
            wait = ready - self._clock()
            if wait > 0:
                self._sleep(wait)
            try:
                yield
            finally:
                self._record(keys, gap, jitter)
        finally:
            for lock in reversed(held):
                lock.release()
            self._leave(keys)


PACER = Pacer()


def _dial(address, timeout):
    """The one place the client opens a connection: `address` is `(checked ip, port)`. Tests point this at a fake server; no setting of a crawl plan can."""
    return socket.create_connection(address, timeout)


def _tls_wrap(sock, host):
    """Start TLS on a connected socket, checking the certificate for the name asked for."""
    return ssl.create_default_context().wrap_socket(sock, server_hostname=host)


def _clean_headers(mapping, what):
    """A header mapping checked and returned with lower-case keys kept as written: token names, printable ASCII values, none of the headers this client sets or that change how it reads the answer."""
    out = {}
    for name, value in (mapping or {}).items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise Refused(f"a {what} header has a name that is not allowed")
        if name.lower() in (CREDENTIAL_FORBIDDEN_HEADERS if what == "credential" else FORBIDDEN_HEADERS):
            raise Refused(f"the {what} header {name!r} is set by the client and cannot be given")
        if not isinstance(value, str) or any(not (32 <= ord(c) < 127 or c == "\t") for c in value):
            raise Refused(f"the {what} header {name!r} has a value that is not printable ASCII text")
        if what == "credential" and not MIN_CREDENTIAL_VALUE <= len(value.strip()) <= MAX_CREDENTIAL_VALUE:
            raise Refused(f"the credential header {name!r} has a value that is too short or too long to be a key")
        out[name] = value
    return out


def _check_value(value, what):
    if not isinstance(value, str) or not value or any(not (32 <= ord(c) < 127) for c in value):
        raise Refused(f"the {what} is not printable ASCII text")
    return value


def _ip_key(address):
    """The pacer's key for an address: an IPv4 address written as a mapped IPv6 one is the same key."""
    ip = ipaddress.ip_address(str(address).split("%")[0])
    return f"ip:{getattr(ip, 'ipv4_mapped', None) or ip}"


def _embedded_v4(ip):
    """The IPv4 address an IPv6 one carries (mapped, translated, compatible, NAT64, 6to4), or None."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _SIIT or ip in _NAT64_WELL_KNOWN or (ip in _V4_COMPATIBLE and int(ip) > 1):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in _SIXTOFOUR:
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def _acceptable(address):
    """The ranges `capture_url.is_public` lets through that the crawl still refuses: an IPv6 address that carries an IPv4 one in any form (mapped, translated, compatible, NAT64, 6to4) is judged by that IPv4
    address, and a platform service address is never fetched, however it is written."""
    ip = ipaddress.ip_address(address)
    inner = _embedded_v4(ip)
    if inner is not None:
        return is_public(inner) and _acceptable(str(inner))
    return not any(ip in net for net in _NEVER_PUBLIC if ip.version == net.version)


def _same_peer(peer, address):
    try:
        return ipaddress.ip_address(str(peer).split("%")[0]) == ipaddress.ip_address(address)
    except ValueError:
        return False


def _connect(host, addresses, port, timeout, live, cancelled, deadline):
    """Connect to one of the addresses that were checked, and refuse the connection unless its peer is that address. Stops dialling once the request has been cut, and never waits past the deadline."""
    last = None
    for address in addresses:
        remaining = deadline - time.monotonic()
        if cancelled.is_set() or remaining <= 0:
            raise FetchError("timed out")
        try:
            sock = _dial((address, port), min(timeout, remaining))
        except OSError as e:
            last = e
            continue
        live.append(sock)
        if cancelled.is_set():
            sock.close()
            raise FetchError("timed out")
        try:
            peer = sock.getpeername()[0]
        except OSError as e:
            last = e
            sock.close()
            continue
        if not _same_peer(peer, address):
            sock.close()
            raise Refused("the connection did not reach the address that was checked")
        return sock
    raise FetchError(f"cannot connect to {host}: {getattr(last, 'strerror', None) or 'no address answered'}")


def _sniff(ctype, body):
    """Refuse a body whose first bytes disagree with its declared type: a page, text, JSON or XML must not be a PDF, gzip or zip, or hold NUL bytes; a PDF must start like one; JSON must start with `{` or `[`;
    XML with `<`. A type with no rule here is checked only for those binary magic numbers."""
    head = body[:8192]
    stripped = head.lstrip(b" \t\r\n\x0c")
    pdf, gzip, zipped = stripped.startswith(b"%PDF-"), head.startswith(b"\x1f\x8b"), head.startswith(b"PK\x03\x04")
    first = stripped[:1]
    if ctype == "application/pdf":
        if not pdf:
            raise Refused("the response says it is a PDF but does not start like one")
        return
    if pdf or gzip or zipped or head.startswith(_BINARY_MAGIC) or b"\x00" in head:
        raise Refused(f"the response says it is {ctype} but its first bytes are binary or another format")
    if ctype == "application/json" and first not in (b"{", b"["):
        raise Refused("the response says it is JSON but does not start like JSON")
    if (ctype in ("application/xml", "text/xml") or ctype.endswith("+xml")) and ctype != "application/xhtml+xml" and first != b"<":
        raise Refused("the response says it is XML but does not start like XML")


def _timed_out(exc):
    return isinstance(exc, (socket.timeout, TimeoutError))


def _read_response(response, policy, address, deadline, max_bytes, secrets=()):
    def shown(text, limit):   # server text for a message or a record: made clean first (a control character a server put inside the key would otherwise hide it from the scrub and be removed after it), then a credential it echoes is removed, then it is cut
        return textutil.clean(_scrub(textutil.clean(text, 10_000), secrets), limit)

    status = response.status
    headers = {}
    for key in _HEADER_KEYS:
        values = response.msg.get_all(key) or []
        if values:
            headers[key] = shown(", ".join(values), 300)
    if status in REDIRECT_STATUSES:
        return "redirect", response.msg.get_all("Location") or []
    if status != 200:
        return Result(status, headers, b"", address)
    raw = response.getheader("Content-Type")
    ctype = raw.split(";")[0].strip().lower() if raw else ""
    if not ctype:
        raise Refused("the response has no Content-Type")
    if ctype not in policy.types:
        raise Refused(f"not an expected type: its content type is {shown(ctype, 80)}")
    for encoding in response.msg.get_all("Content-Encoding") or []:
        if encoding.strip().lower() != "identity":
            raise FetchError(f"the server sent the page encoded ({shown(encoding.strip(), 40)}) although none was asked for")
    lengths = response.msg.get_all("Content-Length") or []
    if len(lengths) > 1 and len({v.strip() for v in lengths}) > 1:
        raise FetchError("the server sent conflicting Content-Length headers")
    declared = None
    if lengths:
        if not re.fullmatch(r"[0-9]{1,15}", lengths[0].strip()):
            raise FetchError("the server sent a Content-Length that is not a number")
        declared = int(lengths[0].strip())
        if declared > max_bytes:
            raise FetchError(f"the response is larger than {max_bytes} bytes (it says {declared})")
    chunks, total = [], 0
    while True:
        if time.monotonic() > deadline:
            raise FetchError("timed out reading the response")
        failure = None
        try:
            chunk = response.read1(65536)
        except Exception as e:
            failure = "timed out" if _timed_out(e) else f"network error while reading: {type(e).__name__}"
        if failure is not None:
            raise FetchError(failure)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"the response is larger than {max_bytes} bytes")
        chunks.append(chunk)
    if declared is not None and total != declared:
        raise FetchError(f"the response ended early: {total} of {declared} bytes arrived")
    body = b"".join(chunks)
    _sniff(ctype, body)
    return Result(status, headers, body, address)


def _request(parts, addresses, port, hop_headers, policy, timeout, total_timeout, max_bytes, address, secrets=(), method="GET", body=None):
    """One request (a GET, or a POST with a body) on one connection to a checked address, under a deadline that cuts the sockets when it passes."""
    live, cancelled = [], threading.Event()
    host, scheme = parts.hostname, parts.scheme
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    started = time.monotonic()

    def run():
        raw = _connect(host, addresses, port, timeout, live, cancelled, started + total_timeout)
        sock = raw
        if scheme == "https":
            failure = None
            try:
                sock = _tls_wrap(raw, host)
            except Exception as e:   # a certificate that is not accepted, a handshake that fails or times out
                raw.close()
                if _timed_out(e):
                    failure = "timed out"
                elif isinstance(e, ssl.SSLCertVerificationError):
                    failure = "the server's certificate was not accepted"
                elif isinstance(e, (OSError, ValueError)):
                    failure = f"network error: {type(e).__name__}"
                else:
                    raise
            if failure is not None:
                raise FetchError(failure)   # outside the `except`, so that the exception that held the server's text is not the new one's context
            live.append(sock)   # wrapping detaches the raw socket, so only this one can be cut now (the handshake itself is bounded by `timeout`)
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.sock = sock
        response = None
        try:
            if cancelled.is_set() or time.monotonic() > started + total_timeout:
                raise FetchError("timed out")
            failure = None
            try:
                shown = f"[{host}]" if ":" in host else host   # the default port of the scheme is never written
                conn.request(method, target, body=body, headers={"Host": shown, **hop_headers})
                response = conn.getresponse()
            except Exception as e:
                if _timed_out(e):
                    failure = "timed out"
                elif isinstance(e, (OSError, http.client.HTTPException, ValueError)):
                    failure = f"network error: {type(e).__name__}"
                else:
                    raise
            if failure is not None:
                raise FetchError(failure)   # outside the `except`: a status line that holds the server's text (and the key) is not this error's context
            return _read_response(response, policy, address, started + total_timeout, max_bytes, secrets)
        finally:
            if response is not None:
                response.close()   # a response that was refused before it was read still holds a file on the socket
            conn.close()
            sock.close()

    def cut():
        cancelled.set()
        for sock in list(live):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    return _with_deadline(run, total_timeout + 0.3, on_timeout=cut, name="kb-webclient")


def _scrub(message, secrets):
    """A message with every credential value, in any letter case, replaced: a server can echo the header it was sent into one it chooses, and the text of an error must not carry it out."""
    for secret in secrets:
        message = re.sub(re.escape(secret), "[credential]", message, flags=re.IGNORECASE)
    return message


def _ask(policy, address):
    if policy.check is None:
        return
    try:
        verdict = policy.check(address)
    except Exception:
        raise Refused("the address check failed, so the request was not made") from None
    if verdict:
        raise Refused(f"refused: {textutil.clean(str(getattr(verdict, 'reason', verdict)), 200)}")


def get(url, *, policy, headers=None, max_bytes=MAX_BYTES, timeout=TIMEOUT, total_timeout=TOTAL_TIMEOUT):
    """One GET of `url` under `policy`, following redirects hop by hop if the policy allows. Returns `Result` (a `(status, headers, body)` tuple with `.final`), or raises `Refused` or `FetchError`.
    `timeout` is the limit of one network operation; `total_timeout` of one hop's connection and body (each hop of a redirect has its own)."""
    return _exchange("GET", None, url, policy, headers, max_bytes, timeout, total_timeout)


def post_json(url, body, *, policy, headers=None, max_bytes=MAX_BYTES, timeout=TIMEOUT, total_timeout=TOTAL_TIMEOUT):
    """One POST of `body` (bytes, one to `MAX_POST_BYTES`, a JSON request that the caller made; nothing here reads it) to `url` under `policy`, sent as `Content-Type: application/json`, which no header of a
    caller can change. A POST never follows a redirect, whatever the policy says (it is refused if the policy allows one, and a redirect answer is refused), and every other rule is a GET's: the address,
    the hook, the pacing, the credential (only over https, to its own host), the size, the time and the type of the answer. Returns `Result`, or raises `Refused` or `FetchError`. **The answer's body is data from the server:
    a server that holds the key can echo it there (the headers and the messages are scrubbed, the body is not), so a caller does not log or keep the body of a keyed answer.**"""
    if type(body) is not bytes or not 1 <= len(body) <= MAX_POST_BYTES:
        raise Refused(f"the body of a POST is bytes, from 1 to {MAX_POST_BYTES} of them")
    if policy.follow_redirects:
        raise Refused("a POST follows no redirect")
    return _exchange("POST", body, url, policy, headers, max_bytes, timeout, total_timeout)


def _exchange(method, body, url, policy, headers, max_bytes, timeout, total_timeout):
    try:
        address = webaddr.canon_address(url)
    except webaddr.AddressError as e:
        raise Refused(f"not a usable address: {e}") from None
    extras = {**_clean_headers(policy.headers, "policy"), **_clean_headers(headers, "call")}
    credentials = _clean_headers(policy.credential_headers, "credential")
    user_agent = _check_value(policy.user_agent, "user agent")
    first = urlsplit(address)
    if credentials:
        # the host of a canonical address is canonical, so equality with it also means the credential host is written in canonical form
        if policy.follow_redirects or first.scheme != "https" or first.hostname != policy.credential_host:
            raise Refused("a credential is sent only over https to its own host, in a call that follows no redirect")
    pacer = policy.pacer or PACER
    secrets = [v for v in credentials.values() if v]
    secrets += [" ".join(v.split()) for v in list(secrets) if " ".join(v.split()) != v]   # a server's text is made clean (spaces collapsed and cut off) before the scrub, so the value is also named the way it will read
    secrets += [token for token in (v.split(None, 1)[1].strip() for v in list(secrets) if len(v.split(None, 1)) == 2) if len(token) >= MIN_TOKEN_SCRUB]   # a bearer key is also named alone: the token after the scheme (a token too short to be a key would blank ordinary text, and is left to the whole value's scrub)
    for hop in range(policy.max_redirects + 1):
        parts = urlsplit(address)
        host = parts.hostname
        _ask(policy, address)
        port = webaddr.DEFAULT_PORT[parts.scheme]
        try:
            addresses = _with_deadline(lambda: resolve_checked(host, port, policy.allow_private), total_timeout)
        except PolicyError as e:
            raise Refused(str(e)) from None
        addresses = addresses[:MAX_ADDRESSES]
        if not policy.allow_private and not all(_acceptable(a) for a in addresses):
            raise Refused(f"{host} resolves to an address that is not fetched")
        hop_headers = {"User-Agent": user_agent, "Accept": policy.accept, "Accept-Encoding": "identity"}
        if host == first.hostname and parts.scheme == first.scheme:   # not to another host, and not in the clear after a step down to http
            hop_headers.update(extras)
            if hop == 0:
                hop_headers.update(credentials)
        if method == "POST":
            for name in [k for k in hop_headers if k.lower() == "content-type"]:
                del hop_headers[name]   # whatever spelling a policy, a call or a credential gave
            hop_headers["Content-Type"] = "application/json"   # last, so that nothing the caller gave can change it
        keys = [f"site:{webaddr.site_info(host, policy.suffixes)[0]}", _ip_key(addresses[0])]   # the address tried first: a name cannot hold the addresses of other sites
        with pacer.slot(keys, policy.gap, policy.jitter):
            rebuilt = None
            try:
                outcome = _request(parts, addresses, port, hop_headers, policy, timeout, total_timeout, max_bytes, address, secrets, method, body)
            except FetchError as e:
                safe = _scrub(str(e), secrets)
                if safe == str(e):
                    raise
                rebuilt = (type(e), safe)
            if rebuilt is not None:
                raise rebuilt[0](rebuilt[1])   # outside the `except`, so that the unscrubbed error is not this one's context
        if isinstance(outcome, Result):
            return outcome
        if not policy.follow_redirects:
            raise Refused("the server redirected, and this request follows no redirect")
        locations = outcome[1]
        if len(locations) != 1 or not locations[0].strip():
            raise Refused("a redirect with no usable Location was refused")
        try:
            address = webaddr.canon_address(urljoin(address, locations[0].strip()))
        except webaddr.AddressError as e:
            raise Refused(f"a redirect to an address that is not allowed was refused: {textutil.clean(str(e), 120)}") from None
    raise Refused(f"too many redirects (more than {policy.max_redirects})")
