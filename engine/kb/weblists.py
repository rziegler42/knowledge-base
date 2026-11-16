"""The owner's blacklist, the allow file and the public lists of known-malicious sites (`docs/specs/population.md`, "Sites that are off limits"; the plan
`2026-11-16-harden-the-fetch-for-the-unattended-crawl`, Increment D).

`Matcher.blocked(address_or_host)` says whether an address may not be requested, as `None` (it may) or a `Block` with a reason (`owner`, `list:<name>`, or `unusable` for text that is no address or host). The
check is made on canonical forms (`webaddr`), so `evil.com`, `evil.com.`, `EVIL.com`, `evil.com:80` and an internationalised spelling are one entry. In this order:

  1. **The owner's blacklist** (a plain file of hostnames, outside the repository) blocks the host and every host below it. Nothing overrides it. A missing file is an empty list; a bad line is an error naming
     the line number, and the list in use stays.
  2. **The pinned hosts** (the scholarly and search sources) are never blocked by a public list: a host and every host below it.
  3. **The allow file** (part of the approved plan) lets through, for the host written in it only, what a public list would block. It never overrides the blacklist.
  4. **A public host list** (Phishing.Database) blocks that exact hostname only, so that an entry for one subdomain cannot block a whole service.
  5. **A public URL list** (URLhaus; its entries are put in by `set_urls`) blocks that exact canonical URL, and a whole host only when the entry's host is a bare IP address: on 2026-11-16 one entry of that list had the
     host `github.com`, so matching by host would have blocked every page there.

`Matcher.update(get, now, lists_plan)` downloads the lists the plan names, each at most once in `refresh_hours`, through `get(url, headers, max_bytes) -> (status, headers, body)` (the runner passes the shared web
client under its list policy, so a list address that resolves to a private address is refused there; **this module makes no request of its own**). A list is **data**: only valid hostnames and addresses are taken. A
list is refused, and the last good copy stays in use, when it is over `list_max_mb`, has no valid entry, is smaller than `list_min_share` of the copy it replaces, or changes more than `list_max_change` of it in one
refresh; a failed download or a 304 changes nothing. Each copy is stored in the lists folder (mode 700, files 600) with its retrieval time, hash and validators, written to a temporary file and renamed into place, and
is read back only if it is a regular file and its hash matches. The report says which list did what; it carries no list text. A **required** list with no copy at all makes the report say `stop`.

The Public Suffix List is kept the same way (`public_suffix`, optional): `suffixes()` is what `webaddr.site_of` takes."""
import datetime
import hashlib
import ipaddress
import json
import os
import re
import stat
import threading
import time
from collections import namedtuple
from urllib.parse import urlsplit

from . import KbError, textutil, webaddr

MAX_LINES = 5_000_000          # lines of a public list that are read
MAX_OWNER_BYTES = 1_000_000    # the owner's blacklist and the allow file
MAX_STORED_BYTES = 256 * 1024 * 1024
MAX_META_BYTES = 64 * 1024
MIN_ENTRIES = {"phishing_domains": 100_000, "public_suffix": 5_000}   # a copy with fewer is refused, first or not (and a stored one is not used): the real lists had 391,548 hosts and 10,453 rules on 2026-11-16
STALE_TEMP_SECONDS = 3600     # a temporary file older than this belongs to a writer that is gone
ZERO = {"owner": frozenset(), "allow": frozenset(), "pinned": frozenset()}

