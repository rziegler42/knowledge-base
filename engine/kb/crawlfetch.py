"""The policy of a fetch of the unattended crawl (`docs/specs/population.md`, "Pacing, the type gate and the shared client"; the plan `2026-11-16-run-the-steps-of-the-unattended-crawl`, Increment F).

`build(plan, matcher, suffixes, index_root, ...)` makes the **one** `webclient.Policy` under which every candidate is fetched, and the limits that go with it (`FetchPolicy`). `classify(error)` says what a failed
fetch was, in a fixed text that holds nothing the server said. The capture of a page (`capture_url.capture`, with `policy=`, `types=` and `auto_filed=True`) is made by a later step with the value `build` gives.

Which of the spec's rules the policy has already, and which this module gives it:

- Already in the shared client (`webclient`, built and tested in the plan before this one), and only used here: the public-address check at connect (a private, loopback, link-local or metadata address is refused
  at the first hop and at every redirect hop, and the address that was checked is the one dialled), ports 80 and 443 only, no credential in an address, no encoded response, a bound on size and time, a response with
  no `Content-Type` or one that disagrees with a sniff of its first bytes refused, one request at a time to a registrable domain and to an address, and an irregular gap.
- Given here: the plan's user agent (`browser`: a common browser's string, or `generic`: the client's honest one), the plan's `min_gap_s` and `jitter`, the plan's `fetch_timeout_s` as the whole time of one
  hop, the page types only (`text/html`, `application/xhtml+xml`), at most 5 redirects, the stored Public Suffix List (a run says loudly when it has none), and the **address hook** of the `lists` step
  (`crawllists.address_hook`) at every hop: the stop file first, then the matcher (the owner's blacklist, the public lists, the URL lists, the pinned hosts and the allow file, under the separate rules of
  `weblists`). No change to `webclient.py` was needed: the stop file between the hops of one fetch is the hook.
- Said in `classify`: a block by the policy (`blocked`), the stop file (`stopped`), a refusal by a site (HTTP 401, 403, 429 or 451: `refused`, which a caller counts for the circuit breaker and does not count
  as a failure), a candidate to reject for what it is (a PDF: `pdf not safe to convert`, a page over the size limit, a body that is not a web page: `rejected`, never tried again) and a failure (`failed`).
  An abuse signal in a body, and the `Retry-After` and rate-limit headers, are not read here: only the status says (a recorded narrowing of the plan's "an abuse signal"). The tests of the text are of the start
  of the client's fixed messages, never of a part a server can fill (a content type, an encoding), so that a server cannot choose its own class.

The **`fetch` step** (`make_step`, `step`; Increment G) takes candidates from the queue and captures each as a book, within every bound. For one candidate, in this order: the stop file and the disk floors (looked at
before a row is taken, so a refusal reserves no unit and leaves no row `fetching`), `crawlstate.reserve` (a row and its units of the ceilings, in one transaction), the address (a PDF by its source or its name is rejected
with no request), the capture (`capture_url.capture` under the policy, `auto_filed`), the `crawl_found` event of the book, and last the row (`kept`, `rejected`, or a failed try). A death between two of these is finished
by the next run from what is written: a book filed with no `crawl_found` (an orphan) is adopted when its address is captured again (it is `held` then, so nothing is fetched twice), and a book that has its event for
this candidate finishes the row. A failed capture leaves no active book: capture makes a book before it knows the fetch worked, and the step sets it `weeded` with a `capture_failed` event, **not** a `crawl_rejected` one
and not a `crawl_found` one, because a retry of the same address reuses that book (the identity index has no removal) and a terminal event would end the retry, and because dead addresses must not use the ceiling on books
filed. A retry that succeeds makes the book `active` again and gives it its `crawl_found`. The step reads no link of a page (the spec leaves that out of the first version). It looks at the stop file before each row, the
disk floors, the ceilings and the batch; a ceiling or a floor ends the step, not the run. Each fetch that made a request is given to the breaker (`crawlguard.record_fetch`): a page filed or a duplicate is a success, a failed
fetch is a failure, and a block, a stop, a rejection, a PDF refused without a request and a refusal of a site are none (a refusal counts for its site: `domain_refusals`). A trip is `ctx.trip`, then the run ends.

The module itself makes no request, reads no file and no environment variable; the capture (the shared client) and the library do."""
import copy
import math
import os
from collections import namedtuple
from urllib.parse import urlsplit

