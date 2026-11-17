"""The owner's confirmation of a proposed shelf (`docs/specs/shelf.md`, "Placement when more than one shelf fits"; the plan `2026-11-15-propose-a-shelf-for-each-book`, Increment C).

`place-propose` (`placement`) writes a proposal into a book's own event log; this module shows the proposals to the owner one book at a time, in the owner's own terminal, and records each answer as
one line of the book's event log (`placement_confirmed`). **A confirmation is a record, not filing:** it changes no book's shelf, card or file; moving books onto shelves is a later plan with its own
governed steps.

The owner answers a book with `1` to `5` (that shelf), `ok` (the model's pick, or its `none`), `none` (no shelf fits), `skip <words>` (cannot judge it; the words are kept) or `quit`; anything
else is asked again and never guessed at. The model's pick is shown with its reason, because the owner is confirming a proposal; the earlier checks were blind because they measured. The event records
whether the answer equals the pick, so that a count of confirmations is read for what it is and not as a measure of accuracy.

**Only a person answers, as far as a command line can make sure.** The dialogue refuses to run unless its input is a terminal, and takes no answer from an argument, a file or the environment. That
stops a mistake, and it stops an agent that is run with a pipe, a file or a here-document. It is an interlock of the command line and **not proof that a person typed**: a program that holds a
pseudo-terminal satisfies it (shown by an experiment of the plan); a process that shares the owner's terminal can type into it; and anything that can write the library as the owner can append a
`placement_confirmed` line to a book's event log directly, without this command, and the reader will count it. **A `placement_confirmed` event is therefore a record of what was typed, not authority.**
A later step that files books must not rest on it alone: it must ask the owner again, in a terminal, by a governed action that shows what it will do and carries a digest of it.

Every text that is shown (a title, an address, a summary, a shelf's name and scope sentence, the model's reason) is untrusted: a book's text came from a web page or a paper, and the reason is model output.
It is cleaned of control, format and line characters (an escape sequence loses its escape character), of invisible characters and of long runs of combining marks, and cut, before it is printed. The events
that are read back are data too: a proposal that is not the shape `placement` writes (five different shelves of the schema, a chosen shelf among them, a number that matches) is counted as unreadable and not shown."""
import re
import sys

from . import KbError, card, placement, shelfvectors, textutil
from .store import _SHELF

EVENT = "placement_confirmed"
MAX_WORDS = 300
SHOWN_SUMMARY = 1500  # the whole summary the card can hold: the owner sees all the text the model saw
SHOWN_REASON = 300
SHOWN_SCOPE = 400
_HEX = re.compile(r"[0-9a-f]{64}")
_ANSWER_SKIP = re.compile(r"skip\s+(\S.*)")
QUESTION = "Which shelf? 1-5 for that shelf, ok for the model's pick, none if no shelf fits, skip <words> if you cannot judge it, quit to stop: "


def safe(value, limit):
    """A text made safe to print on the owner's terminal: the cleaning of the text rule, then every character that the engine's own cleaning (`textutil`) hides as well, and cut. The input is cut
    first to a few times the limit, so that a huge stored field costs little."""
    cleaned = placement.plain(str(value)[:limit * 4 + 100], limit * 4 + 100)
    kept = "".join(c for c in cleaned if not textutil._hidden(c))  # the engine's list of hidden characters is wider than the one the measured text rule uses
    return " ".join(kept.split())[:limit].rstrip()


def _is_text(value):
    return type(value) is str


