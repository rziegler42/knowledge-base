"""The store of the action-review shadow: four files of JSON lines below ``~/.config/project-workbench/action-review/``.

The shadow hook writes them, the labelling tool adds to one, and the report reads them (``docs/specs/action-review.md``,
"The shadow hook", "The data files"). This file is shipped with the module and the owner copies it out of the project, so it
imports only the standard library and runs nothing when imported.

What it keeps true:

* The directory is below the guarded store, found from the home directory. No option or file moves it
  (``docs/decisions/2026-10-20-fixed-store-location.md``); `home` is an argument so that tests can use another one. Without it the
  directory comes from ``HOME`` (``expanduser``), which is what the owner-run labelling tool and the report use at a terminal; **the
  hook never relies on that**: it takes the account's home directory from the account database and passes it in
  (``shadow_hook.account_home``).
* The store root and the directory are real directories, owned by the current user, with mode exactly 0700, and nothing on the
  way down is followed through a link (the ancestors of the store may be, as for the guarded store). A directory with another
  mode is refused and named, never repaired. What is made is the store root (mode 0700), ``action-review`` and its four files,
  and ``~/.config`` itself only if it is missing; nothing else in the store is read or written.
* A file is a regular file with one link, owned by the current user, with no group or other access (mode 0600), reached
  with no-follow opens. Anything else is refused.
* A row is one line of strict JSON, ASCII only, appended with one write under a lock. A row that does not fit its format, or its
  line cap, is refused on write; on read it is skipped and counted. A failed write cuts the file back to what it held.

The rows hold command text and diffs and are never tracked or kept inside a project.
"""

import errno
import fcntl
import json
import os
import re
import secrets
import stat
import time

MAX_FILE_BYTES = 128 * 1024 * 1024
DIR_MODE = 0o700
FILE_MODE = 0o600
LOCK_SECONDS = 5.0

OUTCOMES = ("reviewed", "no_rule", "unreviewable", "refused", "failed", "timeout", "malformed_input", "not_bash")
VERDICTS = ("approve", "decline")
LABELS = ("right", "wrong", "skip")

_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[0-9a-f]{32}")
_CHECK = re.compile(r"[a-z][a-z0-9_]{0,63}")
_RULE = re.compile(r"[a-z][a-z0-9-]{0,127}")
_CASE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class StoreError(Exception):
    """The store cannot be used, or a row does not fit. The text is fixed and quotes no row."""


# -- field checks ---------------------------------------------------------------------------------------------------

def _text(limit):
    return lambda value: isinstance(value, str) and len(value) <= limit


def _match(pattern):
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _one_of(*values):
    return lambda value: isinstance(value, str) and value in values


def _or_none(check):
    return lambda value: value is None or check(value)


def _flag(value):
    return type(value) is bool


def _whole(value):
    return type(value) is int and 0 <= value <= 1000000


def _checks(value):
    return isinstance(value, list) and len(value) <= 32 and all(_match(_CHECK)(item) for item in value) \
        and len(set(value)) == len(value)


def _object(value):
    return isinstance(value, dict)


# For each file: the fields every row has, the fields it may have, and the largest line in bytes.
FORMATS = {
    "verdicts.jsonl": {
        "line": 8192,
        "required": {"ts": _match(_TS), "command_sha256": _or_none(_match(_SHA)), "outcome": _one_of(*OUTCOMES),
                     "verdict": _or_none(_one_of(*VERDICTS)), "failed_checks": _checks, "reason": _or_none(_text(300)),
                     "reviewed": _flag, "no_review_reason": _or_none(_one_of(*OUTCOMES))},
        "optional": {"rule": _or_none(_match(_RULE)), "facts_sha256": _or_none(_match(_SHA)),
                     "rubric_sha256": _or_none(_match(_SHA)), "bridge": _or_none(_text(200)),
                     "model": _or_none(_text(200)), "effort": _or_none(_text(20)), "format": _whole},
    },
    "collected.jsonl": {
        "line": 512 * 1024,
        "required": {"id": _match(_ID), "ts": _match(_TS), "rule": _match(_RULE), "command_sha256": _match(_SHA),
                     "command": _text(4096), "facts": _object, "verdict": _one_of(*VERDICTS),
                     "failed_checks": _checks, "reason": _text(300)},
        "optional": {},
    },
    "labels.jsonl": {
        "line": 4096,
        "required": {"id": _match(_ID), "label": _one_of(*LABELS), "ts": _match(_TS)},
        "optional": {"note": _text(300)},
    },
    "testset.jsonl": {
        "line": 8192,
        "required": {"case": _match(_CASE), "ts": _match(_TS), "expected": _one_of(*VERDICTS),
                     "verdict": _one_of(*VERDICTS), "failed_checks": _checks, "mismatch": _flag,
                     "bridge": _or_none(_text(200)), "model": _or_none(_text(200)), "effort": _or_none(_text(20))},
        "optional": {},
    },
}


