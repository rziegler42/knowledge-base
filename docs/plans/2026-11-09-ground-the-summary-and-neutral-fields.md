# Ground the summary and the neutral fields of a card

Status: Completed
Created: 2026-11-09
Candidate: cards#card-ground-the-rest
Specs: docs/specs/card.md

## Goal

The summary and the five neutral fields of a card (problem, approach, needs, provides, limits) are made of sentences that each cite the
notes that state them, that a second model checks against those notes, and that carry the mark `stated` or `inferred`, as the topics
and key ideas of a card already do. A sentence with no support is dropped and not padded. The cards made this way are compared, on a
blind sample labelled as before, with the cards that the library has now, and the owner decides whether the new form replaces the old
and whether the library is carded again.

The plan is done when the engine makes the new form, a run on books of the library has been labelled and compared with the cards made
now, and the owner has decided.

## Scope

- A card call that writes the summary and the neutral fields as sentences, each with the notes that state it, in place of five and one
  free strings; the engine joins the sentences that it keeps into the fields, so the card's model part is as it is now.
- Pairing and checking of those sentences with the same second-model check as the topics and key ideas, without the requirement that
  a sentence share a word with its note (a neutral description is written without the words of the field, so it shares few).
- The grounding record and its display for these sentences, the thin rule for a field that loses all its sentences, and the effect on
  the catalog's text, the sample tool and the accuracy count.
- A live run on a few books of the library, a blind sample labelled by a strong model, the owner's calibration labels, the comparison,
  and the owner's decision.
- **A revision of the card spec,** in these statements and no others: in "What a card holds", the statement that "adjacent topics,
  'useful for', the summary and the other neutral fields carry no mark" and that "a limit that is dropped leaves its field empty"
  (the marks and the empty field then apply to the summary and to each neutral field too); in "Non-goals", the statement of what the
  engine does check (it then names the sentences of the summary and the neutral fields); and the statement of what a search result
  counts (it then counts the marks of those sentences). The owner's approval of this plan is the owner's word for this revision,
  which changes what the spec says about the card and is the change-direction checkpoint. No text of the spec is changed before
  the approval, and the revision is made in increments A, B and C and shown in the commit.

## Non-goals

- Splitting a sentence into clauses and checking each (`cards#card-clause-check`). The roadmap lists that candidate as a dependency
  of this one because these fields are made of clauses; this plan grounds each sentence as a whole and records, in its Result, what
  the sentence-level check misses.
- The useful-for lines and the adjacent topics, which state no claim of the book.
- Search by meaning (`cross-field-discovery#meaning-search`), carding the whole library again (a queue run the owner starts after this
  plan, with `cards-queue`), and a fix for the card model's wrong-length lists (`cards#card-format-resilience`).
- A cloud model as a card writer or checker. A cloud model labels the sample and does nothing else.
- Rewriting existing cards: a new card is a new generation.

## Assumptions and constraints

- **The evidence for the plan** (held outside the repository; a blind sample of 120 items from the 65 cards that the library queue made
  on 2026-11-08 and 2026-11-09, labelled by three Opus-class labellers who saw the item and up to five passages of the book, and checked
  by the owner on 15 items): 61 percent of the items were supported, 8 inference and 32 unsupported. By field, supported: topics 92
  percent (24 items), key ideas 85 (26), summary 53 (15), neutral problem 58 (12), approach 62 (8), provides 50 (8), needs 30 (10),
  limits 0 (6), caveats 0 (11). The five neutral fields together: 19 of 44 supported (43 percent), 5 inference, 20 unsupported. The
  owner and the labellers agreed on 10 of 14 items (71 percent, one skipped), and in all four differences the labellers were more
  lenient than the owner, so these figures are a ceiling.
- A neutral description is written without the words of the field, so the passages that share the most words with it may not be the ones
  that support it; some of the unsupported items may have support elsewhere in the book. The earlier second look against whole books
  found all five of its unsupported items unsupported, but they were caveats and limits. This plan does not rely on the neutral items
  being supported elsewhere: a sentence is kept only if a note that the card writer cites supports it, whatever the book holds.
