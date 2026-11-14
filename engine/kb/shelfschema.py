"""The checker of the shelf schema file and of the file of custom shelves (Increment A of the plan `2026-11-14-build-the-shelf-schema`).

The schema is a tracked JSON file that lists the shelves of the library: each has a slug of our own, a name, a level (domain, field, subfield, topic or custom), a parent,
its OpenAlex identifier or, for a custom shelf, its Library of Congress subclass code, and one scope sentence (the decision
`2026-11-14-the-shelf-schema-is-our-own-list-from-openalex-and-lcc`). The file holds identity only: it has no field for the state, the priority or the counts of a shelf, and a field
it does not know is a problem, so none can be put there.

The checker reads a file as data, never runs it, and writes nothing. It needs only the standard library, no library of books and no config."""
import datetime
import json
import os
import re
import stat
import unicodedata

from . import KbError

FORMAT = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_PROBLEMS = 200
LEVELS = ("domain", "field", "subfield", "topic", "custom")
PARENT_LEVEL = {"field": "domain", "subfield": "field", "topic": "subfield"}

SCHEMA_KEYS = ("format", "snapshot", "shelves")
SHELF_KEYS = ("slug", "name", "level", "parent", "openalex", "lcc", "scope")
SNAPSHOT_KEYS = {"openalex": ("url", "retrieved", "sha256"), "lcc": ("url", "retrieved", "sha256"), "custom": ("sha256",)}
CUSTOM_KEYS = ("format", "source", "shelves")
CUSTOM_SOURCE_KEYS = ("url", "retrieved", "sha256")
CUSTOM_SHELF_KEYS = ("code", "name", "parent", "scope", "reason", "page", "retrieved")

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
IDENT = re.compile(r"[A-Za-z0-9:/._-]{1,100}")
CODE = re.compile(r"[A-Z]{1,3}")
SHA256 = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SLUG_MAX, NAME_MAX, SCOPE_MAX, REASON_MAX, URL_MAX = 120, 200, 500, 500, 500


# --- reading

def _no_repeat(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("the key %r is given twice" % key)
        seen[key] = value
    return seen


def _no_constant(name):
    raise ValueError("%s is not allowed" % name)


def load(path):
    """The parsed file. A file that is missing, not a regular file, over MAX_BYTES, not UTF-8 JSON, or that repeats a key or holds NaN or Infinity is refused."""
    try:
        # O_NONBLOCK so that a named pipe put in place of the file cannot make the open wait; the kind of file is read from the open descriptor, not from the path
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise KbError("%s is not a regular file" % path)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(MAX_BYTES + 1)
        finally:
            os.close(fd)
    except OSError as e:
        raise KbError("cannot read %s: %s" % (path, e.strerror or e))
    if len(raw) > MAX_BYTES:
        raise KbError("%s is larger than %d bytes" % (path, MAX_BYTES))
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_repeat, parse_constant=_no_constant)
    except (ValueError, RecursionError) as e:
        raise KbError("%s is not a JSON file the checker accepts: %s" % (path, e))


# --- values

def _text(value, limit):
    """None if the value is a non-empty string of at most `limit` characters with no control, format, separator or unassigned character; otherwise the reason."""
    if type(value) is not str:
        return "must be a string"
    if not 1 <= len(value) <= limit:
        return "must have 1 to %d characters" % limit
    for ch in value:
        category = unicodedata.category(ch)
        if category[0] == "C" or category in ("Zl", "Zp"):
            return "holds a control or hidden character"
    return None


def _date(value):
    if type(value) is not str or not DATE.fullmatch(value):
        return "must be a date written YYYY-MM-DD"
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return "is not a real date"
    return None


def _url(value):
    if type(value) is not str or not (value.startswith("https://") or value.startswith("http://")):
        return "must be an http or https address"
    if len(value) > URL_MAX or any(c.isspace() or unicodedata.category(c)[0] == "C" for c in value):
        return "must be one line of at most %d characters with no space" % URL_MAX
    return None


def _sha(value):
    return None if type(value) is str and SHA256.fullmatch(value) else "must be 64 lowercase hex characters"


class _Problems:
    def __init__(self):
        self.items = []
        self.more = 0

    def add(self, text):
        if len(self.items) < MAX_PROBLEMS:
            self.items.append(text)
        else:
            self.more += 1

    def result(self):
        if self.more:
            return self.items + ["... and %d more problems" % self.more]
        return self.items


def _keys(problems, label, obj, allowed):
    """Unknown and missing keys of an object."""
    for key in obj:
        if key not in allowed:
            problems.add("%s: unknown field %r (the file holds identity only)" % (label, key))
    for key in allowed:
        if key not in obj:
            problems.add("%s: missing field %r" % (label, key))


def _check_format(problems, label, value):
    if type(value) is not int or value != FORMAT:
        problems.add("%s: format must be the number %d" % (label, FORMAT))


