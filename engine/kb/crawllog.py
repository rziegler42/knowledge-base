"""The crawl's log (`docs/specs/population.md`, "Safeguards", the log; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment C).

`Log(index_root, run).write(step, outcome, candidate=, book=, host=, reason=, n=, seconds=, now=)` appends **one JSON line** to `<index root>/crawl/log/crawl-YYYY-MM-DD.jsonl`, the day being the UTC day of the line. Every line
holds the same ten fields in the same order (`ts` in UTC, `run`, `step`, `outcome`, `candidate`, `book`, `host`, `reason`, `n`, `seconds`; a field that does not apply is `null`), and `step` and `outcome` are only the
spec's names. The line is made as ASCII (so a file never holds a character that a terminal could act on) and goes out in **one `O_APPEND` write**, so two processes that append leave whole lines only.

The text fields are cleaned of control, invisible and direction characters and cut to a length. A text that looks like a **credential** is refused, not logged: a header line (`Auth-Key: ...`, `Authorization: ...`, a cookie,
a password or key assignment, `Bearer ...`), a run of 40 or more key characters that is not a hexadecimal digest, and any value the caller names in `secrets` (found even when a hidden character or a line break splits it).
A refusal says that a field looked like a credential and never quotes it. A line over 8 KiB has its reason cut and says so (`[cut]`). A log that cannot be written raises `KbError`: a run that cannot log must stop. A write that fails part way (a full disk) can leave an unfinished line, so a reader skips a line that is not JSON.
The patterns are a net; `secrets` (the key the caller holds) is the real guard. Beside the header, bearer and long-run shapes the net holds `Basic <base64>`, a password in the front of an address, `?key=`, `?sig=` and
similar query values, a JWT, an AWS-style key id and the named assignments (`secret_key=`, `access_key=`, `private_key=`, `pwd=`; `client_secret=`, `auth_token=` and `AWS_SECRET_ACCESS_KEY=` are caught by the plain `secret`, `token` and `access_key` names, since `_` is a boundary). `Log.safe(text, field)` is for the steps: it gives the text as
the log would take it, or the fixed `WITHHELD` if the log would refuse it, so that what a hostile page said never ends a run. A torn write (a full disk) can leave a file that does not end in a line feed: the next
record then starts with one, in its own single write, so it is whole and the stub stays a line of its own that a reader skips.

The folders `crawl/` and `crawl/log/` are made mode 700 and the file mode 600; a folder or file that is a link, not a plain folder or file (a folder or a pipe in the file's place included), another user's or writable by
others is refused. This module reads no environment variable, makes no request and takes no model."""
import datetime
import json
import math
import os
import re
import stat

from . import KbError, textutil

STEPS = ("run_start", "refuse", "list_update", "discover", "enqueue", "block", "fetch", "capture", "scan", "hold", "convert", "index", "judge", "reject", "card", "propose", "move", "fail", "breaker",
         "stop", "run_end", "report")
OUTCOMES = ("ok", "skipped", "rejected", "failed", "blocked", "held", "refused", "tripped")
FIELDS = ("ts", "run", "step", "outcome", "candidate", "book", "host", "reason", "n", "seconds")
LIMITS = {"reason": 500, "book": 120, "host": 253}
MARGIN = 256                    # the patterns look at the text that is logged and this much past it, so that a shape that straddles the cut is seen and the cost stays in proportion to what is logged
LINE_MAX = 8192
CUT = " [cut]"
MAX_INT = 2**63 - 1
_RUN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_HEADER = re.compile(r"""(?i)(?:^|[^a-z0-9])(?:auth-key|authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token|api[-_]?key|password|passwd|secret|token|bearer|secret[_-]?key|access[_-]?key|private[_-]?key|pwd)['"\]]?\s*[:=]\s*\S""")
_BEARER = re.compile(r"(?i)\bbearer\s+\S{8,}")
_BASIC = re.compile(r"(?i)\bbasic\s+(?=[A-Za-z0-9+/]*(?:[0-9+]|=))[A-Za-z0-9+/]{8,}={0,2}")          # `Basic <base64>` (it holds a digit, a plus or a padding character, which an English word, or a word pair like input/output, does not)
_USERINFO = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")                          # a password in the front of an address
_HOSTUSER = re.compile(r"[^\s/@:]+:[^/\s@]+@")                                                  # the same in a host field, which has no scheme
_QUERY = re.compile(r"(?i)[?&](?:key|apikey|api_key|sig|signature|token|password|secret|x-amz-signature|x-amz-credential|x-goog-signature)=[^&\s]{4,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_AWS = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b")
WITHHELD = "the text was withheld"
_LONG = re.compile(r"[A-Za-z0-9_+/=-]{40,}")
_HEX = re.compile(r"[0-9a-fA-F]+")


def new_run_id(now=None):
    """A name for one run: its start in UTC and six random hexadecimal characters."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(3).hex()


def _private_dir(path):
    """A folder of ours, not a link, that others cannot write; made mode 700 if it is not there."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)
        except FileExistsError:           # another process made it in the meantime: it is checked as any other
            return _private_dir(path)
        except OSError as e:
            raise KbError(f"the crawl log folder cannot be made ({e.strerror})") from None
        return
    except OSError as e:
        raise KbError(f"the crawl log folder cannot be examined ({e.strerror})") from None
    if not stat.S_ISDIR(info.st_mode):
        raise KbError("a folder of the crawl log is a link or not a folder")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise KbError("a folder of the crawl log is not ours or can be written by others")


