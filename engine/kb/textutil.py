"""Cleaning of text that came from outside (a web server, a tool, an arXiv answer) before it is stored or shown.

Whitespace is collapsed to single spaces; control, direction-mark, zero-width, surrogate, private-use and unassigned
characters are removed; and the result is cut to a length. Nothing is interpreted, so a stored reason, title or
caveat cannot carry escape sequences to a terminal or text that reorders what a reader sees."""
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
