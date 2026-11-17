"""The guards that stop a crawl run (`docs/specs/population.md`, "Safeguards"; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment D).

Each guard is a small function that a run calls in the spec's order and a test can drive:

- **The run lock** `<index root>/crawl.lock`: `acquire_run_lock` takes an exclusive, non-blocking `flock` and, while it holds it, writes one line, `<pid> <start as YYYY-MM-DDTHH:MM:SSZ>`; it returns `None` if another run holds it (and
  writes nothing, so the holder's line stands). The lock is the kernel's, so a run that dies leaves none. It differs from `catalog.lock` (which waits up to a time limit for a writer and writes nothing into the file) in being
  its own file, non-blocking, and in carrying the line. A lock file that is a link, a folder, a pipe, not ours or writable by others is refused.
- **The stop file** `<index root>/crawl.stop`: `stop_requested` is true if the name is there, whatever it is and whatever it holds, or if it cannot be examined.
- **The breaker** `<index root>/crawl/breaker.json`: `read_breaker` reads it strictly; a file that is missing, cannot be examined or read in its form, or says `"tripped": true` reads as **tripped**. `_write_breaker` (private) writes it
  whole or not at all. `trip` records a trip (the first cause stands while it is tripped). `clear` is `crawl-clear`: it changes nothing without `--yes` and without a terminal, and it starts the guard state afresh.
- **The rules that trip it**, with a small state kept in `crawl/guard.json`: `record_fetch` (failures in a row, a failure share over a full window), `note_model` (the model server down longer than `model_down_minutes`),
  `bound_trip` (a stage that hits a bound).
- **A site stopped for the day** is not the breaker: `refusals_today` reads the day's `refusal:<site>` counters (read only) and `site_stopped` says whether one site has reached `domain_refusals`; the stop ends with the plan's day.
- **The disk floors**: `check_disk` refuses when a drive's free space is at or under its floor or cannot be read. **The model probe**: `probe_model` is one call of the existing `embed` on one short text.

This module makes no request of its own, reads no environment variable and starts no program."""
import datetime
import fcntl
import json
import os
import re
import stat
import sys

from . import KbError, crawllog, crawlplan, textutil

KINDS = ("consecutive_failures", "failure_share", "model_down", "stage_bound")
REASON_MAX = 300
MAX_FILE = 16 * 1024
MAX_HISTORY = 1000
PROBE_TEXT = "ping"
WITHHELD = "the reason was withheld"
BREAKER_KEYS = ("tripped", "reason", "kind", "at", "run")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_RUN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
GB = 10**9


class _Unreadable(Exception):
    """A file that is missing (`missing` true) or cannot be read in its form."""

    def __init__(self, missing=False):
        super().__init__()
        self.missing = missing


def _stamp(now):
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise KbError("a guard needs a time with a time zone")
    return now.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def is_terminal():
    """True only when both the input and the output are a terminal; a closed, missing or failing stream is not one."""
    try:
        return bool(sys.stdin is not None and sys.stdout is not None and sys.stdin.isatty() and sys.stdout.isatty())
    except (ValueError, OSError, AttributeError):
        return False


