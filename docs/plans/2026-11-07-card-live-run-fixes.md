# Two fixes from the first live run of cards

Status: Completed
Created: 2026-11-07
Candidate: none (no new roadmap work; these are two findings of the live run of 2026-11-07-card-stage, recorded in its Result)
Specs: card

## Goal

Two things the first live run of `cards` on three real books showed are put right. A card is no longer marked partial only because
its conversion has no headings, which every PDF lacks, so the mark means something again. And when a model's answer is refused
for its shape, the answer is kept aside where the owner can read it, so a failure can be diagnosed and not guessed at.

## Scope

- Increment A: the conversion having no structure (`flat`) stops being a reason for a card to be partial. The card still records
  the structure. A conversion that is partial, a missing conversion, a sampled book and a card with no model part still make a
  card partial.
- Increment B: when `models.run_job` receives an answer and refuses it for its shape, it raises a refusal that carries the answer
  and the record of the call; the card maker keeps that answer aside in a file and raises a typed refusal that carries the name of
  the file, which `run` recognises, so that the failed report of the book has a `kept` field with the file name (every report has
  the field, empty when nothing was kept). Nothing else is kept aside.
- The documents say both.

## Non-goals

- Making the three cards that exist again. A card is never changed; the three keep their partial mark, and a new card needs
  `cards --again` and new model calls, which this plan does not make.
- Retrying a refused answer, trimming a list that is too long, or loosening any limit.
- Keeping aside an answer for any failure other than a refused shape (a failed call has no answer to keep).
- Viewing, listing or pruning the files kept aside. The owner reads them as files; nothing deletes them.
- The other findings of the live run (a large block cut into small pieces; whether the neutral fields name the field).

## Assumptions and constraints

- A card whose conversion is flat is a normal card for a PDF: the converter gives no headings, the text is whole, and the card
  describes the whole work. The reasons that remain are the ones that say the card describes less of the work.
- `validate` accepts a partial card with reasons and a card that is not partial with none, so the three cards already filed stay
  valid, and so does a card made after this change.
- A model's answer is untrusted data. The file that holds it is written with its text escaped to ASCII (`json.dumps` default), so
  a control or escape character in it cannot reach a terminal when the owner reads the file with `cat`; it is bounded in size (the
  bridge already limits a reply to 256 KB). It is written with descriptors and not by path: the index root is opened without
  following a link, the folder `refused` is made or opened relative to it without following a link, the folder must be a
  directory owned by the user with no access for others (otherwise nothing is written), and the file is created relative to that
  folder, exclusively, without following a link, with mode 600. A name that exists is never overwritten: the name carries a random
  suffix, and a clash is met with a new suffix, a few times, before giving up.
- The place is the index root of the library, in a folder `refused`. That root holds what can be rebuilt, so a file there is an aid
  and not a record; the folder is the owner's to delete. The owner's index root is a personal path and appears in no tracked
  file. The spec says only that such output is "kept aside for inspection" and does not give a place (`theme.md`, "Size and kind").
- A bound stops the folder growing without end: no more than 200 files are kept, and past that nothing is kept and the report says
  so, since the program deletes nothing.
- Tests use the fake launcher of `engine/tests/test_cardmake.py`; no step makes a live model call.

## Completion criteria

1. A card whose only possible reason was a flat conversion is not partial and records its structure as `flat`; a partial
   conversion, no conversion, a sampled book and a card with no model part still make a card partial.
2. A refused answer is kept in a file in the index root with the book, version, job, registry name, model, prompt version, date,
   the reason and the answer, escaped, bounded, mode 600, in a folder that is not a link and that no other user can enter; two
   refusals with the same metadata keep two files; the failed report that `run` returns for the book names the file in its `kept`
   field; and no file is kept for a failed call, a missing setting, a success or a skip.
3. No path or name of the owner appears in a tracked file.

## Increments

### Increment A — A flat conversion no longer makes a card partial

**Outcome:** the mark `partial` on a card means that the card describes less of the work than the book holds, and not that a PDF has no
headings.
**Dependencies:** none.
**Affected areas:** `engine/kb/card.py` (the reasons in `_conversion`), `engine/tests/test_card.py`, `engine/README.md` and
`README.md` where they describe the partial mark.
**Steps:**
1. Write the tests first, changing the test that says a flat conversion is partial to say that it is not, and that the structure
   is still recorded as flat: they fail. Keep the tests that a partial conversion, a missing conversion, extra reasons and a card
   with no model part are partial.
2. Remove the flat reason from `_conversion`. The structure stays in the conversion summary of the card, and `card-show` still
   prints it.
3. Say in `engine/README.md` which reasons make a card partial.
4. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_card engine.tests.test_cardmake`. The second file runs the commands that
read and print the mark.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-live-run-fixes#A`.

### Increment B — Keep a refused answer aside

