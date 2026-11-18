"""The `idle` step of the unattended crawl: themes in the time that is left after the fetch (`docs/specs/population.md`, "The idle window"; the plan
`2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave`, increment B).

After the fetch a run may spend `themes_window_s` seconds (the plan's `[idle]` section; 0 is off) making the themes of the books that have none, and **gives the
time back at a deadline**, so that the next run starts on time. What this step guards:

- **The window is the earlier of `themes_window_s` and what the run has left of its own time budget** (`ctx.deadline`). A run that was refused, stopped or tripped,
  or whose budget is spent, never reaches this point (`crawlrun.attach_point`).
- **A `stop` function is given to `themerun.run`** and says true when the stop file is there, when the deadline has come, or when a disk floor refuses; it is looked
  at before every book and before every model call, so a window ends at most one model call after its deadline. A book that is cut keeps the pieces it has answered
  (the run's journal) and is made the next time, with no try charged.
- **Which books.** The active books that have a card, a conversion in use and **no theme generation of any version at all**, oldest first, at most `BATCH` for
  each plan. A book that has themes of any prompt or model, or a generation with no themes, is not planned: a change of the prompt or the model is `themes-run`'s, run by
  the owner, and the window cannot spend its time on a whole library's themes. The test is `themerun._assess`, the one `themerun.plan` uses, after one cheap test, so
  that a library whose books all have themes costs a listing of generations and no conversion is loaded.
- **The card lock has one owner, `themerun.run`**, which takes it before any model call; this step takes none (a second holder, even in this process, is refused). A
  refusal of the lock ends the part with the reason `locked` and no model call, and the run that was planned stays for a later window.
- **A book that fails is not tried again in the same window.** `themerun.run` already tries it twice; a later batch leaves it out. Three books in a row that fail for a
  reason that is not a refused answer end the window, as they end `themes-run`.
- **A model that does not answer is not the book's fault.** After a run with a failed try the two model entries of the themes (`theme`, `theme-check`) are asked one
  short call each, in that order, the first that does not answer ends the asking, and its own down clock (`crawlguard.record_entry`) runs; once it has been down for
  `model_down_minutes` the breaker trips (`model_down`) and the run ends.

One `themes` line is written for each book that ended in the window (`ok`, or `failed` for a try that will be repeated), and one `idle` line for the window with the
seconds used, the number of books made and why it ended: `deadline`, `nothing to do`, `stopped`, `disk`, `locked`, `settings`, `off` or `failed`. Every line holds a fixed
sentence, a number or a book's id, never a word of a book or of a reply.

The module makes no request and reads no environment variable; `themerun` makes the calls through the configured entries."""
import datetime
import os

from . import KbError, crawlguard, crawlrun, theme, themeextract, themerun, themevectors
from . import store as library_store
from . import weave as library_weave

BATCH = 20                                    # books in one plan
TASKS = ("theme", "theme-check")              # the tasks whose entries the themes call, in the order they are asked
EMBED_TASKS = ("card-embed",)                 # the task whose entry the vectors call
THEMES_SHARE = 0.6                            # the part of the window that the themes may use while more books wait for them; the rest is for the vectors and the weave
EMBED_GROUP = 40                              # texts in one call to the embedding entry: about 19 seconds, so that a stop is looked at about that often (a call may hold 3,906)
SECONDS_A_TEXT, SECONDS_A_CALL, BUILD_OVERHEAD_S = 0.35, 5.0, 5.0   # measured on 2026-11-18: an embedding call of 5, 30 and 110 texts took 6.8, 20.9 and 44.4 seconds; the build reads and writes for about 5
MARGIN = 0.75                                 # the part of the time left that an estimate may use
MIN_BATCH = 20                                # fewer texts than this are not begun, when the time left is what limits the batch and more are waiting
LOCK_LOOK_S, LOCK_WRITE_S = 0.0, 5.0              # seconds to wait for the lock of the vector file: none to look at it, a few at the write (the catalog's wait is two minutes, in which no stop is looked at)
WEAVE_RESERVE_S = 30                          # the seconds kept for the repair of the weave, which takes a few (a full build took 5.2), and the least left for it
OFF, NOTHING, STOPPED, DEADLINE, DISK, LOCKED, SETTINGS, FAILED = "off", "nothing to do", "stopped", "deadline", "disk", "locked", "settings", "failed"
LOCK_REFUSED = "another run holds the lock of the queue"       # what `cardstate.lock` says to a second holder
_OUTCOME = {DEADLINE: "ok", NOTHING: "skipped", STOPPED: "skipped", DISK: "skipped", LOCKED: "skipped", SETTINGS: "skipped", OFF: "skipped", FAILED: "failed"}


