# Run the theme extraction over the library

Status: Proposed
Created: 2026-11-11
Candidate: theme-weave#theme-unit
Specs: theme

## Goal

Give every book of the library that has a conversion and a current card a generation of themes, with a run that can be planned, stopped and run
again, that goes on when one book fails, and that says what it will cost before it starts and what it did after. This is Increment F of
`2026-11-11-make-the-theme-the-unit-of-the-weave`, which said that if the card queue did not fit, a plan of its own would be drafted.

The extraction and its prompt are as they stand (`theme` prompt `v4`, `theme-check` prompt `v1`). The trials that led here: the first
trial (report sha256 `844bafe09c361daaff9ed8d8e6dd57750b230151aee72fc7ff09cf67f0d9ae9f`), the repeat trial (`d236b2629b694691c3716123187109bb340f9cb8c231fc4e0ba4203da7428f6b`)
and the trial on the three PDFs (`2cb5f921fc76cd3c1821210dd0c7c2eb58d86dc253dbe803ab8ad98430a02913`). The last one lost 6 of 73 proposed themes to the
size bound (8.2 percent) and one of the three books stopped because two answers in a row for one piece were refused; the owner decided on
2026-11-11 to stop changing the prompt and to go on to a plan for the library run (the Result of `2026-11-11-show-the-model-where-each-block-sits`).

When this plan is done, a run over the library has been made on the owner's word, a book that failed is listed with its reason and the others
have themes, and the owner has the report.

## Scope

- A word for the confidence that the model writes in letters (`one`), which was 69 percent of the confidences in the last trial.
- A planner that lists the books to make themes for and why the others are left out, counts the pieces, and gives an estimate of the time.
- A runner that works through the planned books one at a time, files the generation of each as soon as it is made, records the outcome of
  each, goes on when a book fails, tries the failed books once more at the end, and stops when books fail one after another for a reason that is
  not a refused answer (a server that is down).
- A command line for them, as `cards-queue` has, and the statement in the theme spec of what the run does.
- The run itself, on the owner's word.

## Non-goals

- Changing the prompts, the form of a theme, the size bound, the check or the config. The agent does not write the owner's config.
- A journal of the calls within a book: a run that is stopped loses at most the book in hand (the largest book of the library is 29 pieces,
  about five minutes). The card queue's journal and its visiting each model once are not built (see the calls below).
- Storing the check's model and prompt version in the generation: the run record keeps them. The form of a theme is unchanged.
- The vectors, the links and the walk (`theme-vectors`, `theme-links`, `theme-walk`), and judging the themes.
- Re-making a book whose newest valid generation of themes was made with the same extraction prompt version and model, unless the owner asks for it (`--again`). The newest valid generation is the one a reader gets, so it is the one the skip rule looks at; an older generation that matches does not stop a book being made again when a newer one does not.

## Assumptions and constraints

