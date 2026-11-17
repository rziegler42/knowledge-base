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

Empty until work starts.