def _eligible(library, cfg, index_root, leave_out):
    """The books to plan next: up to `BATCH`, oldest first, not in `leave_out`."""
    extraction = themerun._current(cfg)[2]
    records = themerun._earlier_records(index_root)
    chosen = []
    for book_id in sorted(library.list_books()):
        if book_id in leave_out:
            continue
        try:
            book = library.read_book(book_id)
            version_id = book.get("current_version")
            if book.get("state") != "active" or not version_id or any(theme.generations(library, book_id, v) for v in library.version_ids(book_id)):
                continue
            if themerun._assess(library, book_id, extraction, False, records)[0] != "make":
                continue
        except KbError:
            continue
        chosen.append(book_id)
        if len(chosen) >= BATCH:
            break
    return chosen


def _answers(ctx, probe, answered, tasks=TASKS):
    """Ask each distinct model entry of `tasks` (the themes' by default) one short call, in their order, and note each answer in the entry's own down clock (a trip of a clock ends the
    run). An entry that answered earlier in this step (`answered`) is not asked again. Returns `"ok"` when every entry answered, `"down"` at the first that did not, or the
    reason of a quiet end when the stop file or the time budget appeared between two probes."""
    asked = set(answered)
    for task in tasks:
        try:
            entry = crawlguard.entry_of(ctx.cfg, task)
        except KbError:
            continue
        if not entry or entry in asked:
            continue
        if asked:
            if crawlguard.stop_requested(ctx.index_root):
                return STOPPED
            if crawlrun.spent(ctx):
                return DEADLINE
        asked.add(entry)
        try:
            ok = bool((probe or crawlguard.probe_entry)(ctx.cfg, task))
        except (KbError, OSError):
            ok = False
        tripped = crawlguard.record_entry(ctx.index_root, entry, ok, ctx.clock(), ctx.plan)
        if tripped is not None:
            ctx.trip(*tripped)
            raise crawlrun.BreakerTripped()
        if not ok:
            return "down"
        answered.add(entry)
    return "ok"


def _book_lines(ctx, report):
    """One `themes` line for each book of the report that was made (`ok`), failed a try (`failed`) or was dropped by the run (`skipped`, with its fixed reason). Returns the
    number made, the books that failed and the books that were dropped (neither is to be planned again in this window)."""
    made, failed, dropped = 0, set(), set()
    for item in report["items"]:
        if item["status"] == "done":
            made += 1
            stats = item["stats"] or {}
            ctx.log.write("themes", "ok", book=item["book_id"], n=stats.get("calls"), seconds=stats.get("seconds"), now=ctx.clock())
        elif item["status"] == "failed" or (item["status"] == "waiting" and item["attempts"] > 0):
            failed.add(item["book_id"])
            ctx.log.write("themes", "failed", book=item["book_id"], reason=item["reason"] or None, now=ctx.clock())
        elif item["status"] == "dropped":
            dropped.add(item["book_id"])
            ctx.log.write("themes", "skipped", book=item["book_id"], reason=item["reason"] or None, now=ctx.clock())
    return made, failed, dropped


