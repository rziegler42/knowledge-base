"""The scan and hold step of the unattended crawl, and the steps over a book that follow it (`docs/specs/population.md`, "Scan flags"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment H).

**Scan and hold.** Every unfinished crawl book is scanned before it is converted, and a hostile one is **held**: `crawl_held` (the kinds), a `hold` log line, and the book stays filed on disk but is terminal and its
state becomes `weeded` (`crawlbooks.hold`: the event first, the state second), so that no later crawl step, and no command of the engine that walks the active books (`process`, `cards-queue`, `place-propose`,
the index and the search), converts, indexes, cards or moves it; the report names it by its event, and the rows it had in the index are taken out in the same run. The scan itself is `scan.scan_version` (the tool is the owner's approved `kb-scan`, run through the confined runner), and the
step reads only what it leaves: the stage `scanned` and the caveats on the version. Which findings hold is the plan's `hold_kinds` (the default is the findings that mean a file is hostile); **`script_elements`,
`event_handlers` and `pattern_in_binary_data` never hold, whatever the plan lists**, since nearly every page has them.

**Fail closed.** A scan that fails, that cannot run (the tool is not approved, cannot be started) or that is not made for the file holds the book at once, as `scan_failed`, `scan_unavailable` or `scan_timeout`
(told apart by the fixed wording of the tool runner's own messages, never stored). **A scan is never tried again:** a book whose stage already says `failed` is held without a second scan, so a death between the
scan and the hold costs nothing and loops nowhere. Releasing a held book is not built: the owner may set its state back to `active`, but the next run of a step would weed it again, because a hold whose state was not written and a book released cannot be told apart (a release would need a mark that `finish_weeds` honours).

**Refusals are not holds.** The stop file and the disk floors are looked at before each scan. A refusal by either ends the step quietly with one `skipped` line and leaves the book unscanned for the next run.

What reaches an event or a log line is a kind from a fixed list and a fixed reason; text a page or a tool chose (a stage reason, a caveat's detail) never does. The step acts only on books `crawlbooks.crawl_books` lists
(filed by the crawl under an approved digest, with no terminal event). It makes no request and no model call, reads no environment variable and starts no program of its own; the tool runner does."""
import os

from . import KbError, convert as convert_stage, crawlbooks, crawlguard, crawljudge, crawlrun, crawlstate, index as index_stage, scan as scan_stage, stages
from . import store as library_store

NEVER_HOLD = frozenset({"script_elements", "event_handlers", "pattern_in_binary_data"})
STOPPED = "the stop file is present"
FINISHED = "all the books are scanned"


def _hold_kinds(plan, caveats):
    """The kinds among `caveats` that the plan holds a book for, sorted (the three that never hold are never among them)."""
    wanted = {k for k in (plan.get("hold_kinds") or []) if isinstance(k, str)} - NEVER_HOLD
    return sorted({c["kind"] for c in caveats if isinstance(c, dict) and c.get("kind") in wanted})


def _failure_kind(reason):
    """Which hold a failed scan is, from the tool runner's own wording (the text is read here and never kept)."""
    text = reason if isinstance(reason, str) else ""
    if " timed out after " in text:
        return "scan_timeout"
    if "is not on the approved list" in text or "is not approved for" in text or " could not be started" in text:
        return "scan_unavailable"
    return "scan_failed"


def _refusal(ctx, statvfs, what="a scan"):
    """Why `what` may not be done now (the stop file, a disk floor), or `None`."""
    if crawlguard.stop_requested(ctx.index_root):
        return STOPPED
    try:
        crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=statvfs)
    except KbError as e:
        return f"the disk floor refuses {what}: {e}"
    return None


def _hold(ctx, library, book_id, kinds):
    if crawlbooks.hold(library, book_id, kinds):
        ctx.log.write("hold", "held", book=book_id, reason=", ".join(kinds), now=ctx.clock())
    return "held"


def _state(library, book_id):
    """`(version, stage, caveats)` of a book, or `None` if what says whether it was scanned cannot be read: such a book is held, as a scan that failed (a read that fails is no reason to let it through)."""
    try:
        version = library.read_book(book_id).get("current_version")
        if not version:
            return None
        stage = stages.read(library, book_id, version)["stages"]["scanned"]
        caveats = library.read_version(book_id, version).get("caveats", []) if stage["status"] == "done" else []
        return version, stage, caveats
    except KbError:
        return None


