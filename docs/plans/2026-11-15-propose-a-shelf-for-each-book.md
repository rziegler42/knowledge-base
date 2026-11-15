# Propose a shelf for each book, and record the owner's confirmation

Status: Proposed
Created: 2026-11-15
Candidate: none (the shelves, the fetch engine and the crawler are outside every roadmap, which say so; creating a roadmap for them is the owner's change of direction; this plan follows the two checks of the shelf matcher on the library's books, `2026-11-14-check-the-matcher-on-the-librarys-books` and `2026-11-15-check-the-matcher-on-difficult-books`, and the owner's reading of them)
Specs: docs/specs/shelf.md, docs/specs/card.md, docs/specs/book.md

## Goal

The matcher (the embedding model `qwen3-embedding:4b`, the five nearest of the 4,534 home shelves (the topic and custom shelves among the 4,816 of the schema, whose vectors are all kept), then the choice of `gemma4:12b` with the prompt `place-1`) has been measured on 300 papers and then on the library's own books: on 68 books marked by the owner blind it picked the owner's best or an acceptable shelf for 59 (86.8 percent, rough interval 76 to 94 percent). The owner's reading was that **the choice is good enough to propose a shelf for a book, which the owner confirms; it files nothing; a bare `none` means "unsure, ask the owner"**. Today the matcher exists only as scripts outside the repository, and every book of the library is on the shelf `default`. When this plan is done:

- the engine can build the vectors of the schema's shelves and keep them as a derived file (`shelf-vectors`);
- the engine can propose a home shelf for each book it holds that is still on `default`, with the five shelves offered, the model's choice and its one-line reason, and everything needed to repeat it (`place-propose`); a proposal is a line in the book's own event log and changes nothing else;
- the owner can go through the proposals one book at a time in their own terminal and confirm, change, say `none`, or skip, and each answer is a line in the book's event log (`place-review`);
- the library's books have proposals, the owner has confirmed a first batch, and the Result gives the counts (how often the owner accepted the pick, chose another of the five, said none, skipped), with the plain statement that these counts are **not** a measure of accuracy, because the pick is shown;
- a book's `shelf` field is **unchanged**: moving books onto shelves is a later plan.

## Scope

- **Shelf vectors** (`engine/kb/shelfvectors.py`, command `shelf-vectors`): the vector of each shelf of the tracked schema file `engine/kb/data/shelf-schema.json`, made by the embedding entry that a new task `place-embed` names, kept in one SQLite file in the index root, derived and replaceable, with the schema's hash, the model and the dimension recorded.
- **The proposal** (`engine/kb/placement.py`, command `place-propose`): the text of a book from its newest card by the text rule `text-1` of the earlier plans, its embedding, its five nearest home shelves by cosine (the pure matcher `engine/kb/shelfmatch.py`), the choice by the chat entry that a new task `place` names with the prompt `place-1` and the strict reader of the earlier plans, and one event `placement_proposed` in the book's event log.
- **The confirmation** (`engine/kb/placereview.py`, command `place-review`): a terminal dialogue, one book at a time, and one event `placement_confirmed` in the book's event log for each answer; and a read-only listing of the counts (`--list`).
- **The books** are those the library already holds that are still on the shelf `default` (all of them today), or the books the owner names.
- The two tasks are added to the engine's list of tasks (`engine/kb/models.py`, `docs/specs/models.md`); the owner names the entries in their own config, which the engine never writes.
- The commands are recorded where the project documents commands (the README) and the spec says what is now built.

## Non-goals

- **Moving a book onto a shelf.** No `set_shelf`, no change of a book's `shelf` field or of a card, no `schema-adopt`, no `reshelve-approve` (the spec's governed actions, a later plan). Confirmations are records, not filing.
- **Placement at capture.** Capture, convert and card are not changed; a new book gets a proposal when the owner runs the command.
- **Placement by OpenAlex topic.** The spec places a paper that carries an OpenAlex primary topic by that topic, without the matcher; the library's cards carry none, so every book goes through the matcher here.
- Counts per shelf in a library report, scouts, priorities, the holding shelf, the tie margin and any change of the schema or of the matcher (another model, prompt or number of candidates is a new plan with a new sample and its own measurement).
- Tuning on the owner's confirmations: they are not blind and are not a figure of accuracy.