from . import KbError, capture_arxiv, capture_url, convert_run, crawlbooks, crawlguard, crawllists, crawlrun, crawlstate, identity, stages, webaddr, webclient
from . import store as library_store

# a common browser's string; the plan's `user_agent = browser` sends it. It names no project, tool or contact (the owner chose a browser's, as `shelf.md` agreed).
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
PAGE_MAX_BYTES = capture_url.MAX_BYTES               # the plan has no key for the size of a page; this is the capture's own limit
SITE_REFUSALS = (401, 403, 429, 451)
PDF_REASON = "pdf not safe to convert"
MAX_ARXIV_ID = 40                                    # a real id is at most 20 characters (`math.GT/0309136`); a longer one is not read as a paper's
NOT_A_PDF = "not a PDF"
PDFS_OFF = "PDF files are off for this run: the memory of a tool cannot be read here, so a limit of memory could not be enforced"
MIB = 1024 * 1024

Outcome = namedtuple("Outcome", "kind reason retry")


class FetchPolicy:
    """What a fetch is made under: `policy` (a `webclient.Policy`), `max_bytes`, `timeout` (one network operation) and `total_timeout` (one hop). Plain attributes."""

    def __init__(self, policy, max_bytes, timeout, total_timeout, pdf_bytes=None):
        self.policy, self.max_bytes, self.timeout, self.total_timeout = policy, max_bytes, timeout, total_timeout
        self.pdf_bytes = pdf_bytes                            # the largest PDF this fetch takes, in bytes; None takes none (`max_bytes` is then the page cap)


def pdf_limit(ctx, reader=None):
    """The largest PDF, in bytes, that this run takes, or None: the plan's `pdf_max_mb` when it is above 0 **and the memory of a tool can be read here** (the sandbox would not run a tool that has a limit of
    memory otherwise, so a PDF could not be converted safely); where it cannot, PDFs are off for the run and one line of the log says so. Decided once for a context (`ctx.pdf_bytes`); with `pdf_max_mb` at 0 the memory
    is not looked at and nothing is logged. `reader` is `convert_run.read_group_rss` unless a test gives another."""
    if hasattr(ctx, "pdf_bytes"):
        return ctx.pdf_bytes
    mb = ctx.plan.get("pdf_max_mb", 0)
    ctx.pdf_bytes = None
    if type(mb) is not int or mb <= 0:
        return None
    try:
        (reader or convert_run.read_group_rss)(os.getpgrp())
    except Exception:
        ctx.log.write("fetch", "skipped", reason=PDFS_OFF, now=ctx.clock())
        return None
    ctx.pdf_bytes = mb * MIB
    return ctx.pdf_bytes


def _refuse(message):
    return KbError(f"the policy of a fetch: {message}")


def _number(plan, key):
    value = plan.get(key)
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise _refuse(f"{key} is a number of seconds, not below zero")
    return value


def build(plan, matcher, suffixes, index_root, *, pacer=None, log=None, warn=None, now=None, pdf_bytes=None):
    """The `FetchPolicy` for the approved `plan` (a dictionary of the crawl plan's keys), the `matcher` and the Public Suffix List (a set of rules; none is said loudly: `warn(text)` is called and `log` gets a
    `list_update` line `failed`, and the policy then finds a registrable domain by the last two labels). `pacer` replaces the shared one (tests). **`pdf_bytes`**, a whole number of bytes (see `pdf_limit`), makes the policy take
    `application/pdf` as well and raises the cap of a request to the larger of the page cap and `pdf_bytes`; with none, a PDF is not taken."""
    if pdf_bytes is not None and (type(pdf_bytes) is not int or pdf_bytes < 1):
        raise _refuse("a PDF limit is a whole number of bytes, at least 1")
    if matcher is None:
        raise _refuse("it needs the matcher of the lists step")
    agent = {"browser": BROWSER_AGENT, "generic": webclient.GENERIC_USER_AGENT}.get(plan.get("user_agent")) if isinstance(plan.get("user_agent"), str) else None
    if agent is None:
        raise _refuse("user_agent is browser or generic")
    gap, jitter = _number(plan, "min_gap_s"), _number(plan, "jitter")
    total = plan.get("fetch_timeout_s")
    if type(total) is not int or total < 1:
        raise _refuse("fetch_timeout_s is a whole number of seconds, at least 1")
    if not suffixes:
        text = "the Public Suffix List is not in use: the registrable domain of a site is taken as its last two labels, so the pacing and the per-domain limits are less exact"
        if warn is not None:
            warn(text)
        if log is not None:
            log.write("list_update", "failed", reason=log.safe(text), now=now)
        suffixes = None
    policy = webclient.Policy(user_agent=agent, gap=gap, jitter=jitter, max_redirects=capture_url.MAX_REDIRECTS, follow_redirects=True, types=capture_url.PAGE_TYPES,
                              check=crawllists.address_hook(index_root, matcher), allow_private=False, suffixes=suffixes, pacer=pacer)
    if pdf_bytes:
        policy.types = capture_url.PAGE_TYPES + ("application/pdf",)
    return FetchPolicy(policy, max(PAGE_MAX_BYTES, pdf_bytes) if pdf_bytes else PAGE_MAX_BYTES, min(capture_url.TIMEOUT, total), total, pdf_bytes)


