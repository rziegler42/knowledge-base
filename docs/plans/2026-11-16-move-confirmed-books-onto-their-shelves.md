# Move the books the owner confirmed onto their shelves

Status: In Progress
Created: 2026-11-16
Candidate: none (no roadmap holds a candidate for it: the Cards roadmap, `docs/roadmaps/cards.md`, names "shelf filing and reshelving by card" among the work that follows it and lists no candidate for it, and the shelves, the fetch engine and the crawler have no roadmap; adding a candidate or a roadmap is the owner's change of direction, and **the owner decides before approving whether this plan stands with `none` or waits for that change**; this plan follows `2026-11-15-propose-a-shelf-for-each-book`, whose non-goal it is, and the owner's request of 2026-11-16 to draft it)
Specs: docs/specs/shelf.md, docs/specs/book.md, docs/specs/card.md

## Goal

Today every book is on the shelf `default`. The engine has proposed a home shelf for 202 of the 209 books and the owner has answered 21 of those proposals; each answer is a line in the book's event log, a record and not an approval (`docs/specs/shelf.md`, "Placement when more than one shelf fits"). This plan adds the step that moves books. **It delivers the default level of the spec's governed action only** (the spec's `reshelve-approve` ships at `block`: the owner at a terminal): the owner sees the list of moves and a digest of it, in their own terminal, and the engine moves only what that digest names. It is **not** the spec's governed action: the spec's other levels (`ask`, `delegated`, `none`) and the host's ceiling need the workbench to declare the action, which this plan does not do and does not claim.

When it is done:

- the engine can print the list of moves it would make (`place-apply` with no digest): each book, the shelf it leaves, the shelf it joins, where that choice came from, and the books it leaves out with the reason for each, and a digest of that exact text; it writes nothing;
- the engine can make the moves (`place-apply --digest <digest>`), only in a terminal, only if the digest is the one of the list as it stands now, and each move is a change of the book's `shelf` field and one `reshelved` line in its event log;
- the owner has run it on the library's confirmed books, and the Result says what moved, what did not, and that nothing else in any book changed.

## Scope

- **The list** (`engine/kb/placeapply.py`, command `place-apply`): a book is on the list when it is active, on the shelf `default`, has a current `placement_proposed` event (the card and the schema are those of the proposal) and a `placement_confirmed` event that answers that proposal with a **shelf** (the model's pick the owner accepted, or another shelf the owner chose), and the shelf is a home shelf of the tracked schema whose name the store accepts. The preview prints one block for each book (its title and address, cleaned as `place-review` cleans them, its shelf's name and path, whether the owner's answer was the model's pick, and the model's reason), then the books left out, counted by reason, then the digest.
- **The move** (`place-apply --digest <32 hex>`): refuses unless its input and its output are a terminal; recomputes the list while holding the catalog's writers' lock (`catalog.lock` on the index root, the one lock the library has) and refuses when its digest differs from the one given; then, for each book in the order of the list, reads the book's root file again and refuses that book (stopping the run) if its `shelf`, `state` or `current_version` is not what the list was made from, changes the `shelf` field with the store's own `set_shelf`, reads the root file back to check it, and appends one `reshelved` event (`from`, `to`, the `at` of the proposal and of the confirmation, the digest, the schema's hash). It stops at the first error and says which books moved. A run that stopped, or a move whose event could not be written, is finished by running the preview again and applying its new digest: a book already on its shelf with no `reshelved` event of this plan is listed as "to record" and gets its event.
- **`place-review` after a move.** A book that is no longer on `default` is shown as moved in `--list` and cannot be answered again (an answer would change nothing).
- **Documentation:** the commands and the spec say what is built.

## Non-goals

- **Moving a book the owner has not answered.** 181 of the 202 proposals are unconfirmed; they stay on `default`. Moving them as a batch is a different decision (see Deferred work).
- **A change of a card, a version, a payload, an id, the schema, the matcher or the proposal.** Cards are generations that are never edited; **a card keeps the `shelf` it had when it was made** (`default`), so a moved book's older card names the old shelf. That is a recorded limit, not a fix (see Risks).
- **The workbench key `reshelve-approve` and the level `ask`.** A level of `ask` needs a module that the workbench knows to declare the action with a preview argument; the engine is not one, and that change is in the workbench, outside this repository. This command is the step the owner runs themselves at a terminal, which is what `block` means; a later plan can declare it.
- **Undo.** A move can be reversed by a later move; the `reshelved` event records the shelf it left. No command for it here.
- **Shelf visibility, counts per shelf, the holding shelf, activation, seeding, the tie margin.** None of them is built; none is touched.
- **Placement at capture, and placement by an OpenAlex primary topic.**
- **Sending anything to a model.** This plan makes no model call and sends nothing off the machine.

## Assumptions and constraints

**The owner's choices so far:** none for this plan. The plan rests on the spec statements that a move edits the home shelf and logs it, that a move never changes a book's id and changes no bytes of the book (`docs/specs/book.md`), that the owner approves a list (`docs/specs/shelf.md`, "Reshelving"), and that a recorded confirmation is a record and not an approval (the bullet added by the last plan).

**My calls, not the owner's** (the owner may change any before approving):

- *Only answered books move.* The list is the books with an owner answer that names a shelf. Today that is 20 books of the 21 answered (one answer was `none`); a recount at the time of the run decides. The owner's answer is an input of the list, and the owner's approval of the list, with its digest, is a separate act.
- *The approval is the owner's terminal and a digest.* `place-apply` with no digest is read-only and agent-safe: it prints the list and its digest. With `--digest` it needs a terminal for its input and output, takes the digest from its argument, and refuses a digest that is not the one it computes now. The digest is the first 32 hex characters of the SHA-256 of the exact text the preview prints, as the workbench does for its own previews, so that what the owner read is what is bound. **The terminal check is an interlock, not proof that a person typed** (the limit of `place-review`: a program that holds a pseudo-terminal passes it, and anything that can write the library as the owner can edit a root file directly); the owner who types the command and reads the preview is the approval.
- *A shelf the store refuses is left out, not forced.* The store accepts shelf names of at most 64 characters; 13 of the 4,534 home shelves of the schema have longer slugs (the longest has 83). **None of the 193 proposals and 20 answers that name a shelf today names one of them.** The list leaves such a book out with the reason. Widening the store's rule is a change to its own tests and to the card's, and is not made here.
- *No visibility line is faked.* The spec says a proposal shows a change of visibility. The engine models no shelf visibility today (a search for the word finds only hidden-text handling in HTML), so no move can change one; the preview prints one line saying so, and a later plan that builds visibility must change it.
- *The event is `reshelved`,* the name `docs/specs/book.md` already lists for an event log. Its data: `from`, `to`, `proposal` and `confirmation` (the `at` of each), `digest`, `schema_sha256`, `via` (`place-apply`).
- *The concurrency guarantee is narrow, and I say so.* The store has no lock over the books' root files: the writers of a root file (capture, a new version, a state change, `set_shelf`) take none, and the one lock the library has is the catalog's, in the index root, which the index and vector writers take. `place-apply` holds that lock, which keeps it from running at the same time as an index or vector build, and it re-reads each book's root file just before and just after its write. **That does not exclude another writer of the same root file in the same instant**, and a read-modify-write by one in the gap could be lost. The plan therefore asks the owner to run no capture, process or card command while `place-apply` runs (a precondition the engine cannot enforce and the Result records as kept or not), and a shared writer lock over the root files is Deferred work, not built here.
- *Each move is two writes* (the root file by `set_shelf`, then the event). They are not one atomic act; the recovery above ("to record") is what makes a stop between them harmless, and a test shows it.
- *Command name* is mine (`place-apply`).

**What leaves the machine:** nothing. **What changes in the library:** for each moved book, the `shelf` value in its root file and one line in its event log. A hash of the root file of every book, and of every other file of every book folder, is taken before the run (Increment C) and compared after, which the earlier plan could not do.

**Constraints.** Tests first for every unit of code; deliberate breaks of each new module (compile-checked); the `reviewer` agent's reading of each increment; a recount by a snippet that does not use the module's code; commits and the push only on the owner's word. No change to capture, convert, card, search, theme, placement or schema code, except the one small change to `placereview.py` named above, and `store.py` is used and not changed.

## Completion criteria

1. `place-apply` with no digest prints the list and its digest and writes nothing (a hash of the library before and after, in the tests and in the run); a recount by a snippet that reads the event logs and root files directly gives the same books, and the same left-out counts by reason.
2. `place-apply --digest` refuses, with a reason and nothing written, when its input or output is not a terminal, when no digest or a wrong digest is given, and when anything the list depends on changed after the preview (a new answer, a changed card, another shelf of the book, the schema); a test shows each refusal, and a deliberate break of each check makes a test fail.
3. After the owner's run: each moved book is on the shelf its answer named, has one `reshelved` event that records where it came from, and its root file equals its before-state in every field but `shelf`; every other root file is byte for byte the one hashed before; no other file of any book folder changed (cards, versions, payloads); the counts are recounted by a snippet.
4. A stop between the two writes of a move leaves the library consistent and a second preview and apply completes it (a test; and a real stop is not required).
5. The new modules' tests and breaks, the tests of the files touched, and `wb run code-work check` pass; the commands and the spec are updated; nothing else in the repository changes.
6. The owner has read the result and says what comes next.

## Increments

### Increment A — The list and its digest (read-only)

**Outcome:** `python3 -m kb place-apply` prints the list of moves, the books left out by reason, and a digest, and writes nothing.
**Dependencies:** none (the proposals and answers of the earlier plan exist).
**Affected areas:** `engine/kb/placeapply.py` (new), `engine/kb/__main__.py` (the command, preview only), `engine/tests/test_placeapply.py` (new), a trial script and breaks outside the repository.
**Steps:**
1. Write the tests first, on a temporary library: a book with a current proposal and an answer naming a shelf is listed; each of these is left out with its own reason and counted: unanswered, answered `none`, skipped, proposal stale (card or schema changed), book not on `default`, not active, the answered shelf not in the schema or not a home shelf, a name the store refuses, an event log that cannot be read; the latest answer of a book counts (as in `place-review`); the order of the list is the order of the book ids; the digest is the same for the same library and different when any shown or bound input differs (a title, a reason, an answer, a shelf, the schema); the preview prints the line about visibility and the cleaned texts; and no file of the library changes (the hash of all files before and after).
2. Write `placeapply.py`: the eligibility from the event logs through the reader the earlier plan hardened (`store.read_events`), reusing `placereview`'s checks of a proposal and of an answer instead of copying them; the text of the preview built once and the digest taken from that text; every shown text cleaned as `place-review` does.
3. Add the command with no `--digest` argument yet; with an argument it refuses and says it is not built.
4. Deliberate breaks of the module (each compile-checked, restored byte for byte, equivalent mutants dropped), as in the earlier plans.
5. Run the preview on the library and recount the list and the left-out counts with a snippet that does not use the module.
6. The `reviewer` agent reads the increment; record the Result and the review.
**Verification:** `python3 -m unittest engine.tests.test_placeapply engine.tests.test_placereview engine.tests.test_placement engine.tests.test_store`; the breaks; the recount; `wb run code-work check`. The run of the preview on the library is read-only and sends nothing.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-move-confirmed-books-onto-their-shelves#A`.

### Increment B — The move, behind the terminal and the digest

**Outcome:** `place-apply --digest <digest>` moves the listed books in a terminal, and nothing else; `place-review` knows a moved book.
**Dependencies:** A.
**Affected areas:** `engine/kb/placeapply.py`, `engine/kb/placereview.py` (the state `moved`, only), `engine/kb/__main__.py`, `engine/tests/test_placeapply.py`, `engine/tests/test_placereview.py`, breaks outside the repository.
**Steps:**
1. Write the tests first: the refusals of criterion 2, each alone, each leaving the library byte for byte as it was; a move changes only the `shelf` of the root file (the rest of the root file, parsed, equal; and its formatting as `set_shelf` leaves it, which the test pins) and appends one `reshelved` event with the data above; a book not on the list is untouched; the digest of the list is recomputed while the catalog lock is held and a change made between the preview and the lock is refused; a root file changed (its `shelf`, `state` or `current_version`) between the list and its write stops the run with that book untouched and the earlier moves recorded; the catalog lock is held for the whole apply and a second apply meanwhile is refused; a stop after `set_shelf` and before the event (the event writer made to fail) leaves a book that the next preview lists as "to record" and the next apply completes, with one event only; two runs with the same digest do not move a book twice; the first error stops the run and the output names the books that moved; the output cleans every shown text; `place-review --list` counts a moved book as moved and a direct answer for it is refused.
2. Add the move: terminal interlock as `place-review` has it (input and output, no answer from an argument, a file or the environment), the digest check under the catalog lock, the re-read of each root file before and after `set_shelf`, `append_event`, the recovery path. No shared lock over the root files is added and `store.py` is not changed.
3. Add the state `moved` to `place-review` and nothing else.
4. Deliberate breaks of every new check.
5. **Security review.** The change lets a recorded line reach a write of the library's own files, so the owner is asked once whether to run a security review with the installed module (`security-review`), and it runs only if the owner asks; the points to look at are named in the plan's Risks.
6. The `reviewer` agent reads the increment; record the Result and the review.
**Verification:** the test suites of Increment A plus `engine.tests.test_models`; the breaks; `wb run code-work check`. Nothing is run on the library in this increment: the owner's run is Increment C.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-move-confirmed-books-onto-their-shelves#B`.

### Increment C — The owner's run on the library

**Outcome:** the books the owner answered have moved, and the Result says exactly what changed.
**Dependencies:** B, and the owner's word.
**Affected areas:** the library's root files and event logs for the listed books (outside the repository), the plan's Result.
**Steps:**
1. **Before anything moves,** hash every file of every book folder (root file, cards, versions, payloads, event log) into a file outside the repository and cite its hash in the Result; this is the baseline the last plan lacked.
2. Run the preview and recount it independently; show the owner the preview and the digest.
3. The owner reads the preview and, if it is right, runs `place-apply --digest <digest>` in their own terminal. The agent does not run the apply: it refuses a non-terminal, and the owner's act is the approval.
4. Hash again and compare: moved books differ in the `shelf` field and the event log and nowhere else; all other files of all books are equal; recount the events; run the preview again (it must now list nothing to move).
5. Record the Result with the counts, what was left out and why (including the 181 unanswered), and the plain statement that the owner's answers and these moves are not a measure of the matcher's accuracy.
**Verification:** the comparison of step 4; the recount; the second preview; `wb run code-work check`.
**Evidence:** the one local commit (the plan's Result), with the trailer `Plan: 2026-11-16-move-confirmed-books-onto-their-shelves#C`.

### Increment D — The commands and the spec

**Outcome:** the documents say what is built.
**Dependencies:** C.
**Affected areas:** `README.md`, `engine/README.md`, `docs/specs/shelf.md`, `docs/specs/book.md` and `docs/specs/card.md` where they say a reshelve or the card's shelf.
**Steps:**
1. Add the command to the README's list and a section to `engine/README.md` in the form of the others: what the preview prints, what the digest binds, what the apply refuses, what it writes, the recovery, the left-out reasons, and the limits (the terminal is an interlock; the card keeps the shelf of its time).
2. Update the spec's built-in-the-engine bullet for placement and say in `docs/specs/card.md` or `book.md` that a card's `shelf` is the shelf at the time it was made, if the owner reads that as a statement of what is true now and not a change of direction; if the owner reads it as a change, it stays out.
3. Read every claim against the code, as the earlier plan did; the `reviewer` agent reads the documents.
**Verification:** `wb run code-work check`; `wb check`; no test is run unless code changed.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-move-confirmed-books-onto-their-shelves#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the new module's tests and those of `test_placereview`, `test_placement`, `test_models` and `test_store` are rerun; the hash of every file of every book is compared with the after-state recorded in Increment C; the counts of the event logs are recounted; the hashes of the code files are compared with the ones the Results cite; and `wb run code-work check` is run. The engine's other tests are not rerun: nothing else in the engine changes.

## Risks and sensitive actions

- **A move writes the library's own data.** A move edits the `shelf` field of a root file and appends an event; the only way back is another move (the event records where the book came from). The baseline of Increment C is what shows afterwards that nothing else changed.
- **Another writer in the gap.** The re-read before and after a write narrows but does not close the window in which another process could rewrite the same root file (see the narrow guarantee above); the owner runs nothing else against the library during the apply.
- **A recorded answer reaches a write.** An answer event is a record that anything able to write the library as the owner could forge. The gate is the owner's terminal and the digest of the list that the owner read; the engine refuses a list that changed after the preview. The points for a security review, if the owner asks for one: the forged-event path (an answer appended by a program), a digest that does not bind something the move depends on, a terminal check that a pipe or a here-document could pass, a race between the preview and the lock, a shelf name that reaches a path or a regular expression, and a stop between the two writes.
- **The card keeps the old shelf.** A moved book's card says `default` until a card is made again. Nothing in the engine reads the card's shelf for a decision today (a card search sets aside nothing by shelf, and guest access is not built), but a later plan that does must read the root file's shelf, or make the cards again. The spec's statement that a guest sees a card only if its shelf is shared is not built and is not affected.
- **The recorded 20 are a small and unrepresentative first batch** (the library's first books in id order: web pages and famous machine-learning papers); moving them moves nothing the owner has not read. The counts are not a measure of accuracy.
- **Shelf names the store refuses.** 13 shelves of the schema; none is used today; a future answer for one is left out with its reason and is not forced.

## Review record

### The plan (before approval)

One round of the review engine (the `ask-codex` bridge, model `gpt-5.6-terra`, location class `unknown`; the plan holds no secrets), three major findings, all applied, none rejected: the candidate line now says that the Cards roadmap names reshelving as work that follows it and lists no candidate, and leaves to the owner whether the plan stands with `none`; the goal and the deferred work say that this is the `block` level of the spec's governed action only and that the other levels stay unmet; the claim of a writers' lock was wrong (the store has no lock over root files, only the catalog's lock in the index root) and the plan now holds that lock, re-reads each root file before and after a write, states the narrow guarantee and defers a shared lock. The owner chose to let the plan stand with `none`, to take the `block` level for the first move, and approved the plan.

### Increment A

The `reviewer` agent, one exchange (the first of this plan; the cap is 6), read only; it could not run the tests or read the breaks script, which lie outside the repository, and said so. **No blocking finding.** Applied: the pick flag is worked out from the shelves, not taken from the event; the Result says the workbench files are not part of the increment and that the hash of the real library was taken in the run. Left for Increment B: refuse an answered shelf equal to `default`. Accepted as stated: tests of the schema's effect on staleness live in `test_placereview`.

## Deferred work

- **The books the owner has not answered (181 proposals).** Moving them by the model's pick, in batches after the owner reads a sample, or only after the owner answers them, is a decision for the owner, with the evidence of the 21 answers and the nine `none` books in the earlier plan's Result.
- **The workbench key and the levels.** Declaring this action in the workbench so that it offers `ask`, `delegated` and `none` with a preview, under the host's ceiling, is what `docs/specs/shelf.md` requires of the governed action `reshelve-approve` (which offers all four levels); it is a change to the workbench (a module), outside this repository, and until it is made this command is the `block` level only. The spec's statement stands unmet, and the owner decides whether it must be met before books are moved at all.
- **A shared writer lock over the books' root files,** used by every writer of a root file, which would make the digest-to-write guarantee complete. It changes `store.py` and every writer's tests.
- **What to do with the books the model leaves with `none`,** including the overview pages that fit no topic shelf: a proposal for a custom shelf or a placement at the subfield level.
- **The card's shelf** (made again, or read from the root file) and **widening the store's shelf-name length** to the schema's longest slug.
- **Undo,** shelf visibility, counts per shelf, the holding shelf, placement at capture and the activation of shelves.

## Result

### Increment A — the list and its digest (done on 2026-11-16; not yet committed)

**Changed:** `engine/kb/placeapply.py` (new: `plan`, `render`, `digest_of`, `preview`; the reasons a book is left out; the store's own shelf-name pattern imported, not copied), `engine/kb/__main__.py` (the command `place-apply`; with no argument it prints the preview and writes nothing; with `--digest` it refuses and says the move is not built yet), `engine/tests/test_placeapply.py` (new, 34 tests). Files: `placeapply.py` `5223a377…99d06`, `test_placeapply.py` `1fc52ccb…22371`, `__main__.py` `f9e27e87…1036b`. **The workbench files and `AGENTS.md` that `git status` shows modified are the owner's own change to the workbench, not part of this increment, and are not in its commit.** `placereview.py`, `placement.py` and `store.py` are not changed; the list reuses `placereview.state_of`, `safe`, `_address` and `_path`, and `store._SHELF`.

**What a book needs to be listed:** a readable root file, state `active`, shelf `default`; a newest proposal that `state_of` finds current (the same card version, generation and text and the same schema file) and not an error; the newest answer to that proposal naming a shelf (not `none`, not a skip); and the shelf is a home shelf of the schema, **one of the five the proposal offered** (a check that `place-review` does not need, because it writes only those, but a forged answer could name any shelf of the schema) and a name that the store accepts. Every other book is counted under one reason (13 reasons, in a fixed order); a test shows that each book is listed or counted exactly once. The preview prints, for each book, its id, title, address, the shelf it leaves and the one it joins (slug, name, path, scope), the model's pick, whether the owner's answer is the pick, the model's reason, the card's generation and version and the times of the proposal and the answer; then the counts; then a line that the engine has no shelf visibility, so no move changes one; then `digest: <32 hex>` of everything above that line. All shown text is cleaned as `place-review` cleans it, in the item and again in the render, so that no line of it can imitate the digest line.

**Verification, run.** *Tests first:* the first run failed with `ImportError: cannot import name 'placeapply'`, as it should. `python3 -W error::ResourceWarning -m unittest engine.tests.test_placeapply engine.tests.test_placereview engine.tests.test_placement engine.tests.test_store`: **181 tests, OK** (Python 3.15.0; the 34 of this module in 9 seconds). *Deliberate breaks* (`breaks_placeapply.py` `389b4a64…ab1d8`, 68 breaks of `placeapply.py` and `__main__.py`, each compile-checked and each file restored byte for byte): **the first run caught 58 and missed 9, and the nine showed what the tests had not tested:** (1) a model `none` whose stored answer has no `chosen` key (the shape check allows it) was not tried; (2) the name of the model's pick was not asserted when the owner chose another shelf; (3) the scope of the shelf was not asserted; (4 and 5) the time of the proposal and the time of the answer fell in the same second, so a swap of them was invisible; (6 and 7) a title and the whole render were not shown to be cleaned, because a card's title is already cleaned when the card is made and the render cleans again, which hid a break of either; (8) `digest_of` was not tested on a value that is not text; (9) the command's opening of the store read-only was not tested. **Each gap got a test** (a clock that gives every line a different time; a hostile title injected at the list's own read of the card; a hostile item given directly to the render; and so on) and the nine breaks were run again against the stronger tests: **all caught** (11 ran, the two extra being the breaks of the times shown). The other 58 stay caught, since tests were only added. No break was dropped as equivalent.

**An independent recount** (a snippet that reads the root files and the event logs and imports nothing of the engine but its config reader): of the 209 books, **20 would move, 181 are unanswered, 7 have no proposal and 1 was answered `none`** (20 + 181 + 7 + 1 = 209), the same books and shelves as the preview, which sorts by book id where the recount walks the folders in shard order (`recount-moves-A.json` `20423bc3…ad35c`). **The preview on the real library** (`python3 -m kb place-apply`, read only, no model, nothing sent; `preview-A.txt` `23f4cec3…ba0c5`, 291 lines, the same text again after the review's fix): 20 books would move, 189 are left out (7 with no proposal, 181 unanswered, 1 `none`), digest `9e99671c7c00a491a46613c6f6be4756`, and the digest line matches the text above it. The hash of the root file of each of the 209 books equals the baseline taken after the last plan's Increment D. **That alone compares root files only, so the reviewer's finding 4 was closed in the run:** the hash of every file under the library's bulk root and index root (7,343 files and folders) was taken before and after one more run of `place-apply` on the real library: **identical**. The tests show the same property on the fixture library. The 20 include the Quipu book, which was answered in the earlier plan's Increment C and is last in the list because its id is the largest.

**What the review changed.** The `reviewer` found no blocking finding. **Applied:** whether an answer is the model's pick is now worked out as `to == pick` and no longer read from the stored flag, because a forged event could say `equals_pick: true` for another shelf and the preview would contradict itself (a test that fails before the fix; a break that the test catches; the digest on the real library is unchanged, since there the two agree); the Result says that the workbench files are not part of the increment. **Left for Increment B:** nothing refuses an answered shelf equal to `default` (the tracked schema has no such shelf, so it cannot occur today); the move must refuse it. **Accepted as stated:** the schema's effect on staleness is tested through `state_of` in `test_placereview` and not again here; the no-writes tests hash the library and the index and no other place.

**Departures and limits.** (1) The list's own read of a card that cannot be read (counted as out of date) is shown by a test that replaces the card reader of this module only; with the real card reader it cannot be reached (the check of the proposal reads the same card first). (2) The fixture tests use short fixture schema names; the cleaning of a hostile shelf name or scope is shown only through the render's own cleaning, not by a hostile schema file. (3) `wb run code-work check` is run after the Result's last edit and before the commit. (4) The security review is not asked for here: this increment writes nothing and the move is Increment B, where the owner is asked once.

**Not done:** the commit.