# --- the schema file

def _check_snapshot(problems, snapshot):
    if type(snapshot) is not dict:
        problems.add("snapshot: must be an object")
        return
    for source, allowed in SNAPSHOT_KEYS.items():
        entry = snapshot.get(source)
        if source not in snapshot:
            problems.add("snapshot: missing %r" % source)
            continue
        if type(entry) is not dict:
            problems.add("snapshot %s: must be an object" % source)
            continue
        _keys(problems, "snapshot %s" % source, entry, allowed)
        for key, check in (("url", _url), ("retrieved", _date), ("sha256", _sha)):
            if key in allowed and key in entry:
                reason = check(entry[key])
                if reason:
                    problems.add("snapshot %s: %s %s" % (source, key, reason))
    for source in snapshot:
        if source not in SNAPSHOT_KEYS:
            problems.add("snapshot: unknown source %r" % source)


def _check_shelf_fields(problems, label, shelf):
    _keys(problems, label, shelf, SHELF_KEYS)
    for key, limit in (("name", NAME_MAX), ("scope", SCOPE_MAX)):
        if key in shelf:
            reason = _text(shelf[key], limit)
            if reason:
                problems.add("%s: %s %s" % (label, key, reason))
    if "slug" in shelf:
        slug = shelf["slug"]
        if type(slug) is not str or not SLUG.fullmatch(slug) or len(slug) > SLUG_MAX:
            problems.add("%s: slug must be lowercase words joined by single hyphens, at most %d characters" % (label, SLUG_MAX))
    if "level" in shelf and shelf["level"] not in LEVELS:
        problems.add("%s: unknown level %r (one of %s)" % (label, shelf["level"], ", ".join(LEVELS)))
    if "parent" in shelf and shelf["parent"] is not None and type(shelf["parent"]) is not str:
        problems.add("%s: parent must be a slug or null" % label)
    custom = shelf.get("level") == "custom"
    if "openalex" in shelf:
        value = shelf["openalex"]
        if custom:
            if value is not None:
                problems.add("%s: a custom shelf has no openalex identifier" % label)
        elif type(value) is not str or not IDENT.fullmatch(value):
            problems.add("%s: openalex must be an identifier of 1 to 100 letters, digits and : / . _ -" % label)
    if "lcc" in shelf:
        value = shelf["lcc"]
        if custom:
            if type(value) is not str or not CODE.fullmatch(value):
                problems.add("%s: lcc must be a subclass code of one to three capital letters" % label)
        elif value is not None:
            problems.add("%s: only a custom shelf has an lcc code" % label)


def _check_parents(problems, label, shelf, by_slug):
    level, parent = shelf.get("level"), shelf.get("parent")
    if level not in LEVELS or "parent" not in shelf or (parent is not None and type(parent) is not str):
        return
    if level == "domain":
        if parent is not None:
            problems.add("%s: a domain has no parent" % label)
        return
    if level == "custom":
        if parent is None:
            return
        found = by_slug.get(parent)
        if found is None:
            problems.add("%s: parent %r is not a shelf of the schema" % (label, parent))
        elif found.get("level") != "domain":
            problems.add("%s: a custom shelf has no parent or a domain, and %r is a %s (level)" % (label, parent, found.get("level")))
        return
    wanted = PARENT_LEVEL[level]
    if parent is None:
        problems.add("%s: a %s needs a parent, which is a %s" % (label, level, wanted))
        return
    found = by_slug.get(parent)
    if found is None:
        problems.add("%s: parent %r is not a shelf of the schema" % (label, parent))
    elif found.get("level") != wanted:
        problems.add("%s: level: the parent of a %s is a %s, and %r is a %s" % (label, level, wanted, parent, found.get("level")))


def _check_cycles(problems, by_slug):
    reported = set()
    for start in by_slug:
        path, node = [], start
        while node is not None and node in by_slug and node not in path:
            path.append(node)
            parent = by_slug[node].get("parent")
            node = parent if type(parent) is str else None
        if node is not None and node in path and node not in reported:
            ring = path[path.index(node):]
            reported.update(ring)
            problems.add("cycle: %s" % " -> ".join(ring + [node]))


