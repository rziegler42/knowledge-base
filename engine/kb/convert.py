"""Converted text: what a conversion tool hands back, checked, and the structure the rest of the engine reads it by.

A conversion is a list of **blocks** (a heading, a paragraph, a list item, a quote, a piece of code, a table row), each with
its text, and for a PDF the page it is on. The converted text is the blocks joined by blank lines. Everything a tool writes
is untrusted data: it is read with fixed limits, its form is checked in full, and its text is cleaned (`textutil.block_text`)
before any of it is used. A conversion that does not pass is refused whole.

Two kinds of tool output are read:

    blocks.json   written by the HTML tools: {"format": 1, "truncated": false, "blocks": [{"kind", "level", "text"}, ...]}
    text.txt      written by pdftotext: the text of the PDF, a form feed at the end of each page

The structure quality of a conversion is **full** (headings, and the text starts under one), **partial** (headings, but some
text lies before the first) or **flat** (no headings: a PDF is text with page marks only, and a page with no heading tags is
one block). The extractor-size rule (`check_partial`) is separate: it marks a book whose extraction may have missed text."""
import json
import os
import re
from collections import namedtuple

from . import KbError, approvals, config, convert_html, convert_pdf, convert_run, incoming, stages, textutil

FORMAT = 1
KINDS = ("heading", "paragraph", "list_item", "quote", "code", "table_row")
MAX_BLOCKS = 200_000
MAX_PAGES = 100_000
MAX_BLOCK_CHARS = 2_000_000
MAX_TOTAL_CHARS = 50_000_000
PATH_PART_CHARS = 80

# The first values of the extractor-size rule. They rest on a test of ten web pages, not on a larger study: a thread of 71
# comments gave 3.7k and 28k characters, a repository page 1.5k and 2.6k (a ratio of 1.7, which this value does not catch),
# and a page built by scripts 22 and 29 characters. Change them in the config (`partial_ratio`) or here, not in the data.
PARTIAL_RATIO = 2.0
THIN_CHARS = 200
THIN_RAW_BYTES = 3000

Block = namedtuple("Block", "index kind level text page path paragraph start end on_page")  # on_page: its number among the blocks of its page, 0 if none
Parsed = namedtuple("Parsed", "items truncated pages")


class Conversion:
    """The blocks of one conversion, with the converted text, its structure quality and, for a PDF, its page count."""

    def __init__(self, blocks, quality, pages):
        self.blocks, self.quality, self.pages = blocks, quality, pages
        self.text = "\n\n".join(b.text for b in blocks)
        self.chars = len(self.text)


def parse_blocks_json(raw):
    """The blocks in the output of an HTML tool, checked. Refuses anything that is not exactly the expected form."""
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError, MemoryError):  # not JSON, not UTF-8, nested far too deep, or too big to hold
        raise KbError("the tool's blocks are not readable JSON") from None
    if (not isinstance(obj, dict) or set(obj) != {"format", "blocks", "truncated"} or type(obj["format"]) is not int
            or obj["format"] != FORMAT):
        raise KbError("the tool's blocks are not in the expected form")
    if not isinstance(obj["truncated"], bool) or not isinstance(obj["blocks"], list):
        raise KbError("the tool's blocks are not in the expected form")
    if len(obj["blocks"]) > MAX_BLOCKS:
        raise KbError(f"the tool made more than {MAX_BLOCKS} blocks")
    items, total = [], 0
    for b in obj["blocks"]:
        if not isinstance(b, dict) or set(b) != {"kind", "level", "text"}:
            raise KbError("a block is not in the expected form")
        kind, level, text = b["kind"], b["level"], b["text"]
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(text, str):
            raise KbError("a block has a kind or a text that is not allowed")
        if kind == "heading":
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
                raise KbError("a heading has no level from 1 to 6")
        elif level is not None:
            raise KbError("only a heading has a level")
        if len(text) > MAX_BLOCK_CHARS:
            raise KbError(f"a block has more than {MAX_BLOCK_CHARS} characters")
        text = textutil.block_text(text)
        if not text:
            continue
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            raise KbError(f"the converted text is longer than {MAX_TOTAL_CHARS} characters")
        items.append({"kind": kind, "level": level, "text": text})
    return Parsed(items, obj["truncated"], None)