- **My calls, not yet the owner's.**
  1. **The state of the run is the library plus a record.** A book is skipped when the newest valid generation of its current version has themes
     whose `made` names the prompt version of `THEME_JOB` and the model that the config names for `theme`; a book with no such generation is
     eligible. So a run that is run again repeats no finished book and needs no manifest of calls. A record of the run is written in the index root
     (derived, disposable, no text of any book) with the outcome of each book, so that `status` can show where the run got to.
     **The skip rule sees the extraction only.** The model and the prompt version of the check are not in the generation (its form is unchanged), so a change of
     the model or the prompt of `theme-check` does not make a book eligible by itself. To make that visible and not silent: the record of each book names
     the check's model and prompt version, `plan` reads the records of earlier runs, and a skipped book whose newest record names a different check model or
     prompt version, or has no record at all, is listed in the plan under "checked by another check, or not known", so that the owner can ask for `--again`.
     The records are derived and may be lost; then every skipped book is listed as not known, and nothing is hidden.
  2. **One book at a time, not one model at a time.** The two models are alternated within a book, as in the trials. The card queue's
     visiting each model once is not built: the trials took 9 to 11 seconds a piece with the models alternating. If the estimate is wrong by a
     large factor, the owner decides then.
  3. **Failures.** A book whose answer is refused (kept aside as now) or that fails for another reason is recorded `failed` with the kind of
     reason, and the run goes on. After the last book, the failed books are tried once more. If three books in a row fail for a reason that is not a
     refused answer, the run stops and says so, because a server that is down would otherwise fail every book. An error of a kind the code does
     not expect is a failure of that book, shown by its kind only, as in the card queue.
  4. **The estimate** is the pieces counted from the conversions (no model is called), times a rate taken from the trials. The figures here are from a read-only count made on 2026-11-11
     with `themeextract.pieces` over the store (176 books, all active; 175 with a current card and a conversion that could be read, one without; 597 pieces with the length header of `v2`/`v3`
     and 622 with the offsets of `v4`; the largest book 29 pieces; the Result of `2026-11-11-show-the-model-where-each-block-sits` records it); `themes-run plan` makes the count again
     and its figures replace these, and the owner is shown them before the run. The project README says the library holds about eighty books with 79 cards; that is out of date and is not the basis of this plan.
     The rate: 9 to 14 seconds a
     piece, and two to two and a half calls to the check for each piece. The library has 175 books to make and 622 pieces, so about 1.5 to 2.5 hours. It is an
     estimate; the run reports what it took.
  5. **The confidence.** A confidence that is the whole text `one` or `one.0` is read as 1.0, and `zero` or `zero.0` as 0.0, with no flag; any other
     word is unreadable as now. Nothing reads the confidence yet; the owner may drop this increment.
  6. **The command line** is `themes-run plan`, `themes-run run <run>` and `themes-run status <run>`, taking no model, server or address, as `cards-queue` does.
- A defect found in the live run stops it; the plan is not widened to get past it.
- Each live call goes to the models the owner's config names for `theme` and `theme-check`, in the clear over the owner's network.

## Completion criteria

1. A confidence that is the whole text `one`, `one.0`, `zero` or `zero.0` (in any case) is read, and tests show it; no other word is read as a number.
2. `themes-run plan` lists the books to make, the books skipped (a valid generation made with the same extraction prompt version and model; no card; no
   conversion; not active; more pieces than `MAX_PIECES`) with the reason, the skipped books whose check is another or not known (by the run records),
   the pieces and the calls that can be counted, and the estimate, and sends nothing. Tests show each reason.
3. `themes-run run` files a generation for each book it makes, records the outcome of each book, goes on when a book fails, tries the failed books once more, stops after
   three books in a row fail for a reason that is not a refused answer, and can be stopped and run again without repeating a finished book. Tests show each.
4. The run record holds no text of any book, and `status` shows where each book has got to.
5. The run over the library has been made on the owner's word and a report (counts; each book with its outcome; themes and drops by reason; refusals kept aside; time;
   tokens) is outside the repository with its hash and in the Result.
6. The owner has the report and has decided what comes next.

## Increments

### Increment A — The confidence written in letters

**Outcome:** a confidence of `one` or `zero` is read as 1.0 or 0.0.
**Dependencies:** none.
**Affected areas:** `engine/kb/themeextract.py` (`_confidence`); `engine/tests/test_themeextract.py`; the engine README.
**Steps:**
1. Write the tests first and see them fail: the whole text `one`, `One`, ` one. `, `one.0`, `zero`, `Zero.0` are 1.0 and 0.0 with no flag; `one of them`, `not one`, `someone`,
   `ninety`, `none` and the empty text keep the behaviour they have (unreadable with a flag, or the first number); a number or a level word is read as before.
2. Change `_confidence`; run the tests; break the code on purpose and restore each; update the README (the sentence on the confidence).
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themecheck` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-run-the-theme-extraction-over-the-library#A`.

### Increment B — The plan of a run