def _verdict_is_consistent(row):
    """An approve names no failed check and a decline at least one, as the engine's verdict does."""
    return (row["verdict"] == "approve") == (not row["failed_checks"])


def check_row(name, row):
    """None when `row` fits the format of the file `name`, else a fixed text saying which rule it breaks."""
    layout = FORMATS[name]
    if not isinstance(row, dict):
        return "a row is not an object"
    required, optional = layout["required"], layout["optional"]
    for field in row:
        if field not in required and field not in optional:
            return "a row has a field the format does not name"
    for field, check in required.items():
        if field not in row:
            return "a row lacks a field the format requires"
        if not check(row[field]):
            return "a field of a row is not of its type or bound"
    for field, check in optional.items():
        if field in row and not check(row[field]):
            return "a field of a row is not of its type or bound"
    if name == "verdicts.jsonl":
        if row["reviewed"] != (row["outcome"] == "reviewed"):
            return "reviewed does not agree with the outcome"
        if row["reviewed"]:
            if row["no_review_reason"] is not None or row["verdict"] is None or not _verdict_is_consistent(row):
                return "a reviewed row does not hold a whole verdict"
        elif row["no_review_reason"] != row["outcome"] or row["verdict"] is not None or row["failed_checks"]:
            return "a row that was not reviewed holds a verdict or a wrong reason"
    elif name == "collected.jsonl":
        if not _verdict_is_consistent(row):
            return "an approve names a failed check or a decline names none"
    elif name == "testset.jsonl":
        if row["mismatch"] != (row["expected"] != row["verdict"]):
            return "mismatch does not agree with expected and verdict"
        if not _verdict_is_consistent(row):
            return "an approve names a failed check or a decline names none"
    return None


# -- the directory and the files ----------------------------------------------------------------------------------------

def data_dir(home=None):
    """The directory of the store below `home`, which defaults to the home directory ``expanduser`` finds (from ``HOME``). The
    hook always passes `home` explicitly, from the account database."""
    if home is None:
        home = os.path.expanduser("~")
    if not isinstance(home, str) or not os.path.isabs(home) or "\0" in home:
        raise StoreError("cannot find the home directory for the store")
    return os.path.join(home, ".config", "project-workbench", "action-review")


def new_id():
    """A random 128-bit identifier as 32 lowercase hex characters."""
    return secrets.token_hex(16)


