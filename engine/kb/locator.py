"""Locators: the address of a passage in a conversion, and how it is found again.

A locator names the conversion it was made against (the tool, its version and the generation), because two tools give
different blocks for the same page, and it carries the place in that conversion by the kind of its structure:

    section   the heading path and the paragraph number under it     (a page with headings)
    page      the page and the block on it                           (a PDF)
    offset    a character offset in the converted text               (a page with no headings: one flat block)

and a hash of the excerpt: the first twelve words at that place, lower-cased, without punctuation. The place only holds
against the same conversion. Against another it is the excerpt that finds the passage again, by looking for those words
inside any block, so a different split into blocks does not matter. Nothing is guessed: no match is "not found". A passage
found in more than one block says how many, and names the first."""
import copy
import hashlib
import re
import unicodedata

from . import KbError, convert, textutil

VERSION = 1
KINDS = ("section", "page", "offset")
WINDOW = 12
MAX_LOOKAHEAD = 16_384  # how far on from a place its first twelve words are looked for: a place in a text with hardly a word in it
# (rules of dots, symbols) would otherwise cost the rest of the block, and a long block the square of its size
MAX_SEARCH_CHARS = 100_000_000  # the normalised text one search may go through: twice the longest text a conversion may have
MAX_GROWTH = 4  # normalising may lengthen text by this factor (and a little more): real text grows by a small fraction
LIMIT = 10 ** 9  # the largest number a locator may carry
_WORD = re.compile(r"\w+")
_SHA = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")
_VERSION = re.compile(r"[0-9A-Za-z._-]{1,40}")


def _normalise(text):
    """Text as it is compared: compatibility forms folded and letter case removed. A text that grows a great deal in doing so
    (some single characters become eighteen) is refused, so that text built to grow cannot make a search cost what it likes."""
    out = unicodedata.normalize("NFKC", text).casefold()
    if len(out) > MAX_GROWTH * len(text) + 1000:
        raise KbError("the text grows too much when it is normalised, so it is not searched")
    return out


def words(text):
    return _WORD.findall(_normalise(text))


def _first_words_in(text, start, end, n):
    """The first `n` words of text[start:end], reading only as much of it as that takes, without copying the rest, and never
    more than MAX_LOOKAHEAD characters of it: a place with fewer than `n` words in that stretch has the words that are there (or
    none), and every use of the words (making a locator, naming a place, checking one) reads the same stretch."""
    if n == 0:
        return []  # no words wanted: nothing to read, and no need to normalise text that may be built to grow
    end = min(end, start + MAX_LOOKAHEAD)
    size = 4096
    while True:
        stop = min(end, start + size)
        found = words(text[start:stop])
        if len(found) > n or stop >= end:  # more than n words: the n-th is complete even if the cut fell in the next
            return found[:n]
        size *= 4


def first_words(text, n=WINDOW):
    """The first `n` words of a text, reading only as much of it as that takes (a block may be millions of characters)."""
    return _first_words_in(text, 0, len(text), n)


def _hash(parts):
    return hashlib.sha256(" ".join(parts).encode("utf-8")).hexdigest()


def _chars_hash(text):
    """The hash a place with no words carries instead: that of its first 64 characters, as they are. A place that cannot be
    named by its words (it has none, or its text is built to grow under normalisation) is named by its position and by these,
    so a position alone is never taken for the place."""
    return hashlib.sha256(text[:64].encode("utf-8", "replace")).hexdigest()


def _excerpt_hash(taken, text):
    return _hash(taken) if taken else _chars_hash(text)


def _is_int(value, low, high=LIMIT):
    return type(value) is int and low <= value <= high


def _kind_of(conversion):
    if conversion.pages is not None:
        return "page"
    return "section" if conversion.has_headings else "offset"


