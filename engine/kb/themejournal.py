"""The journal of a book in the making: the accepted answer of each piece of the theme extraction, kept in the index root.

A book is read in pieces and the model is asked once for each (`themeextract.extract`). A refused answer for one piece fails the book,
and without a journal the next try asks for every piece again. This file keeps, for one book and version, the answer of each piece that
was accepted, so that a later try asks only for the pieces it has no answer for.

    <index root>/card-runs/theme-journal/<book>-<version>.json
      {"format": 1, "book_id": ..., "version_id": ..., "entries": [{"piece", "key", "values", "record"}, ...]}

An entry is one accepted piece: its number (from 1, in order, with no gap), the reuse key (64 hex digits; the caller makes it from the
inputs of the piece's prompt and this module only keeps it), the checked answer and the record of the call that was accepted. The values
are untrusted text from a model, so the caller checks them again when it uses them. They are not signed: whoever can write the file can
say what the model answered, as with the journal of a card (`cardstate`); the file is in a folder that only the user can enter, and that
is the whole of its protection.

The file is derived data that can be deleted at any time without losing a theme. It is written and read with the functions that
`cardstate` uses for the files of the index root: the folders are made private to the user and checked, no link is followed, the file is
made with the exclusive create and mode 600 under a temporary name and put in place with one rename, a file that is a link, a pipe,
another user's, readable by others or larger than the limit is refused, and a text that is not one JSON object with exactly the keys
above is refused. The folder is named like a run of the card queue (`RUN`) so that those functions serve it; it holds no run."""
import json
import re

from . import KbError, cardstate

FORMAT = 1
RUN = "theme-journal"
MAX_PIECES = 150   # the pieces one run reads (`themeextract.MAX_PIECES`; a test keeps the two equal)
_KEY = re.compile(r"[0-9a-f]{64}")
_KEYS = ("piece", "key", "values", "record")
RUN_CHECKS = "theme-check-journal"   # the folder of the answers of the checks, named like a run of the card queue as `RUN` is
MAX_CHECKS = 5000                    # the checks one book keeps (one for each theme: a whole book of 150 pieces makes far fewer)
_CHECK_KEYS = ("key", "values", "record")
MAX_VERDICTS, MAX_VERDICT_CHARS = 64, 40   # the verdicts of one check: a word for each part asked about (five at most), and a word is `supports`, `partly` or `no`


def _check_entry(e, number):
    bad = KbError("the saved pieces of a book have an entry that is not valid")
    if not isinstance(e, dict) or set(e) != set(_KEYS):
        raise bad
    if type(e["piece"]) is not int or e["piece"] != number:
        raise bad
    if not isinstance(e["key"], str) or not _KEY.fullmatch(e["key"]):
        raise bad
    # the values and the record are what a card's journal holds for a call, and are checked as it checks them
    cardstate._check_entry({"job": "theme", "entry": "x", "values": e["values"], "record": e["record"]})


def _check_entries(entries):
    if not isinstance(entries, list) or len(entries) > MAX_PIECES:
        raise KbError("the saved pieces of a book are not a list, or are more than one run reads")
    for number, e in enumerate(entries, start=1):
        _check_entry(e, number)


def _put(run, check, what, index_root, book_id, version_id, entries):
    cardstate._names(run, book_id, version_id)
    check(entries)
    doc = {"format": FORMAT, "book_id": book_id, "version_id": version_id, "entries": entries}
    try:
        data = (json.dumps(doc, allow_nan=False) + "\n").encode("ascii")
        same = cardstate._loads(data.decode("ascii")) == doc   # what is read back must be what was given: no tuple, no key that is not text
    except (TypeError, ValueError, RecursionError):
        raise KbError(f"the saved {what} of a book are not plain data") from None
    if not same:
        raise KbError(f"the saved {what} of a book are not plain data")
    cardstate._put(index_root, run, f"{book_id}-{version_id}.json", data)


def _get(run, check, what, index_root, book_id, version_id):
    _, name = cardstate._names(run, book_id, version_id)
    doc = cardstate._get(index_root, run, name)
    if doc is None:
        return None
    if set(doc) != {"format", "book_id", "version_id", "entries"} or type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise KbError(f"the saved {what} of a book are not of this format")
    if doc["book_id"] != book_id or doc["version_id"] != version_id:
        raise KbError(f"the saved {what} are for another book or version than their file name says")
    check(doc["entries"])
    return doc["entries"]


def write(index_root, book_id, version_id, entries):
    """Put the entries of the book in its file, whole, replacing an earlier one. Refuses entries that are not as described."""
    _put(RUN, _check_entries, "pieces", index_root, book_id, version_id, entries)


def read(index_root, book_id, version_id):
    """The entries of the book, or None if there is no file. Refuses a file that is not as the module describes."""
    return _get(RUN, _check_entries, "pieces", index_root, book_id, version_id)


def remove(index_root, book_id, version_id):
    """Delete the file of the book, and what a crash left beside it, if there are any."""
    cardstate.remove(index_root, RUN, book_id, version_id)


# ---- the answers of the checks of a book

def _check_check_entries(entries):
    bad = KbError("the saved checks of a book have an entry that is not valid")
    if not isinstance(entries, list) or len(entries) > MAX_CHECKS:
        raise KbError("the saved checks of a book are not a list, or are more than one book holds")
    seen = set()
    for e in entries:
        if not isinstance(e, dict) or set(e) != set(_CHECK_KEYS) or not isinstance(e["key"], str) or not _KEY.fullmatch(e["key"]) or e["key"] in seen:
            raise bad
        seen.add(e["key"])
        words = e["values"].get("verdicts") if isinstance(e["values"], dict) and set(e["values"]) == {"verdicts"} else None
        if not isinstance(words, list) or len(words) > MAX_VERDICTS or not all(isinstance(w, str) and len(w) <= MAX_VERDICT_CHARS for w in words):
            raise bad                                          # the values of a check are its verdicts and nothing else: a file that holds more is not one this engine wrote
        cardstate._check_entry({"job": "theme-check", "entry": "x", "values": e["values"], "record": e["record"]})   # checked as a card's journal checks a call


def write_checks(index_root, book_id, version_id, entries):
    """Put the accepted checks of the book in their file, whole, replacing an earlier one: each entry is `{"key", "values", "record"}`, the key (64 hex digits, made by the
    caller from the inputs of the check's prompt, and unique in the file) saying which check it answers. Refuses entries that are not as described."""
    _put(RUN_CHECKS, _check_check_entries, "checks", index_root, book_id, version_id, entries)


def read_checks(index_root, book_id, version_id):
    """The checks kept for the book, or None if there is no file. Refuses a file that is not as the module describes."""
    return _get(RUN_CHECKS, _check_check_entries, "checks", index_root, book_id, version_id)


def remove_checks(index_root, book_id, version_id):
    """Delete the file of the checks of the book, and what a crash left beside it, if there are any."""
    cardstate.remove(index_root, RUN_CHECKS, book_id, version_id)