**Outcome:** `themerun.plan` writes a record of the run and returns the books to make, the books skipped with the reason, the pieces, the calls that can be counted and the estimate, and sends nothing.
**Dependencies:** A.
**Affected areas:** a new `engine/kb/themerun.py` (the plan and the record); `engine/tests/test_themerun.py`; reads `cardqueue.py`, `cardstate.py`, `theme.py` and `themeextract.py` and reuses the lock and the way of writing a record where they fit, saying in the Result where they did not.
**Steps:**
1. Write the tests first and see them fail. A store with books of each kind: active with a conversion and a card (to make), one with a valid generation made with the prompt version and the model of the config (skipped), one made with another prompt version or model (to make), one with no card, one with no conversion, one not active, one with more pieces than `MAX_PIECES`, one whose newest generation is damaged (to make). A skipped book whose newest run record names the check model and prompt version now configured is not listed as unknown; one whose record names another check model or another check prompt version, one with no record, and the case where the records are lost, are each listed as "checked by another check, or not known" and are still skipped. The plan names each book and its reason, counts the pieces with `themeextract.pieces`, gives the calls that can be counted (one for each piece) and the estimate with the rates it used, refuses a missing model before anything is written, and writes a record that holds book ids, version ids, reasons and counts and no text of any book. `--book` limits the plan to the books named; `--again` makes every eligible book.
2. Write `themerun.plan`; run the tests; break the code on purpose and restore each.
3. Read the plan of the real library, read-only and with no model: the books to make, the pieces and the estimate; record them in the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_theme` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-run-the-theme-extraction-over-the-library#B`.

### Increment C — The run of a plan

**Outcome:** `themerun.run` and `themerun.status` work through a planned run, file the generations, record the outcomes, and survive a book's failure and a stop.
**Dependencies:** B.
**Affected areas:** `engine/kb/themerun.py`; `engine/tests/test_themerun.py`.
**Steps:**
1. Write the tests first, with a fake that stands in for the models as the tests of the extraction do, and see them fail. Each book is made with `themecheck.make_and_check_for_version`, given the frequencies of the library counted once, and its generation is filed with `theme.file` as soon as it is made.
   A refused answer fails that book with its kind, and the others go on; a book that fails is tried once more after the last; three books in a row that fail for a reason that is not a refused answer stop the run with that reason; an
   unexpected error fails that book and shows its kind only. A run stopped by an exception and run again repeats no book that was filed. A book whose conversion changed since the plan, or that is no longer active, is dropped
   and reported. Only one holder of a run runs it at a time. `status` shows each book's state and no text. The record keeps, for each book, the models and prompt versions of its calls (extraction and check) from the records the call returns.
2. Write `themerun.run` and `themerun.status`; run the tests; break the code on purpose and restore each.
**Verification:** as in B. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-run-the-theme-extraction-over-the-library#C`.

### Increment D — The command line and the spec

**Outcome:** `python3 -m kb themes-run plan|run|status` works, and the theme spec says what the run does.
**Dependencies:** C.
**Affected areas:** `engine/kb/__main__.py`; its tests; `docs/specs/theme.md` (a statement of what is true now: the run, the skip rule, the failure rules; no change of direction); the engine README.
**Steps:**
1. Write the tests first and see them fail: the parser takes no model, server or address; `plan` prints the plan; `run` prints the report and exits 1 when a book failed, with a message on the error output, as `cards-queue` does; `status` opens the store read-only.
2. Wire the command; write the statement in the spec; update the README (the command, what is sent, the estimate and how to stop and run again); run the tests.
**Verification:** the nearest tests of the command line (`engine.tests.test_main` or the module that tests `cards-queue`, found by search), `engine.tests.test_themerun`, and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-run-the-theme-extraction-over-the-library#D`.

### Increment E — The run over the library

