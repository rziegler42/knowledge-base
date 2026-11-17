"""The skeleton of a crawl run (`docs/specs/population.md`, "Filing and placement", the order of one run; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment F).

`run(cfg)` is `crawl-run`. It takes no plan argument: the plan is the approved one (`crawlapprove.load_approved`). It makes **the spec's checks in order** and any failure ends the run with one `refuse` log line and an exit code:

1. the run lock (held by another run: exit 0, nothing printed, one `refuse` line that says `a run is in progress`);
2. the approved plan, its digest and the behaviour fingerprint, and a judgement `threshold` (exit 3); and, first, **the interpreter's bytecode folder**: the tree's own `__pycache__` is not in the fingerprint, so the run
   refuses unless Python was started with `-X pycache_prefix=<a private folder of the owner's outside the engine's code>` (`prefix_problem`);
3. the stop file (3); 4. the breaker (4); 5. the disk floors (3);
6. the ceilings (not a refusal: an exhausted ceiling only limits new fetches, which the run says in the log);
7. the model server (a failure is a refusal, 3, and counts toward `model_down_minutes`; once the server has been down longer than that, the breaker trips and the run exits 4).

A run that passes logs `run_start`, then calls, in the order of the spec's steps, the **points** where the later plan attaches its steps (`lists`, `earlier_work`, `refill`, `fetch`). At each point `attach_point` looks at the stop file (a
stop ends the run at that point, with exit 0 and a `stop` line) and then calls the step registered for it, if any. A run ends with `run_end` and exits 0 (done), or 4 if a step trips the breaker. Nothing else is done yet:
no fetch and no change to a candidate row (rows are changed only through `crawlstate`, which a step uses). The one request a passing run makes is the probe of the model server (one short embedding), check 7.

`--dry-run` takes no lock and writes nothing (no log line, row, counter or state file), makes no request and does not probe the model server: it prints each check and its result in order, what a real run would do next and the
exit code a real run would have if the checks it cannot make (the lock, the model server, the state files) also pass. A log that cannot be written ends a run with a `KbError`, and the lock is always let go."""
import datetime
import os
import sqlite3
import stat
import sys
from types import SimpleNamespace

from . import KbError, crawlapprove, crawlguard, crawllog, crawlqueue, crawlstate

CHECKS = ("lock", "approved", "stop", "breaker", "disk", "ceilings", "model")
POINTS = ("lists", "earlier_work", "refill", "fetch")
EXIT_DONE, EXIT_REFUSED, EXIT_BREAKER = 0, 3, 4
WORDS = {EXIT_DONE: "0 (done)", EXIT_REFUSED: "3 (refused)", EXIT_BREAKER: "4 (the circuit breaker is tripped)"}
LABELS = {"lock": "the run lock", "approved": "the approved plan", "stop": "the stop file", "breaker": "the circuit breaker", "disk": "the disk floors",
          "ceilings": "the ceilings", "model": "the model server"}


class BreakerTripped(Exception):
    """Raised by a step that has tripped the breaker: the run ends with exit 4."""


class _Refuse(Exception):
    def __init__(self, code, reason, check, shown=False):
        super().__init__(reason)
        self.code, self.reason, self.check, self.shown = code, reason, check, shown


_FROM_SYS = object()


def _kb_root(kb_root):
    return kb_root or os.path.dirname(os.path.abspath(crawlapprove.__file__))


