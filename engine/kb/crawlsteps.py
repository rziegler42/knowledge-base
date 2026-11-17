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

from . import KbError, crawlbooks, crawlguard, scan as scan_stage, stages
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


def _refusal(ctx, statvfs):
    """Why a scan may not be made now (the stop file, a disk floor), or `None`."""
    if crawlguard.stop_requested(ctx.index_root):
        return STOPPED
    try:
        crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=statvfs)
    except KbError as e:
        return f"the disk floor refuses a scan: {e}"
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
