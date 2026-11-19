# Fetch the full paper of an arXiv candidate in the unattended crawl, under the plan's limit for PDF files

Status: Proposed
Created: 2026-11-19
Candidate: none (a correction that follows from a finding: the crawl rejects every candidate of the arXiv source without a request, and takes the abstract page of an arXiv paper that OpenAlex found; `docs/specs/population.md` says a candidate is fetched with `capture-url` or `capture-arxiv`)
Specs: docs/specs/population.md ("Capture", the table of files, the type gate)

## Goal

Today the fetch step of the crawl (`engine/kb/crawlfetch.py`, `_Run.one`) rejects every candidate whose source is `arxiv` with the reason `pdf not safe to convert`, before it makes a request, and no book is made. The plan of 2026-11-17 (`let-the-unattended-crawl-take-pdf-files`) left that guard as it was, because "abstract page versus full paper" was the owner's decision. The owner has decided (2026-11-19): **the crawl takes the full paper, and PDFs are not limited to arXiv**; the limit is the plan's `pdf_max_mb`, which the owner has set to 10 and approved.

Measured on 2026-11-19, read only, by scripts of Python 3.15.0 that printed counts, at commit `ce9f1ae` of `main`, on the queue `candidates.sqlite` and the library of the owner:
- 298 candidates of the arXiv source are queued, all with an `/abs/` address, and 1 was rejected as `pdf not safe to convert`. None has been fetched. The arXiv source has never made a book. 19 of the next 50 candidates in the order of the fetch step are of this kind, and each takes the turn of its topic and a unit of the day's `fetches_per_day` (read from `crawlstate.reserve`, which takes the unit before the address is looked at; the count of a rejected row is not measured here).
- 73 candidates of the OpenAlex source with an `arxiv.org/abs/` address were **kept**: they went through `capture_url` as a web page, so the library holds 73 books that are the abstract page of a paper and not the paper. 16 more are queued; 3 were rejected. Five candidates of the web-search source are also `arxiv.org/abs/` addresses.
- Other hosts' PDFs already work: 7 books of the kind `paper` made by the crawl are active.
- The capture for arXiv exists and is made for this: `capture_arxiv.capture(store, ident, arxiv_id, policy=, max_bytes=, timeout=, total_timeout=, auto_filed=)` makes the metadata request and the PDF request through the shared client under the crawl's policy, files a book of the kind `preprint` with the identity key `arxiv`, and returns `filed`, `held` or `failed`. The owner's 48 preprints were made with it.

When this plan is done, **a candidate whose address is an arXiv paper address (an `/abs/<id>` or `/pdf/<id>` address on `arxiv.org`, `www.arxiv.org` or `export.arxiv.org`, the addresses that `webaddr.identity_key` reads as `arxiv:<id>`, of any source) is fetched with `capture_arxiv.capture`** under the same policy, the same site pacing, the same day's limits and the same limit of size as every other PDF (`pdf_max_mb`, at most the capture's own 50 MB); the book is marked `auto_filed` and gets its `crawl_found` event as any crawl book does; with the PDF limit off (`pdf_max_mb` 0, or the memory of a process unreadable) such a candidate is rejected as it is today, with no request.

## Scope

- `engine/kb/crawlfetch.py`: the guard of `one`, a function that reads the arXiv id of an address, the call of the capture of arXiv with the same handling of its three results as for a page, and one new optional parameter of `make_step` that replaces the capture of arXiv in tests.
- `engine/tests/test_crawlfetch.py`: the two tests that say an arXiv candidate is rejected without a request change; new tests for the cases below.
- `docs/specs/population.md`: the table of files and the paragraph "Capture" say what is built.

## Non-goals

- **The 73 books that are abstract pages.** They stay as they are. They hold the identity key of the page's address and not the key `arxiv`, so a later capture of the same paper by id would make a second book; the plan does not touch them, revive them or replace them. A todo item records the decision for the owner (replace, add the paper beside, or leave).
- Any change to `capture_arxiv.py`, `capture_url.py`, `webclient.py`, the sources of discovery (`srcarxiv`, `srcopenalex`) or the plan keys. No new key: the limit is `pdf_max_mb`.
- PDFs at other hosts, the memory limit of the converter, the scan tool and the conversion: unchanged.
- Fetching a particular version of a paper. The crawl always takes the latest version, whatever version an address names: the id comes from `webaddr.identity_key`, which drops the version on purpose, and no candidate asks for a particular one today (the arXiv source gives `/abs/<id>` with no version).

