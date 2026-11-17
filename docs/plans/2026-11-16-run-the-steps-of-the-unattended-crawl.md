# Run the steps of the unattended crawl: lists, refill, fetch, scan, convert, judge, card, proposal and move

Status: In Progress
Created: 2026-11-16
Candidate: none (no roadmap holds a candidate for it: the crawl is specified in `docs/specs/population.md`, which the owner approved as the design to build; adding a candidate is the owner's own change of direction)
Specs: docs/specs/population.md, docs/specs/pipeline.md, docs/specs/shelf.md

## Goal

The guard rails and the skeleton of `crawl-run` are built and closed (`docs/plans/2026-11-16-build-the-safeguards-of-the-unattended-crawl.md`, plan R1): the approval, the log, the stop file, the breaker, the ceilings, the checks in the spec's order, and four **points** (`lists`, `earlier_work`, `refill`, `fetch`) where a step attaches. This plan **attaches the steps**, so that a run takes candidates from the queue to books on shelves, in small bounded batches, with no one at the keyboard: refresh the public lists, finish the earlier work of books already held, refill the queue by discovery, fetch new candidates, scan, hold, convert, index, judge, make cards, propose a shelf and move the book by the model's pick. It also first closes the findings of the security review of R1 that a step would make reachable.

When it is done:

- every finding of the R1 security review that matters before a step exists is closed and tested: bytecode that is not in the fingerprint is never read, a step reads the approved copies and not the owner's live files, the digest the owner confirms covers the code, a step cannot clear the breaker, a failed log write does not corrupt the next line;
- a run, on a temporary library with fake sources and a fake model server, takes a fixture candidate through every step to a `reshelved` line with `via: crawl`, and every step has its log line and its guards (the stop file between requests, model calls and moves; the disk floors before a fetch, a conversion and a card pass; the ceilings; the breaker);
- every failure path of a step ends in a state a later run can resume or in a final one that the report can name: nothing is fetched or judged twice, a failed capture leaves no active book, a held book is not converted, a judged-out book is kept as `weeded`, a book that no step can finish is parked after `retries` tries;
- the move touches only the crawl's own books, and the 172 unanswered proposals and every other book on `default` are untouched (tested);
- `crawl-run` can be scheduled every 15 minutes by a launchd file that the owner installs (this plan writes the file's text, never installs it) and that makes the engine ignore its own bytecode cache.

This plan does **not** start the crawl. The first run on the owner's library is the supervised run of the spec (acceptance criterion 18), the owner's act, after this plan is done and read.

## Scope

**Files owned by this plan:**

- New: `engine/kb/crawlbooks.py` (the crawl's events and the readers of its books), `engine/kb/crawllists.py` (the `lists` step), `engine/kb/crawlrefill.py` (the `refill` step), `engine/kb/crawlfetch.py` (the policy of a fetch and the `fetch` step: capture of a candidate as a book), `engine/kb/crawlsteps.py` (scan and hold, convert and index, as steps over a book), `engine/kb/crawljudge.py` (the judgement), `engine/kb/crawlcards.py` (the card step), `engine/kb/crawlmove.py` (the proposal step and the move), `engine/kb/crawlschedule.py` (the text of the launchd file), and a test file for each in `engine/tests/` with hand-made fixtures under `engine/tests/fixtures/crawl/`.
- Changed, narrowly: `engine/kb/crawlapprove.py`, `crawlguard.py`, `crawllog.py`, `crawlstate.py`, `crawlrun.py` (the R1 modules: the hardening, one new row transition, the assembly of the steps); `engine/kb/__main__.py` (the registration of one command that prints the launchd text, in the block of the crawl's commands; the plan that builds `crawl-status` and `crawl-report` on another machine registers its own commands in the same file); `engine/kb/placement.py` and `engine/kb/placereview.py` (their private helpers that the spec names, made public, with no change of behaviour); `README.md` (the commands, the scheduler and the checklist of the supervised run).

**Not changed:** `engine/kb/crawlqueue.py` (discovery's: no `UPDATE`, no `DELETE`; every change of a row's state is made in `crawlstate.py`), `discover.py` and the `src*.py` sources except through the calls they already take, `webclient.py`, `webaddr.py`, `weblists.py`, `urlhaus.py`, `capture_url.py` and `capture_arxiv.py` (plan F's: used through their arguments; a narrow change to one of them is named in the increment that needs it and needs the owner's word first), and the sandbox and the tools' limits (plan T).

## Non-goals

- Taking **PDFs**. The spec forbids it until the sandbox has limits on memory, processes and decompression (plan T). Until then a candidate whose type is a PDF is `rejected: pdf not safe to convert` and counted, and the crawl takes web pages only (Wikipedia and the landing pages that OpenAlex gives). A candidate from the arXiv source is a PDF and is rejected the same way until plan T is done; turning PDFs on is plan T's change, tested there.
- `crawl-status` and `crawl-report` (another plan, built on another machine) and the scheduler's installation (the owner's act).
- Seeding, scouts and shelf entries (designed in the spec, not built in the first version), the measurement of the judgement's rule (`judge-1`), and any change to what `docs/specs/population.md` says about direction.
- The supervised run on the owner's library.

## Assumptions and constraints

- The spec's text on "The order of one run", capture, scan flags, the judgement, cards and the proposal, the move, the safeguards and scheduling, and the acceptance criteria 1, 3 to 7, 9, 13, 16 and 17, is the specification; where this plan is silent, the spec governs. R1's closed plan (`Interfaces the other plans build against`) is the contract of the files and counters the steps use; this plan keeps it and changes nothing in it except where an increment says so and the owner approves.
- **Tests use a temporary library and index root, a fake source and page server (a function that is passed in), a fake model server, an injected clock, free-space reading and probe.** No test makes a real request, calls a real model, reads the owner's config, plan or key, or touches the owner's library. A step's guards are tested with a spy on each guard so that "not made after a refusal" is shown, as R1's `test_crawlrun` does.
- **Every step is idempotent** and resumes: the state of a book is what its stage file and its events say (`stages.read`), never what a run remembers. A step that finds its work done does nothing and logs `skipped`.
- **The terminal events of a crawl book** are `crawl_rejected`, `crawl_held`, `reshelved` and `crawl_unplaced` (the last is new: a book whose proposal is `none`, malformed or an error stays on `default` and is named in the report; without a terminal event the next run would try again for ever). A book with `crawl_found` and none of these is unfinished work for `earlier_work`.
- **A try that fails** is recorded as an event `crawl_step_failed` (`step`, `reason`, `run`); at the plan's `retries` such failures of one step the book is weeded with `crawl_rejected` (its `stage` names the step), which is a terminal event, so that a page that kills the converter, or a book the card queue cannot finish, is **parked** and does not loop (the spec's acceptance criterion 5). "Parked" means exactly this in every increment below: weeded, terminal, named in the report, never selected by `crawl_books` again.
- **A crawl book is one the runner may act on only if its `crawl_found` event carries the digest of an approved plan** (the spec's "The move"). Approved plans are kept under `crawl/approved/<digest>/` (R1); `approved_digests(index_root)` lists the digests whose folder reads strictly as R1's `load_approved` reads one. A `crawl_found` whose digest is missing, malformed or not in that list is not acted on by any step.
- **The judgement is built here** (`crawljudge.py`), not by the other machine's "Brief 2": the rule is the spec's (a real document of at least `min_chars`, and the best match among the home shelves reaching `threshold`, using the title and the first 1,500 characters embedded by the existing embedding entry against `shelf-vectors`), and the interface is small so that a better judge can replace it: `judge(store, cfg, plan, book_id, version_id, embed=None)` returns `(ok, score, shelf, reason)`. *For the owner:* if you would rather the other machine builds it, say so; Increment J then becomes a call of its function.
- The scheduler command is `python3 -X pycache_prefix=<a private empty folder> -m kb crawl-run`, so that the tree's own `__pycache__` is never read (finding F1 of the R1 security review). `crawl-run` refuses unless the prefix is set.
- Method (as R1): tests first and seen to fail, deliberate breaks of each new module with bytecode caching off (each compile-checked, the file restored byte for byte, equivalent breaks dropped with the reason), the `reviewer` agent's reading of each increment, the Result recorded before the commit, a commit on the owner's word. **A `security-reviewer` run with experiments on a copy is asked of the owner after Increments G, H and I (hostile pages reach the parser, the scanner and the converter) and after L (the move changes the library)**, and a second look at any fixes.

## Completion criteria

1. **Hardening.** `crawl-run` refuses (exit 3, one `refuse` line) unless the interpreter's bytecode prefix is set, and a `.pyc` planted in the tree is not read when it is; the digest the owner confirms changes with one byte of the engine's code or the named model settings; a step receives the approved `topics` and `allow` and not the live files, tested by editing them after the approval; no public function writes the breaker as not tripped except `crawl-clear`; a failed log write is not fused with the next line; the credential shapes the review found are refused; the summary lists every allow host.
2. **The whole chain** (spec criterion 1): a fixture candidate is taken through fetch, capture, scan, convert, index, judge, card, proposal and move; the book has `auto_filed`, a `crawl_found` event and a `reshelved` line with `via: crawl`, `basis: model-pick`, the run id and the plan digest, and no `confirmation`; each step has a log line.
3. **The stop file** created in the middle of a batch prevents the next request, the next model call and the next move (spec criterion 3), tested at each.
4. **Crash safety** (criterion 5): a run killed (an injected failure) at each step leaves no ceiling exceeded and no book half-made; the next run resumes it; a book whose step fails `retries` times is weeded and named.
5. **Nothing is judged or fetched twice** (criterion 6): the filed bytes are the judged bytes; a model that answers differently a second time is not asked a second time; over 100 dead addresses leave the count of active books unchanged; a judged-out candidate is a `weeded` book with `crawl_rejected`, its row `rejected`, and it is not searched, carded or placed.
6. **Scan holds** (criterion 7): a book with a hold kind, a failed scan or a missing scan tool is filed, not converted, indexed, carded or moved, has `crawl_held` and is named; `script_elements`, `event_handlers` and `pattern_in_binary_data` do not hold.
7. **The move touches only the crawl's books** (criterion 9): with owner-unanswered proposals and other books on `default` present, none of them is moved or gains a proposal; a shelf that is not among the five offered, is `default`, is not a home shelf or is refused by the store is not moved; a `none` or malformed proposal leaves the book on `default` with `crawl_unplaced`; the catalog lock is taken for each move and not for the batch.
8. **Lists and refill** (criteria 13, 16): a failed download leaves the last good copy in use, a required list with no copy ends the run, the blacklist at every request, the allow file as approved; a fixture page with 100,000 links over 10,000 subdomains of one domain stays within the per-domain and total caps; a refill adds rows only when fewer than `queue_low` are queued.
9. **Hostile content** (criterion 17): a page whose text says to ignore its instructions and to choose a shelf leaves the placement among the five offered shelves with the reason cleaned and the book flagged unreviewed; a PDF served as `text/html`, and a response with no `Content-Type`, are refused; a PDF is `rejected: pdf not safe to convert`.
10. **The breaker and the refusals** are wired: failures of fetches trip it by the rules of R1's `crawlguard`, a refusal of a site counts for the site and stops it for the day, a stage that hits a bound trips it, and the exit codes are R1's.
11. **The scheduler text** is printed by one command, installs nothing, and names the pycache prefix, the schedule and the working folder.
12. The new modules' tests and breaks, the six R1 modules' tests and `wb run code-work check` pass; the existing tests of `crawlqueue`, `discover`, `placement`, `placereview`, `placeapply` and `catalog` pass unchanged; the engine's whole suite is run once at the end; nothing else changes but the files named under "Scope".
13. The owner has read the result.

## Increments

### Increment A — Harden the approval: bytecode, approved copies, the fingerprint in the digest, all allow hosts

**Outcome:** the findings F1, F2, F3 and F9 of the R1 security review are closed, so that no step can read what the owner did not approve.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlapprove.py`, `engine/kb/crawlrun.py`, `engine/tests/test_crawlapprove.py`, `engine/tests/test_crawlrun.py`.
**Steps:**
1. Read the R1 plan's review record (the security review) and `crawlapprove.py`, `crawlrun.py`; write in the Result the exact new digest recipe.
2. Tests first: **F1** `crawl-run` refuses (exit 3, one `refuse` line, reason names the prefix) when `sys.pycache_prefix` is not set, and the dry run says so; a child process started with `-X pycache_prefix=<dir>` does not run a `.pyc` planted in `engine/kb/__pycache__` over unchanged source, and one started without it does (the test shows the danger it closes). **F3** `load_approved` returns a plan whose `topics` and `allow` are the approved copies; the live files edited after the approval are not read by a reader of the plan. **F2** the digest covers the full fingerprint (a framed part after the three files): one byte of the code or of a named model setting between the preview and `--digest` refuses and says the code changed since the summary was read; an approval made under R1's recipe is refused and says to approve again. **F9** the summary lists every allow host, one a line, and a file of over 500 hosts is refused for approval with a plain reason.
3. Write the changes; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlapprove engine.tests.test_crawlrun engine.tests.test_crawlguard engine.tests.test_crawlplan`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-run-the-steps-of-the-unattended-crawl#A`.

### Increment B — Harden the guards and the log: a private breaker writer, a repaired log line, the credential shapes, the key as a secret

**Outcome:** findings F5, F6 and F7 are closed; a step cannot clear the breaker, a log line cannot be fused with a torn one, and a credential in the shapes the review found is never logged.
**Dependencies:** A.
**Affected areas:** `engine/kb/crawlguard.py`, `engine/kb/crawllog.py`, `engine/kb/crawlrun.py`, their tests.
**Steps:**
1. Read `crawlguard.py` (`write_breaker`, `trip`, `clear`), `crawllog.py` (`Log.write`, `_HEADER`, `_LONG`) and the review record.
2. Tests first: **F5** the only public functions that write `crawl/breaker.json` are `trip` (to tripped) and `clear` (to not tripped, with `--yes` at a terminal); no other public name writes it as not tripped (a test of the module's names); the runner remembers that a run tripped and ends with exit 4 whatever a step does afterwards. **F6** a log file that does not end in a line feed gets one before the next record, in the same single write, and the repaired line is whole; a short write is still an error. **F7** the shapes the review found (`secret_key=`, `access_key=`, `private_key=`, `Basic <base64>`, a URL with `user:pass@`, `?key=` and `?sig=`, a JWT, an AWS-style id, a 40-character non-hexadecimal run) are refused, ordinary text with the same words is not; `crawlrun.run` takes the secrets of the run (the key it loaded, none yet) and gives them to its `Log` and to `trip`'s screening; a refusal of the log for a hostile page's text does not abort the run but is logged with a fixed reason (a function `safe_reason` for the steps).
3. Write the changes; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlguard engine.tests.test_crawllog engine.tests.test_crawlrun engine.tests.test_crawlapprove`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — The crawl's books: events, readers, the failed-step count and the one new row transition

**Outcome:** one module says what a crawl book's state is, so that every later step is idempotent; and the rows can say a kept candidate was later rejected.
**Dependencies:** B.
**Affected areas:** `engine/kb/crawlbooks.py`, `engine/kb/crawlstate.py`, `engine/tests/test_crawlbooks.py`, `engine/tests/test_crawlstate.py`.
**Steps:**
1. Read `store.py` (`create_book` with `auto_filed`, `set_state`, `append_event`, `read_events`), `stages.py`, and the spec's events; write in the Result the exact fields of each event: `crawl_found` (`candidate`, `source`, `found_from`, `topic`, `run`, `plan_digest`), `crawl_held` (`kinds`), `crawl_rejected` (`reason`, `score`, `stage`), `crawl_unplaced` (`reason`), `crawl_step_failed` (`step`, `reason`, `run`), `crawl_judged` (`score`, `shelf`, `ok`) and the existing `reshelved`.
2. Tests first, on a temporary store: writers that refuse missing or wrong fields and clean text; `approved_digests(index_root)` returns the digests whose approved folder reads strictly (a link, a loose mode, an extra or missing file or a changed byte leaves it out); `crawl_books(store, approved)` returns the books with `crawl_found` whose `plan_digest` is in `approved` and no terminal event, in the order found, and never a book without `crawl_found` or with a missing, malformed or unapproved digest (those are returned only by a separate `unapproved_books` reader, which only `reconcile_unapproved` uses; the 172 owner proposals and every other book are never listed); **`reconcile_unapproved(store, approved, log)` is the one place such a book is dealt with: it appends `crawl_unplaced` once to a book with a `crawl_found` and an unapproved digest (a book with no `crawl_found` is never touched), writes one log line, and is idempotent; a test shows that it calls no model, no move, no proposal and no capture, and that a second call writes nothing**; a book parked by `retries` failures is weeded with `crawl_rejected` and so is never listed again; `filed_events(store)` gives `crawlstate.filed_total` its input; `step_failures(store, book_id, step)` counts; `weed(store, book_id, reason, score, stage)` sets the state `weeded` and writes `crawl_rejected` once (idempotent); at `retries` failures a step weeds the book; `crawlstate.reserve` takes `filed` as a required argument (the fail-open of R1's Increment E closed); `crawlstate.reject_kept(conn, plan, id, reason, now)` moves `kept` to `rejected` and nothing else, and the module still has no `DELETE`.
3. Write the module and the transition; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlbooks engine.tests.test_crawlstate engine.tests.test_crawlqueue engine.tests.test_store`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`.

### Increment D — The `lists` point: refresh the public lists and the key

**Outcome:** a run refreshes the lists that are due, and every later step has the matcher.
**Dependencies:** B, C.
**Affected areas:** `engine/kb/crawllists.py`, `engine/tests/test_crawllists.py`, `engine/kb/crawlrun.py`.
**Steps:**
1. Read `weblists.py` (`Matcher`, `update`, the defaults and floors), `urlhaus.py` (the key file and the rate limit), `webclient.py` (`Policy`, the download call) and the spec's "Public lists" and "A key is a credential"; write in the Result how a refresh is made and what the matcher gives the other steps.
2. Tests first, with fake downloads: nothing is requested when the lists are fresh (`refresh_hours`); a failed download keeps the last good copy and logs `list_update`/`failed`; a required list with no copy ends the run with a refusal; a list over its size limit, suddenly far smaller or changed by more than the allowed share is refused; the URLhaus key is read only from its file (mode 600, the owner's), goes only in the `Auth-Key` header, **over https, to its own host, in a request that follows no redirect**, is passed to the log as a secret, and no request is made without it; **a fake API that answers 302 to a second host shows that host no key, and the key is not sent again that day**; **a forced exception inside the request leaves the key in no error text, log line, report, model prompt, environment, command line or address**; on a refusal (a redirect included) or `X-RateLimit-Remaining` of zero no more requests to that service are made that day; the matcher keeps the rules above for the lists it loads (public host lists exact, URL lists exact URL, pinned hosts unblockable by them); the public suffix list is passed to the matcher (the todo of plan F); the blacklist is read afresh each run and the allow file is the approved copy.
3. Write the step and attach it at `lists`; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawllists engine.tests.test_crawlrun engine.tests.test_weblists engine.tests.test_urlhaus engine.tests.test_webclient`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`.

### Increment E — The `refill` point: discovery fills the queue

**Outcome:** a run asks discovery for candidates when fewer than `queue_low` are queued, within every bound.
**Dependencies:** D.
**Affected areas:** `engine/kb/crawlrefill.py`, `engine/tests/test_crawlrefill.py`, `engine/kb/crawlrun.py`.
**Steps:**
1. Read `discover.fill`, the `src*.py` sources and `crawlqueue.add`/`counts`, the plan's discovery keys and the spec's "Bounds against flooding"; write in the Result what `fill` is given (`get`, `chat`, `sources`, `is_blocked`, `canon_address`, `site_of`) and which of them the runner builds.
2. Tests first, with fake sources and a fake chat model: nothing is asked when `queue_low` or more rows are queued; the fetch function given to discovery is the shared client under the plan's gaps and the matcher; `crawl-query` model calls are made only through the configured entry and a failed model gives no rows, not a failure of the run; rows added are logged as `discover`, `enqueue` and `block` lines with counts and no address text beyond the host; the stop file is looked at between requests; a fixture page with 100,000 links over 10,000 subdomains of one domain adds rows only within `queued_total` and `queued_per_domain` and reads at most the plan's links from a page; an address over 2,048 characters is dropped.
3. Write the step and attach it at `refill`; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlrefill engine.tests.test_crawlrun engine.tests.test_discover engine.tests.test_crawlqueue`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#E`.

### Increment F — The policy of a fetch

**Outcome:** one function builds the client policy under which every candidate is fetched, from the approved plan and the lists.
**Dependencies:** D.
**Affected areas:** `engine/kb/crawlfetch.py` (the policy part), `engine/tests/test_crawlfetch.py`.
**Steps:**
1. Read `webclient.Policy` (its fields and its per-hop `check`), `capture_url.capture` (`policy`, `types`, `auto_filed`) and the spec's "Pacing, the type gate and the shared client"; write in the Result which of the spec's rules the policy already has and which this increment gives it. If a rule cannot be given through the policy's arguments (the stop file between the hops of one fetch), stop and ask the owner for a narrow change to `webclient.py`; do not widen the plan.
2. Tests first: the policy has the plan's user agent (`browser` or `generic`), pacing (`min_gap_s` with `jitter`; one request at a time to a registrable domain and to an address), the fetch timeout and the size limit, the matcher at every hop under the spec's separate rules (**the owner's blacklist** blocks a host and its subdomains and not a similar name; **a public host list** blocks that exact host only; **a URL list** blocks that canonical URL and not others on its host unless the host is a bare IP; **a pinned source host** is never blocked by a public list, only by the owner's blacklist; a canonical form such as `EVIL.com.` or an IDN host gives one key; each tested at the candidate, at a redirect hop and for an address found by discovery), **the connection guarantees of plan F kept, shown by tests through the shared client with a fake resolver and a fake socket: a host that resolves to a private, loopback, link-local or metadata address is refused at the first hop and at a redirect hop; an answer that changes between the check and the connect is harmless because the client connects to the address it checked; a connected peer that is not the checked address is refused; and the same client, with the same guarantees, is the one that capture, discovery and the list refresh use (each is shown to refuse a private address)**, the type gate (`text/html` and the page types only; a response with no `Content-Type`, or one that disagrees with a sniff, is refused; a PDF is refused with the reason `pdf not safe to convert`), ports 80 and 443 only, at most 5 redirects, and the stop file looked at before each request and each hop; a refusal of a site (403, 429, an abuse signal) is reported to the caller as a refusal and not as a failure.
3. Write the module; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_webclient engine.tests.test_capture_policy`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#F`.

### Increment G — The `fetch` point: take a candidate and capture it as a book

**Outcome:** a run reserves candidates up to `batch` and captures each as a book with its row, counters and events right.
**Dependencies:** C, F.
**Affected areas:** `engine/kb/crawlfetch.py`, `engine/tests/test_crawlfetch.py`, `engine/kb/crawlrun.py`.
**Steps:**
1. Read `capture_url.capture` and `capture_arxiv.capture` (what they create before they know the fetch worked), `crawlstate.reserve` and `finish`; write in the Result the exact order of one candidate: `reserve`, disk floor, stop file, capture with the policy and `auto_filed`, then `crawl_found`, then the row.
2. Tests first, with a fake page server: a filed page gives a book with `auto_filed`, `crawl_found` (with the plan digest), the row `kept` with its `book_id`, a `fetch` and a `capture` log line; a duplicate or a held address gives `rejected: already held` with the book's id; a failed capture leaves **no active book** (any book it made is `weeded` with `crawl_rejected` and the reason) and the row `failed` with a wait, and over 100 dead addresses leave the count of active books unchanged; a refusal of a site is `finish(..., refusal=True)` and counts for the site, and the site is skipped by the next `reserve` after `domain_refusals`; a candidate from the arXiv source, or any PDF, is `rejected: pdf not safe to convert` without a request where the source already says it is one; each fetch is passed to `record_fetch` and a trip ends the run with exit 4; the ceilings end new fetches and the later steps still run; the stop file between candidates ends the batch; a book is never fetched twice.
3. Write the step and attach it at `fetch`; deliberate breaks; the `reviewer`'s reading; the Result. **Ask the owner for a `security-reviewer` run** (pages from outside reach the capture).
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_crawlstate engine.tests.test_crawlbooks engine.tests.test_capture_url engine.tests.test_crawlrun`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#G`.

### Increment H — Scan and hold

**Outcome:** every crawl book is scanned before it is converted, and a hostile one is held.
**Dependencies:** C, G.
**Affected areas:** `engine/kb/crawlsteps.py`, `engine/tests/test_crawlsteps.py`.
**Steps:**
1. Read `scan.py` (`scan_version`), `scan_tool.py` (`KINDS`), `stages.py` and the spec's "Scan flags"; write in the Result how a scan's findings reach the stage file and which kinds the plan's `hold_kinds` names.
2. Tests first, with a fake scan tool: a book with no hold kind goes on; a book with a hold kind, a failed scan, a missing tool or a timeout is held (`crawl_held` with the kinds, a `hold` log line, not converted, indexed, carded or moved) and is terminal; `script_elements`, `event_handlers` and `pattern_in_binary_data` never hold; the step is idempotent (a scanned book is not scanned again); **a scan that fails is not retried: the book is held at once, as the spec says (fail closed), so there is no retry count for the scan** (the book is filed and named in the report; the owner may release it later); the disk floor and the stop file are looked at before the scan, and a refusal by either leaves the book unscanned for the next run and is not a hold.
3. Write the step; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlsteps engine.tests.test_scan engine.tests.test_stages`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#H`.

### Increment I — Convert and index

**Outcome:** a scanned, unheld book is converted and indexed under the guards.
**Dependencies:** H.
**Affected areas:** `engine/kb/crawlsteps.py`, `engine/tests/test_crawlsteps.py`.
**Steps:**
1. Read `process.py`, `convert.py` (`convert_version`), `convert_run.py`, `index.py` and `stages.py`; write in the Result which entry points run one stage of one book and what they refuse.
2. Tests first, with a fake converter: the step converts then indexes one book and marks the stages; the disk floors (bulk and index) are read before each conversion and each index write and a floor refuses it; the stop file is looked at before each; a converter that is killed or times out is a `crawl_step_failed` and at `retries` the book is weeded and its row `rejected` (the converter's death does not loop and does not trip the breaker by itself; a count of such weeds over a bound does, as a `stage_bound`); a converted text over the size limit, or too short, is refused with its reason; idempotent; a book that is not scanned or is held is never converted.
3. Write the step; deliberate breaks; the `reviewer`'s reading; the Result. **Ask the owner for a `security-reviewer` run** over G, H and I together (hostile input reaches the scanner and the converter).
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlsteps engine.tests.test_convert engine.tests.test_convert_run engine.tests.test_search engine.tests.test_stages` (the converter and the index have no tests of their own named for them; `test_search` is what reads the index); the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#I`.

### Increment J — The judgement

**Outcome:** a converted book is judged once, on the text that was filed, and kept or weeded.
**Dependencies:** C, I.
**Affected areas:** `engine/kb/crawljudge.py`, `engine/tests/test_crawljudge.py`, `engine/kb/crawlsteps.py`, `engine/kb/crawlstate.py` (only the call of `reject_kept`).
**Steps:**
1. Read `shelfvectors.py`, `shelfmatch.py`, `vectors.py`, `models.embed` and the spec's "The judgement"; write in the Result the exact rule and its numbers (`min_chars`, the 1,500 characters, `threshold`, the home shelves, the comparison).
2. Tests first, with a fake embedding entry and fixture shelf vectors: a text under `min_chars`, a menu, a login page and an error page are not real documents; a text whose best match among the home shelves is under `threshold` is rejected with the score and the shelf named; one at or over it is kept and its best shelf recorded (`crawl_judged`); the verdict is recorded once and a second call does not ask the model again (a model that answers differently the second time is not asked); the judged text is the converted text of the stored payload; a rejection weeds the book (`crawl_rejected` with the reason and the score, the files kept, not searched, carded or placed) and the row becomes `rejected` through `reject_kept`; a model that fails is a failed try and not a verdict, and at `retries` tries the book is parked (weeded with `crawl_rejected`, stage `judge`, terminal); the empty `threshold` refuses before any model call (R1 already refuses the run; the step refuses too); a `judge` log line each.
3. Write the module and the step; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawljudge engine.tests.test_crawlsteps engine.tests.test_crawlstate engine.tests.test_shelfvectors`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#J`.

### Increment K — Cards over the batch

**Outcome:** the kept books of a run are given cards, model by model, in bounded passes.
**Dependencies:** J.
**Affected areas:** `engine/kb/crawlcards.py`, `engine/tests/test_crawlcards.py`.
**Steps:**
1. Read `cardqueue.py` (`plan`, `run`, `PASS_CAP`, `status`), `cardstate.py`, `cardmake.py` and the spec's "Cards and the proposal run over the batch"; write in the Result what the queue plans, how a pass is bounded and what one call costs.
2. Tests first, with fake models: the step plans the queue **with the explicit ids of the books it is finishing** and never with no ids (a test that the ids are passed and that a library with other card-less books has none of them planned); each unit of `cards_per_day` is reserved with `reserve_card` before a book is given a card and none after the ceiling; the queue runs in bounded passes with the stop file and the disk floor looked at between passes; a model that fails is a failed try for the book, counted, and at `retries` the book is parked (weeded with `crawl_rejected`, stage `card`: a terminal event, so it is never planned into the queue again and is named in the report, tested by a second run that finds it neither in `crawl_books` nor in the explicit ids); a pass that reaches its bound without finishing trips the breaker as a `stage_bound`; the model server's failure feeds the down clock; the card text of a crawl book is data and flagged unreviewed; a `card` log line per book; idempotent.
3. Write the step; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlcards engine.tests.test_cardqueue engine.tests.test_cardstate engine.tests.test_crawlrun`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#K`.

### Increment L — The proposal and the move

**Outcome:** a carded crawl book gets a proposal and is moved by the model's pick, and nothing else is.
**Dependencies:** K.
**Affected areas:** `engine/kb/crawlmove.py`, `engine/kb/placement.py`, `engine/kb/placereview.py`, `engine/tests/test_crawlmove.py`, and the existing tests of those two modules.
**Steps:**
1. Read `placement.py` (`propose`, `select`, `describe`), `placereview.py` (`state_of`, `listing`), `placeapply.py` (the pattern of an apply), `store.set_shelf` and `catalog.lock` and the spec's "The move is a new path"; write in the Result which helpers are made public and the exact checks a proposal must pass.
2. Tests first: `place-propose` is called with the explicit ids of the crawl books and with no ids never (a library with 172 unanswered proposals and other books on `default` gets none and none are touched, shown by a snapshot of every other book's events and shelf before and after); **a book whose `crawl_found` has a missing, malformed or unapproved `plan_digest` (a forged event, or a digest whose approved folder is gone or altered) is neither proposed nor moved**, and is recorded once as `crawl_unplaced` with the reason `its plan digest is not an approved one` so that it is named in the report and not tried again; the move requires the newest `placement_proposed` event to be current (the same card, text, schema and prompt), its answer to be one of the five shelves offered, a home shelf of the schema, not `default` and accepted by the store; it takes the catalog lock for each move, reads the root file again, calls `set_shelf`, reads it back and appends one `reshelved` line with `from`, `to`, `action: move`, `basis: model-pick`, `via: crawl`, `run`, `plan_digest`, `proposal`, `schema_sha256` and no `confirmation`; a `none`, malformed or error proposal, a shelf not offered, `default`, not a home shelf, or refused by the store leaves the book on `default` with `crawl_unplaced` and the reason; a page whose text tells the model to choose a shelf gets a placement among the five offered and a cleaned reason and the book flagged unreviewed; the stop file is looked at before each move and each model call; a move whose read-back differs is an error that trips nothing but is logged and leaves the book terminal as unplaced; one `propose` and one `move` log line per book; idempotent (a book with `reshelved` or `crawl_unplaced` is not touched again). The helpers made public have no change of behaviour (their existing tests pass unchanged).
3. Write the module; deliberate breaks; the `reviewer`'s reading; the Result. **Ask the owner for a `security-reviewer` run** (the move changes the library).
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlmove engine.tests.test_placement engine.tests.test_placereview engine.tests.test_placeapply engine.tests.test_catalog`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#L`.

### Increment M — The run, assembled

**Outcome:** `crawl-run` runs the steps in the spec's order with every guard wired, resumes what a dead run left, and `--dry-run` describes it.
**Dependencies:** A to L.
**Affected areas:** `engine/kb/crawlrun.py`, `engine/tests/test_crawlrun.py`, `engine/tests/test_crawlchain.py`.
**Steps:**
1. Read `crawlrun.py` (the points and the context) and write in the Result the order of one run: the checks, `requeue_stale` and the sweep of old incoming leftovers, `lists`, `earlier_work` (first `reconcile_unapproved`, which only writes `crawl_unplaced` for a book with an unapproved digest; then every unfinished crawl book of an approved digest through the steps it has not finished, oldest first, bounded by the stop file, the floors and the ceilings), `refill`, `fetch` (up to `batch`, each new book through the same steps), and the end line with the counts.
2. Tests first: **the whole chain** (criterion 2) on a temporary library with a fake page server, fake models and an injected clock; the order of the steps and of the log lines; **a run killed by an injected failure at each step** leaves no ceiling exceeded and no book half-made and the next run finishes it (criterion 4); the stop file made in the middle of a batch prevents the next request, the next model call and the next move (criterion 3, one test each); the breaker trips on injected failures of fetches, on a model down for longer than the limit and on a stage that hits a bound, the next run is refused with exit 4 and runs only after `crawl-clear --yes`; a book unfinished at a ceiling is finished by the next run; the `filed` count (`crawlstate.filed_total` over the books' events) is passed to every `reserve`; the run name is new for every run; `--dry-run` prints the steps it would take and still writes nothing and makes no request; a second test reads the files a run leaves in the forms of R1's "Interfaces" (the lock, the breaker, the counters, the log, the queue) and the events of the books, as the other machine's `crawl-status` and `crawl-report` read them.
3. Write the assembly; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest` on the new modules' tests (`test_crawlbooks`, `test_crawllists`, `test_crawlrefill`, `test_crawlfetch`, `test_crawlsteps`, `test_crawljudge`, `test_crawlcards`, `test_crawlmove`, `test_crawlchain`) and the six R1 modules' tests (`test_crawlrun`, `test_crawlguard`, `test_crawlstate`, `test_crawlapprove`, `test_crawllog`, `test_crawlplan`); the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#M`.

### Increment N — The scheduler's text and the checklist of the supervised run

**Outcome:** the owner can read the exact launchd file and the checklist, and install nothing by accident.
**Dependencies:** M.
**Affected areas:** `engine/kb/crawlschedule.py`, `engine/kb/__main__.py`, `engine/tests/test_crawlschedule.py`, `README.md`.
**Steps:**
1. Read how the engine is launched (`python3 -m kb`), the config's paths and the spec's "Scheduling"; write in the Result the text the command prints.
2. Tests first: one command prints the text of a launchd agent that runs `python3 -X pycache_prefix=<a folder under the index root that the text names and tells the owner to make private> -m kb crawl-run` every 900 seconds with the working folder set to the repository's `engine` folder (where `kb` can be imported, as `engine/README.md` runs every command), with the log of the agent's own output outside the crawl's log, and nothing else; a test runs the printed command's program and arguments from that working folder with `--help` and shows that `kb` is found there, and that it is not found from the repository's top folder; it writes no file, loads nothing and makes no request; paths with spaces or odd characters are escaped for the format and an unsafe path is refused; the README's section names the checklist of the supervised run (approve the plan at a terminal, a dry run, the first run on a small ceiling, read the log and the report, `crawl-clear`, the stop file, how to stop the agent) and every command it names exists.
3. Write the command and the README section; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlschedule engine.tests.test_crawlrun`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#N`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs; A and B change R1's modules, so the six R1 modules' tests are rerun after each increment that touches one of them, and with every increment of M. At the end: the new modules' tests and the six R1 modules' tests are rerun together; the existing tests of `crawlqueue`, `discover`, `placement`, `placereview`, `placeapply`, `catalog`, `capture_url` and `weblists` are rerun; a read-only check shows that no file outside "Scope" changed; `wb run code-work check` is run; **the engine's whole suite is run once**, because `__main__.py` and the fingerprint's inputs change, and its result is recorded; a `crawl-run --dry-run` and one real run against a **temporary** library with fake sources are shown to the owner. No test and no check in this plan makes a request or a model call that is not a fake, and none touches the owner's library.

## Risks and sensitive actions

- **This plan writes the code that, once the owner schedules it, fetches pages from the open web, sends their text to models on the owner's network, and moves books on the owner's shelves without a person at the keyboard.** The code is not run against the real library, the real sources or the real models by this plan; the first run is the supervised run, the owner's act. The approval of the crawl plan (R1) is what grants the action, and A makes that approval cover the code exactly.
- Hostile content reaches the page parser, the scanner, the converter and the models: the scan holds before conversion, the sandbox and its limits are plan T's (hence no PDFs), and a security review with experiments is asked after G, H, I and L.
- The move changes the library: it touches only books with `crawl_found`, one at a time under the catalog lock, with a read-back and an event; a snapshot test shows no other book changes.
- Model calls on `ned` are the owner's own server over plain http (`models.md`); book text goes to it; nothing here sends the owner's name, email or address anywhere.
- The change to `placement.py` and `placereview.py` makes private helpers public and changes no behaviour; their existing tests are the check.
- The scheduler's text is printed, never installed.

## Review record

Plan review: three rounds of the review engine (`ask-codex`; the bound of 3 is used), 2026-11-16, eight findings, none left pending. The files of the review are in `.workbench/workbench/review-engine/plan-0009d70a8002d683/`.

- **Round 1 (two findings), both applied:** a book parked after `retries` failed tries had no terminal event, so the next run would select it again: "parked" now means weeded with `crawl_rejected` naming the stage, defined once in the assumptions and tested in the judgement and card increments (R1-F1); a book was chosen by its `crawl_found` event alone, though the spec requires the digest on it to be an approved plan's: the reader now takes only digests whose approved folder reads strictly, and the move refuses a missing, malformed or unapproved digest (R1-F2).
- **Round 2 (five findings), all applied:** a failed scan was both held at once and retried, which contradicted itself: the scan holds immediately, as the spec says, with no retry (R2-F1); nothing consumed the reader of unapproved books: `reconcile_unapproved` is the one place, runs first in `earlier_work`, writes `crawl_unplaced` once and is tested to call no model, move, proposal or capture (R2-F2); the fetch policy's DNS-rebinding and peer-address guarantees became required tests through the one shared client that capture, discovery and the list refresh use (R2-F3); the matcher rules were wrong against the spec (only the owner's blacklist matches subdomains) and are now stated and tested one by one (R2-F4); the URLhaus key's containment cases (https only, no redirect, no key to a redirect target, no key after a forced exception, the stop for the rest of the day) were added to the lists increment (R2-F5).
- **Round 3 (one finding), applied:** the scheduler text ran the engine from the repository's top folder, but `kb` is imported from `engine/`; the text now sets that working folder and a test shows `kb` is found from it and not from the top folder (R3-F1).
- **Left for the owner:** the third round's fixes were not shown to a fourth round, because the bound is 3; an extension needs the owner's word. The decisions listed in the chat summary (PDFs off until plan T, the judgement built here, the narrow changes to `placement.py`, `placereview.py` and possibly `webclient.py`) are the owner's to accept or change.

## Deferred work

- Plan T: the limits on the sandboxed tools (memory, PDF size, processes, decompression), before the crawl takes a PDF; turning PDFs on is that plan's change.
- `crawl-status` and `crawl-report` (the other machine's plan) and the report's use of the events named here.
- The supervised run on the owner's library, the owner's long run after it, and the measurement of the judgement's rule (`judge-1`).
- The low findings F8 and F10 to F14 of the R1 security review and the owner's todo items (the spec's wording on the last failed try and on the order of work, which candidates a stray file in the code tree should make stale, the stale model-down clock).
- Seeding, scouts and shelf entries.

## Result

### Increment A — Harden the approval: bytecode, approved copies, the fingerprint in the digest, all allow hosts (verified, not committed)

- Changed `engine/kb/crawlapprove.py` and `engine/kb/crawlrun.py`, and their tests (`test_crawlapprove` 62 tests, `test_crawlrun` 70; with `test_crawlguard` and `test_crawlplan`, 246 tests together, OK).
- **The digest, exactly (recipe 2):** the first 32 hex characters of the SHA-256 of `kb-crawl-approval-2` and a line feed, then for `plan`, `topics`, `allow` and `fingerprint`, in that order, `<name>:<decimal length>:<the bytes>` and a line feed; `fingerprint` is the 64 lowercase hex characters of R1's behaviour fingerprint (so the digest now changes with one byte of the engine's code or of the named model settings). `digest_of(plan_bytes, topics_bytes, allow_bytes, fingerprint_hex)` refuses a fingerprint that is not 64 lowercase hex. The stored folder, `current` and the five file names are R1's, unchanged. An approval made under recipe 1 does not match and is refused with `the approval cannot be trusted: approve again`.
- **F2:** `approve` computes the fingerprint first and the digest after it; with `--digest`, code or model settings that changed since the summary was read refuse and store nothing, and the message names the engine's code and model settings among what may have changed; `load_approved` checks the stored fingerprint file against the digest before it compares it with the code now, so a fingerprint forged to match changed code fails the digest (tested).
- **F3:** `load_approved` returns the plan with `topics` and `allow` set to the approved copies' paths (tested by editing the live files after the approval); `blacklist` stays the owner's live file, as the spec has it.
- **F9:** the summary lists every allow host, one a line, cleaned; an allow file of over 500 hosts is refused for approval with the count (tested at 500 and 501, nothing stored).
- **F1:** `crawl-run` refuses (exit 3, one `refuse` line, before the approval is read) unless Python's bytecode folder (`sys.pycache_prefix`, or the argument tests give) is a folder of the owner's, not a link, mode 700, **given as a full path**, outside the engine's code and not holding it, by resolved names; the dry run says so. A child-process test shows the danger (a planted unchecked-hash `.pyc` over unchanged source runs without the prefix) and the protection (with `-X pycache_prefix` the source runs and the bytecode goes to the private folder).
- **The caveat the review made me say plainly: the check is a tripwire and not the defence.** By the time `crawl-run` makes it, Python has already imported `kb.__main__` and these modules from wherever its bytecode folder pointed. What protects is the command that starts the process: **the scheduler's text (Increment N) carries `-X pycache_prefix`**, and the supervised run must be started with it by hand. The refusal catches a run started without it.
- **A residual closed in this increment:** a `.pyc` that sits outside a `__pycache__` folder is importable with no source and is in no fingerprint, so it is now an **error** in the fingerprint (and so a refusal of a run); the contents of a `__pycache__` folder remain left out, since the prefix keeps them from being read. The real engine tree has none.
- Deliberate breaks: 50 single mutations of the two modules with bytecode caching off; 2 survive, both equivalent (a `.strip()` on a bytecode-folder name that `lstat` already refuses, and an owner-uid check a single-account test cannot reach). Real gaps closed by tests: the private-file and the symlinked-parent forms of a bad prefix, the code folder itself as the prefix, the default code folder, a relative prefix, the dry run's duplicate line, the summary's wording, a forged stored fingerprint.
- Review (`reviewer`, one exchange): no blocking finding. **Applied:** the tripwire caveat (docstring and this Result), a stray `.pyc` beside the code is an error, a relative prefix is refused, the code-change message is tested by its own words. **Decided, not changed:** the check does not look at the parent folders' modes of the bytecode folder (the stated threat is a planted file in the tree).
- **For the owner:** `docs/specs/population.md` (line 132) still says the digest is of the plan, topics and allow files; it is now of those and the fingerprint, and the spec should say so. The file is not in this plan's Scope, so I have not changed it; say if you want that one sentence corrected in the commit of this increment.
- Not run: the rest of the engine's tests (run once at the end of the plan).
