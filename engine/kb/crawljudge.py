"""The judgement of a crawled book (`docs/specs/population.md`, "The judgement"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment J).

A book is judged **once**, on the **converted text of its stored version** (`converted_text`: the stage `converted` is done and the conversion in use is read as `index` reads it), in two parts
that are loose, as `docs/specs/shelf.md` asks of relevance. **The text must be a real document** (`is_document`): at least the plan's `min_chars` characters (counted after white space is made one
space and the ends are cut), and not an error page, a login page or a menu. **Its best match among the home shelves of the schema must reach the plan's `threshold`**: the title (cut to 300 characters)
and the first 1,500 characters of the text, made plain, are embedded as one document by the existing embedding entry of the task `place-embed` (the measured model, as `placement` uses it) and
compared by cosine with the vectors of the home shelves (`shelfvectors.load`, `shelfmatch.place`): a topic shelf or a custom shelf, never a domain, a field or a subfield. The best match is the
`score` and its `shelf`; a score **at or over** the threshold keeps the book. The topics of the plan are not part of the test.

`judge(store, cfg, plan, book_id, version_id, embed=None)` returns `(ok, score, shelf, reason)` and records nothing; `embed` is the embedding function (default `models.embed`) and is the one place a
model is called. A text that is not a document gives `(False, None, None, reason)` and **no model call and no read of the shelf vectors**. **An empty `threshold` refuses (`KbError`) before anything is read or
sent.** A model that fails or answers with something that is not a vector is a `ModelFailed` (a `KbError`), whose `why` is a fixed sentence: **what the model said is untrusted and is never kept**. A
refusal that is not that (no entry set, shelf vectors missing or stale, a model that is not the measured one) is a plain `KbError`: it is not a failed try and nothing is recorded for it.

`judge_book(store, conn, cfg, plan, book_id, version_id, run, now, embed=None)` takes one crawl book through the judgement and its record, once: it **finds a verdict already recorded** (`crawl_judged`, or a
`crawl_rejected` of the stage `judge`) and does not ask the model again; a kept book gets `crawlbooks.record_judged(..., True)`; a book under the threshold, or one that is not a document, is **weeded**
(`crawlbooks.weed(..., "judge")`: the event `crawl_rejected` with the reason and the score, the state `weeded`, the files kept) and its queue row, if it is still `kept`, becomes `rejected`
(`crawlstate.reject_kept`); a model that fails is a failed try (`crawlbooks.fail_step`), and at the plan's `retries` such tries the book is parked (weeded, stage `judge`) and its row rejected. It writes **one
`judge` line of the log** for what it did (counts and the score only, no text of the page or the title). A book that is not one the crawl filed is refused; a book that is final already is left alone.
Nothing here opens a card, makes a request or reads the owner's config, plan or key."""
import datetime
import math
import time

from . import KbError, convert, crawlbooks, crawllog, crawlstate, models, placement, shelfmatch, shelfvectors, stages

MAX_TEXT = 1500                      # characters of the converted text that are embedded (the spec's rule)
MAX_TITLE = 300                      # characters of the title that are embedded
JOIN = "\n\n"                        # between the title and the text
NOT_LONG_ENOUGH = "the text is too short to be a document"
ERROR_PAGE = "the page is an error page"
LOGIN_PAGE = "the page is a login page"
MENU_PAGE = "the page is a menu or a list of links"
MODEL_FAILED = "the embedding model could not be reached or refused"
MODEL_ANSWER_BAD = "the embedding model's answer was not a usable vector"

# the rules of a real document; each is a number or a list that a test holds
ERROR_SCAN = 300                     # an error phrase counts in the first characters of the text only ...
ERROR_MAX_CHARS = 2000               # ... and in a text of at most this many characters
ERROR_PHRASES = ("page not found", "404 not found", "error 404", "404 error", "403 forbidden", "error 403", "access denied", "internal server error", "500 error",
                 "service unavailable", "bad gateway", "gateway timeout", "too many requests", "something went wrong", "this page does not exist", "this page doesn't exist",
                 "this page is not available", "page you requested", "verify you are human", "enable javascript", "enable cookies", "unusual traffic", "request blocked",
                 "are you a robot")
LOGIN_MAX_CHARS = 3000               # a login page is a short page
LOGIN_MARKERS = ("sign in", "log in", "login", "password", "username", "forgot", "create an account", "remember me", "two-factor", "email address")
LOGIN_MIN_MARKERS = 3                # different markers
MENU_MIN_BLOCKS = 8                  # a menu is many blocks (blocks are the paragraphs of the converted text, separated by a blank line) ...
MENU_SHORT = 40                      # ... of at most this many characters ...
MENU_SHARE = 0.8                     # ... at least this share of them ...
MENU_LONGEST = 200                   # ... with no block over this many characters
MIN_SENTENCES = 2                    # a text of at most MENU_MAX_CHARS characters with fewer sentence endings than this is a list, not prose
MENU_MAX_CHARS = 3000
SENTENCE_ENDINGS = ".!?。！？"