def check_schema(data):
    """The problems of a schema file, as strings, each naming the shelf it is about; an empty list for a file with none."""
    problems = _Problems()
    if type(data) is not dict:
        return ["the file must be one JSON object"]
    for key in data:
        if key not in SCHEMA_KEYS:
            problems.add("file: unknown field %r (the file holds identity only)" % key)
    if "format" not in data:
        problems.add("file: missing field 'format'")
    else:
        _check_format(problems, "file", data["format"])
    if "snapshot" not in data:
        problems.add("file: missing field 'snapshot'")
    else:
        _check_snapshot(problems, data["snapshot"])
    shelves = data.get("shelves")
    if type(shelves) is not list or not shelves:
        problems.add("file: shelves must be a non-empty list")
        return problems.result()
    by_slug, openalex_seen, lcc_seen, entries = {}, {}, {}, []
    for index, shelf in enumerate(shelves):
        if type(shelf) is not dict:
            problems.add("shelves[%d]: a shelf must be an object" % index)
            continue
        slug = shelf.get("slug")
        label = "shelf %r" % slug if type(slug) is str and slug else "shelves[%d]" % index
        _check_shelf_fields(problems, label, shelf)
        entries.append((label, shelf))
        if type(slug) is str and SLUG.fullmatch(slug):
            if slug in by_slug:
                problems.add("%s: duplicate slug" % label)
            else:
                by_slug[slug] = shelf
        for key, seen in (("openalex", openalex_seen), ("lcc", lcc_seen)):
            value = shelf.get(key)
            if type(value) is str:
                if value in seen:
                    problems.add("%s: duplicate %s %r (also on %s)" % (label, key, value, seen[value]))
                else:
                    seen[value] = label
    for label, shelf in entries:
        _check_parents(problems, label, shelf, by_slug)
    _check_cycles(problems, by_slug)
    return problems.result()


def counts(data):
    """The number of shelves of each level (every level is named, so a level with none says 0)."""
    out = {level: 0 for level in LEVELS}
    shelves = data.get("shelves") if type(data) is dict else None
    for shelf in shelves if type(shelves) is list else []:
        if type(shelf) is dict and type(shelf.get("level")) is str and shelf["level"] in out:
            out[shelf["level"]] += 1
    return out


# --- the file of custom shelves

def check_custom(data):
    """The problems of the file of custom shelves that the builder reads with the saved lists."""
    problems = _Problems()
    if type(data) is not dict:
        return ["the file must be one JSON object"]
    for key in data:
        if key not in CUSTOM_KEYS:
            problems.add("file: unknown field %r" % key)
    if "format" not in data:
        problems.add("file: missing field 'format'")
    else:
        _check_format(problems, "file", data["format"])
    source = data.get("source")
    if "source" not in data:
        problems.add("file: missing field 'source'")
    elif type(source) is not dict:
        problems.add("source: must be an object")
    else:
        _keys(problems, "source", source, CUSTOM_SOURCE_KEYS)
        for key, check in (("url", _url), ("retrieved", _date), ("sha256", _sha)):
            if key in source and check(source[key]):
                problems.add("source: %s %s" % (key, check(source[key])))
    shelves = data.get("shelves")
    if type(shelves) is not list or not shelves:
        problems.add("file: shelves must be a non-empty list")
        return problems.result()
    seen = {}
    for index, shelf in enumerate(shelves):
        if type(shelf) is not dict:
            problems.add("shelves[%d]: a custom shelf must be an object" % index)
            continue
        code = shelf.get("code")
        label = "custom shelf %r" % code if type(code) is str and code else "shelves[%d]" % index
        _keys(problems, label, shelf, CUSTOM_SHELF_KEYS)
        if "code" in shelf:
            if type(code) is not str or not CODE.fullmatch(code):
                problems.add("%s: code must be a subclass code of one to three capital letters" % label)
            elif code in seen:
                problems.add("%s: duplicate code (also in shelves[%d])" % (label, seen[code]))
            else:
                seen[code] = index
        for key, limit in (("name", NAME_MAX), ("scope", SCOPE_MAX), ("reason", REASON_MAX)):
            if key in shelf and _text(shelf[key], limit):
                problems.add("%s: %s %s" % (label, key, _text(shelf[key], limit)))
        if "parent" in shelf and shelf["parent"] is not None and (type(shelf["parent"]) is not str or not SLUG.fullmatch(shelf["parent"])):
            problems.add("%s: parent must be the slug of a domain, or null" % label)
        if "page" in shelf and _url(shelf["page"]):
            problems.add("%s: page %s" % (label, _url(shelf["page"])))
        if "retrieved" in shelf and _date(shelf["retrieved"]):
            problems.add("%s: retrieved %s" % (label, _date(shelf["retrieved"])))
    return problems.result()


def custom_counts(data):
    shelves = data.get("shelves") if type(data) is dict else None
    return {"custom": sum(1 for s in shelves if type(s) is dict) if type(shelves) is list else 0}


# --- the command

def report(path, custom=False):
    """What `shelf-schema-check` prints: the file, its kind, the number of shelves, the counts and the problems."""
    data = load(path)
    if custom:
        problems, found = check_custom(data), custom_counts(data)
    else:
        problems, found = check_schema(data), counts(data)
    shelves = data.get("shelves") if type(data) is dict else None
    return {"file": path, "kind": "custom" if custom else "schema", "shelves": len(shelves) if type(shelves) is list else 0,
            "counts": found, "problems": problems}