def prefix_problem(prefix, kb_root=None):
    """Why the interpreter's bytecode folder cannot be trusted, or `None` if it can. The tree's own `__pycache__` is not in the fingerprint, so a run must read its bytecode from a private folder of the owner's
    that is outside the engine's code (`python3 -X pycache_prefix=<folder>`), or not run (finding F1 of the security review of plan R1). **This is a tripwire and not the defence:** by the time `crawl-run` makes
    the check, Python has already imported the modules that make it, from wherever its bytecode folder pointed. What keeps planted bytecode from running is the command line that starts the process (the scheduler's
    text, which a later increment prints); the check refuses a run that was started without it."""
    if isinstance(prefix, str) and prefix.strip() and not os.path.isabs(prefix):
        return "the bytecode folder (pycache_prefix) must be given as a full path, not a relative one"
    if not isinstance(prefix, str) or not prefix.strip():
        return "the engine is not running with a private bytecode folder: start it as python3 -X pycache_prefix=<a private empty folder> -m kb crawl-run"
    try:
        info = os.lstat(prefix)
    except OSError:
        return "the bytecode folder (pycache_prefix) cannot be examined"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        return "the bytecode folder (pycache_prefix) must be a folder of yours that only you can use (mode 700), and not a link"
    folder, tree = os.path.realpath(prefix), os.path.realpath(_kb_root(kb_root))
    if folder == tree or folder.startswith(tree + os.sep) or tree.startswith(folder + os.sep):
        return "the bytecode folder (pycache_prefix) must be outside the engine's code and not hold it"
    return None


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def attach_point(ctx, name):
    """The point where a step attaches: look at the stop file, then call the step registered for `name`. Returns false when the stop file ended the run here."""
    if crawlguard.stop_requested(ctx.index_root):
        ctx.log.write("stop", "refused", reason=f"the stop file is present at {name}", now=ctx.clock())
        return False
    ctx.log.write("stop", "skipped", reason=f"no stop file at {name}", now=ctx.clock())
    step = ctx.steps.get(name)
    if step is not None:
        try:
            step(ctx)
        except BreakerTripped:
            if not _breaker_file_tripped(ctx.index_root):          # the step ended the run for a bound it hit and did not write it down (or wrote it and made the file good again): the runner does
                try:
                    ctx.trip("stage_bound", f"a step at {name} ended the run for a bound it hit")
                except KbError:
                    pass                                           # the run still ends with exit 4, and the next run reads what was written, or a file that reads as tripped
            raise
        if ctx.tripped or _breaker_file_tripped(ctx.index_root):   # a step that tripped the breaker and went on does not carry the run past it, and one that made the file good again does not either
            raise BreakerTripped()
    return True


def _breaker_file_tripped(index_root):
    return crawlguard.read_breaker(index_root)["tripped"]


def _check_plan(approved):
    plan = approved["plan"]
    if plan["threshold"] is None:
        raise _Refuse(EXIT_REFUSED, "the plan has no judgement threshold: set it under [judge] and approve again", "approved")
    return plan


def _fetch_ceiling(used_limit):
    used, limit = used_limit
    return used >= limit


def run(cfg, dry_run=False, now=None, say=print, warn=None, kb_root=None, statvfs=os.statvfs, probe=None, steps=None, pycache_prefix=_FROM_SYS, secrets=()):
    """Make a run. Returns the exit code: 0 done (or the run lock held by another run), 3 refused, 4 the breaker is tripped. `now` fixes the clock (tests); `say` and `warn` print to the output and the error stream;
    `steps` maps a point name to a function that gets a context (`run`, `index_root`, `cfg`, `plan`, `log`, `clock`, `conn`, `steps`, `secrets`, `tripped`, and `trip(kind, reason)`, the one way a step trips the breaker). `pycache_prefix` is the interpreter's bytecode folder (`sys.pycache_prefix`, read when it is not given). `secrets` are values (the key a run loaded) that no log line, breaker reason or step may hold."""
    prefix = sys.pycache_prefix if pycache_prefix is _FROM_SYS else pycache_prefix
    steps = dict(steps or {})
    unknown = sorted(set(steps) - set(POINTS))
    if unknown:
        raise KbError("a step attaches at one of: " + ", ".join(POINTS))
    warn = warn or (lambda text: print(text, file=sys.stderr))
    probe = probe or crawlguard.probe_model
    clock = (lambda: now) if now is not None else _utc_now
    index_root, bulk_root = cfg["index_root"], cfg["bulk_root"]
    if dry_run:
        return _dry_run(cfg, clock(), say, kb_root, statvfs, prefix)
    started = clock()
    log = crawllog.Log(index_root, crawllog.new_run_id(started), secrets=secrets, clock=clock)
    lock = None
    try:
        try:
            lock = crawlguard.acquire_run_lock(index_root, now=started)
        except KbError as e:
            return _refused(log, clock, warn, _Refuse(EXIT_REFUSED, "the run lock cannot be used: " + str(e), "lock"))
        if lock is None:
            log.write("refuse", "held", reason="a run is in progress", now=clock())
            return EXIT_DONE
        try:
            plan, conn = _checks(cfg, index_root, bulk_root, log, clock, kb_root, statvfs, probe, prefix)
        except _Refuse as r:
            return _refused(log, clock, warn, r)
        try:
            return _steps(cfg, index_root, plan, conn, log, clock, steps, secrets)
        finally:
            conn.close()
    finally:
        if lock is not None:
            lock.release()


def _refused(log, clock, warn, refusal):
    log.write("refuse", "refused", reason=refusal.reason, now=clock())
    warn(f"refused: {refusal.reason}")
    return refusal.code


