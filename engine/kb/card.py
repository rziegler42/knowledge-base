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
FORMAT_GROUNDED = 2   # a card whose key ideas, topics, caveats and limit are marked as stated or inferred (`docs/specs/card.md`)
FORMATS = (FORMAT, FORMAT_GROUNDED)
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
_TOP_GROUNDED = _TOP + ("grounding",)
_RECORD = ("task", "registry", "model", "prompt_version", "date", "input_tokens", "output_tokens")
_COUNT_PAIRS = (("points", "verified"), ("checked", "supported"))   # a record may carry one pair, in a card of format 2: the notes of a piece
# (points, and how many have a quote that occurs) or a call that checks the support of items (items checked, and how many were supported)
GROUNDED_LISTS = ("topics", "key_ideas", "caveats")
MARKS = ("stated", "inferred")
# the fields of the model part that a card of the new form writes as sentences, each marked and backed by notes; the sentences of a
# field joined with a space are the field
SENTENCE_FIELDS = ("summary", "neutral_problem", "neutral_approach", "neutral_needs", "neutral_provides", "neutral_limits")
MAX_SENTENCES = 12
MAX_SENTENCE = 500
MAX_QUOTE = 240
MAX_REFS = 6
_UNMARK = re.compile(r"\[\s*(stated|inferred)\s*\]", re.I)   # text that looks like the mark of an item is shown with round brackets
_REF = re.compile(r"[1-9][0-9]{0,2}\.[1-9][0-9]?")   # the number of a point: the piece, a dot, the point
MAX_REASONS = 20
MAX_CAVEATS = 100
MAX_RECORDS = 30   # at most 28 are needed: 20 notes at the largest cap of pieces, the card call, 4 checks of it, a second round and 2 checks

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


# the model-written fields of a grounded card: higher ceilings, key ideas may be few (a thin card says so), and a limit may be empty
MODEL_SHAPE_GROUNDED = {**MODEL_SHAPE, "topics": {"type": "strings", "max_items": 20, "max": 60},
                        "key_ideas": {"type": "strings", "max_items": 8, "max": 300}}


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
    # a conversion with no headings (flat) is not a reason: every PDF is flat, and the card still describes the whole work; the
    # structure is recorded in the card and shown, and an agent can weigh it
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


def _record(r, grounded=False):
    present = [p for p in _COUNT_PAIRS if isinstance(r, dict) and any(k in r for k in p)]
    extra = set(present[0]) if len(present) == 1 and grounded else set()
    ok = (isinstance(r, dict) and len(present) <= 1 and (not present or grounded) and set(r) == set(_RECORD) | extra and isinstance(r["task"], str) and models._NAME.fullmatch(r["task"])
          and isinstance(r["registry"], str) and models._NAME.fullmatch(r["registry"]) and models._valid_model(r["model"])
          and isinstance(r["prompt_version"], str) and models._VERSION.fullmatch(r["prompt_version"])
          and isinstance(r["date"], str) and _ISO.fullmatch(r["date"]) is not None
          and all(r[k] is None or _count(r[k], 10 ** 12) for k in ("input_tokens", "output_tokens"))
          and (not present or (_count(r[present[0][0]], 1000) and _count(r[present[0][1]], 1000) and r[present[0][1]] <= r[present[0][0]])))
    if not ok:
        raise KbError("a record of how the card was made is not in the expected form")
    return {k: r[k] for k in _RECORD + (present[0] if present else ())}


def _checked_model(part, grounded=False, sentences=False):
    """The model part, checked against the shape of a card and cleaned, or a refusal. In a grounded card the limit may be empty; in
    a card with sentences each of the fields written as sentences may be, since a field with no sentence left is empty."""
    fields = SENTENCE_FIELDS if sentences else ("neutral_limits",)
    empty = [f for f in fields if grounded and isinstance(part, dict) and part.get(f) == ""]
    if empty:
        checked = _checked_model({**part, **{f: "-" for f in empty}}, True, sentences)
        return {**checked, **{f: "" for f in empty}}
    try:
        text = json.dumps(part)
    except (TypeError, ValueError):
        raise KbError("the model part of a card is not plain data") from None
    return models._check_answer(text, MODEL_SHAPE_GROUNDED if grounded else MODEL_SHAPE)


