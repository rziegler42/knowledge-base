"""The builder of the shelf schema file (Increment D of the plan `2026-11-14-build-the-shelf-schema`).

It makes the schema file from three inputs, each given by path and never found by itself: the saved OpenAlex lists (a folder holding the report of the read and the pages it names), the
saved Library of Congress outline (a folder holding the report of the read, the pages it names and the extract of the subclasses) and the tracked file of custom shelves. It reads them as
data, checks each saved page against the hash its report records, makes the slugs and the scope sentences by fixed rules, and writes the file; the same inputs give the same bytes.

The builder reads files and writes one new file. It needs only the standard library, no network, no library of books and no config."""
import hashlib
import json
import os
import re
import stat
import unicodedata

from . import KbError, shelfschema

OPENALEX_REPORT = "openalex-read-report.json"
LCC_REPORT = "lcc-read-report.json"
LCC_EXTRACT = "lcc-subclasses.json"
OPENALEX_SOURCE = "https://api.openalex.org"
LCC_SOURCE = "https://www.loc.gov"
LCC_INDEX_FILE = "index.html"
OPENALEX_PREFIX = "https://openalex.org/"

MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 200
MAX_TOTAL = 64 * 1024 * 1024
SLUG_BASE_MAX = 100

LEVELS = ("domains", "fields", "subfields", "topics")
SINGULAR = {"domains": "domain", "fields": "field", "subfields": "subfield", "topics": "topic"}
ID_FORM = {"domains": re.compile(re.escape(OPENALEX_PREFIX) + r"domains/[0-9]{1,6}"),
           "fields": re.compile(re.escape(OPENALEX_PREFIX) + r"fields/[0-9]{1,6}"),
           "subfields": re.compile(re.escape(OPENALEX_PREFIX) + r"subfields/[0-9]{1,6}"),
           "topics": re.compile(re.escape(OPENALEX_PREFIX) + r"T[0-9]{1,9}")}
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ARTICLE = {"field": "a field", "subfield": "a subfield", "topic": "a topic"}
APOSTROPHES = frozenset("'\u2019\u2018\u02bc")
GREEK = dict(zip("αβγδεζηθικλμνξοπρστυφχψω", "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega".split()), **{"ς": "sigma", "µ": "mu"})
SPELLED = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i"}
ABBREVIATIONS = frozenset(["e.g.", "i.e.", "u.s.", "u.k.", "vs.", "etc.", "approx.", "al.", "dr.", "st.", "no.", "fig.", "mr.", "mrs.", "ms.", "prof.", "inc.", "ltd.", "cf."])
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


# --- reading

def _read_bytes(path, what, follow=False):
    """The bytes of a regular file of at most MAX_FILE bytes, opened without waiting; a link is refused unless `follow`."""
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | (0 if follow else getattr(os, "O_NOFOLLOW", 0))
    try:
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise KbError("%s is not a regular file" % what)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(MAX_FILE + 1)
        finally:
            os.close(fd)
    except OSError as e:
        raise KbError("cannot read %s: %s" % (what, e.strerror or e))
    if len(raw) > MAX_FILE:
        raise KbError("%s is larger than %d bytes" % (what, MAX_FILE))
    return raw


def _parse(raw, what):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=shelfschema._no_repeat, parse_constant=shelfschema._no_constant)
    except (ValueError, RecursionError) as e:
        raise KbError("%s is not a JSON file the builder accepts: %s" % (what, e))


def manifest_sha256(pairs):
    """The hash of the text of the lines `<file name> <sha256 of that file>`, one newline after each, sorted by file name, in UTF-8 (the form Increments B and C recorded)."""
    text = "".join("%s %s\n" % (name, digest) for name, digest in sorted(pairs))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _report(folder, name, source):
    """The report of a read and the verified pages it names: (report, report bytes, {file name: bytes})."""
    raw = _read_bytes(os.path.join(folder, name), name)
    report = _parse(raw, name)
    if type(report) is not dict:
        raise KbError("%s must be one JSON object" % name)
    if report.get("status") != "done":
        raise KbError("%s: the read did not finish (status %r)" % (name, report.get("status")))
    if report.get("source") != source:
        raise KbError("%s: the source is not %s" % (name, source))
    if shelfschema._date(str(report.get("started"))[:10]) or type(report.get("started")) is not str:
        raise KbError("%s: started must be a time that begins with a date" % name)
    entries = report.get("files")
    if type(entries) is not list or not entries or len(entries) > MAX_FILES:
        raise KbError("%s: files must be a list of 1 to %d entries" % (name, MAX_FILES))
    pages, seen, total = {}, set(), 0
    for entry in entries:
        if type(entry) is not dict or type(entry.get("file")) is not str or not FILE_NAME.fullmatch(entry["file"]):
            raise KbError("%s: an entry names a file that is not a plain file name" % name)
        file_name = entry["file"]
        if file_name in seen:
            raise KbError("%s: the file %s is named twice" % (name, file_name))
        seen.add(file_name)
        digest = entry.get("sha256")
        if shelfschema._sha(digest):
            raise KbError("%s: the hash of %s must be 64 lowercase hex characters" % (name, file_name))
        page = _read_bytes(os.path.join(folder, file_name), file_name)
        if _sha(page) != digest:
            raise KbError("%s does not match the hash its report records" % file_name)
        total += len(page)
        if total > MAX_TOTAL:
            raise KbError("%s: the files it names are larger than %d bytes together" % (name, MAX_TOTAL))
        pages[file_name] = page
    return report, raw, pages


