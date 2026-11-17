# Count the crawl report the way the steps write the log

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from a finding: the whole-chain tests of `2026-11-16-run-the-steps-of-the-unattended-crawl` showed that `crawl-report` says DIFFERENT for a healthy run)
Specs: docs/specs/population.md

## Goal

`crawl-report` compares what the log says of a day with what the queue says (`crawlreport._compare`: kept, rejected, failed), so that the owner can see a run that went wrong. For a healthy run with a held book and a judged-out book it says DIFFERENT (found by the whole-chain tests: "kept: log 2, queue 3" and "rejected: log 0, queue 1"), because it counts the log by lines that the steps do not write:

- **rejected** is counted from lines of the step `reject`. A book judged out writes `judge`/`rejected` (with its candidate and book) and no `reject` line; the `reject` lines are written for a book weeded at the scan, the convert or a parking, and they carry a book and no candidate.
- **kept** is counted from `judge`/`ok` lines (a book judged in) and compared with the queue's rows that are `kept`. A row is `kept` from the moment a book is filed (spec: `kept` means a book exists), a held book keeps its row `kept` by design, and a book that waits for its judgement has its row `kept` too. So the two halves count different things, and a hold always makes them differ.

When this plan is done, the same healthy run says the same on both sides, and a run that really differs (a book that is in the log and not in the queue, or the reverse) still says DIFFERENT. The rule:

- **kept**: the log's side is the distinct books of the `capture`/`ok` lines (the capture that filed a book, which is when the queue's row becomes `kept`), compared with the queue's `kept` rows. Both are "a book was filed". The report's own line "Kept" (judge lines that say ok) stays as a number of the day and is relabelled "Judged in", since that is what it counts.
- **rejected**: the log's side is the distinct items rejected by a `reject` line or a `judge`/`rejected` line, each counted once (by its book when the line names one, else by its candidate), compared with the queue's `rejected` rows that are not rejected for their type (as now).
- **failed** is unchanged.

## Scope

**Changed:** `engine/kb/crawlreport.py` (`_counts`, the comparison, the labels of the numbers and of the comparison in `render`), `engine/tests/test_crawlreport.py`, `engine/tests/test_crawlchain.py` (the three assertions that pin the old numbers, and one that shows the comparison is the same for the healthy run).

**Not changed:** the steps and what they write to the log or the queue, `crawlstatus.py`, the spec's statuses, the report's other sections.

## Non-goals

- A change to what a step writes (for example a `reject` line from the judge). The writers match the spec; the report is what changes.
- A comparison across days. The queue holds the current status of a row, not its history, so a book kept on one day and judged out the next differs on the first day's report; the report says this already in its comparison text, and this plan does not change it.

## Assumptions and constraints

- The `capture`/`ok` line names the book it filed (`crawlreport._filed` already reads it that way) and is written when the row becomes `kept`.
- A `judge`/`rejected` line names the candidate and the book; a `reject` line names the book.
- The whole-chain test of the readers (`TheOtherMachinesReaders` in `test_crawlchain.py`) holds a good book, a held book, a judged-out book and an unplaced book, and is the check that the comparison is the same for a healthy run.
- No model, network or owner file is used by any test.

## Completion criteria

1. For the chain test's library (a good book, a held book, a judged-out book, an unplaced book) every row of the comparison says the same.
2. A log line with no matching queue row, and a queue row with no log line (a book filed in only one of them, a rejection in only one), still gives DIFFERENT for that row.
3. The numbers of the day label what they count ("Judged in", and the rejected line says which lines it counts); a held book is counted in the report's held section as before.
4. `wb run code-work check` passes; the tests of `crawlreport`, `crawlstatus` and `crawlchain` pass.
5. The owner has read the result.

## Increments

### Increment A — Count kept and rejected the way the steps write them

**Outcome:** the comparison of the log and the queue is the same for a healthy run and different for a run that really differs.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlreport.py`, `engine/tests/test_crawlreport.py`, `engine/tests/test_crawlchain.py`.
**Steps:**
1. Read `_counts`, `_filed`, `_queue_facts`, `_compare` and `render`, the report tests of the comparison, and the three assertions of `test_crawlchain.py` that pin the old numbers; write in the Result which lines the steps write for each kind of book.
2. Tests first: a day with a good book, a held book, a judged-out book (`judge`/`rejected`), a book weeded at the scan (a `reject` line) and a book waiting for its judgement gives the same on every row of the comparison; a rejection counted once when both a `reject` line and a `judge`/`rejected` line name one book; a book filed in the log only, and one in the queue only, give DIFFERENT; a rejection in the log only, and in the queue only, give DIFFERENT; the rows rejected for their type are not in the comparison, as now; the labels of the numbers say what they count.
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result; update the three assertions of the chain tests and add the one that shows the comparison is the same.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlreport engine.tests.test_crawlstatus engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-count-the-crawl-report-the-way-the-steps-write-the-log#A`.

