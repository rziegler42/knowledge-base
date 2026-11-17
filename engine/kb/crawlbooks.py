"""The crawl's books: their events and readers (`docs/specs/population.md`, "Filing and placement"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment C).

A **crawl book** is a book the runner filed: `auto_filed` and with a `crawl_found` event (`candidate`, `source`, `found_from`, `topic`, `run`, `plan_digest`). Its state is what its events say, never what a run
remembers, so that every step can be run again. The other events of the crawl are `crawl_judged` (`score`, `shelf`, `ok`), `crawl_step_failed` (`step`, `reason`, `run`) and the **terminal** ones: `crawl_rejected` (`reason`,
`score`, `stage`), `crawl_held` (`kinds`), `crawl_unplaced` (`reason`) and `reshelved` (the move's, written elsewhere). A crawl book with none of the terminal events is unfinished work. A terminal event is written once:
the writers return `False` when the book already has one.

**A book is acted on only if its `crawl_found` carries the digest of an approved plan** (`approved_digests`: the stored approvals that read strictly). `crawl_books` lists the unfinished books of an approved digest, in the
order found; `unapproved_books` lists those with a missing, malformed or unapproved digest, and `reconcile_unapproved` is the one place they are dealt with: it writes `crawl_unplaced` once and one log line, and calls no
model, no move, no proposal and no capture. A book that is not `active` is not work. The owner's books (not `auto_filed`) are never read for these events, listed or touched.

`weed` writes `crawl_rejected` (which holds the reason and the stage) and sets the book's state to `weeded`; a death between the two is finished by `finish_weeds` or by a second call. `fail_step` records
a failed try of a step and, at the plan's `retries` such failures of one step, weeds the book (**parked**: weeded, terminal, never listed again). This module reads and writes the books' events and states and nothing else:
no request, no model, no environment variable."""
import re

from . import KbError, crawlapprove, crawlqueue, crawlstate, scan_tool, textutil

STAGES = ("capture", "scan", "convert", "index", "judge", "card", "propose", "move")
TERMINAL = ("crawl_rejected", "crawl_held", "reshelved", "crawl_unplaced")
HOLD_KINDS = frozenset(scan_tool.KINDS) | {"scan_failed", "scan_unavailable", "scan_timeout"}
REASON_MAX = 300
UNAPPROVED = "its plan digest is not an approved one"
_DIGEST = re.compile(r"[0-9a-f]{32}")
_RUN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_SHELF = re.compile(r"[A-Za-z0-9._-]{1,120}")
MAX_INT = 2**63 - 1


# ---- field checks

def _text(value, what, required=True, limit=REASON_MAX):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise KbError(f"the {what} is text")
    cleaned = textutil.clean(value, limit)
    if not cleaned:
        if required:
            raise KbError(f"the {what} is not empty")
        return None
    return cleaned


def _run(value):
    if not isinstance(value, str) or not _RUN.fullmatch(value):
        raise KbError("a run name is 1 to 64 letters, digits or . _ : -")
    return value


def _score(value, required=False):
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1 <= value <= 1:       # NaN and infinity are outside the range
        raise KbError("a score is a number from -1 to 1")
    return float(value)


def _stage(value):
    if value not in STAGES:
        raise KbError("a step is one of: " + ", ".join(STAGES))
    return value


