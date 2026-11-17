"""The proposal and the move of the unattended crawl (`docs/specs/population.md`, "The move is a new path, not place-apply" and "Cards and the proposal run over the batch"; the plan
`2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment L).

A crawl book that was found under an approved plan, was judged in, has a card and has no terminal event is given a proposal of a home shelf (`placement.propose`) and is moved onto the shelf the model picked. This is
the one step that changes the shelf of a book with no one at the keyboard, so it does as little as the rule allows and nothing else.

What the step does, for one book at a time, oldest first:

1. `placement.propose` is called **with the explicit id of the one book and never with none** (with none it covers every book on `default`, the owner's included, and 172 of them have unanswered proposals the runner
   never touches). A book that has a current proposal already is not proposed for again (a run that died after the proposal goes on to the move).
2. The move is made only if the newest `placement_proposed` event passes, in this order: the shape `place-propose` writes (`placereview.proposal_ok`); it is current, the same card, text, schema, shelf vectors and prompt
   (`placement.is_current`); its answer is a shelf (not `none`, not malformed); that shelf is one of the five offered; it is a home shelf of the schema and not `default`; the store accepts its name; and the time of the
   proposal is a time the store writes. Then, **under the catalog lock taken for this one move and not for the batch**, the book's root file is read again and must still be active, still of the version the card was
   for, and on `default`; the shelf is set with the store's `set_shelf`, read back, and one `reshelved` line is appended (`from`, `to`, `action: move`, `basis: model-pick`, `via: crawl`, `run`, `plan_digest`, `proposal`,
   `schema_sha256`, and **no** `confirmation`: nobody confirmed it). A death between the new shelf and the line is finished by the next run, which writes the line with `action: record` and moves nothing.
3. A book whose proposal is `none` or malformed, whose shelf fails a check, or which the store refuses, stays where it is and gets `crawl_unplaced` once, with a fixed reason, and is not tried again. A book whose shelf read
   back is not the one set is logged as failed and gets `crawl_unplaced` too; it trips nothing. A book whose event log cannot safely take another line is left alone and logged (a line appended to it would corrupt it).
4. A book of an unapproved, missing or malformed plan digest is neither proposed nor moved: `crawlbooks.reconcile_unapproved` gives it `crawl_unplaced` once.

What it guards: the stop file before each model call and before each move; the disk floors before each model call (before each proposal; a move writes a few bytes); a refusal by either ends the step with one `skipped` line
and leaves the book as it was (not unplaced, not a failed try). A chat model that fails for a book is a failed try of the book (`crawlbooks.fail_step`, step `propose`; parked at the plan's `retries`), **but only when
the model has answered for another book in this run**; a run in which the model answered for nobody is a server that is down, which costs no book a try and feeds the down clock (`crawlguard.note_model`) instead. The
embedding probe is asked only when the embedding call itself fails, never to decide that the chat model is up, since it cannot see the chat model. A failed embedding that the probe says is a refusal (a model that is not
the measured one) refuses the run with a fixed text.

What it writes is a fixed sentence, a number or an id: never a word a model or a page said. The proposal's own cleaned fields stay in the proposal that `placement` writes. The only mark that a crawl book is unreviewed by
the owner is its own `auto_filed`, which this step leaves as it is; it adds no flag.

What it does not do: it does not call `place-review` or `place-apply` (both need the owner and a terminal), takes no owner's answer and records no `placement_confirmed`, touches no book that is not a crawl book, and is not
attached to `crawl-run` here (Increment M assembles the steps)."""
import os
import re

from . import KbError, card, catalog, crawlbooks, crawlguard, crawlrun, models, placeapply, placement, placereview, shelfvectors
from . import store as library_store
from .store import _SHELF as STORE_SHELF

NOTHING = "no kept book is waiting for a proposal"
STOPPED = "the stop file is present"
DISK = "the disk floor refuses a proposal"
PROPOSED = "a proposal was made"
CURRENT = "a proposal is current"
MOVED = "moved by the model's pick"
RECORDED = "recorded a move made before"
NO_TEXT = "the card has no text to place"
NONE_FITS = "the model said no shelf fits"
MALFORMED = "the model's answer was not a usable one"
UNREADABLE = "its proposal cannot be read"
STALE = "its proposal is out of date"
NOT_OFFERED = "the shelf chosen is not one of the five offered"
NOT_HOME = "the shelf chosen is not a home shelf of the schema"
NAME_REFUSED = "the store would refuse the shelf's name"
STORE_REFUSED = "the store refused the move"
NOT_ON_DEFAULT = "the book is not on the shelf default"
CHANGED = "the book changed while it was being moved"
READBACK = "the shelf read back was not the one set"
LOG_UNUSABLE = "its event log cannot take another line"
FAILED_TRY = "the model could not be reached for a proposal"
PARKED = "the book is parked after failed tries"
DOWN = "the model server did not answer"
MODEL_REFUSED = "the model server refused a proposal or reported another model than the measured one"
SETTINGS = "the models for proposals are not set up"
_DIGEST = re.compile(r"[0-9a-f]{32}")