DEFERRED = {"the site is stopped for the day": "the site it leads to is stopped for the day", "the site is at its limit for the day": "the site it leads to is at its limit for the day"}


def _blocked(text):
    for said, reason in DEFERRED.items():
        if text == "refused: " + said:
            return Outcome("deferred", reason, True)
    if "the stop file" in text:
        return Outcome("stopped", "the stop file is present", True)
    if "owner" in text:
        return Outcome("blocked", "blocked by the owner's blacklist", False)
    if "list:" in text:
        return Outcome("blocked", "blocked by a public list", False)
    if "unusable" in text:
        return Outcome("blocked", "the address is not usable", False)
    return Outcome("blocked", "the address is not allowed", False)


def classify(error):
    """What a failed fetch was: `Outcome(kind, reason, retry)`. `kind` is `blocked`, `stopped`, `deferred` (a redirect led to a site that is stopped or at its limit for the day: a try for later, not a failure), `refused`, `rejected` or `failed`; `reason` is a fixed text; `retry` says whether the same candidate may be tried
    again (a failure and a stop, yes; the others, no). An error that is not a fetch error is raised again."""
    if not isinstance(error, capture_url.FetchError):
        raise error
    text = str(error)
    if isinstance(error, webclient.Refused):
        # every test below is of the start of one of the client's own fixed messages, or the whole of it: a text a server can put into a message (a content type, an encoding) is never searched
        if text.startswith("refused: "):
            return _blocked(text)
        if text == "the response says it is a PDF but does not start like one":
            return Outcome("rejected", NOT_A_PDF, False)
        if text == "not an expected type: its content type is application/pdf":
            return Outcome("rejected", PDF_REASON, False)
        if text.startswith("not an expected type: ") or text == "the response has no Content-Type" or text.startswith("the response says it is "):
            return Outcome("rejected", "not a web page", False)
        if text.startswith("too many redirects") or text == "a redirect with no usable Location was refused":
            return Outcome("failed", "a redirect was refused", True)
        if text == "the address check failed, so the request was not made":
            return Outcome("failed", "the address check failed", True)
        return Outcome("blocked", "the address is not allowed", False)
    if text.startswith("HTTP "):
        digits = text[5:]
        if digits.isdigit() and len(digits) == 3:
            status = int(digits)
            if status in SITE_REFUSALS:
                return Outcome("refused", f"the site refused (HTTP {status})", False)
            return Outcome("failed", f"HTTP {status}", True)
    if text == "the response says it is a PDF but does not begin with %PDF-":
        return Outcome("rejected", NOT_A_PDF, False)
    if text.startswith("the response is larger than ") or text.startswith("the page is larger than "):
        return Outcome("rejected", "over the size limit", False)
    if text == "the response looks like binary or compressed data, not a web page":
        return Outcome("rejected", "not a web page", False)
    return Outcome("failed", "timed out" if text.startswith("timed out") else "the fetch failed", True)


# ---- the `fetch` step

STOPPED = "the stop file is present"
WHY_ENDED = {"fetches_per_day": "fetches_per_day reached: no new candidates today", "filed_total": "filed_total reached: no new books", "batch": "the batch of this run is taken",
             "nothing_queued": "nothing is queued that can be taken now"}
ALREADY_HELD = "already held"


def _arxiv_id(address):
    """The id of the paper that a canonical address names (`webaddr.identity_key` reads it: the hosts `arxiv.org`, `www.arxiv.org` and `export.arxiv.org`, an `/abs/` or `/pdf/` path, a legacy id with a slash, a version and a
    final `.pdf` that it drops), or `None` when the address is not a paper's. The version is dropped on purpose: the crawl takes the latest. It makes no request."""
    try:
        key = webaddr.identity_key(address)
    except KbError:
        return None
    paper = key[6:] if key.startswith("arxiv:") else None
    return paper if paper is not None and len(paper) <= MAX_ARXIV_ID else None        # a legacy id has no length of its own: a long one is junk, and would be sent to arXiv, kept as a key and tried again