def _started(report):
    return report["started"][:10]


# --- the lists of OpenAlex

def _short(level, ident):
    if type(ident) is not str or not ID_FORM[level].fullmatch(ident):
        raise KbError("an identifier of the %s is not of the form OpenAlex gives: %r" % (level, ident if type(ident) is str and len(ident) < 60 else "?"))
    return ident[len(OPENALEX_PREFIX):]


def _parent_id(record, key, level, name):
    link = record.get(key)
    if type(link) is not dict:
        raise KbError("%s %r has no %s" % (SINGULAR[level], name, key))
    return link.get("id")


def read_openalex(folder):
    """(the records of each level, the snapshot block of the source): every page checked against its recorded hash, every identifier and parent checked."""
    report, _, pages = _report(folder, OPENALEX_REPORT, OPENALEX_SOURCE)
    levels = report.get("levels")
    if type(levels) is not dict:
        raise KbError("%s: levels must be an object" % OPENALEX_REPORT)
    rows = {level: [] for level in LEVELS}
    totals = {level: 0 for level in LEVELS}
    for entry in report["files"]:
        level = entry.get("level")
        if type(level) is not str or level not in rows:
            raise KbError("%s: %s has an unknown level %r" % (OPENALEX_REPORT, entry["file"], level if type(level) is str and len(level) < 40 else "?"))
        page = _parse(pages[entry["file"]], entry["file"])
        results = page.get("results") if type(page) is dict else None
        if type(results) is not list or any(type(row) is not dict for row in results):
            raise KbError("%s does not hold a list of results" % entry["file"])
        if entry.get("results") != len(results):
            raise KbError("%s holds %d results and its report says %r" % (entry["file"], len(results), entry.get("results")))
        rows[level].extend(results)
        totals[level] += len(results)
    for level in LEVELS:
        recorded = levels.get(level, {}).get("count") if type(levels.get(level)) is dict else None
        if not rows[level] or recorded != totals[level]:
            raise KbError("%s: the %s are %d in the pages and %r in the report" % (OPENALEX_REPORT, level, totals[level], recorded))
    records = {level: {} for level in LEVELS}
    for level in LEVELS:
        for row in rows[level]:
            ident = _short(level, row.get("id"))
            name = row.get("display_name")
            reason = shelfschema._text(name, shelfschema.NAME_MAX)
            if reason:
                raise KbError("the %s %s: its name %s" % (SINGULAR[level], ident, reason))
            description = row.get("description")
            if ident in records[level]:
                raise KbError("the %s %s is listed twice" % (SINGULAR[level], ident))
            records[level][ident] = {"id": ident, "name": name, "description": description, "raw": row}
    _link(records, "fields", "domains", ())
    _link(records, "subfields", "fields", ("domain",))
    _link(records, "topics", "subfields", ("field", "domain"))
    snapshot = {"url": OPENALEX_SOURCE, "retrieved": _started(report), "sha256": manifest_sha256([(n, _sha(p)) for n, p in pages.items()])}
    return records, snapshot


def _link(records, level, parent_level, also):
    """Set the parent of each record of `level`, and check that the other links it carries (its field, its domain) are those of its parent."""
    parent_key = SINGULAR[parent_level]
    for ident, record in records[level].items():
        parent = _short(parent_level, _parent_id(record["raw"], parent_key, level, record["name"]))
        if parent not in records[parent_level]:
            raise KbError("the %s %s has a %s %s that the lists do not hold" % (SINGULAR[level], ident, parent_key, parent))
        record["parent"] = parent
        for key in also:
            claimed = _short(key + "s", _parent_id(record["raw"], key, level, record["name"]))
            actual = _ancestor(records, parent_level, parent, key)
            if claimed != actual:
                raise KbError("the %s %s says its %s is %s and the %s above it is in %s" % (SINGULAR[level], ident, key, claimed, parent_key, actual))


def _ancestor(records, level, ident, key):
    """The identifier of the `key` ("field" or "domain") above a record: the record itself if it is of that kind, otherwise by its parents."""
    kind = {"field": "fields", "domain": "domains"}[key]
    while level != kind:
        record = records[level][ident]
        level, ident = {"topics": "subfields", "subfields": "fields", "fields": "domains"}[level], record["parent"]
    return ident


