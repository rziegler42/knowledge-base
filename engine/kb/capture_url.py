"""Capture a web page: one plain GET, stored as it came, with a record of where it came from.

The fetch is bounded (a size cap, a per-read timeout and a deadline for the whole fetch), asks for the page unencoded,
sends no cookies or credentials, and follows at most a few redirects, only to http and https. Unless the owner allows it,
it refuses addresses on the local machine or a private network, including a redirect to one. Nothing downloaded is
parsed here: the page is stored whole and left for the conversion stage.

A page is looked up by identity before any download and by content hash after it. A page the library already holds is
not stored again: a different address with the same bytes, or a redirect to a held address, is a sighting on the
existing book. A capture that stopped half way is resumed by the next call for the same address."""
import hashlib
import http.client
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import KbError, __version__, identity, ids, stages, textutil
from .store import now

USER_AGENT = f"knowledge-base/{__version__} (single GET; personal research library)"
TOOL = f"capture-url {__version__}"
KEPT_HEADERS = ("content-type", "content-encoding", "last-modified", "etag", "content-language", "cache-control", "date")
PAGE_TYPES = ("text/html", "application/xhtml+xml")
MAX_BYTES = 20_000_000
TIMEOUT = 10.0
TOTAL_TIMEOUT = 30.0
MAX_REDIRECTS = 5


class FetchError(Exception):
    """A fetch that did not give a page. The message is the reason that is recorded."""


class PolicyError(FetchError):
    """An address refused by policy: on the local machine or a private network."""