def _checks(cfg, index_root, bulk_root, log, clock, kb_root, statvfs, probe, prefix):
    """Checks 2 to 7. Returns the approved plan and an open connection to the queue; raises `_Refuse` at the first that fails. The bytecode folder is part of the second: the code that is approved is only the
    code that runs if no planted bytecode can be read."""
    problem = prefix_problem(prefix, kb_root)
    if problem:
        raise _Refuse(EXIT_REFUSED, problem, "approved")
    try:
        approved = crawlapprove.load_approved(index_root, cfg, kb_root=kb_root)
    except crawlapprove.NotApproved as e:
        raise _Refuse(EXIT_REFUSED, str(e), "approved") from None
    except KbError:
        raise _Refuse(EXIT_REFUSED, "the approval cannot be read: approve again", "approved") from None
    plan = _check_plan(approved)
    if crawlguard.stop_requested(index_root):
        raise _Refuse(EXIT_REFUSED, "the stop file is present", "stop")
    breaker = crawlguard.read_breaker(index_root)
    if breaker["tripped"]:
        raise _Refuse(EXIT_BREAKER, "the circuit breaker is tripped" + (f": {breaker['reason']}" if breaker["reason"] else ""), "breaker")
    try:
        crawlguard.check_disk(bulk_root, index_root, plan, statvfs=statvfs)
    except KbError as e:
        raise _Refuse(EXIT_REFUSED, str(e), "disk") from None
    try:
        conn = crawlqueue.connect(index_root)
    except (KbError, sqlite3.Error):
        raise _Refuse(EXIT_REFUSED, "the candidate queue cannot be opened, or it is not this engine's queue", "ceilings") from None
    try:
        run_started = clock()
        try:
            used = crawlstate.ceilings(conn, plan, run_started)
        except (KbError, sqlite3.Error):
            raise _Refuse(EXIT_REFUSED, "the ceilings cannot be read", "ceilings") from None
        state, restarted = crawlguard.load_state(index_root)
        if restarted:
            log.write("breaker", "skipped", reason="the guard state could not be read: the model server's down clock restarts", now=clock())
        _model(cfg, index_root, plan, state, log, clock, probe)
        log.write("run_start", "ok", reason=f"plan {approved['digest'][:12]}", n=plan["batch"], now=run_started)
        if _fetch_ceiling(used["fetch"]):
            log.write("fetch", "skipped", reason=f"fetches_per_day reached ({used['fetch'][0]} of {used['fetch'][1]}): no new candidates", now=clock())
    except BaseException:
        conn.close()
        raise
    return plan, conn


def _model(cfg, index_root, plan, state, log, clock, probe):
    answered = bool(probe(cfg))
    tripped = crawlguard.note_model(state, answered, clock(), plan)
    try:
        crawlguard.save_state(index_root, state)
        if tripped is not None:
            kind, reason = tripped
            crawlguard.trip(index_root, kind, reason, log.run, now=clock(), log=log)
    except KbError:
        raise _Refuse(EXIT_REFUSED, "the guard state or the circuit breaker cannot be written", "model") from None
    if tripped is not None:
        raise _Refuse(EXIT_BREAKER, "the circuit breaker is tripped: " + tripped[1], "model")
    if not answered:
        raise _Refuse(EXIT_REFUSED, "the model server does not answer, or the model settings are off", "model")


def _steps(cfg, index_root, plan, conn, log, clock, steps, secrets=()):
    ctx = SimpleNamespace(cfg=cfg, index_root=index_root, plan=plan, conn=conn, log=log, run=log.run, clock=clock, steps=steps, secrets=tuple(secrets), tripped=False)

    def trip(kind, reason):
        """Trip the breaker for this run (the only way a step does): the run remembers it, whatever happens to the file afterwards."""
        ctx.tripped = True                      # remembered before the write: a trip that fails half way is still a trip
        return crawlguard.trip(index_root, kind, reason, log.run, now=clock(), log=log)

    ctx.trip = trip
    code, reason = EXIT_DONE, "done"
    try:
        for name in POINTS:
            if not attach_point(ctx, name):
                reason = f"stopped by the stop file at {name}"
                break
    except BreakerTripped:
        code, reason = EXIT_BREAKER, "the circuit breaker was tripped"
    except Exception:
        if ctx.tripped:                                            # a step that tripped the breaker and then failed: the run ends as a tripped one, with no text of the failure
            log.write("run_end", "tripped", reason="a step failed after the circuit breaker was tripped", now=clock())
            return EXIT_BREAKER
        log.write("run_end", "failed", reason="a step failed", now=clock())
        raise
    log.write("run_end", "tripped" if code == EXIT_BREAKER else "ok", reason=reason, now=clock())
    return code