def _path_is_pdf(address):
    try:
        return urlsplit(address).path.lower().endswith(".pdf")
    except ValueError:
        return False


def _crawl_found(events):
    return next((e for e in events if isinstance(e, dict) and e.get("event") == "crawl_found"), None)


class _Run:
    """One run of the step: the context, the library, the policy and the counts."""

    def __init__(self, ctx, fp, library, ident, capture, scan, capture_paper=None):
        self.ctx, self.fp, self.library, self.ident, self.capture = ctx, fp, library, ident, capture
        self.capture_paper = capture_paper or capture_arxiv.capture
        self.filed = crawlbooks.filed_count(library, scan)
        self.orphans = set(scan.orphans)
        self.state, _restarted = crawlguard.load_state(ctx.index_root)
        self.counts = {}
        self.hop = None

    def now(self):
        return self.ctx.clock()

    def say(self, outcome, row, reason=None, book=None, step="fetch"):
        log = self.ctx.log
        self.ctx.log.write(step, outcome, candidate=row["id"], host=log.safe(row["domain"], "host"), book=book, reason=log.safe(reason), now=self.now())
        if step == "fetch":
            self.counts[outcome] = self.counts.get(outcome, 0) + 1

    def finish(self, row, status, reason, book=None, refusal=False, count=True):
        crawlstate.finish(self.ctx.conn, self.ctx.plan, row["id"], status, reason, book, self.now(), refusal=refusal, run=self.ctx.run, count=count)

    def note(self, ok):
        """Give one fetch that made a request to the breaker; a trip is the run's end."""
        tripped = crawlguard.record_fetch(self.state, ok, self.ctx.plan)
        crawlguard.save_state(self.ctx.index_root, self.state)
        if tripped is not None:
            self.ctx.trip(*tripped)
            raise crawlrun.BreakerTripped()

    def adopt(self, row, book):
        """Give a book that was filed or found held its `crawl_found` for this candidate: `"new"` (a book the crawl has not counted), `"counted"` (an orphan or a book of this candidate), or `None` (not ours)."""
        root = self.library.read_book(book)
        events = self.library.read_events(book)
        found = _crawl_found(events)
        if root.get("auto_filed") is not True:
            return None
        if found is not None:
            return "counted" if found.get("candidate") == row["id"] and root.get("state") == "active" else None
        weeded = root.get("state") == "weeded"
        if root.get("state") != "active" and not (weeded and any(e.get("event") == "capture_failed" for e in events)):
            return None
        if weeded:
            self.library.set_state(book, "active")               # a retry of a failed capture that worked: the book is the one the failed try made
        crawlbooks.record_found(self.library, book, candidate=row["id"], source=row["source"], found_from=row["found_from"], topic=row["topic"], run=self.ctx.run, plan_digest=self.ctx.plan_digest)
        return "counted" if book in self.orphans else "new"

    def drop(self, book, reason):
        """A capture that failed: the book it made (if it made one) is not active and not the crawl's."""
        root = self.library.read_book(book)
        if root.get("auto_filed") is True and root.get("state") == "active" and _crawl_found(self.library.read_events(book)) is None:
            self.library.append_event(book, "capture_failed", reason=reason, run=self.ctx.run)      # the event first, as `crawlbooks.weed` does: a death between the two leaves an active orphan that the next sweep finishes
            self.library.set_state(book, "weeded")

    def outcome(self, row, out, book=None):
        """The end of a try that failed, was refused or was rejected, from `classify`: the row and the log. (A stop leaves the next turn of the loop to end the batch: it looks at the stop file first.)"""
        if out.kind in ("blocked", "rejected"):
            self.finish(row, "rejected", out.reason, book)
            self.say(out.kind, row, out.reason, book)
        elif out.kind == "deferred":
            self.finish(row, "failed", out.reason, refusal=True, count=False)         # a hop put off for a site that is stopped or at its limit: its try is counted, it waits a day (the site's day will have ended) and no site is charged
            self.say("skipped", row, out.reason)
        elif out.kind == "stopped":
            self.finish(row, "failed", out.reason)
            self.say("skipped", row, out.reason)
        elif out.kind == "refused":
            answered_by_another = self.hop is not None and self.hop["last"] != self.hop["first"]
            self.finish(row, "failed", out.reason, refusal=True, count=not answered_by_another)         # the row still waits a day; its own site is charged only when it was its own site that refused
            self.say("refused", row, out.reason)
            if answered_by_another:
                crawlstate.note_refusal(self.ctx.conn, self.ctx.plan, self.now(), self.hop["last"])      # the site that answered the refusal is charged, and not the one that led to it
        else:
            self.finish(row, "failed", out.reason)
            self.say("failed", row, out.reason)
            self.note(False)

    def one(self, row):
        """Take one candidate through the capture."""
        if self.fp.pdf_bytes is None and (row["source"] == "arxiv" or _path_is_pdf(row["address"])):
            return self.outcome(row, Outcome("rejected", PDF_REASON, False))
        try:
            address = webaddr.canon_address(row["address"])
        except KbError:
            return self.outcome(row, Outcome("rejected", "the address is not usable", False))
        owner = self.ident.lookup("url", address)
        if owner and self._owners(owner):
            self.finish(row, "rejected", ALREADY_HELD, owner)
            self.say("rejected", row, ALREADY_HELD, owner)
            return
        paper = _arxiv_id(address)
        if paper is None and row["source"] == "arxiv":
            return self.outcome(row, Outcome("rejected", "the address is not usable", False))
        if paper is not None:
            if self.fp.pdf_bytes is None:
                return self.outcome(row, Outcome("rejected", PDF_REASON, False))
            owner = self.ident.lookup("arxiv", paper)
            if owner and not self._adoptable(owner, row["id"]):                  # a book that `adopt` would refuse (the owner's, one the crawl has counted, one weeded by someone else): no request is made for it, since the capture would write a newer version into it
                self.finish(row, "rejected", ALREADY_HELD, owner)
                self.say("rejected", row, ALREADY_HELD, owner)
                return
        try:
            if paper is not None:
                result = self.capture_paper(self.library, self.ident, paper, policy=self._policy(), max_bytes=min(self.fp.pdf_bytes, capture_arxiv.PDF_MAX_BYTES), timeout=self.fp.timeout,
                                            total_timeout=self.fp.total_timeout, auto_filed=True)
            else:
                more = {"pdf_max_bytes": self.fp.pdf_bytes, "page_max_bytes": PAGE_MAX_BYTES} if self.fp.pdf_bytes else {}       # with no PDF limit the capture is called exactly as before
                result = self.capture(self.library, self.ident, address, policy=self._policy(), types=self.fp.policy.types, auto_filed=True, max_bytes=self.fp.max_bytes,
                                      timeout=self.fp.timeout, total_timeout=self.fp.total_timeout, **more)
        except webclient.Refused as e:
            return self.outcome(row, classify(e))
        status, book = result["status"], result["book_id"]
        if status == "duplicate":
            self.finish(row, "rejected", ALREADY_HELD, book)
            self.say("rejected", row, ALREADY_HELD, book)
            self.note(True)
        elif status == "failed":
            out = classify(capture_url.FetchError(result.get("reason") or ""))
            self.drop(book, out.reason)
            self.outcome(row, out)
        else:
            adopted = self.adopt(row, book)
            if adopted is None:
                self.finish(row, "rejected", ALREADY_HELD, book)
                self.say("rejected", row, ALREADY_HELD, book)
                return
            self.finish(row, "kept", None, book)
            if adopted == "new":
                self.filed += 1
            if status == "filed":
                self.say("ok", row, None, book, step="capture")
            self.say("ok", row, None if status == "filed" else "the book of an earlier try", book)
            if status == "filed":
                self.note(True)

    def _policy(self):
        """The policy of this candidate: the shared one, with a hook that also takes a unit of the day of each site a redirect leads to (the first site's units were taken by `reserve`) and refuses a site that is stopped
        or at its limit, so that redirectors cannot aim requests at one site past its limits. **A site is counted once for a candidate, however many requests it makes to it** (a DOI address goes to a publisher
        and on inside it: one paper, one visit): the sites already counted are kept in `self.hop`, which also says the first and the latest site, for the charge of a refusal."""
        own = copy.copy(self.fp.policy)
        base, suffixes = self.fp.policy.check, self.fp.policy.suffixes
        hop = self.hop = {"first": None, "last": None, "counted": set()}

        def check(address):
            why = base(address)
            if why:
                return why
            site = webaddr.site_of(urlsplit(address).hostname or "", suffixes)
            hop["last"] = site
            if hop["first"] is None:
                hop["first"] = site
                return None
            if site != hop["first"] and site not in hop["counted"]:
                try:
                    why = crawlstate.charge_hop(self.ctx.conn, self.ctx.plan, self.now(), site)
                except KbError:
                    return "the site of that address is unusable"          # a literal address or a name the counters cannot hold: a block, not a failure
                if why:
                    return why
                hop["counted"].add(site)                                      # (a refused hop is not counted, and ends the fetch)
            return None

        own.check = check
        return own

    def _adoptable(self, book, candidate):
        """True if a book that holds the key of a paper may go to the capture: it is the crawl's own (`auto_filed`) and `adopt` would take it: it has no `crawl_found` and is active, or is weeded after a failed capture of the crawl's, or it is the active book that this candidate was already counted for (a death after the event and before the row was finished: the capture says `held` and the row is kept); or it cannot be read (a stale entry of the index, which the capture handles)."""
        try:
            root = self.library.read_book(book)
            if root.get("auto_filed") is not True:
                return False
            events = self.library.read_events(book)
        except KbError:
            return True
        found = _crawl_found(events)
        if found is not None:
            return found.get("candidate") == candidate and root.get("state") == "active"
        return root.get("state") == "active" or (root.get("state") == "weeded" and any(e.get("event") == "capture_failed" for e in events))

    def _owners(self, book):
        """True if the address names a book that exists and is not the crawl's (a book of the owner's: nothing here fetches into it)."""
        try:
            return self.library.read_book(book).get("auto_filed") is not True
        except KbError:
            return False


