"""The stage state of a version: found, fetched, scanned, converted and indexed, each pending, done, failed or
skipped, with the reason and the tool. It is a small mutable file rewritten atomically beside the version file.

A stage that is done is never run again. A stage that is pending or failed, and whose inputs are ready, is due. After
a crash a payload may be filed whose stage is not yet marked done, and `reconcile` checks it and adopts it."""
import json
from datetime import datetime, timezone

from . import KbError, config, textutil

FORMAT = 1
STAGES = ("found", "fetched", "scanned", "converted", "indexed")
STATUSES = ("pending", "done", "failed", "skipped")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initial_state():
    """A new version: `found` is done (the book exists) and every other stage waits."""
    return {"format": FORMAT, "stages": {
        s: {"status": "done" if s == "found" else "pending", "reason": "", "tool": "", "at": _now()}
        for s in STAGES}}


def read(store, book_id, version_id):
    path = store.stages_file(book_id, version_id)
    try:
        with open(path) as f:
            state = json.load(f)
    except FileNotFoundError:
        raise KbError("the version has no stage state") from None
    except (OSError, ValueError) as e:
        raise KbError(f"the stage state cannot be read: {e}") from None
    entries = state.get("stages") if isinstance(state, dict) else None
    if not isinstance(entries, dict) or set(entries) != set(STAGES) or not all(
            isinstance(e, dict) and e.get("status") in STATUSES for e in entries.values()):
        raise KbError("the stage state is malformed")
    return state


def _needs_met(state, stage):
    st = state["stages"]
    done = lambda s: st[s]["status"] == "done"
    if stage == "fetched":
        return done("found")
    if stage == "scanned":
        return done("fetched")
    if stage == "converted":
        # a scan that failed or was skipped does not block conversion; a scan still pending does
        return done("fetched") and st["scanned"]["status"] in ("done", "failed", "skipped")
    if stage == "indexed":
        return done("converted")
    return True


_NEEDS_TEXT = {"fetched": "found is done", "scanned": "fetched is done",
               "converted": "fetched is done and scanned is done, failed or skipped", "indexed": "converted is done"}


def mark(store, book_id, version_id, stage, status, reason="", tool=""):
    """Set a stage's status. A stage cannot become done or failed before its inputs are ready, a failure or a skip
    needs a reason, and a stage that is done does not change."""
    if stage not in STAGES:
        raise KbError(f"not a stage: {stage!r}")
    if status not in STATUSES:
        raise KbError(f"not a stage status: {status!r}")
    store._guard()
    state = read(store, book_id, version_id)
    current = state["stages"][stage]["status"]
    if current == "done":
        if status == "done":
            return
        raise KbError(f"the stage {stage} is already done and is not run or changed again")
    reason, tool = textutil.clean(reason, 500), textutil.clean(tool or "", 100)  # text from a server or a tool is untrusted
    if status in ("failed", "skipped") and not reason:  # checked after cleaning: a reason of only control characters is none
        raise KbError(f"a stage that is {status} needs a reason")
    if status in ("done", "failed") and not _needs_met(state, stage):
        raise KbError(f"the stage {stage} needs {_NEEDS_TEXT[stage]} first")
    state["stages"][stage] = {"status": status, "reason": reason, "tool": tool or "", "at": _now()}
    config.write_json_atomic(store.stages_file(book_id, version_id), state, 0o644)


def reset(store, book_id, version_id, stage, reason):
    """Put a stage whose result lives outside the book back to pending, which `mark` does not allow for a stage that is done.
    Only `indexed` is such a stage: its result is rows in the search index, and when a book leaves the index they are gone,
    so the stage is no longer done. Nothing is changed for a stage that is already pending."""
    if stage != "indexed":
        raise KbError(f"the stage {stage} cannot be put back: only the index lives outside the book")
    store._guard()
    state = read(store, book_id, version_id)
    if state["stages"][stage]["status"] == "pending":
        return
    state["stages"][stage] = {"status": "pending", "reason": textutil.clean(reason, 500), "tool": "", "at": _now()}
    config.write_json_atomic(store.stages_file(book_id, version_id), state, 0o644)