## Assumptions and constraints

**The owner's choices** (asked on 2026-11-15, each of the three recommendations taken): confirming **only records** (a book's `shelf` stays `default`); the plan covers **the books already held**, not capture; the owner confirms **one book at a time in the terminal**.

**My calls, not the owner's** (the owner may change any before approving):
- *Where things are kept.* A proposal and a confirmation are lines of the book's own append-only event log (`store.append_event`, event names `placement_proposed` and `placement_confirmed`; `docs/specs/book.md` lists `reshelved` among the events and says each book has such a log). The owner's confirmations are the library's own data and so sit with the book, not in the derived index. The shelf vectors are derived from the schema and the model, so they sit in the index root and can be thrown away.
- *The measured configuration is fixed in the code.* The embedding model `qwen3-embedding:4b` with no document prefix, the chat model `gemma4:12b`, the prompt version `place-1`, five candidates, the text rule `text-1` (title, the card's summary and topics, cut to 1,500 characters, control and hidden characters removed). The commands refuse to run when the entry that a task names uses another model or a prefix, and say why; another model is a new measurement and a new plan.
- *The model's pick is shown* when the owner confirms, with its reason: the owner confirms a proposal. The earlier checks were blind because they measured; this is not a measurement. The event records whether the answer equals the pick so that the counts can be read for what they are.
- *`place-review` asks only a person.* It refuses to run unless its input is a terminal, and takes no answer from an argument or a file, so that an agent cannot fill in the owner's confirmations.
- *Every text shown to the owner is cleaned of control characters* (book titles and summaries are untrusted; the reason and the shelf descriptions are model output or third-party text).
- *Idempotence.* A book that already has a proposal for the same card generation, text hash, schema hash and shelf-vectors file is skipped unless `--again` is given; a confirmation is asked again only with `--again`, and the latest event of a book counts.
- *Command names* are mine (`shelf-vectors`, `place-propose`, `place-review`).

**What leaves the machine, and when.** (1) `shelf-vectors` sends the texts of the 4,816 shelves of the schema (public OpenAlex descriptions and the Library of Congress outline names) to the embedding entry on the owner's model server `ned`, over plain unauthenticated http, in the clear, as the trial did. (2) `place-propose` sends, for each book, its text (the library's own derived text, made from a public page or paper that the owner chose to keep) to the embedding entry, and then a prompt that holds that text between two marker lines and five shelves, to the chat entry, on the same server in the same way; the addresses and book ids are not sent. Each send is preceded by `--check`, which prints what would be sent (the number of texts and prompts, their bytes, and one whole prompt) and sends nothing, and happens only on the owner's word "run it".

**Constraints.** Tests first for every unit of code; deliberate breaks of each new module (compile-checked); the `reviewer` agent's reading of each increment; a recount of counts by a snippet that does not use the module's own code; the commit only on the owner's word, the push only on the owner's word after the shared-branch checks. No change to the capture, convert, card, search or theme code; the one shared file touched is `engine/kb/models.py` (two task names), and its tests are rerun.

## Completion criteria