def make_step(capture=None, open_store=None, statvfs=None, rss_reader=None, capture_paper=None):
    """The function for the `fetch` point. `capture`, `open_store`, `statvfs`, `rss_reader` (the reader of the memory of a process group, for `pdf_limit`) and `capture_paper` (the capture of an arXiv paper) replace the real ones (tests)."""

    def step(ctx):
        if not isinstance(getattr(ctx, "plan_digest", None), str):
            raise crawlrun.StepRefused("the fetch needs the digest of the approved plan")
        try:
            fp = build(ctx.plan, ctx.matcher, ctx.suffixes, ctx.index_root, log=ctx.log, now=ctx.clock(), pdf_bytes=pdf_limit(ctx, rss_reader))
        except KbError as e:
            raise crawlrun.StepRefused(str(e)) from None
        library = (open_store or library_store.Store.open)()
        _sweep(ctx, library)
        run = _Run(ctx, fp, library, identity.Identity(ctx.index_root), capture or capture_url.capture, crawlbooks.scan_crawl_books(library), capture_paper)
        ended = "the step failed"
        try:
            ended = _loop(ctx, run, statvfs or os.statvfs)
        except crawlrun.BreakerTripped:
            ended = "the circuit breaker was tripped"
            raise
        finally:
            ctx.fetch_report = dict(run.counts, filed=run.filed, ended=ended)
            ctx.log.write("fetch", "skipped", reason=ctx.log.safe(ended), n=sum(run.counts.values()), now=ctx.clock())

    return step


