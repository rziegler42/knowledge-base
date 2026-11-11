"""The themes of a book: idea-level pieces of what a version says, each with a description in words of no field, an anchor that points
back to the text, and a mark of what the text states and what a model infers (`docs/specs/theme.md`; the plan
`2026-11-11-make-the-theme-the-unit-of-the-weave`).

A theme belongs to one version of one book and to one generation. The themes of a version are filed together as a generation, a payload
`derived/theme/<n>`, one new number for each. It is filed through the incoming area, read-only and marked untrusted, and an earlier
generation is never changed. As for cards, the newest generation that passes its check is the active one, and a generation can be read
by its number.

This module holds the form of a theme and of a generation, their check, their filing and reading, and the finding of an anchor in a
conversion. It makes no model call; making themes is the extraction's. A model names where a theme comes from by a pointer
(`{"kind", "start", "end"}`, each end the `at` of a locator of the conversion's kind), and code, not the model, finds the exact text:
`anchor_of` turns a pointer into an anchor, `find` finds a stored anchor again in a conversion (the same one or another), and
`check_against` refuses an anchor that does not hold. A span is whole blocks, from the block of the start to the block of the end.
A theme read from a file is untrusted data, so every piece of text in it must already be in the form `textutil.clean` gives."""
import json
import os
import re

from . import KbError, convert, ids, locator, models, textutil

FORMAT = 1
TOOL = "theme"
FILENAME = "themes.json"
MAX_FILE = 8 * 1024 * 1024    # bytes of one generation: 2,000 themes of about 3 KB each, and room. A theme with every field at its
# limit is about 9 KB, so a generation of that many themes is valid in form and then refused at filing, loudly
MAX_THEMES = 2000             # themes in one generation; the bound that catches a runaway is the extraction's, and is lower
MAX_GENERATION = 999_999
MAX_PATH = 6                  # headings in the path of an anchor, as in a locator
MAX_EXCERPT = 6000            # characters of the converted text that one theme may point to, from the start of its first block to the end of its last
TYPES = ("problem", "method", "finding", "concept", "other")   # `other` is a theme without a clear type, and it is kept
MARKS = ("stated", "inferred")
PARTS = ("problem", "method", "needs", "provides", "limits")
MAX_TITLE, MAX_SUMMARY, MAX_PART = 120, 600, 300
MAX_FLAGS, MAX_KIND, MAX_DETAIL = 10, 40, 300
_TOP = ("format", "book_id", "version_id", "themes")
_THEME = ("id", "book_id", "version_id", "conversion", "anchor", "title", "type", "summary", "neutral", "confidence", "made", "flags")
_ANCHOR = ("start", "end", "path", "excerpt_sha256")
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_VERSION = re.compile(r"v[1-9][0-9]{0,5}")
_GENERATION = re.compile(r"[1-9][0-9]{0,5}")
_SHA = re.compile(r"[0-9a-f]{64}")
_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[0-9T:.+Z-]{0,40}")


def _clean(value, limit, least=0):
    """True for text that is already in the form `textutil.clean` gives, of `least` to `limit` characters."""
    return isinstance(value, str) and least <= len(value) <= limit and textutil.clean(value, limit) == value


def _conversion(conv):
    return (isinstance(conv, dict) and set(conv) == {"tool", "version", "generation"} and isinstance(conv["tool"], str)
            and bool(locator._NAME.fullmatch(conv["tool"])) and isinstance(conv["version"], str)
            and bool(locator._VERSION.fullmatch(conv["version"])) and type(conv["generation"]) is int and conv["generation"] >= 1)


def _end(loc):
    """A locator of an anchor, checked in full, or a refusal."""
    try:
        return locator.check(loc)
    except KbError:
        raise KbError("an end of an anchor is not a locator") from None


def _anchor(anchor, conversion):
    if not isinstance(anchor, dict) or set(anchor) != set(_ANCHOR):
        raise KbError("the anchor does not have the keys of an anchor")
    start, end = _end(anchor["start"]), _end(anchor["end"])
    if start["kind"] != end["kind"]:
        raise KbError("the two ends of an anchor are of different kinds")
    if start["conversion"] != conversion or end["conversion"] != conversion:
        raise KbError("an end of an anchor is made against another conversion than the theme names")
    if start["kind"] == "offset" and end["at"]["offset"] < start["at"]["offset"]:  # the order of sections cannot be told without the text
        raise KbError("the end of an anchor comes before its start")
    if start["kind"] == "page" and (end["at"]["page"], end["at"]["block"]) < (start["at"]["page"], start["at"]["block"]):
        raise KbError("the end of an anchor comes before its start")
    path = anchor["path"]
    if not (isinstance(path, list) and len(path) <= MAX_PATH and all(_clean(p, convert.PATH_PART_CHARS, 1) for p in path)):
        raise KbError("the heading path of an anchor is not valid")
    if not isinstance(anchor["excerpt_sha256"], str) or not _SHA.fullmatch(anchor["excerpt_sha256"]):
        raise KbError("the hash of the excerpt of an anchor is not a hash")