## Assumptions and constraints

- The step has the engine's stance: it reads no file and no environment variable itself, and every request is made by the shared client under the policy of the candidate, so the blacklist, the public-address check, the redirects, the cap and the pacing apply to the requests of the arXiv capture as to any.
- `capture_arxiv.capture` makes two requests, to the API host and to the PDF address. Both are sites of the registrable domain `arxiv.org`; the hook of the policy (`_policy.check`) counts a site once per candidate, so the two count as one site. This is checked in Increment A by a test, not assumed.
- **What blocks a fetch before any request is a book of the owner's** (a book that is not `auto_filed`): by its address as a URL, which is the check `one` makes today through `_owners`, and now also by the key `arxiv`, so that no request is made for a paper the owner has (the owner's 48 preprints). A book of the crawl's own does not block: the 73 abstract pages hold the identity of their address as a URL and not the key `arxiv`, so a paper whose abstract page the crawl kept is fetched as a paper and becomes a second book (the non-goals say so); and a book of the crawl's that holds the key `arxiv` (a paper made by an earlier try that died before its `crawl_found`) goes to the capture, which returns `held`, and `adopt` gives the book its event or rejects it as already held, exactly as for a page.
- This is a change to `engine/kb`, so it **voids the approval of the crawl** the moment it is copied into the owner's checkout. It is built in a separate worktree and copied to `main` in one step, and the owner is told before that, as the earlier plans did. It should be bundled with the other engine changes waiting, so that the owner approves once.
- The fetch takes PDFs from the network unattended: a security review of the change is asked for (Risks).

## Completion criteria

1. A queued candidate of the arXiv source with an `/abs/` address is fetched with `capture_arxiv.capture` and becomes a book of the kind `preprint`, `auto_filed`, with a `crawl_found` event, and its row is `kept` with the book's id.
2. A candidate of another source whose address is an arXiv paper address is fetched the same way; the abstract page is no longer taken as a web page.
3. With no PDF limit (`pdf_max_mb` 0 or the memory unreadable) an arXiv candidate is rejected as today, with no request and no book.
4. A paper that the owner already holds (a book that is not `auto_filed`, by the key `arxiv` or by its address) is rejected as already held with no request; a book of the crawl's own does not block (an abstract page the crawl kept does not stop the paper from being fetched; an orphan paper of an earlier try is adopted).
5. A failed capture leaves no active book and counts as a failed try; a refusal by the policy or by the site is handled as for a page (a block, a refusal of the site charged to its domain, a stop).
6. The size limit is the smaller of the plan's `pdf_max_mb` and the capture's own cap; a larger file is refused.
7. The tests of the area and `wb run code-work check` pass.

## Increments

### Increment A — Take the full paper of an arXiv address with the capture for arXiv