def proposal_ok(event, schema):
    """True if a `placement_proposed` event has exactly the shape `placement.propose` writes, with the five shelves among the schema's."""
    try:
        answer = event["answer"]
        order = event["order"]
        if (type(event.get("generation")) is not int or event["generation"] < 1 or not _is_text(event.get("version")) or not _is_text(event.get("at"))
                or not _is_text(event.get("text_sha256")) or not _HEX.fullmatch(event["text_sha256"]) or not _is_text(event.get("schema_sha256")) or not _HEX.fullmatch(event["schema_sha256"])):
            return False
        if type(order) is not list or len(order) != placement.K or len(set(order)) != placement.K or any(not _is_text(s) or s not in schema.by_slug for s in order):
            return False
        near = event["candidates"]
        if (type(near) is not list or len(near) != placement.K or any(type(c) is not list or len(c) != 2 or not _is_text(c[0]) or type(c[1]) not in (int, float) for c in near)
                or {c[0] for c in near} != set(order)):
            return False
        if type(answer) is not dict or answer.get("kind") not in ("shelf", "none", "malformed", "error"):
            return False
        if answer["kind"] == "shelf":
            index = answer.get("index")
            if type(index) is not int or not 1 <= index <= placement.K or answer.get("chosen") != order[index - 1]:
                return False
        return True
    except (KeyError, TypeError):
        return False


_proposal_ok = proposal_ok  # the name it had while it was private; this module's own callers, `placeapply` and the tests still use it


def _confirmation_ok(event, schema):
    """True if a `placement_confirmed` event has exactly the shape `review` writes: a result that is a shelf of the schema, none, or skipped with the owner's words (1 to 300 characters)."""
    result = event.get("result")
    if type(result) is not dict or set(result) != {"kind", "shelf", "words"} or not _is_text(event.get("proposal")):
        return False
    kind, shelf, words = result["kind"], result["shelf"], result["words"]
    equals = event.get("equals_pick")
    if kind == "shelf":
        return _is_text(shelf) and shelf in schema.by_slug and words is None and type(equals) is bool
    if kind == "none":
        return shelf is None and words is None and type(equals) is bool
    if kind == "skipped":
        return shelf is None and _is_text(words) and 1 <= len(words) <= MAX_WORDS and bool(words.strip()) and equals is None
    return False


def state_of(store, book_id, schema, schema_hash):
    """`(state, proposal, confirmation)` of one book, or None if it has no proposal event at all. The state is `unreadable` (the newest proposal is not the shape this engine writes), `no_proposal` (it is
    an error), `moved` (the book is no longer on the shelf `default`: it has been moved onto a shelf, which `place-apply` does), `stale` (the card, the text or the schema is not the one the proposal was made
    for), `unconfirmed` or `confirmed` (the newest answer is to the newest proposal)."""
    try:
        events = store.read_events(book_id)
    except KbError:
        return "unreadable", None, None
    proposals = [e for e in events if isinstance(e, dict) and e.get("event") == placement.EVENT]
    if not proposals:
        return None
    proposal = proposals[-1]
    if not _proposal_ok(proposal, schema):
        return "unreadable", proposal, None
    try:
        shelf = store.read_book(book_id).get("shelf")
    except KbError:
        shelf = "default"  # a root file that cannot be read is not a move: the check of the card below says what is wrong
    if type(shelf) is str and shelf != "default" and _SHELF.fullmatch(shelf):  # a missing or odd value is not a move: it is not a shelf
        return "moved", proposal, None
    if proposal["answer"]["kind"] == "error":
        return "no_proposal", proposal, None
    try:
        items, _ = placement.select(store, book_ids=[book_id])
    except KbError:
        items = []
    if (len(items) != 1 or items[0]["generation"] != proposal["generation"] or items[0]["version"] != proposal["version"]
            or items[0]["text_sha256"] != proposal["text_sha256"] or proposal["schema_sha256"] != schema_hash):
        return "stale", proposal, None
    answered = [e for e in events if isinstance(e, dict) and e.get("event") == EVENT and _confirmation_ok(e, schema) and e["proposal"] == proposal["at"]]
    return ("confirmed", proposal, answered[-1]) if answered else ("unconfirmed", proposal, None)