def _check_file(info):
    if not stat.S_ISREG(info.st_mode):
        raise KbError("the crawl log file is a link or not a plain file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise KbError("the crawl log file is not ours or can be written by others")


class Log:
    """The log of one run, written under `index_root`; `secrets` are values that must never reach it; `clock` gives an aware time when `write` is not given one."""

    def __init__(self, index_root, run, secrets=(), clock=None):
        if not isinstance(run, str) or not _RUN.fullmatch(run):
            raise KbError("a run name is 1 to 64 letters, digits or . _ : -")
        if isinstance(secrets, (str, bytes)) or not isinstance(secrets, (list, tuple, set, frozenset)) or not all(isinstance(s, str) for s in secrets):
            raise KbError("the secrets are a list of strings")
        self.index_root = os.fspath(index_root)
        self.run = run
        self._secrets = [("".join(s.split())).casefold() for s in secrets if "".join(s.split())]
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def _text(self, value, field):
        if value is None:
            return None
        if not isinstance(value, str):
            raise KbError(f"the log's {field} is text")
        squeezed = "".join(textutil.clean(value, len(value) + 1).split()).casefold()
        for secret in self._secrets:                                      # a named secret is looked for in the whole text, wherever it is (a plain substring search, linear)
            if secret in squeezed or secret in "".join(value.split()).casefold():
                raise KbError(f"the log's {field} holds a value that must not be logged")
        shown = textutil.clean(value, LIMITS[field])
        # The shapes are looked for in what will be logged and in a little past it, never in the whole of a text a page chose the length of (the patterns can cost the square of the text), and in the cut text
        # itself, so that what `safe` gives back is what `write` takes.
        for probe in (shown, textutil.clean(value, LIMITS[field] + MARGIN)):
            shaped = any(pattern.search(probe) for pattern in (_HEADER, _BEARER, _BASIC, _USERINFO, _QUERY, _JWT, _AWS))
            if shaped or (field == "host" and _HOSTUSER.search(probe)) or (field != "host" and any(not _HEX.fullmatch(run) for run in _LONG.findall(probe))):
                raise KbError(f"the log's {field} looks like a credential and is not logged")
        return shown or None

    def safe(self, value, field="reason"):
        """`value` as the log would take it for `field`, or, if the log would refuse it (text that looks like a credential, a secret of the run, something that is not text), the fixed `WITHHELD`: for the steps,
        so that what a hostile page said can be logged without a refusal ending the run. `None` and empty text give `None`."""
        if field not in LIMITS:
            raise KbError("the log's text fields are " + ", ".join(sorted(LIMITS)))
        try:
            return self._text(value, field)
        except KbError:
            return WITHHELD

    @staticmethod
    def _count(value, field):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_INT:
            raise KbError(f"the log's {field} is a whole number from 0")
        return value

    def _line(self, step, outcome, now, candidate, book, host, reason, n, seconds):
        if step not in STEPS or not isinstance(step, str):
            raise KbError("the log's step is not one of the spec's")
        if outcome not in OUTCOMES or not isinstance(outcome, str):
            raise KbError("the log's outcome is not one of the spec's")
        if not isinstance(now, datetime.datetime) or now.tzinfo is None:
            raise KbError("the log needs a time with a time zone")
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0 or seconds > 10**9 or not math.isfinite(seconds):
                raise KbError("the log's seconds is a number from 0")
            seconds = round(seconds, 3)
        record = {"ts": now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "run": self.run, "step": step, "outcome": outcome,
                  "candidate": self._count(candidate, "candidate"), "book": self._text(book, "book"), "host": self._text(host, "host"), "reason": self._text(reason, "reason"),
                  "n": self._count(n, "n"), "seconds": seconds}
        dump = lambda: (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")  # noqa: E731
        data = dump()
        if len(data) > LINE_MAX:
            reason = record["reason"] or ""
            while len(data) > LINE_MAX and reason:
                reason = reason[: len(reason) // 2].rstrip()
                record["reason"] = reason + CUT
                data = dump()
            if len(data) > LINE_MAX:
                raise KbError("a log line is over its limit and cannot be cut to it")
        return record["ts"][:10], data

    def write(self, step, outcome, *, candidate=None, book=None, host=None, reason=None, n=None, seconds=None, now=None):
        """Append one line. Raises `KbError` for a field that is not valid or looks like a credential, and for a log that cannot be written."""
        day, data = self._line(step, outcome, now if now is not None else self._clock(), candidate, book, host, reason, n, seconds)
        crawl = os.path.join(self.index_root, "crawl")
        folder = os.path.join(crawl, "log")
        _private_dir(crawl)
        _private_dir(folder)
        path = os.path.join(folder, f"crawl-{day}.jsonl")
        try:
            _check_file(os.lstat(path))
        except FileNotFoundError:
            pass
        except OSError as e:
            raise KbError(f"the crawl log file cannot be examined ({e.strerror})") from None
        try:
            fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except OSError as e:
            raise KbError(f"the crawl log cannot be opened ({e.strerror})") from None
        try:
            size = os.fstat(fd).st_size
            _check_file(os.fstat(fd))
            if size > 0 and os.pread(fd, 1, size - 1) != b"\n":       # a torn earlier write left no line end: this record starts a line of its own, in the same single write
                data = b"\n" + data
            if os.write(fd, data) != len(data):
                raise KbError("the crawl log line was not written whole")
        except OSError as e:
            raise KbError(f"the crawl log cannot be written ({e.strerror})") from None
        finally:
            os.close(fd)
