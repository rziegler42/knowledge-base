"""The `card` step of the unattended crawl: cards over the batch (`docs/specs/population.md`, "Cards and the proposal run over the batch"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment K).

A crawl book that was judged in (`crawl_judged` with `ok`), has no terminal event and was found under an approved plan is given its card by the card queue (`cardqueue`), which goes through the models one at a time
so that each is loaded once. What the queue plans, and what one call costs: `cardqueue.plan` takes a snapshot of the books it is given (it makes no call), and `cardqueue.run` makes the calls of one pass, each
model visited once for every book that waits for it, a card being filed as soon as its last call is made; a call that fails or is refused is tried once more in the next pass, and after that the book is reported as
failed. A card takes the notes (one call for each piece of the text), the card, the checks and, if a model is set for it, a second round, so one book costs at least two calls and usually about four.

What this step guards:

- **The queue is planned with the explicit ids of the books this step is finishing, and never with none** (with none the queue plans every card-less book in the library, the owner's included). The ids are those
  of the books that got a unit of `cards_per_day`.
- **One unit of `cards_per_day` is taken (`crawlstate.reserve_card`) for each book before it is given a card, and none is taken after the ceiling**: the ceiling ends the taking quietly (one `skipped` line) and the
  later books wait for the next run. A unit is taken before the work, so a death or a failed try after it leaves a unit that was not used (it counts too much, never too little); a book that fails tries again with
  a new unit in the next run.
- **The stop file and the disk floors are looked at before each unit and before each pass of the queue**, not only at the start. A refusal by either is a quiet end of the step (one `skipped` line with a fixed reason),
  not a failure and not a trip, and a book that waits at it has no failed try. A pass is the unit the queue can be stopped at: the queue does not look at the stop file inside a pass.
- **The queue is run one pass at a time, up to its own bound** (`cardqueue.PASS_CAP`). A pass that ends with books still waiting after the last pass is a stage that hit a bound: the step trips the breaker as a
  `stage_bound` (`ctx.trip`) and the run ends.
- **A book the queue cannot give a card is a failed try of that book** (`crawlbooks.fail_step`, step `card`, one try for the run however many times the queue asked), with a fixed reason; at the plan's `retries` such
  tries the book is parked (weeded with `crawl_rejected`, stage `card`: a terminal event, so it is never listed or planned again and the report names it). A book the queue leaves out of its plan, and one it drops,
  are failed tries with reasons of their own, so that neither loops for ever.
- **A model that does not answer is not the book's fault.** When a pass has a failed call, the step asks each distinct model entry of the card (the entries of the tasks `card-embed`, `card-notes`, `card`, `card-check`
  and `card-more` if it is set; two tasks that name one entry share one probe) one short call (`probe(cfg, task)`, `crawlguard.probe_entry`), in that order, and **stops at the first entry that does not answer**: that
  entry starts or goes on with its own down clock (`crawlguard.record_entry`, saved in the guard state before any trip is written), costs no book a try, ends the step with one `failed` line, and trips the breaker
  (`model_down`) once it has been down for longer than `model_down_minutes`; each entry that answers has its clock cleared. **The stop file and the time budget are looked at between the probes**: a step that is stopped
  there ends quietly with one `skipped` line and charges no book a try, because it has not shown that the entries answer. A pass with no failed call makes no probe.
- **What a model, a card or a page says is data.** The step reads no page text, and **of a card it reads one fact** (`has_sentences`: whether the newest card holds any sentence, below); what it writes (an event, a reason,
  a log line) is a fixed sentence, a number or a book's id, never a word of the queue's report or of a card. A card is the book's, filed by the queue as it files every card; the book stays `auto_filed`, which is the mark
  that the owner has not reviewed it, and nothing else in a card changes what a step does.
- **A page with nothing in it is judged out after its card** (`judge_out_empty_cards`, at the end of every step, whether or not it made a card): a crawl book that is judged in and whose newest card has **no sentence at all** in its six written parts
  (a repository record with only metadata, whose title matched a shelf; a card that lost only its summary to the checks is kept) is weeded at the stage `card` with a fixed reason, kept with its files, its row `rejected`, one `reject` line, out of the index; it looks at the stop file
  and the disk floors first, and skips a card that cannot be read. A book with any summary is untouched.

One `card` line is written for each book that ends in this run (`ok`, `failed` for a try that will be repeated, `rejected` for a book that was parked), and one line when the step ends early or has nothing to do
(`skipped`). The step is idempotent: a book that has its card is not planned again, and a run with nothing to do takes no unit, asks no model and writes one `skipped` line.

The step is not attached to `crawl-run` here (Increment M assembles the steps). The module makes no request and reads no environment variable; the queue makes the calls through the configured entries."""
import os

from . import KbError, card, cardqueue, cardstate, crawlbooks, crawlguard, crawlrun, crawlstate, crawlsteps
from . import index as index_stage
from . import store as library_store