class _Quiet(Exception):
    """The stop file or a disk floor refused more work: the step ends, one `skipped` line, and the book is left as it was."""

    def __init__(self, step, why):
        super().__init__(why)
        self.step, self.why = step, why


class _Down(Exception):
    """The model server did not answer the embedding: the step ends and no book has a failed try."""


def _newest(events):
    found = [e for e in events if isinstance(e, dict) and e.get("event") == placement.EVENT]
    return found[-1] if found else None


def _has_card(library, book):
    version = library.read_book(book).get("current_version")
    return bool(version) and bool(card.generations(library, book, version))


def _waiting(library, scan, approved):
    """The crawl books for the step, in the order found: unfinished, found under an approved plan, judged in and with a card."""
    judged = {e["id"]: any(isinstance(x, dict) and x.get("event") == "crawl_judged" and x.get("ok") is True for x in e["events"]) for e in scan.entries}
    return [book for book in crawlbooks.crawl_books(library, approved, scan) if judged.get(book) and _has_card(library, book)]


class _Run:
    """One run of the step: the context, the library, the shelf vectors and what the models have done so far."""

    def __init__(self, ctx, library, loaded, make):
        self.ctx, self.library, self.loaded, self.make = ctx, library, loaded, make
        self.schema = loaded["schema"]
        self.answered, self.pending = False, []

    # -- lines, tries and the down clock
    def say(self, step, outcome, reason, book=None):
        self.ctx.log.write(step, outcome, book=book, reason=reason, now=self.ctx.clock())

    def unplaced(self, book, reason):
        crawlbooks.record_unplaced(self.library, book, reason)
        self.say("move", "refused", reason, book)

    def failed_try(self, book):
        result = crawlbooks.fail_step(self.library, self.ctx.plan, book, "propose", FAILED_TRY, self.ctx.run)
        if result == "parked":
            self.say("propose", "rejected", PARKED, book)
        elif result == "retry":
            self.say("propose", "failed", FAILED_TRY, book)

    def note(self, ok):
        """Note one sighting of the model server in the down clock; a trip of the clock ends the run."""
        ctx = self.ctx
        state, _restarted = crawlguard.load_state(ctx.index_root)
        tripped = crawlguard.note_model(state, ok, ctx.clock(), ctx.plan)
        crawlguard.save_state(ctx.index_root, state)
        if tripped is not None:
            ctx.trip(*tripped)
            raise crawlrun.BreakerTripped()

    # -- the models
    def guard(self, which):
        """The model call `which` (`embed` or `call`), with the stop file and the disk floors looked at first: nothing is sent after a refusal."""
        make, ctx = self.make, self.ctx

        def guarded(*args, **kw):
            why = _refusal(ctx, make["statvfs"], disk=True)
            if why:
                raise _Quiet("propose", why)
            return (make["embed"] or models.embed)(*args, **kw) if which == "embed" else (make["call"] or models.call)(*args, **kw)

        return guarded

    def embedding_trouble(self):
        """The embedding call failed: ask the probe, and either it is a server that does not answer (the down clock, and the step ends) or a refusal that stops the run."""
        try:
            ok = bool((self.make["probe"] or crawlguard.probe_model)(self.ctx.cfg))
        except (KbError, OSError):
            ok = False
        if ok:
            raise crawlrun.StepRefused(MODEL_REFUSED)
        self.say("propose", "failed", DOWN)
        self.note(False)
        raise _Down()

    def propose(self, book):
        """Ask for one proposal for this one book. Returns whether the model answered (`False`: its call failed)."""
        make = self.make
        try:
            placement.propose(self.library, self.ctx.cfg, book_ids=[book], again=False, schema_path=make["schema_path"], launcher=make["launcher"], root=make["root"],
                              embed=self.guard("embed"), call=self.guard("call"))
        except KbError:                                           # (a refusal to go on, a trip and a quiet end are not `KbError`s and pass through)
            self.embedding_trouble()
        newest = _newest(self.library.read_events(book))
        answer = newest.get("answer") if newest is not None else None
        if isinstance(answer, dict) and answer.get("kind") == "error":
            if self.answered:
                self.failed_try(book)
            else:
                self.pending.append(book)                         # a failure before any answer: the server's, until the model answers for another book
            return False
        self.answered = True
        for earlier in self.pending:
            self.failed_try(earlier)
        self.pending = []
        self.say("propose", "ok", PROPOSED, book)
        return True

    def current(self, proposal, item):
        return proposal is not None and placereview.proposal_ok(proposal, self.schema) and placement.is_current([proposal], item, self.loaded)

    # -- one book
    def one(self, book):
        library = self.library
        if placeapply._log_unusable(library, book):
            self.say("move", "failed", LOG_UNUSABLE, book)
            return
        try:
            items, _left = placement.select(library, [book])
        except KbError:
            items = []
        if not items:
            self.unplaced(book, NO_TEXT)
            return
        item = items[0]
        proposal = _newest(library.read_events(book))
        if self.current(proposal, item):
            self.say("propose", "skipped", CURRENT, book)
        else:
            if not self.propose(book):
                return
            proposal = _newest(library.read_events(book))
            if not self.current(proposal, item):
                self.unplaced(book, STALE if placereview.proposal_ok(proposal, self.schema) else UNREADABLE)       # (a missing proposal is not of the shape)
                return
        self.move(book, proposal, item)

    def move(self, book, proposal, item):
        """The move of one book by its current proposal, or the reason it is left on `default`. The checks are made in this order; the first that fails ends it."""
        ctx, library = self.ctx, self.library
        if crawlguard.stop_requested(ctx.index_root):
            raise _Quiet("move", STOPPED)
        answer = proposal["answer"]
        if answer["kind"] == "none":
            return self.unplaced(book, NONE_FITS)
        if answer["kind"] != "shelf":
            return self.unplaced(book, MALFORMED)
        shelf = answer["chosen"]
        if shelf not in proposal["order"]:
            return self.unplaced(book, NOT_OFFERED)
        if shelf not in self.schema.home or shelf == placement.SHELF:
            return self.unplaced(book, NOT_HOME)
        if not STORE_SHELF.fullmatch(shelf):
            return self.unplaced(book, NAME_REFUSED)
        if not placeapply._at_ok(proposal["at"]):
            return self.unplaced(book, UNREADABLE)
        with catalog.lock(ctx.index_root):
            root = library.read_book(book)                        # read again, under the lock: it must still be what the proposal was made for
            if root.get("state") != "active" or root.get("current_version") != item["version"]:
                return self.say("move", "skipped", CHANGED, book)
            where = root.get("shelf")
            if where == shelf:
                action, origin = "record", None                   # a move that was made and not written down: write it down and move nothing
            elif where != placement.SHELF:
                return self.unplaced(book, NOT_ON_DEFAULT)
            else:
                action, origin = "move", placement.SHELF
                try:
                    library.set_shelf(book, shelf)
                except KbError:
                    return self.unplaced(book, STORE_REFUSED)
                if library.read_book(book).get("shelf") != shelf:
                    self.say("move", "failed", READBACK, book)
                    return crawlbooks.record_unplaced(library, book, READBACK)
            library.append_event(book, placeapply.EVENT, **{"from": origin, "to": shelf, "action": action, "basis": "model-pick", "via": "crawl", "run": ctx.run,
                                                            "plan_digest": ctx.plan_digest, "proposal": proposal["at"], "schema_sha256": proposal["schema_sha256"]})
        self.say("move", "ok", MOVED if action == "move" else RECORDED, book)


