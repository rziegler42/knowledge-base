"""The list of moves that the owner is asked to approve (`docs/specs/shelf.md`, "Reshelving"; the plan `2026-11-16-move-confirmed-books-onto-their-shelves`, Increment A).

`place-propose` and `place-review` leave a proposal and the owner's answer in each book's own event log (`placement`, `placereview`); none of that moves a book. This module makes the list of the books
that the owner's answers would move, from the books' root files, cards and event logs, and the text that shows the list to the owner with a digest of that exact text (`plan`, `render`, `preview`:
**these are read only: they open no file for writing, take no lock and send nothing to a model**), and, given that digest, makes the moves (`apply`).

**`apply` is the step the owner runs in their own terminal, and it is the only thing in this module that writes.** It refuses unless its input and its output are a terminal (an interlock, not proof of a
person: a program that holds a pseudo-terminal passes it), unless the store is open for writing and unless the digest has the shape of one; it then holds the catalog lock, makes the list again and refuses
if its digest is not the one given, so a list that changed after the owner read it is not applied. For each book, in the order of the list, it reads the root file again, refuses the book if it is not
what the list was made from, changes the `shelf` field with the store's own `set_shelf`, reads it back, and appends one `reshelved` line to the book's event log. A stop between those two writes leaves
the book on its shelf with no line; the next list offers it to record (`action: record only`) and the next `apply` writes the line and touches no root file. It stops at the first error and says which books
moved. **The lock is the catalog's, which the index and vector writers take; the writers of a root file take none, so another process that rewrites the same root file in the same instant could still lose a
write, and the owner is asked to run nothing else against the library meanwhile.**

**A list is made of records, and a record is not an approval.** A `placement_confirmed` line is what was typed in a terminal, or what anything able to write the library as the owner appended; the
list takes it as a reason to *propose* a move and checks it against the proposal it answers (the same card and schema, and a shelf among the five that the proposal offered). The owner's approval is a
separate act: reading the text that `preview` returns and handing its digest back to the command that moves the books, which refuses a digest that is not the one of the list as it stands then.

Every text in the preview is untrusted (a title and an address came from a web page, a reason is model output) and is cleaned as `place-review` cleans what it shows, so that no line of it can be mistaken
for the digest line or move the owner's terminal. The digest is the first 32 hexadecimal characters of the SHA-256 of the whole text above its own line, so what the owner reads is what is bound."""
import hashlib
import os
import re
import stat
import sys

from . import KbError, card, catalog, placement, placereview, shelfvectors
from .store import _SHELF as STORE_SHELF  # the stores's own rule for a shelf name: a move the store would refuse is not listed

FORMAT = 2
EVENT = "reshelved"
_DIGEST = re.compile(r"[0-9a-f]{32}")
_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00", re.ASCII)  # the shape of the time the store writes into a line; the digest binds what is shown, so what is written must be what is shown
DEFAULT_SCHEMA = shelfvectors.DEFAULT_SCHEMA
FROM = "default"
LIMIT = 1000  # the longest line that the preview takes from any one field

# why a book is not on the list, in the order they are checked and printed
REASONS = (
    ("root_unreadable", "the book's root file cannot be read"),
    ("not_active", "the book is not active"),
    ("not_on_default", "the book is not on the shelf default"),
    ("moved_before", "the book was moved by this command before and is on the shelf default again"),
    ("unrecordable", "the book is on the shelf its answer named, no line records the move, and its event log cannot take one (the log needs repair by hand)"),
    ("no_proposal", "the book has no proposal"),
    ("unreadable", "its event log or its newest proposal cannot be read"),
    ("failed", "the model call for its proposal failed"),
    ("stale", "its proposal is out of date (its card or the schema changed)"),
    ("unconfirmed", "the owner has not answered its proposal"),
    ("none", "the owner answered none"),
    ("skipped", "the owner skipped it"),
    ("not_home", "the answered shelf is not a home shelf of the schema"),
    ("not_offered", "the answered shelf is not one of the five the proposal offered"),
    ("name_refused", "the store would refuse the shelf's name"),
    ("log_unusable", "its event log cannot safely take another line (it does not end in a newline, is read only or not a plain file, or holds two proposals made in the same second)"),
)
_STATE_REASON = {"unreadable": "unreadable", "no_proposal": "failed", "stale": "stale", "unconfirmed": "unconfirmed", "moved": "not_on_default"}  # `moved`: another process moved the book after the root file was read


