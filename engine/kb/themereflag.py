"""Giving the themes already made the flags of the rule now in force, with no call to a model (`docs/specs/theme.md`; the plan
`2026-11-12-flag-only-words-that-few-books-hold`).

The flag `field_words` of a theme is worked out from its description and the book's vocabulary (`themecheck.flag_vocabulary`), so it can
be worked out again without a model. For each active book that has a card, a conversion in use and themes, the newest valid generation is
read, and for each theme the flags other than `field_words` are kept as they are, in their order, and the flag the rule gives now is put
after them (or none). A book whose themes already have those flags is left alone. For a book whose flags change, the themes are filed as the
next generation, with everything but the flags as it was (`made` included, so `themes-run` still skips the book); the older generations are
never changed. It can be run again: a second run files nothing.

`plan` reads and writes nothing. `run` holds the lock that the card queue and the theme run hold, so they never run together against one index
root, and goes on to the next book when one fails, saying only the kind of the failure. Nothing here is sent to a model."""
import contextlib

from . import KbError, card, cardstate, convert, textutil, theme, themecheck, themejournal

REASONS = ("inactive", "no_themes", "damaged", "no_card", "no_conversion", "unreadable")   # why a book is left out
KIND = "field_words"


def _flags(t, vocabulary):
    """The flags a theme has by the rule now: those that are not `field_words`, in their order, then the flag of its description, if any."""
    flags = [f for f in t["flags"] if f["kind"] != KIND]
    flag = themecheck.field_flag(t["neutral"], vocabulary)
    return flags + [flag] if flag else flags


def _flagged(t):
    return any(f["kind"] == KIND for f in t["flags"])


def _assess(store, book_id, df, size):
    """`("left out", reason)` for a book that cannot be given the flags, or `("ok", version, generation, themes, changed)`: the version, the
    newest valid generation, the themes with the flags of the rule now and whether any flag changed."""
    book = store.read_book(book_id)
    version = book.get("current_version")
    if book.get("state") != "active" or not version:
        return "left out", "inactive"
    try:
        _, generation = theme.read(store, book_id, version)
    except KbError:
        # no generation was ever filed, or every one that was fails its check
        return "left out", "damaged" if theme.generations(store, book_id, version) else "no_themes"
    try:
        current = card.read(store, book_id, version)[1]
    except KbError:
        return "left out", "no_card"
    try:
        loaded = convert.load_in_use(store, book_id, version)
    except KbError:
        loaded = None
    if loaded is None:
        return "left out", "no_conversion"
    model = current.get("model") or {}
    topics = list(model.get("topics", [])) + list(model.get("adjacent_topics", []))
    vocabulary = themecheck.flag_vocabulary(loaded[1].text, df, size, current["title"], topics)
    themes = []
    for t in generation["themes"]:
        themes.append({**t, "flags": _flags(t, vocabulary)})
    changed = any(new["flags"] != old["flags"] for new, old in zip(themes, generation["themes"]))
    return "ok", version, generation, themes, changed


def _survey(store):
    """What a run would do, book by book: the summary of `plan` and, for each book to change, the version and the themes to file."""
    df, size = themecheck.library_frequencies(store)
    to_change, left_out, filing = [], [], {}
    unchanged = themes = before = after = 0
    for book_id in store.list_books():
        title = ""
        try:
            title = textutil.clean(store.read_book(book_id).get("title") or "", 80)
            got = _assess(store, book_id, df, size)
        except Exception:   # a book that cannot be read is left out and named, and the others go on; the kind of error is not shown
            got = ("left out", "unreadable")
        if got[0] == "left out":
            left_out.append({"book_id": book_id, "title": title, "reason": got[1]})
            continue
        _, version, generation, new_themes, changed = got
        flagged_before = sum(_flagged(t) for t in generation["themes"])
        flagged_after = sum(_flagged(t) for t in new_themes)
        themes += len(new_themes)
        before += flagged_before
        after += flagged_after
        if changed:
            to_change.append({"book_id": book_id, "title": title, "themes": len(new_themes), "flagged_before": flagged_before,
                              "flagged_after": flagged_after})
            filing[book_id] = (version, new_themes)
        else:
            unchanged += 1
    counts = {reason: sum(1 for x in left_out if x["reason"] == reason) for reason in REASONS if any(x["reason"] == reason for x in left_out)}
    summary = {"books": len(to_change), "to_change": to_change, "unchanged": unchanged, "left_out": left_out, "left_out_counts": counts,
               "themes": themes, "flagged_before": before, "flagged_after": after, "share": themecheck.FLAG_SHARE, "library_books": size}
    return summary, filing


def plan(store):
    """The books whose themes would get other flags, the books left out with the reason, and the themes flagged before and after. Reads
    only: nothing is written and no model is called."""
    return _survey(store)[0]


def run(store):
    """File the themes of each book to change as its next generation, with the flags of the rule now in force. Returns the plan that was
    carried out with `filed` (book id and the number of the generation) and `failed` (book id and the kind of the failure, never a message).
    A book that fails does not end the run. Holds the lock of the card queue and the theme run; a second holder is refused."""
    with cardstate.lock(store.cfg["index_root"], themejournal.RUN):
        summary, filing = _survey(store)   # worked out under the lock, so that what is filed is what was seen
        filed, failed = [], []
        for item in summary["to_change"]:
            book_id = item["book_id"]
            version, new_themes = filing[book_id]
            try:
                number = theme.file(store, theme.make(book_id, version, new_themes))
                filed.append({"book_id": book_id, "generation": number})
            except KbError:
                failed.append({"book_id": book_id, "reason": "failed"})
            except Exception as e:   # whatever one book does to the program, the others go on; only the kind of error is shown
                failed.append({"book_id": book_id, "reason": f"an unexpected error ({type(e).__name__})"})
    return {**summary, "filed": filed, "failed": failed}
