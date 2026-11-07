"""The card of a book: a short entry that says what the book is about and what it is useful for (`docs/specs/card.md`).

A card has two parts. The mechanical part is taken from the manifest and the scan and is never written by a model: the book, the
version, the title, the kind, the shelf, where the source came from, what the scan found and how complete the conversion was.
The model part is written by a model and is untrusted data. A card with no model part is built from the metadata alone and is
marked partial.

A card is kept in the book's own folder as a payload `derived/card/<n>`, one new number for each card made. It is filed through
the incoming area, read-only and marked untrusted, and an earlier card is never changed. The newest is the active one.

This module makes no model call; `cardmake` does."""
import json
import os
import re
from urllib.parse import urlsplit

from . import KbError, ids, models, stages, textutil
from . import read as citation  # the rules a read already follows for an address and for the identifiers of a source

FORMAT = 1
TOOL = "card"
FILENAME = "card.json"
MAX_CARD = 262144
MAX_GENERATION = 999_999
SOURCE_KEYS = ("address_asked", "address_final", "arxiv_id", "label", "retrieved", "sha256")  # what is kept of a source record
_ATTRS = ("tool", "version", "generation")
_VERSION = re.compile(r"v[1-9][0-9]{0,5}")
_SHELF = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_GENERATION = re.compile(r"[1-9][0-9]{0,5}")
_TOP = ("format", "book_id", "version_id", "title", "kind", "shelf", "primary_type", "source", "scan", "conversion", "partial",
        "partial_reasons", "model", "made")
_RECORD = ("task", "registry", "model", "prompt_version", "date", "input_tokens", "output_tokens")
MAX_REASONS = 20
MAX_CAVEATS = 100
MAX_RECORDS = 30

# the model-written fields of a card, in the shape the model-call layer checks (`card.md`, "What a card holds")
MODEL_SHAPE = {
    "summary": {"type": "string", "max": 1500},
    "useful_for": {"type": "strings", "max_items": 6, "max": 240},
    "topics": {"type": "strings", "max_items": 15, "max": 60},
    "adjacent_topics": {"type": "strings", "max_items": 10, "max": 60},
    "key_ideas": {"type": "strings", "min_items": 3, "max_items": 5, "max": 300},
    "neutral_problem": {"type": "string", "max": 500},
    "neutral_approach": {"type": "string", "max": 500},
    "neutral_needs": {"type": "string", "max": 500},
    "neutral_provides": {"type": "string", "max": 500},
    "neutral_limits": {"type": "string", "max": 500},
    "caveats": {"type": "strings", "max_items": 5, "max": 240},
}


_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[0-9T:.+Z-]{0,40}")
_ADDRESS_KEYS = ("address_asked", "address_final")


def _count(value, high=10 ** 9):
    return type(value) is int and 0 <= value <= high


def _clean(value, limit):
    """True for text that is already in the form `textutil.clean` gives, within `limit`."""
    return isinstance(value, str) and len(value) <= limit and textutil.clean(value, limit) == value


def _web(value):
    """True for a web address that carries no user name: the rule the citation of a read already follows (`read._address`)."""
    if not citation._WEB.match(value):
        return False
    try:
        return "@" not in urlsplit(value).netloc
    except ValueError:
        return False


def _source_ok(key, value):
    """True if a kept value of the source record has the shape of its key. The same rule is applied when a card is made and when
    one is read back."""
    if key in _ADDRESS_KEYS:
        return _web(value)
    pattern = {"arxiv_id": citation._ARXIV_ID, "label": citation._LABEL, "sha256": citation._SHA, "retrieved": _ISO}.get(key)
    return pattern is not None and pattern.fullmatch(value) is not None  # a key that is not on the list has no pattern


def _text(store, value, limit):
    """Text from a record cleaned of hidden and control characters, the library's folders taken out, and cut."""
    once = textutil.clean(textutil.scrub_roots(store, str(value if value is not None else "")), limit)
    return textutil.clean(textutil.scrub_roots(store, once), limit)  # cleaning can join a folder name that a hidden character split


def _conversion(store, version):
    """(summary of the conversion in use, reasons the card is partial)."""
    ref = version.get("conversion_in_use")
    records = version.get("conversions") if isinstance(version.get("conversions"), list) else []
    record = next((r for r in records if isinstance(r, dict) and isinstance(ref, dict) and {k: r.get(k) for k in _ATTRS} == ref), None)
    if record is None:
        return ({"in_use": False, "structure": None, "partial": False, "reasons": []},
                ["there is no conversion of the text, so the card is built from the metadata"])
    quality = record.get("quality") if record.get("quality") in ("full", "partial", "flat") else None
    check = version.get("conversion_check") if isinstance(version.get("conversion_check"), dict) else {}
    listed = check.get("reasons") if isinstance(check.get("reasons"), list) else []
    reasons = [_text(store, x, 500) for x in listed[:10]]
    reasons = [r for r in reasons if r]
    partial = bool(check.get("partial"))
    why = []
    if partial:
        why += [textutil.clean(f"the conversion is partial: {r}", 500) for r in reasons] or ["the conversion is partial"]
    if quality == "flat":
        why.append("the conversion has no structure (flat)")
    return {"in_use": True, "structure": quality, "partial": partial, "reasons": reasons}, why