def now():
    """The time in UTC to the second, in the form the rows use."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _check_directory(fd, shown):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise StoreError("a directory of the store is not a directory of the current user: %s" % shown)
    mode = stat.S_IMODE(info.st_mode)
    if mode != DIR_MODE:
        raise StoreError("a directory of the store has mode %04o, not 0700: %s" % (mode, shown))


def _open_directory(home, create):
    """The descriptor of the store's directory, or None when it is absent and `create` is false."""
    base = os.path.dirname(os.path.dirname(data_dir(home)))
    if create:
        try:
            os.makedirs(base, exist_ok=True)
        except OSError as exc:
            raise StoreError("cannot make %s: %s" % (base, exc.strerror or exc)) from None
    try:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except FileNotFoundError:
        if create:
            raise StoreError("cannot open %s" % base) from None
        return None
    except OSError as exc:
        raise StoreError("cannot open %s: %s" % (base, exc.strerror or exc)) from None
    shown = base
    try:
        for name in ("project-workbench", "action-review"):
            shown = shown + "/" + name
            made = False
            if create:
                try:
                    os.mkdir(name, DIR_MODE, dir_fd=fd)
                    made = True
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise StoreError("cannot make %s: %s" % (shown, exc.strerror or exc)) from None
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                fd = -1
                return None
            except OSError as exc:
                raise StoreError("cannot open %s without following a link: %s" % (shown, exc.strerror or exc)) from None
            os.close(fd)
            fd = child
            if made:
                os.fchmod(fd, DIR_MODE)
            _check_directory(fd, shown)
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _open_file(directory_fd, name, writing):
    # O_NONBLOCK so that a FIFO planted in place of a file cannot hold the opener; the checks below refuse it. It does nothing
    # for a regular file. The write opens for reading too, to look at the last byte before a row is added.
    flags = os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_RDWR | os.O_APPEND | os.O_CREAT if writing else os.O_RDONLY)
    try:
        fd = os.open(name, flags, FILE_MODE, dir_fd=directory_fd)
    except FileNotFoundError:
        if writing:
            raise StoreError("cannot make %s" % name) from None
        return None
    except OSError as exc:
        raise StoreError("cannot open %s without following a link: %s" % (name, exc.strerror or exc)) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise StoreError("%s is not a regular file of the current user with one link" % name)
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise StoreError("%s is open to other users" % name)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _name(name):
    if not isinstance(name, str) or name not in FORMATS:
        raise StoreError("that is not one of the four files of the store")
    return name


def _lock(fd):
    deadline = time.monotonic() + LOCK_SECONDS
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise StoreError("cannot lock the file: %s" % (exc.strerror or exc)) from None
            if time.monotonic() >= deadline:
                raise StoreError("the file stayed locked by another writer") from None
            time.sleep(0.05)


def append(name, row, home=None):
    """Add `row` to the file `name` as one line, or raise `StoreError` and leave the file as it was."""
    name = _name(name)
    problem = check_row(name, row)
    if problem:
        raise StoreError(problem)
    try:
        text = json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        raise StoreError("a row is not plain JSON data") from None
    line = text.encode("ascii") + b"\n"
    if len(line) > FORMATS[name]["line"]:
        raise StoreError("a row is longer than its file allows")
    directory = _open_directory(home, True)
    try:
        fd = _open_file(directory, name, True)
        try:
            _lock(fd)
            before = os.fstat(fd).st_size
            if before + len(line) > MAX_FILE_BYTES:
                raise StoreError("the file is full")
            # A writer that was killed part-way leaves a fragment with no newline. The next row starts a line of its own,
            # so the fragment stays one bad line, counted when read, and does not swallow a good row.
            if before and os.pread(fd, 1, before - 1) != b"\n":
                line = b"\n" + line
            try:
                written = 0
                while written < len(line):
                    written += os.write(fd, line[written:])
            except BaseException as exc:
                try:
                    os.ftruncate(fd, before)
                except OSError:
                    pass
                if isinstance(exc, OSError):
                    raise StoreError("a row could not be written") from None
                raise
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _strict_pairs(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a duplicate key")
    return dict(pairs)


def _refuse_constant(_):
    raise ValueError("not a JSON number")


def _finite(text):
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("a number too large for a float")
    return value


def read(name, home=None):
    """``(rows, skipped)`` for the file `name`: the rows that fit its format, in order, and the number of lines that did not.
    A missing file reads as no rows. A last line with no newline is unfinished and is skipped."""
    name = _name(name)
    directory = _open_directory(home, False)
    if directory is None:
        return [], 0
    try:
        fd = _open_file(directory, name, False)
        if fd is None:
            return [], 0
        try:
            if os.fstat(fd).st_size > MAX_FILE_BYTES:
                raise StoreError("the file is larger than the store allows")
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    data = b"".join(chunks)
    lines = data.split(b"\n")
    skipped = 1 if lines[-1] else 0
    rows = []
    limit = FORMATS[name]["line"]
    for raw in lines[:-1]:
        try:
            if len(raw) + 1 > limit:
                raise ValueError("a line over its cap")
            row = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_pairs, parse_constant=_refuse_constant,
                             parse_float=_finite)
            if check_row(name, row) is not None:
                raise ValueError("a row that does not fit")
        except (ValueError, RecursionError):
            skipped += 1
            continue
        rows.append(row)
    return rows, skipped
