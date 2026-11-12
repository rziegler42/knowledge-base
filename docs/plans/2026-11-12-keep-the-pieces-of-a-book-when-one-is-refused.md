# Keep the pieces of a book when one is refused

Status: Proposed
Created: 2026-11-12
Candidate: theme-weave#theme-unit
Specs: theme

## Goal

Stop a refused piece from costing a book all the pieces that were made well. Today a book of 29 pieces that has one piece refused twice in a pass fails whole and
nothing of the 28 is kept; the next pass or run asks for all 29 again. This is the "journal within a book" that
`2026-11-11-run-the-theme-extraction-over-the-library` named as a non-goal and, after its run, as the open decision: that run left one book of 175
without themes, **RFC 9110: HTTP Semantics** (29 pieces, refused in both passes, in the first run and in the rerun of the Result of that plan's Increment E).

When this plan is done, the answer to each piece that a model gave and the extraction accepted is kept in the index root as soon as it is accepted; a book that fails keeps them;
a pass or a run that makes the book again asks the model only for the pieces it has no answer for; the book's generation is the one it would have been had it been made in one go from the same
answers; and RFC 9110 has been run again, on the owner's word, with the outcome recorded. If one piece is refused again and again the book still fails, and the report
now says how many of its pieces are kept, so that the piece in question is known.

## Scope

- A file in the index root that keeps, for one book and version, the accepted answer of each piece of the extraction, with what is needed to know that the answer is for the prompt now being sent.
- The extraction (`themeextract.extract`) and the make-and-check call (`themecheck.make_and_check_for_version`) take a journal: a piece with a saved answer is not asked for again, and each answer accepted is saved before the next piece is asked.
- The run (`themerun`) gives each book its journal, keeps it when the book fails, removes it when the generation is filed, and `status` says how many pieces of a book that has not been done are kept.
- The statement in the theme spec and the engine README of what is kept and when it is removed.
- The run again of the book that failed, on the owner's word.

## Non-goals

- A journal of the calls of the check (`theme-check`): they are asked again for a book made again. A check is one short call for each theme; the extraction is the long one (one call for each piece).
- Filing a generation with the pieces that were made when one is refused for good (a partial book). A generation that silently lacks part of a book is a change in what a generation means; if it is wanted it is a decision of the owner and a plan of its own.
- Changing the prompts, the form of a theme or of a generation, the run record's form, the retries (`RETRIES`, `STOP_AFTER`), the config, or the card queue and its journal (`cardstate` is used for its file functions and is not changed).
- Finding why the model's answers for that piece are refused. The refused answers of the run are not kept (the folder `refused` is full and is the owner's to empty); the journal shows which pieces are done, and so which is not.
- Anything for the PDF size bound, the flag rule or the check's leniency (the sample of the library is in the Result of the plan above).

## Assumptions and constraints