**Outcome:** every book with a conversion and a current card has a generation of themes made with the prompt `v4`, or is listed with its reason; the owner has the report.
**Dependencies:** D, and the owner's word.
**Affected areas:** the library (untracked); a report outside the repository; this plan's Result. No tracked code unless a defect is found, which stops the run.
**Steps:**
1. Run `themes-run plan` and show the owner the plan: the books to make and the books skipped with the reasons, the pieces, the calls that can be counted and the estimate; say what is sent (for each piece, the title, the words to avoid and up to 20 KB of text to the model set for `theme`; for each theme, its excerpt and up to five short sentences to the model set for `theme-check`; in the clear to the owner's server) and what is filed (a new generation of themes for each book, never changing an earlier one). Wait for the owner's word.
2. Run on the owner's word. It can be stopped and run again. A defect stops it and is reported; it is not worked around.
3. Write into the Result, from the run's report: the books made, skipped and failed (with the kind of reason); themes kept, and dropped by reason; the flags; refusals kept aside; time and tokens against the estimate; and what could not be concluded. Keep the report outside the repository with its hash.
4. Give the owner the report and a recommendation, and record the owner's decision.
**Verification:** the report holds every book of the library with its outcome or reason; the numbers in the Result are the report's; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-run-the-theme-extraction-over-the-library#E`, holding the Result and the owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun `test_themerun`, `test_themeextract`, `test_themecheck` and `test_theme` once and `wb run code-work check`. A wider run is not named. What could break outside the tested area is the
command line (`__main__.py` is read by every command; the tests of the command line cover it) and the first live call of the run, which the run's first book shows.

## Risks and sensitive actions

- **Book text goes to models, for the whole library.** About 175 books, 622 pieces, over the owner's network in the clear, for 1.5 to 2.5 hours by the estimate. It is said to the owner beforehand with the plan of the run, and waits for the owner's word.
- **The run files data in the library (untracked).** A generation of themes for each book. An earlier generation is never changed, and the newest valid generation is the one read, so a bad run is superseded by a later one rather than undone. The disk the generations take is small: a theme is about 3 KB, a book had 4 to 41 themes in the trials, and the reader refuses a generation of more than 8 MB.
- **A model's reply is untrusted** and decides a pointer into the book and text that is stored; this was reviewed in the earlier plan and is unchanged. The run adds a record in the index root, which holds ids, reasons and counts and no text of a book or of a reply. A security review of the run's record and lock is asked of the owner once and runs only if the owner asks.
- **A server that is down** would fail every book; the stop after three failures in a row is the guard. A book left failed is listed, not hidden.
- **The model's themes are not judged here.** The trials show a flag on 86 to 94 percent of themes and `stated` marks on 82 percent of parts by a check model that has not been tested for leniency; the report says so and the weave must not treat them as checked facts.
- **The owner's config is not written by the agent.**

## Review record

Reviewer: Codex through the review engine (plan-c1d81cc89b004688), 3 rounds of 3, converged. Rounds 1 and 2 were answered by `gpt-5.6-terra`, round 3 by `gpt-6.1-sol`.
- Round 1, `changes_needed`, one major finding (R1-F1): the skip rule sees only the extraction, not the check's model or prompt, which are not in the generation. Applied: the plan states that
  limit, the record of each book names the check's model and prompt version, and `plan` lists skipped books whose record names another check or none ("checked by another check, or not known").
- Round 2, `changes_needed`, two major findings. R2-F1 (the plan's library counts against the project README's about eighty books): applied; the counts are from a read-only count made on 2026-11-11,
  the plan cites it and says `themes-run plan` makes it again, and the README is recorded as out of date. R2-F2 (the non-goal and the skip rule differ about an older matching generation): applied;
  the rule looks at the newest valid generation, and the non-goal says so.
- Round 3, `no_meaningful_changes`, no finding.
- Left for the owner: the project README's figures for the library are out of date (recorded under Deferred work).

## Deferred work

- The check's model and prompt version in the generation itself (until then the skip rule sees the extraction only, and the run records and the plan's list of books "checked by another check, or not known" are the guard), a journal within a book, and a queue that visits each model once, if the estimate proves wrong.
- The flag for words of a field (it flags ordinary words), the leniency of the check, skipping blocks that are only references, and a rewrite step: each is the owner's to decide after the run's report.
- The spans far over the limit that the model names again (7,952 and 8,265 characters in the last two trials), the fallbacks named in `2026-11-11-show-the-model-where-each-block-sits`, and what the model wrote when the blocks were not numbers.
- Vectors, links and the walk: the other candidates of the roadmap.
- The project README's figures for the library (about eighty books, 79 cards) are out of date; correcting them is the owner's to ask for, outside this plan.

