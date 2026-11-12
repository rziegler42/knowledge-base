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
from collections import Counter

from . import KbError, card, cardstate, convert, ids, models, textutil, theme, themecheck, themeextract, themejournal

FORMAT = 1
RECORD = "theme-run.json"
KIND = "themes"
REASONS = ("inactive", "no_card", "no_conversion", "too_long", "already_made")
STATUSES = ("waiting", "done", "failed", "dropped")
SECONDS_PER_PIECE = (9, 14)       # the time of a piece, with the check of its themes, in the trials (9.5 and 10.6 seconds on PDFs, up to 14 on web pages)
CHECKS_PER_PIECE = (2.0, 2.5)     # the calls to the check for each piece in the trials (2.05 and 2.5)
RUNS_READ = 20                    # the records of earlier runs read to see what check a book was made with
RETRIES = 1                       # a book that fails is tried once more, after the last book
STOP_AFTER = 3                    # books in a row that fail for a reason that is not a refused answer stop the run
# What an item says of why it did not finish: a fixed kind, never a title or a piece of a reply or of an error message.
REASON_KINDS = {"refused": "an answer of a model was refused and kept aside", "failed": "a call or a step failed",
                "no_longer_active": "the book is no longer active or has another current version",
                "conversion_changed": "the conversion in use changed since the plan"}
_UNEXPECTED = re.compile(r"an unexpected error \([A-Za-z_][A-Za-z0-9_]{0,59}\)")
DROP_KINDS = ("span_over_limit", "pointer_not_numbers", "pointer_not_in_piece", "proof_or_definition", "merged_near_identical", "unchecked",
              "unusable_field", "other")
_KIND = re.compile(r"[a-z][a-z_]{0,39}")
_VERSION_ID = re.compile(r"v[1-9][0-9]{0,5}")
_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _count(value, high=10 ** 12):
    return type(value) is int and 0 <= value <= high


def _how(how):
    return (isinstance(how, dict) and set(how) == {"model", "prompt_version"} and models._valid_model(how["model"])
            and isinstance(how["prompt_version"], str) and models._VERSION.fullmatch(how["prompt_version"]) is not None)


def _conversion(c):
    return (isinstance(c, dict) and set(c) == {"tool", "version", "generation"} and _count(c["generation"], 10 ** 6)
            and all(isinstance(c[k], str) and 0 < len(c[k]) <= 100 for k in ("tool", "version")))


def _stats(s):
    keys = {"themes", "dropped", "flags", "stated", "inferred", "pieces", "calls", "input_tokens", "output_tokens", "seconds"}
    return (isinstance(s, dict) and set(s) == keys
            and all(_count(s[k]) for k in keys - {"dropped", "flags"})
            and isinstance(s["dropped"], dict) and all(k in DROP_KINDS and _count(v) for k, v in s["dropped"].items())
            and isinstance(s["flags"], dict) and len(s["flags"]) <= 20
            and all(isinstance(k, str) and _KIND.fullmatch(k) and _count(v) for k, v in s["flags"].items()))


def _reason_ok(reason):
    return isinstance(reason, str) and (reason == "" or reason in REASON_KINDS or _UNEXPECTED.fullmatch(reason) is not None)


def _check_item(i):
    bad = KbError("the record of a run has an item that is not valid")
    if not isinstance(i, dict) or set(i) != {"book_id", "version_id", "pieces", "status", "attempts", "generation", "reason", "made", "conversion", "stats"}:
        raise bad
    ids.check_id(i["book_id"])
    if not isinstance(i["version_id"], str) or not _VERSION_ID.fullmatch(i["version_id"]):
        raise bad
    if not _count(i["pieces"], 10 ** 6) or i["status"] not in STATUSES or not _count(i["attempts"], 100):
        raise bad
    if i["generation"] is not None and not _count(i["generation"], 10 ** 6):
        raise bad
    if not isinstance(i["reason"], str) or len(i["reason"]) > 500 or textutil.clean(i["reason"], 500) != i["reason"] or not _reason_ok(i["reason"]):
        raise bad
    made = i["made"]
    if made is not None and not (isinstance(made, dict) and set(made) == {"theme", "theme-check"} and _how(made["theme"]) and _how(made["theme-check"])):
        raise bad
    if i["conversion"] is not None and not _conversion(i["conversion"]):
        raise bad
    if i["stats"] is not None and not _stats(i["stats"]):
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
    return sorted((n for n in names if cardstate._RUN.fullmatch(n) and n != themejournal.RUN), reverse=True)   # the folder of the journals holds no run


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
    """`("make", version_id, pieces, reference of the conversion in use)` or `("skip", reason, version_id)` for a book; a book skipped as
    already made has the number of the generation that was found as a fourth item."""
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
    return "make", version_id, pieces, loaded[0]