def mechanical(store, book_id, version_id):
    """The part of a card that comes from the manifest and the scan, with the reasons the card is partial. A model has no say in it."""
    root = store.read_book(book_id)
    version = store.read_version(book_id, version_id)
    source = version.get("source") if isinstance(version.get("source"), dict) else {}
    kept = {}
    for key in SOURCE_KEYS:
        if isinstance(source.get(key), str):
            # an address is taken as a citation takes it (library folders out, cleaned, only a web address with no user name)
            value = citation._address(store, source[key])[:300] if key in _ADDRESS_KEYS else _text(store, source[key], 300)
            if value and _source_ok(key, value):
                kept[key] = value
    caveats = []
    for c in (version.get("caveats") if isinstance(version.get("caveats"), list) else [])[:MAX_CAVEATS]:
        if isinstance(c, dict) and isinstance(c.get("kind"), str):
            count = c.get("count")
            caveats.append({"kind": _text(store, c["kind"], 40), "count": count if _count(count) else 0,
                            "detail": _text(store, c.get("detail"), 500), "tool": _text(store, c.get("tool"), 100)})
    primary = version.get("primary") if isinstance(version.get("primary"), str) else ""
    ext = os.path.splitext(primary)[1].lstrip(".").lower()
    conversion, why = _conversion(store, version)
    title = textutil.title(textutil.scrub_roots(store, str(root.get("title") or "")), 500)
    title = textutil.title(textutil.scrub_roots(store, title), 500)  # cleaning can join a folder name that a hidden character split
    return {"format": FORMAT, "book_id": book_id, "version_id": version_id, "title": title,
            "kind": _text(store, root.get("kind"), 40), "shelf": root.get("shelf"),
            "primary_type": textutil.clean(ext, 20) or None, "source": kept,
            "scan": {"status": stages.read(store, book_id, version_id)["stages"]["scanned"]["status"], "caveats": caveats},
            "conversion": conversion, "partial": bool(why), "partial_reasons": why}


def _record(r):
    ok = (isinstance(r, dict) and set(r) == set(_RECORD) and isinstance(r["task"], str) and models._NAME.fullmatch(r["task"])
          and isinstance(r["registry"], str) and models._NAME.fullmatch(r["registry"]) and models._valid_model(r["model"])
          and isinstance(r["prompt_version"], str) and models._VERSION.fullmatch(r["prompt_version"])
          and isinstance(r["date"], str) and 0 < len(r["date"]) <= 40 and textutil.clean(r["date"], 40) == r["date"]
          and all(r[k] is None or _count(r[k], 10 ** 12) for k in ("input_tokens", "output_tokens")))
    if not ok:
        raise KbError("a record of how the card was made is not in the expected form")
    return {k: r[k] for k in _RECORD}


def _checked_model(part):
    """The model part, checked against the shape of a card and cleaned, or a refusal."""
    try:
        text = json.dumps(part)
    except (TypeError, ValueError):
        raise KbError("the model part of a card is not plain data") from None
    return models._check_answer(text, MODEL_SHAPE)


def make(store, book_id, version_id, model=None, records=(), pieces=0, calls=0, reasons=()):
    """A card for a version: the mechanical part and, if given, the model part and the records of how it was made. With no model
    part the card is built from the metadata alone and is marked partial. `reasons` are further reasons it is partial."""
    base = mechanical(store, book_id, version_id)
    if model is not None:
        if not isinstance(model, dict):
            raise KbError("the model part of a card is not an object")
        model = _checked_model(model)
    else:
        base["partial_reasons"].append("built from the metadata alone: the card has no model part")
    if not isinstance(records, (list, tuple)) or len(records) > MAX_RECORDS:
        raise KbError("the records of how the card was made are not a short list")
    if not _count(pieces, 1_000_000) or not _count(calls, 1_000_000):
        raise KbError("the number of pieces and calls is not a count")
    extra = [textutil.clean(r, 500) for r in reasons if isinstance(r, str)]
    base["partial_reasons"] = (base["partial_reasons"] + [r for r in extra if r])[:MAX_REASONS]
    base["partial"] = bool(base["partial_reasons"])
    base["model"] = model
    base["made"] = {"pieces": pieces, "calls": calls, "records": [_record(r) for r in records]}
    return validate(base)


def _strings(value, count, limit):
    return isinstance(value, list) and len(value) <= count and all(_clean(x, limit) for x in value)