def make(ref, conversion, block_index, offset=None):
    """The locator for a block of a conversion `ref` names. For a page with no headings `offset` may name a place inside
    the text (a character offset in the converted text); for the other kinds a locator is for the start of the block."""
    if not _is_int(block_index, 0) or block_index >= len(conversion.blocks):
        raise KbError(f"the conversion has no block {block_index!r}")
    block = conversion.blocks[block_index]
    kind = _kind_of(conversion)
    if offset is not None and kind != "offset":
        raise KbError("an offset can only be named in a page with no headings and no page marks")
    if kind == "section":
        at, source = {"path": list(block.path), "paragraph": block.paragraph}, block.text
    elif kind == "page":
        at, source = {"page": block.page, "block": block.on_page}, block.text
    else:
        where = block.start if offset is None else offset
        if not _is_int(where, block.start) or where >= block.end:
            raise KbError("the offset is not inside that block")
        at, source = {"offset": where}, conversion.text[where:block.end]
    taken = first_words(source, WINDOW)
    return {"v": VERSION, "kind": kind, "at": at,
            "conversion": {"tool": ref["tool"], "version": ref["version"], "generation": ref["generation"]},
            "excerpt": {"words": len(taken), "sha256": _excerpt_hash(taken, source)}}


def in_block(ref, conversion, block_index, offset):
    """An offset locator for a place inside a given block of any conversion: the start of a piece of a long block, which the
    search index names. Like `at_offset`, but the block is named and not looked for, so it costs what the words cost and not the
    number of blocks; and like `make`, a place whose text grows too much when normalised has none (a KbError)."""
    if not _is_int(block_index, 0) or block_index >= len(conversion.blocks):
        raise KbError(f"the conversion has no block {block_index!r}")
    block = conversion.blocks[block_index]
    if not _is_int(offset, block.start) or offset >= block.end:
        raise KbError("the offset is not inside that block")
    taken = _first_words_in(conversion.text, offset, block.end, WINDOW)
    return {"v": VERSION, "kind": "offset", "at": {"offset": offset},
            "conversion": {"tool": ref["tool"], "version": ref["version"], "generation": ref["generation"]},
            "excerpt": {"words": len(taken), "sha256": _excerpt_hash(taken, conversion.text[offset:min(block.end, offset + 64)])}}


def at_offset(ref, conversion, offset):
    """An offset locator for a place in the converted text of any conversion, not only a page with no headings: the place a
    reader left off at and wants to go on from. The offset must be inside a block."""
    if not _is_int(offset, 0):
        raise KbError("an offset is a whole number")
    for block in conversion.blocks:
        if block.start <= offset < block.end:
            source = conversion.text[offset:block.end]
            try:
                taken = first_words(source, WINDOW)
            except KbError:
                taken = []  # text built to grow when normalised has no words to compare: it is named by its place and its
                # first characters, so a reader can still go on through it (and a place alone is never taken for it)
            return {"v": VERSION, "kind": "offset", "at": {"offset": offset},
                    "conversion": {"tool": ref["tool"], "version": ref["version"], "generation": ref["generation"]},
                    "excerpt": {"words": len(taken), "sha256": _excerpt_hash(taken, source)}}
    raise KbError("the offset is not inside any block of the text")


def check(loc):
    """A locator from outside, checked in full. Refuses on any doubt, and returns it."""
    if (not isinstance(loc, dict) or set(loc) != {"v", "kind", "at", "conversion", "excerpt"} or type(loc["v"]) is not int
            or loc["v"] != VERSION):
        raise KbError("not a locator")
    kind, at, conv, ex = loc["kind"], loc["at"], loc["conversion"], loc["excerpt"]
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(at, dict):
        raise KbError("not a locator of a kind this reader knows")
    if kind == "section":
        ok = (set(at) == {"path", "paragraph"} and isinstance(at["path"], list) and len(at["path"]) <= 6
              and all(isinstance(t, str) and 0 < len(t) <= convert.PATH_PART_CHARS and textutil.clean(t, len(t)) == t
                      for t in at["path"]) and _is_int(at["paragraph"], 0))
    elif kind == "page":
        ok = set(at) == {"page", "block"} and _is_int(at["page"], 1) and _is_int(at["block"], 1)
    else:
        ok = set(at) == {"offset"} and _is_int(at["offset"], 0)
    ok = ok and isinstance(conv, dict) and set(conv) == {"tool", "version", "generation"} and (
        isinstance(conv["tool"], str) and bool(_NAME.fullmatch(conv["tool"]))
        and isinstance(conv["version"], str) and bool(_VERSION.fullmatch(conv["version"]))) and _is_int(conv["generation"], 1)
    ok = ok and isinstance(ex, dict) and set(ex) == {"words", "sha256"} and _is_int(ex["words"], 0, WINDOW) and \
        isinstance(ex["sha256"], str) and bool(_SHA.fullmatch(ex["sha256"]))
    if not ok:
        raise KbError("not a locator")
    return loc


