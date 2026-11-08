# Cards for the library, one model at a time

Status: In Progress
Created: 2026-11-08
Candidate: cross-field-discovery#neutral-cards-for-the-library
Specs: docs/specs/card.md

## Goal

The owner can start one run that makes a grounded card, with its domain-neutral description, for every book of the library that has no
card, and leave it. The run works through the models one at a time (all the notes on one model, then all the cards on the next, and so
on) instead of going through every model for each book in turn, if a measurement shows that this saves time. It can be stopped and
started again without losing the work done, it takes in no book that arrived after it began, and it reports what failed.

The plan is done when the owner has the measurement, the engine has the run, a live run over the library has made the cards, and the
owner has decided what to do with what the report says.

## Scope

- A read-only measurement of what loading a model costs on the owner's server, with the models of the owner's config, and a decision
  point: if loading is a small part of a call, the plan stops there and the owner decides.
- The owner's own change of the `keep_alive` in the endpoint records of the models (no code, and not done by the engine or by an agent),
  so that a model stays loaded between the calls of a run.
- Making a card in stages whose state can be saved and resumed, with the same result as today.
- A command that plans a run (a snapshot of the books that need a card, sending nothing), runs it, and reports on it.
- A live run over the library, on the owner's word, and the rebuilding of the catalog at its end.

## Non-goals

- A change to what a card holds, to its format or to its checks. A card made by the run is a card as `cards` makes it today, with the
  second round if the owner's config sets it.
- Running two models at once, on one server or on two. One queue runs at a time.
- A run started by capture or by any program of its own: book text goes to models only when the owner starts a run.
- Cards for books that have no conversion beyond what `cards` already does for them (a card from the metadata, with no model call).
- Themes, vectors and the search by meaning (`cross-field-discovery#meaning-search`), and a fix for the replies of the card model that
  have lists of the wrong length (`cards#card-format-resilience`); the run only retries what fails once and reports the rest.
- A cloud model for any call.

## Assumptions and constraints

- A card is made by calls to up to four models in a fixed order: the notes of each piece (task `card-notes`), the card (`card`), the
  checks of its items (`card-check`, ten items to a call), and, if the config sets `card-more`, a second round (`card-more`) and its
  checks. Today each book goes through all of them before the next book starts (`engine/kb/cardmake.py`, `make_model_part`).
- Read from the owner's endpoint file with `wb run ask-ollama check` on 2026-11-08, with no model call: three of the four chat models
  (`gemma4:12b`, `gpt-oss:20b`, `qwen3:14b`) have `keep_alive=0`, so the server unloads them at once after each call, and `phi4` has
  5 minutes. The engine passes no `--keep-alive` today. So the order of the calls cannot save a load for those three models, and the
  saving, if there is one, needs the setting of the second item of the scope. How much a load costs is not known: the live run of the
  previous plan made 13 cards in about 29 minutes of logged time, about 13 seconds a call on average, and a cold load of a model of
  this size is of the order of seconds to tens of seconds. The first increment measures it.
- Memory on the server limits how many models stay loaded; the server unloads a model when another needs the room. A queue that
  keeps one model loaded while it works and moves to the next does not ask for two at once.
- The state of a run holds text made from books and from models (notes, quotes, replies). It is untrusted data, as a refused reply is
  today: it is kept outside the repository and outside the books, in the index root (owner-only), is written with the exclusive
  create and atomic replace that the other files of the engine use, is read back with the same strict checks as a card is, and can be
  deleted at any time without losing a card. The cards are the only durable result.
- A run is a snapshot. The books and versions it will make cards for are fixed when it is planned; a book that arrives later waits
  for the next plan. A conversion that changes while a run is going makes the work on that version stale, and the run drops it and
  says so.
- Caps in force (`wb settings`): one retry of the same failure, and review rounds as the plan sets them. The run retries a failed
  stage of a book once, in a later pass, and then reports it.
