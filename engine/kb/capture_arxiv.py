"""Capture an arXiv paper: its PDF stored unchanged, and its metadata from arXiv's own record.

A paper is a book and each arXiv version (v1, v2, ...) is a version of it. The metadata comes from the arXiv API, an
Atom answer that is untrusted text: it is size-capped, refused if it declares entities, parsed with the standard library
and cleaned and bounded before it is stored. The PDF is fetched with the same bounded fetch as a web page and must start
like a PDF. A version already held is not requested at all; a capture that stopped half way is resumed.

The two address prefixes (the API and the PDF) are settings, so the tests and a mirror can point elsewhere."""
import hashlib
import re
import xml.etree.ElementTree as ET

from . import KbError, __version__, capture_url, identity, ids, stages, textutil
from .capture_url import FetchError
from .store import now

API_BASE = "https://export.arxiv.org/api/query"
PDF_BASE = "https://arxiv.org/pdf"
TOOL = f"capture-arxiv {__version__}"
PDF_MAX_BYTES = 50_000_000
METADATA_MAX_BYTES = 1_000_000
METADATA_TYPES = ("application/atom+xml", "application/xml", "text/xml")
TITLE_MAX, AUTHOR_MAX, AUTHORS_MAX, ABSTRACT_MAX = 500, 200, 200, 20_000

_NEW = r"\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}"
_OLD = r"[a-z]+(?:-[a-z]+)*(?:\.[A-Z]{2})?/\d{2}(?:0[1-9]|1[0-2])\d{3}"
_ID = re.compile(rf"(?P<id>{_NEW}|{_OLD})(?:v(?P<v>[1-9]\d{{0,5}}))?", re.ASCII)  # ASCII: \d is 0-9 only
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def parse_id(text):
    """Split an arXiv id into the paper's id and the version number (or None). Whitespace is not tolerated, and the
    only prefix allowed is `arXiv:`. Anything else is refused."""
    if not isinstance(text, str):
        raise KbError("an arXiv id must be text")
    body = text[6:] if text[:6].lower() == "arxiv:" else text
    m = _ID.fullmatch(body)
    if not m:
        raise KbError(f"not an arXiv id: {text!r} (expected 2101.00001, 2101.00001v2 or cs/0112017)")
    return m.group("id"), int(m.group("v")) if m.group("v") else None


def _clean(text, limit):
    return textutil.clean(text, limit)


def _check_base(url):
    """A configured address prefix: http or https, a host, no credentials. Returns it without a trailing slash."""
    return identity.normalize_address(url).rstrip("/")


def parse_atom(body, base_id, wanted_version):
    """Read the arXiv API's answer about one paper into a dict, or raise FetchError. The text is untrusted."""
    # plain UTF-8 only: a UTF-16 answer has NUL bytes between its letters, which would hide a declaration from the check
    if b"\x00" in body:
        raise FetchError("the metadata answer is not plain UTF-8 text (it contains NUL bytes)")
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        raise FetchError("the metadata answer is not valid UTF-8") from None
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", body, re.I):
        raise FetchError("the metadata answer carries a declaration (DOCTYPE or ENTITY), which is refused")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise FetchError(f"the metadata answer cannot be read: {e}") from None
    entry = root.find(f"{_ATOM}entry")
    if entry is None:
        raise FetchError("paper not found at arXiv (the metadata answer has no entry)")

    def text(parent, name, ns=_ATOM):
        el = parent.find(f"{ns}{name}")
        return el.text if el is not None and el.text else ""

    entry_id = text(entry, "id").strip()
    if "/api/errors" in entry_id:
        raise FetchError("arXiv reports an error: " + _clean(text(entry, "summary"), 300))
    m = re.fullmatch(r"https?://arxiv\.org/abs/(?P<id>.+)v(?P<v>[0-9]{1,6})", entry_id)
    if not m:
        raise FetchError("the metadata answer has no usable paper id")
    if m.group("id") != base_id:
        raise FetchError("arXiv answered with another paper than the one asked for")
    version = int(m.group("v"))
    if wanted_version is not None and version != wanted_version:
        raise FetchError(f"arXiv answered with version v{version}, not v{wanted_version}")

    authors = [a for a in (_clean(text(a, "name"), AUTHOR_MAX) for a in entry.findall(f"{_ATOM}author")) if a]
    published = text(entry, "published").strip()
    year = int(published[:4]) if re.fullmatch(r"[0-9]{4}-.*", published, re.S) and 1900 <= int(published[:4]) <= 2100 else None
    categories = list(dict.fromkeys(t for t in (c.get("term", "") for c in entry.findall(f"{_ATOM}category"))
                                    if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,40}", t)))
    primary = entry.find(f"{_ARXIV}primary_category")
    primary_term = primary.get("term", "") if primary is not None else ""
    doi = text(entry, "doi", _ARXIV).strip()
    return {
        "arxiv_id": base_id, "label": f"v{version}", "version": version,
        "title": _clean(text(entry, "title"), TITLE_MAX), "authors": authors[:AUTHORS_MAX], "year": year,
        "abstract": _clean(text(entry, "summary"), ABSTRACT_MAX), "categories": categories,
        "primary_category": primary_term if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,40}", primary_term) else None,
        "doi": doi if re.fullmatch(r"10\.[0-9]{4,9}/[!-~]{1,180}", doi) else None,
        "published": _clean(published, 40), "updated": _clean(text(entry, "updated"), 40),
    }


