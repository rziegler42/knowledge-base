# Use the time between runs of the crawl, within a window, to make themes and to keep the weave up to date

Status: Proposed
Created: 2026-11-18
Candidate: none (not work too small to need direction: no roadmap covers the crawler, since `theme-weave.md` excludes it in its purpose and `cards.md` and `cross-field-discovery.md` do not name it; the direction is `docs/specs/population.md`, whose non-goal the owner changed on 2026-11-18 for this work; whether a roadmap or a candidate should hold it is the owner's to say)
Specs: docs/specs/population.md ("The idle window", the non-goals, "The crawl plan", "Safeguards", "Scheduling", acceptance criterion 20)

## Goal

Today the loop sleeps after each run of the crawl. The 153 books the crawl has added have a card and no themes, so the theme search, the walk and the weave see only the older books, and `themes-run` is a manual command. When this plan is done, **a run of the crawl ends with an idle window** that makes themes for the books that have none, then the vectors of the themes, then repairs the weave when it is due, and **gives the time back at a deadline** so that the next run starts on time. The window is set by `themes_window_s` in the approved plan (default 600 seconds, 0 is off, at most 3600).

Measured on 2026-11-18, read only, by a script of Python 3.15.0 that printed only counts and seconds, at commit `40fd304` of `main`, from the stored record of the last full run of themes on the owner's library (made on 2026-11-11, 173 books done, 2 failed, with `gemma4:12b`; the record is in the owner's index, which the repository does not hold): a book took a median of 34 seconds, 90 percent took 73 seconds or less, the longest 211; the median book made 12 model calls. The weave was built on 2026-11-13 from 1,805 themes, with no theme waiting (`theme-links status`).

## Scope

