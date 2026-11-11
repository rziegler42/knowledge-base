"""Cleaning of text that came from outside (a web server, a tool, an arXiv answer) before it is stored or shown.

Whitespace is collapsed to single spaces; control, direction-mark, zero-width, surrogate, private-use and unassigned
characters are removed; and the result is cut to a length. Nothing is interpreted, so a stored reason, title or
caveat cannot carry escape sequences to a terminal or text that reorders what a reader sees."""
import re
import unicodedata

_DROPPED = ("Cc", "Cf", "Cs", "Co", "Cn")
# characters that show as nothing but are not in a dropped category: fillers, a blank braille cell, a combining mark that
# joins nothing, the Khmer inherent vowels, and the variation selectors (which can ride on any character and carry a hidden message)
_BLANK = {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x2800, 0x3164, 0xFFA0}


def _hidden(c):
    code = ord(c)
    return (unicodedata.category(c) in _DROPPED or code in _BLANK or 0x180B <= code <= 0x180F  # Mongolian free variation selectors
            or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF)


def clean(text, limit, tail=False):
    """`text` made safe to store and show, at most `limit` characters; `tail` keeps the end instead of the start."""
    collapsed = " ".join(str(text if text is not None else "").split())
    kept = " ".join("".join(c for c in collapsed if not _hidden(c)).split())  # a hidden character between spaces leaves one
    # cut, and no space left at the cut: what comes back is its own cleaned form (code compares a stored string with it)
    return kept[-limit:].lstrip() if tail else kept[:limit].rstrip()


_WORD = re.compile(r"[^\W\d_]{4,}")


def words(text):
    """The words of a text, in order: runs of four or more letters, after the compatibility forms are folded and the case removed. Nothing
    is stemmed. The same words are used to tell a description from the words of a book's field (`themecheck`) and to tell a model which
    words to avoid (`themeextract`)."""
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _letters(text):
    """Only the letters of a text, in their plain lower-case forms (compatibility forms such as fullwidth or bold letters are
    folded first; accents are not letters, so they go), so that spellings of a phrase that differ in spacing, joiners or form are one.
    Only the ASCII letters are kept: after folding, every real spelling of the markers is ASCII, and a letter that reads as punctuation
    (a modifier letter, a click, a stretch mark) must not split the phrase."""
    folded = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in folded if c.isascii() and c.isalpha())


# The words both markers around text from outside carry (search.MARKER: "untrusted text from an outside source", read.END_MARKER:
# "end of untrusted text"): a title that holds them could imitate the end of the untrusted section.
MARKER_WORDS = "untrustedtext"


def title(text, limit):
    """A title made safe to store and show: cleaned and cut like any text from outside, and empty when its letters, folded, hold the
    words of an untrusted-text marker (no title is better than one that imitates the markers). Look-alike letters from another
    alphabet are not folded: this is a guard, not a filter of meaning."""
    kept = clean(text, limit)
    return "" if MARKER_WORDS in _letters(kept) else kept


def scrub_roots(store, text):
    """Text with the library's folders taken out (`store` is anything with `bulk` and a `cfg` that may name `index_root` and
    `bulk_root`). Done on text that is not yet cleaned, so a folder written with odd spacing still matches, and again after cleaning,
    which can join a folder that a hidden character had split."""
    for private in (store.bulk, store.cfg.get("index_root"), store.cfg.get("bulk_root")):
        if private:
            text = text.replace(private, "<library>")
    return text


def block_text(text):
    """The text of one converted block: its lines are kept (a line break in a page or a PDF is part of its structure), spaces
    inside a line are collapsed, empty lines go, and everything `clean` removes goes too. Line separators of every kind
    become line breaks first, and hidden characters are removed only inside a line, so they cannot join two lines."""
    lines = []
    for line in str(text if text is not None else "").splitlines():
        spaced = " ".join(line.split())  # a tab or other whitespace is a space, not a hidden character
        kept = " ".join("".join(c for c in spaced if not _hidden(c)).split())  # collapse again: a hidden one may sit between two spaces
        if kept:
            lines.append(kept)
    return "\n".join(lines)


def literal(text, limit=80):
    """A name from outside, shown as a quoted ASCII literal (escapes for anything else) cut to a length, so it can be put
    in a message without a newline, an escape sequence or a direction mark getting through."""
    shown = ascii(str(text))
    return shown if len(shown) <= limit else shown[: limit - 3] + "..."


def window(text, start, chars):
    """The piece of `text` from `start`: at most `chars` characters, cut at a word, and where the next piece starts (None at the
    end). Returns (end, next_offset)."""
    total = len(text)
    if start + chars >= total:
        return total, None
    end = start + chars
    floor = start + chars // 2
    cut = max(text.rfind(" ", floor, end + 1), text.rfind("\n", floor, end + 1))  # the last place to break, in the later half
    if cut > floor:
        end = cut
    following = end
    while following < total and text[following].isspace():
        following += 1
    if following >= total:
        return total, None
    return end, following


def pieces(text, chars):
    """The consecutive pieces of `text`, each at most `chars` characters and cut at a word where one is near the end, as a list
    of (start, end). Each next one starts at the first character that is not space, so the pieces hold every word once. Reading
    time grows with the length of the text alone."""
    found, start, total = [], 0, len(text)
    while start < total:
        end, following = window(text, start, chars)
        found.append((start, end))
        if following is None:
            break
        start = following
    return found
