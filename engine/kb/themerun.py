"""A run of the theme extraction over the library (`docs/specs/theme.md`; the plan `2026-11-11-run-the-theme-extraction-over-the-library`).

    plan    a snapshot of the books to make themes for, written as a record in the index root; it sends nothing. It lists the books to
            make, and every other book with the reason it is left out, counts the pieces, and gives an estimate of the time.

The state of a run is the library and a record. A book is skipped when the newest valid generation of themes of its current version was
made with the prompt version of the extraction and the model that the config names for it now, so a run that is run again repeats no
finished book. The skip rule sees the extraction only: the model and the prompt version of the check are not in a generation. The record
of each book names them, the plan reads the records of the runs before, and a skipped book whose newest record names another check, or
that has no record, is listed as "checked by another check, or not known" and is still skipped; `again` makes it.

The record is derived, disposable data in the folder of the card runs of the index root, as the card queue keeps its own; it holds ids,
counts and reasons and no text of a book or of a model's reply. It is written and read with the safe file functions of `cardstate`
(the folder is opened without following a link and must be private to the user, the file is put in place with one rename, and a file that
is a link or that others can read is refused), and its form is checked on writing and on reading."""
import json
import os
import re
import secrets
import time

from . import KbError, card, cardstate, convert, ids, models, textutil, theme, themecheck, themeextract

FORMAT = 1
RECORD = "theme-run.json"
KIND = "themes"
REASONS = ("inactive", "no_card", "no_conversion", "too_long", "already_made")
STATUSES = ("waiting", "done", "failed", "dropped")
SECONDS_PER_PIECE = (9, 14)       # the time of a piece, with the check of its themes, in the trials (9.5 and 10.6 seconds on PDFs, up to 14 on web pages)
CHECKS_PER_PIECE = (2.0, 2.5)     # the calls to the check for each piece in the trials (2.05 and 2.5)
RUNS_READ = 20                    # the records of earlier runs read to see what check a book was made with
_VERSION_ID = re.compile(r"v[1-9][0-9]{0,5}")
_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _count(value, high=10 ** 12):
    return type(value) is int and 0 <= value <= high


def _how(how):
    return (isinstance(how, dict) and set(how) == {"model", "prompt_version"} and models._valid_model(how["model"])
            and isinstance(how["prompt_version"], str) and models._VERSION.fullmatch(how["prompt_version"]) is not None)


def _check_item(i):
    bad = KbError("the record of a run has an item that is not valid")
    if not isinstance(i, dict) or set(i) != {"book_id", "version_id", "pieces", "status", "attempts", "generation", "reason", "made"}:
        raise bad
    ids.check_id(i["book_id"])
    if not isinstance(i["version_id"], str) or not _VERSION_ID.fullmatch(i["version_id"]):
        raise bad
    if not _count(i["pieces"], 10 ** 6) or i["status"] not in STATUSES or not _count(i["attempts"], 100):
        raise bad
    if i["generation"] is not None and not _count(i["generation"], 10 ** 6):
        raise bad
    if not isinstance(i["reason"], str) or len(i["reason"]) > 500 or textutil.clean(i["reason"], 500) != i["reason"]:
        raise bad
    made = i["made"]
    if made is not None and not (isinstance(made, dict) and set(made) == {"theme", "theme-check"} and _how(made["theme"]) and _how(made["theme-check"])):
        raise bad


def _check_record(rec):
    bad = KbError("the record of the run is not valid")
    if not isinstance(rec, dict) or set(rec) != {"format", "kind", "run", "created", "again", "extraction", "check", "items"}:
        raise bad
    if type(rec["format"]) is not int or rec["format"] != FORMAT or rec["kind"] != KIND:
        raise bad
    if not isinstance(rec["run"], str) or not cardstate._RUN.fullmatch(rec["run"]):
        raise bad
    if not isinstance(rec["created"], str) or not _ISO.fullmatch(rec["created"]) or type(rec["again"]) is not bool:
        raise bad
    if not _how(rec["extraction"]) or not _how(rec["check"]) or not isinstance(rec["items"], list) or len(rec["items"]) > cardstate.MAX_ITEMS:
        raise bad
    for i in rec["items"]:
        _check_item(i)
    if len({(i["book_id"], i["version_id"]) for i in rec["items"]}) != len(rec["items"]):
        raise bad
    return rec


