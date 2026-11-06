"""Read: the text at a locator, in a bounded piece, with where it came from.

    read(store, book_id, locator, version_id=None, chars=2000)

The locator is one a search returned (a dict, or its JSON). The version is the one named, or the book's current one. The locator
names the conversion it was made against: if that conversion is still recorded for the version it is read from, and the locator
is followed by its place, or by its words if the place no longer holds; if the passage is not in that conversion, or the conversion
is gone, the passage is looked for by the words the locator carries in the conversion now in use. The answer says when it was
found by its words and gives a locator for the conversion read. A recorded conversion whose files have changed since it was
filed is a refusal, not a reason to look elsewhere. A passage that is not there is "not_found" and no text is given. A locator of a kind this reader does not know is "unknown_kind" with its raw value shown (cleaned and cut)
and nothing is guessed.

The text is a window of at most `chars` characters of the converted text, from the start of the block that was found, cut at a
word, between a first line that is the untrusted marker and a last line that is the end marker (a page can put those words in its
own text, so the first and last lines are the ones that count). `next` is a locator for where the following piece begins, or None
at the end, so reading on is following `next`. The citation line names the book, the source address, the date it was retrieved
and the hash of the file that was captured; everything in it comes from records and is cleaned.

Nothing returned, and no message of a refusal, holds a path to the library."""
import json
import re
from urllib.parse import urlsplit

from . import KbError, convert, locator, stages, textutil
from .search import MARKER

END_MARKER = "[end of untrusted text]"
DEFAULT_CHARS = 2000
MIN_CHARS = 100
MAX_CHARS = 20000
RAW_CHARS = 500
MAX_LOCATOR_JSON = 100_000
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA = re.compile(r"[0-9a-f]{64}")
_WEB = re.compile(r"https?://", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w./])/(?!/)[^\s/'\"():;,\[\]]+(?:/[^\s/'\"():;,\[\]]+)+")  # two parts at least: /Users/me
_ARXIV_ID = re.compile(r"(?:[A-Za-z][A-Za-z.-]{0,30}/[0-9]{7}|[0-9]{4}\.[0-9]{4,5})")
_LABEL = re.compile(r"v[0-9]{1,3}")
MAX_CAVEATS = 100
_FILE = re.compile(r"\bfile:/+[^\s'\"():;,]*", re.IGNORECASE)
_DRIVE = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s'\"():;,]*")
_HOME = re.compile(r"(?<![\w.:/])~/[^\s'\"():;,]*")


def _parse(where):
    if isinstance(where, str):
        if len(where) > MAX_LOCATOR_JSON:
            raise KbError(f"a locator is at most {MAX_LOCATOR_JSON} characters")
        try:
            where = json.loads(where)
        except (ValueError, RecursionError):
            raise KbError("that is not a locator: it is not JSON") from None
    if not isinstance(where, dict):
        raise KbError("that is not a locator: it is not an object")
    return where


def _scrub_roots(store, text):
    """Text with the library's folders taken out."""
    return textutil.scrub_roots(store, text)


def _address(store, value):
    """An address from a record, for a citation: the library's folders taken out first (before whitespace is collapsed, so a
    folder with odd spacing still matches), then cleaned; and only a web address is shown, anything else is not."""
    text = textutil.clean(_scrub_roots(store, str(value)), 500)
    if not _WEB.match(text):
        return "non-web address"
    try:
        userinfo = "@" in urlsplit(text).netloc
    except ValueError:
        return "non-web address"
    return "non-web address" if userinfo else text  # an address with a user name in it is not shown


def _citation(store, root, version):
    source = version.get("source") or {}
    title = textutil.title(_scrub_roots(store, str(root.get("title") or "")), 200) or "untitled"
    if isinstance(source.get("arxiv_id"), str) and _ARXIV_ID.fullmatch(source["arxiv_id"]):
        label = source.get("label") if isinstance(source.get("label"), str) and _LABEL.fullmatch(source["label"]) else ""
        where = f"arXiv:{source['arxiv_id']}{label}"
        if isinstance(source.get("address_pdf"), str) and source["address_pdf"]:
            address = _address(store, source["address_pdf"])
            if address != "non-web address":
                where += f", {address}"
    elif isinstance(source.get("address_final") or source.get("address_asked"), str):
        where = _address(store, source.get("address_final") or source.get("address_asked"))
    else:
        where = "no source address recorded"
    retrieved = source.get("retrieved")
    date = retrieved[:10] if isinstance(retrieved, str) and _DATE.fullmatch(retrieved[:10]) else "date not recorded"
    digest = source.get("sha256") if isinstance(source.get("sha256"), str) and _SHA.fullmatch(source["sha256"]) else None
    return f"{title}. {where or 'no source address recorded'}. Retrieved {date}. sha256 {digest or 'hash not recorded'}"


def _caveats(store, version):
    """The scan's caveats as a search gives them, rebuilt from their four fields, cleaned, and at most MAX_CAVEATS."""
    listed = version.get("caveats") if isinstance(version.get("caveats"), list) else []
    out = []
    for c in listed:
        if len(out) >= MAX_CAVEATS:
            break
        if not isinstance(c, dict) or not isinstance(c.get("kind"), str):
            continue
        count = c.get("count")
        out.append({"kind": textutil.clean(_scrub_roots(store, c["kind"]), 40),
                    "count": count if type(count) is int and 0 <= count <= 10 ** 9 else 0,
                    "detail": textutil.clean(_scrub_roots(store, str(c.get("detail") or "")), 500),
                    "tool": textutil.clean(_scrub_roots(store, str(c.get("tool") or "")), 100)})
    return out


