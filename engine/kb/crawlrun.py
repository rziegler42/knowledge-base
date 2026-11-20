"""The skeleton of a crawl run (`docs/specs/population.md`, "Filing and placement", the order of one run; the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl`, Increment F).

`run(cfg)` is `crawl-run`. It takes no plan argument: the plan is the approved one (`crawlapprove.load_approved`). It makes **the spec's checks in order** and any failure ends the run with one `refuse` log line and an exit code:

1. the run lock (held by another run: exit 0, nothing printed, one `refuse` line that says `a run is in progress`);
2. the approved plan, its digest and the behaviour fingerprint, and a judgement `threshold` (exit 3); and, first, **the interpreter's bytecode folder**: the tree's own `__pycache__` is not in the fingerprint, so the run
   refuses unless Python was started with `-X pycache_prefix=<a private folder of the owner's outside the engine's code>` (`prefix_problem`);
3. the stop file (3); 4. the breaker (4); 5. the disk floors (3);
6. the ceilings (not a refusal: an exhausted ceiling only limits new fetches, which the run says in the log);
7. the model server (the card embedding must answer one short embedding: a failure is a refusal, 3, and counts toward `model_down_minutes`; and each model entry that an earlier run found down is asked one short call: once the
   server, or an entry, has been down longer than that, the breaker trips and the run exits 4).

A run that passes logs `run_start`, then calls, in the order of the spec's steps, the **points** where the later plan attaches its steps (`lists`, `earlier_work`, `refill`, `fetch`, and last `idle`, the window that makes themes, which `crawlidle` guards). At each point `attach_point` looks at the stop file (a
stop ends the run at that point, with exit 0 and a `stop` line) and then calls the step registered for it, if any. A run ends with `run_end` and exits 0 (done), or 4 if a step trips the breaker. Nothing else is done yet:
no fetch and no change to a candidate row (rows are changed only through `crawlstate`, which a step uses). The requests a passing run makes are the probe of the model server (one short embedding) and one short call for each model entry that an earlier run found down, check 7.

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
POINTS = ("lists", "earlier_work", "refill", "fetch", "idle")
RUN_SECONDS = 3600                     # the time budget of one run: when it is spent, no step is begun and no book is begun in the scan, the convert, the judge and the fetch (a book that is going is finished), and the run ends at the next point; the card queue's pass and the move are not cut (see their steps)
EXIT_DONE, EXIT_REFUSED, EXIT_BREAKER = 0, 3, 4
WORDS = {EXIT_DONE: "0 (done)", EXIT_REFUSED: "3 (refused)", EXIT_BREAKER: "4 (the circuit breaker is tripped)"}
LABELS = {"lock": "the run lock", "approved": "the approved plan", "stop": "the stop file", "breaker": "the circuit breaker", "disk": "the disk floors",
          "ceilings": "the ceilings", "model": "the model server"}


class BreakerTripped(Exception):
    """Raised by a step that has tripped the breaker: the run ends with exit 4."""


class StepRefused(Exception):
    """Raised by a step that cannot let the run go on (a required list with no copy, a blacklist that cannot be read): the run ends with exit 3, one `refuse` line and the reason, which is cleaned and, if it looks
    like a credential, withheld. Nothing is tripped: the next run tries again."""


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


def spent(ctx):
    """True when the run's time budget is spent (`ctx.deadline`, set when the steps begin; a context with none has no budget)."""
    deadline = getattr(ctx, "deadline", None)
    return deadline is not None and ctx.clock() >= deadline


def attach_point(ctx, name):
    """The point where a step attaches: look at the stop file and at the time budget, then call the step registered for `name`. Returns false when the stop file or the budget ended the run here (`ctx.ended_by` says which)."""
    if crawlguard.stop_requested(ctx.index_root):
        ctx.ended_by = "the stop file"
        ctx.log.write("stop", "refused", reason=f"the stop file is present at {name}", now=ctx.clock())
        return False
    if spent(ctx):
        ctx.ended_by = "the time budget"
        ctx.log.write("stop", "refused", reason=f"the time budget of the run is spent at {name}", now=ctx.clock())
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


