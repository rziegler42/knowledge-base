"""The list of moves that the owner is asked to approve (`docs/specs/shelf.md`, "Reshelving"; the plan `2026-11-16-move-confirmed-books-onto-their-shelves`, Increment A).

`place-propose` and `place-review` leave a proposal and the owner's answer in each book's own event log (`placement`, `placereview`); none of that moves a book. This module makes the list of the books
that the owner's answers would move, from the books' root files, cards and event logs, and the text that shows the list to the owner with a digest of that exact text. **It is read only: it opens
no file for writing, takes no lock and sends nothing to a model.** The move itself is a later increment, and this module does not make it.

**A list is made of records, and a record is not an approval.** A `placement_confirmed` line is what was typed in a terminal, or what anything able to write the library as the owner appended; the
list takes it as a reason to *propose* a move and checks it against the proposal it answers (the same card and schema, and a shelf among the five that the proposal offered). The owner's approval is a
separate act: reading the text that `preview` returns and handing its digest back to the command that moves the books, which refuses a digest that is not the one of the list as it stands then.

Every text in the preview is untrusted (a title and an address came from a web page, a reason is model output) and is cleaned as `place-review` cleans what it shows, so that no line of it can be mistaken
for the digest line or move the owner's terminal. The digest is the first 32 hexadecimal characters of the SHA-256 of the whole text above its own line, so what the owner reads is what is bound."""
import hashlib

from . import KbError, card, placereview, shelfvectors
from .store import _SHELF as STORE_SHELF  # the stores's own rule for a shelf name: a move the store would refuse is not listed

FORMAT = 1
DEFAULT_SCHEMA = shelfvectors.DEFAULT_SCHEMA
FROM = "default"
LIMIT = 1000  # the longest line that the preview takes from any one field

# why a book is not on the list, in the order they are checked and printed
REASONS = (
    ("root_unreadable", "the book's root file cannot be read"),
    ("not_active", "the book is not active"),
    ("not_on_default", "the book is not on the shelf default"),
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
)
_STATE_REASON = {"unreadable": "unreadable", "no_proposal": "failed", "stale": "stale", "unconfirmed": "unconfirmed"}


def _judge(store, book_id, schema, schema_hash):
    """`(reason, None)` for a book that is not listed, or `(None, item)` for one that is."""
    try:
        root = store.read_book(book_id)
    except KbError:
        return "root_unreadable", None
    if root.get("state") != "active":
        return "not_active", None
    if root.get("shelf") != FROM:
        return "not_on_default", None
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
    if to not in schema.home:
        return "not_home", None
    if to not in proposal["order"]:
        return "not_offered", None
    if not STORE_SHELF.fullmatch(to):
        return "name_refused", None
    try:
        _, made = card.read(store, book_id, proposal["version"], proposal["generation"])
    except KbError:  # the card the proposal was made for cannot be read: it is not the card that is there
        return "stale", None
    safe = placereview.safe
    chosen = proposal["answer"]["chosen"] if proposal["answer"]["kind"] == "shelf" else None
    return None, {
        "book": book_id, "title": safe(made.get("title", ""), 300), "address": placereview._address(made), "from": root["shelf"],
        "to": to, "to_name": safe(schema.by_slug[to]["name"], 200), "to_path": placereview._path(schema, to), "to_scope": safe(schema.by_slug[to]["scope"], placereview.SHOWN_SCOPE),
        "equals_pick": to == chosen, "pick": chosen, "pick_name": safe(schema.by_slug[chosen]["name"], 200) if chosen else None,
        "reason": safe(proposal["answer"].get("reason") or "", placereview.SHOWN_REASON),
        "version": proposal["version"], "generation": proposal["generation"], "proposal_at": proposal["at"], "confirmation_at": answer["at"],
    }


def plan(store, schema_path=None):
    """`(items, left, schema_hash)`: the books that would move, in the order of their ids, the counts of the books that would not by reason (every reason is a key), and the hash of the schema file the list
    was made against. Nothing is written."""
    schema, schema_hash = shelfvectors._read_schema(schema_path or DEFAULT_SCHEMA)
    items, left = [], {key: 0 for key, _ in REASONS}
    for book_id in sorted(store.list_books()):
        reason, item = _judge(store, book_id, schema, schema_hash)
        if reason is None:
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
        lines.append("%d book%s would move:" % (len(items), "" if len(items) == 1 else "s"))
    for number, item in enumerate(items, 1):
        pick = "%s (%s)" % (_clean(item["pick"]), _clean(item["pick_name"])) if item["pick"] else "none"
        lines += [
            "",
            "[%d of %d] book %s" % (number, len(items), _clean(item["book"])),
            "title: %s" % _clean(item["title"]),
            "address: %s" % _clean(item["address"]),
            "from: %s" % _clean(item["from"]),
            "to: %s (%s)" % (_clean(item["to"]), _clean(item["to_name"])),
            "path: %s" % _clean(item["to_path"]),
            "scope: %s" % _clean(item["to_scope"]),
            "the model's pick: %s" % pick,
            "the owner's answer: %s" % ("the model's pick" if item["equals_pick"] is True else "another of the five shelves"),
            "the model's reason: %s" % _clean(item["reason"]),
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