1. `shelf-vectors` has built the vectors of all 4,816 shelves of the schema into the index root; the file records the schema's hash, the entry and model as reported, the dimension and the build date; a sample of 20 of its vectors agrees with the vectors the earlier trial saved (cosine at least 0.9999), as a one-off check recorded in the Result.
2. `place-propose` has written one `placement_proposed` event for each book that was on `default` (or the Result names each book left out and why), each holding the five shelves, the choice or `none` and its reason or the malformed reply, and the provenance (the card generation and text hash, the schema hash, the shelf-vectors file's identity, the models as reported, the prompt version, the time); counts of picks, `none`, malformed and errors are recounted by a snippet that reads the event logs directly.
3. `place-review` has been run by the owner in their own terminal; each answer is a `placement_confirmed` event; the Result gives the counts and says that they are not a measure of accuracy.
4. No book's `shelf` field, card or payload changed: the hash of each book's root file is the same before and after, and the only change in a book's folder is lines added to its event log.
5. The new modules' tests and breaks, the tests of the files touched, and `wb run code-work check` pass; the commands and the spec are updated; nothing else in the repository changes.
6. The owner has read the result and says what comes next.

## Increments

### Increment A — The shelf vectors (sends the schema's shelf texts)

**Outcome:** `python3 -m kb shelf-vectors` builds, and `shelfvectors.py` reads, the vectors of every shelf of the schema, as a derived file in the index root.
**Dependencies:** none (the plan's approval).
**Affected areas:** `engine/kb/shelfvectors.py` (new), `engine/kb/models.py` (the task `place-embed`), `engine/kb/__main__.py` (the command), `engine/tests/test_shelfvectors.py` (new), `engine/tests/test_models.py`, `docs/specs/models.md` (the task list); the plan's Result.
**Steps:**
1. Read `engine/kb/vectors.py` (the pattern to follow: a meta table, a build in a folder of its own renamed into place under the writers' lock, reuse of rows whose text and model are unchanged, a reader that refuses a file made for another model, dimension or prefix), the task lists of `engine/kb/models.py`, and the earlier trial's `run_embed.py` (the rule that turns a shelf into a text, which is the measured rule).
2. Write the tests first and see them fail, with a fake embedder: the shelf text rule on a small fixture schema, worked by hand; the meta; a build makes one row for each shelf; a second build with nothing changed makes no call; a changed schema, model or prefix replaces the rows; the vectors are checked when made and when read (length, finite, not all zeros) and read as unit vectors; a file made for another model, dimension, prefix or schema is refused by the reader; a build killed half way leaves the old file; the guard that refuses an entry that is not the measured model or has a prefix; `--check` sends nothing; the new task is accepted by the registry only when it names an entry of the kind embedding and may be left unset (the command then says so and does nothing); the file and its folder are the owner's alone (mode 600 and 700).
3. Write the module and the command. `--check` prints the number of texts and their bytes and one example; `--again` rebuilds.
4. Deliberate breaks of the module and their restoring (each broken text compiled first).
5. `--check` on the real schema; with the owner's "run it" build the real file; compare 20 shelves' vectors with the earlier trial's saved ones (a one-off check outside the repository, recorded in the Result with the hash of the file used).
6. The `reviewer` agent reads the module, its tests and the Result.
**Verification:** from the repository root, `python3 -W error::ResourceWarning -m unittest engine.tests.test_shelfvectors engine.tests.test_models engine.tests.test_shelfmatch engine.tests.test_shelfschema`; the breaks; `wb run code-work check`. The other engine tests are not rerun: the only shared file touched is `models.py` and its own tests are run.
**Evidence:** the one local commit holding the code, its tests and the plan's Result and Review record for A, with the trailer `Plan: 2026-11-15-propose-a-shelf-for-each-book#A`.

### Increment B — The proposal (sends book texts and prompts)

**Outcome:** `python3 -m kb place-propose` writes a `placement_proposed` event for each book it is asked to place; nothing else changes.
**Dependencies:** A.
**Affected areas:** `engine/kb/placement.py` (new), `engine/kb/models.py` (the task `place`, which may be left unset), `engine/kb/__main__.py`, `engine/tests/test_placement.py` (new), `engine/tests/test_models.py`, `docs/specs/models.md`; the plan's Result.
**Steps:**
1. Read the earlier trial's `run_choice.py` (the prompt builder `build_prompt`, the order of the shelves, the marker handling, `parse_answer`, the limits) and `books_sample.card_text` (the text rule): they are ported, not rewritten, and the tests pin their output.
2. Write the tests first and see them fail, with a fake embedder and a fake chat model on a small fixture library built with the engine's own store: the text of a book from its newest current card (a card with no summary, or a text under 100 characters, is refused with the reason); the five nearest home shelves by cosine; the prompt for a fixed example is **byte for byte the earlier `place-1` prompt** (the expected text is in the test); the book's text sits between the marker lines and a marker line inside the text is removed; the shelves are in alphabetical order of their names, not in the order of closeness; the strict reader (a number 1 to 5 or `none`, a colon, a reason of at most 200 characters; anything else is recorded as malformed with the reply cut to 300 characters, never guessed at); one call for each book; five errors in a row stop the run and the rest is not tried; the event holds the five shelves with their scores, the answer, the provenance and not the book's text; a book that has a current proposal for the same card generation, text hash, schema hash and vectors file is skipped without a call unless `--again`; only books on `default` unless named; the command refuses when the vectors file is missing, stale or made for another model, when no entry is set for `place` or it is not the measured chat model, and says why; `--check` prints the counts, the bytes and one whole prompt and sends nothing, writes nothing; a book's root file, card and payload are byte for byte unchanged after a run and only its event log gains lines.
3. Write the module and the command.
4. Deliberate breaks and their restoring.
5. With the owner's "run it", after `--check` on three books the owner names or approves: run on those three; read the events (not the book texts) and report them to the owner.
6. The `reviewer` agent reads the module, its tests and the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_placement engine.tests.test_models engine.tests.test_shelfvectors engine.tests.test_store engine.tests.test_card`; the breaks; a snippet that does not use the module reads the three books' event logs and their root files; `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-propose-a-shelf-for-each-book#B`.

### Increment C — The confirmation at the terminal

**Outcome:** `python3 -m kb place-review` takes the owner through the proposals one book at a time and records each answer as a `placement_confirmed` event; `--list` prints the counts and sends nothing.
**Dependencies:** B.
**Affected areas:** `engine/kb/placereview.py` (new), `engine/kb/__main__.py`, `engine/tests/test_placereview.py` (new); the plan's Result.
**Steps:**
1. Write the tests first and see them fail, driving the dialogue with an input function and a captured output on a fixture library: what is shown for a book (its title, address and the card's summary; the five shelves numbered in alphabetical order, each with its path and scope sentence; the model's pick marked, with its reason, or the word that it said `none` or answered badly); the answers (`1` to `5` chooses that shelf, `ok` accepts the model's pick, `none` says no shelf fits, `skip <words>` leaves it with the owner's words, `quit` stops without recording the current book; anything else is asked again and never guessed at); each answer writes one event with the owner's answer as given, the shelf's slug or `none` or `skipped`, whether it equals the model's pick, the proposal it answers (by its time) and the card generation it was about; a proposal whose card changed since is shown as stale and cannot be confirmed (it is proposed again first); a book already confirmed is not shown again unless `--again`; **every text shown is cleaned of control characters and escape sequences** (a title or a reason that holds them is shown without them, tested); **the command refuses to run when its input is not a terminal**, and takes no answer from an argument or a file; a book's root file, card and payload are unchanged; `--list` prints the counts (proposed, confirmed with the pick accepted, with another shelf, `none`, skipped, stale), reads only, and needs no terminal.
2. Write the module and the command.
3. Deliberate breaks and their restoring.
4. The owner tries the command on one book in their terminal (the agent cannot run it for them) and says whether the dialogue is what they want; changes to the wording are made here.
5. **A security review of the code of B and C together, which the owner asked for on 2026-11-15** (the project's `security-review` skill, by the `security-reviewer` agent, which works on a copy of the tree with fake programs and hostile inputs and changes nothing under review). Its scope is the two boundaries named in the Risks: untrusted book text and model output reaching a prompt, the event log and the owner's terminal; and the terminal check on the owner's confirmations, with its stated limit. It reports findings by severity with what was checked and what was only read. **Each finding that is applied is fixed with a regression test that fails before the fix and passes after, and gets an independent second look**, as the skill requires; a fix to code of B is made here, in C's commit, and the Result of B says so. Findings that are not applied are recorded with the reason.
6. The `reviewer` agent reads the module, its tests, the fixes and the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_placereview engine.tests.test_placement engine.tests.test_store`; the breaks; the security review's checks rerun after its fixes (each regression test fails on the unfixed code and passes on the fixed); `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-propose-a-shelf-for-each-book#C`.

### Increment D — Proposals for the library's books, and the owner's first confirmations

**Outcome:** every book still on `default` has a proposal, and the owner has confirmed a first batch.
**Dependencies:** C and the owner's word "run it".
**Affected areas:** the library's books' event logs (lines added); the plan's Result. No code changes.
**Steps:**
1. Hash the root file of every book (the record of what must stay unchanged).
2. `place-propose --check`: the number of books, of texts and prompts, the bytes in all and one whole prompt; the owner says "run it".
3. `place-propose` for all of them. Report the counts: picks, `none`, malformed, errors, books left out and why.
4. The owner runs `place-review` in their own terminal and confirms as many as they choose (the plan asks for at least 20; the owner may stop at any point and go on later). The agent does not run it.
5. Read the event logs with a snippet that does not use the engine's modules and report the counts: confirmed with the pick accepted, with another of the five, `none`, skipped, not yet confirmed, and the books where the model said `none` or answered badly. Say plainly that the pick was shown, so these are not a figure of accuracy.
6. Hash the root files again: unchanged. The `reviewer` agent reads the Result.
**Verification:** the recount by a snippet; the hashes of the books' root files before and after; `wb run code-work check`. No tests are rerun: no code changes.
**Evidence:** the one local commit holding the plan's Result and Review record for D, with the trailer `Plan: 2026-11-15-propose-a-shelf-for-each-book#D`; the event logs are in the library, not in the repository.

### Increment E — The commands and the spec

**Outcome:** the three commands are recorded where the project documents commands, and the shelf spec says what is now built.
**Dependencies:** D.
**Affected areas:** `README.md` (the commands), `docs/specs/shelf.md` (marks on the placement lines that are now built, and the two commands), `docs/specs/models.md` if A and B did not finish it; the plan's Result.
**Steps:**
1. Add the three commands to the README's list, in the form the others have, with the line that `place-review` needs a terminal.
2. In the spec, say what is true now (the placement is built as a proposal and a recorded confirmation; filing and reshelving are not), without changing any statement of direction: a change to what the spec says about direction is the owner's.
3. `wb run code-work check` and the document checks that the project has.
**Verification:** `wb run code-work check`; a read of each changed line against the code it describes.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-propose-a-shelf-for-each-book#E`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the new modules' tests, and those of the files they touch (`test_models`, `test_shelfmatch`, `test_store`), are rerun; the root files of all books are hashed once more and compared with the hashes of Increment D; the counts of the event logs are recounted; the shelf-vectors file's hash is compared with the one the Result names; and `wb run code-work check` is run. The engine's other tests are not rerun: nothing else in the engine changes, and the one shared file touched is `models.py`.

## Risks and sensitive actions

- **Text leaves the machine in the clear.** The schema's shelf texts (public) in A, and each book's text and a prompt in B and D, go to the model server `ned` over plain unauthenticated http. The book texts are the library's own derived text made from public pages and papers, sent the same way as when the cards were made; each send is preceded by a `--check` and waits for the owner's "run it".
- **Untrusted input reaches a prompt, and model output reaches the log and the terminal.** The book's text is quoted as data between marker lines with an instruction to ignore instructions in it (the earlier injection check steered 0 of 5 cases, an easy test); the answer is read by a strict reader and never guessed at; what is shown to the owner is cleaned of control characters. These are surfaces the project's rules say to name: **the owner asked for a security review of the code of B and C together** (2026-11-15); it is Step 5 of Increment C, runs once C's code and tests exist, and happens before C is committed. Its limits are stated beforehand: a pseudo-terminal can satisfy the terminal check, so that check stops mistakes and not a determined agent (as the spec says of `ask` prompts), and a model cannot be made injection-proof, so the review tries harder cases than the earlier 0-of-5 check but proves nothing absolute. Increment A is not in its scope: its input is public shelf text and its output is a derived file that the reader refuses when it is foreign or stale.
- **The owner's confirmations are the owner's alone.** The command refuses a non-terminal input, so an agent cannot confirm for the owner; an agent can still write to the event logs by other means, as it can write anywhere in the library.
- **Confirmation is biased by the pick being shown**, and the counts will read high. They are recorded as such and not used to set any bar.
- **The record is append-only.** A mistaken answer is corrected by a later one (`--again`), not removed; events are written to the book folders of the library, which the library's backup is meant to cover (`library.md`); I have not checked that a backup is running.
- **Models are fixed to the measured ones.** If the owner changes the entries, the commands refuse until a new plan measures the new ones.
- **A shelf can be described badly.** An OpenAlex topic's description can disagree with its name (for example "Thoreau and American Literature" is described as privacy and security); the matcher reads the description, and the owner's confirmation is where such a case shows.
- **No change** to a book's shelf, card or payload, the schema, the spec's direction or a roadmap, and **no push** without the owner's word.

## Review record

### Increment A

The `reviewer` agent, one exchange of the cap of 6, read only: it read the module, its tests, the breaks, `vectors.py`, `shelfmatch.py`, the task code of `models.py`, the command and the `models.md` paragraph, and ran nothing. **No blocking finding, no concrete security risk.** **Applied:** the check did not honour `--again` and so understated what `--again` would send (it does now, with a test that the command hands the flag on); the reader and a build did not compare the model the bridge reported with the measured one, so a foreign meta could be re-stamped and kept (both now refuse it, with tests); an unused import was removed; the Result's account of the first break run was wrong by one (corrected: two removed, one replaced, 63) and did not give the hashes of the trial's saved vectors (added). **Recorded as limits, not changed:** the unit-vector scaling that the plan's test list names is done by the matcher, not the reader; only the file's mode is tested; a vector changed in place is not detected, as for the card vectors; the lock and the folder-identity check have no test; and the note for B that the guard looks at the document prefix only. It could not run the tests or the build and did not read the trial's files; those are read here from the commands as run.

### The plan (before approval)

Reviewed with Codex through the project's review engine (the bridge `ask-codex`, the model it reported was `gpt-5.6-terra`, profile `standard`; the server's location class read `unknown`; the plan holds no secret and the repository is public), **one round of the bound of three**, which converged with the verdict "no meaningful changes". **One minor finding, applied in a different form:** it said the Goal's "4,534 home shelves" disagreed with the 4,816 shelves of the schema used elsewhere in the plan. Both numbers are right (the matcher ranks the 4,534 topic and custom shelves; the vector file keeps all 4,816 so that counts can roll up), so the number was not changed; the Goal's sentence now says so. Nothing is left open for the owner from the review. The files of the review are in `.workbench/workbench/review-engine/plan-5a1b3ff243e27a1b/`.

## Deferred work

- Moving books onto shelves: `schema-adopt` and `reshelve-approve` (the spec's governed actions), using the confirmed placements; keeping slugs stable across versions of the schema file.
- Placement at capture, so each new book gets a proposal; placement of a paper by its OpenAlex primary topic; counts per shelf in the library report; the holding shelf and the tie margin.
- What to do with the books the model leaves with `none`: a proposal for a new custom shelf (the spec's shelf proposals).
- A new measurement if the embedding or chat model, the prompt or the number of candidates changes.

## Result

### Increment A — the shelf vectors (done on 2026-11-15; not yet committed)

**What was made.** `engine/kb/shelfvectors.py` (`b6c6b4e1…62f1fa`; new): the shelf text rule (name, a full stop, a space, the scope sentence, in the order of the schema file, the rule the matcher was measured with), `build` (keeps a vector whose text is unchanged, sends the rest in chunks that fit in memory, writes a new file in a folder of its own and renames it into place under the catalog lock), `load` (returns the vectors only for a file made for the entry that is set, from the schema file as it is now, with every shelf once and no other), `describe` (what `--check` prints) and the guard that refuses any entry that is not `qwen3-embedding:4b` with no document prefix, and any model the bridge reports as another. `engine/kb/models.py`: the task `place-embed` in `EMBED_TASKS` (one line and a comment). `engine/kb/__main__.py`: the command `shelf-vectors [--check] [--again]`. `engine/tests/test_shelfvectors.py` (`234ccc1b…a0ad7e`; new, 52 tests) and `engine/tests/test_models.py` (the test that pinned the embedding tasks to exactly `("card-embed",)` now pins both, and one test of the new task is added: a deliberate change of an existing test, as the plan's change to `models.py` requires). `docs/specs/models.md`: a paragraph on `place-embed`. The breaks are held outside the repository: `breaks_shelfvectors.py` (`a1d15a97…5ea9ba`).

**Order of work, as run.** The tests were written first and the first run failed because the module did not exist. Then the module: of the 35 tests of the first full run one failed (my own arithmetic in a test: 17 shelves less one plus one is 16 kept, not 15), and `test_models` failed on the old pin of the task list (above). After the command was added, two command-line tests expected the wrong exit code (the command line returns 2 for a refusal); the tests were corrected, not the code. **The first run of the breaks: 65 written, all applied, 12 missed.** Two of those were equivalent breaks and were removed (the configured model equals the reported model in every case the guard allows; writing the file over the old one before renaming it ends in the same file) and one, a reversed dictionary (the same mapping), was replaced by a break that gives every shelf the vector of one shelf; that leaves 63. The other nine showed gaps in the tests: refusals that happened for another reason than the one under test (the shape of the file, the format of the meta, a row with a bad slug or hash, a bad vector in the file), a vector matched to the wrong text, the size of the texts in the check, and the vectors returned for the wrong shelf; tests were added or tightened to assert the reason of each refusal and the vector of each shelf. **Run before the review: 63 of 63 breaks caught**, each broken text compiled first, the file restored byte for byte. After the review (below) four breaks were added for the changes it caused and two broken texts were adapted to the changed code; **the final run: 67 of 67 caught**, the file restored byte for byte. The lock is not covered by a test (it is the same call as in `vectors.py`), and neither is the check that the folder of a build was not replaced while it was built; both are as in the card vectors.

**Verification, run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_shelfvectors engine.tests.test_models engine.tests.test_shelfmatch engine.tests.test_shelfschema`: **348 tests, all pass** (345 before the review's changes). `wb run code-work check`: no problems. The other engine tests were not rerun (the plan's reason: the only shared file touched is `models.py`, whose own tests were).

**The real build** (on the owner's word "run it", after `--check` printed the numbers; the owner set `tasks.place-embed` to `embed-qwen` in their own config first): `python3 -m kb shelf-vectors` sent **4,816 shelf texts, 1,162,537 bytes**, to the embedding entry on the owner's model server `ned` over plain unauthenticated http, in the clear (the texts are public OpenAlex topic descriptions and Library of Congress subclass names), and wrote `shelf-vectors.sqlite` in the index root: mode 600, 59,473,920 bytes, `sha256` `53017fe5…cef56`, model reported `qwen3-embedding:4b`, dimension 2560, 4,816 rows, built from the schema file with hash `f7d9cf00…dfae3` (the same schema hash that the two books-check reports record). **The one-off check against the earlier trial** (a separate snippet that does not use the module, over **all 4,816 shelves**, not the 20 the plan names): the same set of shelves; the cosine of each new vector with the trial's saved vector has a minimum of 1.000000 and none is below 0.9999; the module's `load` reads the file and the pure matcher builds its space from it (4,534 home shelves). The trial's files used for the comparison: `shelves.f32` `1123a5f3…dfc41c` and `vectors-meta.json` `1edb47b1…c4764a` (of the plan `2026-11-14-measure-the-shelf-matcher`).

**Departures and limits, said plainly.** The plan's test list says the vectors are "read as unit vectors"; `load` returns the stored numbers and the matcher's `Space` makes them unit vectors, so nothing in A does or tests the scaling. The plan says the file and its folder are mode 600 and 700: the test checks the file (600); the build folder comes from `tempfile.mkdtemp` (700 by construction), is deleted after the build, and is not asserted; the index root is not touched by this code. The vector blob of a row is not bound to its text or model beyond the text's hash, so a vector changed in place in a file that is otherwise intact is not detected (the file is mode 600 and the card vectors are the same). The lock, the check that the folder of a build was not replaced while it was built, the library's marker check and the order of the rename are not covered by a test. **For Increment B:** the guard looks at `document_prefix` only; book texts must be sent as `kind="document"` with this entry.

**Review (below):** the changes it caused are in the figures above.

**Not done:** the commit.