def _log_unusable(store, book_id):
    """True if the book's event log cannot safely take another line: it is not a plain file, it is not writable, it does not end in a newline (a line appended to it would be glued onto the last one and the
    whole log would stop reading), it cannot be read, it is shared with another book, or the newest proposal has the same time as an older one (an answer names its proposal by that time, so it could not
    tell them apart)."""
    path = store.events_file(book_id)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return not os.access(os.path.dirname(path), os.W_OK)
    except OSError:
        return True
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not os.access(path, os.W_OK):  # a log shared with another book (a hard link) is not this book's log
        return True
    if info.st_size:
        try:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    return True
        except OSError:
            return True
    try:
        events = store.read_events(book_id)
    except KbError:
        return True
    times = [str(e.get("at")) for e in events if isinstance(e, dict) and e.get("event") == placement.EVENT]
    return len(times) > 1 and times[-1] in times[:-1]   # an answer names the newest proposal by its time: another proposal with that time makes it ambiguous


def _moved_before(store, book_id, confirmation_at):
    try:
        events = store.read_events(book_id)
    except KbError:
        return False
    return any(isinstance(e, dict) and e.get("event") == EVENT and e.get("confirmation") == confirmation_at for e in events)


def _at_ok(value):
    return type(value) is str and _AT.fullmatch(value) is not None


def _item(store, book_id, root, proposal, answer, to, schema, action):
    """The item of a listed book, or None if the card the proposal was made for cannot be read."""
    try:
        _, made = card.read(store, book_id, proposal["version"], proposal["generation"])
    except KbError:  # the card the proposal was made for cannot be read: it is not the card that is there
        return None
    safe = placereview.safe
    chosen = proposal["answer"]["chosen"] if proposal["answer"]["kind"] == "shelf" else None
    return {
        "book": book_id, "action": action, "title": safe(made.get("title", ""), 300), "address": placereview._address(made), "from": FROM if action == "move" else None,
        "to": to, "to_name": safe(schema.by_slug[to]["name"], 200), "to_path": placereview._path(schema, to), "to_scope": safe(schema.by_slug[to]["scope"], placereview.SHOWN_SCOPE),
        "equals_pick": to == chosen, "pick": chosen, "pick_name": safe(schema.by_slug[chosen]["name"], 200) if chosen else None,
        "reason": safe(proposal["answer"].get("reason") or "", placereview.SHOWN_REASON),
        "current_version": root.get("current_version"), "version": proposal["version"], "generation": proposal["generation"],
        "proposal_at": proposal["at"], "confirmation_at": answer["at"], "typed": safe(answer.get("answer") or "", 100),
    }


def _to_record(store, book_id, root, schema, schema_hash):
    """`(item, blocked)` for a book that is already on the shelf its answer named but has no `reshelved` line for that answer (a stop between the two writes of a move), where `blocked` says that its
    event log cannot take the line; or None if it is not such a book."""
    try:
        events = store.read_events(book_id)
    except KbError:
        return None
    proposals = [e for e in events if isinstance(e, dict) and e.get("event") == placement.EVENT]
    if not proposals or not placereview._proposal_ok(proposals[-1], schema) or proposals[-1]["schema_sha256"] != schema_hash:
        return None
    proposal = proposals[-1]
    answered = [e for e in events if isinstance(e, dict) and e.get("event") == placereview.EVENT and placereview._confirmation_ok(e, schema) and e["proposal"] == proposal["at"]]
    if not answered:
        return None
    answer, to = answered[-1], root.get("shelf")
    result = answer["result"]
    if result["kind"] != "shelf" or result["shelf"] != to or to not in schema.home or to not in proposal["order"] or not STORE_SHELF.fullmatch(to):
        return None
    if not (_at_ok(proposal["at"]) and _at_ok(answer.get("at"))):
        return None
    if any(isinstance(e, dict) and e.get("event") == EVENT and e.get("confirmation") == answer["at"] and e.get("to") == to for e in events):
        return None
    item = _item(store, book_id, root, proposal, answer, to, schema, "record")
    return None if item is None else (item, _log_unusable(store, book_id))


