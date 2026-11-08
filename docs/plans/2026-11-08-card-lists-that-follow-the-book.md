# Card lists that follow the book

Status: In Progress
Created: 2026-11-08
Candidate: cards#card-grounding
Specs: docs/specs/card.md

## Goal

The topics and key ideas of a card follow what the book holds. A list that was cut off at its ceiling, or that lost most of the
items the model gave it for want of support, gets one more round by a second model, and an item that round adds is kept only
as a `stated` item: it cites a verified note, the note supports it, and it is not a repeat. The round never adds an `inferred`
item. A long book can be read in every piece, when the owner asks for it. A live run on real books and a labelled comparison that
separates the two changes show whether each adds supported items without adding unsupported ones, and the owner decides whether
each stays on.

The plan is done when the engine can make the round and read every piece, a run on books of the library has been labelled and
compared with the cards made without them, the items the round added can be told from the others, and the owner has decided.

## Scope

- A second round for the topics and key ideas of a card, by a model that the owner's config names for a task of its own, run at most
  once for a card, and only when a trigger below holds.
- A setting for the number of pieces of a book that the note stage reads, with the present cap of twelve as its default. This plan
  does not change that default.
- A report of the round and of the pieces read, for each book, and a record in the card of which items the round added, so that a
  sample can draw them as a group of their own.
- A live run on a few books in matched variants, a blind sample of their items labelled by a strong model, the comparisons, and the
  owner's decision.

## Non-goals

- A queue of work for each model, so that a model is loaded once for many books: that is a plan of its own, under
  `cross-field-discovery#neutral-cards-for-the-library`.
- Agreement across two runs of the note stage, grounding of the summary and the neutral fields, a check clause by clause, a fix for
  replies of the wrong shape, and what to do with `inferred` items: they are the other candidates of `cards.md` and are not
  planned here.
- A change to what an item of a card holds. The items the round adds are ordinary `stated` items of a format 2 card. The one
  addition to the card is an optional entry in its generation record that names the items the round added (Increment A).
- The treatment of `inferred` items, which `cards#card-inferred-items` decides. The round asks for none, because an `inferred`
  item is the model's own word and was unsupported in 10 of 13 judged items in the grounding run; this makes the round stricter
  than the first round by choice, and the card spec says so (Increment A).
- A cloud model as a card writer or checker. A cloud model labels the sample and does nothing else.
- Rewriting existing cards: a new card is a new generation.

## Assumptions and constraints

- Evidence for the design, read from the nine grounded cards of the library at commit `bd31a94` (a read-only count, held outside
  the repository): of the nine cards, two have a list of topics that reached the asked twelve and two a list of key ideas that
  reached the asked seven, with none of their items dropped; two have a list that lost half or more of its items to the check
  (one paper of three pieces kept two key ideas and four topics out of twelve and is marked thin; a second kept three key ideas
  and lost four);
  and one book has thirteen pieces, of which twelve are read. So the second round has two cases to serve: a list that may have had
  more, and a list that lost most of what it had. Whether the lost items were wrong or only badly cited is not known, and this plan
  does not assume it.
- The measure is the one of the grounding plan: a blind sample of items, labelled supported, inference or unsupported by a strong
  model from the passages that best match, with the owner's labels on a small subset as a check. In that run a strong model and
  the owner agreed on 12 of 15 items. The labels of a second look at five items against the whole book agreed with the
  passage-only labels in all five.
- The notes carry the verified quotes, and the engine already pairs each item with a cited note and has a second model confirm the
  pair (`docs/specs/card.md`). The round reuses that path, so the round cannot admit what the first round could not.
- Models run on the owner's server through the workbench bridge. A model that the round uses is named in the owner's config under
  `tasks`; an unset task means the round is not made, and the report says so. Book text and notes go only to the models the
  config names, as for every card call.