**Outcome:** when a model's answer is refused for its shape, the owner can read what it wrote.
**Dependencies:** none (A and B do not touch the same code).
**Affected areas:** `engine/kb/models.py` (a refusal that carries the answer), a new module `engine/kb/refused.py`,
`engine/kb/cardmake.py` (keep it aside, a typed refusal that carries the file name, and the `kept` field of the report), their tests (`engine/tests/test_models.py`,
`engine/tests/test_refused.py`, `engine/tests/test_cardmake.py`), `engine/README.md` and `README.md`.
**Steps:**
1. Write the tests first; they fail. In `test_models`, a refused shape raises a refusal that is a `KbError` and carries the answer
   and the record, and a failed call or a bridge refusal carries none. In `test_refused`, the file: its name from checked ids, a
   job name, a time and a random suffix; its content; ASCII escaping of a control character; the size bound; mode 600 in a folder
   of mode 700; a `refused` that is a link, a file, or a directory that others can enter is refused and nothing is written; an index
   root that is a link is refused; a name that exists is never overwritten, and two refusals with the same metadata and a forced
   clash of the suffix keep two files; the limit of 200 files. In `test_cardmake`, through `run`: a book whose answer is refused
   leaves one file and its failed report has the `kept` name, nothing is filed as a card, every other report has `kept` empty, a
   write that fails leaves the refusal reported with a note, and the other kinds of failure and a success leave no file.
2. In `models.py`, make `run_job` raise that refusal when the shape check fails, with the answer text and the record of the call.
3. Write `refused.keep(index_root, ...)` with descriptors: open the index root without following a link, make or open `refused`
   relative to it without following a link, check that it is a directory owned by the user with no access for others, count its
   files, create the file relative to it with `O_EXCL`, no-follow and mode 600 under a name with a random suffix (a new suffix on a
   clash, a few times), and return the file name; stop at the limit of 200 and say that nothing was kept.
4. In `make_for_version`, catch that refusal around the model part, keep the answer aside with the book, version and job, and
   raise a typed refusal (a `KbError`) that carries the file name, or a note that the answer could not be kept, so that the card is
   not made. In `run`, recognise that refusal and put the name in the `kept` field of the failed report; every report gets the
   field, empty by default. A failure to write the file must not hide the refusal.
5. Say in `engine/README.md` where the files are, what they hold and that nothing deletes them.
6. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_models engine.tests.test_refused engine.tests.test_cardmake`. The model
tests are included because `models.py` changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-live-run-fixes#B`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After B, rerun
`python3 -m unittest engine.tests.test_card engine.tests.test_cardmake engine.tests.test_models engine.tests.test_refused
engine.tests.test_setup` once; the setup tests are included because the commands print the report that B extends. The wider engine
suite is not named: the plan changes no stage, no index and no conversion. A wider run is the owner's to ask for.

## Risks and sensitive actions

- **A file of untrusted model text is written to disk.** It is escaped to ASCII, written with mode 600, never through a link and
  never over an existing file, bounded in size and number, and in a folder the owner can delete. Nothing reads it back into the
  engine, so its content steers nothing.
- **It sits in the index root,** a personal path that is never committed. The report names the file and not the folder.
- **A card that no longer says "partial" for a flat conversion** could hide that an agent should treat the structure as poor. The
  card still records the structure as `flat`, and `card-show` prints it.
- **No live call is made by this plan.**

## Review record

Reviewer: Codex through the review engine (model gpt-5.6-terra). Round 1 of 3: changes needed, three findings, all applied.

- R1-F1, applied: the file name could not reach the failed report, because `run` builds a new failed report from only the text of
  an exception. Increment B now raises a typed refusal that carries the name (or a note that the answer could not be kept), `run`
  recognises it and fills a `kept` field that every report has, and the tests check the report `run` returns.
- R1-F2, applied: a name built from the book, version, job and time can repeat, and an exclusive create would then lose the new
  answer. The name now has a random suffix, a clash is met with a new suffix a few times, and a test forces a clash.
- R1-F3, applied: checking that the folder is not a link and then creating a file by path leaves a gap, and the plan had promised
  that no link is followed. The file is now written with descriptors: no-follow opens of the index root and of `refused`, a check
  that it is a directory owned by the user that others cannot enter, and an exclusive no-follow create relative to it, with tests
  for a link, a file, an open directory and a link as the index root.

## Deferred work

- Viewing or listing the files kept aside, and removing old ones.
- Making the cards of the three books again, and a trial of whether the cards help (`cards#card-trial`).
- A large block cut into pieces of 5,000 characters, and a check of the neutral fields for the book's field.

## Result

### Increment A — A flat conversion no longer makes a card partial (2026-11-07)