**Outcome:** the fetch step captures a candidate whose address is an arXiv paper address with `capture_arxiv.capture`, under the rules of criteria 1 to 6; the old guard that rejects every candidate of the arXiv source applies only when the limit for PDF files is off.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlfetch.py`, `engine/tests/test_crawlfetch.py`.
**Steps:**
1. Read `crawlfetch.one`, `_Run.outcome`, `adopt`, `classify`, `crawlstate.reserve` and `finish`, `capture_arxiv.capture` and its tests, and `identity.Identity.lookup` for the kind `arxiv`; write in the Result the exact order of one arXiv candidate and whether the two hosts of the capture count as one site under the hook of the policy.
2. Tests first, with the fake page server and a fake of the capture for arXiv that records what it is given, and see each fail for the right reason: (a) an `arxiv` candidate with an `/abs/` address and a PDF limit makes one call with the id, the policy, a size limit equal to the plan's, `auto_filed=True`, and a `filed` result gives a book with `crawl_found`, a `kept` row, a `fetch` line and a `capture` line; (b) a candidate of the `openalex` source with an `arxiv.org/abs/` address does the same; (c) a versioned address (`/pdf/<id>v2`, `/abs/cs/0112017v2`) passes the id **without** its version, so that the latest version is captured (`webaddr.identity_key` drops the version on purpose, and the plan does not change it); (d) with no PDF limit it is rejected as `pdf not safe to convert` with no call; (e) a book of the owner's held by the key `arxiv`, and a book of the owner's held by the address, each give `rejected: already held` with no call; an `auto_filed` abstract-page book of the same paper (held by the address as a URL) does **not** stop the call and leads to a second book, a preprint; an `auto_filed` paper held by the key `arxiv` with no `crawl_found` (an orphan) goes to the capture, is given its `crawl_found` and the row is `kept`, and one that has the `crawl_found` of another candidate is rejected as already held; (f) `held` leaves the row `kept` as for a page, and `failed` weeds the book it made and records a failed try; (g) a refusal of the policy raised by the capture is classified as for a page; (h) a candidate of the `arxiv` source whose address is not a paper address (`/list/cs/new`) is rejected as not usable with no call, and a candidate of another source at such an address (a listing page of arXiv) keeps going through the ordinary page capture as today, with no call of the capture for arXiv; the three hosts and the legacy and versioned ids of step 3 each lead to a call with the right id; (i) a limit above the capture's cap is cut to the cap; (j) the two hosts of the capture count as one site against the limits of the day.
3. Read the arXiv id of an address with the one function that already decides it, `webaddr.identity_key` (the spec makes `webaddr` the only place that canonicalises): an address is a paper address when it returns a key that begins `arxiv:`, and the id is the rest of the key. That function already knows the three hosts (`arxiv.org`, `www.arxiv.org`, `export.arxiv.org`), the legacy ids with a slash (`cs/0112017`), versions and a final `.pdf`, and makes no request; no second parser is written. The id is given to `capture_arxiv.parse_id` as a check. The tests include each of the three hosts for an `/abs/` and a `/pdf/` address, `/abs/cs/0112017`, `/pdf/cs/0112017.pdf`, a versioned legacy id (`/abs/cs/0112017v2`, read as the id without its version), a modern id with and without a version and with `.pdf`, and addresses that are not papers (`/list/cs/new`, `/abs/2101.00001/extra`, an empty id).
4. In `one`, after the address is made canonical and the check of the owner's books by address, route an address with an id to the capture for arXiv: reject with `PDF_REASON` when `self.fp.pdf_bytes` is `None`; reject as already held, with no request, when `self.ident.lookup("arxiv", id)` names a book of the owner's (`_owners`, the same handling as the check by address; a book of the crawl's own goes to the capture, as the assumptions say); otherwise call the capture with `policy=self._policy()`, `auto_filed=True`, `max_bytes=min(self.fp.pdf_bytes, capture_arxiv.PDF_MAX_BYTES)`, the timeouts of the fetch policy, and handle `filed`, `held` and `failed` with the code that already handles them for a page (the result keys are the same). Candidates of the `arxiv` source whose address gives no id are rejected as not usable; a candidate of another source at an arXiv address that is not a paper's is left to the page capture, as today.
5. Add to `make_step` one optional parameter for the capture for arXiv, defaulting to `capture_arxiv.capture`, beside `capture`.
6. Change the two old tests that said an arXiv candidate is rejected with no request (`test_an_arxiv_candidate_is_rejected_as_a_pdf_without_a_request_or_a_book` and `test_the_arxiv_source_is_still_rejected_without_a_request_with_pdfs_on`) to the new behaviour, keeping the case with the limit off.
7. Deliberate single changes, each compile-checked and each restored byte for byte, each caught by a test: the guard for a PDF limit that is off; the check by the key `arxiv`; the `auto_filed` flag; the cap `min`; the id function accepting `/list/`; the `held` case handled as `failed`.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_capture_arxiv engine.tests.test_crawlsteps` and the deliberate changes of step 7; `wb run code-work check`; `git diff --check`. A wider run is not needed: nothing outside `crawlfetch.py` changes, and the capture for arXiv, the client and the state module are used through calls they already take; what could break outside the tested area is the order of the fetch step, which `test_crawlsteps` runs.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-19-fetch-arxiv-papers-in-the-unattended-crawl#A`.

### Increment B — Say in the spec what is built