def parse_paged_text(raw):
    """The pages and paragraphs in the text of a PDF: pages end at a form feed, paragraphs at a blank line."""
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_TOTAL_CHARS:
        raise KbError(f"the converted text is longer than {MAX_TOTAL_CHARS} characters")
    pages = text.split("\f")
    if not pages[-1].strip():  # the form feed that ends the last page is not the start of another
        pages.pop()
    if len(pages) > MAX_PAGES:
        raise KbError(f"the document has more than {MAX_PAGES} pages")
    items = []  # cleaning only shortens text, so the size checked above holds for what is kept
    for number, page in enumerate(pages, start=1):
        for paragraph in re.split(r"\n\s*\n", page):
            cleaned = textutil.block_text(paragraph)
            if not cleaned:
                continue
            if len(items) >= MAX_BLOCKS:
                raise KbError(f"the tool made more than {MAX_BLOCKS} blocks")
            items.append({"kind": "paragraph", "level": None, "text": cleaned, "page": number})
    return Parsed(items, False, len(pages))


def build(items, pages=None):
    """The conversion for checked items: each block gets its section path, its paragraph number within the section and its
    place in the converted text. Deterministic, so a locator made against it is found again by the same input."""
    blocks, stack, paragraph, position, on_page = [], [], 0, 0, {}
    for index, item in enumerate(items):
        text = item["text"]
        if item["kind"] == "heading":
            while stack and stack[-1][0] >= item["level"]:
                stack.pop()
            stack.append((item["level"], " ".join(text.split())[:PATH_PART_CHARS].rstrip()))  # a cut at a space leaves none
            paragraph = 0
        else:
            paragraph += 1
        page = item.get("page")
        if page is not None:
            on_page[page] = on_page.get(page, 0) + 1  # counted as the blocks are made, not by each locator looking back
        blocks.append(Block(index, item["kind"], item["level"], text, page, tuple(t for _, t in stack),
                            paragraph, position, position + len(text), on_page.get(page, 0) if page is not None else 0))
        position += len(text) + 2  # the blank line between blocks
    headings = [b for b in blocks if b.kind == "heading"]
    quality = "flat" if not headings else ("full" if blocks[0].kind == "heading" else "partial")
    return Conversion(blocks, quality, pages)


def check_partial(sizes, raw_bytes, truncated, ratio):
    """The extractor-size rule. `sizes` maps each extractor that ran to the characters it returned. A book is marked
    partial when two extractors differ by more than `ratio`, when what they found is very little for the size of the file,
    or when an extractor stopped before the end of the page. One extractor alone cannot be compared, and that is said."""
    reasons = []
    if truncated:
        reasons.append("the file is larger than an extractor reads, so the end of it is missing")
    values = list(sizes.values())
    compared = len(values) >= 2
    if compared and max(values) > 0 and max(values) > ratio * min(values):
        reasons.append(f"one extractor returned much less text than the other ({min(values)} characters against {max(values)})")
    if values and max(values) < THIN_CHARS and raw_bytes >= THIN_RAW_BYTES:
        reasons.append(f"little text for the size of the file ({max(values)} characters from {raw_bytes} bytes): "
                       "it may be a page built by scripts or a scan of images")
    return {"rule": "extractor-size", "compared": compared, "partial": bool(reasons), "reasons": reasons,
            "ratio": ratio, "chars": dict(sizes)}


# --- the stage ---------------------------------------------------------------------------------------------------------

# What is converted, and by which tools in which order: the file a capture names as its primary, the kind of file that is,
# and for each kind the tools to try (name, the one file it writes, how that file is read). The first tool is the one used
# when nothing speaks against it.
INPUTS = {"page.html": "html", "paper.pdf": "pdf"}
TOOLS = {"html": [(convert_html.TRAF_NAME, "blocks.json", "blocks-json"), (convert_html.STD_NAME, "blocks.json", "blocks-json")],
         "pdf": [(convert_pdf.NAME, "text.txt", "paged-text")]}