- Time and calls are spent on accuracy (the owner's standing instruction), and a card is never padded to reach a size.
- The live run, the labelling by a cloud model and the owner's labels each need the owner's word before they are done.

## Completion criteria

1. A card is offered one round by the model of the task `card-more` for a list (topics or key ideas) when the model gave the asked
   number of items, or when the check kept fewer than half of the items the model gave and dropped at least two, or, for key
   ideas, when fewer than the floor of three were kept; for no other list, and never a second round for a card. The first two
   triggers have a test for topics and for key ideas, and the third has one for key ideas and one that shows it does not start a
   round for topics.
2. An item added by the round is kept only as a `stated` item: it cites a note whose quote was found in its piece, a second model
   confirms that the note supports it, and it shares fewer words with every item already kept than the repeat limit allows;
   otherwise it is dropped and counted. The round asks for no `inferred` item. The lists never exceed their ceilings.
3. The generation record of a card names the items the round added, and `card-sample` can draw them as a group of their own.
4. With the task unset, the card is made as before and the report says that the round was off. With it set to a name that is not in
   the registry, `cards` refuses before it sends anything.
5. The number of pieces read is a setting with a documented default of twelve (unchanged) and a documented largest value, and the
   report names the pieces read and the pieces the book has.
6. A live run on books named by the owner has made matched generations (Increment C), a blind sample of their items has been
   labelled, and the numbers are recorded for each comparison.
7. The Result records the numbers, the limits and the owner's decision on whether the round stays on and whether reading every
   piece is worth its cost; the default cap is changed only by a later change that cites that decision.

## Increments

### Increment A — A second round for lists that were cut off or lost most of their items

**Outcome:** `cards` can make one further call, to the model of the new task `card-more`, for the topics and key ideas of a card
when a trigger holds, keeps what it adds only as `stated` items on the terms of the card call, and records which items the round
added.
**Dependencies:** none.
**Affected areas:** `engine/kb/cardmake.py` (the triggers, the job and prompt, the repeat limit, the use of `pairs`, `check_job` and
`ground` for the added items, the report fields), `engine/kb/card.py` and `engine/kb/schemas/card.json` (an optional entry of the
generation record that names the items the round added, in a format 2 card only, and its validation), `engine/kb/cardsample.py` and
the sample's item and key files (the group of round-added items), `engine/kb/models.py` (the task `card-more`, optional),
`engine/kb/__main__.py` (the upfront check of tasks and a `card-sample` option for the group), `engine/kb/schemas/` (the schema of
the reply), `engine/tests/test_cardmake.py`, `engine/tests/test_card.py`, `engine/tests/test_cardsample.py`,
`engine/tests/test_models.py`, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first, with fake models. The round is offered for a list when (a) the model gave the asked number of items, (b)
   the check kept fewer than half of the items the model gave and dropped at least two, or (c) for key ideas, fewer than three were
   kept; (a) and (b) are each tested for topics and for key ideas, (c) is tested for key ideas and shown not to start a round for topics,
   and none is offered for any other card, and no card is offered more than one
   round. An added item that cites no note, cites an unverified note, is not confirmed by the check, repeats a kept item, or would
   pass the ceiling is dropped and counted; the round is never asked for an `inferred` item and a reply that marks one is refused. A
   reply of the wrong shape refuses the round and keeps the card as the first round made it. With the task unset no call is made and
   the report says so. The generation record names the items the round added, a card without the round has none, and a record that
   names an item the card does not hold is refused when read. `card-sample` draws the named items as a group of their own and
   keeps them in the key.
2. Add the task `card-more` to the tasks the engine knows, as an optional one: `models.choose` for it returns nothing when the config
   does not list it, and `cards` still refuses before any book if a listed name is not in the registry.
3. Write the job: a prompt that gives the outline, the verified notes and the items already kept for the field, asks for at most the
   number of free places, each different from those kept and each naming the notes that support it, and a schema for the reply. The
   prompt version is recorded with the call, as for every job.
4. Feed the added items through `pairs`, `check_job` and `ground` as the first round's items go, and merge them into the lists in
   order after the kept ones. The repeat limit is a share of content words (five-letter prefixes, as `pairs` counts them) that an
   added item may have in common with a kept item, set so that a restatement is dropped; it is a constant with a test.
5. Report, for each card, whether the round ran and why, the items asked for, added and dropped for each reason, and the calls.
6. Update the card spec (the triggers, that the round adds `stated` items only and asks for no `inferred` one, and the new record
   entry) and the engine README. Make deliberate breaks of the triggers, the merge, the repeat limit, the ceiling and the record
   from a green baseline.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models
engine.tests.test_catalog engine.tests.test_cardsample` and `wb run code-work check`. The tests were written first and failed for
the right reason. The independent reviewer's findings are evaluated and recorded.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-card-lists-that-follow-the-book#A`.

### Increment B — A setting for the number of pieces read

**Outcome:** the number of pieces of a long book that the note stage reads is a setting of the owner's config, with twelve as its
default and a stated largest value, and the report names the pieces read and the pieces the book has.
**Dependencies:** none (it may be built before A).
**Affected areas:** `engine/kb/cardmake.py` (the sample of pieces), `engine/kb/config.py` and the config check (the setting),
`engine/kb/__main__.py`, `engine/tests/test_cardmake.py`, `engine/tests/test_setup.py`, `docs/specs/card.md`, `engine/README.md`.
**Steps:**
1. Write the tests first: the default is twelve; a larger value reads more pieces of a long book and the same pieces of a short one;
   a value under one, above the largest, or of the wrong type refuses the config; the report names both numbers; a book of
   few pieces reads them all.
2. Add the setting to the config and its check, replace the constant `MAX_PIECES` by it where the pieces are chosen, and keep the
   choice of which pieces to read as it is when the cap is lower than the book (spread across the book, as now).
3. Update the card spec and the engine README, and state the cost: one notes call for each piece more.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog
engine.tests.test_setup` and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-card-lists-that-follow-the-book#B`.

### Increment C — A live run, the labelled sample and the comparison

**Outcome:** the owner has numbers on whether the second round adds supported items, and separately on whether reading every piece
of a long book does, and has decided about each.
**Dependencies:** A and B, and the owner's setting of `tasks.card-more` and of the cap for the run.
**Affected areas:** the owner's library (new card generations for the books named, the catalog), files outside the repository, and
the plan's Result. No tracked file other than the plan changes.
**Steps:**
1. Propose to the owner the books (three to five: at least one with more than twelve pieces, preferably two, and one whose card was
   thin), the model for `card-more`, and the cost in calls and time. Say that the labelling sends items and passages to a cloud
   model. Wait for the owner's word.
2. Make matched generations for each book, each changing one thing from the baseline, and record for each the calls, the pieces
   read, the items asked for, added and dropped, and every failure:
   - **baseline**: round off, the default cap of twelve;
   - **round**: round on, the default cap of twelve;
   - **coverage**, for the books with more than twelve pieces only: round off, every piece read;
   - **both**, for the same books: round on, every piece read.
   The baseline is made twice for every book, so that for each book there is a measure of how much two runs of the same thing
   differ.
3. Run `card-index`, draw a blind sample with `card-sample` over the generations (the items the round added are drawn as a group of
   their own, so that they are counted), and have a strong model label it as in the grounding plan. The key is kept by me and not
   given to the labeller. The owner labels a calibration subset of at least ten items of the sample, blind, and the agreement
   between the owner and the strong model on it is computed before the cloud labels are used for any comparison. If the owner
   does not label the subset, or the two agree on fewer than three items in four, the comparisons are reported as the model's labels
   alone and the Result says that no decision is supported by them; the owner then decides on that footing or stops.
4. Run `card-accuracy` and `card-agreement`, and make these comparisons, each with its counts:
   - the items the round added against the items the first round kept (round against baseline);
   - the cards as a whole, round against baseline (the share of supported and unsupported items, and the number of kept items);
   - coverage against baseline, and both against round, on the long books only;
   - the two baseline runs of each book against each other, as the size of an ordinary difference for that book.
5. Write the result in the plan, naming no personal question, path or machine: the counts, the shares, what each change added and
   lost, the cost, the limits (a few books, a small sample, a difference smaller than the one between the two baseline runs of
   the same books is not a finding), and a provenance line. Give a recommendation for each change on its own: keep the round on if the items it added are
   supported at a share of at least 60 percent and not far below the first round's, and the cards as a whole are not less accurate
   than the baseline by more than the difference between the two baseline runs of the same books; read every piece only if the long books gained
   supported items without a lower supported share. Record the owner's decision on each. The default cap stays twelve in this plan.
**Verification:** the runs of steps 2 to 4 read as written, and the tests of A and B once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-08-card-lists-that-follow-the-book#C`, which holds the plan's
Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After C, rerun
`python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog engine.tests.test_models
engine.tests.test_cardsample engine.tests.test_setup` and `wb run code-work check`; nothing wider is named, since no other module
reads what changed.

## Risks and sensitive actions

- **A model adds what the book does not hold.** The round's items face the same pairing and the same check as the first round's, and
  C measures them against labels before the owner decides to keep the round on. A check that is too lenient would pass what the first
  round's check passes; the grounding run found it was right on most items and lenient at the edge of inference.
- **A list fills with near-repeats.** The repeat limit and its test are the guard; C counts the repeats.
- **More calls and time.** The round runs only when a trigger holds, at most once for a card, and the report counts the calls. A
  larger cap costs one notes call for each piece more. The live run makes at least three generations of every book (the baseline twice, and the round) and a fourth and fifth for each long book.
- **Book text and notes go to a model.** To the models the config names, on the owner's server, as for every card call.
- **The labelling sends items and passages to a cloud model.** It is done only on the owner's word, as in the grounding run.
- Nothing is deleted: a new card is a new generation and the earlier ones are kept.

## Review record

- Reviewer: a second model (gpt-5.6-terra) through the project's review engine, on 2026-11-08, round 1 of 3. Verdict: changes
  needed, five findings, all of major severity. Round 2 not asked for yet.
- Applied (all five): (1) the triggers now cover topics and key ideas alike, with a loss rule and a test for each; (2) the round
  adds `stated` items only and asks for no `inferred` one, stated as a choice in the scope and in the spec update, with the wider
  treatment of `inferred` items left to its own candidate; (3) the comparison uses matched generations (baseline, round, coverage,
  both) plus a repeat of the baseline, and each recommendation has its own comparison and threshold; (4) the generation record
  names the items the round added and `card-sample` draws them as a group, with the files and tests in increment A; (5) the
  evaluation compares every piece against the cap of twelve on long books and leaves the default cap unchanged in this plan.
- Round 2 of 3, same reviewer: verdict changes needed, two major findings and one minor. Applied (all three): (1) the baseline is
  made twice for every book and the margin for each decision comes from the matched books, not from one book; (2) the owner's
  calibration subset (at least ten items) and the agreement on it are required before the cloud labels are used, and without
  them the Result says no decision is supported; (3) the third trigger is tested for key ideas only, with a test that it starts no
  round for topics.
- Rejected: none.
- Left for the owner: whether to ask for round 3 before approving (the plan was approved after round 2).
- Increment A: reviewed by the `reviewer` agent (see the Result): no blocking findings, two applied, two not changed with reasons.

## Deferred work

- A queue per model, so that a model is loaded once for many books (`cross-field-discovery#neutral-cards-for-the-library`).
- Agreement across two runs of the note stage, grounding of the summary and the neutral fields, a check clause by clause, a fix for
  replies of the wrong shape, and the treatment of `inferred` items (the other candidates of `cards.md`).
- A second round for the caveats and the limit, which a quote rarely states.

## Result

### Increment A — A second round for lists that were cut off or lost most of their items (built; not committed)

- Built: the optional task `card-more` (`models.REQUIRED_TASKS`, `OPTIONAL_TASKS`, `models.optional`; `cards` checks only the three
  needed tasks up front, and a `card-more` name that is not in the registry is still refused before any book, because the registry
  checks every task of the config); in `cardmake.py` the triggers (`full`: the model gave the asked number; `lost`: the checks kept
  fewer than half of what it gave and dropped at least two; `thin`: key ideas only, fewer than three kept; each needs a free place),
  the prompt (title, outline, notes, the kept items), the job `card-more` v1 with its schema (a support must be note numbers; a
  reply that marks `inferred` or `none` is refused), a cut of the reply at the number asked (which is at most the free places, so the
  ceilings hold), a repeat limit (three quarters of the content words of the item with fewer, 5-letter prefixes as `pairs` counts
  them), the use of `pairs`, `check_job` and the same ten-to-a-call check for the items it adds, a merge after every call has been
  made (so a refused or failed round leaves the card as the first round made it), thin-card wording that says a second round was
  made, and the report field `more`; in `card.py` the optional `added` entry of the grounding record (positions in order, in range,
  stated, topics and key ideas only); in `cardsample.py` the option `added` (draws that many of the added items, counts them in their
  generation's share, marks them in the key; refuses more than exist or than a generation's share) and a group `added` in
  `card-accuracy`; `card-sample --added N`; the card spec and the engine README.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_card
  engine.tests.test_models engine.tests.test_catalog engine.tests.test_cardsample` gave 495 tests, OK; `wb run code-work check` found
  no problems. The tests were written first and failed for the right reason. Deliberate breaks, each from a green baseline: 32
  conditions of the new code, 31 caught at once and one equivalent edit that survived (a changed label in the KEPT section of the
  prompt, with the items still shown). Four gaps found by the breaks and fixed with tests: one dropped item is not a list that lost
  much; the number asked is at most the free places; a generation's share of added items; and, after the review, a reply with more
  items than were asked. Not run: any live run with real models (increment C), the full engine suite, and the other test files.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: a reply with more items than were asked is cut at the number
  asked before the check (the cut ones count as `over`), which also makes the ceiling check in the merge unreachable, so it was
  removed; the report's `checks` totals include the round's items, now said in the README. Not changed, with reasons: the thin
  wording says "a second round added what it could" whenever a round ran, which is true because the key ideas are always offered the
  round when fewer than three are kept; `--added` draws uniformly over all added items, which is a group of their own as the plan
  says, and a corpus in which one generation has more of them than its share is refused, not rebalanced.
- Recorded for C: a round that is refused is not kept aside, as a card call's reply is (`make_model_part` has no store); the report
  carries the reason. If a live run shows refusals, keeping the reply aside is a small addition.
- Next: the owner's word to commit increment A.