## Result

### Increment A (done; committed with the trailer for A)

- **Done.** `engine/kb/themeextract.py`: `_confidence` first tests the whole text against `_SPELLED` (`one` or `zero`, in any case, optionally followed by `.0`, then optionally a full stop
  that touches it, with spaces round it); a match is 1.0 or 0.0 with no flag. Everything else is read as before. The docstring and the engine README say so, with the figure that led to it (the model wrote `one`
  for 45 of 65 confidences in the trial on three PDFs). Tests in `test_themeextract.py`: 11 new readable cases (`one`, `One`, `ONE`, ` one. `, `one.0`, `ONE.0`, `one.0.`, `zero`, `ZERO`, `Zero.0`, `zero.`),
  15 new cases that stay unreadable (`one of them`, `not one`, `someone`, `ninety`, `one.5`, `one or two`, `one hundred`, `twelve`, `once`, `zeros`, `none.0`, `o n e`, `zero zero`, `one .`, `one.0 .`), and a direct
  test of `_confidence` with spaces and a tab round the word.
- **Tests first, seen failing.** The nine readable cases of the first draft failed before the code; the unreadable cases pass before and after, as guards. Two cases of mine were wrong tests and were
  removed (`zero point five` is over the 12 characters the answer check allows, and `one high` is already read by the `high` rule); one more, `one .0`, is read as 0.0 by the existing first-number rule
  and was removed: that is old behaviour and I did not change it.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themecheck`: 211 tests OK.
  `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 14 new: 13 caught. One, reading the spelled word after the number pattern, is not caught and is equivalent (the number pattern cannot match any text the word pattern accepts: in `one.0`
  the `0` follows a `.` that follows a letter, which its look-behind rejects); the reviewer agreed. One break (spaces round the word) was first missed because the answer check trims spaces before `_confidence`
  sees them, which led to the direct test. The 63 earlier breaks of the module and the 16 of the header are still caught.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: the pattern let a space come between `.0` and the full stop (`one.0 .`), which the plan and README did not name; it now must touch the word, with a
  guard test; plain `ONE` and `ZERO` are cases. Recorded, not applied: `\s` is Unicode white space, so a no-break space round the word is accepted (harmless); reading `one` as 1.0 means the 45 themes now rank as
  confidences that were read, so they beat any guessed 0.5 and any read confidence below 1.0 in the merge of near-identical themes, and, since the model writes `one` for nearly everything, the confidence
  still carries almost no signal; nothing else reads the confidence or the flag now (`confidence_unreadable` is read only in `themeextract.py`; the specs say a weak theme is weighted down by it, which is not built).
- **Not done.** Increments B to E. No security review (none asked; the text is a model reply of at most 12 characters, read by a fixed pattern into one of two numbers).

### Increment B (done; committed with the trailer for B)

- **Done.** A new `engine/kb/themerun.py`: `plan(store, cfg, book_ids=None, again=False)` writes a record of the run and returns the books to make (with title and pieces), the
  books left out with the reason (`inactive`, `no_card`, `no_conversion`, `too_long`, `already_made`), the skipped books whose check is another or not known, the books with a damaged
  generation, the pieces, the calls that can be counted, the models and prompt versions, and the estimate with its basis. It refuses a missing model, a model switch that is off and a book
  that is not there before anything is written. `write_record` and `read_record` check the form of the record on writing and on reading; the record holds ids, counts, reasons and the models
  and prompt versions of each book's calls, and no text of a book or of a reply (titles are in the summary that is shown and not in the record). The new tests are `engine/tests/test_themerun.py`.