DEFAULTS = {
    "phishing_domains": True,
    "urlhaus_recent": False,
    "phishing_domains_url": "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt",
    "phishing_domains_format": "domains",
    "public_suffix_url": "https://publicsuffix.org/list/public_suffix_list.dat",
    "refresh_hours": 12,
    "list_max_mb": 50,
    "list_min_share": 0.5,
    "list_max_change": 0.3,
    "urlhaus_keep_days": 30,
    "pinned_hosts": ["openalex.org", "arxiv.org", "wikipedia.org"],
}
FORMATS = ("domains",)
LISTS = (   # name, the plan key that turns it on (None: always), the plan key of its address, whether a run cannot go on without a copy
    ("phishing_domains", "phishing_domains", "phishing_domains_url", True),
    ("public_suffix", None, "public_suffix_url", False),
)
EXTENSIONS = {"phishing_domains": "txt", "public_suffix": "dat"}   # a stored data file is named `<list>.<first 16 hex of its hash>.<ext>`, so a record and its data change together
_SIIT = ipaddress.ip_network("::ffff:0:0:0/96")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPATIBLE = ipaddress.ip_network("::/96")
_SIXTOFOUR = ipaddress.ip_network("2002::/16")


class ListError(KbError):
    """A list, a file or a plan that is refused. The message is safe to log."""


class Block:
    """A reason an address may not be requested."""

    def __init__(self, reason):
        self.reason = reason

    def __str__(self):
        return self.reason

    def __repr__(self):
        return f"Block({self.reason!r})"

    def __bool__(self):
        return True


_SCHEME_LIKE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:(?![0-9]+(?:/|$))")