# ---- --dry-run

def _dry_run(cfg, now, say, kb_root, statvfs, prefix):
    """Print each check, its result, what a real run would do next and its exit code in words; change nothing and make no request."""
    index_root, bulk_root = cfg["index_root"], cfg["bulk_root"]
    plan = None
    outcome = None                       # (code, reason) of the first check that would refuse

    def show(check, text):
        say(f"{LABELS[check]}: {text}")

    for check in CHECKS:
        if outcome is not None:
            show(check, "not reached")
            continue
        try:
            if check == "lock":
                show(check, "not taken in a dry run (a real run takes it, and exits quietly if another run holds it)")
            elif check == "approved":
                problem = prefix_problem(prefix, kb_root)
                if problem:
                    say(f"the bytecode folder: would refuse: {problem}")
                    raise _Refuse(EXIT_REFUSED, problem, check, shown=True)
                say("the bytecode folder: private, and outside the engine's code")
                plan = _check_plan(_dry_approved(cfg, index_root, kb_root, show))
            elif check == "stop":
                if crawlguard.stop_requested(index_root):
                    raise _Refuse(EXIT_REFUSED, "the stop file is present", check)
                show(check, "none")
            elif check == "breaker":
                breaker = crawlguard.read_breaker(index_root)
                if breaker["tripped"]:
                    raise _Refuse(EXIT_BREAKER, "the circuit breaker is tripped" + (f": {breaker['reason']}" if breaker["reason"] else ""), check)
                show(check, "not tripped")
            elif check == "disk":
                try:
                    crawlguard.check_disk(bulk_root, index_root, plan, statvfs=statvfs)
                except KbError as e:
                    raise _Refuse(EXIT_REFUSED, str(e), check) from None
                show(check, "over their floors")
            elif check == "ceilings":
                show(check, _dry_ceilings(index_root, plan, now))
            else:
                show(check, "a real run would ask it to answer one short embedding (not asked in a dry run)")
        except _Refuse as r:
            outcome = (r.code, r.reason)
            if not r.shown:
                show(check, f"would refuse: {r.reason}")
    if outcome is None:
        say("then a real run would: " + "; ".join(name.replace("_", " ") for name in POINTS) + f" (the steps that attach there are not built yet), at each looking at the stop file, with up to {plan['batch']} new candidates")
    code, reason = outcome if outcome is not None else (EXIT_DONE, "")
    say(f"a real run would exit {WORDS[code]}" + (f": {reason}" if reason else "") + ("" if outcome is not None else ", if the checks a dry run cannot make (the lock, the model server, the state files) also pass"))
    return EXIT_DONE


def _dry_approved(cfg, index_root, kb_root, show):
    try:
        approved = crawlapprove.load_approved(index_root, cfg, kb_root=kb_root)
    except crawlapprove.NotApproved as e:
        raise _Refuse(EXIT_REFUSED, str(e), "approved") from None
    plan = approved["plan"]
    show("approved", f"plan {approved['digest'][:12]}, judgement threshold " + ("not set" if plan["threshold"] is None else str(plan["threshold"])))
    return approved


def _dry_ceilings(index_root, plan, now):
    path = os.path.join(index_root, crawlqueue.FILE)
    if not os.path.exists(path):
        return f"no candidate queue yet: 0 of {plan['fetches_per_day']} fetches today"
    try:
        # With no write-ahead file beside it nobody is writing, and an immutable open does not make the `-wal` and `-shm` files that a plain read-only open leaves behind; with one, a plain read-only open sees what is in it.
        mode = "mode=ro" if os.path.exists(path + "-wal") else "mode=ro&immutable=1"
        conn = sqlite3.connect(f"file:{path}?{mode}", uri=True, timeout=30)
    except sqlite3.Error as e:
        raise _Refuse(EXIT_REFUSED, f"the candidate queue cannot be read ({e})", "ceilings") from None
    try:
        used, limit = crawlstate.ceilings(conn, plan, now)["fetch"]
    except sqlite3.Error as e:
        raise _Refuse(EXIT_REFUSED, f"the candidate queue cannot be read ({e})", "ceilings") from None
    finally:
        conn.close()
    return f"{used} of {limit} fetches today" + (": exhausted, so no new candidates would be fetched (the run goes on)" if used >= limit else "")