def _sweep(ctx, library):
    """Finish what a death left: an active `auto_filed` book with no `crawl_found` whose fetch never worked (it has no version, or its `fetched` stage is not done) is weeded as a failed capture, so that it is not
    counted for ever and no later step meets a book with no payload. A retry of its address revives it. An orphan whose payload was filed is left for the capture to adopt."""
    for book in crawlbooks.scan_crawl_books(library).orphans:
        version = library.read_book(book).get("current_version")
        if version and stages.read(library, book, version)["stages"]["fetched"]["status"] in ("done", "skipped"):
            continue
        library.append_event(book, "capture_failed", reason="the capture did not finish", run=ctx.run)
        library.set_state(book, "weeded")


def _loop(ctx, run, statvfs):
    while True:
        if crawlguard.stop_requested(ctx.index_root):
            return STOPPED
        if crawlrun.spent(ctx):
            return "the time budget of the run is spent"
        try:
            crawlguard.check_disk(ctx.cfg["bulk_root"], ctx.index_root, ctx.plan, statvfs=statvfs)
        except KbError as e:
            return f"the disk floor refuses a fetch: {e}"
        row, why = crawlstate.reserve(ctx.conn, ctx.plan, ctx.clock(), ctx.run, run.filed)
        if row is None:
            return WHY_ENDED.get(why, why)
        run.one(row)


step = make_step()