def _entry(e, what):
    """One entry of the grounding record: the mark of an item, the notes that support it and the quote of the first of them."""
    bad = KbError(f"the card is not valid: the mark of {what}")
    if not isinstance(e, dict) or set(e) != {"mark", "notes", "quote"} or e["mark"] not in MARKS:
        raise bad
    notes = e["notes"]
    if not isinstance(notes, list) or len(notes) > MAX_REFS or not all(isinstance(n, str) and _REF.fullmatch(n) for n in notes) \
            or len(set(notes)) != len(notes):
        raise bad
    if e["mark"] == "stated":
        if not notes or not isinstance(e["quote"], str) or not e["quote"] or not _clean(e["quote"], MAX_QUOTE):
            raise bad
    elif notes or e["quote"] is not None:
        raise bad


def _grounding(g, model):
    """The grounding record of a card of format 2, checked against its model part."""
    bad = lambda what: KbError(f"the card is not valid: grounding, {what}")
    keys = set(GROUNDED_LISTS) | {"neutral_limits", "dropped"}
    if not isinstance(g, dict) or not keys <= set(g) or not set(g) - keys <= {"added", "sentences"}:
        raise bad("its keys")
    for field in GROUNDED_LISTS:
        if not isinstance(g[field], list) or len(g[field]) != len(model[field]):
            raise bad(f"{field} has not one entry for each item")
        for n, e in enumerate(g[field], start=1):
            _entry(e, f"{field} {n}")
    if "sentences" in g:
        if g["neutral_limits"] is not None:
            raise bad("an entry for the limit in a card whose limit is written as sentences")
    elif model["neutral_limits"] == "":
        if g["neutral_limits"] is not None:
            raise bad("a mark for a limit that is not there")
    else:
        _entry(g["neutral_limits"], "the limit")
    dropped = g["dropped"]
    if not isinstance(dropped, dict) or set(dropped) != set(GROUNDED_LISTS) | {"neutral_limits"} \
            or not all(_count(v, 1000) for v in dropped.values()):
        raise bad("the counts of what was dropped")
    if "sentences" in g:
        _sentences(g["sentences"], model, bad)
    if "added" in g:
        _added(g["added"], g, model, bad)


def _sentences(record, model, bad):
    """The sentences of the summary and the neutral fields: for each, those kept (each with its text, mark, notes and the quote of
    the first note) and how many were dropped. The sentences of a field joined with a space are exactly the field."""
    if not isinstance(record, dict) or set(record) != set(SENTENCE_FIELDS):
        raise bad("the sentences are not given for the summary and the five neutral fields")
    for field, part in record.items():
        if not isinstance(part, dict) or set(part) != {"kept", "dropped"} or not _count(part["dropped"], 1000):
            raise bad(f"the sentences of {field}")
        kept = part["kept"]
        if not isinstance(kept, list) or len(kept) > MAX_SENTENCES:
            raise bad(f"the sentences of {field} are not a short list")
        for n, e in enumerate(kept, start=1):
            if not isinstance(e, dict) or set(e) != {"text", "mark", "notes", "quote"} or not e["text"] or not _clean(e["text"], MAX_SENTENCE):
                raise bad(f"{field} sentence {n}")
            _entry({k: e[k] for k in ("mark", "notes", "quote")}, f"{field} sentence {n}")
        if " ".join(e["text"] for e in kept) != model[field]:
            raise bad(f"the sentences of {field} do not make up the field")


ADDED_LISTS = ("topics", "key_ideas")   # the lists that a second round may add to


def _added(added, g, model, bad):
    """The items a second round added: for some of the lists the second round serves, the positions in the list, in order, of items
    that are stated."""
    if not isinstance(added, dict) or not added or not set(added) <= set(ADDED_LISTS):
        raise bad("the items a second round added are named for the topics and the key ideas only, and at least one list")
    for field, positions in added.items():
        if not isinstance(positions, list) or not positions or not all(type(p) is int for p in positions) \
                or positions != sorted(set(positions)) or positions[0] < 0 or positions[-1] >= len(model[field]):
            raise bad(f"the positions of the items added to {field}")
        if any(g[field][p]["mark"] != "stated" for p in positions):
            raise bad(f"an item added to {field} that is not stated")