STOPPED = "the stop file is present"
DISK = "the disk floor refuses a card pass"
CEILING = "cards_per_day reached: no more cards today"
BATCH = "the card queue holds no more books in one run"
NOTHING = "no kept book is waiting for a card"
DOWN = "the model server did not answer"
FAILED = "the card could not be made"
DROPPED = "the card queue dropped the book"
NOT_PLANNED = "the book could not be planned for a card"
PARKED = "the book is parked after failed tries"
CATALOG = "the catalog was not rebuilt"
EMPTY_CARD = "the card has no sentence at all (no summary, problem, approach, needs, provides or limits): the page holds nothing of its own to keep"
SPENT = "the time budget of the run is spent"
CARD_TASKS = ("card-embed", "card-notes", "card", "card-check", "card-more")           # the tasks whose entries a card calls, in the order they are asked
SETTINGS = "the models for cards are not set up"


def _waiting(library, scan, approved):
    """The crawl books that need a card, in the order found: unfinished, found under an approved plan, judged in, with no card for their current version."""
    judged = {e["id"]: any(isinstance(x, dict) and x.get("event") == "crawl_judged" and x.get("ok") is True for x in e["events"]) for e in scan.entries}
    return [book for book in crawlbooks.crawl_books(library, approved, scan) if judged.get(book) and not _has_card(library, book)]


def _has_card(library, book):
    version = library.read_book(book).get("current_version")
    return bool(version) and bool(card.generations(library, book, version))


def _refusal(ctx, read_space):
    """Why no more work is started now (the stop file, or a disk floor), or `None`."""
    if crawlguard.stop_requested(ctx.index_root):
        return STOPPED
    try:
        crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=read_space)
    except KbError:
        return DISK
    return None


def _answers(ctx, probe, answered):
    """Ask each distinct model entry of the card one short call, in the order of `CARD_TASKS`, and note each answer in the entry's own down clock (a trip of a clock ends the run). **An entry that answered earlier in
    this step (`answered`, kept by the caller) is not asked again**: a later pass that fails with every entry answering has no new evidence, and each probe of a chat entry loads a model on the server. Returns `"ok"` when
    every entry answered, `"down"` at the first that did not (the entries after it are not asked and keep their clocks), or the reason of a quiet end when the stop file or the time budget appeared between two probes."""
    asked = set(answered)
    for task in CARD_TASKS:
        try:
            entry = crawlguard.entry_of(ctx.cfg, task)
        except KbError:
            continue
        if not entry or entry in asked:
            continue
        if asked:
            if crawlguard.stop_requested(ctx.index_root):
                return STOPPED
            if crawlrun.spent(ctx):
                return SPENT
        asked.add(entry)
        try:
            ok = bool((probe or crawlguard.probe_entry)(ctx.cfg, task))
        except (KbError, OSError):
            ok = False
        tripped = crawlguard.record_entry(ctx.index_root, entry, ok, ctx.clock(), ctx.plan)
        if tripped is not None:
            ctx.trip(*tripped)
            raise crawlrun.BreakerTripped()
        if not ok:
            return "down"
        answered.add(entry)
    return "ok"


def has_sentences(doc):
    """Whether a card holds any sentence at all in its six written parts (`card.SENTENCE_FIELDS`: the summary, the problem, the approach, the needs, the provides and the limits). A card with grounded sentences has one if
    any part kept a sentence after the checks; a card of the earlier form, if any of those parts is not blank; a card with no model part has none. Anything that is not a card has none. **A card that lost only its summary
    to the checks still has sentences and is kept**: the rule is for a page that holds nothing (a record with only metadata), and not for a card whose checks were strict. This is the one fact the step reads of a card,
    and no word of the card is copied anywhere."""
    model = doc.get("model") if isinstance(doc, dict) else None
    if not isinstance(model, dict):
        return False
    grounding = doc.get("grounding")
    sentences = grounding.get("sentences") if isinstance(grounding, dict) else None
    if isinstance(sentences, dict):
        return any(isinstance(sentences.get(field), dict) and bool(sentences[field].get("kept")) for field in card.SENTENCE_FIELDS)
    return any(isinstance(model.get(field), str) and bool(model[field].strip()) for field in card.SENTENCE_FIELDS)


def judge_out_empty_cards(ctx, library, read_space, approved):
    """Judge out each crawl book that is judged in and has a card whose newest generation has no sentence at all (a record page with only metadata: its title matched a shelf, its card says nothing): the book is weeded at
    the stage `card` with a fixed reason (kept, with its files; its row is `rejected`, one `reject` line names it, and it leaves the index). It looks at the stop file and the disk floors first, as the rest of the step
    does, and does nothing then. Only books the crawl filed under an approved plan are looked at (`crawlbooks.crawl_books`), and a card that cannot be read is skipped. Returns the books it judged out."""
    if _refusal(ctx, read_space):
        return []
    scan = crawlbooks.scan_crawl_books(library)
    judged = {e["id"]: any(isinstance(x, dict) and x.get("event") == "crawl_judged" and x.get("ok") is True for x in e["events"]) for e in scan.entries}
    out = []
    for book in crawlbooks.crawl_books(library, approved, scan):
        if not judged.get(book):
            continue
        version = library.read_book(book).get("current_version")
        if not version or not card.generations(library, book, version):
            continue
        try:
            _number, doc = card.read(library, book, version)
        except KbError:
            continue
        if has_sentences(doc):
            continue
        crawlsteps.reject_book(ctx, library, book, EMPTY_CARD, "card")
        out.append(book)
    if out:
        index_stage.forget_inactive(library)                    # a book put away leaves the search now
    return out