def _judge(store, book_id, schema, schema_hash):
    """`(reason, None)` for a book that is not listed, or `(None, item)` for one that is. A book that is on another shelf than `default` is listed only to record a move that was made and not recorded: `(reason, item)`
    with both, where the item is None unless there is one to record."""
    try:
        root = store.read_book(book_id)
    except KbError:
        return "root_unreadable", None
    if root.get("state") != "active":
        return "not_active", None
    if root.get("shelf") != FROM:
        found = _to_record(store, book_id, root, schema, schema_hash)
        if found is None:
            return "not_on_default", None
        item, blocked = found
        return ("unrecordable", None) if blocked else ("not_on_default", item)
    found = placereview.state_of(store, book_id, schema, schema_hash)
    if found is None:
        return "no_proposal", None
    state, proposal, answer = found
    if state != "confirmed":
        return _STATE_REASON[state], None
    result = answer["result"]
    if result["kind"] in ("none", "skipped"):
        return ("none" if result["kind"] == "none" else "skipped"), None
    to = result["shelf"]
    if to not in schema.home or to == FROM:
        return "not_home", None
    if to not in proposal["order"]:
        return "not_offered", None
    if not STORE_SHELF.fullmatch(to):
        return "name_refused", None
    if not (_at_ok(proposal["at"]) and _at_ok(answer.get("at"))):  # a time that is not a time was not written by this engine, and would be shown cut or cleaned and written whole
        return "unreadable", None
    if _moved_before(store, book_id, answer["at"]):
        return "moved_before", None
    if _log_unusable(store, book_id):
        return "log_unusable", None
    item = _item(store, book_id, root, proposal, answer, to, schema, "move")
    return ("stale", None) if item is None else (None, item)


def plan(store, schema_path=None):
    """`(items, left, schema_hash)`: the books that would move, in the order of their ids, the counts of the books that would not by reason (every reason is a key), and the hash of the schema file the list
    was made against. Nothing is written."""
    schema, schema_hash = shelfvectors._read_schema(schema_path or DEFAULT_SCHEMA)
    items, left = [], {key: 0 for key, _ in REASONS}
    for book_id in sorted(store.list_books()):
        reason, item = _judge(store, book_id, schema, schema_hash)
        if item is not None:
            items.append(item)
        else:
            left[reason] += 1
    return items, left, schema_hash


def _clean(value):
    return placereview.safe(value, LIMIT)


def render(items, left, schema_hash):
    """The text that the owner reads, without its digest line. Every field of every item and every count is in it, so a change to any of them changes the digest."""
    lines = ["place-apply preview, format %d" % FORMAT, "schema file sha256: %s" % _clean(schema_hash)]
    if not items:
        lines.append("No book would move.")
    else:
        recording = sum(1 for i in items if i["action"] != "move")
        lines.append("%d book%s to move%s:" % (len(items) - recording, "" if len(items) - recording == 1 else "s", ", %d to record only" % recording if recording else ""))
    for number, item in enumerate(items, 1):
        pick = "%s (%s)" % (_clean(item["pick"]), _clean(item["pick_name"])) if item["pick"] else "none"
        lines += [
            "",
            "[%d of %d] book %s" % (number, len(items), _clean(item["book"])),
            "action: %s" % ("move" if item["action"] == "move" else "record only (the book is already on this shelf and no line says it was moved there; the line written will say that where it came from is not known)"),
            "title: %s" % _clean(item["title"]),
            "address: %s" % _clean(item["address"]),
            "from: %s" % ("not known" if item["from"] is None else _clean(item["from"])),
            "to: %s (%s)" % (_clean(item["to"]), _clean(item["to_name"])),
            "path: %s" % _clean(item["to_path"]),
            "scope: %s" % _clean(item["to_scope"]),
            "the model's pick: %s" % pick,
            "the owner's answer: %s" % ("the model's pick" if item["equals_pick"] is True else "another of the five shelves"),
            "typed answer: %s" % _clean(item["typed"]),
            "the model's reason: %s" % _clean(item["reason"]),
            "current version of the book: %s" % _clean(item["current_version"]),
            "card: generation %s of version %s" % (_clean(item["generation"]), _clean(item["version"])),
            "proposal made: %s" % _clean(item["proposal_at"]),
            "answer given: %s" % _clean(item["confirmation_at"]),
        ]
    lines += ["", "Left out: %d book%s" % (sum(left.values()), "" if sum(left.values()) == 1 else "s")]
    lines += ["  %d %s" % (left[key], words) for key, words in REASONS if left.get(key)]
    lines += ["", "Visibility: the engine has no shelf visibility yet, so no move changes one."]
    return "\n".join(lines)