def _label_number(label):
    m = re.fullmatch(r"v([0-9]+)", label or "")
    return int(m.group(1)) if m else 0


def _fetched_status(store, book_id, version_id):
    return stages.read(store, book_id, version_id)["stages"]["fetched"]["status"]


def _version_for(store, book_id, label):
    """The version of a book with this arXiv label, else an unfinished version that has no label yet, else None."""
    unlabelled = None
    for vid in store.version_ids(book_id):
        existing = store.read_version(book_id, vid)["label"]
        if existing == label:
            return vid
        if existing is None and unlabelled is None and _fetched_status(store, book_id, vid) not in ("done", "skipped"):
            unlabelled = vid
    return unlabelled


def _choose_current(store, book_id):
    """The current version is the one with the newest label among those that were fetched; if none was, the newest."""
    best, best_key = None, None
    for vid in store.version_ids(book_id):
        done = _fetched_status(store, book_id, vid) == "done"
        key = (done, _label_number(store.read_version(book_id, vid)["label"]), int(vid[1:]))
        if best_key is None or key > best_key:
            best, best_key = vid, key
    if best and store.read_book(book_id)["current_version"] != best:
        store.set_current_version(book_id, best)
    return best


def _result(status, book_id, version_id, reason=None):
    out = {"status": status, "book_id": book_id, "version_id": version_id}
    if reason is not None:
        out["reason"] = reason
    return out


def _claim(store, ident, kind, value, book_id):
    """Index a key for a book unless another book that exists already holds it (the first book to claim a key keeps it).
    Returns whether the key now belongs to this book."""
    owner = capture_url._live(store, ident, kind, value)
    if owner in (None, book_id):
        ident.reassign(kind, value, book_id)
        return True
    return False


def _register(store, ident, book_id, version_id):
    """Record a stored version's identity keys and index entries. The arXiv id decides the book. The DOI in the metadata
    answer is kept in the version's source record as a claim, and is not an identity key: it comes from an answer nobody
    has verified, so it must not decide which book anything belongs to."""
    source = store.read_version(book_id, version_id)["source"]
    ident.reassign("arxiv", source["arxiv_id"], book_id)
    store.merge_identity_keys(book_id, add_keys={"sha256": [source["sha256"]]})
    _claim(store, ident, "sha256", source["sha256"], book_id)


def _finish(store, book_id, version_id):
    """Once a version is fetched: make the newest label current, and take the book's title, authors and year from the
    current version, once. The version the fields came from is recorded in the root file, so a repeat does not undo a
    later edit of them, and a stop between the stage and this step is repaired by the next call."""
    source = store.read_version(book_id, version_id)["source"]
    if _choose_current(store, book_id) == version_id and store.read_book(book_id).get("metadata_source") != version_id:
        store.set_metadata(book_id, title=source["title"], authors=source["authors"], year=source["year"],
                           metadata_source=version_id)


def _resume(store, ident, book_id, version_id):
    """Check and adopt a file stored before an earlier capture stopped. A result to hand back, or None."""
    outcome = stages.reconcile(store, book_id, version_id, "fetched", "original")
    if outcome == "adopted":
        _register(store, ident, book_id, version_id)
        source = store.read_version(book_id, version_id)["source"]
        if not any(e["event"] == "filed" and e.get("sha256") == source["sha256"] for e in store.read_events(book_id)):
            store.append_event(book_id, "filed", arxiv_id=source["arxiv_id"], label=source["label"],
                               sha256=source["sha256"], retrieved=source["retrieved"], resumed=True)
        _finish(store, book_id, version_id)
        return _result("held", book_id, version_id)
    if outcome == "invalid":
        return _result("failed", book_id, version_id,
                       stages.read(store, book_id, version_id)["stages"]["fetched"]["reason"])
    return None


def _held_or_resumed(store, ident, book_id, label):
    """If the version with this label is stored (or was stored before a stop), the result to hand back; else None."""
    version_id = _version_for(store, book_id, label)
    if version_id is None or store.read_version(book_id, version_id)["label"] != label:
        return None
    if _fetched_status(store, book_id, version_id) in ("done", "skipped"):
        _finish(store, book_id, version_id)
        return _result("held", book_id, version_id)
    return _resume(store, ident, book_id, version_id)


