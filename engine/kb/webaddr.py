"""Canonical addresses, hosts and sites for the unattended crawl (`docs/specs/population.md`, "Addresses, hosts and sites: one canonical form"; the plan
`2026-11-16-harden-the-fetch-for-the-unattended-crawl`, Increment A).

This is the one place that canonicalises, and every other module of the crawl calls it: the identity keys of the queue, every blacklist and list match, and every per-site counter. A trailing dot, an upper-case
name, an internationalised name and `:80` all give one key. **It makes no request and imports nothing that could.**

  * `canon_host(name)` lower-cases, strips one trailing dot, converts an international name to its ASCII form and refuses anything that is not a hostname or an IP address in its canonical form. The standard
    library converts by IDNA 2003 and not by UTS 46's non-transitional processing, which needs a package this project does not install; the four characters on which the two differ (`ß`, `ς` and the zero-width
    joiners) are therefore **refused and not mapped**, so that no two spellings can ever disagree.
  * `canon_address(url)` keeps only `http` and `https`, no credentials, the default port dropped and any other port refused, no fragment, an empty path as `/`, dot segments removed, percent escapes in upper case,
    non-ASCII encoded, the tracking parameters (every `utm_` and `mc_` parameter, and `fbclid` and `gclid`) removed, and at most 2,048 characters. It is idempotent.
  * `identity_key(x)` is `arxiv:<id>` for an arXiv paper in any spelling (never with the version), else the canonical address; **a DOI is never a key**.
  * `site_of(host, suffixes)` is the registrable domain by the Public Suffix List; without a list it is the last two labels, and `site_info` says that the fallback was used.

Text from outside is untrusted: a refusal is `AddressError`, and nothing is stripped or guessed at (a space is refused, not trimmed)."""
import ipaddress
import os
import re
import stat
import unicodedata
from urllib.parse import urlsplit

from . import KbError

MAX_ADDRESS = 2048
MAX_NAME = 253
MAX_LABEL = 63
MAX_SUFFIX_BYTES = 2 * 1024 * 1024
MAX_SUFFIX_RULES = 50_000
DEFAULT_PORT = {"http": 80, "https": 443}
TRACKING_PREFIXES = ("utm_", "mc_")
TRACKING_NAMES = ("fbclid", "gclid")
DEVIATIONS = ("\u00df", "\u03c2", "\u200c", "\u200d")   # where IDNA 2003 and UTS 46 differ: refused
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_LABEL = re.compile(r"(?:0x[0-9a-f]*|[0-9]+)")
_PORT = re.compile(r"[0-9]{1,5}", re.ASCII)
_SCHEME = re.compile(r"(https?)://", re.I)
_NEW_ID = r"\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}"
_OLD_ID = r"[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{2}(?:0[1-9]|1[0-2])\d{3}"
_ARXIV_ID = re.compile(rf"(?P<id>{_NEW_ID}|{_OLD_ID})(?:v(?P<v>[1-9]\d{{0,5}}))?", re.ASCII)
_ARXIV_PATH = re.compile(rf"/(?:abs|pdf)/(?P<id>{_NEW_ID}|{_OLD_ID})(?:v[1-9]\d{{0,5}})?(?:\.pdf)?", re.ASCII)
_ARXIV_HOSTS = ("arxiv.org", "www.arxiv.org", "export.arxiv.org")
_DOI_HOSTS = ("doi.org", "dx.doi.org")
_DOI_TEXT = re.compile(r"(?:doi:|10\.\d{4,9}/)", re.I)
_PATH_SAFE = frozenset("-._~!$&'()*+,;=:@/")
_QUERY_SAFE = _PATH_SAFE | {"?"}


class AddressError(KbError):
    """An address, a host or a list of suffixes that is refused. The message is safe to log."""


def _refuse(message):
    raise AddressError(message)


def _check_text(value, what):
    """Refuse anything that is not text, and any character that is a control, a format or a space character (bidirectional marks, zero-width characters, line separators): nothing is stripped."""
    if not isinstance(value, str):
        _refuse(f"{what} must be text")
    for c in value:
        if ord(c) < 33 or ord(c) == 127 or unicodedata.category(c)[0] in ("C", "Z"):
            _refuse(f"{what} has a space, control or invisible character (U+{ord(c):04X})")