- **The dependency on `cards#card-clause-check`.** The roadmap names it as a dependency of this candidate because these fields are made
  of clauses; the roadmap's rules call dependencies hints. This plan goes on without it, by the owner's choice on my recommendation,
  for three reasons: the check of whole sentences is the same kind of check that already lifted the topics and key ideas to 85 and
  92 percent; a sentence-level check is a smaller change than a clause splitter and a sentence is the unit that the evidence
  labelled; and the Result of this plan will say how much a sentence-level check lets through, which is the evidence for deciding
  whether the clause check is still needed. The owner's approval of this plan is the owner's acknowledgement of that choice. A
  sentence with a true part and an unsupported part can pass the check of the whole sentence; the labelled comparison measures it.
- **The spec and the direction already given.** The card spec now says that the summary and the other neutral fields carry no mark and
  that only topics, key ideas, caveats and the limit are checked. The grounding plan and the roadmap candidate `cards#card-grounding`
  left grounding of the summary and the other neutral fields in scope "if the labelled sample shows it pays", and the evidence above
  is that sample; so this plan carries out a direction the roadmap gave and does not reverse one. It still changes what the spec
  says, in the statements named in the scope below.
- The existing machinery is reused: the notes with verified quotes, the pairing of an item with a cited verified note, the check by the
  model set for `card-check` (ten pairs to a call), the marks, the second round, the journal of calls and the queue.
- Pairing by shared words is a guard against a model that cites one note for every item. For sentences it is replaced by the check
  alone; the bake-off of the check model (the grounding plan) found that it answers `no` to unrelated pairs, and this plan tests that on
  the new pairs before it is trusted.
- Time and calls are spent on accuracy, as the owner has said; a card is never padded to reach a size. The live run, the labelling by a
  cloud model and the owner's labels each need the owner's word.

## Completion criteria

1. The card call asks for the summary and the neutral fields as sentences with support, and the engine builds the fields from the
   sentences that a check confirmed, so that the model part of a card has the same keys and shapes as now. A sentence that cites no
   verified note, whose pair the check does not confirm, or that is a repeat of another sentence of its field, is dropped and counted.
2. The grounding record of a card names, for each of the summary and the five neutral fields, the sentences it kept, each with its
   mark, the notes that support it and the quote of the first; a record that does not fit the fields it describes is refused when the
   card is read.
3. A field that loses all its sentences is empty and the card says so in its reasons; a card whose summary is empty is partial.
4. The display of a card shows the mark of each sentence, the search result counts the marks of these sentences with the others, and
   the sample tool and the accuracy count work on the new form (a sentence is an item, as the sentences of a summary are today).
5. The cards of books named by the owner exist in the form now in use and in the new form, a blind sample with the same number of items
   from each form of the same books has been labelled, the owner has labelled a calibration subset of at least ten items and the
   agreement is computed before the cloud labels are used, and the numbers are recorded, for the summary and the neutral fields,
   form against form.
6. The Result records the numbers, the limits and the owner's decision.

## Increments

### Increment A — The grounding record and the display for sentences

