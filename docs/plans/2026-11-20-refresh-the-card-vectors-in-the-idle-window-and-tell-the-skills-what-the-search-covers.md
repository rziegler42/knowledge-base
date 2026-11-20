# Refresh the card vectors in the idle window, and tell the skills what the search covers

Status: Proposed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: a correction that follows from a finding, that the search by meaning saw 174 of 925 cards on 2026-11-20 because nothing refreshes the card vectors, and that two skills do not say what to do when the search covers little)
Specs: docs/specs/population.md ("The idle window", and the sentence in "Scope" that says the runner does not run `card-vectors`), docs/specs/card.md, docs/specs/knowledge-base.md

## Goal

`pose-a-problem` searches the card vectors, the file `vectors.sqlite`, which only `python3 -m kb card-vectors` makes. The unattended crawl files and cards about a hundred books a day and does not run it (`docs/specs/population.md` says so: "the runner does not run `card-index` or `card-vectors`, so new books are not found by card search until the owner runs them").

Measured on 2026-11-20, read only, with Python 3.15.0, at commit `49de3cb` of `main`, by `python3 -m kb problem-search --limit 3` with one generic sentence: before the owner ran `card-vectors` the reply said `cards_searched: 174`, `without_vector: 749` (the file was last built on 2026-11-10, about 19 percent of the library); after the owner ran it, `cards_searched: 925`, `without_vector: 0` (the run kept 518 vectors, made 1,956 and sent 1,956 texts). The walk (`theme-walk`) has the same kind of gap, smaller: 7,797 themes have vectors and 7,390 are in the weave, because the weave is repaired only when it is due, so `warning` of its reply is "out of date" on almost every call while the crawl makes themes.

When this plan is done:

1. **The idle window keeps the card vectors up to date.** After the themes and before the vectors of the themes, the window embeds the card texts that have no vector or whose text changed, in a bounded batch that fits the time left, and writes the file once, at the end of the batch, as the vectors of the themes are written. A window with nothing to embed costs a count.
2. **`pose-a-problem` tells the agent what to do when the search covers little**, and **`walk-from-themes` tells the agent how to read the warning that the weave is out of date** (say it once, it is not a failure of the call, and the leads of the newest themes may be missing).

## Scope

- `engine/kb/vectors.py`: `waiting_texts` (read only, the count of the card texts that have no vector or whose vector is of another text), and `build` taking a `stop`, a `max_texts`, a `group` and a `lock_wait` as `themevectors.build` does, with no change for a caller that gives none.
- `engine/kb/crawlidle.py`: a new part of the window, `card_vectors`, between the themes and the vectors of the themes; `engine/kb/crawllog.py` and `engine/kb/crawlstatus.py`: the step name and its count in `idle_today`; `engine/kb/crawlapprove.py` and `engine/kb/crawlrun.py`: the words of the approval preview and the dry run.
- `engine/tests/test_vectors.py`, `test_crawlidle.py`, `test_crawllog.py`, `test_crawlstatus.py`, `test_crawlapprove.py`, `test_crawlrun.py`.
- `docs/specs/population.md` (the idle window, the sentence in "Scope", the log, an acceptance criterion), `docs/specs/card.md` and `engine/README.md`, where they say who makes the vectors.
- `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md` and `package/kb/harness/neutral/skills/walk-from-themes/SKILL.md`, and `engine/tests/test_package.py`, which reads both.

## Non-goals

- `card-index`. Read the code before assuming: whether the crawl keeps the keyword index of the cards (`cards.sqlite`) current is found out in Increment A, step 1, and left as it is unless it is not; this plan is about the vectors.
- The weave's rule for when a repair is due (5 percent of the themes or 30 days), the warning's wording, and the command it names (`theme-links build`, where the repair is `theme-links repair`). They are the walk's, and a change to them is its own plan. Increment C only tells the agent how to read the warning as it is.
- The search itself: the model, the prompt, the fields embedded, the scores.
- A change to `themes_window_s`, `themes_window_full_s`, the share of the themes or the run's budget.
- Installing the skills. The copy in the owner's other folder (`kb-scratch`) is the owner's to refresh; this plan changes the files of the package only.

## Assumptions and constraints