def _neutral(neutral):
    if not isinstance(neutral, dict) or set(neutral) != set(PARTS):
        raise KbError("the description in words of no field must have exactly its five parts")
    for name in PARTS:
        part = neutral[name]
        if not (isinstance(part, dict) and set(part) == {"text", "mark"} and _clean(part["text"], MAX_PART)):
            raise KbError(f"the part {name!r} of the description is not valid")
        mark = part["mark"]
        if part["text"]:
            if not (isinstance(mark, str) and mark in MARKS):
                raise KbError(f"the part {name!r} has text and no mark of stated or inferred")
        elif mark is not None:
            raise KbError(f"the part {name!r} has a mark and no text")


def _made(made):
    if not (isinstance(made, dict) and set(made) == {"model", "prompt_version", "date"} and models._valid_model(made["model"])
            and isinstance(made["prompt_version"], str) and models._VERSION.fullmatch(made["prompt_version"])
            and isinstance(made["date"], str) and _ISO.fullmatch(made["date"])):
        raise KbError("the record of how the theme was made is not in the expected form")


def _flags(flags):
    if not (isinstance(flags, list) and len(flags) <= MAX_FLAGS):
        raise KbError("the flags are not a short list")
    for flag in flags:
        if not (isinstance(flag, dict) and set(flag) == {"kind", "detail"} and _clean(flag["kind"], MAX_KIND, 1)
                and _clean(flag["detail"], MAX_DETAIL, 1)):
            raise KbError("a flag is not in the expected form")


def check_theme(t, book_id, version_id):
    """The theme, if it has exactly the form of a theme of this version of this book; otherwise a refusal."""
    if not isinstance(t, dict) or set(t) != set(_THEME):
        raise KbError("the theme does not have the keys of a theme")
    bad = lambda what: KbError(f"the theme is not valid: {what}")
    if not isinstance(t["id"], str) or not _ID.fullmatch(t["id"]):
        raise bad("id")
    if t["book_id"] != book_id or t["version_id"] != version_id:
        raise bad("it belongs to another book or version than its generation")
    if not _conversion(t["conversion"]):
        raise bad("conversion")
    _anchor(t["anchor"], t["conversion"])
    if not (isinstance(t["title"], str) and 1 <= len(t["title"]) <= MAX_TITLE and textutil.title(t["title"], MAX_TITLE) == t["title"]):
        raise bad("title")
    if not isinstance(t["type"], str) or t["type"] not in TYPES:
        raise bad("type")
    if not _clean(t["summary"], MAX_SUMMARY, 1):
        raise bad("summary")
    _neutral(t["neutral"])
    c = t["confidence"]
    if type(c) not in (int, float) or not 0 <= c <= 1:   # a number that is not a number, or is infinite, fails the range
        raise bad("confidence")
    _made(t["made"])
    _flags(t["flags"])
    return t


def validate(gen):
    """The generation, if it has exactly the form of a generation of themes; otherwise a refusal. The themes are checked in full."""
    if not isinstance(gen, dict) or set(gen) != set(_TOP):
        raise KbError("the generation of themes does not have the keys of one")
    if type(gen["format"]) is not int or gen["format"] != FORMAT:
        raise KbError(f"the format of the themes is not {FORMAT}")
    ids.check_id(gen["book_id"])
    if not isinstance(gen["version_id"], str) or not _VERSION.fullmatch(gen["version_id"]):
        raise KbError("the version of the themes is not a version")
    themes = gen["themes"]
    if not isinstance(themes, list) or len(themes) > MAX_THEMES:
        raise KbError(f"the themes must be a list of at most {MAX_THEMES}")
    seen = set()
    for t in themes:
        check_theme(t, gen["book_id"], gen["version_id"])
        if t["id"] in seen:
            raise KbError("two themes share an id")
        seen.add(t["id"])
    return gen


def make(book_id, version_id, themes):
    """A generation of themes for a version, checked."""
    return validate({"format": FORMAT, "book_id": book_id, "version_id": version_id, "themes": list(themes)})