def _retries(plan):
    value = plan.get("retries") if isinstance(plan, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KbError("the plan's retries is a whole number from 1")
    return value


def _names(events):
    return [e.get("event") for e in events if isinstance(e, dict)]


def _has_terminal(events):
    return any(name in TERMINAL for name in _names(events))


def _found(events):
    for event in events:
        if isinstance(event, dict) and event.get("event") == "crawl_found":
            return event
    return None


# ---- the writers

def record_found(store, book_id, *, candidate, source, found_from, topic, run, plan_digest):
    """The book was filed by the crawl, from this candidate, under the plan with this digest. A book is found once."""
    if isinstance(candidate, bool) or not isinstance(candidate, int) or not 1 <= candidate <= MAX_INT:
        raise KbError("a candidate is named by its row number")
    if source not in crawlqueue.SOURCES:
        raise KbError("a source is one of: " + ", ".join(crawlqueue.SOURCES))
    if not isinstance(plan_digest, str) or not _DIGEST.fullmatch(plan_digest):
        raise KbError("a plan digest is 32 lowercase hexadecimal characters")
    data = {"candidate": candidate, "source": source, "found_from": _text(found_from, "place it was found from", required=False), "topic": _text(topic, "topic", required=False),
            "run": _run(run), "plan_digest": plan_digest}
    if store.read_book(book_id).get("auto_filed") is not True:
        raise KbError("only a book filed by the crawl (auto_filed) can be found by it")
    if _found(store.read_events(book_id)) is not None:
        raise KbError("the book was found already")
    store.append_event(book_id, "crawl_found", **data)


def _crawl_events(store, book_id):
    """The events of a book the crawl filed (`auto_filed` and found), or `KbError`: no writer but `record_found` acts on any other book."""
    events = store.read_events(book_id)
    _require_found(store, book_id, events)
    return events


def _terminal(store, book_id, event, **data):
    if _has_terminal(_crawl_events(store, book_id)):
        return False
    store.append_event(book_id, event, **data)
    return True


def record_held(store, book_id, kinds):
    """The scan held the book: the kinds of finding (or `scan_failed`, `scan_unavailable`, `scan_timeout`). Terminal."""
    if not isinstance(kinds, list) or not kinds or len(set(map(str, kinds))) != len(kinds) or not all(isinstance(k, str) and k in HOLD_KINDS for k in kinds):
        raise KbError("the kinds that held a book are a list of known kinds, none twice")
    return _terminal(store, book_id, "crawl_held", kinds=list(kinds))


def record_rejected(store, book_id, reason, score, stage):
    """The book was judged out or parked, at this stage, with this reason and score (or none). Terminal; it does not change the book's state (`weed` does)."""
    return _terminal(store, book_id, "crawl_rejected", reason=_text(reason, "reason"), score=_score(score), stage=_stage(stage))


def record_unplaced(store, book_id, reason):
    """The book stays on the default shelf, with this reason. Terminal."""
    return _terminal(store, book_id, "crawl_unplaced", reason=_text(reason, "reason"))


def record_step_failed(store, book_id, step, reason, run):
    """One failed try of a step."""
    data = {"step": _stage(step), "reason": _text(reason, "reason"), "run": _run(run)}
    _crawl_events(store, book_id)
    store.append_event(book_id, "crawl_step_failed", **data)


def record_judged(store, book_id, score, shelf, ok):
    """The judgement's verdict, recorded once (`False` if the book has one already): the best match's score and shelf, and whether it was enough."""
    if not isinstance(ok, bool):
        raise KbError("a verdict is yes or no")
    shelf = None if shelf is None else shelf
    if shelf is not None and (not isinstance(shelf, str) or not _SHELF.fullmatch(shelf)):
        raise KbError("a shelf is named by letters, digits, . _ -")
    data = {"score": _score(score, required=True), "shelf": shelf, "ok": ok}
    if "crawl_judged" in _names(_crawl_events(store, book_id)):
        return False
    store.append_event(book_id, "crawl_judged", **data)
    return True


# ---- weeding and failed steps

def _require_found(store, book_id, events):
    """The book is one the crawl filed: it was `auto_filed` and has a `crawl_found` event. An owner's book, even with a forged event, is refused."""
    if _found(events) is None or store.read_book(book_id).get("auto_filed") is not True:
        raise KbError("the book is not one the crawl filed")


def weed(store, book_id, reason, score, stage):
    """Weed a crawl book: `crawl_rejected` is written (once) and its state becomes `weeded`. **The event goes first**, because it holds the reason and the stage: a death between the two writes leaves an active book
    with a rejection, which `finish_weeds` (or a second call of this) finishes from what is written. A book whose state is not `active` (removed, a duplicate) keeps it. Returns `False` if there was nothing to do
    (the book is final already). A book the crawl did not file is refused."""
    events = store.read_events(book_id)
    _require_found(store, book_id, events)
    if any(name in TERMINAL and name != "crawl_rejected" for name in _names(events)):
        return False
    wrote = False
    if "crawl_rejected" not in _names(events):
        record_rejected(store, book_id, reason, score, stage)
        wrote = True
    if store.read_book(book_id)["state"] == "active":
        store.set_state(book_id, "weeded")
        wrote = True
    return wrote


def step_failures(store, book_id, step):
    """How many times this step failed for this book."""
    step = _stage(step)
    return sum(1 for e in store.read_events(book_id) if isinstance(e, dict) and e.get("event") == "crawl_step_failed" and e.get("step") == step)


def fail_step(store, plan, book_id, step, reason, run):
    """Record a failed try of `step`. At the plan's `retries` such failures the book is parked (weeded, terminal). Returns `"retry"`, `"parked"` or, for a book that is final already, `"finished"`
    (nothing is written for it)."""
    retries = _retries(plan)
    step = _stage(step)
    events = store.read_events(book_id)
    _require_found(store, book_id, events)
    if _has_terminal(events):
        return "parked" if "crawl_rejected" in _names(events) else "finished"
    failed = step_failures(store, book_id, step) + 1
    if failed >= retries:                          # the failure that reaches the limit parks the book first and is recorded after, so a death between them costs no extra try
        weed(store, book_id, f"failed {failed} times: {_text(reason, 'reason')}", None, step)
        record_step_failed(store, book_id, step, reason, run)
        return "parked"
    record_step_failed(store, book_id, step, reason, run)
    return "retry"


# ---- the readers

class Scan:
    """What one pass over the library found: `entries`, the crawl books (`auto_filed` and with a `crawl_found` event) as `{"id", "found", "events", "state"}` in the order found, and `unreadable`, the books
    whose event log could not be read (they are skipped, not an error), and `orphans`, the active `auto_filed` books with no `crawl_found` (a run died between filing a book and writing its event: the fetch step adopts
    them, and they count toward the filed total in the meantime)."""

    def __init__(self, entries, unreadable, orphans=()):
        self.entries, self.unreadable, self.orphans = entries, unreadable, list(orphans)


def scan_crawl_books(store):
    """One pass over the library, reading the events of the books the runner could have filed (`auto_filed`); the owner's own books are not read for them."""
    entries, unreadable, orphans = [], [], []
    for book_id in store.list_books():
        try:
            root = store.read_book(book_id)
            if root.get("auto_filed") is not True:
                continue
            events = store.read_events(book_id)
        except KbError:
            unreadable.append(book_id)
            continue
        found = _found(events)
        if found is not None:
            entries.append({"id": book_id, "found": found, "events": events, "state": root.get("state")})
        elif root.get("state") == "active":
            orphans.append(book_id)
    entries.sort(key=lambda e: (str(e["found"].get("at")), e["id"]))
    return Scan(entries, unreadable, orphans)


def _approved(found, approved):
    digest = found.get("plan_digest")
    return isinstance(digest, str) and digest in approved           # `approved` holds only digests that read strictly


def _work(scan, approved, want):
    return [e["id"] for e in scan.entries if e["state"] == "active" and not _has_terminal(e["events"]) and _approved(e["found"], approved) == want]


def approved_digests(index_root):
    """The digests of the stored approvals that read strictly (a link, a loose mode, an extra or missing file or a changed byte leaves one out)."""
    return crawlapprove.stored_digests(index_root)


def crawl_books(store, approved, scan=None):
    """The unfinished crawl books found under an approved plan, in the order found."""
    return _work(scan or scan_crawl_books(store), approved, True)


def unapproved_books(store, approved, scan=None):
    """The unfinished crawl books whose `crawl_found` has a missing, malformed or unapproved digest: nothing acts on them but `reconcile_unapproved`."""
    return _work(scan or scan_crawl_books(store), approved, False)


def filed_events(store, scan=None):
    """`{book id: events}` for every book with a `crawl_found` event, which is what `crawlstate.filed_total` counts."""
    return {e["id"]: e["events"] for e in (scan or scan_crawl_books(store)).entries}


def filed_count(store, scan=None):
    """The number of books the crawl has filed (`filed_total`'s ceiling counts them). A book of the crawl whose event log cannot be read counts too, and so does an active orphan (filed, its event not yet written): a
    ceiling is never undercounted."""
    scan = scan or scan_crawl_books(store)
    return crawlstate.filed_total(filed_events(store, scan)) + len(scan.unreadable) + len(scan.orphans)


def finish_weeds(store, scan=None):
    """Finish the weeds that died half way: a crawl book with `crawl_rejected` whose state is still `active` becomes `weeded`. Returns the book ids."""
    done = []
    for entry in (scan or scan_crawl_books(store)).entries:
        if entry["state"] == "active" and "crawl_rejected" in _names(entry["events"]):
            store.set_state(entry["id"], "weeded")
            done.append(entry["id"])
    return done


def reconcile_unapproved(store, approved, log, scan=None):
    """Deal with the books of an unapproved plan: write `crawl_unplaced` once to each, and one log line (step `move`, outcome `refused`). They are not proposed, moved, carded or fetched. Returns the book ids dealt with."""
    done = []
    for book_id in unapproved_books(store, approved, scan):
        if record_unplaced(store, book_id, UNAPPROVED):
            log.write("move", "refused", book=book_id, reason=UNAPPROVED)
            done.append(book_id)
    return done