# --- the slugs and the scope sentences

def slug_base(name):
    """The name in lowercase words of ASCII letters and digits joined by single hyphens, at most 100 characters. Accent marks are dropped, an apostrophe is dropped and does not
    break the word (`Behcet's` gives `behcets`), a Greek letter is written as its name (`beta`), a few Latin letters that do not decompose are spelled (`strasse`), any other character is a break."""
    if type(name) is not str:
        raise KbError("a name must be text")
    text = "".join(c for c in unicodedata.normalize("NFKD", name) if unicodedata.category(c) != "Mn" and c not in APOSTROPHES).lower()
    text = "".join(" %s " % GREEK.get(c, c) if c in GREEK else SPELLED.get(c, c) for c in text)
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(slug) > SLUG_BASE_MAX:
        slug = slug[:SLUG_BASE_MAX].rstrip("-")
    if not slug:
        raise KbError("the name %r has no letter or digit to make a slug from" % (name if len(name) < 60 else name[:60] + "..."))
    return slug


def assign_slugs(items):
    """The slugs of a list of (level, name), in that order: the base of the name; where it is taken, the base and the level; where that is taken, with 2, 3, ... after the level."""
    used, out = set(), []
    for level, name in items:
        base = slug_base(name)
        candidate = base
        if candidate in used:
            candidate = "%s-%s" % (base, level)
            number = 2
            while candidate in used:
                candidate = "%s-%s-%d" % (base, level, number)
                number += 1
        used.add(candidate)
        out.append(candidate)
    return out


def _first_sentence(text):
    for found in SENTENCE_END.finditer(text):
        if text[:found.start()].split()[-1].lower() in ABBREVIATIONS:
            continue
        return text[:found.start()]
    return text


def scope_sentence(description, name, level, parent_name):
    """The scope sentence of an OpenAlex shelf: the first sentence of the description; a description that is a lowercase phrase is put after the name and a colon; with no description,
    the fixed sentence "Works on <name>, <a level> of <parent name>."; one longer than the limit is cut at a word and ends with three dots."""
    if description is not None and type(description) is not str:
        raise KbError("a description must be text")
    text = " ".join((description or "").split())
    if not text:
        if level == "domain" or parent_name is None:
            return "Works on %s, a domain of OpenAlex." % name
        return "Works on %s, %s of %s." % (name, ARTICLE[level], parent_name)
    sentence = _first_sentence(text)
    if sentence[:1].islower():
        sentence = "%s: %s" % (name, sentence)
    if sentence[-1] not in ".!?":
        sentence += "."
    if len(sentence) > shelfschema.SCOPE_MAX:
        cut = sentence[:shelfschema.SCOPE_MAX - 3].rsplit(" ", 1)[0].rstrip(" ,;:.")
        sentence = cut + "..."
    return sentence


# --- the outline and the custom shelves

def read_lcc(folder):
    """(the subclasses of the extract by code, the verified report entries by file name, the snapshot block of the source)."""
    report, report_bytes, pages = _report(folder, LCC_REPORT, LCC_SOURCE)
    extract = _parse(_read_bytes(os.path.join(folder, LCC_EXTRACT), LCC_EXTRACT), LCC_EXTRACT)
    if type(extract) is not dict or extract.get("report_sha256") != _sha(report_bytes):
        raise KbError("the extract %s was not made from the report %s" % (LCC_EXTRACT, LCC_REPORT))
    subclasses = extract.get("subclasses")
    if type(subclasses) is not list:
        raise KbError("the extract %s holds no list of subclasses" % LCC_EXTRACT)
    by_code = {}
    for entry in subclasses:
        if type(entry) is not dict or any(type(entry.get(k)) is not str for k in ("code", "caption", "file")):
            raise KbError("the extract %s holds a subclass that is not a code, a caption and a file" % LCC_EXTRACT)
        if entry["code"] in by_code:
            raise KbError("the extract %s holds the code %s twice" % (LCC_EXTRACT, entry["code"]))
        by_code[entry["code"]] = entry
    entries = {e["file"]: e for e in report["files"]}
    if LCC_INDEX_FILE not in entries or type(entries[LCC_INDEX_FILE].get("url")) is not str:
        raise KbError("%s does not name the index page %s" % (LCC_REPORT, LCC_INDEX_FILE))
    snapshot = {"url": entries[LCC_INDEX_FILE]["url"], "retrieved": _started(report), "sha256": manifest_sha256([(n, _sha(p)) for n, p in pages.items()])}
    return by_code, entries, snapshot