**Changed:**
- `engine/kb/themerun.py`: `run` takes an optional `stop` function; with it a run ends at the stop (see increment A). Without it nothing changes.
- `engine/kb/themecheck.py`, `engine/kb/themeextract.py`: only if the stop has to be passed through them to reach every model call (the guard wraps the `launcher` that every call already takes, so the aim is no change here).
- `engine/kb/crawlplan.py`: the key `themes_window_s` of the section `idle`; `engine/kb/crawlapprove.py`: its line in the preview.
- `engine/kb/crawlrun.py`: the point `idle` after `fetch`, and its place in the registry; `engine/kb/crawlidle.py` (new): the step.
- `engine/kb/crawllog.py`: the steps `idle` (the window's own line), `themes`, `theme_vectors` and `weave` are added to `STEPS`, which refuses any other; `engine/kb/crawlstatus.py` and `engine/kb/crawlreport.py`: what the last window did; `engine/kb/crawlschedule.py`: the text for the scheduler names the project's interpreter.
- Tests in `engine/tests/`, `docs/specs/population.md` (acceptance criterion 20 and the passages already written, kept in step), and `docs/README.md` or the crawl's own how-to if one names the loop line.

**Not changed:** `themes-run`, `theme-vectors` and `theme-links` as commands (the manual use stays as it is); the card step and the judge; `card-index` and `card-vectors` (not run by the window); the full build of the weave; discovery, the fetch and the placement.

## Non-goals

- Making the themes of books that already have themes made with an older prompt or model. A change of the prompt or the model stays `themes-run`'s, run by the owner; the window plans only books that have **no themes at all**.
- A full build of the weave, `card-index`, `card-vectors`, the walk and any search.
- A second model server or a second model for the window: it uses the models that `themes-run` uses (`theme`, `theme-check`).
- Running while the run is refused, stopped or tripped.
- Measuring or removing the cost of switching models on the server between the crawl's models and the themes' models (unmeasured; named under Risks).

## Assumptions and constraints

- The loop runs the project's own interpreter, `engine/.venv/bin/python` (Python 3.15.0, with numpy 2.5.4, checked on 2026-11-18), which the owner changes in the loop line. The system `python3` has no numpy; the window then skips the weave and says so.
- Every model call of the themes goes through `models.call(cfg, name, prompt, launcher=..., root=...)` and its `launcher`. The pieces of a book already answered are kept in a journal (`themeextract.PieceJournal`), so a book that is cut is finished later without asking for them again.
- `themerun.plan(store, cfg, book_ids=...)` takes the books to plan, and a run holds at most `cardstate.MAX_ITEMS` books.
- The run already has a time budget of 3600 seconds (`crawlrun.RUN_SECONDS`, the context's `deadline`); the window never goes past it.
- The change is engine code, so the approval of the crawl plan is void until the owner approves again, which is the owner's act at a terminal. A new key in the plan also changes the digest.
- No test uses the network, the owner's models, library or config.

## Completion criteria

1. **Increment A:** `themerun.run(..., stop=f)` makes no call and starts no book once `f()` says to stop; a book cut in the middle stays `waiting`, is charged no attempt, keeps its pieces, and the report says it was stopped; a run with no `stop` is byte for byte as before (the existing tests pass unchanged).
2. **Increment B:** with `themes_window_s = 0` a run makes no themes; with a window and books that lack themes it makes them, ends at the deadline by the injected clock, and finishes a cut book in the next window without asking for its answered pieces again; it plans only the eligible books (active, with a card and a conversion, and no themes at all, so no inactive book, no book without a card or conversion and no book with themes of any version); it makes no model call while the card lock is held by another, and runs through the real lock when it is free; the stop file, a refused or tripped run and the run's own time budget each end or prevent it; a window over 3600 or not a whole number is refused when the plan is read.
3. **Increment C:** theme vectors and the weave repair run after the themes while time is left, the repair only when `theme-links status` says it is due; a missing numpy skips the weave with a reason in the log; the vector build takes the same guard (it is stopped before every embedding batch by the stop file and by the deadline, and a cut leaves the old file as it was, since `themevectors.build` keeps its vectors in memory and writes the file at the end); it is begun only when the time left covers its estimated time (the texts to embed times the measured seconds for each, with a margin), and otherwise the log says it waits for a longer window; the repair is begun only when the time left covers its measured worst case.
4. **Increment D:** `crawl-status` and `crawl-report` say what the last window did (seconds used, why it ended, books made); the text for the scheduler names the project's interpreter; the spec's passages and acceptance criterion 20 agree with what is built.
5. `wb run code-work check` passes, the tests of the modules changed pass, and the owner has read the Result; after the owner approves the crawl plan again, the first window is looked at in the log.

## Increments

### Increment A — Let a run of themes end at a deadline

**Outcome:** `themerun.run` can be told to stop, before a book and before each model call, and leaves a cut book to be finished later.
**Dependencies:** none.
**Affected areas:** `engine/kb/themerun.py` (and `themecheck`/`themeextract` only if the guard cannot be a launcher), `engine/tests/test_themerun.py`.
**Steps:**
1. Read `themerun.run`, `_serve`, `themecheck.make_and_check_for_version`, `themeextract.extract` and `_ask`, `models.call` and `models.run_job`, and the tests of the run that fake the server.
2. Tests first, seen failing, with the existing fake launcher and an injected `stop`: no book is started after the stop; a stop between two model calls of one book raises before the next call; the cut book is `waiting` with `attempts` unchanged and its answered pieces in the journal; run again with no stop it finishes with fewer model calls than a book made from nothing; three books failing in a row still end the run; a run with no `stop` behaves as before.
3. Write the change: a `Cut` exception (not a `KbError`, so that no `except KbError` or `except Exception` of the book's path charges a try; `_serve` catches it first and returns `"cut"`), a guard that wraps the launcher and raises it when `stop()` says so, and the report's `stopped` line. Deliberate single changes (the check before a call dropped, the check before a book dropped, a try charged for a cut book, the journal not kept, the guard not applied to the check model), each to be caught; the `reviewer`; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_themecheck`; the deliberate changes; `wb run code-work check`.
**Evidence:** one local commit, `Plan: 2026-11-18-use-the-idle-time-of-the-loop-for-themes-and-the-weave#A`.

### Increment B — The idle point, the setting and the themes

**Outcome:** a run makes themes for books with none, for at most `themes_window_s`, after its fetch. **The eligible books** are the active books that have a card, a conversion and **no theme generation at all**, taken oldest first and at most as many as one run holds; **the card lock has one owner, `themerun.run`**, which takes it through `cardstate.lock` before any model call (a second holder, even in the same process, is refused, so the window takes no lock of its own and `plan` takes none); a refusal of the lock by `run` ends the themes part with the reason `locked` and no model call, and the run that was planned stays to be run by a later window.
**Dependencies:** A.
**Affected areas:** `engine/kb/crawlplan.py`, `engine/kb/crawlapprove.py`, `engine/kb/crawlrun.py`, `engine/kb/crawlidle.py` (new), `engine/kb/crawllog.py`, `engine/tests/` (the tests of the plan, the approval, the run and a new `test_crawlidle.py`).
**Steps:**
1. Read `crawlplan.PLAN` and its readers, the preview of `crawlapprove`, `crawlrun.POINTS`, `attach_point`, `_real_steps` and the registry, `crawlcards.make_step` (the model step to follow, with its refusal, probe and close), the log's steps and its safe text.
2. Tests first, seen failing: the key `themes_window_s` (default 600, 0 off, whole numbers 0 to 3600, others refused with the line named) and its line in the preview and in the digest; `POINTS` ends with `idle` and a run with no step registered for it is as before; the step with a fake store, a fake launcher and an injected clock: window 0 does nothing and says so; a library of books of every kind is planned as the predicate says: an active book with a card, a conversion and no themes is planned, oldest first and up to the run's limit, and an inactive book, a book with no card, a book with no conversion and a book that has themes of any version are not; a card lock that is held by another holder, taken through the real `cardstate.lock`, ends the themes part with the reason `locked` and makes no model call, and a later window runs the planned run once the lock is free; and with the lock free the window runs the eligible books through the real locking path (not a fake of it), so that a second acquisition by the window itself would be caught; the deadline is the earlier of the window and the run's own budget; a stop file, a tripped breaker and a refused run run no window (they end the run before the point); three books failing in a row end it; after a failure the model entry is probed as the card step does, so that a server that is down counts for `model_down_minutes`; a cut book is finished by the next window; the log has one `themes` line for each book and one `idle` line for the window, with the seconds used and why it ended (`deadline`, `nothing to do`, `stopped`, `failed`), and `crawllog` accepts the four new steps and refuses an unknown one as before.
3. Write the change; deliberate single changes (the window ignored, the run's budget ignored, a book with older themes planned, the stop looked at once and not between calls, the probe dropped, the failure count not reset by a success), each to be caught; the `reviewer`; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlplan engine.tests.test_crawlapprove engine.tests.test_crawlrun engine.tests.test_crawlidle engine.tests.test_themerun`; the deliberate changes; `wb run code-work check`.
**Evidence:** one local commit, trailer `#B`.

### Increment C — The vectors of the themes and the repair of the weave

**Outcome:** after the themes, while time is left, the window makes the vectors that are missing and repairs the weave when it is due.
**Dependencies:** B.
**Affected areas:** `engine/kb/crawlidle.py`, `engine/kb/themevectors.py` and `engine/kb/weave.py` only if a step cannot be called from the window as it stands, `engine/tests/test_crawlidle.py`.
**Steps:**
1. Read `themevectors.build` (it takes a `launcher`, embeds in batches through `models.embed`, keeps the vectors in memory and writes the file under its lock at the end, and a failure leaves the old file), `weave.repair_links` and the `theme-links status` and `repair` commands (what makes it due, what it refuses, what numpy it needs), and measure on a copy of the owner's library, read only on the original, how many seconds an embedding takes for each text and how long a repair of the weave takes; record the numbers in the Result.
2. Tests first, seen failing: after the themes the vectors are made for the themes that have none, and only for those; the vector build is given the guard as its `launcher`, so a stop file or an expired deadline in the middle of the batches stops it before the next embedding call and leaves the old file byte for byte; it is not begun when the estimate of its time does not fit the time left, and the log says so; the repair runs only when due and never as a full build, and is not begun when less than its measured worst case is left; a missing numpy skips the weave with a reason and leaves the vectors made; each step's own lock is taken and a refusal of a lock ends the step, not the run; the log has the `theme_vectors` and `weave` lines.
3. Write the change; deliberate single changes (a repair when not due, a full build, a step begun with too little time left, the guard not given to the vector build, numpy missing treated as a failure of the run), each to be caught; the `reviewer`; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlidle engine.tests.test_themevectors engine.tests.test_weave`; the deliberate changes; `wb run code-work check`.
**Evidence:** one local commit, trailer `#C`.

### Increment D — Status, report, the scheduler text and the passages of the spec

**Outcome:** the owner can read what a window did, and the documents agree with the code.
**Dependencies:** C.
**Affected areas:** `engine/kb/crawlstatus.py`, `engine/kb/crawlreport.py`, `engine/kb/crawlschedule.py`, their tests, `docs/specs/population.md`, and the document that names the loop line.
**Steps:**
1. Read the status and report builders and their fixtures, and `crawl-schedule-text`.
2. Tests first, seen failing: `crawl-status` and `crawl-report` print the seconds used by the last window, why it ended and the books made, from a fixture log; the scheduler text names the interpreter given with `--python` and says in a line why it must be the project's own.
3. Write the change, bring the spec's passages and acceptance criterion 20 to what is built (marking what is `[agreed]` and what is `[proposed]` as the spec does), the `reviewer`, the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlstatus engine.tests.test_crawlreport engine.tests.test_crawlschedule`; `wb run code-work check`.
**Evidence:** one local commit, trailer `#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands. After the last increment the tests of the crawl modules that the registry and the plan reach (`test_crawlrun`, `test_crawlplan`, `test_crawlapprove`, `test_crawlcards`, `test_crawlstatus`) are run together once, because the plan reader, the digest and the registry are shared by every step; any wider run is the owner's to decide, after being told what could break outside the area. A read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again** and changes the loop line to the project's interpreter, and the first window is looked at in the log.

## Risks and sensitive actions

- **A change of engine code voids the approval of the crawl plan**, and a new key changes its digest. Runs refuse until the owner approves again, at a terminal.
- **Models on the server `ned`, plain http.** The themes send the text of the library's books to `ned` as the cards do. The window adds no other boundary. The owner is asked once whether to run a security review of the window (a model call on library text, a lock shared with the card step, a subprocess-free numpy step).
- **The cost of switching models.** The themes use `gemma4:12b` and `phi4`, the crawl's steps use others; each window may unload the crawl's model, and the first call of the next run loads it again. It is unmeasured; it costs time, not correctness. A window of 0 turns it off.
- **A longer run.** The run lock is held through the window, up to the window or the run's budget. The loop still sleeps between runs; a second run exits quietly while the first holds the lock.
- **A book cut at a call.** It keeps its answered pieces; the worst case is the loss of one call. A book whose pieces are many may need several windows.
- **A prompt or model change.** The window never remakes themes already made, so it cannot spend the time of a whole library's themes without the owner's word.
- **The weave repair is the only step that rewrites a shared file** (the next generation, keeping the one before); a kill in the middle leaves the generation before in place, as the command already guarantees. Checked in C.

## Review record

Reviewer: `ask-codex` through `review-engine` (models `gpt-5.6-terra` for rounds 1 and 2, `gpt-6.1-sol` for round 3), 3 rounds of a bound of 3. The bound is reached; the last round raised one finding, applied, and was not followed by a fourth round.

- Round 1, three major findings, all applied after reading the code: (R1-F1) the `Candidate: none` line now says plainly that this is not work too small for direction and that no roadmap covers the crawler; whether a roadmap or a candidate should hold it is the owner's word, left to the owner; (R1-F2) `themevectors.build` takes a launcher and embeds in batches but writes its file only at the end, so the plan and the spec give it the guard, begin it only when its estimated time fits and say that a cut leaves the old file; (R1-F3) `crawllog.STEPS` refuses an unlisted step, so the window's line is the step `idle`, added with the three others to the log and the spec.
- Round 2, two major findings, both applied: the window must respect the card lock, and the whole predicate of the books it takes (active, a card, a conversion, no themes at all) is stated and tested.
- Round 3, one major finding, applied after reading `cardstate.lock`: the lock refuses a second holder in the same process, so the lock requirement written in round 2 would have made every window refuse. The plan now gives the lock one owner, `themerun.run`, maps its refusal to `locked`, and tests the real locking path.
- Rejected: none. Left for the owner: whether a roadmap or a candidate should hold this work (R1-F1); the plan as it now stands was not read again by the reviewer after round 3, and a fourth round needs the owner's level for `extend`.

Increment B, independent `reviewer` (one exchange): no blocking finding, no concrete security risk. Six findings, none blocking: (1) the window's line said "nothing to do" when an error left it, applied; (2) no guard against a book that stays eligible but is never made, applied; (3) the probe could run after the deadline or the stop file, applied; (4) the preview and the spec's list of reasons say more than B builds, recorded in the Result and left to C and D; (5) a locked window leaves its planned record and the next one plans a new one, recorded as a deviation and put on the owner's todo list; (6) whether "oldest first" is oldest first: no change, since the book ids are ULIDs and sort by time. The reviewer read the source and not the tests and could not run anything; the test results are mine.

Increment A, independent `reviewer` (one exchange): no blocking finding, no concrete security risk. Two findings, not blocking: (1) the plan's step says the guard wraps the launcher, but the code passes an explicit `stop`; the reviewer calls this sound, and the Result records why; (2) `themeextract.make_for_version`, a single-book path outside the run, takes no `stop` and needs none. The reviewer read the source and not the tests, and could not run anything; the test results are mine.

## Deferred work

- A measurement of the cost of switching models on the server, and a pass that groups the themes of many books by model (the theme-run queue idea).
- The window for `card-index` and `card-vectors`, which the owner has not asked for.
- A daily ceiling of books for the window, if the windows turn out to take more model time than the owner wants.

## Result

### Increment A (committed as `b526ef5`, on `fe44e29`)

- **A deviation from the written step, within the Scope.** Step 3 says the guard wraps the `launcher`. In this code `launcher` is the path of the `wb` executable (`models._launcher`, `models.call`), not a function, so it cannot carry a guard. The Scope names `themecheck.py` and `themeextract.py` "only if the stop has to be passed through them", and that is what was done: an explicit `stop` function is passed down `themerun.run` → `_serve` → `themecheck.make_and_check_for_version` → `themeextract.extract` and `themecheck.check_themes` → `themeextract._ask`, which looks at it before each of its two model calls. Increment C must give the vector build the same kind of `stop`, since `themevectors.build` also takes a launcher path, not a function; its Scope entry (`themevectors.py` "only if a step cannot be called from the window as it stands") covers that.
- **Changed:** `engine/kb/themeextract.py` (`Cut`, `_stop_if_asked`, `_ask` and `extract` take `stop`); `engine/kb/themecheck.py` (`check_themes` and `make_and_check_for_version` take and pass `stop`); `engine/kb/themerun.py` (`run` takes `stop`, looks at it before each book and before the library is counted, `_serve` returns `"cut"`, the constant `STOPPED`); `engine/tests/test_themerun.py` (eight tests of the stop in `JournalRunTest`, and its helper `run_j` takes the arguments of `run`). A first draft named the helper `_cut`, which the module already used for cutting a text range; it was renamed `_stop_if_asked` when 161 tests failed.
- **Seen failing first:** the eight new tests failed with `TypeError: run() got an unexpected keyword argument 'stop'`.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_themecheck`: 255 tests, OK (Python 3.15.0). Ten deliberate single changes (the look before the first call, before the second call and before a book dropped in turn; the stop not given to the extraction, to the checks, to the book's maker or to the check of each theme; a cut not ending the run; a cut left to be an unexpected error that charges a try; the stop not said in the report), each compile-checked and caught; the first run missed two: the look before a book (the count of the library was not asserted, so a test was added that it is not made) and a cut counted as a failure in a row, which is an equivalent change since a cut ends the run, so that test was renamed for what it checks, that no try is charged. All files restored byte for byte. `wb run code-work check` and `git diff --check` pass.
- **Not run:** the other test files, any real model, the manual command `themes-run run` (it passes no `stop`, as before), and a security review (the owner did not ask for one).
- **Behaviour to know.** A book cut during its checks keeps its extraction pieces in the journal but its check answers are not kept, so the next window asks for the checks of that book again (the plan accepted this). Nothing is filed for a cut book.
- **Review:** see the review record; no recommendation was declined.
- **For the owner:** the commit changes `engine/kb`, which voids the approval of the crawl plan. The window does not exist yet (that is increment B), so approving again can wait until the last increment.

### Increment B (working tree on `b526ef5`, not yet committed)

- **Changed:** new `engine/kb/crawlidle.py` (the step) and `engine/tests/test_crawlidle.py` (24 tests); `engine/kb/crawlplan.py` (the key `themes_window_s` of `[idle]`, default 600, 0 to 3600), `engine/kb/crawlapprove.py` (the "Idle window:" line of the preview), `engine/kb/crawlrun.py` (`idle` is the last of `POINTS` and is registered in `default_steps`; the dry-run text and docstrings), `engine/kb/crawllog.py` (the steps `idle`, `themes`, `theme_vectors`, `weave`), `engine/kb/crawlstatus.py` (its own copy of the step list); tests and the fixture of the report (`test_crawlplan`, `test_crawlapprove`, `test_crawlrun`, `test_crawllog`, `test_crawlchain`, `test_crawlreport`, and four lines in `fixtures/crawlstatus/report/crawl-2026-11-18.jsonl`).
- **Beyond the plan's wording, named to the reviewer:** (1) the status reader's step list and the report's fixture were changed here and not in D, since without them `crawl-status` would not take the new log lines; (2) the window's stop also looks at the disk floors, as the spec says the safeguards are the same as elsewhere; (3) "no themes at all" is implemented as no theme generation of the version in use (a generation with no themes counts as made, so a book is not made twice; a book that was converted again has a new version and is eligible for it); (4) the failure probe repeats the card step's `_answers` with the two tasks of the themes, because `crawlcards._answers` is bound to the card tasks and `crawlcards` is outside the Scope; a shared version is for later; (5) a window that finds the card lock held has already planned a run (`plan` writes its record before `run` takes the lock); the next window plans a new one and the earlier record stays unused, which differs from the plan's words "the run that was planned stays to be run by a later window". The cost is a few unused records while a manual run holds the lock; it is on the owner's todo list.
- **Seen failing first:** the new tests failed for want of the module and the key; the tests of the lists and the order of the other modules failed for want of the new point and steps.
- **Verification run (Python 3.15.0, `-W error::ResourceWarning`):** `test_crawlplan`, `test_crawlapprove`, `test_crawlrun`, `test_crawlidle`, `test_themerun`, `test_crawllog`, `test_crawlchain`, `test_crawlstatus`, `test_crawlreport`, `test_crawlschedule`, `test_themeextract`, `test_themecheck`: 1,156 tests OK. Before the three fixes of the review, the other crawl modules and `test_discover` ran together: 1,250 tests OK (they were not run again, because the fixes touched only `crawlidle.py`). 28 deliberate single changes, each compile-checked and caught by the tests of its module: the window ignored, the run's budget ignored, themes of any kind planned, the stop file, the disk floor, the probe, a failed book planned again, the lock called a failure, a window of zero, a swallowed trip, the deadline not noticed, three failures not ending the window, no line for a made book, the plan's own test dropped, no batch limit, the key's range, its default and its lower end, the preview, the point, the registry, the status list and the log list; then five for the fixes below (a hang, of the loop that is no longer guarded, counts as caught, with a 25 second limit). All files restored byte for byte. `wb run code-work check` and `git diff --check` pass.
- **Review, fixes made after it:** (1) an error before the work (the store, the plan) left the window's line saying "nothing to do"; the default reason is now `failed` until a normal end sets another; (2) a book that the run dropped and that stayed eligible was planned again and again until the deadline, and a pass that did nothing looped for ever on a clock that does not move; dropped books are now left out for the window, they get a `themes` line with the outcome `skipped` and their fixed reason, and a pass that made, failed and dropped nothing ends the window; (3) after a failure at the deadline, or with the stop file there, up to two model entries were still asked; the window's own stop is now looked at before the probe. A first run of the tests for (2) hung for over five minutes before the guard existed, and was stopped; it and the two breaks that hung left temporary folders (69 and 14 MB) in the system temporary folder, not removed.
- **Not run:** the real model server, a real clock, a real library, increments C and D, the full suite, and a security review (the owner did not ask for one).
- **Left open from the review:** (4) the preview's line names the vectors and the repair of the weave, which are increment C, so **the crawl plan must not be approved before C is done**; the spec's list of reasons (`deadline`, `nothing to do`, `stopped`, `failed`) lacks `disk`, `locked`, `settings` and `off`, which the code writes, to be aligned in D; (5) above.
- **For the owner:** the commit changes `engine/kb`; approving again waits for the last increment.