def make(store, book_id, version_id, model=None, records=(), pieces=0, calls=0, reasons=(), grounding=None):
    """A card for a version: the mechanical part and, if given, the model part and the records of how it was made. With no model
    part the card is built from the metadata alone and is marked partial. `reasons` are further reasons it is partial. With a
    `grounding` record the card is of format 2: its items are marked and it may be thin; without one it is of format 1."""
    base = mechanical(store, book_id, version_id)
    if grounding is not None and model is None:
        raise KbError("a grounding record needs a model part")
    if model is not None:
        if not isinstance(model, dict):
            raise KbError("the model part of a card is not an object")
        model = _checked_model(model, grounding is not None, isinstance(grounding, dict) and "sentences" in grounding)
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
    base["made"] = {"pieces": pieces, "calls": calls, "records": [_record(r, grounding is not None) for r in records]}
    if grounding is not None:
        base["format"] = FORMAT_GROUNDED
        base["grounding"] = grounding
    return validate(base)


def _strings(value, count, limit):
    return isinstance(value, list) and len(value) <= count and all(_clean(x, limit) for x in value)


def validate(card):
    """The card, if it has exactly the shape of a card of this format; otherwise a refusal."""
    if not isinstance(card, dict) or set(card) not in (set(_TOP), set(_TOP_GROUNDED)):
        raise KbError("the card does not have the keys of a card")
    bad = lambda what: KbError(f"the card is not valid: {what}")
    if type(card["format"]) is not int or card["format"] not in FORMATS:
        raise bad("its format is not one of " + ", ".join(map(str, FORMATS)))
    grounded = card["format"] == FORMAT_GROUNDED
    if grounded != ("grounding" in card):
        raise bad("a card of format 2 has a grounding record and one of format 1 has none")
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
    sentences = grounded and isinstance(card["grounding"], dict) and "sentences" in card["grounding"]
    model = card["model"]
    if model is None:
        if grounded:
            raise bad("a card with no model part is of format 1")
        if not card["partial"]:
            raise bad("a card with no model part must be partial")
    else:
        if not isinstance(model, dict):
            raise bad("model")
        try:
            same = _checked_model(model, grounded, sentences) == model
        except KbError:
            same = False
        if not same:
            raise bad("model")
        if grounded:
            _grounding(card["grounding"], model)
            if len(model["key_ideas"]) < 3 and not card["partial"]:
                raise bad("a card with fewer than three key ideas must be partial and say why")
            if sentences and not model["summary"] and not card["partial"]:
                raise bad("a card with no summary must be partial and say why")
    made = card["made"]
    if not (isinstance(made, dict) and set(made) == {"pieces", "calls", "records"} and _count(made["pieces"], 1_000_000)
            and _count(made["calls"], 1_000_000) and isinstance(made["records"], list) and len(made["records"]) <= MAX_RECORDS):
        raise bad("made")
    for r in made["records"]:
        _record(r, grounded)
    return card


WITHHELD = "[withheld: this text holds the words of an untrusted-text marker]"


def _shown(value):
    """Text of a card as it is shown: cleaned, and withheld if its letters hold the words of an untrusted-text marker (the rule that
    blanks such a title), so that it cannot imitate the end of the section it is shown in."""
    value = str(value)
    if not value:
        return ""
    shown = textutil.title(value, len(value))
    return _UNMARK.sub(r"(\1)", shown) if shown else WITHHELD


def _shown_list(items, marks=None, sep="; "):
    """A list of texts as one line. Each item is withheld on its own if it holds the words of a marker; and if the items hold them
    only together (one item ends with 'untrusted' and the next begins with 'text'), the whole line is withheld. `marks` gives the
    mark of each item (a card of format 2), shown after it."""
    shown = [_shown(x) for x in items]
    joined = sep.join(items)
    if WITHHELD not in shown and joined and not textutil.title(joined, len(joined)):
        return WITHHELD
    if marks:
        shown = [f"{x} [{m['mark']}]" for x, m in zip(shown, marks)]
    return sep.join(shown)