def _completeness(version, ref):
    """How complete the conversion read was, in the shape a search result gives it."""
    quality = next((r.get("quality") for r in version.get("conversions", [])
                    if isinstance(r, dict) and {k: r.get(k) for k in ("tool", "version", "generation")} == ref), None)
    check = version.get("conversion_check") if isinstance(version.get("conversion_check"), dict) else {}
    reasons = check.get("reasons") if isinstance(check.get("reasons"), list) else []
    return {"structure": quality if quality in ("full", "partial", "flat") else None, "partial": bool(check.get("partial")),
            "compared": bool(check.get("compared")), "reasons": [textutil.clean(str(x), 500) for x in reasons[:10]]}


def _read(store, book_id, loc, version_id, chars):
    root = store.read_book(book_id)
    if root.get("state") != "active":
        raise KbError(f"the book is not active ({textutil.clean(str(root.get('state')), 20)})")
    version_id = version_id if version_id is not None else root.get("current_version")
    if version_id is None:
        raise KbError("the book has no current version to read")
    if not isinstance(version_id, str) or version_id not in store.version_ids(book_id):
        raise KbError(f"the book has no version {textutil.literal(version_id, 30)}")
    kind = loc.get("kind")
    if isinstance(kind, str) and kind not in locator.KINDS:
        try:
            raw = json.dumps(loc, sort_keys=True, default=str, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError):  # a dict made in a program can be of a shape JSON cannot hold
            raw = repr(loc)
        return {"status": "unknown_kind", "book_id": book_id, "version_id": version_id, "kind": textutil.clean(kind, 80),
                "raw": textutil.clean(_scrub_roots(store, raw)[:5 * RAW_CHARS], RAW_CHARS)}
    locator.check(loc)
    version = store.read_version(book_id, version_id)
    if stages.read(store, book_id, version_id)["stages"]["converted"]["status"] != "done":
        raise KbError("the version has not been converted yet, so there is nothing to read")
    loaded = convert.load_in_use(store, book_id, version_id)
    if loaded is None:
        raise KbError("the version has no conversion in use to read")
    in_use, in_use_conversion, _record = loaded
    ref, conversion = in_use, in_use_conversion
    named = loc["conversion"]
    if named != in_use:
        for record in version.get("conversions", []):
            if {k: record[k] for k in ("tool", "version", "generation")} == named:
                # a conversion that is recorded is read from, and one that cannot be loaded (its file was changed) is a
                # refusal and is not passed over for another
                ref, conversion = named, convert.load_conversion(store, book_id, version_id, record)
                break
    found = locator.resolve(loc, ref, conversion)
    if found["status"] == "not_found" and ref != in_use:
        ref, conversion = in_use, in_use_conversion  # not in the conversion it names: look in the one in use, by its words
        found = locator.resolve(loc, ref, conversion)
    title = _scrub_roots(store, textutil.title(_scrub_roots(store, str(root.get("title") or "")), 200))  # again: cleaning can join a split folder
    base = {"book_id": book_id, "version_id": version_id, "title": title, "conversion": ref, "untrusted": True,
            "caveats": _caveats(store, version), "completeness": _completeness(version, ref),
            "citation": _scrub_roots(store, _citation(store, root, version))}
    if found["status"] == "not_found":
        return {**base, "status": "not_found", "reason": "the passage is not in the text of the book as it is now"}
    block = conversion.blocks[found["block"]]
    start = loc["at"]["offset"] if found["status"] == "found" and loc["kind"] == "offset" else block.start
    end, following = textutil.window(conversion.text, start, chars)
    body = conversion.text[start:end].rstrip()
    return {
        **base, "status": found["status"], "matches": found["matches"],
        "locator": loc if found["status"] == "found" else locator.make(ref, conversion, block.index),
        "text": f"{MARKER}\n{body}\n{END_MARKER}", "offset": start, "end": start + len(body), "total": len(conversion.text),
        "next": None if following is None else locator.at_offset(ref, conversion, following),
    }


def _scrub(store, message):
    """A message with the library's folders, and any other path (an absolute one, a file address, a drive or home path), taken
    out."""
    text = _scrub_roots(store, message)
    for pattern in (_FILE, _DRIVE, _HOME, _PATH):
        text = pattern.sub("<path>", text)
    return text


def read(store, book_id, where, version_id=None, chars=DEFAULT_CHARS):
    """The piece of a book's text at a locator. Raises KbError for what cannot be read, and returns a dict for everything else,
    including a passage that is not found and a locator of a kind not known (see the module's description)."""
    if type(chars) is not int or not MIN_CHARS <= chars <= MAX_CHARS:
        raise KbError(f"the amount to read is a whole number of characters from {MIN_CHARS} to {MAX_CHARS}")
    loc = _parse(where)
    try:
        return _read(store, book_id, loc, version_id, chars)
    except KbError as e:
        raise KbError(_scrub(store, str(e))) from None
    except OSError as e:
        raise KbError(f"the book could not be read ({_scrub(store, str(e.strerror))})") from None
    except (KeyError, TypeError, AttributeError, ValueError, RecursionError):
        raise KbError("the book's records are not in the form this engine writes, so it cannot be read") from None