MAX_RAW = 100_000_000
MAX_FAILED_GENERATIONS = 5  # outputs of one version of a tool that failed their checks, kept beside each other, before it is not run again
_ATTRS = ("tool", "version", "generation")


def _generations(store, book_id, version_id, tool):
    """The numbers of the outputs of one tool already filed for a version, lowest first."""
    folder = os.path.join(store.version_dir(book_id, version_id), "derived", tool)
    return sorted(int(n) for n in os.listdir(folder) if re.fullmatch(r"[0-9]{1,6}", n)) if os.path.isdir(folder) else []


def _made_by(store, book_id, version_id, tool, generation):
    """The tool (name and version) a filed output says it was made by, or None."""
    try:
        path = store.payload_path(book_id, version_id, f"derived/{tool}/{generation}")
        with open(os.path.join(path, incoming.MANIFEST)) as f:
            return json.load(f).get("tool")
    except (OSError, ValueError, AttributeError, KbError):
        return None


def _read_payload(store, book_id, version_id, name, filename, parse, manifest):
    """The conversion in a filed payload that has passed its hash check: exactly the one file the tool writes."""
    if set(manifest["files"]) != {filename}:
        raise KbError(f"the tool's output must be the one file {filename} and nothing else")
    if manifest["files"][filename]["size"] > MAX_RAW:
        raise KbError("the tool's output is too large to read")
    with open(os.path.join(store.payload_path(book_id, version_id, name), filename), "rb") as f:
        raw = f.read(MAX_RAW + 1)
    parsed = parse_blocks_json(raw) if parse == "blocks-json" else parse_paged_text(raw)
    return build(parsed.items, pages=parsed.pages), parsed.truncated


def load_conversion(store, book_id, version_id, record):
    """A recorded conversion read back from its payload, which is checked against its hashes first. Raises KbError if
    the payload has changed or no longer reads."""
    filename = "blocks.json" if record["parse"] == "blocks-json" else "text.txt"
    if record["payload"] != f"derived/{record['tool']}/{record['generation']}":
        raise KbError("the recorded conversion is not filed under its own tool and generation")
    manifest = store.verify_payload(book_id, version_id, record["payload"])
    if manifest.get("tool") != f"{record['tool']} {record['version']}":
        raise KbError("the recorded conversion was made by another tool or version than the record says")
    conversion, _ = _read_payload(store, book_id, version_id, record["payload"], filename, record["parse"], manifest)
    return conversion


def load_in_use(store, book_id, version_id):
    """(reference, conversion, record) for the conversion to use for a version, or None if it has none."""
    version = store.read_version(book_id, version_id)
    ref = version.get("conversion_in_use")
    if not ref:
        return None
    for record in version.get("conversions", []):
        if {k: record[k] for k in _ATTRS} == ref:
            return ref, load_conversion(store, book_id, version_id, record), record
    raise KbError("the conversion in use is not among the recorded conversions")


def _filed(store, book_id, version_id, entry, generation, filename, parse):
    """Take the output of a tool filed as `generation`: hash check, then the checks of its form. Returns the record and
    the conversion. Refuses an output made by another version of the tool than the one approved now."""
    name = f"derived/{entry['name']}/{generation}"
    manifest = store.adopt_payload(book_id, version_id, name)
    if manifest.get("tool") != f"{entry['name']} {entry['version']}":
        raise KbError(f"the output filed as {name} was made by {manifest.get('tool')}, not by the version approved now")
    conversion, truncated = _read_payload(store, book_id, version_id, name, filename, parse, manifest)
    record = {"tool": entry["name"], "version": entry["version"], "generation": generation, "payload": name,
              "parse": parse, "quality": conversion.quality, "blocks": len(conversion.blocks), "chars": conversion.chars,
              "pages": conversion.pages, "truncated": truncated}
    return record, conversion


