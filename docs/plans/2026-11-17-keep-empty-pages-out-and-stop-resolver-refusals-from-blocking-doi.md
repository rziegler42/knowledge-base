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

### Increment A — A refusal is counted against the site that answered it (committed `dca150b`)

- Changed `engine/kb/crawlstate.py` (`finish(..., count=True)`: its validation, and the refusal count made conditional), `engine/kb/crawlfetch.py` (the `finish` wrapper with `count`, and the `refused` branch of `outcome`), `engine/tests/test_crawlstate.py` (3 tests), `engine/tests/test_crawlfetch.py` (2 tests in `Redirects`), `docs/specs/population.md` (the comment on `domain_refusals`) and `README.md` (the known-limit line). Verification: `test_crawlstate`, `test_crawlfetch` and `test_crawlchain`, 234 tests, OK; `wb run code-work check` and `git diff --check` clean.
- **The rule.** A refusal (403, 429, an abuse signal) answered by a site that a redirect led to (`hop["last"] != hop["first"]`) is counted **once against that site** (`note_refusal`) and **none against the row's own domain**; the row still waits a day (`refusal=True` keeps the wait). A refusal by the candidate's own first site (including a chain that comes back to it) is counted once against it, by `finish`, as before.
- **Tests first** (the fetch test failed on the old code with `refusal:resolver.test` counted): three candidates at one resolver, each sent to a different publisher that answers 403, leave each publisher at 1 and the resolver at none, each row waits for its next try; a refusal by the first site is counted once; `finish` with `count=False` waits a day and counts nothing, with `count=True` counts, and `count` must be a boolean. Sixteen single mutations; two survived and stay, both equivalent: dropping the `last != first` test (the count is then made by `note_refusal`, once, for the same site) and the wrapper's default `count` (never used with a refusal).
- Review (`reviewer`, one exchange): no blocking finding; criterion 2 met. **Recorded, not changed:** (1) a refusal is charged in two commits (`finish`, then `note_refusal`), as before; a death between them leaves a refusal counted for nobody, never twice; (2) the test shows the resolver is not stopped through the counter that `site_stopped` reads, and does not assert a fourth resolver candidate is taken by `reserve` (the three rows wait a day anyway); (3) `count` is accepted and ignored for a failure that is not a refusal; (4) **the open hole is unchanged and not made worse**: a hostile redirect can still add refusals to another site that answers 403, up to `domain_refusals` a day (the todo item stands); (5) a refusal at an unusable site is not reachable: such a hop ends as `blocked` before any request.
- Not run: the rest of the engine's tests.

### Increment B — A book whose card has nothing in it is judged out (committed `16e9c9f`)