class ModelFailed(KbError):
    """The embedding model failed or its answer was not a vector: a failed try, not a verdict. `why` is a fixed sentence; what the model said is not kept."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


# --- the plan's two numbers

def _threshold(plan):
    value = plan.get("threshold") if isinstance(plan, dict) else None
    if value is None:
        raise KbError("the plan's threshold is empty: it is set in the supervised run, and no book is judged until it is")
    if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
        raise KbError("the plan's threshold is a number from -1 to 1")
    return float(value)


def _min_chars(plan):
    value = plan.get("min_chars") if isinstance(plan, dict) else None
    if type(value) is not int or value < 1:
        raise KbError("the plan's min_chars is a whole number of at least 1")
    return value


# --- a real document

def _is_menu(text, plain):
    blocks = [b for b in (" ".join(part.split()) for part in text.split("\n\n")) if b]
    if len(blocks) >= MENU_MIN_BLOCKS:
        short = sum(len(b) <= MENU_SHORT for b in blocks)
        if short / len(blocks) >= MENU_SHARE and max(len(b) for b in blocks) <= MENU_LONGEST:
            return True
    return len(plain) <= MENU_MAX_CHARS and sum(plain.count(mark) for mark in SENTENCE_ENDINGS) < MIN_SENTENCES


def is_document(text, plan):
    """`(True, None)` if `text` is a real document, else `(False, the reason)`: too short (under `min_chars` after white space is made one space), an error page (an error phrase in its first 300
    characters, in a text of at most 2,000), a login page (three different login words in a text of at most 3,000), or a menu or a list of links (eight or more blocks, 80% of them of at most 40
    characters and none over 200; or fewer than two sentence endings in a text of at most 3,000 characters). The rules are applied in that order."""
    minimum = _min_chars(plan)
    if not isinstance(text, str):
        raise KbError("the text to judge is text")
    plain = " ".join(text.split())
    if len(plain) < minimum:
        return False, NOT_LONG_ENOUGH
    lower = plain.lower()
    if len(plain) <= ERROR_MAX_CHARS and any(phrase in lower[:ERROR_SCAN] for phrase in ERROR_PHRASES):
        return False, ERROR_PAGE
    if len(plain) <= LOGIN_MAX_CHARS and sum(marker in lower for marker in LOGIN_MARKERS) >= LOGIN_MIN_MARKERS:
        return False, LOGIN_PAGE
    if _is_menu(text, plain):
        return False, MENU_PAGE
    return True, None


# --- the text of a version

def converted_text(store, book_id, version_id):
    """`(the title of the book, the converted text of the version)`: the conversion in use of a version whose stage `converted` is done. Only the root file, the stage state and the stored conversion
    are read; no card and no original."""
    if stages.read(store, book_id, version_id)["stages"]["converted"]["status"] != "done":
        raise KbError("the version has not been converted, so there is nothing to judge")
    loaded = convert.load_in_use(store, book_id, version_id)
    if loaded is None:
        raise KbError("the version has no conversion to judge")
    title = store.read_book(book_id).get("title")
    return (title if isinstance(title, str) else ""), loaded[1].text


def embedded_text(title, text):
    """What is embedded: the title (made plain, at most 300 characters) and the first 1,500 characters of the text (made plain), apart by a blank line; the text alone if there is no title."""
    body = placement.plain(text, MAX_TEXT)
    head = placement.plain(title, MAX_TITLE) if isinstance(title, str) else ""
    return head + JOIN + body if head else body


# --- the verdict

def below_threshold(shelf, score, threshold):
    return f"the best shelf is {shelf} at {score:.3f}, under the threshold {threshold:g}"


def _best(store, cfg, sent, embed):
    """`(score, shelf)` of the best home shelf for the text `sent`. The entry and the shelf vectors are checked before the model is asked."""
    name, entry = shelfvectors.entry_for(cfg)
    loaded = shelfvectors.load(store.cfg["index_root"], cfg)
    space = shelfmatch.build_space(loaded["schema"], loaded["vectors"])
    embed = embed or models.embed
    try:
        got = embed(cfg, name, [sent], kind="document")
    except (KbError, OSError):
        raise ModelFailed(MODEL_FAILED) from None
    vectors = got.get("vectors") if isinstance(got, dict) else None
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise ModelFailed(MODEL_ANSWER_BAD)
    if got.get("model") != shelfvectors.MEASURED_MODEL or got.get("model") != loaded["meta"]["model"]:
        raise KbError("the embedding model the bridge reports is not the measured one that made the shelf vectors; nothing was recorded")
    vector = vectors[0]
    if not isinstance(vector, list) or len(vector) != entry["dimension"]:
        raise ModelFailed(MODEL_ANSWER_BAD)
    try:
        slug, cosine = shelfmatch.place(space, vector, k=1)["home"][0]
    except KbError:
        raise ModelFailed(MODEL_ANSWER_BAD) from None
    return float(cosine), slug


def _verdict(store, cfg, plan, threshold, title, text, embed):
    ok, reason = is_document(text, plan)
    if not ok:
        return False, None, None, reason
    score, shelf = _best(store, cfg, embedded_text(title, text), embed)
    if score >= threshold:
        return True, score, shelf, None
    return False, score, shelf, below_threshold(shelf, score, threshold)


def judge(store, cfg, plan, book_id, version_id, embed=None):
    """`(ok, score, shelf, reason)` for the converted text of a version, and nothing recorded. See the top of this module for the rule."""
    threshold = _threshold(plan)
    title, text = converted_text(store, book_id, version_id)
    return _verdict(store, cfg, plan, threshold, title, text, embed)


# --- the record

def _newest(events, name):
    found = [e for e in events if isinstance(e, dict) and e.get("event") == name]
    return found[-1] if found else None


def _number(value):
    """A stored score, if it is a number in the range of a score; what an event holds is not trusted."""
    return float(value) if type(value) in (int, float) and math.isfinite(value) and -1 <= value <= 1 else None


def _name(value):
    return value if isinstance(value, str) and value else None


def _result(outcome, ok=None, score=None, shelf=None, reason=None):
    return {"outcome": outcome, "ok": ok, "score": score, "shelf": shelf, "reason": reason}


def _reject_row(conn, plan, row, reason, now):
    """The queue row of a weeded book becomes `rejected` if it is still `kept`; true if it was changed."""
    if type(row) is not int:
        return False
    found = conn.execute("SELECT status FROM candidates WHERE id = ?", (row,)).fetchone()
    if found is None or found[0] != "kept":
        return False
    crawlstate.reject_kept(conn, plan, row, reason, now)
    return True


def judge_book(store, conn, cfg, plan, book_id, version_id, run, now, embed=None):
    """Take one crawl book through the judgement and its record. Returns `{"outcome", "ok", "score", "shelf", "reason"}`, `outcome` being `kept`, `rejected`, `retry`, `parked`, `already_kept`,
    `already_rejected` or `final`. Refused (`KbError`) before anything is read of the book or sent: an empty or odd threshold, a run that is not a name, a time with no zone; and, before the model is
    asked, a book that is not one the crawl filed, a version that is not converted, and an entry, shelf vectors or model that are not right."""
    threshold = _threshold(plan)
    log = crawllog.Log(store.cfg["index_root"], run)
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise KbError("the judgement needs a time with a time zone")
    events = store.read_events(book_id)
    found = crawlbooks._found(events)
    if found is None or store.read_book(book_id).get("auto_filed") is not True:
        raise KbError("the book is not one the crawl filed")
    row = found.get("candidate")

    def line(outcome, reason, chars=None, seconds=None):
        log.write("judge", outcome, candidate=row if type(row) is int else None, book=book_id, n=chars, reason=reason, seconds=seconds, now=now)

    def weed(reason, score, chars, seconds):
        weeded = crawlbooks.weed(store, book_id, reason, score, "judge")
        moved = _reject_row(conn, plan, row, reason, now)
        if weeded or moved:
            line("rejected", reason, chars, seconds)

    judged, rejected = _newest(events, "crawl_judged"), _newest(events, "crawl_rejected")
    if judged is not None and judged.get("ok") is True:
        return _result("already_kept", True, _number(judged.get("score")), _name(judged.get("shelf")))
    if rejected is not None:
        earlier = _name(rejected.get("reason"))             # what an event holds is not trusted: a reason that is not text is none
        if rejected.get("stage") == "judge" and _reject_row(conn, plan, row, earlier, now):
            line("rejected", earlier)
        return _result("already_rejected", False, _number(rejected.get("score")), None, earlier)
    if crawlbooks._has_terminal(events):
        return _result("final")
    if judged is not None:                                  # a verdict of no with no weeding after it: finish it from what is written
        shelf, score = _name(judged.get("shelf")), _number(judged.get("score"))
        reason = below_threshold(shelf, score, threshold) if shelf is not None and score is not None else "judged out before"
        weed(reason, score, None, None)
        return _result("rejected", False, score, shelf, reason)
    title, text = converted_text(store, book_id, version_id)
    started = time.monotonic()
    try:
        ok, score, shelf, reason = _verdict(store, cfg, plan, threshold, title, text, embed)
    except ModelFailed as failed:
        state = crawlbooks.fail_step(store, plan, book_id, "judge", failed.why, run)
        if state == "parked":
            parked = _newest(store.read_events(book_id), "crawl_rejected")
            reason = parked.get("reason") if parked is not None else failed.why
            if _reject_row(conn, plan, row, reason, now):
                line("rejected", reason, len(text))
            return _result("parked", None, None, None, reason)
        line("failed", failed.why, len(text))
        return _result("retry", None, None, None, failed.why)
    seconds = round(time.monotonic() - started, 3) if score is not None else None
    if ok:
        crawlbooks.record_judged(store, book_id, score, shelf, True)
        line("ok", f"score {score:.3f} shelf {shelf}", len(text), seconds)
        return _result("kept", True, score, shelf)
    weed(reason, score, len(text), seconds)
    return _result("rejected", False, score, shelf, reason)