def _with_deadline(fn, seconds, on_timeout=None, name="kb-fetch"):
    """Run fn and give up after `seconds`, whatever it is waiting on (a connection, the headers, a name lookup).

    The work runs in a thread, which cannot be stopped from outside. When the time is up, `on_timeout` is called to cut
    what the thread is waiting on (the fetch closes its sockets), so the thread ends within moments instead of living on
    behind a server that trickles its answer. A name lookup that is stuck in the system resolver cannot be cut, and
    ends when the resolver gives up."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # carried back to the caller
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True, name=name)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        if on_timeout is not None:
            on_timeout()
            worker.join(2)
        raise FetchError("timed out")
    if "error" in box:
        raise box["error"]
    return box["value"]


# Address ranges that hide another address inside an IPv6 one, and ranges that are never a public host.
_V4_IN_V6 = ipaddress.ip_network("::/96")            # IPv4-compatible (deprecated)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")        # NAT64: the last 32 bits are an IPv4 address
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")
_SIXTOFOUR = ipaddress.ip_network("2002::/16")       # 6to4: bits 16 to 48 are an IPv4 address
_TEREDO = ipaddress.ip_network("2001::/32")
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")


def is_public(ip):
    """Whether an address is an ordinary public one. An IPv6 address that carries an IPv4 one (mapped, compatible, NAT64,
    6to4) is judged by the IPv4 address it carries; Teredo, site-local and NAT64-local ranges are never public."""
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return is_public(ip.ipv4_mapped)
        if ip in _TEREDO or ip in _SITE_LOCAL or ip in _NAT64_LOCAL:
            return False
        if ip in _NAT64 or (ip in _V4_IN_V6 and int(ip) > 1):
            return is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip in _SIXTOFOUR:
            return is_public(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
    return ip.is_global and not ip.is_multicast


def resolve_checked(host, port, allow_private):
    """Resolve a host once and return its addresses, refusing the name if any of them is not public (unless allowed).
    The caller connects to one of these addresses, so what was checked is what is connected to."""
    if "%" in host:
        raise PolicyError(f"the host {host!r} is written with percent escapes")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise FetchError(f"cannot resolve {host}: {getattr(e, 'strerror', None) or e}") from None
    addresses = []
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if not allow_private and not is_public(ip):
            raise PolicyError(f"{host} is a private or local address ({ip})")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise FetchError(f"cannot resolve {host}")
    return addresses


def check_host_allowed(host, port, allow_private):
    """Refuse a host that resolves to a private or local address, unless that is allowed (see `resolve_checked`)."""
    resolve_checked(host, port, allow_private)


def _connect_checked(host, port, timeout, allow_private, live):
    """Open a connection to a host by the address that was checked, never by looking the name up a second time."""
    last = None
    for address in resolve_checked(host, port, allow_private):
        try:
            sock = socket.create_connection((address, port), timeout)
        except OSError as e:
            last = e
            continue
        live.append(sock)
        return sock
    raise last or OSError(f"cannot connect to {host}")


def _guarded_handlers(allow_private, live):
    """http and https handlers whose connections go through `_connect_checked`, and keep their sockets in `live` so that
    the caller can cut them when the deadline passes."""
    class Conn(http.client.HTTPConnection):
        def connect(self):
            self.sock = _connect_checked(self.host, self.port, self.timeout, allow_private, live)

    class SConn(http.client.HTTPSConnection):
        def connect(self):
            raw = _connect_checked(self.host, self.port, self.timeout, allow_private, live)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)  # the certificate is checked for the name
            live.append(self.sock)  # wrapping detaches the raw socket from its descriptor: only this one can be cut now

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(Conn, req)

    class HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(SConn, req, context=self._context)

    return HTTP(), HTTPS()


def make_redirect_handler(allow_private, max_redirects):
    class Handler(urllib.request.HTTPRedirectHandler):
        max_redirections = max_redirects

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parts = urlsplit(newurl)
            scheme = parts.scheme.lower()
            if scheme not in ("http", "https") or not parts.hostname:
                raise FetchError(f"a redirect to a {scheme or 'relative'} address was refused")
            if parts.username is not None or parts.password is not None:
                raise FetchError("a redirect carrying a user name or password was refused")
            if "%" in parts.hostname:
                raise FetchError("a redirect to a host written with percent escapes was refused")
            check_host_allowed(parts.hostname, parts.port or identity.DEFAULT_PORT[scheme], allow_private)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return Handler()


def _opener(allow_private, max_redirects, live):
    """An opener with only the http and https handlers (no file, ftp or data), no proxy from the environment, and
    connections that go to the address that was checked."""
    opener = urllib.request.OpenerDirector()
    http_handler, https_handler = _guarded_handlers(allow_private, live)
    for handler in (urllib.request.ProxyHandler({}), http_handler, https_handler,
                    urllib.request.HTTPDefaultErrorHandler(), make_redirect_handler(allow_private, max_redirects),
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


class Page:
    def __init__(self, final, status, headers, body):
        self.final, self.status, self.headers, self.body = final, status, headers, body


def _timed_out(exc):
    return isinstance(exc, (socket.timeout, TimeoutError)) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (socket.timeout, TimeoutError)))


def _fetch(address, allow_private, max_bytes, timeout, total_timeout, max_redirects, types, what, accept, live):
    request = urllib.request.Request(address, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Encoding": "identity",
    })
    deadline = time.monotonic() + total_timeout
    try:
        response = _opener(allow_private, max_redirects, live).open(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        e.close()
        if 300 <= e.code < 400:
            raise FetchError("too many redirects, or a redirect loop") from None
        raise FetchError(f"HTTP {e.code}") from None
    except FetchError:
        raise
    except Exception as e:  # a network failure of any kind is a failed fetch, not a crash
        if _timed_out(e):
            raise FetchError("timed out") from None
        if isinstance(e, urllib.error.URLError):
            raise FetchError(f"cannot connect: {e.reason}") from None
        if isinstance(e, (OSError, http.client.HTTPException, ValueError)):
            raise FetchError(f"network error: {e}") from None
        raise
    with response:
        if response.status != 200:
            raise FetchError(f"HTTP {response.status}")
        content_type = response.headers.get("Content-Type")
        if content_type and content_type.split(";")[0].strip().lower() not in types:
            raise FetchError(f"not a {what}: its content type is {content_type.split(';')[0].strip()}")
        for encoding in response.headers.get_all("Content-Encoding") or []:  # every such header, not only the first
            if encoding.strip().lower() != "identity":
                raise FetchError(f"the server sent the page encoded ({encoding.strip()}) although none was asked for")
        lengths = response.headers.get_all("Content-Length") or []
        if len(lengths) > 1 and len({v.strip() for v in lengths}) > 1:
            raise FetchError("the server sent conflicting Content-Length headers")
        declared = None
        if lengths:
            if not re.fullmatch(r"[0-9]{1,15}", lengths[0].strip()):  # ASCII digits only: str.isdigit accepts others
                raise FetchError("the server sent a Content-Length that is not a number")
            declared = int(lengths[0].strip())
        if declared is not None and declared > max_bytes:
            raise FetchError(f"the page is larger than {max_bytes} bytes (it says {declared})")
        chunks, total = [], 0
        while True:
            if time.monotonic() > deadline:
                raise FetchError("timed out reading the page")
            try:
                chunk = response.read1(65536)  # whatever has arrived, so the deadline is checked often
            except Exception as e:
                if _timed_out(e):
                    raise FetchError("timed out") from None
                raise FetchError(f"network error while reading: {e}") from None
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise FetchError(f"the page is larger than {max_bytes} bytes")
            chunks.append(chunk)
        if declared is not None and total != declared:
            # read1 does not raise when the connection closes early, so the length is checked here
            raise FetchError(f"the page ended early: {total} of {declared} bytes arrived")
        headers = {k: textutil.clean(response.headers[k], 300) for k in KEPT_HEADERS if response.headers.get(k) is not None}
        return Page(response.geturl(), response.status, headers, b"".join(chunks))


def fetch(address, allow_private=False, max_bytes=MAX_BYTES, timeout=TIMEOUT, total_timeout=TOTAL_TIMEOUT,
          max_redirects=MAX_REDIRECTS, types=PAGE_TYPES, what="web page",
          accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"):
    """One GET of an already-normalised address, with a deadline over the whole of it. Only a response whose content
    type is in `types` is taken (`what` names it in the refusal). Returns a Page or raises FetchError."""
    live = []  # the sockets the fetch opens, so that they can be cut if the deadline passes

    def cut():
        for sock in list(live):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    # the thread's limit sits a little after the fetch's own, so the fetch normally reports its own reason first
    return _with_deadline(lambda: _fetch(address, allow_private, max_bytes, timeout, total_timeout, max_redirects,
                                         types, what, accept, live), total_timeout + 0.3, on_timeout=cut)


def _live(store, ident, kind, value):
    """The book an index entry names, if that book exists. An entry for a book that was never made is stale."""
    book_id = ident.lookup(kind, value)
    if book_id:
        try:
            store.read_book(book_id)
        except KbError:
            return None
    return book_id


def _current_version(store, book_id):
    version = store.read_book(book_id)["current_version"]
    return version if version else store.add_version(book_id)


def _unfinished(store, book_id):
    version = store.read_book(book_id)["current_version"]
    if not version:
        return True
    return stages.read(store, book_id, version)["stages"]["fetched"]["status"] not in ("done", "skipped")


def _result(status, book_id, version_id, reason=None):
    out = {"status": status, "book_id": book_id, "version_id": version_id}
    if reason is not None:
        out["reason"] = reason
    return out


def _resume(store, ident, book_id, version_id):
    """If an earlier capture filed its payload before it stopped, check and adopt it. Returns a result to hand back,
    or None when there is nothing filed and the page has to be fetched (or stored) now."""
    outcome = stages.reconcile(store, book_id, version_id, "fetched", "original")
    if outcome == "adopted":
        _register_from_source(store, ident, book_id, version_id)
        source = store.read_version(book_id, version_id)["source"]
        if not any(e["event"] == "filed" and e.get("sha256") == source["sha256"] for e in store.read_events(book_id)):
            store.append_event(book_id, "filed", address_asked=source["address_asked"],
                               address_final=source["address_final"], sha256=source["sha256"],
                               retrieved=source["retrieved"], resumed=True)
        return _result("held", book_id, version_id)
    if outcome == "invalid":
        reason = stages.read(store, book_id, version_id)["stages"]["fetched"]["reason"]
        return _result("failed", book_id, version_id, reason)
    return None


def require_allowed(address, allow_private, total_timeout=TOTAL_TIMEOUT):
    """Refuse (KbError) an address that resolves to a private or local address, unless that is allowed. A name that
    cannot be resolved, or resolves too slowly, is left to the fetch, which records it as a failed fetch."""
    parts = urlsplit(address)
    try:
        _with_deadline(lambda: check_host_allowed(parts.hostname, parts.port or identity.DEFAULT_PORT[parts.scheme],
                                                  allow_private), total_timeout)
    except PolicyError as e:
        raise KbError(f"{e}; pass --allow-private to allow local and private-network addresses") from None
    except FetchError:
        pass


def capture(store, ident, address, allow_private=False, max_bytes=MAX_BYTES, timeout=TIMEOUT,
            total_timeout=TOTAL_TIMEOUT):
    """Capture one web page into the library. Returns a dict whose status is:

    filed      the page was fetched and stored as a new book (or into a book whose earlier fetch had failed or stopped);
    held       the library already holds it, so nothing was downloaded;
    duplicate  it was fetched but the library already holds it (same final address or same bytes): a sighting;
    failed     the fetch failed; the reason is recorded in the book's stage state, and a later call retries it.

    A refused address (bad scheme, credentials, a private address without permission) raises KbError and records nothing."""
    asked = identity.normalize_address(address)
    store._guard()
    require_allowed(asked, allow_private, total_timeout)

    book_id = _live(store, ident, "url", asked)
    version_id = None
    if book_id:
        version_id = _current_version(store, book_id)
        if stages.read(store, book_id, version_id)["stages"]["fetched"]["status"] in ("done", "skipped"):
            return _result("held", book_id, version_id)
        resumed = _resume(store, ident, book_id, version_id)  # a payload may have been filed before a stop
        if resumed:
            return resumed

    try:
        page = fetch(asked, allow_private, max_bytes, timeout, total_timeout)
        if page.body[:2] == b"\x1f\x8b" or b"\x00" in page.body[:8192]:
            # a web page is text; compressed or binary data under a page's name would be stored as page.html
            raise FetchError("the response looks like binary or compressed data, not a web page")
        try:
            final = identity.normalize_address(page.final)
        except KbError as e:
            raise FetchError(f"the final address is not usable: {e}") from None
    except FetchError as e:
        reason = textutil.clean(str(e), 300)  # the reason can carry text a server chose, such as a content type
        if not book_id:
            book_id = ids.new_book_id()
            ident.reassign("url", asked, book_id)  # recorded first, so a stop after the book is made still finds it
            store.create_book(title="", kind="web page", identity_keys={"url": asked}, book_id=book_id)
            version_id = store.add_version(book_id, source={"address_asked": asked})
            store.append_event(book_id, "found", address_asked=asked)
        stages.mark(store, book_id, version_id, "fetched", "failed", reason=reason, tool=TOOL)
        return _result("failed", book_id, version_id, reason)

    digest = hashlib.sha256(page.body).hexdigest()
    retrieved = now()
    url_owner, hash_owner = _live(store, ident, "url", final), _live(store, ident, "sha256", digest)
    other = next((b for b in (url_owner, hash_owner) if b and b != book_id), None)
    if other and _unfinished(store, other):
        # not a duplicate: the book that holds this address is an earlier capture of the same page that never finished
        book_id, other = other, None
        version_id = _current_version(store, book_id)
        resumed = _resume(store, ident, book_id, version_id)
        if resumed:
            return resumed
    if other:
        return _sighting(store, ident, other, hash_owner, book_id, version_id, asked, final, digest, retrieved)

    source = {"address_asked": asked, "address_final": final, "http_status": page.status, "retrieved": retrieved,
              "headers": page.headers, "sha256": digest, "bytes": len(page.body)}
    if book_id:
        store.set_version_source(book_id, version_id, source)
    else:
        book_id = ids.new_book_id()
        aliases = [asked] if asked != final else []
        for value in [final] + aliases:
            ident.reassign("url", value, book_id)  # recorded first, so a stop after the book is made still finds it
        keys = {"url": final, **({"url_alias": aliases} if aliases else {})}
        store.create_book(title="", kind="web page", identity_keys=keys, book_id=book_id)
        version_id = store.add_version(book_id, source=source)
    store.file_payload(book_id, version_id, "original", {"page.html": page.body}, primary="page.html", tool=TOOL)
    _register_from_source(store, ident, book_id, version_id)
    store.append_event(book_id, "filed", address_asked=asked, address_final=final, sha256=digest, retrieved=retrieved)
    stages.mark(store, book_id, version_id, "fetched", "done", tool=TOOL)
    return _result("filed", book_id, version_id)


def _register_from_source(store, ident, book_id, version_id):
    """Record a captured version's addresses and hash as the book's identity keys and in the index."""
    source = store.read_version(book_id, version_id)["source"]
    asked, final, digest = source["address_asked"], source["address_final"], source["sha256"]
    aliases = [asked] if asked != final else []
    store.merge_identity_keys(book_id, set_keys={"url": final}, add_keys={"url_alias": aliases, "sha256": [digest]})
    for value in [final] + aliases:
        ident.reassign("url", value, book_id)
    ident.register("sha256", digest, book_id)


def _sighting(store, ident, other, hash_owner, candidate, candidate_version, asked, final, digest, retrieved):
    """The fetched page is one the library holds under another book: note it there, and point the new addresses at it.

    The bytes' hash is added to that book only when no other book already holds those bytes."""
    keys = store.read_book(other)["identity_keys"]
    same_bytes = digest in keys.get("sha256", [])
    store.append_event(other, "sighting", address_asked=asked, address_final=final, sha256=digest,
                       same_bytes=same_bytes, retrieved=retrieved)
    aliases = [a for a in dict.fromkeys([asked, final]) if a != keys.get("url")]
    claim_hash = hash_owner in (None, other)
    store.merge_identity_keys(other, add_keys={"url_alias": aliases, "sha256": [digest] if claim_hash else []})
    for value in aliases:
        ident.reassign("url", value, other)
    if claim_hash:
        ident.register("sha256", digest, other)
    if candidate:
        stages.mark(store, candidate, candidate_version, "fetched", "skipped", reason=f"duplicate of book {other}",
                    tool=TOOL)
        store.set_state(candidate, "duplicate")
    return _result("duplicate", other, store.read_book(other)["current_version"])
