"""Checking a quote against the piece of the book it is said to come from (`docs/plans/2026-11-07-card-grounding.md`, increment B).

A model that writes notes on a piece gives with each point a short quote of the piece. The quote is only worth something if it really
occurs in the piece, so the engine checks that, and a point whose quote does not occur is marked unverified. This shows that a claim
is in the book. It does not show that the claim is right.

The rule. Both the quote and the piece are put in one form: Unicode compatibility form (so a ligature or a no-break space is a letter
or a space), case folded, the soft hyphen taken out, the hyphens of other scripts made the plain hyphen, and white space of every
kind made one space. A hyphen at the end of a line is a word broken across lines in a converted PDF, and the quote may have the word
joined or with its hyphen, so a quote occurs if it is a substring of the piece with such breaks joined, or of the piece with them
kept. A reply has its line breaks turned into spaces before it is checked, so the break is a hyphen between two letters followed by
white space of any kind. A quote must be at least MIN_CHARS characters in that form and hold at least MIN_ALNUM letters or digits
(a shorter one, or a run of dots or dashes, proves nothing), and at most MAX_CHARS as written. It is checked against the one piece
it names and against nothing else, so a quote made of the words of two pieces, or of the title as a separate section, does not
occur. A heading of the book is a block of the piece, so a quote of a heading occurs."""
import re
import unicodedata

MIN_CHARS = 12
MIN_ALNUM = 8
MAX_CHARS = 240
_HYPHENS = dict.fromkeys(map(ord, "\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{FIGURE DASH}"), "-")
_BREAK = re.compile(r"(?<=\w)-\s+(?=\w)")
_SPACE = re.compile(r"\s+")


def normalize(text, join=True):
    """`text` in the one form quotes are compared in. A hyphen between two letters that is followed by white space (a word broken at
    the end of a line) is joined to the next word if `join`, and otherwise kept as a plain hyphen."""
    form = unicodedata.normalize("NFKC", str(text)).casefold().replace("\N{SOFT HYPHEN}", "").translate(_HYPHENS)
    form = _BREAK.sub("" if join else "-", form)
    return _SPACE.sub(" ", form).strip()


def occurs(quote, piece):
    """True if `quote` is a quote of `piece`: text of the allowed length that, normalised, is part of the normalised piece."""
    if not isinstance(quote, str) or not isinstance(piece, str) or len(quote) > MAX_CHARS:
        return False
    wanted = normalize(quote)
    if len(wanted) < MIN_CHARS or sum(c.isalnum() for c in wanted) < MIN_ALNUM:
        return False
    return wanted in normalize(piece) or wanted in normalize(piece, join=False)
