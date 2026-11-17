# Keep empty pages out of the library and stop a publisher's refusal from blocking every DOI address

Status: Proposed
Created: 2026-11-17
Candidate: none (corrections that follow from findings: the first and third supervised runs of the unattended crawl, and two todo items made from them)
Specs: docs/specs/population.md

## Goal

Two things were found in the supervised runs of the unattended crawl.

1. **A page with nothing in it can be kept.** The book of `biblio.ugent.be/publication/8528188` is a repository record (citation formats, a download link, an ISBN) with no abstract. Its card has no summary, problem, approach, provides or limits and says "only metadata present". It was judged in at 0.63 because its title matches the FPGA shelf: the judgement reads the title and the start of the text, and a higher threshold would not remove it. The book is in the library, unreviewed, with an empty card.
2. **A refusal by a publisher is also counted against `doi.org`.** A candidate at `doi.org` that is sent on to a publisher that answers 403 adds one refusal to the publisher and one to `doi.org` (the first site). The plan stops a site for the day after `domain_refusals` (3) refusals, and most candidates are DOI addresses, so three publishers that refuse robots would stop `doi.org`, and with it every DOI candidate, for the day. The third run showed the first refusal: `hindawi.com` 1 and `doi.org` 1 after one 403.

When this plan is done:

- a crawl book whose card has **no summary** is judged out after its card is made, with a fixed reason, **kept as a weeded book** (like any judged-out book: its files stay, its queue row says `rejected`, the report names it), and never moved;
- a refusal by a site that a redirect led to is counted **against the site that answered it, and not also against the site that led to it**; a refusal by the candidate's own first site is counted against it, as now.

## Scope