def _refusal(ctx, read_space, disk):
    """Why no more work is started now (the stop file, or a disk floor), or `None`."""
    if crawlguard.stop_requested(ctx.index_root):
        return STOPPED
    if disk:
        try:
            crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=read_space)
        except KbError:
            return DISK
    return None


def make_step(open_store=None, statvfs=None, approved=None, probe=None, launcher=None, root=None, embed=None, call=None, schema_path=None):
    """The function for the move point of a run. `open_store`, `statvfs`, `approved` (the approved digests, given the index root), `probe` (the embedding probe, given the config), `launcher`, `root`, `embed`, `call`
    and `schema_path` replace the real ones (tests)."""
    make = {"statvfs": statvfs or os.statvfs, "probe": probe, "launcher": launcher, "root": root, "embed": embed, "call": call, "schema_path": schema_path}

    def step(ctx):
        if not isinstance(getattr(ctx, "plan_digest", None), str) or not _DIGEST.fullmatch(ctx.plan_digest):
            raise crawlrun.StepRefused("the move needs the digest of the approved plan")
        library = (open_store or library_store.Store.open)()
        scan = crawlbooks.scan_crawl_books(library)
        digests = (approved or crawlbooks.approved_digests)(ctx.index_root)
        crawlbooks.reconcile_unapproved(library, digests, ctx.log, scan)
        waiting = _waiting(library, scan, digests)
        if not waiting:
            ctx.log.write("propose", "skipped", reason=NOTHING, now=ctx.clock())
            return
        try:
            placement.chat_entry_for(ctx.cfg)                     # (`load` checks the embedding entry itself)
            loaded = shelfvectors.load(ctx.index_root, ctx.cfg, schema_path=schema_path)
        except KbError:
            raise crawlrun.StepRefused(SETTINGS) from None
        run, quiet = _Run(ctx, library, loaded, make), None
        try:
            for book in waiting:
                run.one(book)
        except _Quiet as stopped:
            quiet = stopped
        except _Down:
            return
        if quiet is not None:
            run.say(quiet.step, "skipped", quiet.why)
        elif run.pending:
            run.say("propose", "failed", DOWN)                    # the model answered for nobody: the server's failure, and no book has a try
            run.note(False)
        if run.answered:
            run.note(True)

    return step


step = make_step()
