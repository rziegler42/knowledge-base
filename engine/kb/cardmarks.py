"""Count the items of the cards that are marked `stated` and `inferred`, by field and by form of the card.

A card of the grounded form marks each topic, key idea and caveat it keeps, and its limit, as `stated` (a verified note states it and a
second model confirmed it) or `inferred` (the card model's own word). A card of the sentence form also marks each kept sentence of the
summary and of the five neutral fields. This reads the newest card of each version of each active book, or the generations named, counts
the marks and prints numbers: no text of a card, no call to a model, and nothing written. It is the count that the decision about
inferred items rests on (`docs/plans/2026-11-10-decide-what-to-do-with-inferred-items.md`), kept as a command so that the figures can be
read again."""
from . import KbError, card

FIELDS = {"earlier": (*card.GROUNDED_LISTS, "neutral_limits"),
          "sentences": (*card.GROUNDED_LISTS, *card.SENTENCE_FIELDS)}   # the fields whose items carry a mark, in each form


def _blank():
    return {form: {"cards": 0, "fields": {f: {mark: 0 for mark in card.MARKS} for f in fields}} for form, fields in FIELDS.items()}


def _entries(grounding, form):
    """`(field, entry)` for each marked item of a card's grounding record."""
    for field in card.GROUNDED_LISTS:
        for e in grounding[field]:
            yield field, e
    if form == "earlier":
        if grounding["neutral_limits"]:
            yield "neutral_limits", grounding["neutral_limits"]
    else:
        for field in card.SENTENCE_FIELDS:
            for e in grounding["sentences"][field]["kept"]:
                yield field, e


def _cards(store, generations, books):
    """`(cards, unreadable)`: each card to count as `(book_id, version_id, made)`, and how many could not be read. The newest card of each
    version of each active book, or the generations named; a generation that no card has is refused."""
    found, unreadable, seen = [], 0, set()
    wanted = None if generations is None else set(generations)
    for book_id in (books if books is not None else store.list_books()):
        if store.read_book(book_id).get("state") != "active":
            continue
        for version_id in store.version_ids(book_id):
            have = card.generations(store, book_id, version_id)
            if not have:
                continue
            for number in ([have[-1]] if wanted is None else sorted(wanted & set(have))):
                seen.add(number)
                try:
                    _, made = card.read(store, book_id, version_id, number)
                except (KbError, OSError):
                    unreadable += 1
                    continue
                found.append((book_id, version_id, made))
    if wanted is not None and sorted(wanted - seen):
        raise KbError(f"no card has the generation {sorted(wanted - seen)[0]}")
    return found, unreadable


def counts(store, generations=None, books=None):
    """The marks of the cards, as `{"generations": "newest" or the list named, "cards": the cards read, "forms": {form: {"cards": n,
    "fields": {field: {"stated": n, "inferred": n}}}}, "without_marks": {"metadata": n, "not_checked": n}, "unreadable": n}`. A card built
    from the metadata has no model part (`metadata`); a card with a model part and no grounding record is of the first format and was
    not checked (`not_checked`); neither has marks. No text of a card is in the result."""
    found, unreadable = _cards(store, generations, books)
    forms, without = _blank(), {"metadata": 0, "not_checked": 0}
    for _, _, made in found:
        if made["model"] is None:
            without["metadata"] += 1
            continue
        grounding = made.get("grounding")
        if not isinstance(grounding, dict):
            without["not_checked"] += 1
            continue
        form = "sentences" if "sentences" in grounding else "earlier"
        forms[form]["cards"] += 1
        for field, e in _entries(grounding, form):
            forms[form]["fields"][field][e["mark"]] += 1
    return {"generations": "newest" if generations is None else sorted(set(generations)), "cards": len(found), "forms": forms,
            "without_marks": without, "unreadable": unreadable}