def listing(store, schema_path=None):
    """The counts of where each book stands, read only: the books with a proposal event (`books`), those `unconfirmed` and `confirmed`, the confirmed by what the owner said (`accepted_pick`,
    `other_shelf`, `none`, `skipped`) and the books `moved`, `stale`, `no_proposal` (the model's call failed) and `unreadable`. A skipped book counts as `skipped` and not as `confirmed`."""
    schema, schema_hash = shelfvectors._read_schema(schema_path or shelfvectors.DEFAULT_SCHEMA)
    counts = {"books": 0, "unconfirmed": 0, "confirmed": 0, "accepted_pick": 0, "other_shelf": 0, "none": 0, "skipped": 0, "stale": 0, "no_proposal": 0, "unreadable": 0, "moved": 0}
    for book_id in store.list_books():
        found = state_of(store, book_id, schema, schema_hash)
        if found is None:
            continue
        state, proposal, answer = found
        counts["books"] += 1
        if state != "confirmed":
            counts[state] += 1
            continue
        kind = answer["result"]["kind"]
        if kind == "skipped":
            counts["skipped"] += 1
            continue
        counts["confirmed"] += 1
        if kind == "none":
            counts["none"] += 1
        else:
            counts["accepted_pick" if answer["equals_pick"] else "other_shelf"] += 1
    return counts


def _address(made):
    source = made.get("source") if isinstance(made.get("source"), dict) else {}
    for key in ("address_final", "address_asked"):
        if _is_text(source.get(key)) and source[key].strip():
            return safe(source[key], 300)
    ident = source.get("arxiv_id")
    return safe("https://arxiv.org/abs/" + ident, 300) if _is_text(ident) and re.fullmatch(r"[0-9A-Za-z./-]{1,40}", ident) else ""


def _path(schema, slug):
    ancestors = schema.ancestors.get(slug)
    by = schema.by_slug
    if ancestors is None:
        return "%s (a custom shelf, with no domain or field)" % safe(by[slug]["name"], 200)
    return " > ".join(safe(by[ancestors[level]]["name"], 200) for level in ("domain", "field", "subfield")) + " > " + safe(by[slug]["name"], 200)


def _show(say, store, book_id, proposal, schema, number, total):
    version = proposal["version"]
    _, made = card.read(store, book_id, version, proposal["generation"])
    model = made.get("model") if isinstance(made.get("model"), dict) else {}
    say("")
    say("=" * 70)
    say("Book %d of %d: %s" % (number, total, safe(made.get("title", ""), 300)))
    address = _address(made)
    if address:
        say(address)
    say(safe(model.get("summary", ""), SHOWN_SUMMARY))
    topics = [safe(t, 120) for t in model.get("topics", []) if _is_text(t)] if isinstance(model.get("topics"), list) else []
    topics = [t for t in topics if t]
    if topics:
        say("Topics: " + "; ".join(topics))
    say("Shelves, in the order the model saw them:")
    for n, slug in enumerate(proposal["order"], 1):
        say("  %d. %s | %s | %s" % (n, safe(schema.by_slug[slug]["name"], 200), _path(schema, slug), safe(schema.by_slug[slug]["scope"], SHOWN_SCOPE)))
    answer = proposal["answer"]
    if answer["kind"] == "shelf":
        say("The model's pick: %d. %s. Its reason: %s" % (answer["index"], safe(schema.by_slug[answer["chosen"]]["name"], 200), safe(answer.get("reason") or "", SHOWN_REASON)))
    elif answer["kind"] == "none":
        say("The model said none of the five fits. Its reason: %s" % safe(answer.get("reason") or "", SHOWN_REASON))
    else:
        say("The model gave no usable answer.")