def _fit(seconds_left):
    """The most texts that an embedding of `seconds_left` seconds can send, by the measured cost (a fixed part, a part for each call of `EMBED_GROUP` texts and a part for each text),
    using only `MARGIN` of the time. Never below zero."""
    usable = seconds_left * MARGIN - BUILD_OVERHEAD_S
    return max(0, int(usable // (SECONDS_A_TEXT + SECONDS_A_CALL / EMBED_GROUP)))


def make_step(open_store=None, statvfs=None, probe=None, launcher=None, root=None, weave=None):
    """The function for the `idle` point. `open_store`, `statvfs` (the free-space reader), `probe` (the probe of one model entry, given the config and the task), `launcher`, `root`
    and `weave` (the module that repairs the weave: `_np`, `status`, `repair`) replace the real ones (tests)."""
    read_space = statvfs or os.statvfs
    weaving = weave or library_weave

    def step(ctx):
        window = ctx.plan["themes_window_s"]
        began = ctx.clock()
        made, reason, ran_out = 0, OFF, False     # `ran_out`: a part of the window ended for want of time, and not for want of work
        try:
            if window == 0:
                return
            end = min(began + datetime.timedelta(seconds=window), ctx.deadline)
            themes_end = began + (end - began) * THEMES_SHARE

            def stopper(until, why):
                def stop():
                    """True when no more work is to be started: the stop file, the time `until`, or a disk floor; once said, it stays said (in `why`)."""
                    if not why:
                        if crawlguard.stop_requested(ctx.index_root):
                            why.append(STOPPED)
                        elif ctx.clock() >= until:
                            why.append(DEADLINE)
                        else:
                            try:
                                crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=read_space)
                            except KbError:
                                why.append(DISK)
                    return bool(why)
                return stop

            why, themes_why = [], []
            stop, stop_themes = stopper(end, why), stopper(themes_end, themes_why)

            def say(step_name, outcome, why_text=None, n=None, since=None):
                seconds = int((ctx.clock() - since).total_seconds()) if since is not None else None
                ctx.log.write(step_name, outcome, reason=why_text, n=n, seconds=seconds, now=ctx.clock())

            reason = FAILED                                            # what the window says if an error leaves it before a normal end sets another reason
            if stop():
                reason = why[0]
                return
            library = (open_store or library_store.Store.open)()
            try:
                themerun._current(ctx.cfg)
            except KbError:
                reason = SETTINGS
                return

            # ---- 1. the themes, for at most their share of the window
            leave_out, answered = set(), set()
            while True:
                chosen = _eligible(library, ctx.cfg, ctx.index_root, leave_out)
                if not chosen:
                    break
                planned = themerun.plan(library, ctx.cfg, book_ids=chosen)
                if planned["books"] == 0:
                    break
                try:
                    report = themerun.run(library, ctx.cfg, planned["run"], launcher=launcher, root=root, stop=stop_themes)
                except KbError as error:
                    reason = LOCKED if str(error) == LOCK_REFUSED else FAILED
                    return
                done, failed, dropped = _book_lines(ctx, report)
                made += done
                leave_out |= failed | dropped
                if failed:
                    if stop_themes():                                  # at the end of the share, or with the stop file there, no model entry is asked
                        break
                    verdict = _answers(ctx, probe, answered)
                    if verdict == "down":
                        reason = FAILED
                        return
                    if verdict != "ok":
                        reason = verdict
                        return
                if themes_why:
                    break
                if report["stopped"] is not None:
                    reason = FAILED
                    return
                if not (done or failed or dropped):                    # a pass that made nothing, failed nothing and dropped nothing would be planned again for ever
                    break
            if themes_why and themes_why[0] == DEADLINE:
                ran_out = True                                         # the share of the themes is spent: the rest of the window is for the vectors and the weave
            if stop():
                reason = why[0]
                return

            # ---- 2. the vectors of the themes, in a batch that fits the time left
            outcome = _vectors(ctx, library, stop, why, end, say, probe, launcher, root)
            if outcome == "limited":
                ran_out = True
            elif outcome is not None:
                reason = outcome
                return
            if stop():
                reason = why[0]
                return

            # ---- 3. the weave, when a repair is due
            if _weave(ctx, library, end, say, weaving) == "limited":
                ran_out = True
            reason = DEADLINE if ran_out else NOTHING
        except crawlrun.BreakerTripped:
            reason = FAILED
            raise
        finally:                                                       # the window's own line, whatever ended it
            used = int((ctx.clock() - began).total_seconds())
            outcome = ("ok" if made or ran_out else "skipped") if reason in (NOTHING, DEADLINE) else _OUTCOME[reason]
            ctx.log.write("idle", outcome, reason=reason, n=made, seconds=used, now=ctx.clock())

    return step


def _vectors(ctx, library, stop, why, end, say, probe, launcher, root):
    """The `theme_vectors` part of the window: the vectors of the themes that have none, in a batch that fits the time left. Returns None when it went well or had nothing to do,
    `"limited"` when the time left held back a batch, or the reason that ends the window (`STOPPED`, `DISK`, `DEADLINE` from the stop, or `FAILED`). A build that is cut writes nothing."""
    since = ctx.clock()
    try:
        crawlguard.entry_of(ctx.cfg, "card-embed")
    except KbError:
        say("theme_vectors", "skipped", SETTINGS)
        return None
    try:
        waiting = themevectors.waiting_texts(library, ctx.cfg)
    except KbError:
        say("theme_vectors", "failed", "the texts that wait could not be counted", since=since)
        return FAILED
    if waiting == 0:
        say("theme_vectors", "skipped", "nothing waits", since=since)
        return None
    fit = _fit((end - ctx.clock()).total_seconds() - WEAVE_RESERVE_S)
    batch = min(waiting, fit)
    if batch < min(MIN_BATCH, waiting):                                # the time limits the batch below the least, and more are waiting: a longer window will do it
        say("theme_vectors", "skipped", "waits for a longer window", since=since)
        return "limited"
    try:
        with themevectors.lock(ctx.index_root, wait=LOCK_LOOK_S):      # looked at before the work, which a lock refused at the write would lose
            pass
    except themevectors.Busy:
        say("theme_vectors", "skipped", LOCKED, since=since)
        return None
    except KbError:
        say("theme_vectors", "failed", "the lock of the vectors could not be opened", since=since)
        return FAILED
    try:
        built = themevectors.build(library, ctx.cfg, launcher=launcher, root=root, stop=stop, max_texts=(batch if batch < waiting else None), group=EMBED_GROUP, lock_wait=LOCK_WRITE_S)
    except themeextract.Cut:
        say("theme_vectors", "skipped", why[0] if why else STOPPED, since=since)
        return why[0] if why else STOPPED
    except themevectors.Busy:                                          # taken between the look and the write: the work is lost, and no model is to blame
        say("theme_vectors", "skipped", LOCKED, since=since)
        return None
    except KbError:
        say("theme_vectors", "failed", "the vectors could not be made", since=since)
        _answers(ctx, probe, set(), tasks=EMBED_TASKS)                 # a model that does not answer is counted; a trip ends the run
        return FAILED
    say("theme_vectors", "ok", n=built["texts_sent"], since=since)
    return "limited" if batch < waiting else None


def _weave(ctx, library, end, say, weaving):
    """The `weave` part of the window: the repair of the weave, only when it is due, never a full build, and only with the least time left. Returns `"limited"` when too little
    time was left, otherwise None."""
    since = ctx.clock()
    if (end - ctx.clock()).total_seconds() < WEAVE_RESERVE_S:
        say("weave", "skipped", "too little time")
        return "limited"
    try:
        weaving._np()
    except KbError:
        say("weave", "skipped", "numpy is not installed")
        return None
    try:
        state = weaving.status(ctx.index_root, ctx.cfg, library)
    except KbError:
        say("weave", "skipped", "no weave", since=since)
        return None
    if state["full_build_needed"]:
        say("weave", "skipped", "a full build is needed", since=since)
        return None
    if not state["repair_due"]:
        say("weave", "skipped", "not due", n=state["waiting"]["total"], since=since)
        return None
    try:
        done = weaving.repair(ctx.index_root, ctx.cfg, library)
    except KbError:
        say("weave", "failed", "the repair was refused", since=since)
        return None
    say("weave", "ok", n=done.get("themes_added"), since=since)
    return None


step = make_step()