def _ascii_label(label):
    if not label:
        _refuse("a host name has an empty label")
    if label.isascii():
        ascii_label = label
    else:
        try:
            ascii_label = label.encode("idna").decode("ascii")
        except UnicodeError:
            _refuse("a host name label cannot be converted to its ASCII form")
    if len(ascii_label) > MAX_LABEL or not _LABEL.fullmatch(ascii_label):
        _refuse("a host name label is not a valid label")
    if ascii_label.startswith("xn--"):
        try:
            decoded = ascii_label[4:].encode("ascii").decode("punycode")
            again = decoded.encode("punycode").decode("ascii")
        except UnicodeError:
            _refuse("a host name label is bad punycode")
        if again != ascii_label[4:] or not decoded:
            _refuse("a host name label is not canonical punycode")
        _check_text(decoded, "a host name label")
        if unicodedata.normalize("NFKC", decoded).lower() != decoded or any(c in decoded for c in DEVIATIONS):
            _refuse("a host name label decodes to a name that is not in canonical form")
    return ascii_label


def canon_host(name):
    """The canonical form of a host name or an IP address, or `AddressError`. A name carries no port, path or brackets (but `[::1]` is accepted for an IPv6 address)."""
    if isinstance(name, str) and len(name) > MAX_NAME + 2:   # room for the brackets of an IPv6 address
        _refuse("a host is too long")
    _check_text(name, "a host")
    text = name
    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            _refuse("a host has an unbalanced bracket")
        text = text[1:-1]
        if ":" not in text:
            _refuse("only an IPv6 address may be written in brackets")
    if "%" in text:
        _refuse("a host is written with a percent escape or a zone")
    if ":" in text:
        try:
            return str(ipaddress.IPv6Address(text))
        except ValueError:
            _refuse("a host has a port or is not an IPv6 address")
    text = unicodedata.normalize("NFKC", text).lower()
    if any(c in text for c in DEVIATIONS):
        _refuse("a host has a character that IDNA 2003 and UTS 46 map differently, and it is not accepted")
    if text.endswith("."):
        text = text[:-1]
    if not text:
        _refuse("a host is empty")
    labels = [_ascii_label(label) for label in text.split(".")]
    ascii_name = ".".join(labels)
    if len(ascii_name) > MAX_NAME:
        _refuse("a host name is over 253 characters")
    if _NUMERIC_LABEL.fullmatch(labels[-1]):   # a browser reads a name whose last label is a number as an IPv4 address: only the canonical dotted form is one
        try:
            return str(ipaddress.IPv4Address(ascii_name))
        except ValueError:
            _refuse("a host looks like an IPv4 address but is not in its canonical form")
    return ascii_name


