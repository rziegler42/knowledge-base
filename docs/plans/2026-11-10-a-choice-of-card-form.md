# A choice of card form

Status: Proposed
Created: 2026-11-10
Candidate: none (a correction that follows from a finding: the Result of Increment B of the plan `2026-11-10-add-sources-from-the-fields-that-ideas-come-from` found that the engine can make only the sentence form of the card, which the owner decided on 2026-11-09 not to use for the library)
Specs: docs/specs/card.md

## Goal

The engine can make a card in either of two forms, the owner chooses the form for each run, and the earlier form is the default, as the
owner decided on 2026-11-09. The earlier form asks the card model for the summary and the neutral parts as plain text and marks only the
topics, key ideas, caveats and limits; the sentence form asks for them as sentences with support and drops a sentence that no verified
note supports. When the plan is done, the 30 books added by the plan `2026-11-10-add-sources-from-the-fields-that-ideas-come-from`
(27 with a card in the sentence form, 3 with none) have a card in the earlier form as their newest generation, the Result compares the
two forms on those books, and the older 79 cards and the sentence-form cards are unchanged.

## Scope

- The earlier card call (its prompt, its shape, its parsing and its grounding) comes back from the history of the repository
  (`engine/kb/cardmake.py` and `engine/kb/schemas/card.json` as they were before commit `2c082cd`) as a form of the card call, beside the
  sentence form, which stays as it is.
- A choice of the form in the commands `cards` and `cards-queue plan`, recorded in the run and in each journal, with the earlier form as
  the default.
- One live run that makes the cards of the 30 books again in the earlier form, on the owner's word.

## Non-goals

- Any change to the sentence form, the checks, the second round, the marks, the catalog, the vectors or the searches.
- Making the 79 older cards again: they are already in the earlier form.
- Removing the sentence form, or a decision about which form is better: the plan reports the numbers and the owner decides.
- The other ways on named in the Result of `2026-11-09-ground-the-summary-and-neutral-fields` (keeping a neutral part as a marked
  inference, or the check by clause, which the owner dropped).
- Carding other books, or the card quality: no accuracy is measured here.

## Assumptions and constraints

- A card of either form is valid and is read as before (`card.py` reads a card with no sentence record as the earlier form). The
  catalog takes the newest generation of each version, so a card made now in the earlier form becomes the one the catalog holds; the
  sentence-form card stays as the earlier generation and is never overwritten or deleted.
- The earlier call is restored from history and adapted to the code that exists now (the queue's journal, the second round, the
  settings of the pieces). The tests of the earlier form are restored from the same history and adapted; the tests of the sentence form
  stay as they are and must stay green.
- The form is a value from a fixed set (`earlier` or `sentences`); no option takes a path, an address or a model name.
- The journal header says what a card is made with (the prompt version of each job); a journal made for one form must be refused by the
  other, so a resumed run cannot mix forms.
- The earlier run of this kind (66 books, 495 calls, about 5 seconds a call) suggests about 8 calls a card and, for 30 books, 30
  minutes to an hour on the owner's server; the real figure is measured and recorded.
- Book text, notes and items go only to the models the config names, on the owner's server, over plain HTTP; each run says so and waits
  for the owner's word.

## Completion criteria

1. The card call has two forms, `earlier` and `sentences`; a card made with a form is as valid as any card; the sentence form's
   behaviour and tests are unchanged and pass.
2. `cards` and `cards-queue plan` take `--form`, default `earlier`; the run and each journal record the form; a journal of one form is
   refused by the other; the report names the form.
3. The 30 books have a card in the earlier form as their newest generation, or the Result gives the reason for each that has none; the
   sentence-form cards are still generation 1; the 80 books that existed before the batch are unchanged.
4. The Result compares the two forms on the books that have both (cards marked partial, parts that are empty, the searched fields that
   hold text, the items marked stated and inferred) and records the owner's decision on which generation stays the newest.
5. `docs/specs/card.md` and `engine/README.md` say that the earlier form is the default and the sentence form an option, and
   `wb run code-work check` finds no problems.

## Increments

### Increment A — The earlier call as a form of the card call

