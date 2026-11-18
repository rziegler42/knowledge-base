# Stop a long shelf name from ending the unattended judge step

Status: Proposed
Created: 2026-11-18
Candidate: none (a correction that follows from a finding: the first day of the unattended crawl showed 14 of 24 runs ended early with the judge refusal; the cause was read from the run with the hidden error shown)
Specs: docs/specs/population.md

## Goal

The judge step writes a log line for each book it keeps (`score 0.560 shelf <shelf name>`) and for each book it rejects (`the best shelf is <shelf name> at 0.434, under the threshold 0.45`). The log writer (`crawllog.Log._text`) refuses any text that holds a run of 40 or more characters of letters, digits and `_ + / = -` that is not all hex, because such a run looks like a key. **1215 of the library's 4534 shelf names are 40 characters or longer** (for example `wnt-beta-catenin-signaling-in-development-and-cancer`). For a book whose best shelf has such a name the log line raises `KbError`, and the judge step takes any `KbError` that is not a model failure for a refusal and ends the run with "the judgement cannot be made: the embedding entry or the shelf vectors are not set up" (the real error is hidden by the step). The verdict is already recorded when the line is written (`record_judged`, `weed`), so no book is lost, but the run ends before its cards, move, refill and fetch steps. 14 of 24 runs of the first full day ended this way.

When this plan is done the judge step's log lines show a shelf name cut to a length the log accepts, and the run goes on. The credential check of the log is **not** changed. The events and the queue keep the whole name and the whole reason, as now.

## Scope

**Changed:** `engine/kb/crawljudge.py` (the local `line` function of `judge_book`, and the one place that writes the "already rejected" line, which go through one small function that cuts a run of 40 or more name characters in the reason to its first 36 characters followed by `...`), `engine/tests/test_crawljudge.py`, `docs/specs/population.md` (one sentence).

**Not changed:** `crawllog` and its credential check, the events, the queue's reasons, the shelves and their names, the judgement, the threshold, every other step.

## Non-goals

- Renaming shelves, or limiting their name length.
- Making the judge step tell a log failure apart from a settings refusal in its message (a separate defect: the step's fixed text hid this cause for a day). It is put on the owner's list.
- Looking for other log lines that may carry a long name. A read of the crawl steps found none that carry a shelf name; a move by the model's pick is off in the approved plan.

## Assumptions and constraints

- A run of 40 or more name characters is exactly what `crawllog._LONG` searches; a cut name of 36 characters then `...` has no such run (`.` is not in its class).
- A reason is cut for the log only; `crawlbooks.record_judged`, `weed` and the queue get the full text.
- No test uses the network, a real model, the owner's library or config.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. A book whose best shelf has a name of 40 or more characters is judged, its verdict recorded with the full name, and a judge log line is written with the name cut; the step does not refuse. The same holds for a rejection and for the "already rejected" line.
2. A shelf name under 40 characters is logged as before, unchanged.
3. The event, the queue's reason and the book's record hold the full name.
4. `wb run code-work check` passes and the tests of the module changed pass.
5. The owner has read the result.

## Increments

### Increment A — Cut a long shelf name in the judge's log lines

**Outcome:** the judge step goes on after a book whose best shelf has a long name.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawljudge.py`, `engine/tests/test_crawljudge.py`, `docs/specs/population.md`.
**Steps:**
1. Read `crawljudge.judge_book` (`line`, `weed`, the already-rejected branch), `crawllog._text` and `_LONG`, and the nearest tests in `test_crawljudge`.
2. Tests first, seen failing: with a shelf whose name is 52 characters, a kept book, a rejected book and an already-rejected book each end with their outcome and not a `KbError`; the log line holds the name cut; the recorded event and the queue reason hold the full name; a 39-character name is logged whole.
3. Write the change: one small function that cuts each run of 40 or more name characters in a reason to 36 characters and `...`, used by `line`. Deliberate breaks (the cut length, the cut not applied to the reject line, the cut applied to what is recorded); the `reviewer`'s reading; the Result; the sentence of the spec.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawljudge engine.tests.test_crawllog engine.tests.test_crawlsteps`; the breaks; `wb run code-work check`. A wider run is not needed: only the text of three log lines changes, and the three modules cover the writer and the step that takes the refusal.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-18-stop-a-long-shelf-name-from-ending-the-judge-step#A`.

## Verification for the plan as a whole

The one increment's verification stands. A read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again** (the engine code changed).

## Risks and sensitive actions

- A logged name is cut, so two long names with the same first 36 characters look alike in the log; the book's events keep the full name.
- The change of the code makes the approval of the crawl plan stale; the runs refuse until the owner approves again, which is his act.

## Review record

- **Reviewer:** the `reviewer` agent, one round of the cap, no blocking finding.
- **Applied:** the Result says that the log's check is no longer the guard for the three judge line sites that go through `logged()` (see below).
- **Rejected, with reason:** (a) the judge's two other log writes (`charge_failed_try`, parked, and `why`) are not cut: their reasons are fixed sentences from `fail_step` or a forced one of two texts, and no shelf name reaches them; the plan's scope names the one place of the already-rejected line. (b) A secret named to the log that sits past the 36th character of a 40+ run would no longer be seen by the log's secret search: nothing writes a configured secret into a judge reason today.
- **Left for the owner:** nothing. The reviewer could not run programs, the plan check, or read the whole spec line; those were run by the agent that made the change (below).

## Deferred work

A judge step that names the real cause of a refusal (a log failure is not a settings fault); the discovery's day (UTC) against the plan's day (local).

## Result

### Increment A — Cut a long shelf name in the judge's log lines (verified, not committed)

- **Changed (in a separate copy of the tree, moved to the main tree when the owner says to commit):** `engine/kb/crawljudge.py` (`logged()` and `_LONG_NAME`: each run of 40 or more name characters in a reason is cut to its first 36 and `...`; the local `line` of `judge_book` gives the log `logged(reason)`; the events, the queue and the returned reason are not cut), `engine/tests/test_crawljudge.py` (four tests: a kept book, a rejected book and a rejection finished later, each with a 52-character shelf name, are judged, the full name is recorded and the line shows it cut; a name of 39 characters is logged whole and one of 40 is cut), `docs/specs/population.md` (one sentence at the log paragraph).
- **Seen failing first:** the four tests failed with the log's "looks like a credential" refusal before the change.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawljudge engine.tests.test_crawllog engine.tests.test_crawlsteps` gave 275 tests OK. Five deliberate single changes (the cut length, the `{40,}` boundary, the log given the whole reason, the recorded reason cut, the dots dropped) were each caught by the judge tests and the file was restored byte for byte. `git diff --check` clean. Not run: the whole suite (only the text of three log lines changes).
- **Reviewer's observation recorded:** `logged()` cuts every run of 40 or more name characters in these reasons, a hex run too; the log's own check is therefore no longer the guard for the three judge lines that use it. The reasons are fixed sentences and shelf names, none is page text. The log's other checks (header, bearer, basic, userinfo, query, JWT, AWS) still run on the cut text.
- **Not done:** the judge step still turns a failure of the log into the settings refusal (on the owner's todo list); the discovery day (UTC) against the plan's day.