def scan_and_hold(ctx, library, book_id, scan, statvfs):
    """Take one crawl book through the scan. Returns `("scanned", None)` (scanned now, no hold), `("held", None)`, `("already", None)` (scanned earlier, no hold) or `("refused", why)` (the stop file or a disk floor:
    nothing was done). `scan(store, book_id, version_id)` is `scan.scan_version` unless a test gives another. A refusal touches only a book that needs a scan: one whose scan is over is still dealt with, so that
    a refusal never leaves a book that must be held to be converted."""
    state = _state(library, book_id)
    if state is None:
        return _hold(ctx, library, book_id, ["scan_failed"]), None
    version, stage, caveats = state
    status = stage["status"]
    if status == "failed":                                              # a scan that failed before is not made again
        return _hold(ctx, library, book_id, [_failure_kind(stage.get("reason"))]), None
    if status == "skipped":
        return _hold(ctx, library, book_id, ["scan_unavailable"]), None
    if status == "done":
        kinds = _hold_kinds(ctx.plan, caveats)
        return (_hold(ctx, library, book_id, kinds), None) if kinds else ("already", None)
    why = _refusal(ctx, statvfs)
    if why:
        return "refused", why
    try:
        result = scan(library, book_id, version)
    except KbError:
        result = {"status": "failed", "reason": ""}
    if result.get("status") == "done":
        caveats = result.get("caveats") or []
        kinds = _hold_kinds(ctx.plan, caveats)
        if kinds:
            return _hold(ctx, library, book_id, kinds), None
        ctx.log.write("scan", "ok", book=book_id, n=len(caveats), now=ctx.clock())
        return "scanned", None
    kind = "scan_unavailable" if result.get("status") == "skipped" else _failure_kind(result.get("reason"))
    return _hold(ctx, library, book_id, [kind]), None


def make_scan_step(scan=None, open_store=None, statvfs=None):
    """The function that scans and holds every unfinished crawl book, oldest first. `scan`, `open_store` and `statvfs` replace the real ones (tests)."""

    def step(ctx):
        library = (open_store or library_store.Store.open)()
        finished = crawlbooks.finish_weeds(library)                         # a hold or a weed that died between its event and its state
        approved = crawlbooks.approved_digests(ctx.index_root)
        listed = crawlbooks.crawl_books(library, approved, crawlbooks.scan_crawl_books(library))
        report, ended = {"scanned": 0, "held": 0}, FINISHED
        for book_id in listed:
            outcome, why = scan_and_hold(ctx, library, book_id, scan or scan_stage.scan_version, statvfs or os.statvfs)
            if outcome == "refused":
                if ended == FINISHED:                                       # the refusal is said once; the books that need a scan wait, the others are still dealt with
                    ctx.log.write("scan", "skipped", reason=ctx.log.safe(why), now=ctx.clock())
                ended = why
            if outcome in ("scanned", "held"):
                report["scanned"] += 1
                report["held"] += outcome == "held"
        if report["held"] or finished:
            index_stage.forget_inactive(library)                            # a book held after it was indexed leaves the search now
        ctx.scan_report = dict(report, ended=ended)

    return step


step = make_scan_step()


# ---- convert and index

MAX_TEXT_CHARS = 5_000_000            # the plan has no key for the size of a converted text; the judgement reads 1,500 characters and the index writes a row for each 2,000
TOO_SHORT = "the converted text is shorter than min_chars"
TOO_LONG = "the converted text is over the size limit"
NO_CONVERTER = "the file has no converter"
CONVERT_FAILED = "the conversion failed"
INDEX_FAILED = "the book could not be indexed"
PARKED_TEXT = "the book is parked after failed tries"
CONVERTED = "all the books are converted and indexed"
TRIPPED = "the circuit breaker was tripped"
_FAILURES = (Exception,)              # whatever a hostile page or a broken tool does to the converter or the index is one failed try of the book, never a crash of the step that would be met again by the next run


def _found(events):
    return next((e for e in events if isinstance(e, dict) and e.get("event") == "crawl_found"), None)


def _reject_row(ctx, library, book_id, reason):
    """Reject the candidate row of a book that was weeded: `kept` to `rejected` with the reason, and nothing if the row is not `kept` (it was done, or the book has no row)."""
    found = _found(library.read_events(book_id))
    number = found.get("candidate") if found else None
    row = ctx.conn.execute("SELECT status FROM candidates WHERE id = ?", (number,)).fetchone()
    if row is not None and row[0] == "kept":
        crawlstate.reject_kept(ctx.conn, ctx.plan, number, reason, ctx.clock())