**Outcome:** `cardmake.make_model_part` makes the model part of a card in the form it is told, `earlier` or `sentences`, with the
prompt, shape, parsing and grounding of that form; the sentence form is unchanged.
**Dependencies:** none.
**Affected areas:** `engine/kb/cardmake.py`, `engine/kb/schemas/card.json` (a shape for each form), `engine/kb/card.py` only if the
record of an earlier-form card needs it, `engine/tests/test_cardmake.py`.
**Steps:**
1. Read `git show 2c082cd^:engine/kb/cardmake.py` and the schema and tests of the same commit, and the diff of `2c082cd` and `503d46c`,
   and write down what separates the two forms: the prompt, the shape of the reply, the parsing, the grounding of the summary and the
   neutral parts, the prompt version. If the earlier form cannot be restored beside the sentence form without a change to how the checks
   or the second round work, stop and report instead of changing them.
2. Write the tests first: the tests of the earlier form restored from `2c082cd^` and adapted (a reply in the earlier shape makes a card
   whose summary and neutral parts are the plain text of the reply, marked as before for topics, key ideas, caveats and limits; a reply in
   the wrong shape is refused); a test that an unknown form is refused before any call; the tests of the sentence form unchanged. See the
   new tests fail for the right reason.
3. Add the form to the code: a parameter `form` (`earlier` default, `sentences`), a prompt version for each form, and the header of the
   journal recording the form so that a journal of one form is refused by the other.
4. Deliberate breaks, each from green: the form ignored, the sentence prompt used for the earlier form (and the reverse), the journal
   header without the form, an unknown form accepted, the plain neutral text of the earlier form dropped.
5. The independent `reviewer` agent.
6. **Checkpoint, after the review and before the commit.** This increment brings back the parsing of a model's reply (the earlier shape
   and its grounding) and changes the header of the journal that a resumed card is checked against. Name this to the owner and ask
   once whether to run a security review with the installed module on this surface; record the answer in the Result. A review runs
   only if the owner asks.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_card
engine.tests.test_cardstate engine.tests.test_cardqueue` and `wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-a-choice-of-card-form#A`.

### Increment B — Choosing the form in the commands and the queue

**Outcome:** `python3 -m kb cards --form earlier|sentences` and `python3 -m kb cards-queue plan --form earlier|sentences` choose the
form (default `earlier`); the run's manifest and its journals record it, `cards-queue run` and `status` keep it, and the report names it.
**Dependencies:** A.
**Affected areas:** `engine/kb/__main__.py`, `engine/kb/cardqueue.py`, `engine/kb/cardmake.py` (the call of the queue), `engine/tests/
test_cardqueue.py`, `engine/tests/test_cardmake.py`, `engine/README.md`, `docs/specs/card.md`.
**Steps:**
1. Write the tests first: the option is parsed and refused for a value outside the set; a plan made with a form records it in its
   manifest; a run uses it for every call; a resumed run keeps it and a journal of the other form is refused; the report and `status`
   name it; the default is `earlier`; a run made before this change (no form in its manifest) is read as `sentences`, which is what it
   was made with.
2. Add the option and thread the form through the plan, the run and the journal.
3. Update `engine/README.md` and the card spec: the earlier form is the default and the sentence form an option.
4. Deliberate breaks, each from green: the option ignored, the default made `sentences`, a resumed run taking the default instead of the
   recorded form, the manifest without the form, a journal of the other form accepted.
5. The independent `reviewer` agent.
6. **No second question about the same surface.** The parsing of a model's reply and the journal were asked about in Increment A. This
   increment adds an option whose value comes from a fixed set (no path, no address, no model name) and records it in the run. If
   building it changes how input reaches a privileged use (a path, a command, shared state), stop and ask the owner again.