def run(cfg, dry_run=False, now=None, say=print, warn=None, kb_root=None, statvfs=os.statvfs, probe=None, steps=None, pycache_prefix=_FROM_SYS, secrets=(), entry_probe=None):
    """Make a run. Returns the exit code: 0 done (or the run lock held by another run), 3 refused, 4 the breaker is tripped. `now` fixes the clock (tests); `say` and `warn` print to the output and the error stream;
    `steps` maps a point name to a function that gets a context (`run`, `index_root`, `cfg`, `plan`, `log`, `clock`, `conn`, `steps`, `secrets`, `tripped`, `plan_digest` (the digest of the approved plan, which a step writes into a book it files), `matcher` and `suffixes` (the lists step sets them for the steps after it), and `trip(kind, reason)`, the one way a step trips the breaker). A step that cannot let the run go on raises `StepRefused`. `pycache_prefix` is the interpreter's bytecode folder (`sys.pycache_prefix`, read when it is not given). `entry_probe(cfg, task)` asks one model entry whether it answers (`crawlguard.probe_entry`), for the entries an earlier run found down. `secrets` are values (the key a run loaded) that no log line, breaker reason or step may hold."""
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
    problem = crawlguard.index_root_problem(index_root)
    if problem:                          # before the lock and the log: nothing is written into a folder that cannot be trusted
        warn(f"refused: {problem}")
        return EXIT_REFUSED
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
            plan, conn, digest = _checks(cfg, index_root, bulk_root, log, clock, kb_root, statvfs, probe, prefix, entry_probe)
        except _Refuse as r:
            return _refused(log, clock, warn, r)
        try:
            return _steps(cfg, index_root, plan, conn, log, clock, steps, secrets, warn, digest)
        finally:
            conn.close()
    finally:
        if lock is not None:
            lock.release()


def _refused(log, clock, warn, refusal):
    log.write("refuse", "refused", reason=refusal.reason, now=clock())
    warn(f"refused: {refusal.reason}")
    return refusal.code