def _place(kind, place):
    """The place of one end of a pointer, in the form a locator of that kind has it, or a refusal."""
    if not isinstance(place, dict):
        raise KbError("an end of a pointer is not a place")
    if kind == "section":
        ok = (set(place) == {"path", "paragraph"} and isinstance(place["path"], list) and len(place["path"]) <= MAX_PATH   # none: before any heading
              and all(isinstance(t, str) and 0 < len(t) <= convert.PATH_PART_CHARS for t in place["path"])
              and locator._is_int(place["paragraph"], 0))
    elif kind == "page":
        ok = set(place) == {"page", "block"} and locator._is_int(place["page"], 1) and locator._is_int(place["block"], 1)
    else:
        ok = set(place) == {"offset"} and locator._is_int(place["offset"], 0)
    if not ok:
        raise KbError(f"an end of a pointer is not a place of the kind {kind!r}")
    return place


def _block(conversion, kind, place):
    """The index of the one block at a place of a pointer, or a refusal."""
    found = locator._place({"kind": kind, "at": _place(kind, place)}, conversion)
    if not found:
        raise KbError("the conversion has no block at that place")
    if len(found) > 1:
        raise KbError("more than one block of the conversion is at that place")
    return found[0]


def _between(ref, conversion, first, last):
    """The anchor for the blocks from `first` to `last` of a conversion `ref` names. The excerpt is at most MAX_EXCERPT characters and
    has words; its hash is that of its words, lower-cased, without punctuation, joined by single spaces."""
    blocks = conversion.blocks
    size = blocks[last].end - blocks[first].start   # of the converted text, with the blank line between blocks; measured before it is copied
    if size > MAX_EXCERPT:
        raise KbError(f"the excerpt is {size} characters, more than the {MAX_EXCERPT} a theme may point to")
    text = conversion.text[blocks[first].start:blocks[last].end]
    words = locator.words(text)
    if not words:
        raise KbError("the excerpt has no words")
    anchor = {"start": locator.make(ref, conversion, first), "end": locator.make(ref, conversion, last),
              "path": list(blocks[first].path), "excerpt_sha256": locator._hash(words)}
    _anchor(anchor, {k: ref[k] for k in ("tool", "version", "generation")})
    return anchor


def anchor_of(ref, conversion, pointer):
    """The anchor for a pointer a model named, in the conversion `ref` names: `{"kind", "start", "end"}`, the kind that of the
    conversion (section, page or offset), each end the place a locator of that kind has (a heading path and a paragraph, a page and a
    block, a character offset). The span is the whole blocks from the block at the start to the block at the end; an offset only
    chooses its block. A pointer that names no block, more than one, a kind other than the conversion's, an end before its start, an
    excerpt over MAX_EXCERPT characters or with no words is refused."""
    if not isinstance(pointer, dict) or set(pointer) != {"kind", "start", "end"}:
        raise KbError("a pointer has exactly a kind, a start and an end")
    kind = pointer["kind"]
    if not isinstance(kind, str) or kind not in locator.KINDS:
        raise KbError("a pointer is of a kind this reader does not know")
    if kind != locator._kind_of(conversion):
        raise KbError(f"the pointer is of the kind {kind!r} and the conversion is of the kind {locator._kind_of(conversion)!r}")
    first, last = _block(conversion, kind, pointer["start"]), _block(conversion, kind, pointer["end"])
    if last < first:
        raise KbError("the end of a pointer comes before its start")
    return _between(ref, conversion, first, last)


def _form(anchor):
    """The conversion an anchor was made against, after its form is checked."""
    if not isinstance(anchor, dict) or set(anchor) != set(_ANCHOR):
        raise KbError("the anchor does not have the keys of an anchor")
    own = _end(anchor["start"])["conversion"]
    _anchor(anchor, own)
    return own


def find(ref, conversion, anchor):
    """Find a stored anchor again in the conversion `ref` names, which may be the one it was made against or another. Returns
    `{"status", "anchor", "reason"}`: `found` (both ends are at their places in the same conversion and the text between them is the text
    that was anchored), `found_by_text` (the ends were found by their words in another conversion, and the text between them is still
    the text that was anchored; `anchor` is the anchor made against this one), or `not_found` (`anchor` is None and `reason` says why).
    The text is the same only if the hash of the whole excerpt found equals the stored one, and an anchor in the conversion it was made
    against is `found` only if it is also exactly the anchor code makes for that text (its path and both ends). An anchor that is not
    in the form of an anchor, and a text too large to search (`locator.resolve` refuses it), are refusals (`KbError`), not a status."""
    own = _form(anchor)
    lost = lambda why: {"status": "not_found", "anchor": None, "reason": why}
    start = locator.resolve(anchor["start"], ref, conversion)
    end = locator.resolve(anchor["end"], ref, conversion)
    if start["status"] == "not_found" or end["status"] == "not_found":
        return lost("an end of the anchor is not in the text")
    first, last = start["block"], end["block"]
    if last < first:
        return lost("the end of the anchor is found before its start")
    try:
        made = _between(ref, conversion, first, last)
    except KbError as e:
        return lost(str(e))
    if made["excerpt_sha256"] != anchor["excerpt_sha256"]:
        return lost("the text between the ends is not the text that was anchored")
    same = own == {k: ref[k] for k in ("tool", "version", "generation")} and start["status"] == end["status"] == "found"
    if same and made != anchor:  # the text is right, but the path or an end is not what code would have made for it
        return lost("the path or places of the anchor are not those of the text between its ends")
    return {"status": "found" if same else "found_by_text", "anchor": made, "reason": ""}


