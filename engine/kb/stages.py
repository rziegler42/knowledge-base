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