def _checks(cfg, index_root, bulk_root, log, clock, kb_root, statvfs, probe, prefix, entry_probe=None):
    """Checks 2 to 7. Returns the approved plan, an open connection to the queue and the plan's digest; raises `_Refuse` at the first that fails. The bytecode folder is part of the second: the code that is approved is only the
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
            log.write("breaker", "skipped", reason="the guard state could not be read: the model clocks restart", now=clock())
        _model(cfg, index_root, plan, state, log, clock, probe, entry_probe)
        log.write("run_start", "ok", reason=f"plan {approved['digest'][:12]}", n=plan["batch"], now=run_started)
        if _fetch_ceiling(used["fetch"]):
            log.write("fetch", "skipped", reason=f"fetches_per_day reached ({used['fetch'][0]} of {used['fetch'][1]}): no new candidates", now=clock())
    except BaseException:
        conn.close()
        raise
    return plan, conn, approved["digest"]


def _task_of(cfg, entry):
    """The first task of the engine that the config sets to the entry named `entry`, or `None` when none does (the entry was renamed or removed)."""
    from . import models
    for task in models.TASKS + models.EMBED_TASKS:
        try:
            if crawlguard.entry_of(cfg, task) == entry:
                return task
        except KbError:
            continue
    return None


def _entries(cfg, plan, state, log, clock, entry_probe, index_root):
    """Ask each model entry that an earlier run found down (`state["entries_down"]`, in the order of their names), each by the first task that names it: an entry that answers has its clock cleared; one that does not
    keeps the time it was first seen down and, once that is over `model_down_minutes`, is the trip `(kind, reason)` that is returned; an entry that the config no longer names has its clock dropped, with a line.
    **The asking ends at the first trip and at the stop file** (looked at before each probe): the entries not asked keep their clocks as they were, which is harmless, and the wait is bounded by the entries asked
    (each by its own timeout, 600 seconds by default) and not by all of them."""
    tripped = None
    for entry in sorted(state["entries_down"]):
        if tripped is not None or crawlguard.stop_requested(index_root):
            break
        task = _task_of(cfg, entry)
        if task is None:
            del state["entries_down"][entry]
            log.write("breaker", "skipped", reason=f"the model entry {entry} is not named in the config any more: its clock is dropped", now=clock())
            continue
        since = state["entries_down"][entry]
        answered = bool((entry_probe or crawlguard.probe_entry)(cfg, task))
        trip = crawlguard.note_entry(state, entry, answered, clock(), plan)
        if answered:
            log.write("breaker", "ok", reason=f"the model entry {entry} answers again", now=clock())
        else:
            log.write("breaker", "failed", reason=f"the model entry {entry} has not answered since {since}", now=clock())
        tripped = trip
    return tripped


def _model(cfg, index_root, plan, state, log, clock, probe, entry_probe=None):
    """Check 7: the card embedding answers one short embedding (refused otherwise: exit 3, and its down clock counts toward `model_down_minutes`), and **each entry that an earlier run found down is asked too**, so
    that a model that fails alone (a chat model) is followed from run to run until it answers or has been down for over `model_down_minutes`. The entries are not asked when the card embedding does not answer: the
    server is then down for all of them, and a chat probe of a server that is down can wait as long as its timeout."""
    answered = bool(probe(cfg))
    tripped = crawlguard.note_model(state, answered, clock(), plan)
    if answered:
        tripped = _entries(cfg, plan, state, log, clock, entry_probe, index_root)        # (an answer cleared the card embedding's clock: there is no trip of it to keep)
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


def _steps(cfg, index_root, plan, conn, log, clock, steps, secrets=(), warn=None, digest=None):
    ctx = SimpleNamespace(cfg=cfg, index_root=index_root, plan=plan, conn=conn, log=log, run=log.run, clock=clock, steps=steps, secrets=tuple(secrets), tripped=False, matcher=None, suffixes=None, plan_digest=digest,
                          deadline=clock() + datetime.timedelta(seconds=RUN_SECONDS), ended_by=None)

    def trip(kind, reason):
        """Trip the breaker for this run (the only way a step does): the run remembers it, whatever happens to the file afterwards."""
        ctx.tripped = True                      # remembered before the write: a trip that fails half way is still a trip
        return crawlguard.trip(index_root, kind, reason, log.run, now=clock(), log=log)

    ctx.trip = trip
    code, reason = EXIT_DONE, "done"
    try:
        for name in POINTS:
            if not attach_point(ctx, name):
                reason = f"stopped by {ctx.ended_by} at {name}"
                break
    except BreakerTripped:
        code, reason = EXIT_BREAKER, "the circuit breaker was tripped"
    except StepRefused as refusal:
        shown = log.safe(str(refusal)) or "a step refused the run"
        log.write("refuse", "refused", reason=shown, now=clock())
        if warn is not None:
            warn(f"refused: {shown}")
        log.write("run_end", "refused", reason=shown, now=clock())
        return EXIT_REFUSED
    except Exception:
        if ctx.tripped:                                            # a step that tripped the breaker and then failed: the run ends as a tripped one, with no text of the failure
            log.write("run_end", "tripped", reason="a step failed after the circuit breaker was tripped", now=clock())
            return EXIT_BREAKER
        log.write("run_end", "failed", reason="a step failed", now=clock())
        raise
    log.write("run_end", "tripped" if code == EXIT_BREAKER else "ok", reason=reason, now=clock())
    return code


# ---- the assembly of the steps

def _requeue_stale(ctx):
    """The first of a run: the rows that have been `fetching` for over 30 minutes (a run that died) go back to the queue as a try, or are `failed` at `retries`. One line says how many, if any."""
    out = crawlstate.requeue_stale(ctx.conn, ctx.plan, ctx.clock())
    if out["requeued"] or out["failed"]:
        ctx.log.write("fail", "ok", reason=f"{out['requeued']} stalled rows queued again, {out['failed']} given up", n=out["requeued"] + out["failed"], now=ctx.clock())


def _reconcile(ctx):
    """The first of the earlier work: the books of a plan that is not approved are named (`crawl_unplaced`, once) and nothing else is done for them."""
    from . import crawlbooks, store
    digests = crawlbooks.approved_digests(ctx.index_root)
    if ctx.plan_digest not in digests:                   # an approved set that could not be read (it is empty then) must not make every crawl book terminal for good
        raise StepRefused("the approved plans cannot be read, or the plan of this run is not among them")
    crawlbooks.reconcile_unapproved(store.Store.open(), digests, ctx.log)


def default_steps(parts=None):
    """The registry of a real run, for `run(steps=...)`. In the spec's order: at `lists`, the stalled rows and then the lists (which make the matcher the later steps need); at `earlier_work`, the books of a plan that is
    not approved are named and then every unfinished crawl book is taken through the steps it has not finished: scan and hold, convert and index, judge, cards, proposal and move (each step takes the books oldest
    first, each looks at the stop file and the disk floors itself); at `refill`, discovery; at `fetch`, up to `batch` new candidates and then **the same chain again**, so that each new book goes through the steps in the
    same run. Between two steps of the chain the stop file and the time budget are looked at, and a step does not begin after either. The scan comes before the conversion in every pass. At `idle`, last, the window of `themes_window_s` seconds makes themes for the books that have none (`crawlidle`). `parts` replaces a
    step by name (`stale`, `lists`, `reconcile`, `scan`, `convert`, `judge`, `cards`, `move`, `refill`, `fetch`, `idle`: tests, with the steps given their own fakes); the steps are made when this is called and none is run."""
    from . import crawlcards, crawlfetch, crawlidle, crawllists, crawlmove, crawlrefill, crawlsteps
    given = dict(parts or {})
    unknown = sorted(set(given) - {"stale", "lists", "reconcile", "scan", "convert", "judge", "cards", "move", "refill", "fetch", "idle"})
    if unknown:
        raise KbError("a part of the assembly is one of: stale, lists, reconcile, scan, convert, judge, cards, move, refill, fetch, idle")

    def part(name, real):
        return given[name] if name in given else real

    chain = [("scan", part("scan", crawlsteps.step)), ("convert", part("convert", crawlsteps.convert_step)), ("judge", part("judge", crawlsteps.judge_step)),
             ("cards", part("cards", crawlcards.step)), ("move", part("move", crawlmove.step))]
    stale, lists, reconcile = part("stale", _requeue_stale), part("lists", crawllists.step), part("reconcile", _reconcile)
    refill, fetch = part("refill", crawlrefill.step), part("fetch", crawlfetch.step)
    idle = part("idle", crawlidle.step)

    def run_chain(ctx):
        for _name, step in chain:
            if crawlguard.stop_requested(ctx.index_root) or spent(ctx):
                return
            step(ctx)

    def first(ctx):
        stale(ctx)
        lists(ctx)

    def earlier_work(ctx):
        reconcile(ctx)
        run_chain(ctx)

    def new_books(ctx):
        fetch(ctx)
        run_chain(ctx)

    return {"lists": first, "earlier_work": earlier_work, "refill": refill, "fetch": new_books, "idle": idle}


def run_unattended(cfg, dry_run=False):
    """`crawl-run`: one run with the assembled steps (a dry run takes none: it makes no request and writes nothing)."""
    return run(cfg, dry_run=dry_run, steps=None if dry_run else default_steps())


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
                problem = crawlguard.index_root_problem(index_root)
                if problem:
                    raise _Refuse(EXIT_REFUSED, problem, check)
                show(check, "the index folder is yours and others cannot write it; the lock is not taken in a dry run (a real run takes it, and exits quietly if another run holds it)")
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
                show(check, "a real run would ask it to answer one short embedding, and each model entry that an earlier run found down (not asked in a dry run)")
        except _Refuse as r:
            outcome = (r.code, r.reason)
            if not r.shown:
                show(check, f"would refuse: {r.reason}")
    if outcome is None:
        say("then a real run would: requeue the stalled rows; refresh the lists; finish the earlier work (reconcile the books of a plan that is not approved; scan and hold; convert and index; judge; cards; proposal and move); "
            f"refill the queue; fetch up to {plan['batch']} new candidates and take each new book through the same steps; "
            + (f"then use up to {plan['themes_window_s']} seconds of an idle window "
               + (f"(up to {plan['themes_window_full_s']} seconds once the day's fetches are used up, never past the end of the day) " if plan["themes_window_full_s"] else "(the same length once the day's fetches are used up) ")
               + "to make themes, the vectors of the cards, the vectors of the themes and a repair of the weave; " if plan["themes_window_s"]
               else "then no idle window (themes_window_s is 0); ")
            + "at each point looking at the stop file and at the time budget")
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
