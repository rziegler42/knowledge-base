"""Cleaning of text that came from outside (a web server, a tool, an arXiv answer) before it is stored or shown.

Whitespace is collapsed to single spaces; control, direction-mark, zero-width, surrogate, private-use and unassigned
characters are removed; and the result is cut to a length. Nothing is interpreted, so a stored reason, title or
caveat cannot carry escape sequences to a terminal or text that reorders what a reader sees."""
import unicodedata

_DROPPED = ("Cc", "Cf", "Cs", "Co", "Cn")
# characters that show as nothing but are not in a dropped category: fillers, a blank braille cell, a combining mark that
# joins nothing, and the variation selectors (which can ride on any character and carry a hidden message)
_BLANK = {0x034F, 0x115F, 0x1160, 0x2800, 0x3164, 0xFFA0}


def _hidden(c):
    code = ord(c)
    return unicodedata.category(c) in _DROPPED or code in _BLANK or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


def clean(text, limit, tail=False):
    """`text` made safe to store and show, at most `limit` characters; `tail` keeps the end instead of the start."""
    collapsed = " ".join(str(text if text is not None else "").split())
    kept = "".join(c for c in collapsed if not _hidden(c))
    return kept[-limit:] if tail else kept[:limit]


def literal(text, limit=80):
    """A name from outside, shown as a quoted ASCII literal (escapes for anything else) cut to a length, so it can be put
    in a message without a newline, an escape sequence or a direction mark getting through."""
    shown = ascii(str(text))
    return shown if len(shown) <= limit else shown[: limit - 3] + "..."