**Outcome:** a card of the new form can be validated, filed, read, shown and searched, with the sentences of the summary and the neutral
fields marked and each backed by a note.
**Dependencies:** none.
**Affected areas:** `engine/kb/card.py` (the grounding record: an optional entry for the summary and the five neutral fields, its
checks against the model part, the display, `grounding_counts`; the neutral fields and the summary may be empty in a card of the new
form), `engine/kb/catalog.py` (the card's text and the counts), `engine/kb/cardsample.py` (the items of the new form), the tests of
these, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first. A grounding record may carry, for the summary and for each neutral field, a list of sentences, each with its
   text, mark, notes and quote; the sentences joined with a single space are exactly the field of the model part; a record with a
   field whose sentences do not join to the text, an unknown field, a mark that is not `stated` or `inferred`, a `stated` sentence with
   no notes or quote, an `inferred` sentence with notes, more than the limit of sentences, a sentence of the wrong length or with a
   control character is refused when the card is made and when it is read. A card of the earlier form (no such entry) is read, shown,
   searched and sampled as before.
2. Write the display (`[stated]` or `[inferred]` after each sentence, with the quote under the same rules as the other items), the
   counts in a result of the search, and the sample items (a sentence is an item, whichever form the card has).
3. Update the engine README, and the statements of the card spec that the scope names (those about marks, about the empty field and
   about what a search result counts), to say what the code does.
**Verification:** `python3 -m unittest engine.tests.test_card engine.tests.test_catalog engine.tests.test_cardsample` and `wb run
code-work check`; deliberate breaks of the new checks from a green baseline; the review of the `reviewer` agent is evaluated and
recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-ground-the-summary-and-neutral-fields#A`.

### Increment B — The card call, the pairing and the check for sentences

**Outcome:** `make_model_part` makes cards of the new form: the model writes the sentences with their support, the engine pairs and
checks them, keeps the confirmed ones and builds the fields.
**Dependencies:** A.
**Affected areas:** `engine/kb/cardmake.py` (the card prompt and its shape, the pairing of sentences, the use of `check_job`, `ground`,
the thin reasons, the report fields), `engine/kb/schemas/card.json`, `engine/kb/card.py` (the shape of the model part), the tests of
these, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first, with fake models. The card call's reply has three lists of the same length for the sentences (the field each
   belongs to, the sentence, the notes that state it); a reply with lists of different lengths, a field name that is not one of the six,
   more than the ceiling of sentences for a field, a sentence of the wrong length or one that cites `inferred` or `none` for a field
   that may not be inferred is refused as an answer that is kept aside. A sentence is paired with the first verified note it cites
   (the order the model wrote them in), without the requirement of a shared word, and put to the check with the other pairs, ten to a
   call; only a confirmed sentence is kept, in the order the model wrote it, and a sentence that repeats another of its field (the
   repeat limit of the second round) is dropped. A field is the join of its kept sentences; a field with none is empty and the reasons
   say which. The topics, key ideas and caveats are made as before, and a card from the model that sets no `card-more` is unchanged in
   them. The journal replays the new call as it replays the others.
2. Write the prompt: the sentences are the claims of the book in words of no field for the neutral ones, each citing the one or two notes
   that state it, never a note that is only loosely related, and never a mention of the notes in the text. Version the prompt and the
   job.
3. Count in the report the sentences asked for, kept and dropped for each reason, and the checks.
4. Update the engine README, and the statement of the card spec that the scope names about what the engine checks. Make deliberate
   breaks of the pairing, the check, the building of the fields and the thin rules from a green baseline.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate
engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample` and `wb run code-work
check`; the review of the `reviewer` agent is evaluated and recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-ground-the-summary-and-neutral-fields#B`.

### Increment C — Check a sentence against every note it cites, and ask for more sentences

**Outcome:** a sentence that the notes it cites state together is confirmed, and each neutral part is asked for up to three sentences,
so that one refusal does not empty it. The first live run (see the Result) found that half of the neutral parts ended empty: the model
wrote one sentence for each, the check refused it, and a sentence was checked against the first note it cited only, though the book
states some of them in a second note.
**Dependencies:** B.
**Affected areas:** `engine/kb/cardmake.py` (the pairing of a sentence, the check prompt, `ground`, the card prompt, `SENTENCE_ASKED`, the
version of the card job), its tests and the fake reply of the queue tests, `docs/specs/card.md` (the clause on pairing), `engine/README.md`.
The record of a card needs no change: the notes of a stated entry are already a list.
**Steps:**
1. Write the tests first. A sentence is paired with up to two verified notes that it cites, in the order written; the check prompt shows
   each note with its point and quote under the sentence; one `supports` verdict for the item confirms it; the entry that is kept lists
   the notes that were shown and has the quote of the first. A sentence that cites one verified note is paired with it as before, and
   one that cites none has no pair. The pairing of a topic, key idea or caveat is unchanged (one note, a shared word). The check job
   has one verdict for each item whatever the number of notes. The card is asked for up to three sentences for each neutral part
   (the checked caps and the ceilings stay, so the arithmetic of the records still holds), each saying one thing, preferring two or
   three short sentences to one, and citing the notes that state it together with the one that states most first. The card job is
   version `v6`, so a journal made with `v5` is stale.
2. Make the change, update the clause of the card spec on pairing and the engine README, and make deliberate breaks of the new pairing,
   the check prompt and the entry from a green baseline.
3. Run the diagnosis of the first live run again on the same three books (the card model and the check model on the configured
   servers, nothing filed, nothing sent elsewhere) and record in the Result how many parts end empty and why sentences were dropped.
   This is information for the owner and is not a gate.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate
engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample` and `wb run code-work
check`; the review of the `reviewer` agent is evaluated and recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-ground-the-summary-and-neutral-fields#C`.

### Increment D — A live run, the labelled sample and the comparison

**Outcome:** the owner has numbers on whether grounding the sentences makes the summary and the neutral fields more accurate, at what
loss of content, and has decided.
**Dependencies:** A, B and C, and the owner's word on the books, on sending the sample to a cloud model, and on the calibration labels.
**Affected areas:** the owner's library (new card generations for the books named), files outside the repository, and the plan's
Result. No tracked file other than the plan changes.
**Steps:**
1. Propose to the owner eight to ten books that have a card in the form now in use (generation 1 of the library queue), the cost in
   calls and time, and that the labelling sends items and passages to a cloud model. Wait for the word. (The owner gave the word for
   ten books and for the send of the sample before increment C; the books are named in the Result. If the books or the send change,
   ask again; otherwise the same ten books are made again.)
2. Make the cards of those books in the new form with `cards-queue` and `--again`, as the next generation, and record the calls, the sentences
   asked for, kept and dropped for each reason, the fields that ended empty, and every failure. If a field ends empty on more than a
   fifth of the cards, stop and report before the labelling.
3. Draw one blind sample from both forms of the same books: `card-sample` over the two generations of the books named, with the same
   number of items from each (about 90 each; the summary sentences and the five neutral fields are six of the nine kinds of item it
   takes in turn, so about 60 items of each form are of these fields), so that the book and the kind of item are matched by
   construction. Have a strong model label the whole sample as before, without the generation or the form, and compute the owner's
   agreement on a calibration subset of at least ten items before the cloud labels are used. If the owner does not label, or the
   agreement is below three in four, the comparison is reported as the model's labels alone and the Result says no decision is
   supported.
4. Compare, form against form on the same books, the supported, inference and unsupported shares of the summary and the neutral fields
   (all six together and each apart), with the counts, and the number of sentences and words that the new form lost. The 43 percent of
   the evidence above is given as a reference for the old form on a larger and different set of books, and is not the baseline of the
   decision. The difference between two runs of the same form on the same book was about 12 points in the earlier measurement, and a
   difference smaller than that is not a finding.
5. Write the result in the plan, naming no personal question, path or machine, with the limits and a provenance line, and a
   recommendation: replace the old form if the supported share of the summary and the neutral fields rises, on the same books, by at
   least 20 points over the old form, no more than a fifth of the fields end empty, and the owner agrees with the labels; and say what the check of whole
   sentences let through, so that the owner can decide on `cards#card-clause-check`. Record the owner's decision, including whether the
   library is carded again with `cards-queue`.
**Verification:** the runs of steps 2 to 4 read as written, and the tests of A, B and C once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-ground-the-summary-and-neutral-fields#D`, which holds the plan's
Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After D, rerun
`python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate engine.tests.test_cardqueue
engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample engine.tests.test_setup` and `wb run code-work check`;
nothing wider is named, since no other module reads the grounding record.

## Risks and sensitive actions

- **A model that cites a note for a sentence it does not state.** The check decides, and its answers on pairs with no shared word are
  tested in increment B before it is trusted. A check that is too lenient would pass what it passes now; the labelled comparison
  measures the result.
- **Content lost.** Dropping unsupported sentences may leave a field empty or thin, and the card shorter and less useful. Criterion 3 and
  step 2 of increment D bound this: a field that ends empty is reported, and the run stops above a fifth.
- **The prompt asks for more.** Writing every sentence with support is a larger reply for the card model, whose replies already fail
  in their shape in about one attempt in five; the report counts the failures, and the queue retries once.
- **A new shape for the card call changes the journal.** The prompt version is in the journal's header, so a journal made with the old
  prompt is refused as stale and its book is planned again.
- **Book text and notes go to the owner's local models,** as for every card. The labelling sends items and passages to a cloud model
  and needs the owner's word.
- Nothing is deleted: a new card is a new generation and the earlier ones are kept.

## Review record

- Reviewer: a second model (gpt-5.6-terra) through the project's review engine, on 2026-11-09, round 1 of 3. Verdict: changes needed,
  three findings, all of major severity.
