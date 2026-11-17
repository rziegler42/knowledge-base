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
- **A model server that does not answer is not the book's fault.** When a pass has a failed call, the step asks the run's own probe of the model server (`crawlguard.probe_model`); a server that does not answer
  starts or goes on with the down clock (`crawlguard.note_model`, saved in the guard state), costs no book a try, ends the step with one `failed` line, and trips the breaker (`model_down`) once it has been down for
  longer than `model_down_minutes`; a server that answers clears the clock.
- **What a model, a card or a page says is data.** The step reads no card and no page text; what it writes (an event, a reason, a log line) is a fixed sentence, a number or a book's id, never a word of the queue's
  report. A card is the book's, filed by the queue as it files every card; the book stays `auto_filed`, which is the mark that the owner has not reviewed it, and nothing in a card changes what a step does.

One `card` line is written for each book that ends in this run (`ok`, `failed` for a try that will be repeated, `rejected` for a book that was parked), and one line when the step ends early or has nothing to do
(`skipped`). The step is idempotent: a book that has its card is not planned again, and a run with nothing to do takes no unit, asks no model and writes one `skipped` line.

The step is not attached to `crawl-run` here (Increment M assembles the steps). The module makes no request and reads no environment variable; the queue makes the calls through the configured entries."""
import os

from . import KbError, card, cardqueue, cardstate, crawlbooks, crawlguard, crawlrun, crawlstate
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


def _answers(ctx, probe):
    """Ask the model server, note the answer in the down clock and return it; a trip of the clock ends the run."""
    try:
        ok = bool((probe or crawlguard.probe_model)(ctx.cfg))
    except (KbError, OSError):
        ok = False
    state, _restarted = crawlguard.load_state(ctx.index_root)
    tripped = crawlguard.note_model(state, ok, ctx.clock(), ctx.plan)
    crawlguard.save_state(ctx.index_root, state)
    if tripped is not None:
        ctx.trip(*tripped)
        raise crawlrun.BreakerTripped()
    return ok


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
    """The function for the `card` point. `open_store`, `statvfs`, `approved` (the approved digests, given the index root), `probe` (the model server's, given the config), `launcher` and `root` replace the
    real ones (tests)."""
    read_space = statvfs or os.statvfs

    def step(ctx):
        library = (open_store or library_store.Store.open)()
        scan = crawlbooks.scan_crawl_books(library)
        todo = _waiting(library, scan, (approved or crawlbooks.approved_digests)(ctx.index_root))
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
        report, down, stopped, bound = None, False, None, False
        try:
            for _ in range(cardqueue.PASS_CAP):
                stopped = _refusal(ctx, read_space)
                if stopped:
                    break
                report = cardqueue.run(library, ctx.cfg, summary["run"], passes=1, launcher=launcher, root=root)
                if any(i["status"] == "failed" or (i["status"] == "waiting" and i["attempts"] > 0) for i in report["items"]) and not _answers(ctx, probe):
                    down = True
                    break
                if report["counts"]["waiting"] == 0:
                    break
            else:
                bound = True
            if bound:
                ctx.trip(*crawlguard.bound_trip("card", f"the queue still had books waiting after {cardqueue.PASS_CAP} passes"))
                raise crawlrun.BreakerTripped()
        finally:
            _close(ctx, library, report, left_out, down, stopped or limit)

    return step


def _close(ctx, library, report, left_out, down, ended):
    """The lines and the failed tries of what this run did: each book that ended, each book the queue could not plan, the catalog, and why the step ended early."""
    for item in (report or {"items": []})["items"]:
        if item["status"] == "done":
            generation = item["generation"]
            _say(ctx, "ok", f"generation {generation}" if isinstance(generation, int) and not isinstance(generation, bool) else None, item["book_id"])
        elif item["status"] in ("failed", "dropped") and not down:
            _failed_try(ctx, library, item["book_id"], FAILED if item["status"] == "failed" else DROPPED)
    if not down:
        for book in left_out:
            _failed_try(ctx, library, book, NOT_PLANNED)
    if report is not None and isinstance(report.get("catalog"), dict) and isinstance(report["catalog"].get("failed"), str):       # a rebuild that worked says how many books failed, a number; one that did not says why
        _say(ctx, "failed", CATALOG)
    if down:
        _say(ctx, "failed", DOWN)
    elif ended:
        _say(ctx, "skipped", ended)


step = make_step()