def _ask(input_fn, say, proposal):
    """The owner's answer as `(typed, result, equals_pick)`, or None to stop. Anything that is not an answer is asked again."""
    answer = proposal["answer"]
    while True:
        try:
            raw = input_fn(QUESTION)
        except EOFError:
            return None
        text = str(raw).strip()
        typed = safe(text, 400)
        if text == "quit":
            return None
        if re.fullmatch(r"[1-5]", text):
            slug = proposal["order"][int(text) - 1]
            return typed, {"kind": "shelf", "shelf": slug, "words": None}, answer["kind"] == "shelf" and answer["chosen"] == slug
        if text == "ok":
            if answer["kind"] == "shelf":
                return typed, {"kind": "shelf", "shelf": answer["chosen"], "words": None}, True
            if answer["kind"] == "none":
                return typed, {"kind": "none", "shelf": None, "words": None}, True
            say("There is no model's pick to accept for this book: choose 1 to 5, none, skip <words> or quit.")
            continue
        if text == "none":
            return typed, {"kind": "none", "shelf": None, "words": None}, answer["kind"] == "none"
        found = _ANSWER_SKIP.fullmatch(text)
        if found:
            words = safe(found.group(1), 10000)
            if words and len(words) <= MAX_WORDS:
                return typed, {"kind": "skipped", "shelf": None, "words": words}, None
        say("That is not an answer. Type 1 to 5, ok, none, skip and then your words (up to %d characters), or quit." % MAX_WORDS)


def review(store, schema_path=None, book_ids=None, again=False, input_fn=input, say=print, is_tty=None):
    """Take the owner through the proposals one book at a time and record each answer as a `placement_confirmed` event. Returns the counts: the books `asked`, `confirmed` (a shelf or none), `skipped`,
    and the books left out because they are `stale`, have `no_proposal` or are `unreadable`, and whether the owner stopped. Refused unless the input is a terminal. A book already confirmed is not shown again
    unless `again`. Nothing but event lines is written."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    if is_tty is None:
        is_tty = sys.stdin.isatty
    if not is_tty():
        raise KbError("place-review asks you questions and takes your answers from a terminal; run it in your own terminal (`place-review --list` reads the counts and needs none)")
    schema, schema_hash = shelfvectors._read_schema(schema_path or shelfvectors.DEFAULT_SCHEMA)
    if book_ids is not None:
        if not isinstance(book_ids, (list, tuple)) or not all(_is_text(b) for b in book_ids):
            raise KbError("the books are a list of book ids")
        for book_id in book_ids:
            store.read_book(book_id)
        wanted = list(book_ids)
    else:
        wanted = store.list_books()
    counts = {"asked": 0, "confirmed": 0, "skipped": 0, "stale": 0, "no_proposal": 0, "unreadable": 0, "moved": 0, "stopped": False}
    todo = []
    for book_id in wanted:
        found = state_of(store, book_id, schema, schema_hash)
        if found is None:
            continue
        state, proposal, answered = found
        if state in ("stale", "no_proposal", "unreadable", "moved"):
            counts[state] += 1
            if state == "stale":
                say("The proposal for the book %s is out of date (its card or the schema changed); run `place-propose --book %s` first." % (safe(book_id, 40), safe(book_id, 40)))
            elif state == "moved" and book_ids is not None:
                say("The book %s is no longer on the shelf default, so there is nothing to answer." % safe(book_id, 40))
            continue
        if state == "confirmed" and not again:
            continue
        todo.append((book_id, proposal))
    for number, (book_id, proposal) in enumerate(todo, 1):
        _show(say, store, book_id, proposal, schema, number, len(todo))
        counts["asked"] += 1
        got = _ask(input_fn, say, proposal)
        if got is None:
            counts["stopped"] = True
            break
        typed, result, equals_pick = got
        store.append_event(book_id, EVENT, proposal=proposal["at"], version=proposal["version"], generation=proposal["generation"], text_sha256=proposal["text_sha256"],
                           schema_sha256=proposal["schema_sha256"], answer=typed, result=result, equals_pick=equals_pick)
        counts["skipped" if result["kind"] == "skipped" else "confirmed"] += 1
    return counts
