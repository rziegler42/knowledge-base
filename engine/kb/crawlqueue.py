"""The candidate queue of the unattended crawl: `candidates.sqlite` in the index root (`docs/specs/population.md`, "The queue and the
seen list"). Discovery and the runner meet only here.

Discovery puts rows in: `queued` ones, `blocked` ones for an address on a list, and `rejected` ones with the reason `type`. The
runner changes the status of every other row. So nothing in this module removes a row or changes an existing one: a row, once
written, is the seen list. A test reads this file's text to keep it so.

The address functions (`canon_address`, `site_of`) belong to `kb/webaddr.py`, which another plan builds. Each function here takes
them as arguments and imports `webaddr` only when it is called without them."""

import ipaddress
import os
import re
import sqlite3
import stat
import time
import unicodedata
from contextlib import closing
from urllib.parse import urlsplit

from . import KbError

FILE = "candidates.sqlite"
FORMAT = 1
MAX_ADDRESS = 2048  # an address longer than this is dropped (the spec)
MAX_TEXT = 1000  # a text field (a query, a topic, a work id) longer than this is a fault of the caller
MAX_WEIGHT = 1_000_000  # a topic's weight (a whole number)
MAX_DEPTH = 1000  # wandering stops at 2; this only keeps a caller's number inside SQLite's integers
SOURCES = ("openalex", "arxiv", "wikipedia", "web-search")
STATUSES = ("queued", "fetching", "kept", "rejected", "failed", "blocked")

# The spec's table, written as the spec writes it, with the comments left out. `connect` makes it and `_shape_ok` compares it.
_SCHEMA = (
    """CREATE TABLE candidates(
  id INTEGER PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL, address TEXT NOT NULL,
  source TEXT NOT NULL,
  source_id TEXT,
  found_from TEXT,
  topic TEXT, weight INTEGER,
  depth INTEGER NOT NULL DEFAULT 0, domain TEXT, ip TEXT,
  status TEXT NOT NULL,
  reason TEXT, score REAL, book_id TEXT,
  tries INTEGER NOT NULL DEFAULT 0, run_id TEXT,
  added TEXT NOT NULL, updated TEXT NOT NULL, next_try TEXT)""",
    "CREATE TABLE counters(day TEXT, key TEXT, n INTEGER, PRIMARY KEY(day, key))",
)
_COLUMNS = {
    "candidates": [  # (name, type, notnull, default, primary key), as PRAGMA table_info gives them
        ("id", "INTEGER", 0, None, 1), ("identity_key", "TEXT", 1, None, 0), ("address", "TEXT", 1, None, 0),
        ("source", "TEXT", 1, None, 0), ("source_id", "TEXT", 0, None, 0), ("found_from", "TEXT", 0, None, 0),
        ("topic", "TEXT", 0, None, 0), ("weight", "INTEGER", 0, None, 0), ("depth", "INTEGER", 1, "0", 0),
        ("domain", "TEXT", 0, None, 0), ("ip", "TEXT", 0, None, 0), ("status", "TEXT", 1, None, 0),
        ("reason", "TEXT", 0, None, 0), ("score", "REAL", 0, None, 0), ("book_id", "TEXT", 0, None, 0),
        ("tries", "INTEGER", 1, "0", 0), ("run_id", "TEXT", 0, None, 0), ("added", "TEXT", 1, None, 0),
        ("updated", "TEXT", 1, None, 0), ("next_try", "TEXT", 0, None, 0)],
    "counters": [("day", "TEXT", 0, None, 1), ("key", "TEXT", 0, None, 2), ("n", "INTEGER", 0, None, 0)],
}
# What a caller may give for a candidate. Everything else (the status, the reason, the domain, the dates, the tries) is set here
# or by the runner.
_REQUIRED = ("address", "source")
_OPTIONAL = ("identity_key", "source_id", "found_from", "topic", "weight", "depth", "ip")
_TEXTS = ("source_id", "found_from", "topic", "ip")
_NOW = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_LIST_REASON = re.compile(r"list:[a-z0-9][a-z0-9_.-]{0,39}")


def _refuse(message):
    return KbError(f"the candidate queue: {message}")