- The live run and any labelling need the owner's word. The run sends book text, notes and items only to the models the config names.

## Completion criteria

1. The measurement is in the Result: for each model of the config, the time of a call that has to load the model and of one that does
   not, on prompts of the shapes the stages use, repeated, with the share of a call that loading takes; and the plan's decision at that
   point (go on, or stop for the owner) is recorded.
2. The owner's endpoint records give the models a `keep_alive` of a few minutes or more (the owner's change, which the Result records
   with its value), so that a run finds a model loaded between its calls. The engine passes no `--keep-alive` of its own, and no
   command of the engine changes for it.
3. `make_model_part` gives the same result for the same replies as before the change (the existing tests pass unchanged), and a card
   made in stages can be stopped after any stage, saved, and resumed to the same card.
4. `cards-queue plan` sends nothing, writes the state of the run, and prints the number of books, the number of calls it expects for
   each model and the models in the order of the run; `cards-queue run` makes the cards as new generations, working through the models in
   that order; the number of times the run changes from one model to another does not depend on the number of books; a run that is
   stopped and started again repeats no call whose result was saved; a book that arrived after the plan is not in the run; a version
   whose conversion changed is dropped and reported; a second run at the same time is refused; a stage that fails is retried once in a
   later pass and then reported; and the report names every book as made, failed or dropped, with the reason.
5. A live run over the library has made the cards, the catalog has been rebuilt, and the Result records the time, the number of calls,
   the number of times the models changed, what failed, and the comparison with the time of the one-by-one way that the measurement
   predicts.

## Increments

### Increment A — What loading a model costs

**Outcome:** the owner and the plan know what the queue could save, from a measurement on the owner's server, before anything is built.
**Dependencies:** none.
**Affected areas:** files outside the repository (a script and its log), and the plan's Result. No tracked file other than the plan
changes.
**Steps:**
1. Tell the owner what will be called: the models of the config, with short prompts of the shapes of the stages (a notes call on a
   piece of a real book, a card call, a check call), twice or three times each, about 60 calls in all, and that nothing leaves the
   owner's network. Wait for the owner's word.
2. For each model, in the order of the stages, make the cold state on purpose and check it: call the model once with `--keep-alive 0`,
   so that the server unloads it at once, call the model that comes next in the order of the stages (so that the room is used), wait
   ten seconds, and then make the timed call that must load it. At once after it make the same call again with `--keep-alive` of a few
   minutes (the model has just been loaded and stays), and a third time. Time each call. Repeat three times. The bridge shows no
   state of the server, so the cold state is judged by the times: a "cold" call that is as fast as the warm ones (within a tenth) in
   all three repeats means that the cold state was not made, and the model is recorded as not measured and left out of the decision;
   the owner may also look at what is loaded on the server (`ollama ps` there) at the moments of a repeat, if the owner wishes. A
   script held outside the repository does this through the same bridge command that the engine uses.
3. Work out for each model the time of a call with a load, the time of one without, and the share that the load takes. Estimate what
   the library run would take one by one and through a queue, from the number of calls of the previous plan's run and of the books
   in the library.
4. Write the result in the plan, naming no personal question, path or machine, with a provenance line, and a recommendation: go on if
   the saving is large enough to matter against the work of the other increments (the plan proposes a saving of a quarter of the
   time or more), stop and leave the owner the choice if not. Record the owner's decision.
**Verification:** the runs of step 2 read as written; the Result holds the numbers.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#A`, which holds the
plan's Result.

### Increment B — Dropped: the owner sets the keep-alive in the endpoint records

**Outcome:** none. The measurement of increment A showed that the larger part of the saving comes from the models staying loaded
between calls, and the owner chose to set the `keep_alive` of the models in the endpoint records, which needs no code. So there is
no option of a call, no config key for queue runs and no change to `models.py` in this plan.
**Dependencies:** none.
**Affected areas:** none in the repository. The owner's endpoint file is changed by the owner and is not read or written by an agent.
**Steps:**
1. None. The Result records that the owner made the change and its value.
**Verification:** none.
**Evidence:** none: this increment makes no commit.