**Outcome:** `docs/specs/population.md` says that an arXiv paper is fetched as a paper by its id under the plan's limit for PDF files, that the crawl no longer takes the abstract page of a paper, and that with the limit off such a candidate is rejected.
**Dependencies:** Increment A.
**Affected areas:** `docs/specs/population.md` (the table of files, "Capture", the type gate), and the plan's Result.
**Steps:**
1. Edit the three places so that they agree with the code of Increment A; do not change anything the spec says about direction.
2. Add a todo item for the 73 books that are abstract pages (the decision is the owner's).
3. Write the review record and the Result of Increment A in this plan, and run `wb run code-work check`.
**Verification:** `wb run code-work check`; `git diff --check`; a read of the three places against `crawlfetch.py`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-19-fetch-arxiv-papers-in-the-unattended-crawl#B`.

## Verification for the plan as a whole

Increment A's verification stands unless Increment B changed `engine/kb`, which it does not. After both: `wb run code-work check`. Then the live loop, once the approval of the crawl is renewed: the first arXiv candidate that is taken shows in the log as a `fetch` line and a `capture` line, and in the queue as a `kept` row with a book. That is the one thing the tests cannot show, a real answer from arXiv; it is read, not run as a separate step.

## Risks and sensitive actions

- **Untrusted input at a network boundary, unattended.** The crawl will download PDFs from arXiv, as it already does from other hosts, and the converter will read them. The size is limited (the plan's `pdf_max_mb`, at most 50 MB), the file must begin with `%PDF-` (`capture_arxiv.capture` checks it), the memory of the converter is limited by the plan of 2026-11-17, and the requests go through the shared client. A security review is asked for before the commit of Increment A: the id function (an address that is made to look like a paper's), the cap, the type check, the use of the key `arxiv` as a check before a request, and a hostile answer of the API.
- **The approval of the crawl is voided** when the files reach `main`; the crawl stops until the owner approves again. Bundled with the other engine changes, one approval covers all.
- **Rate against arXiv.** The 298 queued candidates will be fetched at the pace of the fetch step and the day's limits, as for any host: the plan's `min_gap_s` and `jitter` between requests to a registrable domain (the key `gap_arxiv_s`, 15 seconds in the owner's plan, paces the search of the arXiv source in discovery and not the fetch). arXiv's own rules for automated access are not changed by this plan. If arXiv answers 429, the existing handling of a refusal of a site applies and the site rests for the day. Whether `min_gap_s` is enough for arXiv's API, which the capture also asks, is read in Increment A (step 1) and set down in the Result.
- **Disk.** Each paper is up to 10 MB at the owner's limit, 298 papers at most 3 GB, with 14 GiB free against a floor of 10 GB; the floor stops the crawl before it is passed, as it does for any book.

## Review record

Plan review with the review engine (`review-plan`; model `gpt-5.6-terra` for rounds 1 and 2, `gpt-6.1-sol` for round 3): 3 of 3 rounds used (the bound), 5 findings, all applied, none rejected. After round 3 the plan was corrected and **no fourth round was run**, so the last correction has not been read by the reviewer.
- **Round 1.** (1) The plan promised both that an existing auto-filed abstract-page book is left and that every held address is rejected: now only a book of the owner's blocks before a request; the crawl's own books go to the capture (assumptions, criterion 4, test e). (2) Legacy ids with a slash: covered in the tests.
- **Round 2.** (1) Only the apex host was read: the id is now read with `webaddr.identity_key`, which knows `arxiv.org`, `www.arxiv.org` and `export.arxiv.org`. (2) The rule for a non-paper arXiv address differed between the tests and the steps: only the `arxiv` source is rejected for it; another source keeps the page capture.
- **Round 3.** `webaddr.identity_key` drops the version (checked by running it on six addresses): the crawl takes the latest version of a paper, test (c) says so, and keeping a named version is deferred.
- Left for the owner: whether to ask for a fourth round (it needs `wb run review-engine extend`, which is the owner's), and the approval.

## Deferred work

- The 73 books that are the abstract page of an arXiv paper, made before this change: replace, add the paper beside, or leave. A todo item is added in Increment B.
- A candidate of the web-search source that is an arXiv address is routed the same way by this plan; arXiv addresses of other hosts' mirrors are not.
- A candidate that names a particular version is captured as the latest version. Keeping the named version would need the shared address module to give it, which is a change to `webaddr.py` that nothing asks for today.

## Result

### Increment A

Built in a separate worktree (`wt-arxiv`, branch `arxiv-fetch`, from `b9cf3f0`), so that the approval of the running crawl was not voided while it was written and reviewed; it has not been copied to `main` or committed yet.

**Step 1, what was read.** The order of one arXiv candidate in `_Run.one` is now: the guard for a PDF limit that is off (an `arxiv` source, or an address that names a PDF); the canonical address; the owner's book by the address as a URL; the id of the paper (`webaddr.identity_key`); a candidate of the `arxiv` source with no id is rejected as not usable; with an id and no PDF limit, rejected as a PDF; the book that holds the key `arxiv` (rejected as already held with no request unless `adopt` would take it); then `capture_arxiv.capture` through `self._policy()`, with `auto_filed=True` and `max_bytes=min(pdf_max_mb, 50 MB)`; then the same handling of `filed`, `held` and `failed` as for a page. The API host (`export.arxiv.org`) and the PDF host (`arxiv.org`) are one site (`arxiv.org`) for the hook of the policy, which counts a site once per candidate: shown by a test that runs the real capture at those two production names, and by reading `_policy.check`. The fetch is paced by the plan's `min_gap_s` (default 8 seconds, with `jitter`) per registrable domain, so the API request and the PDF request of one paper are paced as two requests to `arxiv.org`, and the day's `per_domain_per_day` (150 in the owner's plan) is the ceiling of papers a day from arXiv; at that pace the 298 queued candidates take two days. Whether 8 seconds suits arXiv's own rules was not checked here.

**What was done.** `engine/kb/crawlfetch.py`: `_arxiv_id`, `MAX_ARXIV_ID`, `_Run._adoptable`, the routing in `one`, and the parameter `capture_paper` of `make_step`. `engine/tests/test_crawlfetch.py`: the old test that said an arXiv candidate is rejected with the limit on now says it is rejected as not usable when its address is not an arXiv paper's; 15 new tests (class `ArxivPapers`).

**Departures from the plan's wording, for the owner to accept.**
1. A book that holds the key `arxiv` and that `adopt` would refuse (a book the crawl has counted for another candidate, or one weeded by someone else) is rejected as already held **before any request**, where the plan's assumption said such a book goes to the capture, which says `held`. The rows end as the plan's criterion 4 says; the change is that no request is made. It came from the security review (below): the capture asks the API first and files a newer version into whatever book holds the key.
2. The id is read with `webaddr.identity_key` and is **not** passed to `capture_arxiv.parse_id` as a check (the plan's step 3): the two modules use the same id patterns, so an id from the first always parses in the second, and `capture` calls `parse_id` itself.
3. An id longer than 40 characters is not read as a paper's (a real one has at most 20): not in the plan, from the security review.
4. The break "the id function accepting `/list/`" is the break "the id function returns any address as a paper": the same fault.

**Verification run (in the worktree).** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_capture_arxiv engine.tests.test_crawlsteps`: 336 tests, OK; the tests were written first and failed for the right reason (`make_step()` had no `capture_paper`, the routing did not exist). Ten deliberate single changes of `crawlfetch.py` (the guard for a PDF limit that is off; the check of a book that `adopt` would refuse; a book counted for another candidate taken as adoptable; a book counted for this very candidate refused; a book weeded by someone else taken as adoptable; the length cap; the `auto_filed` flag; the size cap `min`; the id function taking any address; a `held` result handled as `failed`) were each compile-checked, each made at least one test fail, and the file was restored byte for byte after each. `git diff --check` clean. **Not run:** `wb run code-work check` (it runs in `main`, after the copy), and a run against the real arXiv.

**Review.** `reviewer`, one exchange: no blocking finding. Applied: the parameter was renamed `capture_paper` (it hid the module `capture_arxiv`); tests added for the host spellings from both sources, the reason of a refusal, the two production hosts of the capture, and a paper over the limit through the real capture. Recorded: a weeded book of the owner's that still holds the key `arxiv` blocks the fetch, as the existing check by address does. `security-reviewer`, one exchange and a second look by `reviewer`: no Critical and no High finding; one Medium applied (the book counted or weeded was written into by a newer version: now rejected before the request, with two tests and three breaks); the Low about the length of an id applied; the second look found that the fix refused a row requeued after a death for the book it was counted for, which is now allowed (test and break added). **Recorded, not changed:** (1) a subject-class spelling of a legacy id (`math.GT/0309136` for `math/0309136`) is not the owner's key: one failed request and a weeded junk book; (2) a paper the owner holds only under a page address of another spelling is fetched again as a second book (the owner's book is not touched); (3) permanent failures of the capture (another paper's answer, not found) are retried and count toward the breaker, like a dead page; (4) `source["address_pdf"]` names the address asked and not the one a redirect led to (a change of `capture_arxiv.py`, outside the plan); (5) a candidate at a blacklisted `www.arxiv.org` would be fetched from `export.arxiv.org` and `arxiv.org`, since the blacklist matches the hosts of the requests (no arXiv host is on the owner's list).

**Left for the owner:** the word to copy the two files to `main` (which voids the approval of the crawl) and to commit; to accept the departures above; and the todo items for the recorded points.