- Applied: (2) the spec revision is now named statement by statement in the scope, with the note that the owner's approval is the
  owner's word for it and that no spec text changes before the approval; the plan also records that the grounding plan and the roadmap
  had left this grounding in scope if the labelled sample showed it paid; (3) increment D (then C) now draws one blind sample from both forms of
  the same books, with the same number of items from each, so that the book and the kind of item are matched by construction, and the
  threshold is a rise form against form; the 43 percent of the evidence is only a reference.
- Rejected, with the reason recorded in the plan: (1) making `cards#card-clause-check` a prerequisite. The roadmap's rules call
  dependencies hints, the owner chose to go on without it on my recommendation, and the plan now says why and what the sentence-level
  check may let through; the owner's approval of the plan is the acknowledgement. The finding stands as a question for the owner at
  approval: a plan that waits for the clause check is the alternative.
- Left for the owner: whether to ask for round 2 before approving, and the question in (1).

## Deferred work

- A check of each clause of a sentence (`cards#card-clause-check`), if the result shows the check of whole sentences lets too much
  through.
- Carding the library again in the new form with `cards-queue`, if the owner decides to.
- The accuracy of the caveats, which a quote rarely states: 0 of 11 supported in the evidence, and out of this plan.

## Result

### Increment A

- **Done** (uncommitted until the owner says to commit). A card of format 2 may carry `grounding.sentences`: for the summary and the
  five neutral fields, the sentences kept (text, mark, notes, quote of a stated one) and the number dropped. The sentences joined with
  a space are exactly the field; with the record the limit has no entry of its own, any of the six fields may be empty, and a card
  with no summary must be partial. `make` and `validate` (so `read` too) refuse any record that does not fit, `grounding_counts`
  counts the sentences, `render` shows a mark after each sentence and the quote of a stated one, and `card-sample` takes a kept
  sentence as an item. A card of format 1, and one of format 2 with no sentence record, behave as before. The `catalog.py` file named in
  the plan needed no change: it uses `grounding_counts` and `render`. The card spec (three statements) and the engine README were
  updated; the card call does not make the form yet.
- **Verification run:** `python3 -m unittest engine.tests.test_card engine.tests.test_catalog engine.tests.test_cardsample`, 233 tests
  OK; `wb run code-work check`, no problems. Tests were written first and seen to fail (the missing `SENTENCE_FIELDS`). Sixteen
  deliberate one-line breaks of the new code were each caught; two (the limit on the number of sentences and on their length) were
  first missed because the tests changed the text and failed on the join, so a test was added that keeps the join true. Not run:
  other test modules; nothing outside the three modules reads the new record.
- **Review:** the `reviewer` agent, one exchange. No blocking findings. Three not blocking, all evaluated: a field that loses all its
  sentences is not tied to a reason on the card (completion criterion 3), which only the card call can supply, so it is done in
  increment B with the thin reasons; repeated sentences and a quote not compared with its notes are not checked on read (repeats are
  B's, and the quote is checked as for the other items); the spec statements run ahead of the code until B, and are marked proposed.
  The reviewer could not run tests or read the new tests.

### Increment B

- **Done** (uncommitted until the owner says to commit). The card call is version `v5`: the summary and the five neutral fields are
  asked for as sentences in three lists of the same length (the part, the sentence, the notes that state it). A sentence is paired
  with the first verified note it cites, with no shared word required, and put to the check with the other pairs; a confirmed
  sentence is kept with the mark `stated`, its note and its quote. Only a sentence of the limit may be the model's own inference
  (`inferred`); a reply that gives `inferred` or `none` to a sentence of another part is refused and kept aside. A reply with more
  than 8 sentences for the summary or 4 for another part is refused; only the first 5 and 3 of a part are checked. A sentence is also
  dropped if it repeats one kept before it in its part or would make the part longer than the card allows, so a card made from any
  accepted reply can be filed. A part that keeps no sentence is empty, the card says so in its reasons, and so is partial. The
  report of `cards` gives, for each part, the sentences asked for and kept and why the others were dropped (`over`, `none`,
  `unpaired`, `not_confirmed`, `repeat`), and `empty`. The schema file names the six parts. `docs/specs/card.md` gained one clause
  (only the limit may be kept as an inference); `engine/README.md` describes the call.
- **Deviation from the plan's wording, and why.** The plan says a reply is refused for `inferred` or `none` "for a field that may
  not be inferred" and did not name the fields. On the owner's answer (only the limit sentences may be inferred) the job refuses both
  for every other part; for the limit, `none` is accepted and the sentence is dropped.
- **Live probe of the check, with the owner's word** (before the build, the check model on its configured server, nothing left the
  machine): 26 pairs built from two cards' notes and from sentences of other books' cards, through the real check prompt. All 14
  unrelated sentence and note pairs were answered `no`; of 8 pairs known to hold, 6 were `supports` and 2 `partly`, none `no`; of
  4 pairs of a stated item with a note from another piece of the same book, 3 were `no` and 1 `partly`. So the check does not
  answer yes to everything. The unrelated pairs are easy negatives; the labelled comparison in D is the test of the harder ones.