REDO_FROM = ("scanned", "converted", "indexed")  # the stages whose result can be made again; each puts back the ones after it


def redo(store, book_id, version_id, stage, reason):
    """Make a stage, and the stages after it, again: the owner's command, for when a tool was changed and approved anew. Every
    one of them that is done goes back to pending (a stage that is pending, failed or skipped is left as it is), so the next
    `process` runs it again. Nothing that was filed is touched: the payloads stay, and a tool whose version is the same as the one
    that made them is not run again. A version that has not been fetched is left alone. Returns the stages put back, in order."""
    if not isinstance(stage, str) or stage not in REDO_FROM:
        raise KbError(f"only {', '.join(REDO_FROM)} can be made again")
    store._guard()
    state = read(store, book_id, version_id)
    if state["stages"]["fetched"]["status"] != "done":
        return []
    reason, put_back = textutil.clean(reason, 500), []
    for name in REDO_FROM[REDO_FROM.index(stage):]:
        if state["stages"][name]["status"] == "done":
            state["stages"][name] = {"status": "pending", "reason": reason, "tool": "", "at": _now()}
            put_back.append(name)
    if put_back:
        config.write_json_atomic(store.stages_file(book_id, version_id), state, 0o644)
    return put_back


def redo_books(store, book_ids, scan, reason):
    """`redo` for every version of the books named (all of them, if none are named), from the conversion on, or from the scan if
    `scan` is true. Books that are not active are left alone. A book named that is not there is a refusal before anything is
    done. A version that cannot be read is reported and the others go on. Returns what was put back, version by version."""
    if book_ids is None:
        wanted = store.list_books()
    else:
        wanted = list(book_ids)
        for book_id in wanted:
            store.read_book(book_id)
    stage, report = ("scanned" if scan else "converted"), []
    for book_id in wanted:
        try:
            if store.read_book(book_id).get("state") != "active":
                continue
            versions = store.version_ids(book_id)
        except KbError as e:
            report.append({"book_id": book_id, "version_id": None, "error": textutil.clean(str(e), 300)})
            continue
        for version_id in versions:
            try:
                put_back = redo(store, book_id, version_id, stage, reason)
            except KbError as e:
                report.append({"book_id": book_id, "version_id": version_id, "error": textutil.clean(str(e), 300)})
                continue
            if put_back:
                report.append({"book_id": book_id, "version_id": version_id, "stages": put_back})
    return report


def due(store, book_id, version_id):
    """The stages to run now, in order: pending or failed, with their inputs ready."""
    state = read(store, book_id, version_id)
    return [s for s in STAGES if state["stages"][s]["status"] in ("pending", "failed") and _needs_met(state, s)]


def reconcile(store, book_id, version_id, stage, payload_name):
    """After a stop, decide what to do with a stage that may have filed its payload.

    Returns "done" (nothing to do), "run" (no payload is filed, so do the work), "blocked" (a payload is filed but the
    stage's inputs are not ready, so nothing is changed), "adopted" (a filed payload passed its hash check, the
    version file now lists it and the stage is done) or "invalid" (a filed payload failed the check, the stage is
    marked failed with the reason, and the payload is not adopted or overwritten)."""
    state = read(store, book_id, version_id)
    if state["stages"][stage]["status"] == "done":
        return "done"
    if store.payload_dir(book_id, version_id, payload_name) is None:
        return "run"
    if not _needs_met(state, stage):
        return "blocked"
    try:
        manifest = store.adopt_payload(book_id, version_id, payload_name)
    except KbError as e:
        mark(store, book_id, version_id, stage, "failed", reason=f"the filed payload does not validate: {e}")
        return "invalid"
    mark(store, book_id, version_id, stage, "done", tool=manifest.get("tool") or "")
    return "adopted"