def _record_failure(store, ident, book_id, base_id, label, meta, error):
    """A fetch that failed: keep the failure in the stage state of a version, so a later call can retry into it."""
    if not book_id:
        book_id = ids.new_book_id()
        ident.reassign("arxiv", base_id, book_id)  # recorded first, so a stop after the book is made still finds it
        store.create_book(title=(meta or {}).get("title", ""), kind="preprint", authors=(meta or {}).get("authors"),
                          year=(meta or {}).get("year"), identity_keys={"arxiv": base_id}, book_id=book_id)
        store.append_event(book_id, "found", arxiv_id=base_id)
    version_id = _version_for(store, book_id, label) if label else _version_for(store, book_id, None)
    if version_id is None:
        version_id = store.add_version(book_id, label=label, source={"arxiv_id": base_id})
        _choose_current(store, book_id)
    reason = textutil.clean(str(error), 300)  # the reason can carry text the server chose
    stages.mark(store, book_id, version_id, "fetched", "failed", reason=reason, tool=TOOL)
    return _result("failed", book_id, version_id, reason)


def capture(store, ident, arxiv_id, allow_private=False, api_base=API_BASE, pdf_base=PDF_BASE,
            max_bytes=PDF_MAX_BYTES, metadata_max_bytes=METADATA_MAX_BYTES, timeout=capture_url.TIMEOUT,
            total_timeout=capture_url.TOTAL_TIMEOUT):
    """Capture one version of an arXiv paper. With no version in the id, the latest is captured. Returns a dict whose
    status is filed, held (that version is already stored, and nothing was downloaded) or failed (the reason is
    recorded in the stage state, and a later call retries it). A bad id or address raises KbError and records nothing."""
    base_id, wanted = parse_id(arxiv_id)
    api, pdf = _check_base(api_base), _check_base(pdf_base)
    store._guard()
    capture_url.require_allowed(api, allow_private, total_timeout)
    capture_url.require_allowed(pdf, allow_private, total_timeout)

    book_id = capture_url._live(store, ident, "arxiv", base_id)
    if book_id and wanted:  # a version that is already stored needs no request at all
        held = _held_or_resumed(store, ident, book_id, f"v{wanted}")
        if held:
            return held

    try:
        page = capture_url.fetch(f"{api}?id_list={base_id}" + (f"v{wanted}" if wanted else ""), allow_private,
                                 metadata_max_bytes, timeout, total_timeout, types=METADATA_TYPES,
                                 what="metadata answer", accept="application/atom+xml, application/xml;q=0.9")
        meta = parse_atom(page.body, base_id, wanted)
    except FetchError as e:
        return _record_failure(store, ident, book_id, base_id, f"v{wanted}" if wanted else None, None, e)
    label = meta["label"]
    if book_id and not wanted:  # the latest was asked for, and only now is its label known
        held = _held_or_resumed(store, ident, book_id, label)
        if held:
            return held

    pdf_address = f"{pdf}/{base_id}{label}"
    try:
        page = capture_url.fetch(pdf_address, allow_private, max_bytes, timeout, total_timeout,
                                 types=("application/pdf",), what="PDF", accept="application/pdf")
        if not page.body.startswith(b"%PDF-"):
            raise FetchError("not a PDF: the file does not start like one")
    except FetchError as e:
        return _record_failure(store, ident, book_id, base_id, label, meta, e)

    digest = hashlib.sha256(page.body).hexdigest()
    source = {**{k: meta[k] for k in ("arxiv_id", "label", "title", "authors", "year", "abstract", "categories",
                                      "primary_category", "doi", "published", "updated")},
              "address_pdf": pdf_address, "http_status": page.status, "retrieved": now(), "headers": page.headers,
              "sha256": digest, "bytes": len(page.body)}
    if not book_id:
        book_id = ids.new_book_id()
        ident.reassign("arxiv", base_id, book_id)  # recorded first, so a stop after the book is made still finds it
        store.create_book(title=meta["title"], kind="preprint", authors=meta["authors"], year=meta["year"],
                          identity_keys={"arxiv": base_id}, book_id=book_id)  # the DOI is added once it is claimed
    version_id = _version_for(store, book_id, label)
    if version_id is None:
        version_id = store.add_version(book_id, label=label, source=source)
        _choose_current(store, book_id)  # a new version is made current when it is added; undo that until it is fetched
    else:
        store.set_version_label(book_id, version_id, label)
        store.set_version_source(book_id, version_id, source)
    store.file_payload(book_id, version_id, "original", {"paper.pdf": page.body}, primary="paper.pdf", tool=TOOL)
    _register(store, ident, book_id, version_id)
    store.append_event(book_id, "filed", arxiv_id=base_id, label=label, sha256=digest, retrieved=source["retrieved"])
    stages.mark(store, book_id, version_id, "fetched", "done", tool=TOOL)
    _finish(store, book_id, version_id)
    return _result("filed", book_id, version_id)