def _rejection_reason(library, book_id):
    event = next((e for e in library.read_events(book_id) if isinstance(e, dict) and e.get("event") == "crawl_rejected"), None)
    return event.get("reason") if event else None


def _reject(ctx, library, book_id, reason, stage):
    """Weed a book for a reason of its own (fixed text), reject its row and say so."""
    crawlbooks.weed(library, book_id, reason, None, stage)
    _reject_row(ctx, library, book_id, reason)
    ctx.log.write("reject", "rejected", book=book_id, reason=reason, now=ctx.clock())
    return "rejected"


def _failed_try(ctx, library, book_id, stage, reason):
    """One failed try of `stage`; at the plan's `retries` the book is parked (weeded, its row rejected)."""
    result = crawlbooks.fail_step(library, ctx.plan, book_id, stage, reason, ctx.run)
    if result == "parked":
        _reject_row(ctx, library, book_id, _rejection_reason(library, book_id) or PARKED_TEXT)
        ctx.log.write("reject", "rejected", book=book_id, reason=PARKED_TEXT, now=ctx.clock())
        return "parked"
    if result == "retry":
        ctx.log.write(stage, "failed", book=book_id, reason=reason, now=ctx.clock())
        return "failed"
    return "final"


def _converted_chars(library, book_id, version):
    """The size of the converted text in use, from the record the conversion filed."""
    record = library.read_version(book_id, version)
    use = record.get("conversion_in_use")
    for item in record.get("conversions", []):
        if isinstance(use, dict) and all(item.get(k) == use.get(k) for k in ("tool", "version", "generation")):
            return item["chars"]                      # the store keeps it a whole number from 0
    raise KbError("the converted text has no record")


def convert_and_index(ctx, library, book_id, convert, index, statvfs, counts=None):
    """Take one crawl book through the conversion and the index. Returns `(outcome, why)`: `"done"`, `"skipped"` (the book is not one to convert now), `"final"`, `"failed"` (a failed try), `"parked"`, `"rejected"`
    or `"refused"` (the stop file or a disk floor: nothing was done, and `why` says which). A book is converted only if its scan is **done** and it has no terminal event, so a book that failed its scan, was
    skipped or is held is never converted here, whatever the stage file would let `process` do. `counts` (a dictionary) is given what was converted and indexed."""
    counts = counts if counts is not None else {}
    events = library.read_events(book_id)
    if any(isinstance(e, dict) and e.get("event") in crawlbooks.TERMINAL for e in events):
        return "final", None
    try:
        version = library.read_book(book_id).get("current_version")
        state = stages.read(library, book_id, version)["stages"] if version else None
    except KbError:
        return "skipped", None
    if state is None or state["scanned"]["status"] != "done":
        return "skipped", None
    try:
        kinds = _hold_kinds(ctx.plan, library.read_version(book_id, version).get("caveats", []))
    except KbError:
        kinds = ["scan_failed"]
    if kinds:                                                           # a scan that died before its hold was written: the hold is made here and the book is not converted
        return _hold(ctx, library, book_id, kinds), None
    if state["converted"]["status"] != "done":
        why = _refusal(ctx, statvfs, "a conversion")
        if why:
            return "refused", why
        try:
            result = convert(library, book_id, version)
        except _FAILURES:
            result = {"status": "failed"}
        if result.get("status") == "skipped":
            return _reject(ctx, library, book_id, NO_CONVERTER, "convert"), None
        if result.get("status") != "done":
            return _failed_try(ctx, library, book_id, "convert", CONVERT_FAILED), None
        counts["converted"] = counts.get("converted", 0) + 1
        ctx.log.write("convert", "ok", book=book_id, now=ctx.clock())
    try:
        chars = _converted_chars(library, book_id, version)
    except _FAILURES:
        return _failed_try(ctx, library, book_id, "convert", CONVERT_FAILED), None
    if chars < ctx.plan["min_chars"]:
        return _reject(ctx, library, book_id, TOO_SHORT, "convert"), None
    if chars > MAX_TEXT_CHARS:
        return _reject(ctx, library, book_id, TOO_LONG, "convert"), None
    if stages.read(library, book_id, version)["stages"]["indexed"]["status"] != "done":
        why = _refusal(ctx, statvfs, "an index write")
        if why:
            return "refused", why
        try:
            result = index(library, book_id, version)
        except _FAILURES:
            result = {"status": "failed"}
        if result.get("status") != "done":
            return _failed_try(ctx, library, book_id, "index", INDEX_FAILED), None
        counts["indexed"] = counts.get("indexed", 0) + 1
        ctx.log.write("index", "ok", book=book_id, now=ctx.clock())
    return "done", None