**Verification:** the same test modules as A, with `engine.tests.test_catalog` (the catalog reads the newest card of either form), and
`wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — Card the 30 books in the earlier form

**Outcome:** the 30 books have a card in the earlier form as their newest generation (or a recorded reason for each that has none), and
the Result compares the two forms.
**Dependencies:** B.
**Affected areas:** the cards of the 30 books (a new generation each) and the card runs in the index root; this plan's Result. No
tracked code.
**Steps:**
1. Run `python3 -m kb cards-queue plan --form earlier --again --book ID ...` with the 30 ids; it makes no call. Show the owner the
   number of books, the form, the models, the calls that can be counted and the estimate, say that the text of these pages goes to the
   models on `ned`, and wait for a yes.
2. Run `python3 -m kb cards-queue run RUN`. Record the time, the cards made and, for a book that fails twice, its reason; a new attempt
   or a fix is the owner's decision.
3. Compare, on the books that have both forms: cards marked partial, parts that are empty, the searched fields (problem, approach,
   provides) that hold text, the items marked stated and inferred. Check that the sentence-form cards are still generation 1, that
   the 80 older books are unchanged (the snapshot of the earlier plan), and read two of the new cards with `card-show`.
4. Put the numbers to the owner with a recommendation, and record the owner's decision on which generation stays the newest.
**Verification:** `cards-queue status RUN`; the counts of the comparison; the snapshot comparison; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the card test modules once
and `wb run code-work check`. A wider run is not named. What could break outside what is tested is the default of `cards` and
`cards-queue`, which changes from the sentence form (the only form until now) to the earlier form; the journals of runs made before are
read as the sentence form, and the catalog, the vectors and the searches read a card of either form.

## Risks and sensitive actions

- **A default that changes.** Until now every new card was made in the sentence form; after this plan it is the earlier form unless
  `--form sentences` is given. That is the owner's decision of 2026-11-09, and the plan records it in the README and the spec.
- **Restoring code from history.** The earlier call was replaced in one commit and its tests were rewritten; restoring it beside the
  sentence form can bring back an old defect or clash with the queue's journal. Increment A stops and reports if it needs a change to
  the checks or the second round.
- **Model output is parsed.** A restored path parses a model's reply (as the old path did) and the journal header changes; Increment A
  asks the owner once about a security review, before it is committed.
- **Text sent out.** Book text goes to the owner's models in the clear on the owner's server, said before the run.
- **Two cards for a book.** The catalog holds the newest; the older generation is kept. Nothing is deleted.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, one finding (major), applied:

- **R1-F1, applied.** The plan asked the owner about a security review in Increment B, but the restored parsing of a model's reply and
  the change to the journal header are made in Increment A, so A could have been committed first without the question. The checkpoint
  is now step 6 of Increment A, after the independent review and before the commit, and covers the parsing and the journal; Increment
  B carries a note that it adds only an option with a value from a fixed set and asks again only if that changes how input reaches a
  privileged use.

The reviewer found the plan consistent with the card spec and with the cited batch of 30 books. A second round has not been asked for.

## Deferred work

- A decision on which form the owner wants in general, from more than 30 books and from a labelled sample of accuracy (this plan
  reports counts of partial cards and empty parts, not accuracy).
- The plan `2026-11-10-add-sources-from-the-fields-that-ideas-come-from` goes on with its Increment C (the catalog, the vectors and the
  twelve searches) once the cards of its books are in the form the owner wants.

## Result

### Increment A — The earlier call as a form of the card call

- **Done.** `engine/kb/cardmake.py` has `FORMS = ("earlier", "sentences")`, `EARLIER_JOB` (prompt version `v4`, schema
  `card-earlier.json`), `check_form`, `card_job`, the earlier prompt (`_card_prompt_earlier`) and a `form` parameter in `card_prompt`,
  `new_journal`, `make_model_part`, `make_for_version`, `run` and `thin_reason`; `pairs`, `unpaired` and `ground` read a reply in the earlier
  shape by the key `neutral_limits_support`. `engine/kb/schemas/card-earlier.json` is the schema as it was before `2c082cd`. The
  earlier-form tests are restored from `2c082cd^` into `engine/tests/test_cardmake_earlier.py` (125 tests), with new tests for the choice
  of form (12) and one end-to-end class. Provenance: the earlier prompt text and the schema were compared with `git show 2c082cd^` and are
  identical.
- **What separates the two forms** (step 1): the prompt; the shape of the reply (earlier: plain `summary` and `neutral_*` plus
  `neutral_limits_support`; sentences: `sentence_fields`, `sentences`, `sentences_support`); the grounding (earlier: the three lists and
  the limit are checked, the summary and the other neutral parts are the plain text; sentences: each sentence needs a verified note);
  the empty-part reason (sentences only); the prompt version (`v4` and `v6`). The checks and the second round did not need a change, so
  the stop condition did not apply.
- **Deviations.** (1) The function default is `form="sentences"` here; the default `earlier` is made in Increment B with the option, so
  that no commit changes what the engine does before the choice exists. (2) The earlier form uses today's check call (`card-check` v2),
  not the v1 it was made with; the restored test that named v1 now names v2. (3) The new tests are in a new file, not in
  `test_cardmake.py`, so that the sentence-form tests stay as they are. (4) The journal header has no `form` key: `cardstate` accepts
  exactly its eleven keys, so a header with a twelfth cannot be saved. The prompt version of the card call (`v4` or `v6`) is in the header
  and makes a journal of one form stale for the other; a journal made before this change is read as the sentence form. This was found by
  the reviewer (a journal of the earlier form could not be written to its file) and fixed with a test that writes and reads a journal of
  each form.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_cardmake_earlier`, `test_cardmake`, `test_card`,
  `test_cardstate`, `test_cardqueue`, `test_cardsample`, `test_catalog`: 691 tests, OK; `wb run code-work check`: no problems. The
  restored tests were seen to fail first (112 errors, 8 failures, for the missing `form` and `EARLIER_JOB`). Twenty deliberate breaks, each
  from green, were each caught; one (the second round forgetting the form) was first missed and a test was added; two breaks about a `form`
  key in the header no longer apply and the key's return is caught by the new round-trip test. No call to a model server was made.