def _fold(host):
    """An IPv6 address that carries an IPv4 one (mapped, translated, NAT64, compatible, 6to4) is that IPv4 address, so that an entry written one way matches a request written the other."""
    if ":" not in host:
        return host
    ip = ipaddress.IPv6Address(host)
    if ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    if ip in _SIIT or ip in _NAT64 or (ip in _V4_COMPATIBLE and int(ip) > 1):
        return str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip in _SIXTOFOUR:
        return str(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
    return host


State = namedtuple("State", "owner allow pinned public urls suffixes")


def parse_domains(text):
    """`(hosts, ignored)` from a list with one hostname or address to a line. Blank lines and lines starting `#`, `//` or `;` are skipped; a line that is not one valid host (an underscore in a label, an address with a
    path, text with a space) is ignored and counted. Every host is in canonical form."""
    if text.count("\n") > MAX_LINES:   # counted before the text is split, so a list of one-character lines cannot make millions of strings
        raise ListError("the list has too many lines")
    lines = text.split("\n")
    found, ignored = set(), 0
    for line in lines:
        item = line.strip()
        if not item or item[0] in "#;" or item.startswith("//"):
            continue
        try:
            host = _fold(webaddr.canon_host(item))
        except webaddr.AddressError:
            ignored += 1
            continue
        if "." in host or ":" in host:
            found.add(host)
        else:
            ignored += 1    # a name with no dot is a top-level name or a local one: not a site to block
    return found, ignored


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def parse_urls(text):
    """`(urls, bare_hosts, ignored)` from a list with one address to a line: the canonical addresses, the hosts of those entries that are bare IP addresses, and the count of lines that are not addresses."""
    if text.count("\n") > MAX_LINES:   # counted before the text is split, so a list of one-character lines cannot make millions of strings
        raise ListError("the list has too many lines")
    lines = text.split("\n")
    urls, bare, ignored = set(), set(), 0
    for line in lines:
        item = line.strip()
        if not item or item[0] == "#":
            continue
        try:
            url = webaddr.canon_address(item)
        except webaddr.AddressError:
            ignored += 1
            continue
        urls.add(url)
        host = urlsplit(url).hostname
        if _is_ip(host):
            bare.add(_fold(host))
    return urls, bare, ignored


def _open_regular(path, limit, what):
    """The bytes of a regular file that is not a link and not over `limit`, or None if it is missing; `ListError` for anything else."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ListError(f"{what} cannot be opened ({getattr(e, 'strerror', None) or 'bad path'})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ListError(f"{what} is not a regular file")
        if info.st_size > limit:
            raise ListError(f"{what} is too large")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ListError(f"{what} is too large")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as e:
        raise ListError(f"{what} cannot be read ({e.strerror})") from None
    finally:
        os.close(fd)


def _owner_hosts(path, what):
    """The hosts of the owner's own file, strictly: one host a line, `#` starts a comment; a line that is not a host is an error that names its number (never its text). A missing file is an empty list."""
    data = _open_regular(path, MAX_OWNER_BYTES, what)
    if data is None:
        return frozenset()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ListError(f"{what} is not UTF-8 text") from None
    hosts, bad = set(), []
    for number, line in enumerate(text.split("\n"), 1):
        item = line.split("#", 1)[0].strip()
        if not item:
            continue
        try:
            hosts.add(_fold(webaddr.canon_host(item)))
        except webaddr.AddressError:
            bad.append(number)
    if bad:
        raise ListError(f"{what} has lines that are not hostnames: {', '.join(map(str, bad[:20]))}")
    return frozenset(hosts)


def _pinned(hosts):
    if not isinstance(hosts, (list, tuple)):
        raise ListError("the pinned hosts must be a list")
    out = set()
    for host in hosts:
        try:
            canonical = webaddr.canon_host(host)
        except webaddr.AddressError:
            raise ListError("a pinned host is not a hostname") from None
        if "." not in canonical and ":" not in canonical:
            raise ListError("a pinned host must be a site, not a single name such as a top-level domain")
        out.add(canonical)
    return frozenset(out)


def _number(value, what, low, high=None, low_open=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ListError(f"{what} must be a number")
    if value != value or (value <= low if low_open else value < low) or (high is not None and value > high):
        raise ListError(f"{what} is out of range")
    return value


def _flag(value, what):
    if isinstance(value, str) and value.strip().lower() in ("on", "off"):
        return value.strip().lower() == "on"
    if isinstance(value, bool):
        return value
    raise ListError(f"{what} must be on or off")


def check_plan(lists_plan):
    """The `[lists]` settings with the spec's defaults filled in, or `ListError`: an unknown key, a wrong type, a value out of range and an address that is not a plain http or https one are refused."""
    if not isinstance(lists_plan, dict):
        raise ListError("the lists plan must be a dict")
    unknown = sorted(str(k) for k in lists_plan if k not in DEFAULTS)
    if unknown:
        raise ListError(f"unknown settings in the lists plan: {textutil.clean(', '.join(unknown), 200)}")
    cfg = {**DEFAULTS, **lists_plan}
    cfg["phishing_domains"] = _flag(cfg["phishing_domains"], "phishing_domains")
    cfg["urlhaus_recent"] = _flag(cfg["urlhaus_recent"], "urlhaus_recent")
    cfg["refresh_hours"] = _number(cfg["refresh_hours"], "refresh_hours", 1, 24 * 365)
    cfg["list_max_mb"] = _number(cfg["list_max_mb"], "list_max_mb", 0.001, 250)   # under what MAX_STORED_BYTES can read back
    cfg["list_min_share"] = _number(cfg["list_min_share"], "list_min_share", 0, 1)
    cfg["list_max_change"] = _number(cfg["list_max_change"], "list_max_change", 0, 1)
    cfg["urlhaus_keep_days"] = _number(cfg["urlhaus_keep_days"], "urlhaus_keep_days", 1, 3650)
    if cfg["phishing_domains_format"] not in FORMATS:
        raise ListError("phishing_domains_format is not one this version reads")
    for key in ("phishing_domains_url", "public_suffix_url"):
        try:
            if not isinstance(cfg[key], str) or not cfg[key]:
                raise webaddr.AddressError("not an address")
            canonical = webaddr.canon_address(cfg[key])
            if not canonical.startswith("https://"):
                raise webaddr.AddressError("not https")
            cfg[key] = canonical    # the downloader is given the form that was checked
        except webaddr.AddressError:
            raise ListError(f"{key} is not a plain https address") from None
    cfg["pinned_hosts"] = _pinned(cfg["pinned_hosts"])
    return cfg


def _iso(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_iso(text):
    return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def ensure_private_dir(path):
    """A folder that is a plain folder of ours (not a link, not someone else's), made with mode 700 if missing and tightened to 700 if it is looser; `ListError` otherwise."""
    try:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            os.mkdir(path, 0o700)
            info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ListError("the lists folder is not a plain folder")
        if info.st_uid != os.getuid():
            raise ListError("the lists folder is not ours")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchmod(fd, 0o700)
        finally:
            os.close(fd)
    except OSError as e:
        raise ListError(f"the lists folder cannot be made ready ({e.strerror})") from None


class Matcher:
    """See the module's text. `Matcher(owner_blacklist_path, allow_path, lists_dir, pinned_hosts)`; the stored copies are read at once."""

    def __init__(self, owner_blacklist_path, allow_path, lists_dir, pinned_hosts):
        self._black, self._allow, self._dir = owner_blacklist_path, allow_path, lists_dir
        self._lock = threading.RLock()
        self._meta = {}
        self.problems = []
        self._s = State(frozenset(), frozenset(), _pinned(pinned_hosts), {}, {}, frozenset())
        self.reload()

    # --- reading ---

    def reload(self):
        """Read the owner's blacklist and the allow file again, and the stored copies of the lists. If a file is bad the error is raised and what was in use stays."""
        with self._lock:
            owner = _owner_hosts(self._black, "the owner's blacklist")
            allow = _owner_hosts(self._allow, "the allow file")
            public, suffixes, meta, problems = self._load_stored()
            self._meta = meta
            self.problems = problems
            self._s = self._s._replace(owner=owner, allow=allow, public=public, suffixes=suffixes)

    def _load_stored(self):
        public, suffixes, meta, problems = {}, frozenset(), {}, []
        if not self._dir_ok():
            problems.append("the lists folder is not a plain folder of ours: no stored copy is read, and the copies in use stay")
            for name, _key, _url, _required in LISTS:
                suffixes = self._keep(name, public, meta, suffixes)
            return public, suffixes, meta, problems
        for name, _key, _url, _required in LISTS:
            try:
                found = self._read_copy(name)
                if found is None:
                    if name in self._meta:
                        problems.append(f"{name}: the stored files are missing; the copy in use stays")
                    suffixes = self._keep(name, public, meta, suffixes)
                    continue
                info, data = found
                if name == "public_suffix":
                    entries = webaddr.parse_suffixes(data)
                else:
                    entries = frozenset(parse_domains(data.decode("utf-8", "replace"))[0])
                if not entries:
                    raise ListError("it has no valid entry")
                if len(entries) < MIN_ENTRIES[name]:
                    raise ListError(f"it has fewer than {MIN_ENTRIES[name]} entries")
            except (ListError, webaddr.AddressError) as e:
                problems.append(f"{name}: the stored copy is not used ({e})")
                suffixes = self._keep(name, public, meta, suffixes)
                continue
            meta[name] = info
            if name == "public_suffix":
                suffixes = entries
            else:
                public[name] = entries
        return public, suffixes, meta, problems

    def _dir_ok(self):
        """Whether the lists folder, if there is one, is a plain folder of ours (the stored copies are not read from anything else)."""
        try:
            info = os.lstat(self._dir)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid()

    def _keep(self, name, public, meta, suffixes):
        """A stored copy that is gone or damaged does not switch off the copy that is in use: it stays, and the problem is reported. Returns the suffix rules to use."""
        if name in self._meta:
            meta[name] = self._meta[name]
            if name == "public_suffix":
                return self._s.suffixes
            if name in self._s.public:
                public[name] = self._s.public[name]
        return suffixes

    def _read_copy(self, name):
        raw = _open_regular(os.path.join(self._dir, f"{name}.meta.json"), MAX_META_BYTES, "the list's record")
        if raw is None:
            return None
        try:
            info = json.loads(raw.decode("utf-8"))
            if not isinstance(info, dict) or not isinstance(info.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"]):
                raise ValueError
            _from_iso(info["checked"])
            if not isinstance(info.get("file"), str) or info["file"] != self._data_name(name, info["sha256"]):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError, UnicodeDecodeError):
            raise ListError("its record cannot be read") from None
        data = _open_regular(os.path.join(self._dir, info["file"]), MAX_STORED_BYTES, "the stored list")
        if data is None:
            raise ListError("its data file is missing")
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise ListError("its data does not match its recorded hash")
        return info, data

    @staticmethod
    def _data_name(name, sha256):
        return f"{name}.{sha256[:16]}.{EXTENSIONS[name]}"

    def suffixes(self):
        """The rules of the stored Public Suffix List, for `webaddr.site_of` (empty if there is no copy)."""
        return self._s.suffixes

    # --- matching ---

    @staticmethod
    def _target(text):
        """`(host, url_or_None)` for an address or a host, or None."""
        if not isinstance(text, str):
            return None
        try:
            if "://" in text:
                url = webaddr.canon_address(text)
                return _fold(urlsplit(url).hostname), url
            try:
                return _fold(webaddr.canon_host(text)), None
            except webaddr.AddressError:
                if _SCHEME_LIKE.match(text):
                    return None     # `http:/evil.example` is not a host `http`
                url = webaddr.canon_address("http://" + text)
                return _fold(urlsplit(url).hostname), url
        except webaddr.AddressError:
            return None

    @staticmethod
    def _chain(host):
        """The host and every host above it (`a.b.c` gives `a.b.c`, `b.c`, `c`); an address is only itself."""
        if _is_ip(host):
            return [host]
        labels = host.split(".")
        return [".".join(labels[i:]) for i in range(len(labels))]

    def blocked(self, address_or_host):
        """`None` if the address or host may be requested, else a `Block` whose reason is `owner`, `list:<name>`, or `unusable`."""
        target = self._target(address_or_host)
        if target is None:
            return Block("unusable")
        host, url = target
        s = self._s
        chain = self._chain(host)
        if any(h in s.owner for h in chain):
            return Block("owner")
        if any(h in s.pinned for h in chain):
            return None
        if host in s.allow:
            return None
        for name, hosts in s.public.items():
            if host in hosts:
                return Block(f"list:{name}")
        for name, (urls, bare) in s.urls.items():
            if (url is not None and url in urls) or host in bare:
                return Block(f"list:{name}")
        return None

    def set_urls(self, name, urls):
        """Put a public URL list in use under `name` (its entries are made canonical; what is not an address is dropped). Returns the number of entries."""
        text = "\n".join(u for u in urls if isinstance(u, str) and "\n" not in u)
        found, bare, _ignored = parse_urls(text)
        with self._lock:
            self._s = self._s._replace(urls={**self._s.urls, name: (frozenset(found), frozenset(bare))})
        return len(found)

    # --- downloading ---

    def update(self, get, now, lists_plan):
        """Download the lists the plan names that are due, and use what is accepted. Returns `{"lists": {name: {"status": ..., "reason": ..., ...}}, "stop": bool, "stop_reason": text or None}`.
        Statuses: `updated`, `unchanged` (a 304), `not-due`, `failed` (nothing usable came; the last copy stays), `refused` (a list that came and was not accepted; the last copy stays), `off` and `skipped`."""
        cfg = check_plan(lists_plan)
        if not isinstance(now, datetime.datetime) or now.tzinfo is None:
            raise ListError("the time must be a datetime with a time zone")
        with self._lock:
            if "pinned_hosts" in lists_plan:
                self._s = self._s._replace(pinned=cfg["pinned_hosts"])
            self._ensure_dir()
            report = {"lists": {}, "stop": False, "stop_reason": None}
            for name, key, url_key, required in LISTS:
                if key is not None and not cfg[key]:
                    report["lists"][name] = {"status": "off"}
                    continue
                result = self._refresh(name, cfg[url_key], cfg, get, now)
                report["lists"][name] = result
                if required and name not in self._meta:
                    report["stop"] = True
                    report["stop_reason"] = f"the required list {name} has no usable copy ({result.get('reason') or result['status']})"
            report["lists"]["urlhaus_recent"] = {"status": "skipped", "reason": "not handled by this module"} if cfg["urlhaus_recent"] else {"status": "off"}
            return report

    def _ensure_dir(self):
        ensure_private_dir(self._dir)

    @staticmethod
    def _plain(value):
        """A validator (ETag, Last-Modified) that is safe to send back: printable ASCII, one line, not long."""
        return value if isinstance(value, str) and value and len(value) <= 300 and all(32 <= ord(c) < 127 for c in value) else None

    def _refresh(self, name, url, cfg, get, now):
        meta = self._meta.get(name)
        if meta is not None and datetime.timedelta(0) <= now - _from_iso(meta["checked"]) < datetime.timedelta(hours=cfg["refresh_hours"]):
            return {"status": "not-due"}
        headers = {}
        damaged = False
        if meta is not None:
            try:
                self._read_copy(name)
            except ListError:
                damaged = True    # the files on disk do not agree with the record: ask for the whole list, and believe no 304
        if meta is not None and not damaged:
            if self._plain(meta.get("etag")):
                headers["If-None-Match"] = meta["etag"]
            if self._plain(meta.get("last_modified")):
                headers["If-Modified-Since"] = meta["last_modified"]
        limit = int(cfg["list_max_mb"] * 1024 * 1024)
        try:
            status, reply, body = get(url, headers, limit)
        except Exception as e:   # a refusal, a failed connection, a timeout, anything the downloader raises
            return {"status": "failed", "reason": textutil.clean(str(e) or type(e).__name__, 300)}
        if not isinstance(status, int) or isinstance(status, bool):
            return {"status": "failed", "reason": "the downloader gave no status"}
        if status == 304:
            if meta is None:
                return {"status": "failed", "reason": "the server said not modified, but there is no copy"}
            if damaged:
                return {"status": "failed", "reason": "the server said not modified, but the stored copy is damaged, so it is not believed"}
            if not headers:
                return {"status": "failed", "reason": "the server said not modified, but no validator was sent, so it is not believed"}
            try:
                self._install(name, {**meta, "checked": _iso(now)})
            except OSError as e:
                return {"status": "failed", "reason": f"the record could not be written ({e.strerror})"}
            self._meta[name] = {**meta, "checked": _iso(now)}
            return {"status": "unchanged"}
        if status != 200:
            return {"status": "failed", "reason": f"HTTP {status}"}
        if not isinstance(body, (bytes, bytearray)):
            return {"status": "failed", "reason": "the download is not bytes"}
        body = bytes(body)
        if len(body) > limit:
            return {"status": "refused", "reason": f"over the size limit ({cfg['list_max_mb']} MB)"}
        try:
            return self._accept(name, body, reply if isinstance(reply, dict) else {}, url, cfg, now)
        except OSError as e:
            return {"status": "failed", "reason": f"the copy could not be stored ({e.strerror})"}
        except Exception as e:   # a list that makes the reader raise is a failed list, not a crash of the run
            return {"status": "failed", "reason": textutil.clean(f"the list could not be read ({type(e).__name__})", 300)}

    def _temp(self, label):
        return os.path.join(self._dir, f".{label}.{os.urandom(6).hex()}.new")

    def _accept(self, name, body, reply, url, cfg, now):
        previous = self._s.suffixes if name == "public_suffix" else self._s.public.get(name)
        if name == "public_suffix":
            try:
                entries = webaddr.parse_suffixes(body)
            except webaddr.AddressError as e:
                return {"status": "refused", "reason": textutil.clean(str(e), 200)}
            ignored = 0
        else:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                return {"status": "refused", "reason": "the list is not UTF-8 text"}
            try:
                entries, ignored = parse_domains(text)
            except ListError as e:
                return {"status": "refused", "reason": str(e)}
            entries = frozenset(entries)
        if not entries:
            return {"status": "refused", "reason": "the list has no valid entry"}
        if ignored > len(entries):
            return {"status": "refused", "reason": f"most lines are not hostnames ({ignored} of {ignored + len(entries)})"}
        if len(entries) < MIN_ENTRIES[name]:
            return {"status": "refused", "reason": f"the list has fewer than {MIN_ENTRIES[name]} entries ({len(entries)})"}
        if previous:
            if len(entries) < cfg["list_min_share"] * len(previous):
                return {"status": "refused", "reason": f"the list is smaller than {cfg['list_min_share']:.0%} of the last copy ({len(entries)} against {len(previous)} entries)"}
            changed = len(entries ^ previous) / len(previous)
            if changed > cfg["list_max_change"]:
                return {"status": "refused", "reason": f"the list changed by {changed:.0%} of the last copy in one refresh (more than {cfg['list_max_change']:.0%})"}
        meta = {"source": url, "retrieved": _iso(now), "checked": _iso(now), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "entries": len(entries),
                "etag": self._plain(self._header(reply, "etag")), "last_modified": self._plain(self._header(reply, "last-modified"))}
        meta["file"] = self._data_name(name, meta["sha256"])
        tmp_data = self._temp(f"{name}.data")
        try:
            self._write_file(tmp_data, body)
            self._install(name, meta, tmp_data)
        except OSError:
            self._remove(tmp_data)
            raise
        self._sweep(name, meta["file"])
        self._meta[name] = meta
        if name == "public_suffix":
            self._s = self._s._replace(suffixes=entries)
        else:
            self._s = self._s._replace(public={**self._s.public, name: entries})
        return {"status": "updated", "entries": len(entries), "ignored": ignored, "sha256": meta["sha256"]}

    def _sweep(self, name, keep):
        """Remove the data files of this list that no record names (the old copy, and any left by a stop between the two renames), keeping the one the record **on disk** names now (another process may have
        installed a newer copy), and this list's temporary files that are old enough to belong to a writer that is gone. Other files are not touched."""
        keep = {keep}
        try:
            raw = _open_regular(os.path.join(self._dir, f"{name}.meta.json"), MAX_META_BYTES, "the list's record")
            named = json.loads(raw.decode("utf-8")).get("file") if raw is not None else None
            if isinstance(named, str):
                keep.add(named)
        except (ListError, ValueError, AttributeError, RecursionError, UnicodeDecodeError):
            pass
        data = re.compile(rf"{re.escape(name)}\.[0-9a-f]{{16}}\.{EXTENSIONS[name]}")
        temp = re.compile(rf"\.{re.escape(name)}\.(?:data|meta\.json)\.[0-9a-f]{{12}}\.new")
        try:
            names = os.listdir(self._dir)
        except OSError:
            return
        for entry in names:
            path = os.path.join(self._dir, entry)
            if data.fullmatch(entry) and entry not in keep:
                self._remove(path)
            elif temp.fullmatch(entry):
                try:
                    if time.time() - os.lstat(path).st_mtime > STALE_TEMP_SECONDS:
                        self._remove(path)
                except OSError:
                    pass

    @staticmethod
    def _header(reply, key):
        value = next((v for k, v in reply.items() if str(k).lower() == key), None)
        return value if isinstance(value, str) and value and all(32 <= ord(c) < 127 for c in value) and len(value) <= 300 else None

    # --- files ---

    def _write_file(self, path, data):
        self._remove(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _remove(path):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def _install(self, name, meta, new_data=None):
        """Put a new data file in place under its own hash-bearing name, and then, last, the record that names it, each through a temporary file and a rename. A stop in between leaves the old record and
        the old data, which still agree; the new data file, if it was put in place, is removed."""
        tmp_meta = self._temp(f"{name}.meta.json")
        final_data = os.path.join(self._dir, meta["file"])
        placed = False
        try:
            self._write_file(tmp_meta, json.dumps(meta, sort_keys=True).encode("utf-8"))
            if new_data is not None:
                os.replace(new_data, final_data)
                placed = True
            os.replace(tmp_meta, os.path.join(self._dir, f"{name}.meta.json"))
        except OSError:
            self._remove(tmp_meta)
            if placed and (self._meta.get(name) or {}).get("file") != meta["file"]:
                self._remove(final_data)
            raise