def check_against(ref, conversion, anchor):
    """The anchor, if it holds in the conversion `ref` names as it is stored; otherwise a refusal."""
    got = find(ref, conversion, anchor)
    if got["status"] != "found":
        raise KbError("the anchor does not hold in the text: " + (got["reason"] or "it is found only by its words"))
    return anchor


def excerpt_text(ref, conversion, anchor):
    """The text of the excerpt an anchor points to (whole blocks, from the block at its start to the block at its end), if the anchor
    holds in the conversion `ref` names as it is stored; otherwise a refusal. At most MAX_EXCERPT characters."""
    check_against(ref, conversion, anchor)
    first = locator.resolve(anchor["start"], ref, conversion)["block"]
    last = locator.resolve(anchor["end"], ref, conversion)["block"]
    return conversion.text[conversion.blocks[first].start:conversion.blocks[last].end]


def generations(store, book_id, version_id):
    """The numbers of the generations filed for a version, lowest first. A folder whose name is not a plain number, or is a link, is
    ignored."""
    folder = os.path.join(store.version_dir(book_id, version_id), "derived", TOOL)
    if not os.path.isdir(folder):
        return []
    return sorted(int(n) for n in os.listdir(folder)
                  if _GENERATION.fullmatch(n) and os.path.isdir(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n)))


def damaged(store, book_id, version_id):
    """`[(number, reason)]` for each generation of a version that fails its check, lowest first. A read without a number skips such
    a generation and returns an older one, so this is how a caller sees that a newer one is damaged."""
    out = []
    for number in generations(store, book_id, version_id):
        try:
            _load(store, book_id, version_id, number)
        except KbError as e:
            out.append((number, str(e)))
    return out


def file(store, gen):
    """File a generation of themes as the next one of its version, and return the number. It is checked first; one that is not valid
    files nothing. An earlier generation is never changed."""
    validate(gen)
    book_id, version_id = gen["book_id"], gen["version_id"]
    store.read_version(book_id, version_id)
    existing = generations(store, book_id, version_id)
    number = (existing[-1] + 1) if existing else 1
    if number > MAX_GENERATION:
        raise KbError("this version has as many generations of themes as it can have")
    data = (json.dumps(gen, indent=1) + "\n").encode()
    if len(data) > MAX_FILE:
        raise KbError("the generation of themes is larger than one may be")
    store.file_payload(book_id, version_id, f"derived/{TOOL}/{number}", {FILENAME: data}, tool=f"kb-theme {gen['format']}", untrusted=True)
    return number


def _load(store, book_id, version_id, number):
    name = f"derived/{TOOL}/{number}"
    manifest = store.verify_payload(book_id, version_id, name)
    if set(manifest["files"]) != {FILENAME}:
        raise KbError(f"the payload of themes must be the one file {FILENAME} and nothing else")
    if manifest["files"][FILENAME]["size"] > MAX_FILE:
        raise KbError("the generation of themes is larger than one may be")
    with open(os.path.join(store.payload_path(book_id, version_id, name), FILENAME), "rb") as f:
        raw = f.read(MAX_FILE + 1)
    try:
        doc = models._loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        doc = None
    if not isinstance(doc, dict):
        raise KbError("the file of themes is not one JSON object")
    validate(doc)
    if doc["book_id"] != book_id or doc["version_id"] != version_id:
        raise KbError("the themes belong to another book or version")
    return doc


def read(store, book_id, version_id, generation=None):
    """`(number, generation)` of the generation asked for, or without a number of the newest one that passes its check (its payload
    against its hashes, its file, and the form of every theme). A number asked for is read as it is, and refused if it fails."""
    existing = generations(store, book_id, version_id)
    if not existing:
        raise KbError("the version has no themes")
    if generation is not None:
        if type(generation) is not int or generation not in existing:
            raise KbError(f"the version has no themes of generation {generation!r}")
        return generation, _load(store, book_id, version_id, generation)
    newest = None
    for number in reversed(existing):
        try:
            return number, _load(store, book_id, version_id, number)
        except KbError as e:
            newest = newest or e
    raise KbError(f"no generation of themes of the version passes its check; the newest says: {newest}")