def _finish_rejections(ctx, library):
    """Finish what a death left half done: a crawl book with `crawl_rejected` or `crawl_held` whose state is still `active` becomes `weeded`, and the candidate row of a rejected book, if still `kept`, is rejected
    with the book's reason. Returns the ids of the books whose state was finished."""
    scan = crawlbooks.scan_crawl_books(library)
    finished = crawlbooks.finish_weeds(library, scan)
    for entry in scan.entries:
        if any(isinstance(e, dict) and e.get("event") == "crawl_rejected" for e in entry["events"]):
            _reject_row(ctx, library, entry["id"], _rejection_reason(library, entry["id"]) or PARKED_TEXT)
    return finished


def make_convert_step(convert=None, index=None, open_store=None, statvfs=None):
    """The function that converts and indexes every unfinished crawl book, oldest first. `convert`, `index`, `open_store` and `statvfs` replace the real ones (tests). Books parked in one run, at `consecutive_failures`
    of them, trip the breaker as a `stage_bound` and end the run: a converter that kills book after book is a fault of the converter, not of the books."""

    def step(ctx):
        library = (open_store or library_store.Store.open)()
        finished = _finish_rejections(ctx, library)
        approved = crawlbooks.approved_digests(ctx.index_root)
        listed = crawlbooks.crawl_books(library, approved, crawlbooks.scan_crawl_books(library))
        counts, report, ended = {}, {"held": 0, "rejected": 0, "failed": 0, "parked": 0}, CONVERTED
        try:
            for book_id in listed:
                outcome, why = convert_and_index(ctx, library, book_id, convert or convert_stage.convert_version, index or index_stage.index_version, statvfs or os.statvfs, counts)
                if outcome == "refused":
                    ended = why
                    ctx.log.write("convert", "skipped", reason=ctx.log.safe(why), now=ctx.clock())
                    break
                if outcome in report:
                    report[outcome] += 1
                if outcome == "parked" and report["parked"] >= ctx.plan["consecutive_failures"]:
                    ended = TRIPPED
                    ctx.trip(*crawlguard.bound_trip("convert", f"{report['parked']} books were parked in this run"))
                    raise crawlrun.BreakerTripped()
        finally:
            if report["held"] or finished:
                index_stage.forget_inactive(library)
            ctx.convert_report = {"converted": counts.get("converted", 0), "indexed": counts.get("indexed", 0), **report, "ended": ended}

    return step


convert_step = make_convert_step()


# ---- the judgement

JUDGED = "all the books are judged"
JUDGE_DOWN = "the model server did not answer"
JUDGE_FAILED = "the stored conversion cannot be read"
JUDGE_SETTINGS = "the judgement cannot be made: the embedding entry or the shelf vectors are not set up"
JUDGE_THRESHOLD = "the judgement has no threshold: it is set in the supervised run, and no book is judged until it is"
_RAN = ("scanned", "indexed")                 # (`indexed` is only ever done after `converted`)


def _ready_for_the_judge(library, book_id):
    """The version of a crawl book that has been scanned, converted and indexed and has no verdict of yes, taken from the book's own record, or `None`."""
    try:
        if any(isinstance(e, dict) and e.get("event") == "crawl_judged" and e.get("ok") is True for e in library.read_events(book_id)):
            return None
        version = library.read_book(book_id).get("current_version")
        state = stages.read(library, book_id, version)["stages"] if version else None
    except KbError:
        return None
    if state is None or any(state[name]["status"] != "done" for name in _RAN):
        return None
    return version


def _model_answers(ctx, probe):
    try:
        return bool((probe or crawlguard.probe_model)(ctx.cfg))
    except (KbError, OSError):
        return False


def _note_model(ctx, ok):
    """Note the sighting of the model server in the down clock; a trip of the clock ends the run."""
    state, _restarted = crawlguard.load_state(ctx.index_root)
    tripped = crawlguard.note_model(state, ok, ctx.clock(), ctx.plan)
    crawlguard.save_state(ctx.index_root, state)
    if tripped is not None:
        ctx.trip(*tripped)
        raise crawlrun.BreakerTripped()