- **Verification run:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate
  engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample`, 645 tests OK;
  `wb run code-work check`, no problems. The fake replies of the tests of the card call and of the queue were changed to the new
  shape; the default reply of those tests has one inferred limit sentence, so the other five parts are empty and the cards are
  partial, and the tests that need all six parts use a reply with sentences for each. Twenty-eight deliberate one-line breaks of the
  new code were each caught in the end. Six were first missed, because my test of a bad card reply sent it as the first call, which
  is the notes call; tests were added that send it as the card call and test the job's check directly, and a test that tells a
  sentence with no pair from one the check refused. One further break was an equivalent mutant and the code was simplified. Not run:
  `test_setup` and the other engine modules; nothing outside these modules reads the card call.
- **Review:** the `reviewer` agent, one exchange. No blocking findings. Four not blocking, all evaluated: the comment on
  `MAX_RECORDS` was out of date (the worst case is exactly 30: 20 notes, the card, 6 checks, a round and 2 checks, so there is no
  margin, which a test asserts) and is corrected; the README said `none` for a sentence is refused without the exception for the
  limit, corrected; the spec was looser than the code on which sentences may be inferred, one clause added; the schema file is
  stricter than the engine on the names of the parts, which is harmless and left. The reviewer did not run the tests, did not read
  the new tests in full, and could not say how often a live model's replies are refused with the new prompt: that is for D.

### First live run (increment D begun, stopped by its own rule) and its diagnosis

- **What was done, with the owner's word.** The owner approved ten books that have a card of the old form (generation 1): Prisoner's
  dilemma, Nash equilibrium, Genetic algorithm, Amdahl's law, Message Passing Interface, OpenMP (web pages); The Case for Learned Index
  Structures, Megatron-LM, DeepCAD (papers); Solid modeling (web page). They were made again as generation 2 with `cards-queue` and
  `--again` (run planned for the ten books; two passes; ten done, none failed; two books needed one retry), and the owner approved
  sending a blind sample of about 90 items from each form, with passages, to cloud labellers after the run. Nothing was sent: the run
  stopped at its rule below.
- **Correction of what the owner was told.** The owner was told that the catalog would not be rebuilt. The queue rebuilds it at the
  end of a run, so it was: search shows the generation-2 card for these ten books. The generation-1 cards are untouched.
- **Numbers (generation 2 of the ten books).** The model wrote 93 sentences and 62 were kept (58 stated, 4 inferred); the 31 dropped
  were all sentences that the check did not confirm or that repeated another. Parts that ended empty, of ten cards: needs 5,
  provides 5, approach 4, problem 3, limits 2, summary 0. Nine of the ten cards are partial; the summaries are 20 to 89 words. The
  rule of increment D (stop if a part ends empty on more than a fifth of the cards) fired for four of the five neutral parts.
- **Diagnosis (read-only, nothing filed; three books, twice).** Every dropped sentence had a pair and was judged `partly` or `no` by
  the check; none was dropped for citing no note. The model wrote one sentence for each neutral part, so one refusal emptied it.
  The refused sentences were of two kinds: invented ones that no note states ("readers require familiarity with parallel computing
  basics"), and fair ones whose first cited note is a general one and not the one that states them (a sentence about how the law
  models a task, checked against the note that only defines it). Only the first cited note was shown to the check. The runs differ a
  great deal: the same book ended with 4, 1 and 4 empty parts in three runs, so ten books are a small sample.
- **Consequence.** With only the limit allowed to be an inference, the new form cannot meet the plan's replace rule as it stands.
  The owner chose to fix the two mechanical causes first (increment C: check against up to two cited notes, ask for up to three
  sentences for each neutral part) and to run the ten books again before any labelling. A third option, to let the neutral parts be
  kept as marked inferences, was put to the owner and not taken.
- **Provenance.** Run on the owner's configured servers at commit 2c082cd; the queue's run name is kept outside the repository; the
  probe and diagnosis scripts and logs are held outside the repository.

### Increment C

- **Done** (uncommitted until the owner says to commit). A sentence of the summary or a neutral part is paired with up to two
  verified notes that it cites (`SENTENCE_NOTES`), in the order written; the check prompt shows each note with its point and quote
  under the sentence and tells the check model to read them together; one verdict confirms the sentence. The entry that is kept lists
  the notes that were shown (never one that is not verified or not cited) and has the quote of the first. A topic, key idea or
  caveat is checked as before (one note, a shared word). The card is asked for up to three sentences for each neutral part, each
  saying one thing, and for the notes that together state a sentence, the best first. The card job is `v6` and the check job `v2`,
  so a journal made before is stale. The clause of the card spec on pairing and the engine README say the same.
- **Verification run:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_cardstate
  engine.tests.test_cardqueue engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample`, 650 tests OK;
  `wb run code-work check`, no problems. Tests were written first and seen to fail. Seventeen deliberate one-line breaks of the new
  code were each caught in the end; four were first missed (the cap of two notes was never tested with three verified notes, and a
  phrase of the prompt that the test looked for also stood elsewhere in the prompt), and tests were added. Not run: `test_setup` and
  the other engine modules.