def digest_of(text):
    """The first 32 hexadecimal characters of the SHA-256 of `text`."""
    if type(text) is not str:
        raise KbError("the text to take a digest of is a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def preview(store, schema_path=None):
    """`(text, digest, items, left)`: what the owner reads, ending with the line `digest: <digest>`, the digest, and the list and counts it was made from. Nothing is written."""
    items, left, schema_hash = plan(store, schema_path)
    body = render(items, left, schema_hash)
    digest = digest_of(body)
    return body + "\ndigest: " + digest, digest, items, left


def _move(store, item, digest, schema_hash):
    """Make one move, or record one that was made. The book is read again first: it must still be what the list was made from. Raises KbError and leaves the book as it was if not."""
    book, to, origin, action = item["book"], item["to"], item["from"], item["action"]
    if action not in ("move", "record") or type(to) is not str or not STORE_SHELF.fullmatch(to) or to == origin:
        raise KbError("the book %s is not to be moved to the shelf %r" % (book, to))
    if _log_unusable(store, book):
        raise KbError("the event log of the book %s cannot take another line" % book)
    root = store.read_book(book)
    if root.get("state") != "active":
        raise KbError("the book %s is no longer active" % book)
    if root.get("current_version") != item["current_version"]:
        raise KbError("the book %s has another current version than the list was made from" % book)
    if action == "move":
        if root.get("shelf") != origin:
            raise KbError("the book %s is no longer on the shelf %s" % (book, origin))
        store.set_shelf(book, to)
        if store.read_book(book).get("shelf") != to:
            raise KbError("the shelf of the book %s did not change" % book)
    elif root.get("shelf") != to:
        raise KbError("the book %s is no longer on the shelf %s" % (book, to))
    store.append_event(book, EVENT, **{"from": origin, "to": to, "action": action, "proposal": item["proposal_at"], "confirmation": item["confirmation_at"], "digest": digest,
                                       "schema_sha256": schema_hash, "via": "place-apply"})


def apply(store, digest, schema_path=None, is_tty=None, say=print):
    """Make the moves of the list whose digest is `digest`, or refuse. Returns `{"moved": [...], "recorded": [...], "digest": digest}`. See the top of this module for what is refused and what is written."""
    if type(digest) is not str or not _DIGEST.fullmatch(digest):
        raise KbError("the digest is the 32 lowercase hexadecimal characters on the last line of what `place-apply` prints")
    if is_tty is None:
        is_tty = lambda: sys.stdin.isatty() and sys.stdout.isatty()  # noqa: E731
    if not is_tty():
        raise KbError("place-apply with a digest moves books and takes its approval from a terminal; run it in your own terminal (`place-apply` with no digest prints the list and needs none)")
    if not getattr(store, "write", False):
        raise KbError("the store was opened read-only")
    with catalog.lock(store.cfg["index_root"]):
        items, left, schema_hash = plan(store, schema_path)
        if digest_of(render(items, left, schema_hash)) != digest:
            raise KbError("the list is not the one with that digest (it changed since you read it, or the digest is another's): run `place-apply` again, read the list and give its digest")
        moved, recorded = [], []
        for item in items:
            try:
                _move(store, item, digest, schema_hash)
            except Exception as e:  # whatever stops a move, the owner is told which books moved before it
                raise KbError("stopped at the book %s: %s; moved before it: %s; recorded before it: %s" % (
                    placereview.safe(item["book"], 40), placereview.safe(getattr(e, "strerror", None) or e, 300), ", ".join(moved) or "none", ", ".join(recorded) or "none")) from None
            (moved if item["action"] == "move" else recorded).append(item["book"])
            say("%s %s to the shelf %s" % ("moved" if item["action"] == "move" else "recorded the move of", placereview.safe(item["book"], 40), placereview.safe(item["to"], 100)))
        return {"moved": moved, "recorded": recorded, "digest": digest}