def _say(ctx, outcome, reason, book=None):
    ctx.log.write("card", outcome, book=book, reason=reason, now=ctx.clock())


def _failed_try(ctx, library, book, reason):
    """One failed try of this book for this run, and its line."""
    result = crawlbooks.fail_step(library, ctx.plan, book, "card", reason, ctx.run)
    if result == "parked":
        _say(ctx, "rejected", PARKED, book)
    elif result == "retry":
        _say(ctx, "failed", reason, book)


def make_step(open_store=None, statvfs=None, approved=None, probe=None, launcher=None, root=None):
    """The function for the `card` point. `open_store`, `statvfs`, `approved` (the approved digests, given the index root), `probe` (the probe of one model entry, given the config and the task), `launcher` and `root` replace the
    real ones (tests)."""
    read_space = statvfs or os.statvfs

    def step(ctx):
        library = (open_store or library_store.Store.open)()
        digests = (approved or crawlbooks.approved_digests)(ctx.index_root)
        _work(ctx, library, digests)
        judge_out_empty_cards(ctx, library, read_space, digests)               # (a refusal or a trip above ends the step before this)

    def _work(ctx, library, digests):
        scan = crawlbooks.scan_crawl_books(library)
        todo = _waiting(library, scan, digests)
        chosen, limit = [], None
        for book in todo:
            if len(chosen) >= cardstate.MAX_ITEMS:
                limit = BATCH
                break
            limit = _refusal(ctx, read_space)
            if limit is None and not crawlstate.reserve_card(ctx.conn, ctx.plan, ctx.clock()):
                limit = CEILING
            if limit is not None:
                break
            chosen.append(book)
        if not chosen:
            _say(ctx, "skipped", limit or NOTHING)
            return
        try:
            summary = cardqueue.plan(library, ctx.cfg, book_ids=chosen)
        except KbError:
            raise crawlrun.StepRefused(SETTINGS) from None
        planned = {item["book_id"] for item in cardstate.read_manifest(ctx.index_root, summary["run"]).items}
        left_out = [book for book in chosen if book not in planned and not _has_card(library, book)]
        report, down, stopped, bound, uncharged, answered = None, False, None, False, False, set()
        try:
            for _ in range(cardqueue.PASS_CAP):
                stopped = _refusal(ctx, read_space)
                if stopped:
                    break
                report = cardqueue.run(library, ctx.cfg, summary["run"], passes=1, launcher=launcher, root=root)
                if any(i["status"] == "failed" or (i["status"] == "waiting" and i["attempts"] > 0) for i in report["items"]):
                    try:
                        verdict = _answers(ctx, probe, answered)
                    except crawlrun.BreakerTripped:
                        uncharged = True                                         # a trip is not shown to be the books' fault: no book is charged
                        raise
                    if verdict == "down":
                        down = True
                        break
                    if verdict != "ok":                                          # stopped between two probes: nothing is shown, so no book is charged
                        stopped, uncharged = verdict, True
                        break
                if report["counts"]["waiting"] == 0:
                    break
            else:
                bound = True
            if bound:
                ctx.trip(*crawlguard.bound_trip("card", f"the queue still had books waiting after {cardqueue.PASS_CAP} passes"))
                raise crawlrun.BreakerTripped()
        finally:
            _close(ctx, library, report, left_out, down, stopped or limit, uncharged)

    return step


def _close(ctx, library, report, left_out, down, ended, uncharged=False):
    """The lines and the failed tries of what this run did: each book that ended, each book the queue could not plan, the catalog, and why the step ended early."""
    for item in (report or {"items": []})["items"]:
        if item["status"] == "done":
            generation = item["generation"]
            _say(ctx, "ok", f"generation {generation}" if isinstance(generation, int) and not isinstance(generation, bool) else None, item["book_id"])
        elif item["status"] in ("failed", "dropped") and not down and not uncharged:
            _failed_try(ctx, library, item["book_id"], FAILED if item["status"] == "failed" else DROPPED)
    if not down and not uncharged:
        for book in left_out:
            _failed_try(ctx, library, book, NOT_PLANNED)
    if report is not None and isinstance(report.get("catalog"), dict) and isinstance(report["catalog"].get("failed"), str):       # a rebuild that worked says how many books failed, a number; one that did not says why
        _say(ctx, "failed", CATALOG)
    if down:
        _say(ctx, "failed", DOWN)
    elif ended:
        _say(ctx, "skipped", ended)


step = make_step()