## Verification for the plan as a whole

The increment's recorded verification stands. Nothing else reads the counts of the report (`crawlstatus.py` does not), which is confirmed by a search at the start of the increment. The engine's whole suite is not rerun.

## Risks and sensitive actions

None identified: the report reads the log and the queue and writes only its own file, as before. A wrong rule would only mislead the owner's reading of a report, which is why a run that really differs must still say DIFFERENT (criterion 2).

## Review record

Empty until a review is asked for.

## Deferred work

The comparison across days (a book kept on one day and judged out on the next) is not changed: see the non-goals.

## Result

### Increment A — Count kept and rejected the way the steps write them (verified, not committed)

- Changed `engine/kb/crawlreport.py` (`_item`, `_counts`, `_compare`, and two lines of `render`), `engine/tests/test_crawlreport.py` and `engine/tests/test_crawlchain.py` (three assertions in the reader test). Verification: the plan's line (`test_crawlreport`, `test_crawlstatus`, `test_crawlchain`), 524 tests, OK; `wb run code-work check` and `git diff --check` clean. A search at the start confirmed that nothing but `crawlreport.py` reads `counts["kept"]` of the report.
- **What the steps write (step 1).** A book **filed**: `capture`/`ok` with the book. A book **held**: a `hold` line only (its row stays `kept`). A book **judged in**: `judge`/`ok`. A book **judged out**, and a book **parked at the judge**: `judge`/`rejected` with the candidate and the book (the row becomes `rejected`). A book **weeded at the scan, the convert or a parking in the convert step**: a `reject` line with the book and no candidate (the row becomes `rejected`). A candidate **that fetch itself refuses** (a duplicate of a held book, a PDF, a page over the size limit, an address not usable, a blocked class): `fetch`/`rejected` or `fetch`/`blocked` with the candidate, and no book of its own (the row becomes `rejected`). A book **parked at the card or the proposal**: a `card` or `propose` line `rejected`, and **its row stays `kept`**.
- **The rule as built, with two differences from the approved plan text** (the approved body cannot change; the owner should read these): (1) the log's kept side is **the books filed (`capture`/`ok`) that no `reject` line and no `judge`/`rejected` line names** (`counts["standing"]`), not all the books filed: the whole-chain library showed that a book filed and judged out the same day has a capture line while its row is `rejected`; (2) the log's rejected side **also counts the candidates that fetch itself refused** (`fetch`/`rejected` and `fetch`/`blocked` lines, by candidate: such a line may name an earlier book that the candidate repeated, so it is never counted as a rejection of that book and never takes it away from the books that stand), which the review found (finding 1): the queue's rows for them are `rejected` too, and a day with a duplicate or a PDF would have said DIFFERENT. A rejection is counted once by its book (a `reject` or `judge` line) or by its candidate (a fetch line, or a line with no book); a line that names neither is one of its own.
- **The chain library** (a good, a held, a judged-out and an unplaced book) says the same on every row: kept 3 and 3, rejected 1 and 1, failed 0 and 0; the report's own number "Kept" is relabelled "Judged in" (2 there).
- Deliberate breaks: 26 single mutations of the new code, bytecode caching off; four survived the first 17 and were real gaps (a line that names neither book nor candidate, a judge line that is not `rejected`, a capture that is not `ok`, the explanatory line), one more after the fetch lines were added (a fetch line keyed by its book); each closed by a test and killed.
- Review (`reviewer`, one exchange): no blocking finding. **Applied:** the fetch-time refusals (finding 1), a test for a book parked after the card or the proposal (finding 6), the misplaced docstring of `_compare` (finding 5). **Recorded, not changed:** (1) **the comparison is of counts, not of sets**: one book in the log only and another in the queue only agree in a count; the report lists each book with `seen_in` (log, queue, both), but a judged-out book is `log` too, so `log` alone does not tell an orphan from a rejection (a fuller report could mark which books the log shows rejected: not built); (2) narrow paths that still differ: a book adopted from an earlier try (a crash between the filing and the row) has a `kept` row and no capture line, so `standing` is lower by one; `_finish_rejections` rejects a row after a death and writes no line, so the queue has one more rejection; `_reject` and `_failed_try` write their `reject` line even when the row was not `kept` (a log-only rejection); (3) a book filed on one day and rejected on a later day still differs on the first day's report, the plan's non-goal (the queue holds the current status), pinned by a test.
- Not run: the engine's other tests.