### Increment C — Make a card in stages that can be saved and resumed

**Outcome:** the making of a card is a sequence of stages (notes of each piece, the card, the checks, the second round, its checks,
filing) over a state that can be written and read, and `make_model_part` runs the stages one after another and gives the result it
gave before.
**Dependencies:** none (it may be built before B).
**Affected areas:** `engine/kb/cardmake.py` (the stages and the state), a new module for the saved state in `engine/kb/` and its tests,
`engine/tests/test_cardmake.py`, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first. Every existing test of `make_model_part` and `cards` passes unchanged. The state after each stage is
   written and read back to the same values; a state with a missing, extra or wrong key, a value of the wrong type, a file larger than
   the limit, a link or a file that is not the user's own is refused; text in it that looks like a delimiter of a prompt does not
   change what a prompt is made from. A card made with a stop and a restart after each stage in turn is the same card as one made
   straight through, and no call of a stage whose result was saved is repeated.
2. Split `make_model_part` into the stages: the choice of the pieces and the models of each stage (found before any call), one call
   for the notes of a piece, the card call, the pairing and a batch of checks, the second round, its pairing and its checks, and the
   merge that gives the model part. A stage reads the state and returns the changes to it; it makes at most the calls it needs and
   saves nothing itself.
3. Write the state: the identity of the book, the version and the conversion in use, the pieces read, the notes with their quotes and
   whether each is verified, the reply to the card call, the verdicts, the round, the records of the calls made, and the stage reached.
   It is held in a file of the index root, made with the exclusive create and atomic replace, with the limits of size that the other files
   have, and checked when read.
4. Update the card spec and the engine README: what a stage is and that the state is disposable.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models
engine.tests.test_catalog engine.tests.test_cardsample` and `wb run code-work check`; deliberate breaks of the state's checks and of
the resume from a green baseline; the review of the `reviewer` agent is evaluated and recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#C`.

### Increment D — Plan and run a queue over the library

**Outcome:** `cards-queue plan`, `cards-queue run` and `cards-queue status` make the cards of every book that needs one, one model at
a time, and report.
**Dependencies:** C.
**Affected areas:** `engine/kb/` (a module for the queue, `__main__.py` for the commands, `cardmake.py` for the filing), the lock and
the state of a run in the index root, `engine/tests/` (tests of the queue), `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first, with fake models that count their calls and the order of them. `plan` lists the books that are active, have
   a conversion and no card (or all, with `--again`), as the snapshot, makes no call, and prints the counts; a book that arrives after
   it is not in the run; two plans do not share a state. `run` works through the models in the order of the stages, taking from each
   model's queue every item that is waiting for it, and starts a pass again until no queue has an item that can go on or the cap on
   passes is reached; the number of changes from one model to another is the same for 2 books and for 20. A stop and a restart in the
   middle of any stage repeats no saved call and gives the same cards. A failed or refused stage is kept aside as a refused reply is
   today, retried once in the next pass, and then marked failed with its reason; the other books go on. A version whose conversion in
   use is not the one in the state, or whose book is no longer active, is dropped and reported when it comes to filing. A second `run`
   on the same run is refused while one holds the lock, and the lock is released when the run ends or is killed. A card is filed as a
   new generation as soon as its last stage is done, so a stopped run leaves the cards made. `status` reads the state and prints the
   counts for each stage and the failures, with no book text.
2. Write the queue: the grouping of stages by the server and model that the config names for their tasks (the physical pair, so that
   two registry entries that name the same server and model share one queue and one load, while each call keeps the options of its
   own entry; tested with two tasks that name the same pair and with two that name different models), the order of the stages, the
   pass, the lock, the report, and the call of `card-index` at the end of a
   finished run (and a line for the owner when it was not run). No option names a model, a server or an address, as `cards` has
   none.
3. Update the card spec and the engine README: the commands, the snapshot, the state, the lock, and what a run sends where.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models
engine.tests.test_catalog engine.tests.test_cardsample engine.tests.test_setup` and the tests of the queue, and `wb run code-work
check`; deliberate breaks of the grouping, the snapshot, the lock, the resume, the retry and the stale check from a green baseline; the
review of the `reviewer` agent is evaluated and recorded. A security review is offered to the owner for the new state, the lock and
the files made from model output, once.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#D`.