- **The vectors are a pure function of the cards and the model.** `vectors.build` keeps a vector whose text hash is unchanged and embeds only the rest (the owner's run on 2026-11-20 kept 518 and made 1,956), so a build with a few new cards sends a few texts.
- **A build embeds in memory and writes its file once at its end** (`vectors.build`), as the build of the theme vectors does, so a build that is cut writes nothing and leaves the old file. A bounded batch (`max_texts`) writes a file that is valid for the cards it embedded and leaves the rest with no vector, which the search says (`without_vector`) and a later window finishes.
- **Cost.** The window's own estimate, measured for the theme vectors on 2026-11-18 (`crawlidle.SECONDS_A_TEXT` 0.35, `SECONDS_A_CALL` 5.0, `BUILD_OVERHEAD_S` 5.0, so a call of `EMBED_GROUP` 40 texts is about 19 seconds); the card texts are of the same kind (a few sentences each), and the batch uses the same `_fit`. A day's new cards (about a hundred books, three fields each) are about 300 texts, about two minutes, which a short window's share does over a few runs and a long window does at once. The first window after this plan has one big batch only if the file is stale (it is not, after the owner's run of 2026-11-20).
- **The lock.** The write takes the catalog lock, as every write of the vectors does. The window gives it a short wait, as the part for the theme vectors gives its own, so that no stop is missed while it waits (the catalog's own wait is two minutes).
- **The engine's code changes, which voids the approval of the crawl** (`docs/specs/population.md`: the fingerprint holds every module of `engine/kb`). The change is built in a worktree and copied to `main` in one step, after the owner is told, and the owner runs `crawl-approve` afterwards. Increment C changes no code of `engine/kb`.
- **A model that does not answer** is handled as for the theme vectors: one probe call, counted by the model's own down clock, and the breaker as it is now.

## Completion criteria

1. `vectors.waiting_texts(store, cfg)` returns the number of card texts that have no vector or whose text hash differs, reads and writes nothing else and sends nothing.
2. `vectors.build(..., stop, max_texts, group, lock_wait)`: with none of the new arguments it behaves as before (its existing tests stand); with `max_texts` it embeds at most that many texts and keeps the old vectors; with a `stop` that says true it embeds no more and writes nothing; with a `lock_wait` it refuses with a fixed message when the lock cannot be had in that time.
3. The idle window has a part `card_vectors` between the themes and the vectors of the themes, which writes one `card_vectors` line (`ok` with the number of texts embedded, or `skipped` with one fixed reason: nothing waits, waits for a longer window, locked, settings; or `failed`), embeds a batch that fits the time left less the reserve of the later parts, never starts a batch under `MIN_BATCH` while more wait, and ends the window with the reason of the stop when the stop file, the deadline or a disk floor says so.
4. `crawl-status` counts the texts embedded for cards in `idle_today` beside those of the themes; the approval preview and the dry run name the part.
5. On a library whose cards are all embedded, the part costs one count and no model call.
6. The spec and the guide no longer say that the runner does not run `card-vectors`; they say that the idle window keeps the vectors current and that `card-index` is as Increment A found it.
7. `pose-a-problem` says: read `cards_searched` and `without_vector`; when the books without a vector are more than a fifth of the books searched, say so in the answer and that the owner runs `card-vectors`, and do not say that nothing fit. `walk-from-themes` says: when `warning` is not null, say it once at the start and go on; it does not fail the call, and the newest themes may be missing from the leads. `test_package.py` holds both rules.

## Increments

### Increment A — Count the waiting card texts and let the build be bounded and stopped

**Outcome:** `vectors.waiting_texts` exists and `vectors.build` accepts `stop`, `max_texts`, `group` and `lock_wait`, with no change for a caller that gives none.
**Dependencies:** none.
**Affected areas:** `engine/kb/vectors.py`, `engine/tests/test_vectors.py`.
**Steps:**
1. Read `themevectors.waiting_texts`, `themevectors.build` and their tests, and read how the crawl keeps `cards.sqlite` current (the card step of `crawlbooks`, `cardqueue.py` line 265 and `catalog.rebuild`); write what was found into the plan's Result as the answer to the non-goal on `card-index`.
2. Write the tests first and see them fail: the count of waiting texts for a library with no file, with a current file, with a new card, with a changed card (same book, new text) and with a card removed; a build with `max_texts` embeds that many and keeps the rest of the old vectors; a build with a stop that is true embeds nothing and leaves the file as it was; a build with `group` sends at most that many texts to the model in a call; a build with `lock_wait` refuses with a fixed message when another holder has the lock; a build with none of the new arguments is the old build (the old tests).
3. Write `waiting_texts` and the new arguments of `build`, as `themevectors` has them; a cut build raises the exception `themevectors` raises for it, so that one handler serves both.
4. Break the code on purpose, one change at a time (the count ignores a changed text, the batch not bounded, the stop not looked at before a model call, the old vectors dropped when the batch is cut, the lock wait ignored, a default that changes the old behaviour), see a test fail for each, and restore the code byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_vectors.py`, `test_themevectors.py` (the same pattern, unchanged) and the tests of the modules that call `vectors.build` (`grep` them); `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-refresh-the-card-vectors-in-the-idle-window-and-tell-the-skills-what-the-search-covers#A`.

### Increment B — The part of the window, its log, its words and the spec

**Outcome:** the idle window keeps the card vectors current, says so in its log, the status, the approval preview and the dry run, and the spec says so.
**Dependencies:** Increment A.
**Affected areas:** `engine/kb/crawlidle.py`, `engine/kb/crawllog.py`, `engine/kb/crawlstatus.py`, `engine/kb/crawlapprove.py`, `engine/kb/crawlrun.py`, their tests, `docs/specs/population.md`, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first and see them fail: the part runs after the themes and before the vectors of the themes; it writes `card_vectors` `skipped` "nothing waits" and calls no model when nothing waits; it embeds a batch bounded by `_fit` and `MIN_BATCH` and writes `ok` with the count; a batch too small for the time left gives `skipped` "waits for a longer window" and the window goes on to the other parts; a lock that is held gives `skipped` "locked"; a stop, the deadline or a disk floor ends the window with that reason and writes no file; a settings error (no `card-embed`) gives `skipped` "settings"; a model that does not answer gives `failed` and the probe of the model's down clock as for the theme vectors; `idle_today` counts the texts of cards; the preview and the dry run name the part.
2. Add the part to `crawlidle.make_step` and its function, the step name to `crawllog.STEPS` and `crawlstatus`, the words to `crawlapprove` and `crawlrun`; keep the time of the later parts (`WEAVE_RESERVE_S`, and the batch of the theme vectors takes what is left).
3. Write the spec (the idle window, the sentence in "Scope", the log, one acceptance criterion), `docs/specs/card.md` and the guide: who makes the card vectors, and that `card-vectors` is still the owner's command to make them all again (`--again`) or when the crawl is off.
4. Break the code on purpose, one change at a time (the part not run, run before the themes, no count of waiting, a batch not bounded by the time, a lock not looked at, a stop not looked at, a failure counted as `ok`, `MIN_BATCH` ignored), see a test fail for each, and restore the code byte for byte.
**Verification:** the tests of the new part and the whole of `test_crawlidle.py`, `test_crawllog.py`, `test_crawlstatus.py`, `test_crawlapprove.py`, `test_crawlrun.py` and `test_vectors.py`; `wb run code-work check`; `git diff --check`. A wider run is named for the reason that the change adds a step to every run of the crawl, which the crawl's own tests (`test_crawlsteps`, `test_crawlfetch`, `test_crawlstate`, `test_crawlschedule`, `test_crawlreport`) read: they are run too, and the owner is told before the copy to `main` what could break outside the tested area (a run's time, the log's step list, the status's counts).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-refresh-the-card-vectors-in-the-idle-window-and-tell-the-skills-what-the-search-covers#B`.