def make_judge_step(judge=None, embed=None, open_store=None, statvfs=None, probe=None):
    """The function that judges every crawl book that has been scanned, converted and indexed, oldest first, once each (`crawljudge.judge_book` does the judgement and its record). `judge`, `embed`, `open_store`,
    `statvfs` and `probe` replace the real ones (tests). The stop file and the disk floors are looked at before each call of the model. **A failed try asks the run's probe of the model server:** one that does not
    answer starts or goes on with the down clock (and trips on its rule) and ends the step; and `consecutive_failures` books in a row that fail with the server answering (a failed try, a parked book, or a stored conversion
    that cannot be read) trip the breaker as a `stage_bound`, so that a fault of the model or of the books is not paid for by every book. A book whose stored conversion cannot be read is a failed try of its own; a
    refusal that is not the book's (the entry or the shelf vectors) ends the run, and nothing is recorded for the book. The rows of a book that was weeded leave the index in the same run."""

    def step(ctx):
        if ctx.plan.get("threshold") is None:
            raise crawlrun.StepRefused(JUDGE_THRESHOLD)
        library = (open_store or library_store.Store.open)()
        finished = _finish_rejections(ctx, library)
        approved = crawlbooks.approved_digests(ctx.index_root)
        listed = crawlbooks.crawl_books(library, approved, crawlbooks.scan_crawl_books(library))
        report, ended, streak, answered = {"kept": 0, "rejected": 0, "retry": 0, "parked": 0}, JUDGED, 0, False
        try:
            for book_id in listed:
                version = _ready_for_the_judge(library, book_id)
                if version is None:
                    continue
                why = _refusal(ctx, statvfs or os.statvfs, "a judgement")
                if why:
                    ended = why
                    ctx.log.write("judge", "skipped", reason=ctx.log.safe(why), now=ctx.clock())
                    break
                try:
                    result = (judge or crawljudge.judge_book)(library, ctx.conn, ctx.cfg, ctx.plan, book_id, version, ctx.run, ctx.clock(), embed=embed)
                except Exception as error:                                   # (anything a damaged book does to the judgement is that book's failed try, and never a crash that the next run would meet again at the same book)
                    book_fault = not isinstance(error, KbError)
                    if not book_fault:
                        try:
                            crawljudge.converted_text(library, book_id, version)
                        except Exception:
                            book_fault = True
                    if book_fault:                                           # the book's own fault: a failed try of its own
                        outcome = "retry" if _failed_try(ctx, library, book_id, "judge", JUDGE_FAILED) != "parked" else "parked"
                        report[outcome] += 1
                        streak += 1
                        if streak >= ctx.plan["consecutive_failures"]:
                            ended = TRIPPED
                            ctx.trip(*crawlguard.bound_trip("judge", f"{streak} books in a row could not be judged"))
                            raise crawlrun.BreakerTripped()
                        continue
                    raise crawlrun.StepRefused(JUDGE_SETTINGS) from None
                outcome = result.get("outcome")
                if outcome in ("kept", "rejected", "retry", "parked"):
                    report[outcome] += 1
                if outcome in ("retry", "parked"):
                    streak += 1
                    if not _model_answers(ctx, probe):
                        ended = JUDGE_DOWN
                        ctx.log.write("judge", "failed", reason=JUDGE_DOWN, now=ctx.clock())
                        _note_model(ctx, False)
                        break
                    if streak >= ctx.plan["consecutive_failures"]:
                        ended = TRIPPED
                        ctx.trip(*crawlguard.bound_trip("judge", f"{streak} books in a row failed with the model server answering"))
                        raise crawlrun.BreakerTripped()
                elif outcome in ("kept", "rejected") and result.get("score") is not None:
                    streak, answered = 0, True                              # the model gave an answer for this book (a text that is not a document asks none, says nothing of the model and leaves the run of failures as it is)
            if answered and ended != JUDGE_DOWN:
                _note_model(ctx, True)                                       # the model answered in this run: its down clock is cleared
        finally:
            if report["rejected"] or report["parked"] or finished:
                index_stage.forget_inactive(library)
            ctx.judge_report = dict(report, ended=ended)

    return step


judge_step = make_judge_step()
