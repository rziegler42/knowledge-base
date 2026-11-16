"""The reading side of `crawl-status` and `crawl-report` (`docs/specs/population.md`, "Status and the report"; the plan
`2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl`).

**Nothing in this module writes, creates, locks, deletes or sends.** It opens files for reading only, never follows a link, never waits on a
pipe, and reads at most a fixed size. Every function that reads a file of the crawl takes a path and gives data back; a fault of one file is a
result that says so, never a crash of the whole command.

**What is read is untrusted.** The log is written by a process that reads pages from the web; its `reason`, `host` and `candidate` can hold
text from them. This module therefore (1) takes only the fields of the spec from a log line and drops every other field, so that a field that
should never be there cannot reach an output; (2) type-checks each field and counts a line that fails as bad instead of guessing; and (3) gives
`clean`, the one way a text is made ready to print or write: **normalise** (the cleaning of `place-review`, which removes control, format, line,
invisible and bidirectional characters, so the text is what a reader would see and no hidden character can split a name), **redact**, then **cut**
to the field's length, last, so that a cut can never leave part of a key that the rule would have withheld.

`redact` is a safeguard against an accident and **not a guarantee**: it withholds a text that holds a header name (`Auth-Key`, `Authorization`,
`Cookie` and the like) or a bearer token, and hides a user, a password and the value of a parameter named like a key in an address. It cannot know
a key by its look: a bare key with no name around it is printed as text. The spec's rule that the log, the queue and the report never contain a
key stays the runner's first line."""

import datetime
import errno
import fcntl
import json
import math
import os
import re
import stat
import zoneinfo
from collections import namedtuple
from pathlib import Path
from urllib.parse import unquote

from . import KbError, placereview

MAX_SMALL = 64 * 1024             # the default size of a small file (a record, a breaker file, a lock's line)
MAX_LOG_BYTES = 32 * 1024 * 1024  # the most of one day's log that is read
MAX_LINE = 16 * 1024              # a log line over this is bad: the runner's writer cuts a line over 8 KiB itself
MAX_FIELD = 4096                  # a text field of a log line (an address may be 2,048 characters)
NORMALISE = 2000                  # the bound at which a text is normalised, and the most `clean` can give
_SLICE = NORMALISE * 4 + 100      # `placereview.safe` takes this much of a text before it cleans it
WITHHELD = "[withheld: looks like a header or a key]"
PARAM_WITHHELD = "[withheld]"

# The steps and outcomes of the spec's log, in its order (a test reads the spec's own text and compares).
STEPS = ("run_start", "refuse", "list_update", "discover", "enqueue", "block", "fetch", "capture", "scan", "hold", "convert", "index", "judge",
         "reject", "card", "propose", "move", "fail", "breaker", "stop", "run_end", "report")
OUTCOMES = ("ok", "skipped", "rejected", "failed", "blocked", "held", "refused", "tripped")
FIELDS = ("ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds")
BREAKER_KINDS = ("consecutive_failures", "failure_share", "model_down", "stage_bound")  # the runner plan's contract for `crawl/breaker.json`
MAX_LOCK_LINE = 256               # the most of the lock's line that is read
MAX_RUN_FILES = 60                # the most log files `last_run` looks through for a run (it stops at the newest file that has one)
MAX_RUN_BYTES = 128 * 1024 * 1024  # and the most bytes it reads in all
GIB = 1024 ** 3                   # a floor of the plan is in gigabytes; read here as 2**30 bytes (to be checked against the runner's guard)
# the values of the approved plan that the status uses, and no others
PLAN_VALUES = ("fetches_per_day", "per_domain_per_day", "cards_per_day", "filed_total", "timezone", "bulk_floor_gb", "index_floor_gb",
               "domain_refusals", "phishing_domains", "urlhaus_recent")