### Increment C — What the two skills say about coverage and the warning

**Outcome:** the two skills tell the agent what to do with a search that covers little, and with a walk whose weave is out of date.
**Dependencies:** none (it is written for the behaviour that Increment B makes, but it holds without it).
**Affected areas:** `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, `package/kb/harness/neutral/skills/walk-from-themes/SKILL.md`, `engine/tests/test_package.py`.
**Steps:**
1. Read `test_package.py` where it reads the two skills, and the plan `2026-11-14-plain-words-in-the-search-of-pose-a-problem`, so that the rule of plain words is not weakened.
2. Write the tests first and see them fail: the text of `pose-a-problem` tells the agent to read `cards_searched` and `without_vector`, to say in its answer when the books without a vector are more than a fifth of the books searched and that the owner runs `card-vectors`, and not to say that nothing fit then; the text of `walk-from-themes` tells the agent to say a warning once at the start and go on, that it does not fail the call, and that the newest themes may be missing.
3. Write the two paragraphs, in the existing sections (4 of `pose-a-problem`, 3 of `walk-from-themes`), in the same plain words, and say in the second that the lanes, the thresholds and the numbers are unchanged.
**Verification:** the tests of both skills in `test_package.py` and the rest of that file; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-refresh-the-card-vectors-in-the-idle-window-and-tell-the-skills-what-the-search-covers#C`.

## Verification for the plan as a whole

Increment A's tests stand unless B changes `vectors.py`, which it does not. After B, the tests of `vectors`, `themevectors` and the crawl modules named in B are rerun together, and `code-work check`. Increment C is documents and one test file, and touches no engine code. A live check after B is copied to `main` and the owner has approved the crawl again: read only, `python3 -m kb problem-search` with one generic sentence on the next day, to show that `without_vector` is small, and the `card_vectors` lines of the log.

## Risks and sensitive actions