def _current(cfg):
    """`(extraction entry, check entry, extraction, check)`: the entries the config sets for the two kinds of work, and the model and prompt
    version of each now. Both are found before anything is sent."""
    extraction_entry, check_entry = models.choose(cfg, "theme")[0], models.choose(cfg, "theme-check")[0]
    entries = models.registry(cfg)
    return (extraction_entry, check_entry,
            {"model": entries[extraction_entry]["model"], "prompt_version": themeextract.THEME_JOB.prompt_version},
            {"model": entries[check_entry]["model"], "prompt_version": themecheck.check_job(1).prompt_version})


def plan(store, cfg, book_ids=None, again=False):
    """Plan a run: write the record and return a summary (the run's name, the books to make with their pieces, the books left out with the
    reason, those skipped whose check is another or not known, the pieces, the calls that can be counted, the models and prompt versions,
    and the estimate). Makes no call. A book that is not there, or a model that is not set, is a refusal and nothing is written."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    extraction_entry, check_entry, extraction, check = _current(cfg)
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
            _, version_id, pieces, ref = outcome
            to_make.append({"book_id": book_id, "title": title, "pieces": pieces})
            items.append({"book_id": book_id, "version_id": version_id, "pieces": pieces, "status": "waiting", "attempts": 0, "generation": None,
                          "reason": "", "made": None, "conversion": dict(ref), "stats": None})
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


def _category(reason):
    """The kind of a reason for which a theme was dropped, from the words the extraction and the check use: one of DROP_KINDS."""
    if reason.startswith("skipped"):
        return "proof_or_definition"
    if reason.startswith("merged"):
        return "merged_near_identical"
    if reason.startswith("unchecked"):
        return "unchecked"
    if "no usable title" in reason or "has no summary" in reason:
        return "unusable_field"
    if "characters, more than" in reason:
        return "span_over_limit"
    if "not numbers" in reason:
        return "pointer_not_numbers"
    if "not in the piece" in reason:
        return "pointer_not_in_piece"
    return "other"


def _how_made(got, rec):
    """The model and prompt version of the extraction and of the check, from the records of the calls. A check that made no call (the book had no
    theme to check) names the check that was set for the run."""
    def first(task, fallback):
        for r in got["records"]:
            if r.get("task") == task:
                how = {"model": r.get("model"), "prompt_version": r.get("prompt_version")}
                return how if _how(how) else fallback
        return fallback
    return {"theme": first("theme", rec["extraction"]), "theme-check": first("theme-check", rec["check"])}


def _stats_of(got, seconds):
    themes = got["generation"]["themes"]
    marks = Counter(p["mark"] for t in themes for p in t["neutral"].values() if p["mark"])
    return {"themes": len(themes), "dropped": dict(Counter(_category(d["reason"]) for d in got["dropped"])),
            "flags": dict(Counter(f["kind"] for t in themes for f in t["flags"])), "stated": marks["stated"], "inferred": marks["inferred"],
            "pieces": got["pieces"], "calls": got["calls"], "input_tokens": sum(r.get("input_tokens") or 0 for r in got["records"]),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in got["records"]), "seconds": int(seconds)}


def _counts(rec):
    counts = {s: 0 for s in STATUSES}
    for i in rec["items"]:
        counts[i["status"]] += 1
    return counts


def _items(rec):
    return [{k: i[k] for k in ("book_id", "version_id", "pieces", "status", "generation", "reason", "attempts", "made", "stats")} for i in rec["items"]]


def _forget(index_root, book_id, version_id):
    """Remove the journal of the pieces of a book, if it has one. A journal that cannot be removed is left: it is derived data, and a later go
    finds it stale or uses it only for the same pieces."""
    try:
        themejournal.remove(index_root, book_id, version_id)
    except (KbError, OSError):
        pass


def _kept(index_root, item):
    """How many pieces of a book that is not done are in its journal (0 if there is none or it cannot be read), or None for a book that is
    done or dropped."""
    if item["status"] not in ("waiting", "failed"):
        return None
    try:
        return len(themejournal.read(index_root, item["book_id"], item["version_id"]) or [])
    except KbError:
        return 0


def _serve(store, cfg, rec, item, frequencies, launcher, root):
    """Make, check and file the themes of one book, and say what became of it in the item. Returns "done", "dropped", "refused", "failed" or
    "unexpected". A reason is a fixed kind (`REASON_KINDS`) or the name of the kind of an unexpected error, never a message."""
    def fail(kind, reason):
        item["attempts"] += 1
        item["reason"] = reason
        item["status"] = "waiting" if item["attempts"] <= RETRIES else "failed"
        return kind

    def drop(reason):
        item["status"], item["reason"] = "dropped", reason
        _forget(index_root, book_id, version_id)   # a book that is dropped is not made from its pieces later
        return "dropped"
    index_root = store.cfg["index_root"]
    book_id, version_id = item["book_id"], item["version_id"]
    try:
        book = store.read_book(book_id)
        if book.get("state") != "active" or book.get("current_version") != version_id:
            return drop("no_longer_active")
        loaded = convert.load_in_use(store, book_id, version_id)
        if not loaded or loaded[0] != item["conversion"]:
            return drop("conversion_changed")
        started = time.monotonic()
        # the pieces already answered, from a go that failed or was stopped, are not asked for again; a book that fails keeps them
        journal = themeextract.PieceJournal.for_book(index_root, book_id, version_id)
        got = themecheck.make_and_check_for_version(store, cfg, book_id, version_id, launcher=launcher, root=root, frequencies=frequencies,
                                                    journal=journal)
        made, stats = _how_made(got, rec), _stats_of(got, time.monotonic() - started)
        done = {"status": "done", "generation": 1, "reason": "", "made": made, "stats": stats}
        _check_item({**item, **done})   # what the record will say is checked before anything is filed, so that a book is not filed and then failed
        done["generation"] = theme.file(store, got["generation"])
        item.update(done)
        _forget(index_root, book_id, version_id)   # the pieces are in the generation now
        return "done"
    except themeextract.ThemeRefused:
        return fail("refused", "refused")
    except KbError:
        return fail("failed", "failed")
    except Exception as e:   # whatever one book's data does to the program, the other books go on; only the kind of error is shown
        return fail("unexpected", f"an unexpected error ({type(e).__name__})")


def _totals(rec):
    """The sums of the stats of the books that are done. A book that failed or was dropped has no stats, so its time and tokens are not here."""
    done = [i["stats"] for i in rec["items"] if i["status"] == "done" and i["stats"]]
    out = {k: sum(s[k] for s in done) for k in ("themes", "stated", "inferred", "pieces", "calls", "input_tokens", "output_tokens", "seconds")}
    out["books"] = len(done)
    out["dropped"] = dict(sum((Counter(s["dropped"]) for s in done), Counter()))
    out["flags"] = dict(sum((Counter(s["flags"]) for s in done), Counter()))
    return out


def _report(rec, passes, stopped, elapsed=None):
    out = {"run": rec["run"], "created": rec["created"], "again": rec["again"], "extraction": rec["extraction"], "check": rec["check"],
           "passes": passes, "stopped": stopped, "counts": _counts(rec), "totals": _totals(rec), "items": _items(rec)}
    if elapsed is not None:
        out["elapsed_seconds"] = elapsed   # the wall time of this call (the seconds of the books are the time of their calls)
    return out


def run(store, cfg, run_id, launcher=None, root=None):
    """Run a planned run: each book that waits is made, checked and filed as a new generation of themes as soon as it is made, and what became
    of it is saved in the record. A book that fails does not end the run; the books that failed are tried once more after the last (RETRIES);
    STOP_AFTER books in a row that fail for a reason that is not a refused answer stop it (a server that is down would fail every book), and
    the books not yet tried stay waiting. A book that is no longer active, or whose conversion changed since the plan, is dropped and
    reported. A run that is stopped at any point and run again repeats no finished book. One window is accepted: a book whose generation was
    filed and whose record was not yet saved when the program was killed is made again, as a new generation (the newest valid generation is the
    one a reader gets, so the extra one is harmless, and at most one book is made twice). Returns the report; the models and prompt versions
    must be those of the plan."""
    index_root = store.cfg["index_root"]
    _, _, extraction, check = _current(cfg)
    if read_record(index_root, run_id) is None:
        raise KbError("there is no run with that name; make one with `themes-run plan`")
    stopped, in_a_row, passes, frequencies, began = None, 0, 0, None, time.time()
    with cardstate.lock(index_root, run_id):
        rec = read_record(index_root, run_id)
        if rec["extraction"] != extraction or rec["check"] != check:   # the record that is run, read under the lock
            raise KbError("the models or the prompts of the config are not those of the plan: plan again")
        while passes <= RETRIES and stopped is None and any(i["status"] == "waiting" for i in rec["items"]):
            passes += 1
            for item in rec["items"]:
                if item["status"] != "waiting":
                    continue
                if frequencies is None:
                    frequencies = themecheck.library_frequencies(store)   # the library is counted once for the whole run
                outcome = _serve(store, cfg, rec, item, frequencies, launcher, root)
                write_record(index_root, rec)
                if outcome in ("failed", "unexpected"):
                    in_a_row += 1
                    if in_a_row >= STOP_AFTER:
                        stopped = f"{STOP_AFTER} books in a row failed for a reason that is not a refused answer: the run is stopped; run it again when the cause is gone"
                        break
                elif outcome in ("done", "refused"):
                    in_a_row = 0
    return _report(rec, passes, stopped, int(time.time() - began))


def status(store, run_id):
    """Where each book of a run has got to, with no text of any book."""
    rec = read_record(store.cfg["index_root"], run_id)
    if rec is None:
        raise KbError("there is no run with that name")
    items = _items(rec)
    for each in items:   # the pieces of a book that is not done which are kept, so that the piece a book fails at is known
        each["kept"] = _kept(store.cfg["index_root"], each)
    return {"run": rec["run"], "created": rec["created"], "again": rec["again"], "extraction": rec["extraction"], "check": rec["check"],
            "counts": _counts(rec), "totals": _totals(rec), "items": items, "pieces": sum(i["pieces"] for i in items),
            "pieces_done": sum(i["pieces"] for i in items if i["status"] == "done")}
