# Lengthen the idle window of the crawl once the day's fetches are used up

Status: Completed
Created: 2026-11-19
Candidate: none (a correction that follows from a finding: the idle window of plan `2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave` has one length whatever the crawl has to do, and on a day when the crawl has nothing to fetch the window is the only work left and is too short for a backlog of themes)
Specs: docs/specs/population.md ("The idle window", "The crawl plan", acceptance criterion 20)

## Goal

A run of the crawl ends with an idle window of at most `themes_window_s` seconds (the owner's plan sets 300), of which the themes take 60 percent, and the loop then sleeps 60 seconds and starts the next run. The window is short on purpose, so that the crawler gets its turn. **When the day's ceiling of fetches is used up there is no turn to give**: no new book can arrive until the day ends, so the runs between are lists, a check, an empty fetch and the window.

Measured on 2026-11-19, read only, from the log of the crawl (`crawl-2026-11-19.jsonl`) and the library, at commit `f91c62f` of `main`, by scripts of Python 3.15.0 that printed counts and seconds: the ceiling was used up (400 of 400 fetches) within minutes of the restart at 22:47Z, after the 19 fetches that were left, and stayed so to the end of the day (05:00Z, midnight of the owner's zone); five windows between 22:52Z and 23:22Z ended at their deadline after 189 to 216 seconds each and made themes for 5 books in all (3, 0, 2, 0, 0), about 2 minutes of theme work in each cycle of about 7 minutes; about 257 active books had a card and no themes (the 207 books of the old library and the 59 electronics books, loaded that day); a whole book of 34 pieces and 109 themes took about 406 seconds in an earlier measurement (the plan of the idle window), so a window of 300 seconds cannot finish a large book, and the backlog at that rate is about 30 hours.

When this plan is done, **a window is longer when the day's fetches are used up**: a new key `themes_window_full_s` of the plan's `[idle]` section (a whole number of seconds from 0 to 3600, default 3600) gives the length of the window in a run that begins its window with the ceiling `fetches_per_day` of the day used up. The window is then the earliest of `themes_window_full_s`, the run's own time budget and **the end of the crawl's day** (so that no work of the window **starts** after the ceiling resets, and whichever run the loop or the scheduler starts next finds the new day's fetches; like every deadline of the window it is cooperative: a call of a model that began before the end of the day may finish after it, and nothing new begins), and in every other run it is `themes_window_s` as today. **When that next run starts is the business of the loop or the scheduler and not of the engine**: the owner's loop sleeps 60 seconds between runs, and the scheduling text of the spec fires a run every 15 minutes, so the plan promises that the window ends at the day's end and nothing about when the next run begins. With `themes_window_s` at 0 there is still no window (the switch that turns the idle work off stays one switch), and with `themes_window_full_s` at 0 the window is the same in both cases.

## Scope

- `engine/kb/crawlplan.py`: the key `themes_window_full_s` and a function that gives the end of the day of an aware time in the plan's zone.
- `engine/kb/crawlidle.py`: the choice of the window's length at the start of the step.
- `engine/kb/crawlapprove.py` and `engine/kb/crawlrun.py`: the words of the approval preview and of the dry run, which say what the window is.
- `engine/tests/test_crawlidle.py`, `engine/tests/test_crawlplan.py`, and the tests of the preview and the dry run.
- `docs/specs/population.md`: the idle window, the plan's example, acceptance criterion 20.

## Non-goals

- Any change to what the window does (the themes, the vectors, the repair of the weave), to the share of the themes (60 percent), to the run's time budget (`RUN_SECONDS`, one hour), or to the loop outside the engine.
- Other ceilings: only the day's ceiling of fetches counts. The ceiling of cards, the total of books filed, and a queue with nothing in it do not lengthen the window.
- Anything the owner can do by hand: `themes-run` and the plan's `themes_window_s` stay as they are.
- The loop and the scheduler (the sleep between runs, the text of `crawl-schedule-text`, launchd): when a run starts is not changed or promised by this plan.

## Assumptions and constraints

- The ceiling is read the way `crawlstate.ceilings` reads it, from the counters of the day in the queue, without changing anything. **A failure to read it means "not used up"**: the window is the short one, never the long one by mistake. The boundary is narrow and stated: an error of the queue read, which is a `KbError` (the plan's own checks of the numbers) **or a `sqlite3.Error`** (a closed connection raises `sqlite3.ProgrammingError`, a locked or damaged queue `sqlite3.OperationalError` or `DatabaseError`), is an unreadable counter; any other error is a fault of the code and **propagates** as every error of the step does (the window's own `idle` line is still written by its `finally`).
- The end of the day is the start of the next day in the plan's zone (`local` is the machine's zone), found with the same zone code that `crawlplan.day_of` uses. A window that is still going when the day changes ends there, so that the next run, which starts a new day's counters, may fetch at once.
- What already ends a window is unchanged and is looked at before each call of a model as now: the stop file, a disk floor, and the time. A stop file made in the middle of a long window ends it before the next call.
- The long window holds the lock of the card queue (`cardstate.lock`, taken by `themerun.run`) for as long as the themes run, as a short one does between its calls. A manual `cards-queue` or `themes-run` started during a window is refused until the window ends (at most one hour, or at once with the stop file). The owner already makes the stop file before a manual run of those commands; the plan says so in the spec.
- The run's steps before the window are not changed: a crawl book that needs a card, a proposal or a move is dealt with at the start of the run, and during the window no new book arrives (no fetch is possible), so nothing waits for the window to end.
- This is a change to `engine/kb`, so it **voids the approval of the running crawl** when its files reach `main`, and the plan's example and the preview change. It is built in a separate worktree and copied to `main` in one step, after the owner is told, and should be bundled with other changes so that the owner approves once. The new key has a default, so a plan file that does not name it is still valid; the owner's approval of the plan is renewed all the same, as for every change of the engine.

## Completion criteria

1. `themes_window_full_s` is a key of the `[idle]` section, a whole number from 0 to 3600, default 3600; a plan with it over 3600, negative, not a whole number or a boolean is refused as the other keys are; the approval preview and the dry run say the two lengths and when each applies.
2. In a run whose day has used up `fetches_per_day` the window is the earliest of `themes_window_full_s`, the run's deadline and the end of the day; in a run whose day has not, it is `themes_window_s`, byte for byte as before.
3. With `themes_window_s` at 0 there is no window whatever `themes_window_full_s` says; with `themes_window_full_s` at 0 the window is `themes_window_s` in both cases.
4. A window that reaches the end of the day starts no further call of a model after it (a call in flight is let finish, as at every deadline of the window); a window with the stop file made in the middle ends before the next call of a model.
5. A counter that cannot be read gives the short window.
6. The tests of the area and `wb run code-work check` pass; and in the owner's log, after the ceiling is used up, an `idle` line shows a window of more than `themes_window_s` seconds (up to the new length), the last call of a model of a window that reached the end of the day began before it (its `idle` line may be written a few seconds after, by the call in flight), and the first run that the loop starts after midnight fetches again (the counters of the new day).

## Increments

### Increment A — The key, the end of the day and the words

**Outcome:** `themes_window_full_s` is a key of the plan with its checks, `crawlplan.day_end(now, timezone)` gives the start of the next day, and the preview and the dry run name the two windows.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlplan.py`, `engine/kb/crawlapprove.py`, `engine/kb/crawlrun.py`, and their tests.
**Steps:**
1. Read `crawlplan` (`PLAN`, the checks of a whole number with limits, `day_of`, the example text), `crawlapprove` (the preview lines and where `themes_window_s` is named) and `crawlrun` (the dry-run text), and the tests that name `themes_window_s`; write in the Result the places that must change and the exact wording of each.
2. Tests first, each seen to fail for the right reason: (a) the key with 0, 1, 3600 and the default is accepted, and -1, 3601, 1.5, `"10"`, `None` and `True` are refused; (b) `day_end` gives the start of the next day for `local`, for `UTC` and for a zone with an offset (`America/New_York`), for a time one second before the end and one second after the start, across a month and a year, and for a day with a change of the clock (the day of 2026-11-01 in `America/New_York` is 25 hours and the day of 2026-03-08 is 23), and refuses a time with no zone and an unknown zone as `day_of` does; (c) the preview says both lengths, and says "no window" when `themes_window_s` is 0 whatever the other says, and the same for the dry run; (d) an old plan file with no such key has the default and the same digest as a plan that names the default (the approval fingerprint reads the values, as for the other keys).
3. Add the key (section `idle`, kind `int`, default 3600, limits 0 and 3600) and `day_end`; change the preview and the dry-run words.
4. Deliberate single changes, each compile-checked and restored byte for byte, each caught by a test: the upper limit; the default; the zone of `day_end`; the day of 25 hours; the word in the preview.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlplan engine.tests.test_crawlapprove engine.tests.test_crawlrun` (and the tests that name the plan's keys, found in step 1) and the deliberate changes; `wb run code-work check`; `git diff --check`. A wider run is not needed: nothing outside the plan, the preview and the dry-run text changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-19-lengthen-the-idle-window-once-the-days-fetches-are-used-up#A`.

### Increment B — The choice of the window, and the spec

**Outcome:** the idle step uses the long window when the day's fetches are used up, as criteria 2 to 5 say; the spec says so.
**Dependencies:** Increment A.
**Affected areas:** `engine/kb/crawlidle.py`, `engine/tests/test_crawlidle.py`, `docs/specs/population.md`.
**Steps:**
1. Read `crawlidle.make_step` (the window, `THEMES_SHARE`, `stopper`), `crawlstate.ceilings`, `crawlrun` (where `ctx.conn`, `ctx.deadline` and the clock are set) and the existing tests of the window, and write in the Result the exact place of the new choice and how the test context carries a queue connection.
2. Tests first, with the fake model server and the injected clock of `test_crawlidle`, each seen to fail for the right reason: (a) with the ceiling used up the window is `themes_window_full_s`, and a book whose themes need more than `themes_window_s` is finished inside it; (b) with the ceiling not used up the window is `themes_window_s` and the lines of the log are the same as before; (c) the window is cut by the run's deadline and by the end of the day when either is earlier, and **a call of a model that begins before the end of the day and ends after it (the injected clock moves past it inside the fake call) is let finish and no later call, of the themes, the vectors or the weave, begins**; (d) with `themes_window_s` at 0 there is no window with the ceiling used up, and with `themes_window_full_s` at 0 the window is `themes_window_s` with the ceiling used up; (e) a counter that raises `KbError`, one that raises `sqlite3.OperationalError` (database is locked), a queue connection that is closed (`sqlite3.ProgrammingError`) and a day with no counters give the short window and no error, while an error of another kind from the read (a `RuntimeError` put in its place) propagates out of the step and the `idle` line is written all the same; (f) the stop file made in the middle of a long window prevents the next call of a model, and the `idle` line says `stopped`; (g) the ceiling used up by one fetch short of the limit (399 of 400) gives the short window and at the limit the long one; (h) the share of the themes (60 percent) and the vectors and the weave steps are the same in the long window as in the short one (the same code paths, shown by the log lines).
3. Add the choice at the start of `step` (read the ceiling with `crawlstate.ceilings` inside a `try` that catches `KbError` and `sqlite3.Error` and nothing else, compare `fetch` used with its limit, take the earliest of the three ends with the day's end from `crawlplan.day_end`).
4. Deliberate single changes, each compile-checked and restored byte for byte, each caught by a test: the comparison (`>=` to `>`); a failure to read the counter giving the long window; the cut at the end of the day; the cut at the run's deadline; the catch of `sqlite3.Error` (removed, the closed connection propagates); the catch widened to `Exception` (the `RuntimeError` is swallowed); the check for a window of 0; the use of `themes_window_full_s` with the ceiling not used up.
5. Edit the spec: the idle window section (the two lengths and when each applies, the end of the day, the lock held for up to an hour, the stop file before a manual run), the plan's example (`[idle]`), and acceptance criterion 20.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlidle engine.tests.test_crawlstate engine.tests.test_crawlrun engine.tests.test_crawlplan` and the deliberate changes; `wb run code-work check`; `git diff --check`. A wider run is not needed: the window's own work is not changed, and only its length is chosen differently.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-19-lengthen-the-idle-window-once-the-days-fetches-are-used-up#B`.

## Verification for the plan as a whole

Increment A's recorded verification still stands unless Increment B changed the plan code, which it does not. After both: `wb run code-work check`. The one run that the tests cannot show is on the owner's log, on a day when the ceiling is used up: the first `idle` line after it shows a window longer than `themes_window_s` and no longer than `themes_window_full_s`, a window that reached midnight starts no call after it, and the first run that the loop starts after midnight fetches (the start of that run is the loop's, within its sleep of 60 seconds). The owner reads it, with the log lines of `idle`, `themes`, `theme_vectors` and `weave`.

## Risks and sensitive actions

- **A long hold of the lock of the card queue and of `ned`.** A window of up to an hour keeps the card queue's lock and the model server busy, and a manual `cards-queue` or `themes-run` is refused meanwhile. The stop file ends a window before its next call of a model, and the owner makes it before a manual run already. The spec says so, and the log shows the window as it runs.
- **Reading a count that decides the length.** The count is a number read from the owner's own queue; a wrong count can only make a window short or long, never skip a check, and any failure to read it gives the short window.
- **The approval of the crawl is voided** when the files reach `main`, and the owner is told first. Bundled with other changes of the engine, one approval covers all.
- **The end of the day.** A time zone error could make a window run past the day's end. The window is also cut by the run's one-hour budget, and a test of the days with a change of the clock covers the two days of the year that differ in length. A security review is not asked for: no input from outside, no path, no network, no parsing; the owner decides.

## Review record

Plan review with the review engine (`review-plan`; model `gpt-5.6-terra` for rounds 1 and 2, `gpt-6.1-sol` for round 3): 3 of 3 rounds used (the bound), 3 findings, all applied, none rejected. After round 3 the plan was corrected and **no fourth round was run**, so the last correction has not been read by the reviewer.
- **Round 1.** The plan promised that the first run after midnight would begin on time, but the start of a run belongs to the owner's loop (a sleep of 60 seconds) or to the scheduler (the spec's text fires every 15 minutes), and the plan leaves both alone. It now promises only what the engine controls, and the acceptance reads the log for a fetch after midnight.
- **Round 2.** A closed queue connection raises `sqlite3.ProgrammingError`, not `KbError`, so the planned fallback to the short window did not hold. The boundary is now stated: `KbError` and `sqlite3.Error` mean an unreadable counter and give the short window, and any other error propagates; tests and breaks cover both sides.
- **Round 3.** The end of the day is a cooperative deadline like every other of the window: no new call starts after it, and a call in flight may finish. The goal, criteria 4 and 6 and the acceptance say so, and a test lets a call cross midnight.
- Left for the owner: whether to ask for a fourth round (`wb run review-engine extend`, which is the owner's), and the approval.

## Deferred work

- A rule for other days when the crawl has nothing to fetch (the queue is empty, or the total of books filed is reached); and a window that stays long while the ceiling is used up but ends when a kept book of the crawl needs a card.
- A report line of the length of the window in `crawl-status` and the daily report.

## Result

### Increment A

Built in a separate worktree (`wt-window`, branch `long-window`, from `534ebab`), so that the approval of the running crawl was not voided while it was written and reviewed; copied to `main` and committed with the word of the owner (the copy voided the approval of the crawl).

**Step 1, what was read.** The places that change: `crawlplan.PLAN` (the key, section `idle`), `crawlplan.day_of` (the zone code that `day_end` reuses), the preview line `Idle window:` of `crawlapprove` and the dry-run sentence of `crawlrun`; the tests that name `themes_window_s` are those of `test_crawlplan` (the defaults, the values, the section), `test_crawlapprove` (the preview and the digest) and `test_crawlrun` (the dry run).

**What was done.** `engine/kb/crawlplan.py`: the key `themes_window_full_s` (section `idle`, whole number from 0 to 3600, default 3600) and `day_end(now, timezone)`, which gives the start of the next day in the plan's zone as an **instant in UTC** (`local` is the machine's zone, with its changes of the clock); `engine/kb/crawlapprove.py` and `engine/kb/crawlrun.py`: the sentences of the preview and the dry run, which name both lengths; the tests of the three modules.

**Departures from the plan's wording, for the owner to accept.**
1. The plan's test (d) said that a plan which names the default digests the same as one that does not. That is not how the approval digest works (it covers the text of the plan file, for every key, as was checked on the existing key `themes_window_s`), so the test says what is true: a plan with no key has the default, and each other value changes the digest.
2. `day_end` returns UTC and not the zone of the plan (from the review of this increment): two times that share one zone object are compared by their wall clocks, which is wrong across a change of the clock, and Increment B subtracts and compares it with the run's clock.

**Verification run (in the worktree).** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlplan engine.tests.test_crawlapprove engine.tests.test_crawlrun` (and the schedule, status and idle modules) passed; the new tests were written first and failed for the right reason. Fourteen deliberate single changes of the three code files (the limits, the default and the section of the key, the zone and the next-day arithmetic of `day_end`, the `local` branch, the day taken from the time, the conversion to UTC, and the words of the preview and of the dry run) were each compile-checked, each made a test fail, and the files were restored byte for byte; two were missed at first (the dry-run words) and the tests were made exact. **Review:** `reviewer`, one exchange: no blocking finding; applied: the test of the preview now reads `up to 600 seconds` (the number 600 is also in 3600), and `day_end` returns UTC. **Not run:** `wb run code-work check` (in `main`, after the copy).

### Increment B

Built in the same worktree, on top of Increment A.

**Step 1, what was read.** `crawlidle.make_step` (the window, `THEMES_SHARE`, `stopper`), `crawlstate.ceilings`, `crawlrun._steps` (the real context carries `conn` and a `deadline` that is the start of the steps plus `RUN_SECONDS`, and the clock is UTC) and the existing tests of the window; the test context of `test_crawlidle` has no `conn`, so a context with no queue is the short window, which keeps the earlier tests as they were. The new choice is `crawlidle._long_end(ctx, began)`, used at the start of `step` after the check for a window of 0.

**What was done.** `engine/kb/crawlidle.py`: `_long_end` and its use (the window is the earliest of `themes_window_full_s`, the run's deadline and the end of the day when the day's `fetch` counter has reached its limit; `KbError` and `sqlite3.Error` from the read mean the short window; any other error propagates and the window's own line says `failed`); `engine/tests/test_crawlidle.py`: the class `LongWindowTest` (13 tests, with a real queue and a fake clock); `docs/specs/population.md`: the plan's example, the setting, the deadline, the safeguards and acceptance criterion 20.

**Verification run (in the worktree).** `python3 -B -W error::ResourceWarning -m unittest` of the idle, plan, approve, run, state, schedule, status, report, steps and fetch modules: 1,218 tests, OK; the new tests were written first and failed for the right reason. Thirteen deliberate single changes of `crawlidle.py` (the comparison with the limit, the limit taken as not reached, an unreadable counter giving the long window, the cut at the end of the day, the cut at the run's deadline, the length used, the window of 0, the long window of 0, a context with no queue, the catch of a database error, of a plan error, the catch widened to every error, and the line of a fault in the read) were each compile-checked, each made a test fail, and the file was restored byte for byte. **Review:** `reviewer`, one exchange: no blocking finding; applied: the spec says the lock of the card queue is held while a batch of themes runs (up to 20 books), not until the window ends, and that a long window below the short one is the shorter window of a used-up day (the rule is "earliest of", as the plan says); tests for a day with no counter row and for a long window below the short one. **Recorded, not changed:** a long window sizes the vectors batch to the time left, so one build can embed about 2,000 texts, and a stop file or the end of the day during it discards the build (nothing is unsafe, the stop is looked at about every 20 seconds); a todo item is added. A non-UTC zone of the plan in the idle step is not tested there (`day_end` is, in Increment A). **Not run:** `wb run code-work check` (in `main`, after the copy) and the criterion that only the owner's log can show (an `idle` line of more than `themes_window_s` seconds after the ceiling is used up).

**Left for the owner:** to accept the two departures; `crawl-approve`, since the copy voided the approval of the crawl; and, on a day when the fetches are used up, to read the first `idle` lines of the log.
