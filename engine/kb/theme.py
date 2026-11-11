"""The themes of a book: idea-level pieces of what a version says, each with a description in words of no field, an anchor that points
back to the text, and a mark of what the text states and what a model infers (`docs/specs/theme.md`; the plan
`2026-11-11-make-the-theme-the-unit-of-the-weave`).

A theme belongs to one version of one book and to one generation. The themes of a version are filed together as a generation, a payload
`derived/theme/<n>`, one new number for each. It is filed through the incoming area, read-only and marked untrusted, and an earlier
generation is never changed. As for cards, the newest generation that passes its check is the active one, and a generation can be read
by its number.

This module holds the form of a theme and of a generation, their check, and their filing and reading. It makes no model call and does
not look at the book: finding the anchor in the text is `theme_anchor`'s work, and making themes is the extraction's. A theme read from
a file is untrusted data, so every piece of text in it must already be in the form `textutil.clean` gives."""
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
