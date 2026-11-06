"""`process`: take every version of every active book through the stages it has not finished, in order: scan, convert, index.

Each stage keeps its own record in the version's stage state (done, failed with the reason, or skipped), so a run can be
stopped at any point and started again: a stage that is done is not run again, and a result a stage filed just before a stop
is adopted by the stage and not made again. A stage that failed is tried again on the next run. A failed scan does not stop
conversion; a failed conversion stops that version (it cannot be indexed) and no other. A version that has not been fetched is
left alone, because fetching is capture and not processing. The report lists only what was done in this run."""
from . import KbError, convert, index, scan, stages, textutil


def _run(store, stage, book_id, version_id):
    if stage == "scanned":
        return scan.scan_version(store, book_id, version_id)
    if stage == "converted":
        return convert.convert_version(store, book_id, version_id)
    return index.index_version(store, book_id, version_id)


def advance(store, book_id, version_id):
    """Run the stages of one version that are due. Returns a list of outcomes, one for each stage that was run."""
    report = []
    state = stages.read(store, book_id, version_id)["stages"]
    if state["fetched"]["status"] != "done":
        return report
    for stage in ("scanned", "converted", "indexed"):
        if state[stage]["status"] in ("done", "skipped"):
            continue
        entry = {"book_id": book_id, "version_id": version_id, "stage": stage}
        try:
            result = _run(store, stage, book_id, version_id)
        except (KbError, OSError, ValueError, MemoryError) as e:  # an error of this version is reported; the other versions go on
            report.append({**entry, "status": "error", "reason": textutil.clean(str(e), 300)})
            break
        entry["status"] = result["status"]
        if result.get("reason"):
            entry["reason"] = textutil.clean(result["reason"], 300)
        report.append(entry)
        if result["status"] != "done" and stage != "scanned":
            break  # a scan that failed or was skipped does not stop the conversion; nothing else does without a result
    return report


def _error(book_id, version_id, e):
    reason = str(e) if isinstance(e, KbError) else f"{type(e).__name__}: {e}"
    return {"book_id": book_id, "version_id": version_id, "stage": None, "status": "error", "reason": textutil.clean(reason, 300)}


def process(store, book_ids=None):
    """Advance the books named (all, if none are named). Books that are not active are left alone."""
    if book_ids is None:
        wanted = store.list_books()
    else:
        wanted = list(book_ids)
        for book_id in wanted:
            store.read_book(book_id)  # a book named that is not there is a refusal, before anything is done
    index.forget_inactive(store)  # a book put away leaves the search now, not at the next rebuild
    report = []
    for book_id in wanted:
        try:
            if store.read_book(book_id).get("state") != "active":
                continue
            versions = store.version_ids(book_id)
        except Exception as e:  # a book that cannot be read is reported, and the others go on
            report.append(_error(book_id, None, e))
            continue
        for version_id in versions:
            try:
                report.extend(advance(store, book_id, version_id))
            except Exception as e:  # whatever its data does to the program, the other versions and books go on
                report.append(_error(book_id, version_id, e))
    return report