WITHHELD = "[withheld: this text holds the words of an untrusted-text marker]"   # the one text the library shows for a text it withholds (`card.WITHHELD`)


def shown(loc):
    """A locator as a result shows it: a copy in which each heading of the path of a locator of a section is shown as a title is
    (`textutil.title`: cleaned, and withheld, here as `WITHHELD`, if its letters hold the words of an untrusted-text marker). A heading is
    text of a book, and a result carries a locator as data, outside the markers. Everything else is as it was, and the locator given is
    not changed. A place that holds a heading that is changed no longer equals the one the book has, so `resolve` finds the passage by
    the words of its excerpt; one that has no words is then not found."""
    out = copy.deepcopy(loc)
    if isinstance(out, dict) and out.get("kind") == "section" and isinstance(out.get("at"), dict) and isinstance(out["at"].get("path"), list):
        out["at"]["path"] = [(textutil.title(part, len(part)) or WITHHELD) if isinstance(part, str) else WITHHELD for part in out["at"]["path"]]
    return out


def _place(loc, conversion):
    """The blocks at the place a locator names, in this conversion."""
    kind, at, blocks = loc["kind"], loc["at"], conversion.blocks
    if kind == "section":
        return [b.index for b in blocks if list(b.path) == at["path"] and b.paragraph == at["paragraph"]]
    if kind == "page":
        on_page = [b.index for b in blocks if b.page == at["page"]]
        return [on_page[at["block"] - 1]] if at["block"] <= len(on_page) else []
    return [b.index for b in blocks if b.start <= at["offset"] < b.end]


def _text_at(loc, conversion, index):
    block = conversion.blocks[index]
    return conversion.text[loc["at"]["offset"]:block.end] if loc["kind"] == "offset" else block.text


def _holds(loc, conversion, index, n, target):
    """Whether the text at the place a locator names is the text it was made from: its words, or with none, its characters."""
    text = _text_at(loc, conversion, index)
    return (_chars_hash(text) if n == 0 else _hash(first_words(text, n))) == target


def resolve(loc, ref, conversion):
    """Find a locator again in `conversion`, which `ref` names. Returns {"status": "found" | "found_by_text" | "not_found",
    "block": the block index or None, "matches": how many blocks held it}."""
    loc = check(loc)
    n, target = loc["excerpt"]["words"], loc["excerpt"]["sha256"]
    if loc["conversion"] == {"tool": ref["tool"], "version": ref["version"], "generation": ref["generation"]}:
        here = [i for i in _place(loc, conversion) if _holds(loc, conversion, i, n, target)]
        if here:
            return {"status": "found", "block": here[0], "matches": len(here)}
    if n == 0:
        return {"status": "not_found", "block": None, "matches": 0}
    holding, budget, skipped = [], MAX_SEARCH_CHARS, 0
    for block in conversion.blocks:
        try:
            normal = _normalise(block.text)
        except KbError:
            skipped += 1  # a block built to grow is not searched; the rest of the book still is, and the answer says so
            continue
        budget -= len(normal)
        if budget < 0:
            raise KbError("there is too much text to search in one call")
        parts = _WORD.findall(normal)
        if any(_hash(parts[j:j + n]) == target for j in range(len(parts) - n + 1)):
            holding.append(block.index)
    extra = {"skipped_blocks": skipped} if skipped else {}  # said only when it happened, so a "not found" is not taken for a full search
    if holding:
        return {"status": "found_by_text", "block": holding[0], "matches": len(holding), **extra}
    return {"status": "not_found", "block": None, "matches": 0, **extra}
