"""The scan stage: objective checks on a captured file, before conversion, through the confined tool runner.

The built-in scan tool (`scan_tool.py`) must be on the owner's approved list, like any tool. Its findings become caveats
on the version and never stop a book being filed: a scan that cannot run (the tool is not approved, it fails, it
overruns) marks the stage failed with the reason, the book stays filed, and conversion goes on regardless."""
import json
import os

from . import KbError, __version__, approvals, convert_run, stages, textutil
from .scan_tool import KINDS

TOOL_NAME = "kb-scan"
TOOL_VERSION = __version__
TOOL_LABEL = f"{TOOL_NAME} {TOOL_VERSION}"
MAX_CAVEATS = 50
FORMATS = {".pdf": "pdf", ".html": "html", ".htm": "html"}


def _format_of(primary):
    for ext, fmt in FORMATS.items():
        if primary and primary.lower().endswith(ext):
            return fmt
    return None


def _generations(store, book_id, version_id):
    """The numbers of the scan outputs already filed for a version, lowest first."""
    folder = os.path.join(store.version_dir(book_id, version_id), "derived", TOOL_NAME)
    return sorted(int(n) for n in os.listdir(folder) if n.isdigit()) if os.path.isdir(folder) else []


def _read_result(store, book_id, version_id, name):
    """The caveats in the scan tool's output, checked: it is untrusted data from a tool, so nothing is taken on trust."""
    path = store.payload_dir(book_id, version_id, name)
    try:
        with open(f"{path}/scan.json", "rb") as f:
            raw = f.read(1_000_000)
        result = json.loads(raw)
    except (OSError, ValueError, TypeError, RecursionError) as e:  # RecursionError: deeply nested JSON
        raise KbError(f"the scan output cannot be read: {type(e).__name__}") from None
    if not isinstance(result, dict) or result.get("format") != 1 or result.get("kind") not in ("pdf", "html"):
        raise KbError("the scan output is not in the expected form")
    listed = result.get("caveats")
    if not isinstance(listed, list) or len(listed) > MAX_CAVEATS:
        raise KbError("the scan output has no usable list of caveats")
    caveats = []
    for c in listed:
        if (not isinstance(c, dict) or set(c) != {"kind", "count", "detail"} or not isinstance(c["kind"], str)
                or c["kind"] not in KINDS
                or not isinstance(c["count"], int) or isinstance(c["count"], bool) or not 0 <= c["count"] <= 10**9
                or c["detail"] != KINDS[c["kind"]]):
            raise KbError("the scan output has a caveat that is not one of the known kinds")
        caveats.append({"kind": c["kind"], "count": c["count"], "detail": c["detail"], "tool": TOOL_LABEL})
    return caveats


def _record(store, book_id, version_id, name):
    """Take a filed scan output: check it, put its caveats on the version, and only then mark the stage done."""
    manifest = store.adopt_payload(book_id, version_id, name)  # hash check, read-only marking, the version file's payload list
    if manifest.get("tool") != TOOL_LABEL:  # made by another version of the tool than the one approved now
        raise KbError(f"the scan output was made by {textutil.literal(manifest.get('tool'), 60)}, not by {TOOL_LABEL}")
    caveats = _read_result(store, book_id, version_id, name)
    store.set_version_caveats(book_id, version_id, caveats)
    stages.mark(store, book_id, version_id, "scanned", "done", tool=TOOL_LABEL)
    return {"status": "done", "caveats": caveats}


def _fail(store, book_id, version_id, reason):
    stages.mark(store, book_id, version_id, "scanned", "failed", reason=reason, tool=TOOL_LABEL)
    return {"status": "failed", "reason": reason}


def scan_version(store, book_id, version_id):
    """Scan the original of a version. Returns {"status": "done", "caveats": [...]}, {"status": "failed", "reason": ...}
    or {"status": "skipped", "reason": ...}. Raises KbError only if the version cannot be scanned yet (it is not fetched).

    A scan output filed before a stop is checked and used. One that fails its checks is left where it is, and the scan
    is run again as the next generation beside it."""
    state = stages.read(store, book_id, version_id)["stages"]["scanned"]["status"]
    if state in ("done", "skipped"):
        return {"status": state, "caveats": store.read_version(book_id, version_id).get("caveats", [])}
    if stages.read(store, book_id, version_id)["stages"]["fetched"]["status"] != "done":
        raise KbError("the version has not been fetched yet, so there is nothing to scan")
    fmt = _format_of(store.read_version(book_id, version_id).get("primary"))
    if fmt is None:
        reason = "there is no scanner for this kind of file"
        stages.mark(store, book_id, version_id, "scanned", "skipped", reason=reason, tool=TOOL_LABEL)
        return {"status": "skipped", "reason": reason}
    existing = _generations(store, book_id, version_id)
    if existing:
        try:
            return _record(store, book_id, version_id, f"derived/{TOOL_NAME}/{existing[-1]}")
        except (KbError, OSError, ValueError):
            pass  # that output is unusable; scan again as the next generation
    name = f"derived/{TOOL_NAME}/{(existing[-1] if existing else 0) + 1}"
    try:
        entry = approvals.find(TOOL_NAME, TOOL_VERSION)
        if fmt not in entry["formats"]:
            raise KbError(f"{TOOL_LABEL} is not approved for {fmt} files")
        convert_run.run_to_payload(store, book_id, version_id, entry, name)
        return _record(store, book_id, version_id, name)
    except (KbError, OSError, ValueError) as e:  # any failure of the run is recorded, not raised
        return _fail(store, book_id, version_id, str(e))