- **My calls, not yet the owner's.**
  1. **Where.** `<index root>/card-runs/theme-journal/<book>-<version>.json`, written and read with the safe file functions of `cardstate` (`_put`, `_get`, `remove`: private folder, no link followed, mode 600, exclusive temporary
     file and one rename, a file larger than the limit or one that is not the user's refused, a repeated key refused). The folder is named as a run is named; no run is called `theme-journal`. `themerun._run_names` lists every folder of `card-runs` that is named like a run and sorts newest first, so `theme-journal` would sort before the runs
     (a letter sorts after the digits that a run's name begins with) and take one of the `RUNS_READ` places; Increment C leaves it out by name (a test shows it). Only `themerun` lists the folders; the card queue does not.
  2. **What an entry is.** `{"piece": n, "key": <the reuse key, 64 hex digits: the sha256 of the inputs of the piece's prompt, see below>, "values": <the checked answer>, "record": <the call's record>}`; the file holds the book id, the version id and the entries, in the order of the pieces, with no gap. The record saved is that of the call that was accepted (the retry's, if the first was refused); the key is the same whichever call was accepted. **The key is not a digest of the prompt text**: `cardmake._prompt` puts a fresh random token in every prompt it builds (`_token`, `secrets.token_hex`), so the same inputs give a different text each time, and neither the original nor the retry prompt can be the key.
     The key is the sha256 of a fixed encoding (JSON with sorted keys) of the inputs that make the prompt: the title, the words to avoid as listed (after the example's words are left out), the piece's text, its number and the number of pieces. The rules text is not in the key; it is the prompt version of the job, which is in the record and is changed whenever the rules are (as `THEME_JOB` has been, v1 to v4). A saved entry is used only if its key equals that of the piece now built **and** its record names the model and the prompt version now in use; the first entry for which
     either differs, and every entry after it, is dropped and asked again. A file that is not as the module describes is refused and is not used (the book is made from the start, and the file is replaced when the first piece is saved).
  3. **Only an accepted answer is saved**, after `_ask` returns it (so after the one retry with the reason for a refused shape); a refused or failed call is never saved. The values are untrusted text from a model, so on use they go through `_rows` and `_draft` exactly as a fresh answer does. Whoever can write the file can say what the model answered,
     as with the card journal; the folder is the user's alone, and that is its protection (said in the module's docstring as `cardstate` says it).
  4. **When it is removed.** When the generation of the book is filed (`done`), when the book is dropped by the run, and when the journal is stale beyond use (its first entry does not match). A book that fails, is stopped or is killed keeps it. A journal of a book that is never made again stays until the owner deletes the folder; it is
     derived and holds the model's answers for the pieces of one book (about the size of the themes), no more.
  5. **The report.** `calls`, `input_tokens` and `output_tokens` of a book that was made in more than one go count the calls of its pieces whether made now or in an earlier go (the record of each is saved), and `seconds` is the time of the go that finished it. This is said in the README, because the run record has no
     key for it and its form is not changed.
  6. **A piece refused for good still fails the book**, as now. The journal makes the next try cheap (only that piece, and the check), and the report says how many pieces are kept.
- The shared lock of the card queue is held by the run while it works, as now; the journal is written and read only under it (or by a single `make_for_version` call, which holds none: a test shows two writers cannot leave a half file).
- A defect found in the live run stops it; the plan is not widened to get past it.
- Each live call goes to the models the owner's config names for `theme` and `theme-check`, in the clear over the owner's network, as before.

## Completion criteria

1. The file is written and read as described, and a file that is a link, readable by others, too large, not JSON, with a repeated key, with an entry out of order, with a gap, with a key that is not expected or for another book or version is refused. Tests show each.
2. With a journal, `extract` asks no model for a piece whose saved entry matches (the same key, model and prompt version), also across two separate extractions that build their prompts with the real prompt builder (whose random token differs each time) and make no model call for a saved piece; asks for a piece whose inputs changed (another title, another word to avoid, another text, another number of pieces, another model, another prompt version) and for every piece after it;
   saves each accepted answer before the next piece is asked; never saves a refused or failed answer; and returns the same themes, records and drops as a run with no journal given the same answers. Tests show each.
3. A book that fails keeps its journal; the next go asks only for the pieces with no entry and for the check; a book that is done has no journal; a dropped book has none. A killed run leaves a journal that is valid. Tests show each.
4. `themes-run status` shows, for a book that has not been done, how many of its pieces are kept, and shows no text of any book.
5. The book that failed has been run again on the owner's word, and the outcome (done, or failed with the pieces kept) is in the Result, with the hash of the report that is outside the repository.
6. The owner has the result and has decided what comes next.

## Increments

### Increment A — The file of the journal

**Outcome:** `themejournal` writes, reads and removes the journal of one book and version, and refuses a file that is not as it describes.
**Dependencies:** none.
**Affected areas:** a new `engine/kb/themejournal.py`; `engine/tests/test_themejournal.py`. Uses `cardstate` (`_put`, `_get`, `remove`); changes nothing in it.
**Steps:**
1. Write the tests first and see them fail: a journal with entries is written and read back equal; no file reads as `None`; a file that is a link, a pipe, another user's, readable by others, larger than the limit, not JSON, a repeated key, a key not expected, a piece number out of order or repeated or with a gap, a key that is not 64 hex digits,
   a record that is not as `cardstate` describes (the keys of a record, a model that is not valid, a date with control characters), a file for another book or version than its name says, more entries than `MAX_PIECES`, and values that are not plain data are each refused; the temporary file is not left behind when a write fails; `remove` removes the file and a
   temporary file left by a crash and does not fail when there is none.
2. Write `engine/kb/themejournal.py` (`write`, `read`, `remove`, the checks) with the docstring of the file's trust as in `cardstate`; run the tests; break the code on purpose, one break at a time, and restore each.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-keep-the-pieces-of-a-book-when-one-is-refused#A`.

### Increment B — The extraction uses the journal

**Outcome:** `extract` and `make_and_check_for_version` take a journal and ask only for the pieces it does not hold.
**Dependencies:** A.
**Affected areas:** `engine/kb/themeextract.py` (`extract`, and `make_for_version`, which passes the journal on); `engine/kb/themecheck.py` (`make_and_check_for_version`); `engine/tests/test_themeextract.py`, `engine/tests/test_themecheck.py`.
**Steps:**
1. Write the tests first, with the fake that stands in for the models, and see them fail: the cases of criterion 2 (a saved entry is not asked for again; each of the changes of prompt makes that piece and the following ones asked again; each accepted answer is saved before the next piece is asked, shown by a save that fails on the third piece and a journal with two entries;
   a refused answer, a runaway and a failed call are not saved; an answer refused once and accepted at the retry is saved once, as accepted, with the key of the piece, and is reused when the inputs are unchanged and asked again when any of them changed); a book made in two goes (first go refused at piece 3 of 5, second go) has the themes, records, drops and calls of a book made in one go from the same answers, and asks the fake for pieces 3 to 5 only; a saved entry whose values
   are bad is dropped as a fresh bad answer is, with its reason; with no journal given, nothing changes (the existing tests stand).
2. Change the two functions; run the tests; break the code on purpose, one break at a time (the key left out of the match, the key made from the prompt text, the model left out, a refused answer saved, the save made after the next call, a saved piece used for a later piece), and restore each.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-keep-the-pieces-of-a-book-when-one-is-refused#B`.

### Increment C — The run keeps and removes the journal; the status says how many pieces are kept

**Outcome:** a book made by `themes-run` has a journal that survives its failure and is removed when its generation is filed, and `status` says how many pieces of an undone book are kept.
**Dependencies:** B.
**Affected areas:** `engine/kb/themerun.py` (`run`, `status`, the plan's reading of run folders if a test shows it takes the journal folder for a run); `engine/tests/test_themerun.py`; `docs/specs/theme.md` (a statement of what is true now, no change of direction); the engine README (what is kept, where, when removed, what the report counts).
**Steps:**
1. Write the tests first and see them fail: a book whose third piece is refused twice fails with its first two pieces kept; the second pass asks the fake for the third piece only and the book is done, its themes equal to those of an unbroken run, and its journal is gone; a run killed after piece 2 (the fake raises) leaves a valid journal and the next run
   asks from piece 3; a dropped book (no longer active, conversion changed) has no journal left; a book whose conversion changed since the journal was made does not use it (its first prompt differs); the run record's form is unchanged and the totals count the saved calls (said in the README); `status` shows "kept 2 of 5 pieces" for a failed or waiting book, nothing for a done one,
   and no text; `plan` and `status` do not take the folder `theme-journal` for a run; a journal that cannot be read is not used and does not stop the run (the book is made from the start).
2. Change `run` and `status`; wire the journal to the book in `run`, under the lock; write the statements in the spec and the README; run the tests; break the code on purpose, one break at a time (the journal not removed on done, removed on failure, not given to the second pass, used for another book), and restore each.
3. Run `python3 -m kb --help` and `python3 -m kb themes-run --help` to show that the command line is unchanged.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_cardqueue engine.tests.test_cardstate` (the last two show that the shared file functions and lock behave as they did; the result is recorded) and `wb run code-work check`; the module that tests the command line, found by search, because `status` prints a new line. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-keep-the-pieces-of-a-book-when-one-is-refused#C`.

### Increment D — Run the book that failed again

**Outcome:** RFC 9110: HTTP Semantics has been run again with the journal, and the result is known.
**Dependencies:** C. The owner's word, given after the plan of the run is shown.
**Affected areas:** the index root only (a journal, and a generation if the book is done); nothing tracked except this plan's Result.
**Steps:**
1. `python3 -m kb themes-run plan --book 01M6SR0CSZ177HZK2FS52EKRGE` and show the owner the plan: the book, its 29 pieces, the estimate (about 6 to 7 minutes if all pieces are asked for, less if the journal holds some), the models and prompt versions, and exactly what is sent (the title, the words to avoid and up to 20 KB of text of each piece to the `theme` model; the excerpt and up to five sentences of each theme to the `theme-check` model), in the clear to the owner's servers.
   Wait for the owner's "run it".
2. `python3 -m kb themes-run run <run>`; read the outcome and the status; if the book fails again, read how many pieces are kept, and run the run again once on the owner's word to see whether the same piece is refused (the pieces kept are not asked for again). Keep the report outside the repository with its hash.
3. Write the Result with the counts and the hash. If a piece is refused for good, say which piece number, and recommend: leave the book out, split that piece, or a plan for a partial generation (not built here).
**Verification:** the run's own report; `themes-run status`; a read-only read of the library: the book has one valid generation filed, or none, and the others are as they were (174 books with generation 1, none damaged).
**Evidence:** the Result of this plan, committed with the trailer `Plan: 2026-11-12-keep-the-pieces-of-a-book-when-one-is-refused#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. Increment B changes `themeextract` and `themecheck`, so the tests of A are not rerun (they do not import them) and the tests of B are run again in C with the others. After D: `python3 -W error::ResourceWarning -m unittest discover -s engine/tests`
is not named, because nothing outside the theme modules and the run changed; what could break outside them is the card queue, which shares `cardstate` and its lock and is not changed, so the tests of the card queue are run once in C (`engine.tests.test_cardqueue`, `engine.tests.test_cardstate`) to show that the shared functions behave as they did.

## Risks and sensitive actions

- A live run (Increment D) sends the text of one book, up to 20 KB for each piece, to the models of the owner's servers in the clear; the owner's word is asked after the plan is shown.
- The journal is a new file in the index root holding model answers about one book. It is written with the safe functions and is the user's alone; it is read back as untrusted text and checked again on use. A hostile or damaged file is refused and the book is made from the start. **Security review checkpoint:** this is a filesystem and untrusted-input surface, so the owner is asked once, before Increment A begins, whether to run `security-review` on it. A review runs only if the owner asks; my reading is that the risk is low because the file is written and read by the checked functions of `cardstate` and its values are checked again on use.
- A stale journal could give a book the answers made for another prompt. The key of the piece's inputs, the model and the prompt version guard against it (a change of the rules text without a new prompt version would not be seen; the prompt version is changed with the rules, as it has been); the tests show each change makes the piece asked again.
- A journal that is never removed (a book that is never made again) stays on disk until the owner deletes the folder; it is derived data.

## Review record

- **Reviewer:** the review engine (`plan-8de5db9ec0a935e9`), models `gpt-5.6-terra` (rounds 1 and 2) and `gpt-6.1-sol` (rounds 3 and 4). Rounds used: 4 of a bound of 4 (the owner extended it from 3 by one); the fourth converged with no meaningful finding.
- **Applied (4):** a security-review checkpoint in the risks section, asking the owner once and running a review only on request (R1-F1); the two card tests added to Increment C's verification (R1-F2); the retry-accepted entry's reuse key, no longer tied to the retry prompt (R2-F1);
  the reuse key made from the fixed inputs of the piece and not from the prompt text, because `cardmake._prompt` puts a random token in each prompt, which I confirmed in the code (R3-F1), with a test across two real extractions.
- **Rejected:** none.
- **Left for the owner:** whether to ask for a security review of the journal (a filesystem and untrusted-input surface; not yet asked for), and whether to approve the plan.

## Deferred work

- A partial generation for a book with a piece refused for good (a decision of the owner; changes what a generation means).
- A journal of the checks.
- Reading the refused answers to find why a piece is refused (the folder is full and the files are the owner's to move).
- The PDF size bound, the flag rule, the check's leniency, the queue that visits each model once, and the stale figures of the project README (the Result of `2026-11-11-run-the-theme-extraction-over-the-library`).

## Result

### Increment A (the file of the journal; committed)

- **Done.** New `engine/kb/themejournal.py` (`write`, `read`, `remove`; folder `card-runs/theme-journal/`, file `<book>-<version>.json`) and `engine/tests/test_themejournal.py` (40 tests). It reuses the safe file functions and the entry check of `cardstate` and changes nothing in it.
  The reuse key is a field the module keeps and checks as 64 hex digits; making it is Increment B's. Writing also reads back what it is about to write and refuses values that would not read back equal (a tuple, a key that is not text, a repeated key).
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal` printed `Ran 40 tests ... OK`; `engine.tests.test_cardstate` (shares the functions; not changed) `Ran 38 tests ... OK`; `wb run code-work check` printed `checked 33 plans / check found no problems`. Tests first: the first run failed because the module did not exist.
  Deliberate breaks: 24 one-line breaks of `themejournal.py`, each run against the tests, the file restored identical (sha256 prefix `c34cb7e1421d`). All were caught but one: removing `allow_nan=False` is not caught, because the read-back check refuses NaN too (two checks guard one thing); I left both.
  The break "another folder name" was first missed, because the tests read the name from the module; a test for the documented path was added.
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: a test for another user's file (by patching `getuid`, so the folders are refused too; the file's own check is the same function); the read-back check at write; a `RecursionError` at write is a `KbError`, with a test that makes `json.dumps` raise it (on this Python, 3.15, nesting 5,000 deep neither fails to write nor to read, so a deep value cannot reach it); the unused import removed.
  Not applied: the coupling to `cardstate._check_entry` through a fake entry (the plan names this reuse; a change in `cardstate` is caught by `test_themejournal` because the tests use valid and invalid records). Increment B must pass only data from `_rows` and `_draft`, and its test that a saved journal reads back equal to what was written uses the real shapes.
- **Not run.** The whole suite; no live call. No security review (the owner was asked in the report and did not ask; the reviewer found no concrete exposure and noted that nothing in the repository records the question having been put).
- **Not done.** Increments B, C and D.

### Increment B (the extraction uses the journal; committed)

- **Done.** In `engine/kb/themeextract.py`: `piece_key` (sha256 of the title, the words to avoid as the prompt lists them, the text, the number and the number of pieces; not of the prompt text, because `cardmake._prompt` puts a random token in each prompt); `_listed` (shared with `theme_prompt`); class `PieceJournal`
  (`entries`, `add`, `drop_from`, `for_book`, which reads and writes through `themejournal` and does not use a file that cannot be read); `_saved_answer` (a saved entry is an answer only if its key, the registry entry, the model and the prompt version are those now, and its values pass the shape and the check of `THEME_JOB`);
  `extract` and `make_for_version` take `journal`. In `engine/kb/themecheck.py`, `make_and_check_for_version` takes `journal` and passes it on. A piece whose saved answer does not fit, and every piece after it, is forgotten and asked for; each accepted answer is added (and saved) before the next piece is asked; a refused, runaway or failed answer never reaches `add`.
  An answer accepted at the retry is saved once, with the key of the piece. With no `journal` nothing changes.
- **Calls of mine that the owner did not give** (new in this increment): (1) **a save that fails fails the book** (a `KbError`, "the answer for the piece could not be kept"), as a card's journal does, and the entries in memory stay what was saved; the other way (go on without keeping) would hide a journal that is silently not kept. The limit of a file is 8 MB, far above a book's answers.
  (2) **A saved answer is compared with the model the config names**, not with the one in its own record alone: its record's `model` must equal the configured model of the entry (the earlier run showed the reported name equals the configured one on this server; Increment D will show it again).
- **Verification as run.** Tests first: the new tests failed (`PieceJournal` did not exist). `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme` printed `Ran 240 tests ... OK`; `engine.tests.test_themerun` (it calls `extract` through `make_and_check_for_version`; not named by the plan) `Ran 80 tests ... OK`; `wb run code-work check` clean.
  Deliberate breaks: 21 one-line breaks of the new code (the key, the entry, the model, the prompt version, the shape, the check, the order of save and update, the stale tail, a failed save, each input of the key, `for_book`, the passing of the journal by the two functions), plus the key made of the prompt text (the defect of round 3 of the plan's review): all caught; files restored identical (sha256 prefixes `c23cfc71b56b`, `c4e4922b8cbf`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: a test that a saved answer failing only the shape of the job (a key missing, a key not expected, an item that is not text, an item too long) is asked for again, with a break that shows it; the pieces-count test made to change only the number of pieces (a longer book whose first three pieces keep their text), so that the key's `total` is shown through `extract`.
  Recorded for later, not applied here: the words to avoid come from the library's frequencies and the card, so a book added to the library or a card made again between two goes changes the key of every piece; **Increment C passes `frequencies` counted once for the run** (the run already does) so that a run's goes agree; the reuse also assumes `textutil.clean` is idempotent (not read by the reviewer; the saved values are already clean, and a second clean of clean text is the same in the tests).
- **Not run.** The whole suite; any live call. No security review (not asked; the reviewer found no concrete exposure beyond the trust model of the plan).
- **Not done.** Increments C and D.

### Increment C (the run keeps and removes the journal; the status says how many pieces are kept; committed)

- **Done.** In `engine/kb/themerun.py`: `_serve` gives each book `themeextract.PieceJournal.for_book(...)` and passes it to `make_and_check_for_version`; the journal is removed (`_forget`) when the generation is filed and when the book is dropped (`no_longer_active`, `conversion_changed`), and kept when the book is refused, fails, raises an unexpected error or the program is killed; `_run_names` leaves out the folder `theme-journal` (it sorts before the dated runs and would have taken one of the 20 places read);
  `status` adds `kept` to each item: the number of pieces in the book's journal for a book that is waiting or failed (0 if there is none or it cannot be read), `None` for one that is done or dropped. The run record's form and the `run` report are unchanged (`_items` copies nine fixed keys; `kept` is added in `status` only). A failure to remove a journal is ignored.
  `docs/specs/theme.md`: one new [proposed] statement under "A run over the library". `engine/README.md`: one paragraph (what is kept, when it is removed, when it is reused, what the numbers of a book made in more than one go count, that a save that fails fails the book, `kept`), and the old sentence "there is no journal" qualified.
  The command line is unchanged (`themes-run --help` and `run --help` printed as before).
- **Window recorded, not closed.** If the program is killed after the generation is filed and before the journal is removed, the journal stays; a later `plan --again` of that book then reuses its saved answers and asks only for the checks again. The README says so, and a test shows it (the book gets generations 1, 2 and 3 with the extraction asked for once). A kill between the removal and the saving of the record is the old window (the book is made from its first piece).
- **Verification as run.** Tests first: the new tests failed before the code. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themejournal engine.tests.test_themerun engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_cardqueue engine.tests.test_cardstate` printed `Ran 443 tests ... OK`
  (the card tests show that the shared file functions and the lock behave as they did); `wb run code-work check` clean. The only test of the command line is in `test_themerun` (`CommandTest`), which is in the run. Two helpers of `test_themerun` that left a file open were closed with `with` (the `ResourceWarning`s were printed, not failures, before).
  Deliberate breaks: 10 one-line breaks of the new code in `themerun.py` (a done book keeps its journal, a failed book loses it, the journal not given to the make, a dropped book keeps it, the folder taken for a run, `kept` for a done book, `kept` not computed, `kept` stopping at an unreadable file, a failed removal failing the book, a new journal for every go): all caught; file restored identical (sha256 prefix `8985958f1f83`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: the README sentence "there is no journal" that the new paragraph contradicted; the test of an unreadable journal, which passed whether or not the file was used (it now holds one valid entry and shows the file is not used); the window above stated in the README and tested; a test name that promised more than it checked ("a run planned again" does not mean `--again`, now named for what it does); "the records of its stats" in the README corrected.
  Not applied: the plan's wording "kept 2 of 5 pieces" is shown as two numbers in `status` (`kept` and `pieces`), not as one string; the command prints JSON.
- **Not run.** The whole suite; any live call. No security review (not asked; the reviewer named no concrete exposure: the path is built from ids checked by `cardstate._names`, files are read and written by the checked functions, saved values are checked again on use, and `_forget` and `_kept` cannot be made to stop a run by a hostile file).
- **Not done.** Increment D, the run of the book that failed, on the owner's word after the plan is shown.

### Increment D (the live run of the book that failed; the owner's decision is pending; committed)

- **Run.** `python3 -m kb themes-run plan --book 01M6SR0CSZ177HZK2FS52EKRGE` made run `20261112t122213z-b9a734` (RFC 9110: HTTP Semantics, 29 pieces, estimate 261 to 406 seconds, 58 to 72 check calls; models `gemma4:12b` for the themes and `phi4:latest` for the check, prompts `v4` and `v1`), the plan was shown to the owner with what is sent, and on the owner's word ("Run it")
  `themes-run run` was started at commit `358e80a`. The report is kept outside the repository, mode 600, sha256 `76cf88b01c6d81f4278d03385fb3a2541c0270feeff83238f4dcbe4266e37d99`.
- **Outcome.** The book is **done on its first attempt**: 1 pass, `attempts` 0, no refusal, generation 1 filed. 134 themes; 458 parts stated and 116 inferred (79.8 percent stated); 129 themes (96 percent) carry a flagged word; dropped 17 (14 proofs or definitions, 3 over the size bound); 163 calls (29 for the pieces, 134 for the checks); 316,606 tokens in and 20,712 out;
  431 seconds for the book (434 for the command), a little over the high end of the estimate (406), so the estimate is a guide and not a bound. `status`, while the run was going, showed `kept` 29: all 29 pieces were answered and saved before the check began.
- **Verified against the library, read-only.** The book has generations [1] and the newest valid one is generation 1 with 134 themes; its journal is gone and the journal folder is empty; 175 of the 175 books now have themes, each with the one generation [1], none unreadable.
- **What this run does not show.** No piece was refused this time, so **the resumption from a journal was not exercised live**: it is shown by the tests only. Neither earlier run's refusal of this book repeated, and what refused it before is not known (the folder `refused` is full, so those answers were not kept). It may have been chance, since a refusal of a piece depends on the model's answer. Whether the model name that a live call reports
  equals the configured one, on which the reuse of a saved piece depends, is also not shown, because nothing was reused. The journal was written (29 pieces, `kept` 29) and removed when the book was filed.
- **For the owner to decide.** Whether the plan is complete on this evidence (criteria 1 to 5 are met with recorded evidence; the live resumption is untested, which the plan's step 2 expected to see only if the book failed again); the open decisions listed in the Result of `2026-11-11-run-the-theme-extraction-over-the-library`: the PDF size bound, the flag rule (now 96 percent for this book), the check's leniency, the queue that visits each model once, and the project README's stale figures.
- **Not done.** No push. No security review (not asked).