### Increment E — A live run over the library

**Outcome:** the library has its cards, the owner has the numbers, and the owner has decided what the report asks.
**Dependencies:** D, and the owner's word to start the run.
**Affected areas:** the owner's library (new card generations, the catalog), files outside the repository, and the plan's Result. No
tracked file other than the plan changes.
**Steps:**
1. Tell the owner what the run will do: the books it will make cards for and their number, the calls expected for each model, the
   time expected from A, the models and the `keep_alive` of the endpoint records, and that book text goes to the owner's models. Wait
   for the word.
2. Run `cards-queue plan`, show the counts, then `cards-queue run`, and read `status` while it goes. Stop and report if fewer than half
   of the quotes verify for a model's first books (the check may be failing for a reason of conversion, not of the model).
3. At its end run `card-index` if the queue did not, and look at the report: the books made, failed and dropped, with the reasons.
4. Write the result in the plan: the time, the calls, the number of changes of model, what failed and why, the comparison with the
   time that A predicts for the one-by-one way, and a recommendation on what the failures call for (a second run for the books that
   failed, the plan for `cards#card-format-resilience`). Record the owner's decision.
**Verification:** the runs read as written; the tests of C and D once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#E`, which holds the
plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After E, rerun
`python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog engine.tests.test_models
engine.tests.test_cardsample engine.tests.test_setup` and `wb run code-work check`, and the tests of the queue; nothing wider is named,
since no other module reads the state of a run.

## Risks and sensitive actions

- **No saving.** If loading is a small part of a call, or if the owner's server cannot keep a model loaded for long, the queue buys
  little. Increment A measures this first, with the owner's word, and the plan stops there if the saving is small.
- **State made from model output, on disk.** It holds untrusted text. It is kept in the index root, written and read as the other files
  of the engine are, checked when read, never run, never put in a prompt except as the data sections that prompts already hold, and
  safe to delete. A security review of this new surface is offered to the owner once, in increment D.
- **A long unattended run.** It sends book text to the owner's models for hours. It starts only on the owner's word, can be stopped at
  any time, resumes, and reports. It writes only new generations of cards and the catalog.
- **A model kept loaded takes memory** that other work on the server may want. The `keep_alive` is the owner's change to the endpoint
  records, applies to every call of those models, and can be undone by the owner at any time; the engine and agents do not touch the
  endpoint file.
- **A card made from a stale state.** The conversion in use is recorded in the state and compared when the card is filed.
- Nothing is deleted from the library: a run files new generations and the earlier ones are kept.

## Review record

- Reviewer: a second model (gpt-5.6-terra) through the project's review engine, on 2026-11-08, round 1 of 3. Verdict: changes
  needed, three findings, all of major severity.
- Applied (all three): (1) the cold state of the measurement is made on purpose and judged by the times: the model is called once
  with `--keep-alive 0`, the next model of the stage order is called, ten seconds pass, then the timed call; a model whose "cold" call
  is as fast as its warm ones in every repeat is recorded as not measured and left out of the decision; (2) `keep_alive` is no longer an
  option of a registry entry but an argument of a single call plus a config setting (`cards_queue_keep_alive`) that only queue runs
  use, so `cards` and every other command are unchanged, with a test for each; (3) the queue groups stages by the physical server and
  model pair, keeping the options of each call's own entry, with tests for two tasks that name the same pair and for two that do not.