Removed the reason "the conversion has no structure (flat)" from `_conversion` in `engine/kb/card.py`, with a comment saying why.
The card still records the structure (`flat`) in its conversion summary and `card-show` prints it. A partial conversion (with its
reasons), a missing conversion, a sampled book, a book below the cutoff and a card with no model part are still partial, and a flat
conversion that is also partial is partial for that reason only. `validate` is unchanged, so the three cards already filed, which
carry the old reason, stay valid and read back (a test files and reads one). `engine/README.md` has a new bullet in the Cards section
listing when a card is marked partial. The root `README.md` is in the plan's list for this increment but its only mention of
"partial" is about web pages, so it is unchanged.

Verification run: `python3 -m unittest engine.tests.test_card engine.tests.test_cardmake` gave 129 tests, OK. The changed and added
tests were written first and three failed before the change. Five deliberate breaks were each caught (a flat conversion partial
again; a partial conversion not partial; the partial reasons dropped; a missing conversion not partial; the structure not
recorded). Not run: any other test file, and any live call. The three existing cards were not made again.

Review: the `reviewer` agent, one exchange, no blocking findings. It found no other text in the repository that says a flat
conversion makes a card partial, and nothing else in the engine that reads the flat reason (the search, read and index code read the
conversion's own partial check, not the card). Nothing applied beyond the above.

### Increment B — Keep a refused answer aside (2026-11-07)

`engine/kb/models.py`: `run_job` raises `AnswerRefused` (a `KbError`) when it received an answer and the shape check refused it; the
refusal carries the answer (`reply`), the record of the call and the job name. A failed call, a reply that is not of the bridge's
form, a prompt that is refused before sending, a missing setting and the switch off still raise a plain `KbError` with no answer.
New `engine/kb/refused.py`: `keep` writes the answer to a file in the folder `refused` of the index root and returns the file's
name. It is written with descriptors: the index root is opened without following a link, `refused` is made or opened relative to it
without following a link, it must be a directory owned by the user with no access for group or others in its mode bits, the files
are counted (at 200 nothing more is kept and nothing is deleted), and the file is created relative to it, exclusively, without
following a link, with mode 600 and a random suffix in its name (a new suffix, up to five times, on a clash). The file is JSON with
the book, version, job, model entry, prompt version, date, token counts, the cleaned reason and the answer (cut at 262,144
characters, `answer_cut` says so), every character outside ASCII escaped. A file that cannot be written whole is removed. The ids,
the version and the job in the name and the record are checked; nothing reads a file back. `engine/kb/cardmake.py`:
`make_for_version` catches the refusal around the model part, keeps the answer aside and raises `CardRefused`, which carries the
file name or a note that it could not be kept; `run` recognises it and puts the name in the `kept` field of the failed report, and
every report has the field (empty by default). The report names the file and not the folder. `engine/README.md` says where the
files are and what they hold, and its sentence that a refused answer is not kept is corrected. The root `README.md` has the plan's
row and a clause about the refused answer.

Verification run: `python3 -m unittest engine.tests.test_card engine.tests.test_cardmake engine.tests.test_models
engine.tests.test_refused engine.tests.test_setup` gave 290 tests, OK (the new tests also pass with a resource warning treated as an
error). Tests were written first and failed because the module did not exist. Nineteen deliberate breaks were each caught (a
refused shape being a plain error; the index root or the folder followed through a link; a folder others can enter used; the file
limit not enforced; an existing file overwritten; a clash giving up at once; the file not private; the answer not escaped, not
bounded; the reason not cleaned; the version not checked; a refused answer not kept; the report not naming the file; a failed write
hiding the refusal; the note missing from the reason; a half-written file left behind; a failed write not an error of the engine;
a descriptor leaking when the stream cannot be made). Not run: any other test file, and any live call: this plan makes none, so the
three real cards and the refusal seen in the live run were not repeated. No security review was asked for or run.

Review: the `reviewer` agent, one exchange, no blocking findings, and no gap between a check and its use in the write. Applied: a
write that fails (a full disk) used to leave an empty or half-written file that counted toward the limit and was not mentioned; it
is now removed and the failure is reported, and a descriptor cannot leak when the stream cannot be made (tests first, and the
second needed a new test after a break survived); the docstring and the README no longer say more than the code checks. Recorded
limits, not changed: no-follow covers the last step of the path to the index root and to `refused` (the library's roots are checked
for links when it is set up, which is why a link higher up is not looked for here), and the folder check reads the mode bits, so an
access list that macOS can add is not seen. Two refusals within one second keep two files (the suffix); the count of files is a
check outside the create, so two runs at once could pass 200 by a little.

Plan as a whole: each increment's recorded verification still stands. Completion criteria 1 to 3 are met: a flat conversion alone
no longer makes a card partial and the structure is still recorded; a refused answer is kept with its metadata, escaped, bounded and
private, the report names the file, and nothing is kept for any other failure; and no name or path of the owner is in a tracked
file. The three cards made in the live run were not made again and keep their old reason.