- **Diagnosis again (step 3; read-only, nothing filed, three books, one run each).** No part ended empty in any of the three books
  (the two diagnosis runs before had 1, 2 and 2 empty parts for Amdahl, MPI and Prisoner's dilemma, and then 4, 3 and 4), and every
  sentence the model wrote was kept: the `partly` and `no` verdicts that remain (MPI 4 and 2, Prisoner 1 and 2) fell on list items.
  The model still wrote one sentence for each neutral part although it was told up to three. This is one run of three books, and
  the runs of this model differ a great deal, so it shows that the mechanical causes are fixed and not by how much.
- **Limits recorded, from the review.** (1) The quote shown under a `[stated]` sentence is the first note's, though the check read
  two notes together and its verdict may rest on the second; the card lists both notes. (2) Reading two notes together makes it
  easier to confirm a sentence, because the card model chooses the second note and a loosely related one can fill a gap in the
  first; only `supports` confirms. How often the two-note check wrongly says `supports` is not tested: the probe of increment B
  tested the one-note check on 26 pairs. The labelled comparison of increment D is the test, and its Result must say what the check
  of whole sentences let through.
- **Review:** the `reviewer` agent, one exchange. No blocking findings; seven points, all not blocking and all evaluated: the two
  limits above are recorded here; the rule that a sentence is stated only if the check confirmed a verified cited note holds; the
  entry fits the card record; the check prompt cannot be broken by a note or quote that looks like an item line, since text is
  cleaned to one line and the verdicts are counted by position; the journal is stale for older versions and replay rechecks; and
  topics, key ideas and caveats and the non-goals are untouched. The reviewer did not run the tests, read the tests or see the diff.
- **Committed** by the owner's word as 503d46c, with the trailer `Plan: 2026-11-09-ground-the-summary-and-neutral-fields#C`.

### Increment D

- **Step 1.** The owner's earlier word covered the same ten books and the send of a blind sample to cloud labellers; the owner said
  "Start d" after being told that the run would rebuild the catalog and would send nothing, and said to go on to the labelling after
  the empty-parts rule stopped the run.
- **Step 2, the run (generation 3, same ten books, `cards-queue plan --again` and `run`, two passes).** Nine cards made, one book
  failed: the paper whose card answer twice had `topics` and `topics_support` of different lengths; it keeps its generation 2 card.
  From the nine cards (read back from the cards; the queue does not save the reasons for drops, so only counts exist): the model
  wrote 74 sentences for the summary and the neutral parts, 62 were kept (58 stated, 4 inferred) and 12 dropped (generation 2: 93
  asked, 62 kept, 31 dropped); six of the nine cards are partial (generation 2: nine of ten). The model still wrote one sentence for
  almost every neutral part although it was told up to three. Cards with an empty part, of nine: needs 4, problem 2, limits 2,
  provides 1, approach 0, summary 0 (generation 2, of ten: 5, 3, 2, 5, 4, 0). **The rule of this increment (stop if a part ends empty
  on more than a fifth of the cards) fired for needs, problem and limits.** The catalog was rebuilt by the queue: search shows
  generation 3 for nine of the books and generation 2 for the failed one; earlier generations are untouched.
- **Step 3, the sample.** The owner said to go on to the labelling although the rule had fired. One blind sample with `card-sample`
  (seed 7, 180 items, 90 from generation 1 and 90 from generation 3, over the nine books that have both, 15 for calibration) was
  labelled by a cloud model (Opus, six batches of 30, without the generation or the form; the key was not shown). The batches were
  merged and checked against the original items: the book, field, text and passages of all 180 items are unchanged and every label
  is one of the four. **The owner did not label the calibration items**, so the agreement is not measured: by the plan's rule the
  comparison is the model's labels alone and no decision on replacing the old form is supported by the data.
- **Step 4, the comparison (summary and the five neutral fields, nine books; the model's labels).** Old form, 57 items judged:
  supported 21 (36.8 percent), inference 10 (17.5), unsupported 26 (45.6). New form, 47 judged (2 skipped): supported 21 (44.7),
  inference 8 (17.0), unsupported 18 (38.3). The supported share rose by about 8 points, against the 20 the replace rule asks for, and
  against about 12 points between two runs of the same form in the earlier measurement, so the rise is not a finding. All nine kinds
  of item together: supported 45 of 89 (50.6 percent) for the old form and 45 of 83 (54.2) for the new. The six fields hold 984 words
  in the new form and 1,209 in the old on the nine books (19 percent less); the new form has 62 sentences there.
- **What the check of whole sentences let through.** Of the 45 sentences of the six fields that the new form kept as `stated`, the
  labeller judged 21 supported, 8 inference and 16 unsupported (36 percent); the 2 kept as `inferred` limits were judged skip and
  unsupported. The labeller sees only the five best passages of a book, and the check saw whole notes, so some of the 16 may be
  supported elsewhere in the book; the figure still shows that the check is lenient, and it bears on `cards#card-clause-check`.
- **Limits.** Small sample: about 50 items judged per form in the six fields, nine books, one labeller model, no measure of its
  agreement with the owner. The old form's neutral field is one long item judged whole and the new form is judged by sentence, which
  favours the new form, so the rise, if anything, overstates it. One book is missing from the comparison. The 43 percent of the earlier
  evidence is a reference only.
- **Recommendation (given before the owner's word).** Do not replace the old form: the supported share did not rise by 20 points, more
  than a fifth of the cards have an empty neutral part, and the calibration was not made. Keep the new form as an option and do not
  card the library again. A way on is a separate plan, either to keep neutral parts as marked inferences or `cards#card-clause-check`.
- **Owner's decision.** The owner said to go with the recommendation: the old form is not replaced and the library is not carded again
  with the new form. Which of the two ways on to plan, if either, is not decided.
- **Provenance.** Run on 2026-11-09 at commit 503d46c on the owner's configured servers; the labelling was done by cloud Opus
  subagents; the commands were `cards-queue plan --again`, `cards-queue run`, `card-sample`, `card-accuracy`; the counting scripts,
  the labelled files and the run's name are held outside the repository.
- **Closed without the calibration labels, 2026-11-10.** Completion criterion 5 asks that the owner has labelled a calibration subset
  of at least ten items. The owner did not, and on 2026-11-10 agreed to close the plan without them, on my recommendation: the decision
  above (the old form is not replaced and the library is not carded again with the new form) rests on the model's labels alone, as the
  plan's own rule says, and labelling now would change nothing in it. So criterion 5 is met only in part, and the agreement between
  the cloud labeller and the owner is not measured; that stays a limit of the comparison above. All four increments are committed.
  The plan is marked `Completed` on this record. It makes the candidate `cards#card-ground-the-rest` complete in the sense that the
  form is built and measured; it does not make the new form the form in use.
