# Bring the card maker's task tests up to date

Status: Completed
Created: 2026-11-16
Candidate: none (a correction that follows from a finding of the engine's whole test run on 2026-11-16, too small to need roadmap direction)
Specs: docs/specs/models.md

## Goal

Two tests of the card maker, `test_the_jobs_are_the_kinds_of_work_the_engine_knows` in `engine/tests/test_cardmake.py` and in `engine/tests/test_cardmake_earlier.py`, say that the card maker's jobs are every kind of model work the engine knows (`models.TASKS`) except the two theme tasks. Two more kinds of work have been added since: `place`, by the plan that proposes a shelf for each book, and `crawl-query`, by the plan that finds candidates for the unattended crawl. Neither is the work of a card, and both are optional tasks that may be left unset. The two tests fail on the names `place` and `crawl-query`, and the engine's whole test run (4,328 tests) shows no other failure.

When this plan is done, the two tests name the tasks that are not a card's work (`theme`, `theme-check`, `place`, `crawl-query`) and pass, and nothing else changes.

## Scope

- `engine/tests/test_cardmake.py` and `engine/tests/test_cardmake_earlier.py`: one line each, the set of names that is taken out of `models.TASKS`.

## Non-goals

- Changing `models.TASKS`, the card maker's jobs or any code of the engine.
- Making the tests find the non-card tasks by themselves. The explicit list is the point of the test: a new kind of work must be named there on purpose.
- The `ResourceWarning` noise that the whole run printed from `test_convert.py` (files opened and not closed in a test): its own item on the owner's todo list.

## Assumptions and constraints

- The whole test run on the merged tree (4,328 tests, 2 failures, 251 skipped) is the evidence that these are the only failures. At the commit before the merge the same two tests failed on `place` alone.
- A code edit passes the workbench gate only when every approved or in-progress plan of the checkout is approved on this machine. Plan D is approved here; the parked clause-check plan is approved here.

## Completion criteria

1. Both tests pass, and every other test of `test_cardmake`, `test_cardmake_earlier` and `test_models` still passes.
2. The only files that change are the two test files and this plan.
3. `wb run code-work check` passes.

## Increments

### Increment A — Name the tasks that are not a card's work

**Outcome:** the two tests exclude `place` and `crawl-query` as well as the theme tasks, and pass.
**Dependencies:** none.
**Affected areas:** `engine/tests/test_cardmake.py` (line 1687 to 1689), `engine/tests/test_cardmake_earlier.py` (the test of the same name).
**Steps:**
1. Run the two tests and see them fail on exactly the names `place` and `crawl-query`.
2. In each test, add `"place"` and `"crawl-query"` to the set that is taken out of `set(models.TASKS)`, and say in the comment that they are the kinds of work of the placement of a book and of the crawl's queries.
3. Run the verification.
4. Have the `reviewer` read the two lines; record the result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_cardmake_earlier engine.tests.test_models`; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-bring-the-card-maker-task-tests-up-to-date#A`.

## Verification for the plan as a whole

The increment's verification stands. `git diff --name-status` between the commit before the plan and the last commit shows only the two test files and this plan. The engine's other tests are not rerun: nothing else changes.

## Risks and sensitive actions

None identified. Only test files change, by one line each.

## Review record

- Increment A: read by the `reviewer` agent, one exchange. No finding. It read `models.py` (the required and optional tasks, and that `EMBED_TASKS` is separate and not in `TASKS`) and the jobs of `cardmake.py`, and found that the card jobs are exactly `card-notes`, `card`, `card-check` and `card-more`, that `TASKS` minus the four named tasks is exactly that set, and that the test still fails if a new card job or a new non-card task is added without being named. Not checked by it: it cannot run tests, and it did not run `git diff`; both are recorded below.

## Deferred work

- The `ResourceWarning` noise from `test_convert.py` (see Non-goals), on the owner's todo list.

## Result

### Increment A — Name the tasks that are not a card's work

- Before the edit, `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake.JobTest.test_the_jobs_are_the_kinds_of_work_the_engine_knows engine.tests.test_cardmake_earlier.JobTest.test_the_jobs_are_the_kinds_of_work_the_engine_knows`: both failed, with exactly `place` and `crawl-query` as the names in `models.TASKS` that the card jobs do not cover.
- Changed: one line in `engine/tests/test_cardmake.py` and one in `engine/tests/test_cardmake_earlier.py`: `"place"` and `"crawl-query"` are taken out of `set(models.TASKS)` with the two theme tasks, and the comment names them. `git diff --stat`: 2 files, 2 insertions, 2 deletions.
- After: `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_cardmake_earlier engine.tests.test_models`: **Ran 558 tests, OK.** `wb run code-work check`: no problems.
- Review: see the Review record. No finding.

### The whole plan

- The increment's verification stands. The files that differ from the commit before this plan are the two test files and this plan, and nothing else. The engine's other tests were not rerun (nothing else changes); the whole-engine run of 2026-11-16 (4,328 tests) is what showed these two as the only failures.
- Completion criteria: (1) both tests pass and the others of the three files still pass: met; (2) only the two test files and this plan change: met; (3) `wb run code-work check` passes: met.