def connect(folder):
    """The queue in `folder` (the index root), checked and ready to write. It is made, with mode 600 and the spec's table, by the
    first of discovery and the runner to open it; a file that is a link or not a plain file, that others can read, that is not
    this engine's table exactly, or that has another version, is a refusal. WAL mode, a busy timeout of 30 seconds, and SQLite's
    own locking: no other lock. A lock that is not given up in 30 seconds, or a transaction the caller left open, is the
    `sqlite3.OperationalError` of SQLite, not a refusal of ours."""
    if not isinstance(folder, (str, os.PathLike)) or not os.path.isdir(folder):
        raise _refuse(f"the folder does not exist: {os.fspath(folder)!r}" if isinstance(folder, (str, os.PathLike)) else
                      "the folder is not a path")
    path = os.path.join(os.fspath(folder), FILE)
    try:
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600))
        except FileExistsError:
            pass
        _check_file(path)
    except OSError as e:
        raise _refuse(f"the file cannot be made or read ({e.strerror}): {path}") from None
    try:
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    except sqlite3.Error as e:
        raise _refuse(f"the file cannot be opened ({e}): {path}") from None
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            empty = conn.execute("PRAGMA user_version").fetchone()[0] == 0 and not conn.execute(
                "SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            if empty:  # the first to open it makes it, and the others, waiting for the lock, find it made
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {FORMAT}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        _check_shape(conn, path)
        _wal(conn)
    except sqlite3.Error as e:
        conn.close()
        raise _refuse(f"the file is not a candidate queue of this engine ({e}): {path}") from None
    except BaseException:
        conn.close()
        raise
    return conn


def _check_file(path):
    info = os.lstat(path)  # a link is not followed: it is not a plain file
    if not stat.S_ISREG(info.st_mode):
        raise _refuse(f"the path is not a plain file (a link, a pipe or a folder is refused): {path}")
    if info.st_uid != os.getuid():
        raise _refuse(f"the file is not the owner's: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise _refuse(f"the file can be read by others (mode {stat.S_IMODE(info.st_mode):o}); it must be 600: {path}")


def _wal(conn):
    for attempt in range(50):  # changing the mode needs a moment with no other writer, and does not always wait for one
        try:
            if conn.execute("PRAGMA journal_mode = WAL").fetchone()[0].lower() == "wal":
                return
        except sqlite3.OperationalError as e:
            if "lock" not in str(e).lower() and "busy" not in str(e).lower():
                raise
        time.sleep(0.05)
    raise _refuse("the file cannot be put in WAL mode")


def _check_shape(conn, path):
    wrong = _refuse(f"the file is not the table of this engine's queue; it is not changed: {path}")
    if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
        raise _refuse(f"the file has another version than {FORMAT}; it is not changed: {path}")
    master = conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    if {n for t, n, _ in master if t == "table"} != set(_COLUMNS) or any(
            t not in ("table", "index") or (t == "index" and not n.startswith("sqlite_autoindex_")) for t, n, _ in master):
        raise wrong
    # The text of each table is the spec's, apart from white space: this holds what table_info cannot show (a CHECK, STRICT,
    # WITHOUT ROWID or a generated column).
    if {n: " ".join(s.split()) for t, n, s in master if t == "table"} != {
            n: " ".join(s.split()) for n, s in zip(("candidates", "counters"), _SCHEMA)}:
        raise wrong
    for table, expected in _COLUMNS.items():
        if [(r[1], r[2], r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({table})")] != expected:
            raise wrong
    unique = [[c[2] for c in conn.execute(f"PRAGMA index_info({i[1]})")]
              for i in conn.execute("PRAGMA index_list(candidates)") if i[2]]
    if unique != [["identity_key"]]:
        raise wrong


def _clean(text):
    return not any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in text)


def _now(now):
    if not isinstance(now, str) or not _NOW.fullmatch(now):
        raise _refuse("the time must be a UTC time like 2026-11-16T10:00:00Z")
    return now


def _number(name, value, low, high=2**31 - 1):
    if type(value) is not int or not low <= value <= high:
        raise _refuse(f"{name} must be a whole number from {low} to {high}")
    return value


def _check(candidate):
    """The candidate as the caller gave it, or a refusal: a fault of the caller is an exception, a fact about the address is a
    result of `enqueue`."""
    if not isinstance(candidate, dict):
        raise _refuse("a candidate is a plain dictionary")
    extra = set(candidate) - set(_REQUIRED) - set(_OPTIONAL)
    if extra:
        raise _refuse(f"unknown keys of a candidate (the queue sets the rest itself): {sorted(map(str, extra))}")
    for key in _REQUIRED:
        if key not in candidate:
            raise _refuse(f"a candidate needs {key}")
    for key in ("address", "identity_key") + _TEXTS:
        value = candidate.get(key)
        if value is None and key != "address":
            continue
        if not isinstance(value, str) or not value or not _clean(value):
            raise _refuse(f"{key} must be a text with no control or invisible characters")
        if key in _TEXTS and len(value) > MAX_TEXT:
            raise _refuse(f"{key} is over {MAX_TEXT} characters")
    if candidate["source"] not in SOURCES:
        raise _refuse(f"source must be one of {', '.join(SOURCES)}")
    if candidate.get("weight") is not None:
        _number("weight", candidate["weight"], 1, MAX_WEIGHT)
    _number("depth", candidate.get("depth", 0), 0, MAX_DEPTH)
    if candidate.get("ip") is not None:
        try:
            ipaddress.ip_address(candidate["ip"])
        except ValueError:
            raise _refuse("ip is not an IP address") from None
    return candidate


def _limits(limits):
    if not isinstance(limits, dict) or set(limits) != {"queued_total", "queued_per_domain"}:
        raise _refuse("limits are queued_total and queued_per_domain")
    return _number("queued_total", limits["queued_total"], 0), _number("queued_per_domain", limits["queued_per_domain"], 0)


def _webaddr():
    try:
        from . import webaddr
    except ImportError:
        raise _refuse("kb/webaddr.py is not built yet: give canon_address and site_of") from None
    return webaddr.canon_address, webaddr.site_of


def _insert(conn, candidate, status, reason, caps, canon_address, site_of, now):
    _check(candidate)
    _now(now)
    if canon_address is None or site_of is None:
        default_canon, default_site = _webaddr()
        canon_address, site_of = canon_address or default_canon, site_of or default_site
    if len(candidate["address"]) > MAX_ADDRESS or len(candidate.get("identity_key") or "") > MAX_ADDRESS:
        return "too_long"  # before anything works on it
    try:
        address = canon_address(candidate["address"])
        if not isinstance(address, str) or not _clean(address):  # what the canonicaliser gives back is data as well
            return "refused"
        host = urlsplit(address).hostname
        domain = site_of(host) if host else None
    except (KbError, ValueError):
        return "refused"
    if not isinstance(domain, str) or not domain:
        return "refused"
    if len(address) > MAX_ADDRESS:
        return "too_long"
    key = candidate.get("identity_key") or address
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM candidates WHERE identity_key = ?", (key,)).fetchone():
            result = "duplicate"
        elif caps and conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'queued'").fetchone()[0] >= caps[0]:
            result = "capped"
        elif caps and conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'queued' AND domain = ?",
                                   (domain,)).fetchone()[0] >= caps[1]:
            result = "capped"
        else:
            made = conn.execute(  # `OR IGNORE` on the unique identity key, as the spec says; the check above makes it the exception
                "INSERT OR IGNORE INTO candidates (identity_key, address, source, source_id, found_from, topic, weight, depth,"
                " domain, ip, status, reason, added, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, address, candidate["source"], candidate.get("source_id"), candidate.get("found_from"), candidate.get("topic"),
                 candidate.get("weight"), candidate.get("depth", 0), domain, candidate.get("ip"), status, reason, now, now))
            result = status if made.rowcount == 1 else "duplicate"
        conn.execute("COMMIT")
        return result
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def enqueue(conn, candidate, *, canon_address=None, site_of=None, limits, now):
    """Add one candidate as `queued`. `candidate` is a plain dictionary: `address` and `source` are required; `identity_key` (the
    canonical address when it is left out, `arxiv:<id>` for a paper), `source_id`, `found_from`, `topic`, `weight`, `depth` and `ip`
    are not. The answer says what happened and nothing is raised for a fact about the address: `queued`; `duplicate` (the identity
    key is held, in any status, and nothing changes); `too_long` (over 2,048 characters, tested before the address is worked on);
    `refused` (the address is not one the canonicaliser takes); `capped` (the queue is at `queued_total`, or the registrable
    domain is at `queued_per_domain`; only rows with status `queued` count). A candidate that is not a plain dictionary of the keys
    above, or holds a bad value, is a fault of the caller and a `KbError`."""
    return _insert(conn, candidate, "queued", None, _limits(limits), canon_address, site_of, now)


def insert_blocked(conn, candidate, reason, *, canon_address=None, site_of=None, now):
    """Record an address that the blacklist or a public list blocks, as `blocked`, so that it is never queued and the report can
    count it. `reason` is `owner` or `list:<name>`. The same rules as `enqueue` for a duplicate and a length; no cap, since a
    blocked row is not work."""
    if not isinstance(reason, str) or not (reason == "owner" or _LIST_REASON.fullmatch(reason)):
        raise _refuse("the reason of a blocked address is owner or list:<name>")
    return _insert(conn, candidate, "blocked", reason, None, canon_address, site_of, now)


def insert_rejected(conn, candidate, reason, *, canon_address=None, site_of=None, now):
    """Record a work whose only full text is a type the first version does not take, as `rejected` with the reason `type`, so that
    the report counts what was missed. Discovery gives no other reason; the runner does the rest."""
    if reason != "type":
        raise _refuse("discovery rejects a candidate for its type only")
    return _insert(conn, candidate, "rejected", reason, None, canon_address, site_of, now)


def kept_sources(conn, source, max_depth):
    """`(source_id, depth)` of the rows of `source` that are `kept` and have a `source_id`, in the order they were added, that are
    shallower than `max_depth`: those a wander may still start from."""
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT source_id, depth FROM candidates WHERE status = 'kept' AND source = ? AND source_id IS NOT NULL AND depth < ? "
        "ORDER BY id", (source, max_depth))]


def counts(conn):
    """The number of rows of each status, every status present."""
    made = dict.fromkeys(STATUSES, 0)
    for status, n in conn.execute("SELECT status, COUNT(*) FROM candidates GROUP BY status"):
        made[status] = n
    return made