- Rejected: none.
- Left for the owner: whether to ask for round 2 before approving.
- Amendment of 2026-11-08, after increment A: increment B (a keep-alive for queue runs only, which finding 2 above shaped) is dropped,
  because the owner sets the `keep_alive` in the endpoint records instead; the scope, completion criterion 2, the dependencies of D, a
  step of D and E, and two risks were changed to match. The amendment was not reviewed by a second model; it removes work and adds none.

## Deferred work

- Running two models at once, or a second server.
- A run started by a timer, which the owner's rule on book text going to models does not allow until the owner sets it.
- Dropping the throwaway card generations that the live runs of earlier plans left in the library.
- The fix for the replies of the card model with lists of the wrong length (`cards#card-format-resilience`), which decides how many
  books fail in a run.

## Result

### Increment A — What loading a model costs (committed as a4ea80c)

- **What was run** (the owner's word): for each of the four models of the config, in the order of the stages, three repeats of: a tiny
  call with `--keep-alive 0` (the server unloads the model), a tiny call to the next model of the order (the room is used), a wait of
  ten seconds, then the same prompt three times, the first of which has to load the model (`--keep-alive 10m`, so that the next two
  find it loaded). The prompts have the shapes of the stages, made from one real paper: a notes prompt on a piece of 20 KB, a card
  prompt with twelve sections of notes, a check prompt of ten items, and a round prompt. 60 calls, none failed, all to the owner's
  server on the owner's network; the book text and notes went in the clear, as with every card call.
- **Times, in seconds** (the three cold calls; the six calls that found the model loaded, as a median; the load is the difference of the
  medians):

  | stage, model | cold calls | median loaded | load | share of a cold call |
  |---|---|---|---|---|
  | notes, `gemma4:12b` | 8.9, 6.5, 6.4 | 2.2 | 4.3 | 66% |
  | card, `gpt-oss:20b` | 18.6, 14.0, 22.3 | 14.7 | 3.9 | 21% |
  | check, `phi4` | 19.7, 4.7, 4.7 | 1.95 | 2.7 | 58% |
  | round, `qwen3:14b` | 7.0, 7.0, 7.0 | 4.0 | 3.0 | 43% |

  No model was left out as not measured: every cold call was slower than the loaded ones. The load of `gpt-oss` is not measured well,
  because the length of what it writes varies from call to call (loaded calls took 8.5 to 21.5 seconds), so its 3.9 seconds is an
  estimate with a wide margin. The first cold call of `phi4` (19.7 seconds) is the first load of that model in the session; its later
  loads took 4.7 seconds, and I used the later figure.
- **What the library run would take** (assumptions: the 66 books that have no card, 220 notes calls, 66 card calls, about 2.2
  check calls and 0.7 second rounds for each book, with 0.5 further check calls; the three models with `keep_alive=0` load on every
  call, as the endpoint file says, and `phi4` loads once per book after the card call): about 60 minutes one by one; loads take about 27
  of those minutes; through a queue, with each model loaded about once for each stage, about 34 minutes. That is a saving of about 45
  percent, above the quarter that the plan sets.
- **What a simpler change would save.** If the four endpoint records had a `keep_alive` of a few minutes (a change of the owner's
  endpoint file, no code), the notes calls would stay loaded between the pieces of a book, which is 220 of the loads and about 16 of the
  27 minutes; the loads left are the changes from one model to another for each book (about 11 minutes). So the queue's own saving, on top
  of that, is about 11 minutes for this library, and the rest of what it buys is that a run can be stopped and started again, takes a
  snapshot, retries what failed and reports.
- **Limits.** Four models, three repeats, one paper's prompts; the figures for the numbers of calls are estimates from the previous
  run; the server may not hold a model for a few minutes when memory is wanted for another.
- **Recommendation:** see the owner's decision below. The plan's own rule (go on if the saving is a quarter of the time or more) says
  go on. My own reading is that the larger part of the saving is the `keep_alive`, which needs no code, and that the plan is worth
  going on with for the run that can be resumed, but that increment B (a keep-alive for queue runs only) is then not needed if the
  owner sets the endpoint records, and could be dropped by an amendment.
- **The owner's decision** (2026-11-08): option 2, namely that the owner sets the `keep_alive` of the models in the endpoint records
  (no code, and the engine and agents do not touch that file), and that the plan goes on with C, D and E. Increment B is dropped by an
  amendment of the plan, which needs the owner's new approval. The owner set the `keep_alive` of `phi4`, `gemma4:12b`, `gpt-oss:20b`
  and `qwen3:14b` to 10 minutes on 2026-11-08, and `wb run ask-ollama check` (which reads the endpoint file and makes no connection)
  shows `keep_alive=10m` on all four. A short test through the engine, which passes no `--keep-alive`: three one-sentence calls in a
  row took 3.4, 1.0 and 1.1 seconds to `qwen3:14b`, and 3.5, 0.5 and 0.4 seconds to `gemma4:12b`, so the models stay loaded between
  calls.
- Provenance: measured on 2026-11-08 at commit `211014d` on the owner's server with the local models `gemma4:12b`, `gpt-oss:20b`,
  `phi4:latest` and `qwen3:14b` through the owner's bridge; the log is held outside the repository.

### Increment C — Make a card in stages that can be saved and resumed (committed as 87fd8a2)

- **A deviation from the steps as approved, which the owner accepted on 2026-11-08 on my recommendation.** The plan's steps 2 and 3 say to split `make_model_part` into
  stage functions that read a state and return changes to it, with a state that holds the pieces, the notes, the reply, the verdicts,
  the round and the stage reached. I did not do that. I built a *journal* of the calls instead: `make_model_part` is unchanged in its
  logic, each successful call (its job, model entry, checked answer and record) is added to a journal, a call that is already in the
  journal is not made again (its saved answer is checked again as a reply is), and a call for a model entry that the caller is not
  serving raises `Pause` before it is made. Everything else (the pieces, the quotes, the pairing, the grounding, the merge) is
  recomputed from the journal and the book each time. The reasons: a card made again from the journal is the same card by construction,
  with the existing tests of `make_model_part` unchanged; the change is much smaller than a rewrite into stage functions; and it gives
  increment D exactly what it needs, a stop at a model boundary and a resume. What it gives up is the state that holds the stage
  reached and the intermediate results, which are recomputed. Criterion 3 as worded is met (the same result for the same replies, the
  existing tests unchanged, a card stopped after any call and made again is the same card and repeats no saved call). If the owner
  wants the stage functions as written, that is an amendment and more work.
- Built: `engine/kb/cardstate.py` (the journal, and `write`, `read` and `remove` of its file `card-runs/<run>/<book>-<version>.json` in
  the index root: the index root opened without following a link, folders 700 and checked, the file 600 under a temporary name and
  put in place with one rename, refused if a link, a pipe, another user's, readable by others, over 8 MiB or not exactly the shape;
  `remove` also deletes what a crash left); in `cardmake.py` `Pause`, `JournalFault`, `new_journal`, the header (`_expected`: the title,
  the kind, the pieces and the pieces read, the model entry and the server and model of each kind of work, the prompt version of each
  job, a digest of the outline and of the text of the pieces read) and `make_model_part`'s arguments `journal`, `allow` and
  `identity` (the book, the version and the conversion in use, required with a journal); the engine README and the card spec.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_card
  engine.tests.test_cardstate engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample engine.tests.test_setup`
  gave 578 tests, OK, the existing tests of `cardmake` and `cards` unchanged; `wb run code-work check` found no problems. The tests were
  written first and failed for the right reason. A card stopped after each of its 8 boundaries (0 to 7 calls) and made again is the
  same card as one made straight through, with the number of calls that remain. Deliberate breaks, each from a green baseline: 35
  conditions, 31 caught and 4 survived, which are equivalent edits (a defensive copy of an answer, a size check that a later check
  repeats, and two header constants that both sides of the comparison use). Not run: any live run (increment E), the full engine suite.
- Review: the `reviewer` agent, round 1, two blocking findings and four others. Applied: a fault of the journal in the second round
  (a saved call that is not the call being made, an answer that is not valid, a failure to save) was taken for a failed round and a
  different card would have been filed; it is now a `JournalFault` that the round does not catch, with tests; the header bound the
  journal to neither the book, the version, the conversion, the text nor the models behind the entries, although the spec and the README
  said it did; it now does, with `identity` required and a digest of the text and the models in the header, with tests; calls in a
  journal that the card does not make are stale; `remove` deletes what a crash left; the README says plainly that the journal is not
  signed and that the verdicts, the support lists and the records are taken as saved. Recorded for increment D: `cardmake.run` has an
  `except Exception` that would report a `Pause` as a failure, so the queue must call `make_model_part` itself or catch `Pause`
  first; the queue is also where the journal's trust statement and the lock belong in the security review that is offered to the owner.
- Next: increment D.

### Increment D — Plan and run a queue over the library (built; not committed)

- Built: `engine/kb/cardqueue.py` and the command `cards-queue plan | run | status` (no option names a model, a server, an address or a
  path). `plan` makes a snapshot of the active books whose version is converted and has no card (with `--again` those with one too; with
  `--book` only the books named, each once), writes it as a run (`card-runs/<run>/manifest.json`) and sends nothing; a book that
  arrives later is not in it. `run` works in passes (at most 1 to 10, default 3); a pass visits the models in the order of the stages, one
  visit for each run of stages on one server and model (the grouping is by the pair the config names, not by the entry, and each call keeps
  its own entry's options), and at each visit takes every waiting book as far as the models served go, through `make_model_part` with
  the book's journal and `allow` (increment C). A card is filed as a new generation as soon as its last call is made. A call that fails,
  an answer that is refused (kept aside as `cards` keeps it) and a card that cannot be filed are tried again in the next pass and then
  reported as failed; a book that failed in a pass is not tried again in the same pass. A book is dropped and reported if it is no longer
  active, if its conversion is not the one the plan saw (or has gone, or is now below the cutoff), or if its saved state is stale or wrong.
  A card filed after the plan (a stop between filing and saving the manifest, or a `cards` run) marks the book done and no second card is
  made. One run works at a time, whatever its name (`card-runs/queue.lock`, released when the holder ends or is killed). The catalog is
  rebuilt if a card was made now, and the report says in `catalog_note` when it was not and the run has cards from before. `status`
  prints the counts and how far the waiting books have got, with no book text, and one unreadable journal does not hide the rest. In
  `cardmake.py`, `make_for_version` was split into `plan_version` and `file_model_card` (all its tests unchanged) and `keep_aside` made
  public; in `cardstate.py` the manifest, the lock and `Stale`; the engine README and the card spec.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_card
  engine.tests.test_cardstate engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample
  engine.tests.test_setup` gave 637 tests, OK, the existing tests unchanged; `wb run code-work check` found no problems. The tests were
  written first and failed for the right reason. With a fake bridge that answers by job, the number of changes from one model to another
  is the same for 2 books and for 6 (two: the notes, then the cards, then the checks), a run stopped after any number of calls and run
  again repeats none and gives the same cards, and a run of three books with one that always fails makes two and reports the third as
  failed with its reason. Deliberate breaks, each from a green baseline: 34 conditions of the queue and its state, all caught in the end;
  the first round of breaks showed 11 gaps in the tests (the grouping was only tested through the physical changes of model, which are
  the same with and without grouping; the turns, the retry on a failed call, a stale journal being dropped, the cap on passes, the
  lock and the manifest checks had no test of their own), which were closed with tests. Not run: any live run with real models
  (increment E), the full engine suite.
- Review: the `reviewer` agent, round 1, one blocking finding and nine others. Applied: an error while filing a card (a card that is too
  large, no free generation, a failed write) escaped `_serve` and ended the run, and a rerun reached the same book and ended the same
  way; it is now a failure of that book, tried once more and reported, with a test for the card of a model and one for a card from
  the metadata; two runs of different names could work on the same book at the same time and file two cards, so the lock is now of the
  queue and not of the run, with tests; a book that had a conversion at the plan and now gets a metadata card was filed and reported as
  done, it is now dropped; the README and the spec now say that a changed setting drops a book's saved state; `plan` counts the calls
  that can be counted for the books that need the models only, names each book once, classifies "has a card" without matching text,
  and loads each conversion once; the reasons in the manifest are cut at 200 characters and a run holds at most 10,000 books, so the
  manifest cannot reach its size limit; `status` survives a journal it cannot read; the report says when the catalog was not rebuilt.
  Not changed, with reasons: the second round is not tried again if it fails (as with `cards`; the README says so).
- **Security review** (the owner asked for it on 2026-11-08; the `security-reviewer` agent, on a copy of the repository with a fake
  launcher and a temporary index root, 29 tool runs, nothing of the owner's config or library read). No Critical or High finding.
  - *Medium: one unreadable journal stops the whole queue.* A journal that was corrupt, in an old format, a directory, a pipe, or too
    large made `run` raise out of `_serve`, so every book after it stayed waiting and every rerun failed the same way. Fixed: the
    journal is read inside the handling of the book, a journal that cannot be read drops that book (and is left in place for the owner),
    `_get` checks that a file is a regular file before it opens it for reading and closes its descriptor on every path, and tests cover
    a corrupt file, a directory and a pipe in place of a journal.
  - *Low: exceptions that are not a `KbError` escaped `_serve`.* Fixed: `run` catches any exception per book, fails that book (tried
    once more, then reported) and shows only the kind of error, not its text, which may hold words of a book or a model; a failure to
    keep the manifest (`ManifestFault`) still stops the run.
  - *Low: a manifest or a journal that can be written can be bent.* Accepted, and said in the README: whoever can write the private
    folder can make the program send the text of any existing book to the owner's models when the owner runs, forge what a check said
    for an item (the cited note must still share words with it and its quote must occur in the book), put any text that a reply could
    carry into a card, forge the record of which model made it, and lower `had` to cause a second card. They cannot write or delete
    anything outside `card-runs` and new card generations, cannot make a card that `card.make` refuses, and cannot name another
    book or version through a journal. The folder is private to the user, so the writer already has the owner's identity; if the
    library were more protected than the index root, this would be an escalation.
  - *Informational, taken:* a book that gains a newer version after the plan is dropped; `run` exits with 1 when a book failed; a run
    name is checked against an existing manifest; the unexpected-error text is the kind only. *Not taken:* printing the books before a
    run; the cost of rewriting the manifest at each status change (at most 10,000 items, about 2.5 MB); the message for a lock that is
    a pipe, which fails closed.
  - Disclosure: the reviewer ran three old timing scripts that were already in the scratch folder (benchmarks of the PDF scan from
    earlier in the session) before noticing they were not its own; they touch nothing of the library.
  - Limits: macOS only; files of another user and concurrent processes beyond a held lock were not tested; no real model server.
- Verification after the review: the same seven test modules plus `test_cardqueue` gave 644 tests, OK; `wb run code-work check` found
  no problems; the deliberate breaks of the queue and its state are 41 conditions, all caught except two equivalent edits (a redundant
  check in `plan`, and a directory read as a journal that the read error refuses anyway).
- Next: the owner's word to commit increment D; then increment E, the live run over the library.