def grounding_counts(card):
    """How many items of a card are marked `stated` and how many `inferred`, as {"stated": n, "inferred": n}, or "not checked" for
    a card of format 1 or one with no model part. The items are the topics, key ideas, caveats and the neutral limit if it is kept, and,
    in a card with sentences, the sentences of the summary and the neutral fields."""
    g = card.get("grounding")
    if not isinstance(g, dict):
        return "not checked"
    entries = [e for field in GROUNDED_LISTS for e in g[field]] + ([g["neutral_limits"]] if g["neutral_limits"] else [])
    entries += [e for part in (g.get("sentences") or {}).values() for e in part["kept"]]
    return {mark: sum(1 for e in entries if e["mark"] == mark) for mark in MARKS}


def render(card):
    """The text of a card for a reader, one fact to a line. Every piece of text that came from a book, its source or a model goes
    through `_shown`; the caller puts the whole between the untrusted-text markers."""
    lines = []

    def add(label, value, mark=None):
        shown = _shown(value)
        if shown:
            lines.append(f"{label}: {shown}" + (f" [{mark['mark']}]" if mark else ""))

    add("title", card["title"])
    add("kind", card["kind"])
    add("type of the original", card["primary_type"] or "")
    for key, value in card["source"].items():
        add(f"source {key}", value)
    for c in card["scan"]["caveats"]:
        add("scan finding", f"{c['kind']} (found {c['count']} times): {c['detail']} [{c['tool']}]")
    add("conversion", card["conversion"]["structure"] or "none")
    for reason in card["conversion"]["reasons"]:
        add("conversion note", reason)
    for reason in card["partial_reasons"]:
        add("partial because", reason)
    model = card["model"]
    if model is None:
        lines.append("model part: none (the card was built from the metadata alone, with no model part)")
        return "\n".join(lines)
    marks = card.get("grounding") or {}
    if "grounding" not in card:
        lines.append("grounding: not checked (a card of the earlier form, whose items are not marked)")
    sentences = marks.get("sentences") or {}

    def written(field, label):
        """The line of a field written as sentences, each with its mark, and the quote of each stated one."""
        kept = sentences[field]["kept"]
        if kept:
            lines.append(f"{label}: " + _shown_list([e["text"] for e in kept], kept, " "))
        for number, e in enumerate(kept, start=1):
            if e["mark"] == "stated":
                add(f"quote for {label} sentence {number}", e["quote"])

    if sentences:
        written("summary", "summary")
    else:
        add("summary", model["summary"])
    for key, label in (("useful_for", "useful for"), ("topics", "topics"), ("adjacent_topics", "adjacent topics")):
        if model[key]:
            lines.append(f"{label}: " + _shown_list(model[key], marks.get(key)))

    def quote_of(entry, label):
        if entry and entry["mark"] == "stated":
            add(f"quote for {label}", entry["quote"])

    for number, idea in enumerate(model["key_ideas"], start=1):
        entry = marks.get("key_ideas", [None] * number)[number - 1]
        add(f"key idea {number}", idea, entry)
        quote_of(entry, f"key idea {number}")
    for key in ("problem", "approach", "needs", "provides", "limits"):
        if sentences:
            written(f"neutral_{key}", f"neutral {key}")
            continue
        entry = marks.get("neutral_limits") if key == "limits" else None
        add(f"neutral {key}", model[f"neutral_{key}"], entry)
        if key == "limits" and model["neutral_limits"]:
            quote_of(entry, "neutral limits")
    for number, note in enumerate(model["caveats"], start=1):
        entry = marks.get("caveats", [None] * number)[number - 1]
        add("caveat", note, entry)
        quote_of(entry, f"caveat {number}")
    return "\n".join(lines)


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
    store.file_payload(book_id, version_id, f"derived/{TOOL}/{number}", {FILENAME: data}, tool=f"kb-card {card['format']}", untrusted=True)
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