def _percent(text, safe, what):
    """Upper-case the escapes already there, encode what must be encoded, and refuse a `%` that starts no escape."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "%":
            digits = text[i + 1:i + 3]
            if len(digits) != 2 or any(d not in "0123456789abcdefABCDEF" for d in digits):
                _refuse(f"{what} has a % that does not start an escape")
            char = chr(int(digits, 16))
            out.append(char if char.isascii() and (char.isalnum() or char in "-_~") else "%" + digits.upper())
            i += 3
            continue
        if c.isascii() and (c.isalnum() or c in safe):
            out.append(c)
        else:
            out.extend("%%%02X" % b for b in c.encode("utf-8"))
        i += 1
    return "".join(out)


def _dot_segments(path):
    out, trailing = [], False
    segments = path.split("/")[1:]
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment == ".":
            trailing = last
            continue
        if segment == "..":
            if out:
                out.pop()
            trailing = last
            continue
        out.append(segment)
        trailing = False
    result = "/" + "/".join(out)
    return result + "/" if trailing and out else result


def _tracking(part):
    name = part.split("=", 1)[0].lower()
    return name in TRACKING_NAMES or name.startswith(TRACKING_PREFIXES)


def canon_address(url):
    """The canonical form of a web address, or `AddressError`. See the top of this module for what that is."""
    if isinstance(url, str) and len(url) > MAX_ADDRESS:
        _refuse("an address is over 2,048 characters")
    _check_text(url, "an address")
    if not url:
        _refuse("an address is empty")
    scheme_match = _SCHEME.match(url)
    if not scheme_match:
        _refuse("only http and https addresses are accepted")
    scheme = scheme_match.group(1).lower()
    try:
        parts = urlsplit(url)
    except ValueError:
        _refuse("not a usable address")
    netloc = parts.netloc
    if "@" in netloc:
        _refuse("an address carries a user name or password")
    if netloc.startswith("["):
        close = netloc.find("]")
        if close < 0:
            _refuse("an address has an unbalanced bracket")
        host, rest = netloc[:close + 1], netloc[close + 1:]
        port_text = rest[1:] if rest.startswith(":") else None
        if rest and port_text is None:
            _refuse("an address has text after its IPv6 host")
    elif ":" in netloc:
        if netloc.count(":") > 1:
            _refuse("an address has a host with colons that is not in brackets")
        host, _, port_text = netloc.rpartition(":")
    else:
        host, port_text = netloc, None
    if port_text:
        if not _PORT.fullmatch(port_text) or not 1 <= int(port_text) <= 65535:
            _refuse("an address has a port that is not a usable number")
        if int(port_text) != DEFAULT_PORT[scheme]:
            _refuse("only the default port of the scheme is accepted")
    shown = canon_host(host)
    if ":" in shown:
        shown = f"[{shown}]"
    path = _dot_segments(_percent(parts.path or "/", _PATH_SAFE, "an address path"))
    normal = [_percent(part, _QUERY_SAFE, "an address query") for part in parts.query.split("&") if part]
    query = "&".join(part for part in normal if not _tracking(part))
    result = f"{scheme}://{shown}{path}" + (f"?{query}" if query else "")
    if len(result) > MAX_ADDRESS:
        _refuse("an address is over 2,048 characters once canonical")
    return result


def identity_key(value):
    """`arxiv:<id>` for an arXiv paper written in any way (a bare id, `arXiv:` and an id, an abs or pdf address on arxiv.org), else the canonical address of a page. A DOI is never a key."""
    if not isinstance(value, str):
        _refuse("an identity key is made from text")
    if _DOI_TEXT.match(value):
        _refuse("a DOI is never an identity key: resolve it to an arXiv id or an address first")
    bare = value[6:] if value[:6].lower() == "arxiv:" else value
    found = _ARXIV_ID.fullmatch(bare)
    if found:
        return "arxiv:" + found.group("id")
    address = canon_address(value)
    parts = urlsplit(address)
    host = parts.hostname or ""
    if host in _DOI_HOSTS:
        _refuse("a DOI address is never an identity key: resolve it first")
    if host in _ARXIV_HOSTS:
        paper = _ARXIV_PATH.fullmatch(parts.path)
        if paper:
            return "arxiv:" + paper.group("id")
    return address


def load_suffixes(path):
    """The rules of a Public Suffix List file as a frozenset of canonical ASCII rules (`co.uk`, `*.ck`, `!www.ck`). The file is read as data: no link, a regular file only, at most 2 MiB, UTF-8, at most
    50,000 rules; a comment, a blank line and anything after the first space of a line are ignored, and a line that is not a valid rule is ignored."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        _refuse("the suffix list path must be a path")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (OSError, ValueError) as e:
        _refuse(f"the suffix list cannot be opened ({getattr(e, 'strerror', None) or 'bad path'})")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _refuse("the suffix list is not a regular file")
        if info.st_size > MAX_SUFFIX_BYTES:
            _refuse("the suffix list is too large")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_SUFFIX_BYTES:
                _refuse("the suffix list is too large")
        data = b"".join(chunks)
    except OSError as e:
        _refuse(f"the suffix list cannot be read ({e.strerror})")
    finally:
        os.close(fd)
    return parse_suffixes(data)


def parse_suffixes(data):
    """The rules of a Public Suffix List given as bytes (what `load_suffixes` reads from a file), so that the bytes that were checked are the bytes that are parsed."""
    if not isinstance(data, (bytes, bytearray)):
        _refuse("the suffix list must be bytes")
    if len(data) > MAX_SUFFIX_BYTES:
        _refuse("the suffix list is too large")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        _refuse("the suffix list is not UTF-8")
    rules, count = set(), 0
    for line in text.splitlines():
        token = line.split(None, 1)[0] if line.split() else ""
        if not token or token.startswith("//"):
            continue
        prefix = "!" if token.startswith("!") else "*." if token.startswith("*.") else ""
        try:
            rule = prefix + canon_host(token[len(prefix):])
        except AddressError:
            continue
        count += 1
        if count > MAX_SUFFIX_RULES:
            _refuse("the suffix list has too many rules")
        rules.add(rule)
    return frozenset(rules)


def site_info(host, suffixes=None):
    """`(site, exact)`: the registrable domain of a host, and whether it was found by a suffix list (`exact`) or by the fallback of the last two labels (a list that is absent or empty is no list)."""
    host = canon_host(host)
    if ":" in host or host.replace(".", "").isdigit():
        return host, True
    labels = host.split(".")
    n = len(labels)
    if not suffixes:
        return (".".join(labels[-2:]) if n > 2 else host), False
    for i in range(n):
        if "!" + ".".join(labels[i:]) in suffixes:
            suffix_len = n - i - 1
            return ".".join(labels[-(suffix_len + 1):]), True
    suffix_len = 1   # the default rule `*`
    for i in range(n):
        if ".".join(labels[i:]) in suffixes or ("*." + ".".join(labels[i + 1:]) in suffixes and i + 1 < n):
            suffix_len = n - i
            break
    return ".".join(labels[-(suffix_len + 1):]), True


def site_of(host, suffixes=None):
    """The registrable domain of a host (see `site_info`)."""
    return site_info(host, suffixes)[0]