- Changed `engine/kb/crawlcards.py` (`has_sentences`, `judge_out_empty_cards`, `EMPTY_CARD`, the split of `step` into `step` and `_work`, the module docstring), `engine/kb/crawlsteps.py` (`reject_book`, a public wrapper of `_reject`), `engine/tests/test_crawlcards.py` (the class `EmptyCards`, 14 tests; a fixture card `SUMMARY_CARD` and a `set_plan` that uses it; three structural tests updated), `engine/tests/test_crawlchain.py` (the class `EmptyCardInTheChain`), `docs/specs/population.md` (one sentence) and `README.md` (one clause). Verification: `test_crawlcards`, `test_cardqueue`, `test_crawlbooks`, `test_crawlreport`, `test_crawlchain`, plus `test_crawlsteps` and `test_crawlschedule`, 582 tests, OK; `wb run code-work check` and `git diff --check` clean.
- **The rule as built, narrower than the approved text (the owner should read this).** The plan says a card with **no summary** is judged out. The review's main finding was that the checks of the grounding can drop every sentence of a real document's summary (a summary sentence with no supporting quote, a quote that does not occur in a badly converted text, a check model that is strict), so "no summary" would weed a good book for the fault of the card-making and not of the page. **The rule as built judges a book out only when its newest card has no sentence at all in its six written parts (summary, problem, approach, needs, provides, limits)**, which is the shape of the record page (its card says all six were empty after the checks) and needs every part to fail together. A card that lost only its summary, or any other part, is kept (two tests, with real grounded cards filed through `card.file`: one that kept only its limits, one that kept only its summary). The rule weeds a subset of what the approved text would have weeded, never more. The reviewer suggested also requiring no key ideas and topics; that would **not** catch the real record page, whose card keeps a dozen key ideas and topics inferred from its metadata, so it is not used.
- **What it does.** `judge_out_empty_cards` runs after the step's work on every call (also when the step had nothing to do; not when it raised a trip or a refusal), skips at the stop file or a disk floor, and looks at the newest card of each crawl book that is judged in, unfinished and under an approved plan (`crawlbooks.crawl_books`). A card with no sentence at all: the book is weeded through `crawlsteps.reject_book` (`crawlbooks.weed` first, which refuses a book the crawl did not file; then its row `kept` to `rejected`, one `reject` line, a fixed reason), at the stage `card`, and leaves the index. A card that cannot be read is skipped. **The step reads one fact of a card (`has_sentences`) and copies no word of it.** The real record page of the first run would be judged out by this rule at the next run (its card has six empty parts).
- Tests first and breaks: the rule on a book with a card of no model part, one with a model part and every part dropped, one that kept only a part, one carded in an earlier run, a hostile card in an earlier generation, a book the crawl did not file, an unapproved digest, a book not judged in, the stop file and the disk floor, the order (the weeding before the row), a damaged card, a newer version with no card; and a chain test where the real rule runs and the report compares the same on every row (kept 2 and 2, rejected 2 and 2). Twenty single mutations of the narrowed rule were all killed (earlier, 25 of the wider rule: 20 killed in the first run, the 5 that survived closed by tests or equivalent).
- Review (`reviewer`, one exchange, of the wider rule): no blocking finding; criteria 1, 3 and 4 met. **Applied:** the narrowing above. **Recorded, not changed:** (1) **a death after the weeding leaves no `reject` line**: the order in `_reject` is the weeding, the row, then the line, and the judge step's `_finish_rejections` repairs the state and the row and writes no line, so the report would count one more rejected row than rejected lines; the same is true of the parking paths that existed before; (2) one book that raises in `reject_book` stops the weeding of the books after it, and the next run meets it first (no concrete trigger found; `_reject_row` guards a row that is not `kept`); (3) the cost is two scans and a read of the newest card of each unfinished judged-in carded book (at most `filed_total`), each run; (4) **the narrowed rule was made after the review and has had no second reading**: it is covered by the tests and the breaks above, and the owner may ask for a review.
- **The plan as a whole (criteria 1 to 5).** 1 (a book with a card of no sentence is judged out, nothing of the card copied, a book with sentences or one the crawl did not file untouched) by B, as narrowed above; 2 (a refusal counted against the site that answered) by A; 3 (the log and the queue compare the same with an empty-card book) by B's chain test; 4: `wb run code-work check` clean. 5 waits for the owner's reading. **Plan-level verification (the plan's last section), as run after B:** `test_crawlchain`, `test_crawlrun`, `test_crawlguard`, `test_crawlstate`, `test_crawlapprove`, `test_crawllog`, `test_crawlplan`, `test_crawlbooks`, `test_crawllists`, `test_crawlrefill`, `test_crawlfetch`, `test_crawlsteps`, `test_crawljudge`, `test_crawlcards`, `test_crawlmove`, `test_crawlstatus`, `test_crawlreport`, `test_crawlschedule` and `test_cardqueue`: **1,743 tests, OK, in 92 seconds**. Not run: the engine's whole suite. **The code fingerprint changed (A and B): the owner approves the crawl plan again** with `crawl-approve` before the next run.
- Not run: the rest of the engine's tests.