def _check_file(info):
    if not stat.S_ISREG(info.st_mode):
        raise KbError("a file of the crawl guards is a link or not a plain file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise KbError("a file of the crawl guards is not ours or can be written by others")


# ---- the run lock

class RunLock:
    """A held run lock; `release` (or leaving a `with`) empties the line and lets go."""

    def __init__(self, fd):
        self._fd = fd

    def release(self):
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            os.ftruncate(fd, 0)
        except OSError:
            pass
        os.close(fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def acquire_run_lock(index_root, now=None, pid=None):
    """The run lock, or `None` when another run holds it (nothing is written then). A refusal for a lock file that is not a plain file of ours."""
    stamp = _stamp(now if now is not None else _utc_now())
    path = os.path.join(os.fspath(index_root), "crawl.lock")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise KbError(f"the run lock cannot be examined ({e.strerror})") from None
    else:
        _check_file(info)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as e:
        raise KbError(f"the run lock cannot be opened ({e.strerror})") from None
    try:
        _check_file(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        except OSError as e:
            raise KbError(f"the run lock cannot be taken ({e.strerror})") from None
        line = b"%d %s\n" % (os.getpid() if pid is None else pid, stamp.encode("ascii"))
        try:
            os.ftruncate(fd, 0)
            os.pwrite(fd, line, 0)
        except OSError as e:
            raise KbError(f"the run lock's line cannot be written ({e.strerror})") from None
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return RunLock(fd)


# ---- the stop file

def stop_requested(index_root):
    """True if `<index root>/crawl.stop` is there in any form, or cannot be examined; its content is never read."""
    try:
        os.lstat(os.path.join(os.fspath(index_root), "crawl.stop"))
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


# ---- small files of the guards

def _read_small(path):
    """The bytes of a plain file of ours that others cannot write, at most `MAX_FILE`; otherwise `_Unreadable`."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise _Unreadable(missing=True) from None
    except OSError:
        raise _Unreadable() from None
    try:
        _check_file(info)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (KbError, OSError):
        raise _Unreadable() from None
    try:
        _check_file(os.fstat(fd))
        data = os.read(fd, MAX_FILE + 1)
    except (KbError, OSError):
        raise _Unreadable() from None
    finally:
        os.close(fd)
    if len(data) > MAX_FILE:
        raise _Unreadable()
    return data


def _json_object(data):
    """The one JSON object in `data`, with no repeated key and no `NaN`; otherwise `_Unreadable`."""
    def pairs(items):
        keys = [k for k, _ in items]
        if len(set(keys)) != len(keys):
            raise ValueError("a key is repeated")
        return dict(items)

    def constant(name):
        raise ValueError(name)

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _Unreadable() from None
    if not isinstance(value, dict):
        raise _Unreadable()
    return value


def _atomic_write(folder, name, data):
    """Write `data` to `folder/name` whole or not at all: a new file at mode 600, written and synced, then renamed over the name (a link there is replaced, not followed)."""
    final = os.path.join(folder, name)
    tmp = os.path.join(folder, f".{name}-{os.urandom(6).hex()}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, final)
        dir_fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise KbError(f"{name} cannot be written ({e.strerror})") from None


def _crawl_dir(index_root):
    folder = os.path.join(os.fspath(index_root), "crawl")
    crawllog._private_dir(folder)
    return folder


# ---- the breaker

def _breaker_record(data):
    value = _json_object(data)
    if tuple(sorted(value)) != tuple(sorted(BREAKER_KEYS)):
        raise _Unreadable()
    if not isinstance(value["tripped"], bool) or not isinstance(value["reason"], str) or len(value["reason"]) > REASON_MAX or textutil.clean(value["reason"], REASON_MAX) != value["reason"]:
        raise _Unreadable()
    if not isinstance(value["kind"], str) or (value["kind"] and value["kind"] not in KINDS):
        raise _Unreadable()
    if not isinstance(value["at"], str) or not _TS.fullmatch(value["at"]) or not isinstance(value["run"], str) or (value["run"] and not _RUN.fullmatch(value["run"])):
        raise _Unreadable()
    return {key: value[key] for key in BREAKER_KEYS}


def _read_breaker(index_root):
    try:
        return _breaker_record(_read_small(os.path.join(os.fspath(index_root), "crawl", "breaker.json"))), None
    except _Unreadable as e:
        return None, "the breaker file is missing" if e.missing else "the breaker file cannot be read in its form"


def read_breaker(index_root):
    """The breaker as a dictionary. A file that is missing, cannot be examined or read in its form, or says tripped reads as `"tripped": true`."""
    record, why = _read_breaker(index_root)
    if record is None:
        return {"tripped": True, "reason": why, "kind": "", "at": "", "run": ""}
    return record


def _write_breaker(index_root, tripped, reason, kind, run, now=None):
    """Write the breaker whole or not at all, in the form of the plan's interface; returns the record. **Private on purpose**: the only public ways to change the file are `trip` (to tripped) and `clear` (to not
    tripped, with `--yes` at a terminal), so that no step can make a tripped breaker good again (finding F5 of the security review)."""
    if not isinstance(tripped, bool):
        raise KbError("the breaker is tripped or not")
    if not isinstance(reason, str):
        raise KbError("the breaker's reason is text")
    if not isinstance(kind, str) or (kind and kind not in KINDS):
        raise KbError("the breaker's kind is one of " + ", ".join(KINDS))
    if not isinstance(run, str) or (run and not _RUN.fullmatch(run)):
        raise KbError("the breaker's run name is 1 to 64 letters, digits or . _ : -")
    record = {"tripped": tripped, "reason": textutil.clean(reason, REASON_MAX), "kind": kind, "at": _stamp(now if now is not None else _utc_now()), "run": run}
    _atomic_write(_crawl_dir(index_root), "breaker.json", (json.dumps(record, sort_keys=True) + "\n").encode("ascii"))
    return record


def trip(index_root, kind, reason, run, now=None, log=None, secrets=()):
    """Trip the breaker. While it is tripped, the first cause stands. With a `crawllog.Log`, the trip is logged and the reason is screened with that log's secrets; without one, with `secrets`. Returns the record that
    stands."""
    if kind not in KINDS:
        raise KbError("the breaker's kind is one of " + ", ".join(KINDS))
    record, _why = _read_breaker(index_root)
    if record is not None and record["tripped"]:
        return record
    now = now if now is not None else _utc_now()
    try:                                  # a reason that looks like a credential is not kept: the trip is what matters
        screened = (log if log is not None else crawllog.Log(index_root, "screen", secrets=secrets))._text(reason, "reason") or ""
    except KbError:
        screened = WITHHELD
    record = _write_breaker(index_root, True, screened, kind, run, now=now)
    if log is not None:
        try:
            log.write("breaker", "tripped", reason=record["reason"], now=now)
        except KbError:                   # the breaker is tripped whatever the log says; the log line is made without the text
            log.write("breaker", "tripped", reason=WITHHELD, now=now)
    return record


def clear(index_root, yes, is_tty=None, now=None, run=None):
    """`crawl-clear`: with `yes` and at a terminal, log the clear and write the breaker as not tripped. It changes nothing otherwise, and the refusal says why. The log is written first, so a log that cannot be
    written leaves the breaker as it was. The stop file and the sites stopped for the day are not touched."""
    if not yes:
        raise KbError("crawl-clear changes nothing without --yes: run it as `crawl-clear --yes` in your own terminal to clear the circuit breaker")
    if not (is_tty or is_terminal)():
        raise KbError("crawl-clear --yes takes the owner's word from a terminal and this is not one: run it in your own terminal (it is an interlock, not proof that a person typed)")
    now = now if now is not None else _utc_now()
    name = run if run is not None else crawllog.new_run_id(now)
    crawllog.Log(index_root, name).write("breaker", "ok", reason="cleared by the owner", now=now)
    save_state(index_root, fresh_state())     # a clear is a fresh start: the first failure after it must not trip the breaker again at once
    return _write_breaker(index_root, False, "", "", "", now=now)


# ---- the rules that trip it

def fresh_state():
    """The guard state of a library that has none: no sighting of the model server down and no history."""
    return {"model_down_since": None, "history": []}


def _parsed(text):
    """A stored time as an aware datetime, or `None` if it is not a real time of the form."""
    if not isinstance(text, str) or not _TS.fullmatch(text):
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _valid_state(state):
    return (isinstance(state, dict) and sorted(state) == ["history", "model_down_since"]
            and (state["model_down_since"] is None or _parsed(state["model_down_since"]) is not None)
            and isinstance(state["history"], list) and len(state["history"]) <= MAX_HISTORY and all(isinstance(x, bool) for x in state["history"]))


def load_state(index_root):
    """`(state, restarted)`: the state kept in `crawl/guard.json`. No file is a fresh state; a file that cannot be read (a link, loose, not in the form) is a fresh state with `restarted` true, so the caller says
    that the clock was restarted."""
    try:
        state = _json_object(_read_small(os.path.join(os.fspath(index_root), "crawl", "guard.json")))
    except _Unreadable as e:
        return fresh_state(), not e.missing
    if not _valid_state(state):
        return fresh_state(), True
    return {"model_down_since": state["model_down_since"], "history": list(state["history"])}, False


def save_state(index_root, state):
    """Write the guard state whole or not at all."""
    if not _valid_state(state):
        raise KbError("the guard state is not in its form")
    _atomic_write(_crawl_dir(index_root), "guard.json", (json.dumps(state, sort_keys=True) + "\n").encode("ascii"))


def record_fetch(state, ok, plan):
    """Note one fetch (`ok` or not) in `state["history"]` and return `None` or the trip `(kind, reason)`: `consecutive_failures` failures in a row, or, once the last `window` fetches are all known, a share of
    failures of `failure_share` or more."""
    if not isinstance(ok, bool):
        raise KbError("a fetch succeeded or it did not")
    history = state["history"]
    history.append(ok)
    keep = max(plan["window"], plan["consecutive_failures"])
    del history[:-keep]
    run = 0
    for item in reversed(history):
        if item:
            break
        run += 1
    if run >= plan["consecutive_failures"]:
        return "consecutive_failures", f"{run} fetches in a row failed"
    recent = history[-plan["window"]:]
    failed = recent.count(False)
    if len(recent) == plan["window"] and failed / plan["window"] >= plan["failure_share"]:
        return "failure_share", f"{failed} of the last {plan['window']} fetches failed"
    return None


def note_model(state, ok, now, plan):
    """Note one probe of the model server: `None`, or the trip `(kind, reason)` once it has been down for longer than `model_down_minutes`, counted from the first probe that failed."""
    stamp = _stamp(now)
    if not isinstance(ok, bool):
        raise KbError("a probe of the model server succeeded or it did not")
    if ok:
        state["model_down_since"] = None
        return None
    began = _parsed(state["model_down_since"]) if state["model_down_since"] is not None else None
    if began is None or began > now:          # no sighting yet, one that is not a real time, or one in the future: the clock starts now
        state["model_down_since"] = stamp
        return None
    if (now - began).total_seconds() > plan["model_down_minutes"] * 60:
        return "model_down", f"the model server has not answered for over {plan['model_down_minutes']} minutes"
    return None


def bound_trip(stage, what):
    """The trip of a stage that hit a bound: `("stage_bound", reason)`."""
    if not isinstance(stage, str) or not isinstance(what, str) or not textutil.clean(stage, 40) or not textutil.clean(what, 200):
        raise KbError("a stage that hit a bound is named and says which bound")
    return "stage_bound", textutil.clean(f"the {textutil.clean(stage, 40)} stage hit a bound: {textutil.clean(what, 200)}", REASON_MAX)


# ---- a site stopped for the day

def refusals_today(conn, plan, now):
    """`{site: refusals}` for the plan's day of `now`, read from the `refusal:<site>` counters; reads and changes nothing."""
    day = crawlplan.day_of(now, plan["timezone"])
    found = {}
    for key, n in conn.execute("SELECT key, n FROM counters WHERE day = ? AND substr(key, 1, 8) = 'refusal:'", (day,)).fetchall():
        site = key[8:]
        if site and isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            found[site] = n
    return found


def site_stopped(refusals, site, plan):
    """Whether `site` has reached `domain_refusals` refusals today. It is that site alone; nothing is written, and the stop ends with the day."""
    if not isinstance(refusals, dict) or not isinstance(site, str):
        return True                           # what is not a table of sites or a site is not let through
    return refusals.get(site, 0) >= plan["domain_refusals"]


# ---- the disk floors

def check_disk(bulk_root, index_root, plan, statvfs=os.statvfs):
    """Refuse (`KbError`) when the space a normal user can use on the bulk drive or the index drive is at or under its floor, or cannot be read."""
    problems = []
    for label, path, floor_gb in (("bulk", bulk_root, plan["bulk_floor_gb"]), ("index", index_root, plan["index_floor_gb"])):
        try:
            reading = statvfs(path)
            avail, size = reading.f_bavail, reading.f_frsize
        except (OSError, AttributeError):
            problems.append(f"the free space of the {label} drive cannot be read")
            continue
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (avail, size)) or avail < 0 or size <= 0:
            problems.append(f"the free space of the {label} drive cannot be read")
            continue
        free = avail * size
        if free <= floor_gb * GB:
            problems.append(f"the {label} drive has {free / GB:.1f} GB free, at or under its floor of {floor_gb} GB")
    if problems:
        raise KbError("; ".join(problems))


# ---- the model probe

def probe_model(cfg, embed=None):
    """One call of the engine's `embed` on one short text; true when vectors come back. A refusal or an error of the connection is a server that does not answer."""
    try:
        name = cfg["tasks"]["card-embed"]
    except (TypeError, KeyError):
        return False
    if not isinstance(name, str) or not name:
        return False
    if embed is None:
        from . import models
        embed = models.embed
    try:
        reply = embed(cfg, name, [PROBE_TEXT])
    except (KbError, OSError):
        return False
    vectors = reply.get("vectors") if isinstance(reply, dict) else None
    return isinstance(vectors, list) and bool(vectors) and isinstance(vectors[0], list) and bool(vectors[0])