def _convert_with(store, book_id, version_id, entry, filename, parse):
    """One tool on a version: a usable output filed before a stop is adopted; otherwise the tool is run, as the next
    generation beside any output that did not pass its checks."""
    existing = _generations(store, book_id, version_id, entry["name"])
    if existing:
        try:
            return _filed(store, book_id, version_id, entry, existing[-1], filename, parse)
        except (KbError, OSError, ValueError):
            pass  # that output is unusable; it stays where it is and the tool is run again, a few times at most
        label = f"{entry['name']} {entry['version']}"
        failed = sum(1 for g in existing if _made_by(store, book_id, version_id, entry["name"], g) == label)
        if failed >= MAX_FAILED_GENERATIONS:
            raise KbError(f"{label} has failed on this version {failed} times; its outputs are kept and it is not run again")
    generation = (existing[-1] if existing else 0) + 1
    convert_run.run_to_payload(store, book_id, version_id, entry, f"derived/{entry['name']}/{generation}")
    return _filed(store, book_id, version_id, entry, generation, filename, parse)


def _ratio(cfg):
    if "partial_ratio" not in cfg:
        return PARTIAL_RATIO
    value = cfg["partial_ratio"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 < value <= 1000:
        raise KbError("partial_ratio in the config must be a number greater than 1 and at most 1000")
    return value


def _summary(version, status):
    return {"status": status, "conversions": version["conversions"], "in_use": version["conversion_in_use"],
            "check": version["conversion_check"]}


def convert_version(store, book_id, version_id):
    """Convert a version that has been fetched and whose scan has finished (done, failed or skipped: a failed scan does
    not block conversion). Returns {"status": "done", ...}, {"status": "failed", "reason": ...} or {"status": "skipped",
    "reason": ...}. Raises KbError only if the version is not ready or the config setting is wrong.

    Each tool for the kind of file runs on the capture; one that is not approved or fails is noted and the others go on.
    The stage is done if at least one made a usable conversion. For a web page the two extractors are compared (the
    extractor-size rule); the conversion to use is the first tool's unless the rule marks the book partial, in which case it
    is the one with the most text. The capture and the earlier stages are never changed."""
    cfg = config.load()
    ratio = _ratio(cfg)
    version = store.read_version(book_id, version_id)
    state = stages.read(store, book_id, version_id)["stages"]
    if state["converted"]["status"] == "done":
        return _summary(version, "done")
    if state["converted"]["status"] == "skipped":
        return {"status": "skipped", "reason": state["converted"]["reason"]}
    if state["fetched"]["status"] != "done":
        raise KbError("the version has not been fetched yet, so there is nothing to convert")
    if state["scanned"]["status"] not in ("done", "failed", "skipped"):
        raise KbError("the version has not been scanned yet; the scan comes before the conversion")
    kind = INPUTS.get(version.get("primary"))
    if kind is None:
        reason = "there is no converter for this kind of file"
        stages.mark(store, book_id, version_id, "converted", "skipped", reason=reason)
        return {"status": "skipped", "reason": reason}
    made, notes = [], {}
    for name, filename, parse in TOOLS[kind]:
        try:
            entry = approvals.find_for(name, kind, cfg)
        except KbError as e:
            notes[name] = textutil.clean(str(e), 400)
            continue
        label = f"{entry['name']} {entry['version']}"
        try:
            made.append(_convert_with(store, book_id, version_id, entry, filename, parse))
        except (KbError, OSError, ValueError, MemoryError) as e:  # any failure of one tool is recorded, not raised
            notes[label] = textutil.clean(str(e), 400)
    if not made:
        reason = textutil.clean("; ".join(f"{k}: {v}" for k, v in notes.items()), 480)
        stages.mark(store, book_id, version_id, "converted", "failed", reason=reason)
        return {"status": "failed", "reason": reason}
    sizes = {f"{r['tool']} {r['version']}": r["chars"] for r, _ in made}
    cut = [f"{r['tool']} {r['version']}" for r, _ in made if r["truncated"]]
    check = check_partial(sizes, version["payloads"]["original"]["bytes"], cut, ratio)
    check["notes"] = notes
    records = [r for r, _ in made]
    chosen = max(records, key=lambda r: r["chars"]) if check["partial"] else records[0]
    in_use = {k: chosen[k] for k in _ATTRS}
    store.set_version_conversions(book_id, version_id, records, in_use, check)
    stages.mark(store, book_id, version_id, "converted", "done", tool=" + ".join(sizes))
    return _summary(store.read_version(book_id, version_id), "done")
