"""The `idle` step of the unattended crawl: themes in the time that is left after the fetch (`docs/specs/population.md`, "The idle window"; the plan
`2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave`, increment B).

After the fetch a run may spend `themes_window_s` seconds (the plan's `[idle]` section; 0 is off) making the themes of the books that have none, and **gives the
time back at a deadline**, so that the next run starts on time. What this step guards:

- **The window is the earlier of `themes_window_s` and what the run has left of its own time budget** (`ctx.deadline`). A run that was refused, stopped or tripped,
  or whose budget is spent, never reaches this point (`crawlrun.attach_point`).
- **A `stop` function is given to `themerun.run`** and says true when the stop file is there, when the deadline has come, or when a disk floor refuses; it is looked
  at before every book and before every model call, so a window ends at most one model call after its deadline. A book that is cut keeps the pieces it has answered
  (the run's journal) and is made the next time, with no try charged.
- **Which books.** The active books that have a card, a conversion in use and **no theme generation of the version in use at all**, oldest first, at most `BATCH` for
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

from . import KbError, crawlguard, crawlrun, theme, themerun
from . import store as library_store

BATCH = 20                                    # books in one plan
TASKS = ("theme", "theme-check")              # the tasks whose entries the themes call, in the order they are asked
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
            if book.get("state") != "active" or not version_id or theme.generations(library, book_id, version_id):
                continue
            if themerun._assess(library, book_id, extraction, False, records)[0] != "make":
                continue
        except KbError:
            continue
        chosen.append(book_id)
        if len(chosen) >= BATCH:
            break
    return chosen


def _answers(ctx, probe, answered):
    """Ask each distinct model entry of the themes one short call, in the order of `TASKS`, and note each answer in the entry's own down clock (a trip of a clock ends the
    run). An entry that answered earlier in this step (`answered`) is not asked again. Returns `"ok"` when every entry answered, `"down"` at the first that did not, or the
    reason of a quiet end when the stop file or the time budget appeared between two probes."""
    asked = set(answered)
    for task in TASKS:
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


def make_step(open_store=None, statvfs=None, probe=None, launcher=None, root=None):
    """The function for the `idle` point. `open_store`, `statvfs` (the free-space reader), `probe` (the probe of one model entry, given the config and the task), `launcher`
    and `root` replace the real ones (tests)."""
    read_space = statvfs or os.statvfs

    def step(ctx):
        window = ctx.plan["themes_window_s"]
        began = ctx.clock()
        made, reason = 0, OFF
        try:
            if window == 0:
                return
            end = min(began + datetime.timedelta(seconds=window), ctx.deadline)
            why = []

            def stop():
                """True when no more work is to be started: the stop file, the deadline, or a disk floor; once said, it stays said."""
                if not why:
                    if crawlguard.stop_requested(ctx.index_root):
                        why.append(STOPPED)
                    elif ctx.clock() >= end:
                        why.append(DEADLINE)
                    else:
                        try:
                            crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=read_space)
                        except KbError:
                            why.append(DISK)
                return bool(why)

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
            leave_out, answered = set(), set()
            while True:
                chosen = _eligible(library, ctx.cfg, ctx.index_root, leave_out)
                if not chosen:
                    reason = NOTHING
                    return
                planned = themerun.plan(library, ctx.cfg, book_ids=chosen)
                if planned["books"] == 0:
                    reason = NOTHING
                    return
                try:
                    report = themerun.run(library, ctx.cfg, planned["run"], launcher=launcher, root=root, stop=stop)
                except KbError as error:
                    reason = LOCKED if str(error) == LOCK_REFUSED else FAILED
                    return
                done, failed, dropped = _book_lines(ctx, report)
                made += done
                leave_out |= failed | dropped
                if failed:
                    if stop():                                         # at the deadline, or with the stop file there, no model entry is asked
                        reason = why[0]
                        return
                    verdict = _answers(ctx, probe, answered)
                    if verdict == "down":
                        reason = FAILED
                        return
                    if verdict != "ok":
                        reason = verdict
                        return
                if why:
                    reason = why[0]
                    return
                if report["stopped"] is not None:
                    reason = FAILED
                    return
                if not (done or failed or dropped):                    # a pass that made nothing, failed nothing and dropped nothing would be planned again for ever
                    reason = NOTHING
                    return
        except crawlrun.BreakerTripped:
            reason = FAILED
            raise
        finally:                                                       # the window's own line, whatever ended it
            used = int((ctx.clock() - began).total_seconds())
            outcome = ("ok" if made else "skipped") if reason == NOTHING else _OUTCOME[reason]
            ctx.log.write("idle", outcome, reason=reason, n=made, seconds=used, now=ctx.clock())

    return step


step = make_step()