- **How it reuses the card queue's code.** The record is the file `theme-run.json` in the run's folder under `card-runs` of the index root, written and read with `cardstate._put` and `_get`
  (private names used from another module: no change to `cardstate`, which is outside this increment's areas), so it has their protections (no link followed, a private folder, one rename, mode 600).
  The card manifest's own checks are card-specific and were not reused; `themerun` has its own. The lock of `cardstate` is for Increment C; because it is one lock for the whole folder, a
  theme run and a card run cannot run at the same time, which is wanted (both drive the same server) and is to be said in the README with the command line (D). A card run's folder and a theme
  run's folder can hold each other's files side by side without either reading the other's; a test shows it.
- **Tests first.** The tests were written before the module; they failed because it did not exist (the first run was one import error), and when they were run against it two real gaps showed:
  a generation with no themes must be judged by the newest record of the version and not by any record that matches, and a record of another generation is no evidence of the check.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themecheck
  engine.tests.test_textutil`: 249 tests OK (38 of the planner). `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 53 of `themerun.py`: 52 caught, the file restored byte for byte. One is not caught and is equivalent: the 500-character limit on a reason in an item, which the check that the
  reason is its own cleaned text also enforces. Nine were first missed and led to tests (a malformed check entry in an item, the cap on the records read, an item that is not done taken as
  evidence, one theme of another prompt among several, the limit of exactly `MAX_PIECES`, the books named checked before any is looked at, a name that is taken, a title not cleaned and cut). One redundant
  condition was removed (`generation is not None` in `_done_item`: both callers compare the generation).
- **Read-only on the real library (no model, no network, the record not written; the script switched the write off and no file was found afterwards).** The plan took 2.5 seconds: 175 books to make
  (622 pieces: the estimate is 5,598 to 8,708 seconds, 1.6 to 2.4 hours, and 1,244 to 1,555 calls to the check), 1 book left out for having no card, none inactive, none without a conversion, none too long,
  none already made (no book has themes yet), none with a damaged generation. The largest books are the HTTP RFC (29 pieces), the networks paper and PaLM (18 each).
- **The model names, checked.** The skip rule compares the model name that a call reports with the `model` of the config entry. In both trials the one name the server reported for each task is exactly
  the config entry's `model` (compared in a script that printed only whether they match), so the rule can fire on this server; had they differed, every book would have been made again, never skipped wrongly.
- **A difference from the plan's wording, for the owner.** Step 1 listed "one whose newest generation is damaged (to make)". The code follows the plan's own rule (the newest *valid* generation, which is what a
  reader gets): a book whose only generation is damaged is made; a book with an older generation that matches and a newer one that is damaged is skipped, and the plan lists the damaged one under `damaged`
  so that it is seen. A test shows each. If the owner wants such a book made again, `--again` does it.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: the point above (the damaged generation is listed, with a test); a test that a plan reaches no model (`models.run_job` and `models.call` patched to fail);
  two items for one version are refused in the form; a test with a card run's folder present. Recorded, not applied: (1) only `KbError` is caught around a book's card, conversion and pieces, as in the card queue's
  plan, so an unexpected error in one book stops the plan loudly before anything is written (Increment C's run treats an unexpected error as that book's failure); (2) the `reason` field of an item is free text
  up to 500 characters, and in B it is always empty: **Increment C must keep the reasons to a fixed set of kinds and never put a title or a fragment of a reply there**; (3) the form accepts a `done`
  item with no generation or no `made` (the callers compare, so it is harmless); (4) `_earlier_records` scans every folder of the card runs and is bounded only by the count of theme records it finds; (5) a
  crash leaves `.theme-run.json.*.tmp` files that nothing cleans, as with the card manifest; (6) whoever can write the 0600 record can forge a `done` item for a generation with no themes and make the plan skip that
  book, the same trust as the card journal.
- **Not done.** Increments C to E. The README and the spec say nothing of the run yet (Increment D). No security review (none asked; no new input reaches a privileged use in a plan: it reads the library and
  writes one record by the card queue's safe functions).