_TEXT_FIELDS = ("candidate", "book", "host", "reason")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_LOG_NAME = re.compile(r"crawl-([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl")
_DIGEST = re.compile(r"[0-9a-f]{32}\n?")
_LOCK_LINE = re.compile(r"([0-9]{1,10}) ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)\n?")
_ZONE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-/]{0,63}")
_HEADER = re.compile(r"(?<![A-Za-z0-9])(?:auth-key|authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token)[\"']?\s*[:=]", re.I)
_BEARER = re.compile(r"(?<![A-Za-z0-9])bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
_SCHEME = r"[A-Za-z][A-Za-z0-9+.\-]*://"
_URL = re.compile(_SCHEME + r"\S+")
_USERINFO = re.compile(r"^(" + _SCHEME + r")[^/?#]*@")
_TAIL_BEARER = re.compile(r"(?<![A-Za-z0-9])bearer\s+\S{0,7}$", re.I)
_TAIL_URL = re.compile(_SCHEME + r"\S*$")
_PARAM = re.compile(r"([?&;#])([^=&;#\s]*)=([^&;#\s]*)")
_SECRET_PARAMS = frozenset(("key", "apikey", "api_key", "token", "access_token", "auth", "secret", "password", "passwd", "sig", "signature"))

FileRead = namedtuple("FileRead", "data status reason cut")  # status: ok | missing | bad


def _me():
    return os.getuid()


def _refuse(message):
    return KbError(f"crawl status: {message}")


def _why(e):
    return e.strerror or type(e).__name__


# --- reading a file safely -----------------------------------------------------------------------------------------------------------------

def read_file(path, limit, *, tail=False):
    """The bytes of a plain file of the owner's, at most `limit` of them: the first ones, or with `tail` the last ones. The file is opened
    without following a link and without waiting on a pipe, and what is read is read through that one open file. `cut` says the file was
    longer than `limit`. A file that is not there is `missing`; a link, a pipe, a folder, a file of another owner or one that cannot be read is
    `bad` with a short reason that holds no path."""
    if type(limit) is not int or limit < 1:
        raise _refuse("a read limit is a whole number of at least 1")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return FileRead(None, "missing", None, False)
    except OSError as e:
        return FileRead(None, "bad", _why(e), False)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return FileRead(None, "bad", "it is not a plain file", False)
        if info.st_uid != _me():
            return FileRead(None, "bad", "it is not the owner's file", False)
        size = info.st_size
        cut = size > limit
        start = size - limit if cut and tail else 0
        want = min(size, limit)
        chunks, got = [], 0
        while got < want:
            chunk = os.pread(fd, min(want - got, 1 << 20), start + got)
            if not chunk:
                break
            chunks.append(chunk)
            got += len(chunk)
        return FileRead(b"".join(chunks), "ok", None, cut)
    except OSError as e:
        return FileRead(None, "bad", _why(e), False)
    finally:
        os.close(fd)


def read_small(path, limit=MAX_SMALL):
    """A small file whole: one that is over `limit` is `bad` and nothing of it is returned."""
    result = read_file(path, limit)
    if result.cut:
        return FileRead(None, "bad", f"it is over {limit} bytes", False)
    return result


# --- redaction and cleaning ----------------------------------------------------------------------------------------------------------------

def _redact_url(match):
    url = _USERINFO.sub(r"\1", match.group(0))
    cut = min((i for i in (url.find("?"), url.find("#")) if i >= 0), default=-1)
    if cut < 0:
        return url

    def hide(m):
        if unquote(m.group(2)).lower() in _SECRET_PARAMS:
            return f"{m.group(1)}{m.group(2)}={PARAM_WITHHELD}"
        return m.group(0)

    return url[:cut] + _PARAM.sub(hide, url[cut:])


def redact(text):
    """`text` with what looks like a credential taken out. It expects text that is already normalised (see `clean`): a header name split by a
    hidden character is not seen here. A value that holds a header name or a bearer token is withheld whole; in an address the user and the
    password are removed and the value of a parameter named like a key is hidden. Anything else is returned as it is."""
    if _HEADER.search(text) or _BEARER.search(text):
        return WITHHELD
    return _URL.sub(_redact_url, text)


def _drop_split_tail(text):
    """The end of a text that the first step cut, without a credential that the cut may have split: a bearer word with fewer than eight
    characters after it (too short for the rule to see) and an address that runs to the end (its `@` or its parameter may be past the cut)."""
    for pattern in (_TAIL_BEARER, _TAIL_URL):
        found = pattern.search(text)
        if found:
            text = text[:found.start()]
    return text


def clean(value, limit):
    """`value` made ready to print or write, at most `limit` characters (1 to 2,000): normalised, then redacted, then cut, in that order. **When
    the normalising step cut the text (it reached 2,000 characters, or the raw text was longer than the slice `placereview.safe` takes first),
    the last bearer word and the last address of what is left are dropped before the rule looks at it**, because a cut can split a credential
    into a piece that the rule does not recognise."""
    if type(limit) is not int or not 1 <= limit <= NORMALISE:
        raise _refuse(f"a text limit is a whole number from 1 to {NORMALISE}")
    text = "" if value is None else str(value)
    normal = placereview.safe(text, NORMALISE)
    if len(normal) >= NORMALISE or len(text) > _SLICE:
        normal = _drop_split_tail(normal)
    return redact(normal)[:limit].rstrip()


# --- the log ---------------------------------------------------------------------------------------------------------------------------------

class _Duplicate(Exception):
    pass


class _NotFinite(Exception):
    pass


def _pairs(pairs):
    made = {}
    for key, value in pairs:
        if key in made:
            raise _Duplicate
        made[key] = value
    return made


def _constant(_name):
    raise _NotFinite


def _text_ok(value):
    if not isinstance(value, str) or len(value) > MAX_FIELD:
        return False
    try:
        value.encode("utf-8")  # a lone surrogate cannot be written out
    except UnicodeEncodeError:
        return False
    return True


def parse_line(line):
    """`(record, None)` for a good line of the log, or `(None, kind)` for a bad one. The kinds: `blank`, `too_long`, `nul`, `not_utf8`, `not_json`,
    `not_object`, `duplicate_key`, `non_finite`, `missing_field`, `bad_ts`, `bad_step`, `bad_outcome` and `bad_field`. A good record has exactly the ten fields
    of the spec (`ts`, `run`, `step`, `outcome`, `candidate`, `book`, `host`, `reason`, `n`, `seconds`; the last six may be absent or null) and nothing
    else: any other key of the line is dropped. The texts are as the line gave them: print them through `clean`."""
    if not isinstance(line, (bytes, bytearray)):
        raise _refuse("a log line is bytes")
    line = bytes(line)
    if not line.strip():
        return None, "blank"
    if len(line) > MAX_LINE:
        return None, "too_long"
    if b"\x00" in line:
        return None, "nul"
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not_utf8"
    try:
        obj = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except _Duplicate:
        return None, "duplicate_key"
    except _NotFinite:
        return None, "non_finite"
    except (ValueError, RecursionError):
        return None, "not_json"
    if type(obj) is not dict:
        return None, "not_object"
    if any(key not in obj for key in ("ts", "run", "step", "outcome")):
        return None, "missing_field"
    ts = obj["ts"]
    if not isinstance(ts, str) or not _TS.fullmatch(ts):
        return None, "bad_ts"
    try:
        datetime.datetime.strptime(ts, _TS_FORMAT)
    except ValueError:
        return None, "bad_ts"
    if not isinstance(obj["step"], str) or obj["step"] not in STEPS:
        return None, "bad_step"
    if not isinstance(obj["outcome"], str) or obj["outcome"] not in OUTCOMES:
        return None, "bad_outcome"
    if not _text_ok(obj["run"]):
        return None, "bad_field"
    for key in _TEXT_FIELDS:
        value = obj.get(key)
        if value is not None and not _text_ok(value):
            return None, "bad_field"
    n, seconds = obj.get("n"), obj.get("seconds")
    if n is not None and (type(n) is not int or not 0 <= n <= 2**53):
        return None, "bad_field"
    if seconds is not None:
        if type(seconds) not in (int, float):
            return None, "bad_field"
        if isinstance(seconds, float) and not math.isfinite(seconds):
            return None, "non_finite"
        if seconds < 0:
            return None, "bad_field"
    return {key: obj.get(key) for key in FIELDS}, None


def read_log(path, *, limit=MAX_LOG_BYTES, tail=False):
    """One log file, strictly. `{"lines": [good records, in file order], "bad": {kind: count}, "cut": bool, "first": ts, "last": ts, "status":
    "ok"|"missing"|"bad", "reason": text or None}`. A bad line is skipped and counted by its kind; a blank line is skipped and not counted. A file
    over `limit` is read from its start (or, with `tail`, from its end) and the line that the cut splits is dropped, not counted."""
    result = read_file(path, limit, tail=tail)
    out = {"lines": [], "bad": {}, "cut": False, "first": None, "last": None, "status": result.status, "reason": result.reason, "bytes": 0}
    if result.status != "ok":
        return out
    data = result.data
    out["bytes"] = len(data)
    if result.cut:
        out["cut"] = True
        if tail:
            at = data.find(b"\n")
            data = b"" if at < 0 else data[at + 1:]
        else:
            at = data.rfind(b"\n")
            data = b"" if at < 0 else data[:at + 1]
    for part in data.split(b"\n"):
        record, kind = parse_line(part)
        if kind == "blank":
            continue
        if kind:
            out["bad"][kind] = out["bad"].get(kind, 0) + 1
            continue
        out["lines"].append(record)
    if out["lines"]:
        stamps = [r["ts"] for r in out["lines"]]
        out["first"], out["last"] = min(stamps), max(stamps)
    return out


def _folder_state(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "bad"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != _me():  # a link is not a folder to lstat
        return "bad"
    return "ok"


def log_files(index_root, first_date=None, last_date=None, *, newest_first=False):
    """`([(date, path), ...], problem)`: the log files `crawl-YYYY-MM-DD.jsonl` of `<index root>/crawl/log/` that are plain files, from `first_date`
    to `last_date` inclusive (each a `datetime.date`, or None for no bound), oldest first. A folder that is missing is nothing to read and no
    problem; one that is a link, not a folder or not the owner's is a problem and nothing is read from it."""
    for bound in (first_date, last_date):
        if bound is not None and type(bound) is not datetime.date:
            raise _refuse("a date bound is a date")
    crawl = Path(index_root) / "crawl"
    state = _folder_state(crawl)
    if state == "missing":
        return [], None
    if state == "bad":
        return [], "the crawl folder is not a plain folder of the owner's, so no log is read"
    folder = crawl / "log"
    state = _folder_state(folder)
    if state == "missing":
        return [], None
    if state == "bad":
        return [], "the log folder is not a plain folder of the owner's, so no log is read"
    found = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                match = _LOG_NAME.fullmatch(entry.name)
                if not match:
                    continue
                try:
                    day = datetime.date.fromisoformat(match.group(1))
                    plain = entry.is_file(follow_symlinks=False)
                except (ValueError, OSError):
                    continue
                if not plain or (first_date and day < first_date) or (last_date and day > last_date):
                    continue
                found.append((day, folder / entry.name))
    except OSError as e:
        return [], f"the log folder cannot be listed ({_why(e)})"
    found.sort(key=lambda item: item[0], reverse=newest_first)
    return found, None


# --- a day in the plan's zone ----------------------------------------------------------------------------------------------------------------

def day_bounds(day, zone):
    """`(start, end)`, two UTC times, of the day `day` (a `datetime.date`) in `zone` (`local` for the machine's own, or an IANA name): the day is
    `start <= t < end`, and is 23 or 25 hours long on a day the clock changes."""
    if type(day) is not datetime.date:
        raise _refuse("a day is a date")
    utc = datetime.timezone.utc
    midnight = datetime.time.min
    following = day + datetime.timedelta(days=1)
    if zone == "local":
        return (datetime.datetime.combine(day, midnight).astimezone(utc), datetime.datetime.combine(following, midnight).astimezone(utc))
    if not isinstance(zone, str) or not _ZONE.fullmatch(zone):
        raise _refuse("the time zone is local or a name of the zone database")
    try:
        info = zoneinfo.ZoneInfo(zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        raise _refuse("the time zone is not one the system knows") from None
    return (datetime.datetime.combine(day, midnight, tzinfo=info).astimezone(utc),
            datetime.datetime.combine(following, midnight, tzinfo=info).astimezone(utc))


def lines_of_day(index_root, day, zone, *, limit=MAX_LOG_BYTES):
    """The good log lines whose `ts` falls in the day `day` of `zone`, oldest first, from every log file that the day can reach (the files are
    named by UTC day, so a local day can lie in two or three of them) and from no other; the day of a line is its `ts` and never the name of its
    file. `{"day", "lines", "bad", "cut", "dates" (the files read), "unreadable" (files that could not be), "problem", "first", "last"}`."""
    start, end = day_bounds(day, zone)
    files, problem = log_files(index_root, start.date(), (end - datetime.timedelta(seconds=1)).date())
    low, high = start.strftime(_TS_FORMAT), end.strftime(_TS_FORMAT)
    out = {"day": day.isoformat(), "lines": [], "bad": {}, "cut": False, "dates": [], "unreadable": 0, "problem": problem, "first": None, "last": None}
    for date, path in files:
        read = read_log(path, limit=limit)
        if read["status"] != "ok":
            out["unreadable"] += 1
            continue
        out["dates"].append(date)
        out["cut"] = out["cut"] or read["cut"]
        for kind, count in read["bad"].items():
            out["bad"][kind] = out["bad"].get(kind, 0) + count
        out["lines"].extend(r for r in read["lines"] if low <= r["ts"] < high)
    out["lines"].sort(key=lambda r: r["ts"])  # stable: lines with one ts stay in the order they were written
    if out["lines"]:
        out["first"], out["last"] = out["lines"][0]["ts"], out["lines"][-1]["ts"]
    return out


# --- the state: the breaker, the lock, the stop file -------------------------------------------------------------------------------------------

def _str_ok(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _breaker(state, detail=None, fields=None):
    out = {"state": state, "paused": state != "not_tripped", "detail": detail, "reason": None, "kind": None, "at": None, "run": None}
    if fields:
        out.update(reason=clean(fields["reason"], 300), kind=clean(fields["kind"], 40), at=clean(fields["at"], 20), run=clean(fields["run"], 200))
    return out


def breaker_state(index_root):
    """`crawl/breaker.json` read as the runner plan's contract has it: `{"tripped": <bool>, "reason": <text, at most 300 characters>, "kind":
    <one of BREAKER_KINDS or "">, "at": <a UTC time or "">, "run": <text, as long as a log field>}`. **The crawl is paused unless the file says
    `"tripped": false`:** the state is `missing`, `cannot_examine` (it cannot even be looked for), `cannot_read` (not a plain file, over the size,
    not UTF-8, not JSON, not an object, a key missing, a wrong type or form), `tripped`, or `not_tripped` (the one that is not paused). The file is
    read once through one open file; its texts are shown cleaned; any other key is ignored and not shown."""
    crawl = Path(index_root) / "crawl"
    folder = _folder_state(crawl)
    if folder == "missing":
        return _breaker("missing")
    if folder == "bad":  # a link, a file or a folder of another owner is not a folder to trust the file in
        return _breaker("cannot_examine", "the crawl folder is not a plain folder of the owner's")
    path = crawl / "breaker.json"
    try:
        os.lstat(path)
    except FileNotFoundError:
        return _breaker("missing")
    except OSError as e:
        return _breaker("cannot_examine", clean(_why(e), 200))
    read = read_small(path)
    if read.status == "missing":
        return _breaker("missing")
    if read.status == "bad":
        return _breaker("cannot_read", clean(read.reason, 200))
    unreadable = _breaker("cannot_read", "the file is not in the form of the contract")
    try:
        obj = json.loads(read.data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, _Duplicate, _NotFinite, ValueError, RecursionError):
        return unreadable
    if type(obj) is not dict or type(obj.get("tripped")) is not bool:
        return unreadable
    reason, kind, at, run = (obj.get(k) for k in ("reason", "kind", "at", "run"))
    if not (_str_ok(reason, 300) and _str_ok(run, MAX_FIELD) and _str_ok(kind, 40) and kind in ("",) + BREAKER_KINDS and _str_ok(at, 20)):
        return unreadable
    if at:
        try:
            if not _TS.fullmatch(at):
                raise ValueError
            datetime.datetime.strptime(at, _TS_FORMAT)
        except ValueError:
            return unreadable
    return _breaker("tripped" if obj["tripped"] else "not_tripped", None, {"reason": reason, "kind": kind, "at": at, "run": run})


def _holder(fd):
    """The holder named by the lock's line, `<pid> <YYYY-MM-DDTHH:MM:SSZ>`, or `unknown` when the line is missing or is not exactly that."""
    try:
        data = os.pread(fd, MAX_LOCK_LINE + 1, 0)
        match = _LOCK_LINE.fullmatch(data.decode("utf-8")) if len(data) <= MAX_LOCK_LINE else None
        if match and int(match.group(1)) >= 1:
            datetime.datetime.strptime(match.group(2), _TS_FORMAT)
            return {"pid": int(match.group(1)), "since": match.group(2)}
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    return "unknown"


def lock_state(index_root):
    """Whether a run holds `crawl.lock`: `{"held": True|False|None, "holder": {"pid", "since"} | "unknown" | None, "fault": text or None}`. The
    file is opened for reading, never created and never followed if it is a link; **one non-blocking shared `flock` is tried and let go at once**
    (it is never held while anything else is read). If another process holds the lock, `held` is True and the line it wrote is read (at most 256
    bytes, only now: a line left in a free lock is stale and is not read); a line that is missing or wrong makes the holder `unknown`, not the
    lock free. A lock file that is a link, a folder, a pipe or not the owner's is a fault and is not claimed to be held; `held` is None when the
    system cannot say."""
    path = Path(index_root) / "crawl.lock"
    out = {"held": False, "holder": None, "fault": None}
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return out
    except OSError as e:
        return {**out, "held": None, "fault": f"the lock file cannot be looked for ({_why(e)})"}
    if not stat.S_ISREG(info.st_mode):
        return {**out, "fault": "the lock file is not a plain file, so it is not opened"}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return out
    except OSError as e:
        return {**out, "held": None, "fault": f"the lock file cannot be opened ({_why(e)})"}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != _me():
            return {**out, "fault": "the lock file is not a plain file of the owner's, so it is not tried"}
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return {**out, "held": True, "holder": _holder(fd)}
            return {**out, "held": None, "fault": f"the lock cannot be tried ({_why(e)})"}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return out
    finally:
        os.close(fd)


def stop_file(index_root):
    """`{"present": True|False|None, "fault": ...}`: `crawl.stop` counts by its presence, whatever it is (a file, a link, a folder, a pipe)."""
    try:
        os.lstat(Path(index_root) / "crawl.stop")
    except FileNotFoundError:
        return {"present": False, "fault": None}
    except OSError as e:
        return {"present": None, "fault": f"the stop file cannot be looked for ({_why(e)})"}
    return {"present": True, "fault": None}


def state(index_root):
    """The state of the crawl: `stopped` if the stop file is there, else `paused` if the breaker says so (see `breaker_state`: also when its file is
    missing or unreadable), else `running` if another process holds the lock, else `idle`; the facts are given as well, so a run that is finishing
    its step while the stop file exists is shown as both. A fault of a file is listed and never turned into a claim."""
    stop, breaker, lock = stop_file(index_root), breaker_state(index_root), lock_state(index_root)
    running = lock["held"] is True
    name = "stopped" if stop["present"] else "paused" if breaker["paused"] else "running" if running else "idle"
    return {"state": name, "running": running, "stop": stop, "breaker": breaker, "lock": lock,
            "faults": [f for f in (stop["fault"], lock["fault"]) if f]}


# --- the approved plan, the disk, the runs --------------------------------------------------------------------------------------------------

def approved_plan(index_root, read_plan):
    """The approved plan's values. `crawl/approved/current` holds one line, a digest of 32 hexadecimal characters; the copy is
    `crawl/approved/<digest>/plan.txt`, read through `read_plan(path)` (the runner plan's `crawlplan.read_plan`, given by the caller: this module
    has no reader of its own). `{"status": "approved"|"none"|"unreadable", "digest", "values", "reason"}`: `none` when there is no approved plan
    (every case: no folder, no `current`, a line that is not one digest, no folder or no `plan.txt` of that digest, a link where a plain file or
    folder is expected), `unreadable` when the reader fails (its message is cleaned). `values` has only the keys of `PLAN_VALUES` that the plan
    gives, and only plain values (a number, a text or a yes/no); a key the plan lacks is absent and never guessed."""
    def none(why):
        return {"status": "none", "digest": None, "values": None, "reason": why}

    folder = Path(index_root) / "crawl" / "approved"
    if _folder_state(Path(index_root) / "crawl") != "ok" or _folder_state(folder) != "ok":
        return none("there is no approved folder of the owner's")
    current = read_small(folder / "current", MAX_LOCK_LINE)
    if current.status != "ok":
        return none("there is no current approval")
    try:
        text = current.data.decode("utf-8")
    except UnicodeDecodeError:
        return none("the current approval is not one digest")
    if not _DIGEST.fullmatch(text):
        return none("the current approval is not one digest")
    digest = text[:32]
    copy = folder / digest
    if _folder_state(copy) != "ok":
        return none("the folder of the approved copy is missing or is not a plain folder of the owner's")
    plan_file = copy / "plan.txt"
    try:
        info = os.lstat(plan_file)
    except OSError:
        return none("the approved copy has no plan file")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != _me():
        return none("the plan file of the approved copy is not a plain file of the owner's")
    try:
        plan = read_plan(str(plan_file))
    except Exception as e:  # the reader is the caller's, and what it raises is shown cleaned and not trusted
        return {"status": "unreadable", "digest": digest, "values": None, "reason": clean(str(e) or type(e).__name__, 200)}
    if type(plan) is not dict:
        return {"status": "unreadable", "digest": digest, "values": None, "reason": "the reader gave no plan"}
    values = {key: plan[key] for key in PLAN_VALUES if key in plan and type(plan[key]) in (int, float, str, bool)}
    return {"status": "approved", "digest": digest, "values": values, "reason": None}


def zone_of(plan):
    """`(zone, problem)`: the time zone of an approved plan as `approved_plan` gave it, and `local` (the spec's default) without one. A plan
    that cannot be read, or that names a zone that is not text or that the system does not know, gives `local` **and a problem**, so that a
    day counted in the machine's zone is never counted silently."""
    if isinstance(plan, dict):
        status = plan.get("status")
        if status == "unreadable":
            return "local", "the approved plan cannot be read, so the machine's time zone is used"
        if status == "approved":
            zone = (plan.get("values") or {}).get("timezone")
            if zone is None:
                return "local", None
            if not isinstance(zone, str):
                return "local", "the time zone of the plan is not text"
            if zone != "local":
                try:
                    day_bounds(datetime.date(2000, 1, 3), zone)
                except KbError:
                    return "local", "the time zone of the plan is not one the system knows, so the machine's is used"
            return zone, None
    return "local", None


def _free(path, statvfs):
    try:
        info = statvfs(path)
        return int(info.f_bavail) * int(info.f_frsize), None
    except OSError as e:
        return None, clean(_why(e), 200)
    except (AttributeError, TypeError, ValueError) as e:
        return None, clean(type(e).__name__, 200)


def _floor(gb):
    if type(gb) not in (int, float) or not math.isfinite(gb) or gb < 0:
        return None
    return int(gb * GIB)


def disk(bulk_root, index_root, floors, statvfs=os.statvfs):
    """The free space of the two drives against their floors. `free_bytes` is what a user may use (`f_bavail` times the block size); `floor_bytes`
    is the plan's floor in gigabytes (2**30 bytes) or None if it is not known; `below_floor` is `free < floor` and `at_or_under_floor` is `free <=
    floor`, **the runner's refusal rule**; a reading that fails is None with the reason. `same_device` says the two roots are on one drive."""
    floors = floors if isinstance(floors, dict) else {}
    out = {}
    for side, root, key in (("bulk", bulk_root, "bulk_floor_gb"), ("index", index_root, "index_floor_gb")):
        free, reason = _free(root, statvfs)
        floor = _floor(floors.get(key))
        known = free is not None and floor is not None
        out[side] = {"free_bytes": free, "floor_bytes": floor, "below_floor": free < floor if known else None,
                     "at_or_under_floor": free <= floor if known else None, "reason": reason}
    try:
        out["same_device"] = os.stat(bulk_root).st_dev == os.stat(index_root).st_dev
    except (OSError, TypeError, ValueError):
        out["same_device"] = None
    return out


def last_run(index_root, now, *, max_files=MAX_RUN_FILES, max_bytes=MAX_RUN_BYTES, limit=MAX_LOG_BYTES):
    """The last run, from `run_start` and `run_end` lines only. **The log files are searched from the newest back, and the search stops at the
    first file that has a `run_start`**, so any number of newer files that hold only refused firings (a `refuse` line each) do not hide a run in an older file; it
    is bounded by `max_files` files and `max_bytes` bytes in all (the end of a file over `limit` is the part read), and `stopped_by` says why it
    stopped: `found`, `no_more_files` (every file was searched), `max_files` or `max_bytes` (a run may be older: the answer is "not in what was
    searched", not "none"). The last run is the run whose `run_start` has the newest `ts` (the later line if two are equal), with the `run_end`
    of the same `run` that is not older than its start; none: `status` is `no end line`. A `refuse` line is not a run. `now` is an aware time, for
    `age_s`."""
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise _refuse("now is a time with a zone")
    for bound in (max_files, max_bytes, limit):
        if type(bound) is not int or bound < 1:
            raise _refuse("a search bound is a whole number of at least 1")
    found, problem = log_files(index_root, newest_first=True)
    out = {"found": False, "searched_files": 0, "files_read": 0, "bytes_read": 0, "stopped_by": "no_more_files", "bad": {}, "cut": False,
           "problem": problem}
    chunks = []  # the lines of each file read, the newest file's first
    for _date, path in found:
        if out["searched_files"] >= max_files:
            out["stopped_by"] = "max_files"
            break
        if out["bytes_read"] >= max_bytes:
            out["stopped_by"] = "max_bytes"
            break
        out["searched_files"] += 1
        read = read_log(path, limit=limit, tail=True)
        if read["status"] != "ok":
            continue
        out["files_read"] += 1
        out["bytes_read"] += read["bytes"]
        out["cut"] = out["cut"] or read["cut"]
        for kind, count in read["bad"].items():
            out["bad"][kind] = out["bad"].get(kind, 0) + count
        chunks.append([r for r in read["lines"] if r["step"] in ("run_start", "run_end")])
        if any(r["step"] == "run_start" for r in chunks[-1]):
            out["stopped_by"] = "found"
            break
    lines = [r for chunk in reversed(chunks) for r in chunk]  # in time order, so that the later line wins a tie
    start = None
    for record in lines:
        if record["step"] == "run_start" and (start is None or record["ts"] >= start["ts"]):
            start = record
    if start is None:
        return out
    end = None
    for record in lines:
        if record["step"] == "run_end" and record["run"] == start["run"] and record["ts"] >= start["ts"] and (end is None or record["ts"] >= end["ts"]):
            end = record
    began = datetime.datetime.strptime(start["ts"], _TS_FORMAT).replace(tzinfo=datetime.timezone.utc)
    age = int((now - began).total_seconds())
    out.update(found=True, run=clean(start["run"], 200), start=start["ts"], end=end["ts"] if end else None, age_s=age if age >= 0 else None,
               status="ended" if end else "no end line", end_outcome=end["outcome"] if end else None,
               end_reason=clean(end["reason"], 300) if end and end["reason"] is not None else None,
               end_n=end["n"] if end else None, end_seconds=end["seconds"] if end else None)
    return out


def run_counts(index_root, day, zone):
    """The runs of a day of `zone`, by the `ts` of their lines: how many started and ended (`run_start` and `run_end` only, the ends by outcome),
    and apart from them how many firings were refused (`refuse` lines, by cleaned reason, the ten commonest). A refused firing is not a run."""
    found = lines_of_day(index_root, day, zone)
    started = ended = refused = 0
    outcomes, reasons = {}, {}
    for record in found["lines"]:
        if record["step"] == "run_start":
            started += 1
        elif record["step"] == "run_end":
            ended += 1
            outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
        elif record["step"] == "refuse":
            refused += 1
            why = clean(record["reason"], 100) or "(no reason)"
            reasons[why] = reasons.get(why, 0) + 1
    top = dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:10])
    return {"day": found["day"], "started": started, "ended": ended, "ended_by_outcome": outcomes, "refused": refused, "refused_by_reason": top,
            "bad": found["bad"], "cut": found["cut"], "unreadable": found["unreadable"], "problem": found["problem"],
            "first": found["first"], "last": found["last"]}