def write_record(index_root, rec):
    """Put the record of a run in its file, whole, replacing an earlier one. Refuses a record that is not in the form."""
    _check_record(rec)
    try:
        data = (json.dumps(rec) + "\n").encode("ascii")
    except (TypeError, ValueError):
        raise KbError("the record of a run is not plain data") from None
    cardstate._put(index_root, rec["run"], RECORD, data)


def read_record(index_root, run):
    """The record of a run, or None if the run has none. Refuses a file that is not in the form, and one that is another run's."""
    if not isinstance(run, str) or not cardstate._RUN.fullmatch(run):
        raise KbError("a run is named with lower-case letters, digits and hyphens")
    doc = cardstate._get(index_root, run, RECORD)
    if doc is None:
        return None
    _check_record(doc)
    if doc["run"] != run:
        raise KbError("the record is not the record of this run")
    return doc


def _run_names(index_root):
    """The names of the runs in the folder, newest first (a name begins with the time the run was planned). A folder that is not there or is
    a link gives none."""
    try:
        root_fd = os.open(index_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return []
    try:
        try:
            fd = os.open(cardstate.FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except OSError:
            return []
        try:
            names = os.listdir(fd)
        except OSError:
            return []
        finally:
            os.close(fd)
    finally:
        os.close(root_fd)
    return sorted((n for n in names if cardstate._RUN.fullmatch(n)), reverse=True)


def _earlier_records(index_root):
    """The records of earlier runs, newest first, at most RUNS_READ; one that cannot be read is passed over."""
    found = []
    for name in _run_names(index_root):
        try:
            rec = read_record(index_root, name)
        except KbError:
            continue
        if rec is not None:
            found.append(rec)
            if len(found) >= RUNS_READ:
                break
    return found


def _done_item(records, book_id, version_id):
    """The newest item of the earlier records that says this version was made (its status is done). The caller compares its generation with
    the one that is there."""
    for rec in records:
        for i in rec["items"]:
            if i["book_id"] == book_id and i["version_id"] == version_id and i["status"] == "done":
                return i
    return None


def _made_with(store, book_id, version_id, extraction, records):
    """`(matches, generation number)` for the newest valid generation of themes of a version: whether it was made with the extraction given.
    A generation with no themes cannot say, so a record of a run must: an item that is done, for that generation, naming the extraction."""
    try:
        number, gen = theme.read(store, book_id, version_id)
    except KbError:
        return False, None
    if gen["themes"]:
        return all(t["made"]["model"] == extraction["model"] and t["made"]["prompt_version"] == extraction["prompt_version"] for t in gen["themes"]), number
    said = _done_item(records, book_id, version_id)   # the newest record of the version decides
    return bool(said and said["generation"] == number and said["made"] and said["made"]["theme"] == extraction), number


def _stamp():
    return time.strftime("%Y%m%dt%H%M%Sz", time.gmtime()) + "-" + secrets.token_hex(3)


def _assess(store, book_id, extraction, again, records):
    """`("make", version_id, pieces)` or `("skip", reason, version_id)` for a book; a book skipped as already made has the number of the
    generation that was found as a fourth item."""
    book = store.read_book(book_id)
    version_id = book.get("current_version")
    if book.get("state") != "active":
        return "skip", "inactive", version_id
    if not version_id:
        return "skip", "no_conversion", None
    try:
        card.read(store, book_id, version_id)
    except KbError:
        return "skip", "no_card", version_id
    try:
        loaded = convert.load_in_use(store, book_id, version_id)
        pieces = len(themeextract.pieces(loaded[1])) if loaded else None
    except KbError:
        pieces = None
    if pieces is None:
        return "skip", "no_conversion", version_id
    if pieces > themeextract.MAX_PIECES:
        return "skip", "too_long", version_id
    if not again:
        matches, number = _made_with(store, book_id, version_id, extraction, records)
        if matches:
            return "skip", "already_made", version_id, number
    return "make", version_id, pieces


def plan(store, cfg, book_ids=None, again=False):
    """Plan a run: write the record and return a summary (the run's name, the books to make with their pieces, the books left out with the
    reason, those skipped whose check is another or not known, the pieces, the calls that can be counted, the models and prompt versions,
    and the estimate). Makes no call. A book that is not there, or a model that is not set, is a refusal and nothing is written."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    extraction_entry, check_entry = models.choose(cfg, "theme")[0], models.choose(cfg, "theme-check")[0]
    entries = models.registry(cfg)
    extraction = {"model": entries[extraction_entry]["model"], "prompt_version": themeextract.THEME_JOB.prompt_version}
    check = {"model": entries[check_entry]["model"], "prompt_version": themecheck.check_job(1).prompt_version}
    if book_ids is not None:
        for book_id in book_ids:
            store.read_book(book_id)
    index_root = store.cfg["index_root"]
    records = _earlier_records(index_root)
    to_make, skipped_books, unknown, damaged, items, seen = [], [], [], [], [], set()
    counts = {reason: 0 for reason in REASONS}
    for book_id in (book_ids if book_ids is not None else store.list_books()):
        if book_id in seen:   # a book named twice is planned once
            continue
        seen.add(book_id)
        title = textutil.clean(store.read_book(book_id).get("title", ""), 80)
        outcome = _assess(store, book_id, extraction, again, records)
        having = outcome[1] if outcome[0] == "make" else outcome[2]
        broken = theme.damaged(store, book_id, having) if having else []   # a generation that fails its check is passed over by a reader; show it
        if broken:
            damaged.append({"book_id": book_id, "title": title, "generations": [n for n, _ in broken]})
        if outcome[0] == "make":
            _, version_id, pieces = outcome
            to_make.append({"book_id": book_id, "title": title, "pieces": pieces})
            items.append({"book_id": book_id, "version_id": version_id, "pieces": pieces, "status": "waiting", "attempts": 0, "generation": None,
                          "reason": "", "made": None})
            continue
        reason, version_id = outcome[1], outcome[2]
        counts[reason] += 1
        skipped_books.append({"book_id": book_id, "title": title, "reason": reason})
        if reason == "already_made":
            said = _done_item(records, book_id, version_id)   # a record is evidence of the check only for the generation that is there now
            if not (said and said["generation"] == outcome[3] and said["made"] and said["made"]["theme-check"] == check):
                unknown.append({"book_id": book_id, "title": title})
    if len(items) > cardstate.MAX_ITEMS:
        raise KbError(f"a run holds at most {cardstate.MAX_ITEMS} books; name fewer with --book")
    for _ in range(5):
        run_id = _stamp()
        if cardstate._get(index_root, run_id, RECORD) is None:
            break
    else:
        raise KbError("no free name for the run was found")
    write_record(index_root, {"format": FORMAT, "kind": KIND, "run": run_id, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "again": again, "extraction": extraction, "check": check, "items": items})
    pieces_all = sum(b["pieces"] for b in to_make)
    low, high = SECONDS_PER_PIECE
    return {"run": run_id, "books": len(to_make), "again": again, "to_make": to_make, "skipped": counts, "skipped_books": skipped_books,
            "check_unknown": unknown, "damaged": damaged, "pieces": pieces_all, "calls_known": {"theme": pieces_all},
            "models": {"theme": extraction_entry, "theme-check": check_entry},
            "prompt_versions": {"theme": extraction["prompt_version"], "theme-check": check["prompt_version"]},
            "estimate": {"seconds_low": pieces_all * low, "seconds_high": pieces_all * high,
                         "check_calls_low": round(pieces_all * CHECKS_PER_PIECE[0]), "check_calls_high": round(pieces_all * CHECKS_PER_PIECE[1]),
                         "basis": f"an estimate from the trials: {low} to {high} seconds a piece with the check of its themes, and "
                                  f"{CHECKS_PER_PIECE[0]} to {CHECKS_PER_PIECE[1]} calls to the check for each piece; a call whose answer is refused is asked once more"}}
