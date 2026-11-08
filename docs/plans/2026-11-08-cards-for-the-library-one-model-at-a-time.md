# Cards for the library, one model at a time

Status: Proposed
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
- A config setting that lets a model stay loaded between the calls of a queue run, and only of a queue run (the bridge already takes
  it as an option of a call).
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
2. The calls of a queue run pass `--keep-alive` with the value of a setting of the owner's config for queue runs only; the calls of
   `cards` and every other command are exactly as before, whatever the config holds. A wrong value of the setting is refused when
   the queue reads it, before any call.
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

### Increment B — Let a model stay loaded between the calls of a queue run

**Outcome:** a call can be given a `keep_alive` for that call only, and the config has a setting for the value that queue runs give
their calls; no other call changes.
**Dependencies:** A, and the owner's decision there to go on.
**Affected areas:** `engine/kb/models.py` (`run_job` and `_argv` take an optional `keep_alive` of the call; a function that reads and
checks the setting), `engine/tests/test_models.py`, `engine/README.md` where the registry and the config keys are described.
**Steps:**
1. Write the tests first: a call given a `keep_alive` passes `--keep-alive` with that value; a call given none passes exactly the
   arguments it passed before, whatever the config holds, so that `cards` and the other commands are unchanged (tested for each of
   them); a value of the setting outside the bridge's grammar (`0`, `-1`, or one to four digits from 1 to 9 and then `s`, `m` or `h`),
   a number and a value that is not text are refused, naming the rule and not the value; the setting has no default (unset means that
   queue calls pass none).
2. Add the argument to the call and the reading of the setting (`cards_queue_keep_alive`), and describe it in the engine README: it
   overrides the value of the owner's endpoint record for the calls of a queue run only.
**Verification:** `python3 -m unittest engine.tests.test_models engine.tests.test_cardmake` and `wb run code-work check`. The review
of the `reviewer` agent is evaluated and recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#B`.

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
**Dependencies:** B (if the owner went on at A) and C.
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
   pass, the lock, the report, the `keep_alive` of the setting for the calls of the run, and the call of `card-index` at the end of a
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
   time expected from A, the models and the `keep_alive` it will use, and that book text goes to the owner's models. Wait for the word.
2. Run `cards-queue plan`, show the counts, then `cards-queue run`, and read `status` while it goes. Stop and report if fewer than half
   of the quotes verify for a model's first books (the check may be failing for a reason of conversion, not of the model).
3. At its end run `card-index` if the queue did not, and look at the report: the books made, failed and dropped, with the reasons.
4. Write the result in the plan: the time, the calls, the number of changes of model, what failed and why, the comparison with the
   time that A predicts for the one-by-one way, and a recommendation on what the failures call for (a second run for the books that
   failed, the plan for `cards#card-format-resilience`). Record the owner's decision.
**Verification:** the runs read as written; the tests of B, C and D once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-cards-for-the-library-one-model-at-a-time#E`, which holds the
plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After E, rerun
`python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog engine.tests.test_models
engine.tests.test_cardsample engine.tests.test_setup` and `wb run code-work check`, and the tests of the queue; nothing wider is named,
since no other module reads the state of a run or the new option of the registry.

## Risks and sensitive actions

- **No saving.** If loading is a small part of a call, or if the owner's server cannot keep a model loaded for long, the queue buys
  little. Increment A measures this first, with the owner's word, and the plan stops there if the saving is small.
- **State made from model output, on disk.** It holds untrusted text. It is kept in the index root, written and read as the other files
  of the engine are, checked when read, never run, never put in a prompt except as the data sections that prompts already hold, and
  safe to delete. A security review of this new surface is offered to the owner once, in increment D.
- **A long unattended run.** It sends book text to the owner's models for hours. It starts only on the owner's word, can be stopped at
  any time, resumes, and reports. It writes only new generations of cards and the catalog.
- **A model kept loaded takes memory** that other work on the server may want. The setting is the owner's and applies to the calls of
  a queue run only; the owner's endpoint record and the calls of every other command are not changed.
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

## Deferred work

- Running two models at once, or a second server.
- A run started by a timer, which the owner's rule on book text going to models does not allow until the owner sets it.
- Dropping the throwaway card generations that the live runs of earlier plans left in the library.
- The fix for the replies of the card model with lists of the wrong length (`cards#card-format-resilience`), which decides how many
  books fail in a run.

## Result

Empty until work starts.