- **Review.** Independent `reviewer`, one exchange: one blocking finding (the header key above), applied; two not-blocking notes
  (the new test file; the changes to `pairs`, `unpaired`, `ground` and `thin_reason` are the earlier form's own, additive and keyed on the
  reply's shape, and the sentence path is unchanged), accepted. It could not read git history; the comparison with history was made by me.
- **Security review checkpoint.** Asked once, about the parsing of a model's reply and the journal header. The owner said no security
  review; none was run. The reviewer found no new exposure by reading (replies still pass the shape check and `parse_support`; the form is
  checked against a fixed set before any call).

### Increment B — Choosing the form in the commands and the queue

- **Done.** `cards` and `cards-queue plan` take `--form earlier|sentences` (argparse `choices`, default `earlier` from
  `cardmake.DEFAULT_FORM`). `cardqueue.plan` checks the form first and writes it in the manifest; `_serve` passes `manifest.form` to
  `new_journal` and `make_model_part`, so every call of a run, and of a run taken up again, is in the recorded form; `plan`, `run`,
  `status` and each `cards` report name the form. `cardstate` has `FORMS`, `Manifest.form` and an optional `form` key (a manifest with no
  key is read as `sentences`; a value outside the two, or a non-string, is refused in writing and in reading; unknown keys are still
  refused). `engine/README.md` (the form, both commands, the manifest) and `docs/specs/card.md` (one `[agreed]` bullet, following the
  owner's decision of 2026-11-09 that the earlier form is the default) are updated.
- **Deviations.** (1) `engine/kb/cardstate.py` and `engine/tests/test_cardstate.py` are changed though B's Affected areas do not list
  them: the manifest is validated there and takes a fixed set of keys. The owner agreed to this on 2026-11-10 when asked. (2) Completion
  criterion 2 asks that each journal record the form; a journal records it through the prompt version of the card call (`v4` or `v6`),
  not a key (Result of A), and the manifest records it as a key. (3) The library functions (`cardmake.run`, `make_for_version`,
  `make_model_part`, `cardqueue.plan`, `Manifest`) default to `sentences`; only the commands default to `earlier`. Reason: a manifest
  with no form must read as `sentences`, and no existing caller changes behaviour. The reviewer calls this a latent trap for a script that
  calls the functions directly; the only callers in the repository pass the form. (4) Five command tests in `test_cardmake.CommandTest`
  now pass `--form sentences`, because their fake launcher and fixtures are of the sentence form and the command default moved; the
  default itself is tested in `test_cardqueue.CommandTest`.
- **Known and left.** Every `cards` report names the form, including a card built from the metadata with no model call and a skipped
  book; for those the field is the form asked for, not one the card was made in (cosmetic, reported by the reviewer).
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_cardmake_earlier`, `test_cardmake`, `test_card`,
  `test_cardstate`, `test_cardqueue`, `test_cardsample`, `test_catalog`: 708 tests, OK; `wb run code-work check`: no problems. The new
  tests were seen to fail first. Eighteen deliberate breaks, each from green (the option ignored by each command, the default made
  `sentences`, a resumed run taking the default for the journal and for the calls, the manifest without the form, the form unchecked in
  writing and in reading, any extra key allowed, the plan not checking the form, a journal of the other form accepted, the form missing
  from `run`, `status`, `plan` and the `cards` report, the option taking any value) were each caught; one (the plan not checking the form)
  was first missed because the manifest write refuses a bad form too, and the test now requires the plain refusal. No call was made to a
  model server.
- **Review.** Independent `reviewer`, one exchange, no blocking finding. Not blocking, accepted: the library-default trap (3 above) and the
  metadata label (known and left); the others confirmed the code and the documents. It could not run anything or read the diff.
- **No second security question.** The option's value is one of two words checked by argparse, `check_form` and the manifest in writing
  and in reading, and never reaches a path, command, address or model name; the reviewer found no concrete exposure. As the plan says,
  the owner is not asked again.

### Increment C — Card the 30 books in the earlier form

- **Done.** Run `20261110t152341z-f03ec5` (`cards-queue plan --form earlier --again`, 30 books; the plan made no call). The owner said yes
  to the run after being told what is sent: the text of the 30 Wikipedia pages in pieces, and the notes, outlines and short-page text
  for the card and the checks, to the models the config names on the owner's server, over plain HTTP. It ran from 2026-11-10T15:25:31Z to
  15:41:26Z (about 16 minutes; the plan expected 30 to 60) in 2 passes and made 201 calls on the 29 cards filed (66 notes, 29 card, 77
  check, 29 second round). Result: 29 done, 1 failed. The queue rebuilt the catalog (110 books, 109 cards, no failures); vectors were not
  made.
- **The failed book.** Newsvendor model: after two tries the card model gave `topics` and `topics_support` of different lengths and the
  answer was refused and kept aside. Its only card is still the sentence-form one (generation 1). No new attempt was made; the owner
  decides whether to try again.
- **Where the cards are.** 26 books have the sentence-form card as generation 1 and the earlier-form card as generation 2; the 3 books
  that had no card (Sequential analysis, Queueing theory, Stigmergy) have the earlier-form card as generation 1; Newsvendor model has the
  sentence-form card only. All 27 sentence-form cards are still generation 1. The 80 books that existed before the batch are unchanged
  (snapshot compare: 80 before, 110 now, 0 changed, 30 new).
- **Comparison** (counts of what each form produced, not accuracy; `card.read` over the 30 books; provenance: the scratchpad script
  `compare_forms.py` run at commit `fa2ea76`, 2026-11-10):

  | | sentence form | earlier form |
  |---|---|---|
  | cards | 27 | 29 |
  | marked partial | 24 | 7 |
  | cards with an empty part | 24 | 5 |
  | empty parts in all | 56 | 5 |
  | searched fields (problem, approach, provides) holding text | 51 of 81 | 87 of 87 |
  | items marked stated / inferred | 321 / 85 | 314 / 141 |
  | key ideas per card, average | 5.0 | 4.6 |

  On the 26 books that have both: partial 23 against 6, searched fields with text 49 of 78 against 78 of 78, stated / inferred 313 / 85
  against 293 / 117. The two earlier-form cards with an empty limit are Sequential probability ratio test and Linear programming; the
  other five partial earlier-form cards are partial for other reasons that the cards state. The earlier form marks more items inferred, which
  is its cost; no accuracy was measured (see Deferred work). Two cards were read with `card-show` (Annealing, Thompson sampling) and read
  sensibly.
- **The owner's decision (2026-11-10).** The owner took the recommendation: the earlier form stays the newest generation. Nothing was
  deleted; the sentence-form generation can still be read with `card-show --generation 1`. No change was made to any card after the run.
- **Verification as run.** `cards-queue status` before and the run's report after (counts above); the snapshot comparison (0 of the 80
  old books changed); the comparison counts above; the card test modules once more at the end of the plan (708 tests, OK, no code changed
  since Increment B); `wb run code-work check`: no problems.
- **Left for the owner.** Whether to try Newsvendor model again; the plan `2026-11-10-add-sources-from-the-fields-that-ideas-come-from`
  can go on with its Increment C (card-index, card-vectors, the twelve searches) now that the cards are in the form wanted; a labelled
  sample of accuracy for the two forms (Deferred work); push of the local commits.