- **The crawl's approval is voided** by Increments A and B; the owner runs `crawl-approve`. The change adds a step to every run of the crawl and sends card texts to `ned` (plain http, in the clear, as the card and theme texts do); nothing new leaves the owner's network.
- **A window's time.** The part takes time from the vectors of the themes and the repair of the weave, which come after it. It is bounded by `_fit` and the reserve for the weave, and skipped when little time is left; a window with nothing waiting costs a count.
- **A bounded build writes a file for part of the cards.** The search says how many cards have no vector (`without_vector`), and Increment C makes the agent say so. No search is wrong for it, only narrower.
- **Increment C changes what an agent is told to say.** It adds a duty to report coverage and does not widen what the agent may do or run.
- A security review: this changes a step that runs unattended, sends text to a model and writes the library's index files under a lock. The owner is asked once whether to run a review with the installed `security-reviewer`.

## Review record

Plan review through the review engine (`gpt-5.6-terra`), 1 round of a bound of 3, converged on 2026-11-20: no meaningful findings; the reviewer found the plan consistent with its named specs, with scoped increments and adequate verification. Applied: none. Rejected: none. Before the review I corrected one figure of the plan myself, after reading the code: the cost constants of the window are 0.35 seconds a text and 5 seconds a call. Left for the owner: the approval, and whether to run a security review (asked once, in the owner's hands).

Increment C, independent review by the `reviewer` agent (read only, 1 exchange of a cap of 6): no blocking findings. It checked the wording against `problem.py`, `vectors.py`, `walk.py`, `weave.py` and `crawlidle.py`, and found the unchanged rules (plain words, untrusted data, single quotes, no loops) intact.

- Applied: the definitions of `stale` (vectors made from an older text of their card, not cards) and of `without_vector` (cards with no usable vector, a card whose only vectors are stale among them) now say exactly that; the walk's skill now says that the command the warning names is for the owner and is not to be run.
- Not applied, with a reason: the plan's criterion 7 says the books without a vector are "more than a fifth of the books searched", and the skill says "more than a fifth of `cards_searched` and `without_vector` together", that is `without_vector / (searched + without_vector) > 0.2`. The skill's form is the one that reads as a share of the library, and on the measurement of 2026-11-20 (749 of 923) both trigger; it is recorded here as a departure from the plan's words.
- Could not be checked by the reviewer: how an agent behaves with the wording; the 77 tests of the file that need a workbench checkout (skipped before and after the change).

## Deferred work

- The weave's repair rule and the wording and the command of the walk's warning: the weave is repaired only when due, so the warning is on almost every call while the crawl makes themes. A change is the walk's own plan.
- A search that reads the shelf of a book (the library now has shelves) and a filter for web pages and papers.
- The refresh of the card vectors when the owner changes the embedding model: that is `card-vectors --again`, run by the owner, and the window does not do it.

## Result

**Increment C** (built in `main` directly, since it changes no code of `engine/kb` and so does not void the crawl's approval; done before A and B because it depends on neither).

- Done: a paragraph in step 4 of `pose-a-problem` ("Say how much of the library the search covered": the definitions of `cards_searched`, `stale` and `without_vector`; when `without_vector` is more than a fifth of the two together, say so with both numbers, tell the owner to run `card-vectors`, and note that a search that covered little cannot show that nothing fits) and a closing paragraph of step 7 (if the search covered little, do not say that nothing from another field fit); one sentence group in step 3 of `walk-from-themes` (say the warning once at the start and go on, it is not a failure of the call, the leads of the newest themes may be missing, the command it names is for the owner and is not to be run, the lanes, thresholds and numbers are as they are); two new tests in `engine/tests/test_package.py`.
- Tests were written first and seen failing (2 failures: the words were not in the skills).
- Verification: `python3 -B -m unittest engine.tests.test_package`, 107 tests, OK, 77 skipped (they need a workbench checkout, and were skipped before the change too), Python 3.15.0; `wb run code-work check`, 75 plans, no problems; `git diff --check`, clean.
- Breaks (11 single changes to the two skill files, each caught by the matching new test, the files restored byte for byte): the fifth changed to a half; the word to the owner removed; the two numbers dropped; the sentence that a search that covered little cannot show that nothing fits inverted; the closing rule of step 7 removed; `once` removed; `not a failure` inverted; the newest-themes sentence removed; the do-not-run clause removed; the definition of the stale card removed; the numbers-as-they-are sentence removed. Two breaks were first not caught or not applied (a definition that no test held; a sentence whose lines I had moved), and the test and the break script were corrected.
- Departures from the plan: the threshold is said as a share of the two counts together (see the review record). Nothing else.