def validate(card):
    """The card, if it has exactly the shape of a card of this format; otherwise a refusal."""
    if not isinstance(card, dict) or set(card) != set(_TOP):
        raise KbError("the card does not have the keys of a card")
    bad = lambda what: KbError(f"the card is not valid: {what}")
    if type(card["format"]) is not int or card["format"] != FORMAT:
        raise bad("its format is not " + str(FORMAT))
    ids.check_id(card["book_id"])
    if not isinstance(card["version_id"], str) or not _VERSION.fullmatch(card["version_id"]):
        raise bad("version_id")
    # text that came from a book or its source must already be in its clean form, so a card read back cannot carry what a card
    # made would have lost (the title also under the rule that blanks the words of an untrusted-text marker)
    if not isinstance(card["title"], str) or len(card["title"]) > 500 or textutil.title(card["title"], 500) != card["title"]:
        raise bad("title")
    if not _clean(card["kind"], 40) or not card["kind"]:
        raise bad("kind")
    if not isinstance(card["shelf"], str) or not _SHELF.fullmatch(card["shelf"]):
        raise bad("shelf")
    if card["primary_type"] is not None and not _clean(card["primary_type"], 20):
        raise bad("primary_type")
    source = card["source"]
    if not isinstance(source, dict) or set(source) - set(SOURCE_KEYS) or not all(
            _clean(v, 300) and _source_ok(k, v) for k, v in source.items()):
        raise bad("source")
    scan = card["scan"]
    if not isinstance(scan, dict) or set(scan) != {"status", "caveats"} or scan["status"] not in stages.STATUSES \
            or not isinstance(scan["caveats"], list) or len(scan["caveats"]) > MAX_CAVEATS:
        raise bad("scan")
    for c in scan["caveats"]:
        if not (isinstance(c, dict) and set(c) == {"kind", "count", "detail", "tool"} and _clean(c["kind"], 40)
                and _count(c["count"]) and _clean(c["detail"], 500) and _clean(c["tool"], 100)):
            raise bad("a scan caveat")
    conv = card["conversion"]
    if not (isinstance(conv, dict) and set(conv) == {"in_use", "structure", "partial", "reasons"} and type(conv["in_use"]) is bool
            and conv["structure"] in (None, "full", "partial", "flat") and type(conv["partial"]) is bool
            and _strings(conv["reasons"], 10, 500)):
        raise bad("conversion")
    if type(card["partial"]) is not bool or not _strings(card["partial_reasons"], MAX_REASONS, 500):
        raise bad("partial")
    if card["partial"] and not card["partial_reasons"]:
        raise bad("a partial card must say why")
    model = card["model"]
    if model is None:
        if not card["partial"]:
            raise bad("a card with no model part must be partial")
    else:
        if not isinstance(model, dict) or _checked_model(model) != model:
            raise bad("model")
    made = card["made"]
    if not (isinstance(made, dict) and set(made) == {"pieces", "calls", "records"} and _count(made["pieces"], 1_000_000)
            and _count(made["calls"], 1_000_000) and isinstance(made["records"], list) and len(made["records"]) <= MAX_RECORDS):
        raise bad("made")
    for r in made["records"]:
        _record(r)
    return card


def generations(store, book_id, version_id):
    """The numbers of the cards filed for a version, lowest first. A folder whose name is not a plain number is ignored."""
    folder = os.path.join(store.version_dir(book_id, version_id), "derived", TOOL)
    if not os.path.isdir(folder):
        return []
    return sorted(int(n) for n in os.listdir(folder)
                  if _GENERATION.fullmatch(n) and os.path.isdir(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n)))


def file(store, card):
    """File a card as the next generation of its version, and return the number. The card is checked first; a card that is not
    valid files nothing. An earlier card is never changed."""
    validate(card)
    book_id, version_id = card["book_id"], card["version_id"]
    store.read_version(book_id, version_id)
    existing = generations(store, book_id, version_id)
    number = (existing[-1] + 1) if existing else 1
    if number > MAX_GENERATION:
        raise KbError("this version has as many cards as it can have")
    data = (json.dumps(card, indent=1) + "\n").encode()
    if len(data) > MAX_CARD:
        raise KbError("the card is larger than a card may be")
    store.file_payload(book_id, version_id, f"derived/{TOOL}/{number}", {FILENAME: data}, tool=f"kb-card {FORMAT}", untrusted=True)
    return number


def read(store, book_id, version_id, generation=None):
    """`(number, card)` of the newest card of a version, or of the generation asked for. The payload is checked against its hashes,
    must hold exactly the card file, and the card is checked; a card that fails any check is refused."""
    existing = generations(store, book_id, version_id)
    if not existing:
        raise KbError("the version has no card")
    if generation is None:
        generation = existing[-1]
    elif type(generation) is not int or generation not in existing:
        raise KbError(f"the version has no card of generation {generation!r}")
    name = f"derived/{TOOL}/{generation}"
    manifest = store.verify_payload(book_id, version_id, name)
    if set(manifest["files"]) != {FILENAME}:
        raise KbError(f"the card payload must be the one file {FILENAME} and nothing else")
    if manifest["files"][FILENAME]["size"] > MAX_CARD:
        raise KbError("the card is larger than a card may be")
    with open(os.path.join(store.payload_path(book_id, version_id, name), FILENAME), "rb") as f:
        raw = f.read(MAX_CARD + 1)
    try:
        doc = models._loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        doc = None
    if not isinstance(doc, dict):
        raise KbError("the card file is not one JSON object")
    validate(doc)
    if doc["book_id"] != book_id or doc["version_id"] != version_id:
        raise KbError("the card belongs to another book or version")
    return generation, doc
