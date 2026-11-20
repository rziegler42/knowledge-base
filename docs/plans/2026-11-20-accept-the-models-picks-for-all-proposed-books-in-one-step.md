# Accept the model's picks for all proposed books in one step

Status: Proposed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: the owner's answer to 455 proposals, one book at a time, is the step that holds up the placement of the owner's own books, and a command that records the same answer for all of them follows from that finding)
Specs: docs/specs/shelf.md ("Placement when more than one shelf fits", the paragraph on what an owner's answer is)

## Goal

After `place-propose` the owner has a proposal for each book on `default` and answers each one with `place-review`, which asks one book at a time and takes only a terminal. On 2026-11-20 that is 455 books (read from `place-review --list` at commit `facf457` of `main`: 455 unconfirmed, 1 confirmed, 460 moved), and the owner wants to take the model's pick for all of them.

When this plan is done, **`python3 -m kb place-review --accept-picks`** prints, read only, the list of the books it would answer, with a count for each shelf and a digest of the text, and **`python3 -m kb place-review --accept-picks --digest HEX`** records, for exactly those books and only in the owner's terminal, the same answer that typing `ok` records: the model's pick, or its `none`. The books then wait for `place-apply`, which stays what moves them, with its own list and digest. The step that moves books does not change, and nothing moves in this plan.

## Scope

- `engine/kb/placereview.py`: the list of the books that the step would answer (`accept_plan`), the text the owner reads (`accept_render`), its digest, the preview (`accept_preview`) and the step that writes (`accept_picks`).
- `engine/kb/__main__.py`: the flag `--accept-picks` of `place-review`, with `--digest`.
- `engine/tests/test_placereview.py`, and a new test file for the command line if the existing one has none for `place-review`.
- `docs/specs/shelf.md` and `engine/README.md`: the step, and what it is and is not.

## Non-goals

- Any change to `place-apply`, to `place-propose`, to the matcher, the prompt or the schema.
- Answering with anything but the model's pick: a book whose proposal is `malformed` or an error is left out, as `ok` refuses it; a book the owner has answered is left as it is; a stale, unreadable or moved book is left out, as `place-review` leaves it out.
- An answer from outside a terminal. The step that writes refuses unless the input and the output are a terminal, as `place-apply` does, and takes no answer from an argument, a file or the environment other than the digest of a list the owner read.
- Any move of a book. A recorded answer is a record and not an approval (`docs/specs/shelf.md`); the owner's approval of a move stays their own run of `place-apply --digest`.
- An undo. A book answered by this step is asked again with `place-review --again --book <id>`, as any answered book is.

## Assumptions and constraints

- The answer this step records is the one `review` records for `ok`: an event `placement_confirmed` with `result` of kind `shelf` (the pick's slug) or `none`, `equals_pick` true, and the text of the answer `accept-picks`, so that a count of answers can tell this step's from a typed `ok`. The shape check of the reader (`_confirmation_ok`) is not changed and takes both.
- The list is made from the same reader as `review` (`state_of`), so what this step answers is exactly what `review` would have asked and `ok` would have accepted.
- Writing uses the store's own `append_event`, one line to each book's own log, under the catalog lock as `place-apply` takes it, and the list is made again under the lock and refused if its digest is not the one given. A stop in the middle leaves the books answered so far answered; running the preview and the step again answers the rest (the digest of the new list is another).
- **The engine's code changes, which voids the approval of the crawl** (`docs/specs/population.md`: the fingerprint holds every module of `engine/kb`). The change is built in a worktree and copied to `main` in one step, after the owner is told, and the owner runs `crawl-approve` afterwards.
- The crawl loop and a run of this step must not write at the same time (the writers of an event log take no lock but the file's own append). The owner pauses the loop with the stop file first, as for any hand run.

## Completion criteria

1. `place-review --accept-picks` prints, and writes nothing, a text that names each book (its id, title, address, the shelf of the pick or `none`, and the pick's reason), a count for each shelf, the count of books left out for each reason, and ends with the line `digest: <32 hex>` that is the digest of the text above it.
2. `place-review --accept-picks --digest HEX` refuses unless the input and the output are a terminal, unless the store is open for writing, unless the digest has the shape of one, and unless the list made again under the lock has that digest; it then records one `placement_confirmed` event for each book of the list and no other line.
3. A book answered by it reads as `confirmed` with `accepted_pick` (or `none`) in `place-review --list`, and `place-apply` lists it as it lists a book answered with `ok`.
4. A book that has no pick (`malformed`, error), is stale, unreadable or moved, or is already answered, is not in the list and gets no line.
5. A list that changed between the preview and the step (a book answered or a new proposal) is refused.
6. The spec and the guide say what the step is and that its record is not an approval.

## Increments

### Increment A — The list, the text, the digest and the step

**Outcome:** `placereview.accept_preview(store)` returns the text and the digest and writes nothing; `placereview.accept_picks(store, digest)` records the answers of that list, or refuses.
**Dependencies:** none.
**Affected areas:** `engine/kb/placereview.py`, `engine/tests/test_placereview.py`.
**Steps:**
1. Write the tests first and see them fail: the list holds the unconfirmed books whose newest proposal is a shelf or `none` and no other; a confirmed, stale, unreadable, moved or no-pick book is left out and counted; the text names each book and ends with its digest; the digest changes when any field changes; the step refuses a bad digest, a digest of another list, a list that changed after the preview, a store opened read-only, input that is not a terminal, and input that is a terminal with output that is not (each refusal writes no line); the step writes one line for each book, of the same shape as `review`'s `ok` with the answer text `accept-picks`; a second run writes nothing; `listing` counts the answered books as `accepted_pick` and `none`; `place-apply`'s `plan` lists them.
2. Write `accept_plan`, `accept_render`, `accept_preview` and `accept_picks`, reading with `state_of` and writing with `store.append_event` under `catalog.lock`, and cleaning every shown text with `safe`.
3. Break the code on purpose, one change at a time (the digest ignored, a book with no pick included, an answered book answered again, the terminal check removed, the lock not taken, the list not made again under the lock), see a test fail for each, and restore the code byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_placereview.py` and `engine/tests/test_placeapply.py`, which read what this step writes; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-accept-the-models-picks-for-all-proposed-books-in-one-step#A`.

### Increment B — The command, the spec and the guide

**Outcome:** the owner can run the two forms on the command line, and the spec and the guide say what they do.
**Dependencies:** Increment A.
**Affected areas:** `engine/kb/__main__.py`, the test of the command line, `docs/specs/shelf.md`, `engine/README.md`.
**Steps:**
1. Write the test first: `place-review --accept-picks` prints the text and writes nothing; with `--digest` and no terminal it refuses, both when the input is not a terminal and when the input is a terminal and the output is not, and appends no line either way; the flag cannot be given with `--list`, `--again` or `--book`; the help names the digest.
2. Add the flag `--accept-picks` and the use of `--digest` for `place-review`, and the dispatch to `accept_preview` and `accept_picks`.
3. Write the step into `docs/specs/shelf.md` (the paragraph on what an owner's answer is: this step records the same answer as `ok`, for a list the owner read, in a terminal, with a digest; it is a record and not an approval) and into the guide, with the order of the commands: pause the loop, `place-propose`, `place-review --accept-picks`, the same with `--digest`, `place-apply`, `place-apply --digest`.
**Verification:** the command-line tests and the tests of A; `wb run code-work check`; `git diff --check`; a run of the preview on the owner's library, read only, to show that the list matches `place-review --list` (455 unconfirmed, of which the 5 whose pick is `none` and the malformed ones are named).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-accept-the-models-picks-for-all-proposed-books-in-one-step#B`.

## Verification for the plan as a whole

Increment A's tests stand unless B changes `placereview.py`, which it does not. After B, the tests of `placereview`, `placeapply` and the command line are rerun together, and `code-work check`. No wider run is named: nothing outside the placement modules reads the new lines except `placeapply`, whose tests are in the run.

## Risks and sensitive actions

- **A bulk answer is not a considered one.** The owner accepts the model's pick for each book without looking at each. The model offers one of the five shelves nearest to the book, so a book can only land on a shelf that fits at least roughly, but it can land on a poor one. The text the owner reads before the digest shows each book with its shelf and reason, a count per shelf shows an odd cluster, and the move itself is a second list and a second digest (`place-apply`). An answer is changed later with `place-review --again --book <id>`, and a move is not undone by this plan (an undo is not built; `docs/specs/shelf.md`).
- **The terminal check is an interlock and not proof that a person typed** (`docs/specs/shelf.md`). The step takes its approval from a terminal and a digest of text the owner read; the move still takes its own.
- **Untrusted text.** The title, address and reason of a book come from a web page, a paper or a model; every text is cleaned with `safe` before it is printed, and the digest binds what is printed.
- **The crawl's approval is voided** by the engine change; the owner runs `crawl-approve`.
- A security review: this adds a step that records the owner's approval-like answer for many books, and touches untrusted input and the file system. The owner is asked once whether to run a review with the installed `security-reviewer`.

## Review record

Plan review through the review engine (`gpt-5.6-terra`), 2 rounds of a bound of 3, converged on 2026-11-20.

- Round 1, one finding (major): the plan required the write form to refuse unless input and output are both a terminal, but its tests covered only input that is not a terminal. **Applied:** the steps of A and B now name a test where input is a terminal and output is not, which must refuse and append no line.
- Round 2: no meaningful findings.
- Rejected: none. Left for the owner: the approval, and whether to run a security review (asked once, in the owner's hands).

Increment A, independent review by the `reviewer` agent (read only, 1 exchange of a cap of 6): no blocking findings.

- Applied: the card's text hash (`text_sha256`) is now in the text the owner reads, so that every field written is also a field the digest binds.
- Not applied, with reasons: (1) a proposal whose time (`at`) is not of the shape `place-apply` wants is answered here and left out there as unreadable; a typed `ok` does the same, `review` does not check it either, and the engine writes that shape, so a book would have to be damaged by hand; (2) the catalog lock is held for the whole re-made list, which for 455 books is about a minute of card reads; the wait of any other writer is bounded by the lock's own limit, and the plan has the loop paused; (3) `version`, `generation` and the proposal's time are cut by `safe` in the text while the raw value is written; the engine writes these and the digest binds the card text hash and the schema hash, which a different value would change.
- Could not be checked by the reviewer: that the tests assert what their names say, and the time the lock is held on the real library.

Increment B, independent review by the `reviewer` agent (1 exchange of a cap of 6): no blocking findings. The command line passes only the digest to the step, so the terminal check and the digest cannot be skipped by an argument; the spec and the guide match the code.

- Applied: the guide now says that the crawl's approval is voided and `crawl-approve` is run again before the stop file is removed; the spec now says the step stops at the first error and names the books answered before it.
- Not applied: a command-line test of an empty or upper-case digest; the step's own tests (`AcceptPicks`) already refuse each, so the command line adds none.

## Deferred work

- An undo of a move, and a way to accept the picks for a part of the list (one shelf, or the books above a score). Both are separate decisions.
- The single-book shelves: 84 of the 162 shelves hold one book, and this step will add to some and not to others. A look at the shelf list is separate.

## Result

**Increment A** (built in a worktree at `eb544a4`, copied to `main` in one step, which voided the approval of the crawl).

- Done: `placereview.accept_plan`, `accept_render`, `accept_preview` and `accept_picks`, and 15 tests of `AcceptPicks` and one of `AcceptDirectly` (the display's own cleaning with a hostile value in every field, which a card made by the engine does not reach). Tests were written first and seen failing (14 errors: the functions did not exist).
- Verification run in `main` after the copy: `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_placereview engine.tests.test_placeapply engine.tests.test_placement`, 232 tests, OK, Python 3.15.0; `wb run code-work check`, 74 plans, no problems; `git diff --check`, clean.
- Breaks (19 single changes, each compile-checked, each caught by at least one test, the file restored byte for byte): the digest not compared; the shape of the digest not checked; a book with no pick included; an answered book answered again; the terminal check removed; only the input checked; only the output checked; the store not refused read-only; the lock not taken; `equals_pick` false; the answer text `ok`; a none answered as a shelf; the proposal's time wrong; a stop not named; the title and the reason not cleaned; the left-out counts dropped; the tally dropped; the stale branch counted as answerable. Five of the first run were not caught and the tests were strengthened (the read-only check must come before the lock; the left-out lines; the display's cleaning with a hostile value; a card that cannot be read while the list is made; the message of a bad digest).
- Departures from the plan: the plan's break "the list not made again under the lock" is not a break the tests can show (the digest of the list made before the lock and that of the list made under it are equal unless another process writes in between), so the list is made only under the lock and the break was replaced by "the store not refused read-only". The step says `answered` and not `moved` in its result. Nothing else.

**Increment B** (copied to `main` after A was committed as `d0e1f9e`).

- Done: the flags `--accept-picks` and `--digest` of `place-review` in `kb/__main__.py`; the class `AcceptPicksCommand` (5 tests: the preview prints and writes nothing, and opens the store read-only; the digest form passes the digest on and opens the store for writing; the flag with `--list`, `--again` or `--book`, and a digest without the flag, are refused; a refusal for input a terminal with output not, input not with output a terminal, and neither; the real command with piped input refuses and the flag is in the help); the paragraph of `docs/specs/shelf.md` and the bullet of `engine/README.md`, with the order of the commands and the word that `crawl-approve` is run again.
- Order: the command-line tests were written after the code, not before, which the plan asks the other way round. To show that they test something, the wiring was taken out (the file as it is at `HEAD`) and the new tests failed (10 failure lines, each subtest counted, in a class of 5 tests); it was put back byte for byte.
- Breaks of `__main__.py` (8 single changes, each compile-checked, each caught, the file restored byte for byte): the wiring removed; a digest without the flag accepted; the flag accepted with the other flags; the preview opening the store for writing; the digest form opening it read-only; the digest not passed on (a fixed one passed); the preview printing the digest alone; the flag not in the help. The last was not caught at first, and the help test now checks the flag's own words.
- Verification run in `main` after the copy: `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_placereview engine.tests.test_placeapply engine.tests.test_placement`, 237 tests, OK; `wb run code-work check`, 74 plans, no problems; `git diff --check`, clean. 329 tests had passed in the worktree with `placeapply` named twice by mistake.
- The read-only run of the preview on the owner's library (2026-11-20, `Store.open(write=False)`, nothing written): 453 books would be answered (34 with none and 419 with a shelf, on 135 shelves; 87 of those shelves would get one book), 2 are left out for no usable pick, 1 as already answered, 460 as moved; `place-review --list` says 455 unconfirmed, which is 453 plus 2. The list is 4,221 lines and ends with its digest. 155 books would go to `artificial-intelligence-in-games`; read from their titles, they are papers on poker, Go, checkers, StarCraft and Hex, so the number is the library's (the old library is a collection of game-playing papers) and not a pile-up of a poor pick. A sample of 10 of the other picks read as reasonable, and a few are loose (an electronics textbook on `engineering-and-technology-innovations`).
- Departures from the plan: none.