**Changed:** `engine/kb/crawlcards.py` (the cards step), `engine/kb/crawlfetch.py` and `engine/kb/crawlstate.py` (the charge of a refusal), their tests (`test_crawlcards`, `test_crawlfetch`, `test_crawlstate`, `test_crawlchain`), `docs/specs/population.md` (where it states what is built: the judgement and the site's refusals) and `README.md` (the known limits).

**Not changed:** the judgement (`crawljudge.py`), the threshold and its meaning, the move step, the queue's shape, the plan's keys, `crawlreport.py` and `crawlstatus.py`.

## Non-goals

- Papers instead of landing pages: the crawl takes no PDF until the converter has a memory limit (a todo item, and a larger piece of work). This plan keeps empty landing pages out; it does not change what the crawl fetches.
- A rule that judges a page out **before** its card (a heuristic on the page's text). The card is what shows that a page has no content, and the card is already made; the cost of the model calls for such a page is accepted and recorded.
- Other refusal accounting (a hostile redirect adding refusals to another site stays a todo item).

## Assumptions and constraints

- A card whose `summary` has no sentence is **not** a failed card: the card queue made it and filed it, with `partial` set and the reason `no sentence of the summary was left after the checks`. The cards step today reads no card (it writes only fixed text); this plan lets it read **one fact** of the newest card of the book's current version: whether `summary` holds any text. It never copies a word of the card into an event, a line or a reason.
- The rule applies to a book that **has just been carded** by this step, and to a book already carded whose card has no summary and that is still waiting (so a book of an earlier run is judged out at the next run too). A book with a summary is untouched.
- A judged-out crawl book is weeded through the existing writer (`crawlbooks.weed`, which refuses a book that the crawl did not file and writes `crawl_rejected` first), its queue row goes `kept` to `rejected` (`crawlstate.reject_kept`), its rows leave the index (`index_stage.forget_inactive`, as the judge step does), and one `reject` line with the book and a fixed reason is written, so that the report counts it with the other rejections and the log and the queue compare the same.
- The refusal accounting: `crawlstate.finish(..., refusal=True)` both lengthens the wait before the next try (24 hours) and counts a refusal against the row's own domain. The wait stays; the count against the row's domain is made conditional.
- No test uses the network, a real model, the owner's library or config.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. A crawl book whose newest card has no summary is weeded after the cards step with the stage `card` and a fixed reason, its row is `rejected`, its index rows are gone, one `reject` line names it, and nothing from the card is copied into any event, line or reason; a book whose card has a summary is not touched; a book that is not the crawl's is never touched.
2. A candidate at `doi.org` whose redirect reaches a site that answers 403 adds one refusal to that site and none to `doi.org`; a refusal by the candidate's own first site is counted against it once; the wait before the next try stays as now.
3. For a library with a good book, a held book, a judged-out book, an unplaced book and a book with an empty card, the log and the queue compare the same on every row of the report.
4. `wb run code-work check` passes; the tests of `crawlcards`, `crawlfetch`, `crawlstate`, `crawlchain` and `crawlreport` pass.
5. The owner has read the result.

## Increments

### Increment A — A refusal is counted against the site that answered it

**Outcome:** a publisher's refusal no longer counts against the resolver that led to it.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlstate.py`, `engine/kb/crawlfetch.py`, `engine/tests/test_crawlstate.py`, `engine/tests/test_crawlfetch.py`.
**Steps:**
1. Read `crawlstate.finish` (the `refusal` argument), `crawlfetch.outcome` (the `refused` branch and `note_refusal` for `hop["last"]`) and the tests of refusals (`a_refusal_at_the_first_hop_is_charged_once...`, `a_redirect_to_a_site_that_refuses_is_charged_to_that_site...`).
2. Tests first: a refusal after a hop to another site is counted once against that site and **not** against the row's domain, and the row still waits 24 hours; a refusal by the first site itself is counted against it once (as now); three refusals by publishers reached through `doi.org` do not stop `doi.org`; the site that refused is stopped for the day at `domain_refusals`; a refusal that is counted against the site that answered can still stop that site (the open todo about a hostile redirect stays: a test says it is unchanged).
3. Write the change (an argument that says whether `finish` counts the refusal against the row's domain); deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlstate engine.tests.test_crawlfetch engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-keep-empty-pages-out-and-stop-resolver-refusals-from-blocking-doi#A`.

### Increment B — A book whose card has no summary is judged out

**Outcome:** a crawl book that has been carded and has no summary is weeded as judged out.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlcards.py`, `engine/tests/test_crawlcards.py`, `engine/tests/test_crawlchain.py`, `docs/specs/population.md`, `README.md`.
**Steps:**
1. Read `crawlcards.make_step` and `_close`, `card.read` and the card's `summary` field, `crawlbooks.weed`, `crawlstate.reject_kept`, `crawljudge`'s `weed` and the judge step's use of `index_stage.forget_inactive`.
2. Tests first: a book carded with an empty summary is weeded with the stage `card`, its row is `rejected`, its index rows are removed and one `reject` line names it with the fixed reason; a book carded with a summary is not touched; a hostile card (text in the summary field that looks like an instruction) is not copied into anything; the rule is applied again, in the same way, to a waiting book whose card has no summary; a book that is not the crawl's is not touched; the stop file and the disk floor are looked at before the check as for every other work of the step; a death between the weeding and the row is finished by the next run (as `finish_weeds` does); the chain tests' library with a book of an empty card says the same on every row of the report.
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result; the spec (the judgement and the report) and the README say what is built.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlcards engine.tests.test_cardqueue engine.tests.test_crawlbooks engine.tests.test_crawlreport engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless the other changed its inputs. At the end the tests of the six R1 modules, `test_crawlfetch`, `test_crawlsteps`, `test_crawlcards`, `test_crawlmove`, `test_crawljudge`, `test_crawlstate`, `test_crawlreport`, `test_crawlstatus` and `test_crawlchain` are rerun together; `wb run code-work check` is run; a read-only check shows that no file outside "Scope" changed. The engine's whole suite is not rerun unless the owner asks. **After this plan the owner approves the crawl plan again** (`crawl-approve`), because the code fingerprint changed.

## Risks and sensitive actions

- **Increment B weeds books**, a change of state of books in the owner's library. It does so only through `crawlbooks.weed`, which refuses a book that is not `auto_filed` and found by the crawl, and only for a book whose newest card has no summary. A book is kept as weeded with its files and its reason, so a wrong rule is recoverable by reading the report and the book's events; the rule is stated plainly (no summary at all, not a short one).
- **Reading a card** is reading text from outside. The step looks at one fact (does `summary` hold any text) and copies nothing.
- **A network boundary is touched in Increment A** (the accounting of refusals): a change that counted too little would let a hostile redirect aim requests at a site that refuses without that site being stopped; the site that answers is still counted and still stopped at its limit.
- The change of the code makes the approval of the crawl plan stale: the runs refuse until the owner approves again, which is his act. The owner is asked whether to run a security review once both increments are done; none runs unless he asks.

## Review record

Empty until a review is asked for.

## Deferred work

Papers instead of landing pages (the PDF work and the converter's memory limit), the refusals that a hostile redirect can still add to another site, the sweep of `incoming` and the card stop file inside a pass stay on the owner's todo list.

## Result

### Increment A — A refusal is counted against the site that answered it (verified, not committed)

- Changed `engine/kb/crawlstate.py` (`finish(..., count=True)`: its validation, and the refusal count made conditional), `engine/kb/crawlfetch.py` (the `finish` wrapper with `count`, and the `refused` branch of `outcome`), `engine/tests/test_crawlstate.py` (3 tests), `engine/tests/test_crawlfetch.py` (2 tests in `Redirects`), `docs/specs/population.md` (the comment on `domain_refusals`) and `README.md` (the known-limit line). Verification: `test_crawlstate`, `test_crawlfetch` and `test_crawlchain`, 234 tests, OK; `wb run code-work check` and `git diff --check` clean.
- **The rule.** A refusal (403, 429, an abuse signal) answered by a site that a redirect led to (`hop["last"] != hop["first"]`) is counted **once against that site** (`note_refusal`) and **none against the row's own domain**; the row still waits a day (`refusal=True` keeps the wait). A refusal by the candidate's own first site (including a chain that comes back to it) is counted once against it, by `finish`, as before.
- **Tests first** (the fetch test failed on the old code with `refusal:resolver.test` counted): three candidates at one resolver, each sent to a different publisher that answers 403, leave each publisher at 1 and the resolver at none, each row waits for its next try; a refusal by the first site is counted once; `finish` with `count=False` waits a day and counts nothing, with `count=True` counts, and `count` must be a boolean. Sixteen single mutations; two survived and stay, both equivalent: dropping the `last != first` test (the count is then made by `note_refusal`, once, for the same site) and the wrapper's default `count` (never used with a refusal).
- Review (`reviewer`, one exchange): no blocking finding; criterion 2 met. **Recorded, not changed:** (1) a refusal is charged in two commits (`finish`, then `note_refusal`), as before; a death between them leaves a refusal counted for nobody, never twice; (2) the test shows the resolver is not stopped through the counter that `site_stopped` reads, and does not assert a fourth resolver candidate is taken by `reserve` (the three rows wait a day anyway); (3) `count` is accepted and ignored for a failure that is not a refusal; (4) **the open hole is unchanged and not made worse**: a hostile redirect can still add refusals to another site that answers 403, up to `domain_refusals` a day (the todo item stands); (5) a refusal at an unusable site is not reachable: such a hop ends as `blocked` before any request.
- Not run: the rest of the engine's tests.