def read_custom(path, by_code, entries, lcc_snapshot):
    """(the custom entries sorted by code, the hash of the file): the file as the checker accepts it, made from this read of the outline, each entry's code and caption in the extract."""
    raw = _read_bytes(path, "the file of custom shelves", follow=True)
    data = _parse(raw, "the file of custom shelves")
    problems = shelfschema.check_custom(data)
    if problems:
        raise KbError("the file of custom shelves does not pass the checker: %s" % "; ".join(problems[:5]))
    source = data["source"]
    if source["sha256"] != lcc_snapshot["sha256"] or source["url"] != lcc_snapshot["url"]:
        raise KbError("the file of custom shelves was not made from this read of the outline (its hash or address differs from the report's)")
    for shelf in data["shelves"]:
        code = shelf["code"]
        found = by_code.get(code)
        if found is None:
            raise KbError("the custom shelf %s is not a subclass of the saved outline" % code)
        if shelf["name"] != found["caption"]:
            raise KbError("the custom shelf %s is named %r and the outline's caption is %r" % (code, shelf["name"], found["caption"]))
        page = entries.get(found["file"])
        if page is None or page.get("url") != shelf["page"]:
            raise KbError("the custom shelf %s names a page that is not the file of the outline that holds it (%s)" % (code, found["file"]))
    return sorted(data["shelves"], key=lambda s: s["code"]), _sha(raw)


# --- the file

def build(openalex_folder, lcc_folder, custom_path):
    """The schema file made from the three inputs: {"bytes", "counts", "snapshot", "shelves", "sha256"}; nothing is written."""
    records, openalex_snapshot = read_openalex(openalex_folder)
    by_code, entries, lcc_snapshot = read_lcc(lcc_folder)
    custom, custom_sha = read_custom(custom_path, by_code, entries, lcc_snapshot)

    order = [(level, record) for level in LEVELS for record in sorted(records[level].values(), key=lambda r: (r["name"].casefold(), r["name"], r["id"]))]
    slugs = assign_slugs([(SINGULAR[level], record["name"]) for level, record in order] + [("custom", shelf["name"]) for shelf in custom])
    slug_of = {(level, record["id"]): slug for (level, record), slug in zip(order, slugs)}
    parent_level = {"fields": "domains", "subfields": "fields", "topics": "subfields"}
    shelves = []
    for (level, record), slug in zip(order, slugs):
        parent_slug = parent_name = None
        if level in parent_level:
            parent = records[parent_level[level]][record["parent"]]
            parent_slug, parent_name = slug_of[(parent_level[level], parent["id"])], parent["name"]
        shelves.append({"slug": slug, "name": record["name"], "level": SINGULAR[level], "parent": parent_slug, "openalex": record["id"], "lcc": None,
                        "scope": scope_sentence(record["description"], record["name"], SINGULAR[level], parent_name)})
    for shelf, slug in zip(custom, slugs[len(order):]):
        shelves.append({"slug": slug, "name": shelf["name"], "level": "custom", "parent": shelf["parent"], "openalex": None, "lcc": shelf["code"], "scope": shelf["scope"]})
    data = {"format": shelfschema.FORMAT, "snapshot": {"openalex": openalex_snapshot, "lcc": lcc_snapshot, "custom": {"sha256": custom_sha}}, "shelves": shelves}
    problems = shelfschema.check_schema(data)
    if problems:
        raise KbError("the file the builder made does not pass the checker: %s" % "; ".join(problems[:5]))
    try:
        raw = _render(data).encode("utf-8")
    except UnicodeError as e:
        raise KbError("the file cannot be written as UTF-8: %s" % e)
    return {"bytes": raw, "counts": shelfschema.counts(data), "snapshot": data["snapshot"], "shelves": len(shelves), "sha256": _sha(raw)}


def _render(data):
    """One line for the format, one for the snapshot and one for each shelf, so that a change of one shelf is a change of one line."""
    lines = ['{', ' "format": %d,' % data["format"], ' "snapshot": %s,' % json.dumps(data["snapshot"], ensure_ascii=False), ' "shelves": [']
    lines.append(",\n".join("  " + json.dumps(shelf, ensure_ascii=False) for shelf in data["shelves"]))
    lines.extend([" ]", "}"])
    return "\n".join(lines) + "\n"


def write_new(path, raw):
    """Write `raw` to a file that does not exist (mode 644, never through a link), flushed to disk; a failed write leaves no file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as e:
        raise KbError("cannot create %s: %s" % (path, e.strerror or e))
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def run(openalex_folder, lcc_folder, custom_path, out_path):
    """Build the file and write it to a new file; what the command prints (the counts, the snapshot, the size and the hash)."""
    built = build(openalex_folder, lcc_folder, custom_path)
    write_new(out_path, built["bytes"])
    return {"file": out_path, "shelves": built["shelves"], "counts": built["counts"], "snapshot": built["snapshot"], "bytes": len(built["bytes"]), "sha256": built["sha256"]}
