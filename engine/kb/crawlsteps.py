"""The scan and hold step of the unattended crawl, and the steps over a book that follow it (`docs/specs/population.md`, "Scan flags"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment H).

**Scan and hold.** Every unfinished crawl book is scanned before it is converted, and a hostile one is **held**: `crawl_held` (the kinds), a `hold` log line, and the book stays filed (its state is not changed) but is
terminal, so no later step converts, indexes, cards or moves it, and the report names it. The scan itself is `scan.scan_version` (the tool is the owner's approved `kb-scan`, run through the confined runner), and the
step reads only what it leaves: the stage `scanned` and the caveats on the version. Which findings hold is the plan's `hold_kinds` (the default is the findings that mean a file is hostile); **`script_elements`,
`event_handlers` and `pattern_in_binary_data` never hold, whatever the plan lists**, since nearly every page has them.

**Fail closed.** A scan that fails, that cannot run (the tool is not approved, cannot be started) or that is not made for the file holds the book at once, as `scan_failed`, `scan_unavailable` or `scan_timeout`
(told apart by the fixed wording of the tool runner's own messages, never stored). **A scan is never tried again:** a book whose stage already says `failed` is held without a second scan, so a death between the
scan and the hold costs nothing and loops nowhere. The owner may release a held book later; nothing here does.

**Refusals are not holds.** The stop file and the disk floors are looked at before each scan. A refusal by either ends the step quietly with one `skipped` line and leaves the book unscanned for the next run.

What reaches an event or a log line is a kind from a fixed list and a fixed reason; text a page or a tool chose (a stage reason, a caveat's detail) never does. The step acts only on books `crawlbooks.crawl_books` lists
(filed by the crawl under an approved digest, with no terminal event). It makes no request and no model call, reads no environment variable and starts no program of its own; the tool runner does."""
import os

from . import KbError, convert as convert_stage, crawlbooks, crawlguard, crawlrun, crawlstate, index as index_stage, scan as scan_stage, stages
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
    if crawlbooks.record_held(library, book_id, kinds):
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
    """Finish what a death left half done: a crawl book with `crawl_rejected` whose state is still `active` becomes `weeded`, and its candidate row, if still `kept`, is rejected with the book's reason."""
    scan = crawlbooks.scan_crawl_books(library)
    crawlbooks.finish_weeds(library, scan)
    for entry in scan.entries:
        if any(isinstance(e, dict) and e.get("event") == "crawl_rejected" for e in entry["events"]):
            _reject_row(ctx, library, entry["id"], _rejection_reason(library, entry["id"]) or PARKED_TEXT)


def make_convert_step(convert=None, index=None, open_store=None, statvfs=None):
    """The function that converts and indexes every unfinished crawl book, oldest first. `convert`, `index`, `open_store` and `statvfs` replace the real ones (tests). Books parked in one run, at `consecutive_failures`
    of them, trip the breaker as a `stage_bound` and end the run: a converter that kills book after book is a fault of the converter, not of the books."""

    def step(ctx):
        library = (open_store or library_store.Store.open)()
        _finish_rejections(ctx, library)
        approved = crawlbooks.approved_digests(ctx.index_root)
        listed = crawlbooks.crawl_books(library, approved, crawlbooks.scan_crawl_books(library))
        counts, report, ended = {}, {"rejected": 0, "failed": 0, "parked": 0}, CONVERTED
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
            ctx.convert_report = {"converted": counts.get("converted", 0), "indexed": counts.get("indexed", 0), **report, "ended": ended}

    return step


convert_step = make_convert_step()
