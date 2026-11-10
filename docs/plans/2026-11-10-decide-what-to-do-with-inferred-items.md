# Decide what to do with inferred items

Status: Proposed
Created: 2026-11-10
Candidate: cards#card-inferred-items
Specs: docs/specs/card.md

## Goal

The owner decides, from numbers, what the library does with the topics and key ideas of a card that are marked `inferred` (the card
model's own word that no verified note states them): drop them, leave them out of the search, or keep them and show the warning. This plan
gets the numbers, puts them to the owner with options, and records the decision. It does not change the cards, the display or the search:
that depends on the choice and is a plan of its own (Deferred work). The roadmap candidate `cards#card-inferred-items` names both halves, the
decision and the change of the cards and the display that follows it; this plan is the first half, so **the candidate is not complete when
this plan is**, and stays open until the follow-up plan is done. Nothing here changes the roadmap.

## Scope

- A read-only command that counts the items marked `stated` and `inferred` by field and by form of card, over the newest card of each
  version, so that the figures can be read again and not only once.
- A way to draw one blind sample that holds a stated number of `inferred` and of `stated` items of the topics and key ideas, split
  equally over the fields named for each mark (the share a field cannot fill, because its pool is smaller, goes to the other field and is
  reported), mixed and shuffled, with the mark kept in the key and not in the items file, and a `card-accuracy` that reports the labels by
  mark and by field.
- One labelling of that sample by strong-model labellers, on the owner's word, and the owner's labels of a calibration subset if the
  owner wishes to give them.
- The numbers and the options put to the owner, and the owner's decision recorded.

## Non-goals

- Any change to the cards, the catalog, the vectors, the display or the search: they follow the decision, in a plan of its own.
- Caveats and limits. The roadmap candidate puts how they should be written out of scope until the owner says, and the counts below show
  why: most of them are `inferred` because a quote can rarely state them.
- The summary and the neutral parts of a card in the sentence form, and the accuracy of `stated` items as such (the earlier grounding
  work measured it); `stated` items are drawn here only as the comparison for the `inferred` ones.
- A new model, a new prompt or a new check of an item.

## Assumptions and constraints

- **Today's marks** (counted on 2026-11-10 at commit `6483487` with a throwaway script, from the newest card of each version that carries
  marks: 106 cards, 96 in the earlier form and 10 in the sentence form; Increment A replaces the script with a command). Earlier form:
  topics 644 `stated` and 116 `inferred` (15 percent), key ideas 381 and 80 (17 percent), caveats 29 and 146 (83 percent), limits 15 and
  59 (80 percent). Sentence form: topics 84 and 8, key ideas 58 and 5, caveats 6 and 13. So 209 topics and key ideas are `inferred`.
- **What the earlier measurement found** (`2026-11-07-card-grounding`, its Result): of 73 `stated` topics and key ideas judged, 64 were
  supported (88 percent); of 13 `inferred` items judged (caveats, the limit, a few key ideas and one topic), 2 were supported, 1 was an
  inference and 10 were unsupported (77 percent). The 13 are too few to decide on, and most were caveats and limits.
- **What the library does with an `inferred` item now.** It is kept on the card and marked `[inferred]` when the card is shown; the
  catalog's keyword index (`cards_fts`) holds the text of every topic and key idea whatever its mark; the vectors are made from the three
  neutral fields only; a search result gives the counts of stated and inferred items of the card (`grounding`), not the mark of each item.
  The options are therefore: (a) drop the `inferred` topics and key ideas when the card is made; (b) keep them on the card and leave
  them out of the keyword index; (c) keep and index them and show the mark with each item found, as `card-show` does now.
- **Labelling.** As in the earlier grounding work: a blind sample with the passages of the book that share the most words with each item
  (up to five, of at most 600 characters), labelled `supported`, `inference`, `unsupported` or `skip` by strong-model labellers that see
  the item and the passages and not the key. A labeller sees only those passages, so an item supported elsewhere in the book is counted
  `unsupported`; the same method is applied to the `stated` items, so the bias is shared and the difference is what is read. The 15
  items of the earlier calibration set that the owner has not labelled stay the owner's to label, and are not needed to run this plan.
- **Text sent out.** The labelling sends the text of the sampled items and their passages to the labellers, which are not on the owner's
  machine. The pages and papers are public. It is sent only on the owner's word, said before, with the number of items and the size of
  the send. The key (which card, which mark) stays on the machine and is never given to a labeller.
- Files of the sample are held outside the repository, in a private folder, as `card-sample` already does.

## Completion criteria

1. `python3 -m kb card-marks` prints, for the newest card of each version, the number of items marked `stated` and `inferred` by field
   and by form, and prints no card text; it calls no model and changes nothing.
2. `card-sample` can draw a sample with a stated number of `inferred` and of `stated` items of the fields named, split equally over
   those fields for each mark, with the fallback reported, mixed and shuffled; the items file does not say which is which; the key
   does; `card-accuracy` reports the labels by mark and by field (and still by generation).
3. A labelled sample of 60 `inferred` and 60 `stated` items of topics and key ideas, 30 of each mark for each field (or all that exist,
   with the rest given to the other field), exists, with the share of `supported`, `inference` and `unsupported` for each mark overall
   and for each mark and field, and the limits of the method stated, among them that a cell of 30 items has an interval of about plus
   or minus 17 points.
4. The numbers and the three options are put to the owner, with a recommendation, and the owner's decision is recorded in the Result,
   with what the follow-up plan must change. The Result says that `cards#card-inferred-items` is not complete and names the follow-up
   plan that remains to be written.
5. The tests of the changed modules pass, the sentence-form and earlier-form card tests are unchanged, and `wb run code-work check`
   finds no problems.

## Increments

### Increment A — Count the marks

**Outcome:** `python3 -m kb card-marks` reads the cards and prints the counts of `stated` and `inferred` items by field and by form, and
the number of cards without marks (built from the metadata), for the newest card of each version or for the generations named.
**Dependencies:** none.
**Affected areas:** a new module `engine/kb/cardmarks.py`, `engine/kb/__main__.py`, `engine/README.md`, a new test module
`engine/tests/test_cardmarks.py`.
**Steps:**
1. Read `card.py` (`grounding_counts`, the marks of a card, how a card of each form is read) and `card-sample`'s way of walking the
   library, and write down how the form of a card is told (a sentence record, `grounding.sentences`).
2. Write the tests first: a library with cards of both forms, a metadata-only card and an unreadable card gives the counts by field and
   form, the count of cards without marks and of cards that could not be read; the output holds numbers and names of fields and no
   text of a card; the command writes nothing and calls no model; `--generation` names other generations. See them fail.
3. Write the module and the command; document it in the README.
4. Deliberate breaks, each from green: a mark counted for the wrong field, the two forms added together, a metadata card counted as
   marked, the oldest generation read instead of the newest, text of an item in the output.
5. The independent `reviewer` agent.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmarks engine.tests.test_card
engine.tests.test_cardsample` and `wb run code-work check`; then the command on the library, whose figures must equal the counts above
(or the Result says why they differ). No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-decide-what-to-do-with-inferred-items#A`.

### Increment B — A sample by mark, and the accuracy by mark

**Outcome:** a blind sample of `inferred` and `stated` items of the fields named can be drawn in one go, and the labelled file reports the
labels by mark.
**Dependencies:** A (for the figures it is checked against).
**Affected areas:** `engine/kb/cardsample.py`, `engine/kb/__main__.py`, `engine/README.md`, `engine/tests/test_cardsample.py`.
**Steps:**
1. Read `cardsample.py` (how items are drawn and shuffled, what the key records, what `card-accuracy` groups by). Write down whether the
   key already records the mark of an item; if it does not, it must, and the items file must still not.
2. Write the tests first: `--marks inferred=N stated=M` draws N and M items of the fields given (refused if the cards hold fewer, as for
   `--added`), N/2 and M/2 for each of two fields (an odd number gives the extra one to the field named first); when the pool of a
   field and mark is smaller than its share, all of it is taken, the rest goes to the other field, and the printed summary says so;
   the items file has no mark and no order that tells the mark apart (the draw is shuffled, and the two kinds are not in two runs); the
   key records the mark; the same seed gives the same sample; `card-accuracy` reports the counts and the shares of each label for each
   mark within each field and for each mark overall, and refuses a key without marks when `--by-mark` is asked; the draw of a sample
   without the option is as it was. See them fail.
3. Add the option and the report.
4. Deliberate breaks, each from green: the mark in the items file, the two kinds drawn in blocks, the key without the mark, the draw
   not seeded, the old draw changed, the share of one mark counted into the other, the shares of the fields not equal, a pool that is
   too small refused instead of given to the other field, the fallback not reported.
5. The independent `reviewer` agent.
**Verification:** the same test modules as A with `engine.tests.test_cardsample`, and `wb run code-work check`. No call is made to the
owner's server.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — Label the sample

**Outcome:** a sample of 60 `inferred` and 60 `stated` items of topics and key ideas is labelled, and the shares of `supported`,
`inference` and `unsupported` are known for each mark.
**Dependencies:** B.
**Affected areas:** the files of the sample in a private folder outside the repository; this plan's Result. No tracked code.
**Steps:**
1. Draw the sample: `card-sample OUTDIR --field topics --field key_ideas --marks inferred=60 stated=60 --seed N`. Tell the owner the
   number of items, the size of the items file (the passages included), and that the item text and the passages of public pages go to
   the labellers and the key does not; wait for the owner's yes. The owner may also label the calibration set.
2. Have strong-model labellers label the items file as subagents that are given the file and the rules and not the key; record the
   model and the date. Use the number of labellers the earlier work used for a comparison of agreement, and say how many were used.
3. Run `card-accuracy` with the key, by mark, and `card-agreement` between labellers (and with the owner's labels, if given). Write
   the figures in the Result with their provenance: the commands, the tool versions, the commit, the seed, and the hash of the items
   file. State the limits: only the passages shown are seen, one kind of labeller, the sample size and its interval.
**Verification:** `card-accuracy` accepts the labelled file (no unlabelled item, no inference without a note); the counts add up to the
sample; the agreement is reported; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`, holding the Result.

### Increment D — The numbers, the options and the decision

**Outcome:** the owner has decided what the library does with `inferred` topics and key ideas, and the decision is recorded.
**Dependencies:** C.
**Affected areas:** this plan's Result; if the owner asks, a draft of the follow-up plan.
**Steps:**
1. Put to the owner: the counts of Increment A, the shares of Increment C by mark and field, what each option would do to the cards
   (how many items it would drop or hide in today's library), and a recommendation with its reasons.
2. Record the owner's decision and what the follow-up plan must change (the card call, the format, the display, the search, the
   catalog). Writing that plan is a new piece of work for the owner to ask for; do not begin it.
**Verification:** the Result holds the numbers, the options, the decision and the owner's words; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the card test modules once
and `wb run code-work check`, and run `card-marks` once more to confirm that the counts in the Result are the library's. A wider run is
not named. What could break outside what is tested is the draw of `card-sample` without the new option, which a test pins.

## Risks and sensitive actions

- **Text sent out.** Increment C sends item text and passages of public pages to labellers outside the machine; the key stays here. Said
  to the owner with the size, and sent only on the owner's word.
- **A small or biased sample.** 60 items of each mark give an interval of roughly plus or minus 12 points at a share near 20 percent
  (about plus or minus 17 for the 30 items of a mark and field);
  labellers see only five passages, so every share is a lower bound for support; both marks are labelled the same way, and the
  difference is what is read. The Result states this and does not call the figures accuracy of the cards.
- **A decision made on the wrong field.** Caveats and limits are mostly `inferred` and are not in the sample; the Result says the figures
  are for topics and key ideas only, so that the owner does not read them as a verdict on caveats and limits.
- **The draw changes.** Adding an option to `card-sample` could change the sample it draws without the option; a test pins the old
  draw for a fixed seed.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, two findings (one major, one minor),
both applied:

- **R1-F1, applied (major).** The roadmap candidate `cards#card-inferred-items` names both the decision and the change of the cards and
  the display that follows it, and this plan covers only the decision, so finishing it would leave the candidate open. The plan was
  already open about leaving the change to a follow-up plan; the Goal now says that this plan is the first half and the candidate is not
  complete when it is done, and criterion 4 requires the Result to say so and name the follow-up plan. Not done, and why: an
  implementation increment (what it would change, the card call, the keyword index or the display, depends on the owner's choice among
  the three options, so it cannot be written and approved first), and splitting or narrowing the candidate (a change to a roadmap,
  which only the owner may make). The second is raised with the owner.
- **R1-F2, applied (minor).** A sample of 60 items per mark did not require any items in each field. The draw now splits each mark
  equally over the fields named, with the share of a field whose pool is smaller given to the other field and reported; the allocation is
  tested and has deliberate breaks; the criteria and the figures put to the owner are by mark and by field, and the interval of about
  17 points for a cell of 30 items is stated.

A second round has not been asked for.

## Deferred work

- The follow-up plan that makes the decision real in the card call, the card format, `card-show`, the catalog and the search.
- Caveats and limits: how they should be written when a quote cannot state them (the other half of the boundary of the candidate).
- The 15 unlabelled calibration items of the earlier work, which the owner may label at any time.
- The rate at which the card model marks an item `inferred`, which depends on the model and the prompt and is not changed here.

## Result

### Increment A — Count the marks

- **Done.** `engine/kb/cardmarks.py` (`counts`) and the command `python3 -m kb card-marks [--generation G ...] [--book BOOK_ID ...]`. It
  reads the newest card of each version of each active book, or the generations named, and prints the number of `stated` and `inferred`
  items for each field of each form of card, with every field of a form listed (zeros where nothing is marked), the number of cards
  read, `without_marks` (`metadata`: a card built from the metadata; `not_checked`: a card of the first format, with a model part and no
  grounding record), `unreadable`, and the generations counted. It calls no model, opens the store read-only, writes nothing and takes no
  model, server or path option. How the form of a card is told (step 1): the grounding record of the sentence form has a `sentences`
  entry and that of the earlier form has none; in the earlier form the limit is one marked entry (or none), and in the sentence form the
  limit and the summary are marked sentences under `sentences`.
- **Deviations.** (1) Two sentences of `engine/README.md` that said nothing is retried (one in "What a model is told", one in "Not
  covered") are corrected to the retry that has existed since the plan `2026-11-10-keep-one-reply-slip-from-failing-a-book`; they are
  outside this increment's Affected areas, and I should have caught them in that plan. (2) Step 2 asked for the tests to be seen to fail:
  they failed first because the module did not exist and then because of faults in my own fixtures (a grounding record must have one
  entry per item and an `inferred` entry has no quote), so the evidence that they bite is the deliberate breaks below.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmarks engine.tests.test_card
  engine.tests.test_cardsample engine.tests.test_cardmake`: 395 tests, OK (`test_cardmarks` has 13); `wb run code-work check`: no
  problems. 17 deliberate breaks, each from green (a mark counted for the wrong field, the two forms added together, a metadata card
  counted as not checked and the reverse, the oldest generation read, text of a card in the output, a book that is not active counted,
  an unreadable card not counted, the limit counted when it is not there, the sentences not counted, a generation that no card has not
  refused, fields listed only when seen, named generations read as the newest, the cards read counted as the cards with marks, and
  the limit and a kept sentence counted twice, the last two seen caught by the test that adds the fields up to `card.grounding_counts`),
  were each caught; a caveat counted as a key idea is caught by the field tests and not by the totals, as it should be. No call was
  made to a model server.
- **On the library** (a read-only run on 2026-11-10 at commit `6483487` plus this change): 109 cards read; 96 of the earlier form and 10
  of the sentence form with marks; 1 built from the metadata and 2 of the first format with none; 0 unreadable. Earlier form: topics 644
  `stated` and 116 `inferred`, key ideas 381 and 80, caveats 29 and 146, limit 15 and 59. Sentence form: topics 84 and 8, key ideas 58
  and 5, caveats 6 and 13, summary 29 and 0, problem 8 and 0, approach 9 and 0, needs 5 and 0, provides 9 and 0, limit 6 and 4. The counts
  equal those written in the plan, which were made with a throwaway script.
- **Review.** Independent `reviewer`, one exchange, no blocking finding. Applied: a test that adds the fields of a card up to
  `card.grounding_counts` (by reading the two agree; now pinned), the items of the fixtures made distinctive so that the test that no
  card text reaches the output is not satisfied by short strings, and the second stale README sentence. Not done: a test with several
  versions of one book (the walk is that of `card-sample`, and the library has one version per book). It could not run anything or read
  the diff.

### Increment B — A sample by mark, and the accuracy by mark

- **Done.** In `engine/kb/cardsample.py`: `card-sample --marks inferred=N stated=M --field ...` draws one sample with N items marked
  `inferred` and M marked `stated`, from the newest card of each version that carries marks. Each count is split equally over the fields
  named (the extra item of an odd count to the field named first); a field whose pool holds fewer than its share gives all it has and
  the rest goes to the others, and the summary says, for each mark and field, what was asked and what was drawn (`allocation`) and the
  counts of each mark (`marks`); a mark whose fields hold fewer than asked is refused. In each cell the cards are visited in turn, so
  no card fills it. The items are mixed and shuffled with the same shuffle as any sample, and ids are given after it; the items file and
  the calibration file never say the mark, the key does (`mark` for each item, and the counts asked for at its top). `card-accuracy
  --by-mark` reports the counts and the shares of `supported`, `inference` and `unsupported` for each mark overall and for each field
  of each mark, and is refused for a key in which an item has no mark; without the option the report is as it was. `_load_key` accepts
  an optional `mark` and checks its value, so keys of earlier samples load as before. `parse_marks` reads `MARK=N` and refuses anything
  else, a mark twice, and a count of more than six digits. Step 1 (does the key record the mark?): it did not; `mark` is new.
- **Deviations.** (1) `--marks` accepts only `topics`, `key_ideas` and `caveats`, the three fields whose items carry a mark one by one in
  both forms of the card (the limit has one mark in the earlier form, the other fields of the sentence form are marked as sentences);
  the plan said "the fields named". (2) The size of the sample is the sum of the counts, so `--items`, `--generation` and `--added` are
  refused with `--marks`; `--items` no longer has the default 80 on the command line, `sample` applies 80 when it is given no size and
  no marks (the only callers are the command and the tests, by keyword). (3) A `stated` item that a second round added can be drawn like
  any other `stated` item (its key entry is not flagged `added`); the docstring says so.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_cardsample`, `test_cardmarks`, `test_card`,
  `test_cardmake`, `test_cardmake_earlier`, `test_cardqueue`, `test_cardstate`, `test_catalog`, `test_models`: 939 tests, OK (90 of
  them in `test_cardsample`), run after the review's fixes; `wb run code-work check`: no problems. The draw without the option is pinned by
  a trace of seed 7 taken from the code before the change (`UnchangedDrawTest`; stable over six runs before it was written into the
  test), and the summary and key of such a sample are pinned to the keys they always had. 22 deliberate breaks, each from green (the
  mark in the items file, the two kinds drawn in blocks, the key without the mark, the draw not seeded, the old draw changed, the
  share of one mark counted into the other, the shares of the fields not equal, the extra item to the last field, a pool that is too
  small refused, the fallback not reported, `--by-mark` not refused for a key without marks, a mark of the key not checked,
  generations or added items or a size accepted with marks, any field accepted, a mark named twice accepted, a card with no marks
  drawn from, one card filling a cell, the size not the sum, the command ignoring `--by-mark` or `--marks`, and the length of a count
  not limited) were each caught; two were first missed (a mark named twice, because the command-line test was refused for its
  calibration and not for the option; the size not the sum, because nothing set a calibration between the largest count and the sum)
  and the tests were strengthened. The tests failed first for the missing option (33 errors and failures). No call was made to a model
  server and no file of a sample was made outside a temporary folder.
- **Review.** Independent `reviewer`, one exchange, no blocking finding. Applied: a count of more than 4,300 digits ended in a traceback
  (Python refuses `int()` of a longer string) and exit 1; `parse_marks` now refuses more than six digits, and the command-line tests
  now check that a refusal is the program's (`refused:` and no traceback) and not only the parser's; the docstring of `sample` no
  longer says that no second-round item can be drawn. Noted for Increment C and not changed: the content of `inferred` items differs
  from that of `stated` ones (an inferred item has no supporting quote, and its passages may be fewer or poorer), so a labeller may
  judge the two marks differently for a reason that is part of the difference being measured, and the Result of C must say so among
  the limits; and Increment C must send `items.json` (or `calibration.json`) only and never the folder, which holds the key. It could not
  run anything or compare the trace with the old code.

### Increment C — Label the sample (run, 2026-11-10)

- **The send, and the owner's word.** The sample was drawn first, and the owner was told, before anything left the machine: 120 items,
  30 in each cell of mark and field; `items.json` of 325,032 bytes (about 80,000 tokens) holding the item text, the book title, an opaque
  book id, the field and up to five passages of the book (536 passages), plus the rubric; the 75 titles all public (51 Wikipedia pages,
  22 papers, and the FreeCAD and Python documentation); that the key never leaves the machine and that only a copy of
  `items.json` in a folder of its own would be given to the labellers; and that the labellers are three strong-model subagents of this
  session, the provider that runs the session. The owner said yes. The calibration subset (15 items, `calibration.json`) was not
  labelled by the owner and is not needed; it stays in the sample folder for the owner to label.
- **Provenance.** `python3 -m kb card-sample ~/.local/share/knowledge-base/trial/inferred-sample --field topics --field key_ideas --marks
  inferred=60 stated=60 --seed 20261110 --calibration 15` at commit `475cba5`, on the library of 110 books and 109 cards; SHA-256 of
  `items.json` `0dbf9c66d1b496ae40a0471471771232f56d3900fec1d61b9d29fca0f929fb02`. The marks come from the newest card of each of 75 books
  (generations 1 to 4 and 6), 30 in each cell. In the file the marks run in a mixed order along the ids, and
  `items.json` holds none of the fields of the key. Labellers: three subagents with the model `claude-opus-5-5` (from the transcripts),
  launched in parallel with the same neutral brief that named neither the marks nor the aim and gave only the path of the staged copy
  (SHA-256 checked equal) and the rubric. The transcripts show that each made only `Read` calls of that one file (8, 6 and 6 calls, in
  parts) and the final hand-back, and no other tool and no other path. Each returned all 120 ids with a label and a note; the files
  were assembled from the returned JSON by script and accepted by the engine's loader (`labelled-labeller-N.json` in the sample folder).
  `python3 -m kb card-accuracy LABELLED KEY --by-mark` for each, and `card-agreement` for each pair.
- **Agreement.** The three labellers agree closely: 115 of 120 (95.8 percent), 117 of 120 (97.5) and 118 of 120 (98.3) for the three
  pairs, and all three give the same label to 115 items. They give `unsupported` to the same 16 items, 4 of which are items for which no
  passage was found. The five split items are all key ideas and every split is between `supported` and `inference`.
- **The labels by mark** (shares of the items not skipped; no item was skipped; labeller 1 / 2 / 3):

  | | items | supported | inference | unsupported |
  |---|---|---|---|---|
  | `inferred`, all | 60 | 45 / 48 / 47 (75.0 / 80.0 / 78.3 percent) | 5 / 2 / 3 | 10 / 10 / 10 (16.7 percent) |
  | `stated`, all | 60 | 50 / 50 / 49 (83.3 / 83.3 / 81.7 percent) | 4 / 4 / 5 | 6 / 6 / 6 (10.0 percent) |
  | `inferred` topics | 30 | 27 / 27 / 27 (90.0 percent) | 0 | 3 (10.0 percent) |
  | `stated` topics | 30 | 28 / 28 / 28 (93.3 percent) | 0 | 2 (6.7 percent) |
  | `inferred` key ideas | 30 | 18 / 21 / 20 (60.0 / 70.0 / 66.7 percent) | 5 / 2 / 3 | 7 (23.3 percent) |
  | `stated` key ideas | 30 | 22 / 22 / 21 (73.3 / 73.3 / 70.0 percent) | 4 / 4 / 5 | 4 (13.3 percent) |

- **What the numbers show, and do not.** Topics and key ideas marked `inferred` are judged supported by the passages shown about three
  times in four (75 to 80 percent, and 83.3 percent counting `inference`), against 82 to 83 percent (90.0 percent with `inference`) for
  those marked `stated`. The point estimates favour `stated` by 3 to 8 points of `supported` and by 6.7 points of `unsupported`
  (10 of 60 against 6 of 60), but at 60 items a side the difference is within chance: Fisher's exact test, two-sided, gives p = 0.42 for
  the `unsupported` counts, 0.55 when the 4 items without passages (3 `inferred`, 1 `stated`) are left out, 0.37, 0.81 and 0.82 for the
  strict `supported` counts of the three labellers, and 0.51 for key ideas alone (7 of 30 against 4 of 30). The sample cannot tell
  these two marks apart on topics and key ideas; it does not show that they are the same. The weak spot of both is the key idea
  (60 to 73 percent supported against 90 to 93 percent for topics); the items judged `unsupported` are mostly a detail the passages do
  not state (a named condition, a term such as FFT or POMDP that no shown passage mentions). **This is for topics and key ideas only.**
  Caveats and limits, most of which are `inferred` (83 and 80 percent of them), are not in the sample, and the earlier finding that
  2 of 13 `inferred` items were supported (`2026-11-07-card-grounding`) was mostly about caveats and limits.
- **Limits.** (1) A labeller sees only the five best passages; an item supported elsewhere in the book is counted `unsupported`, so
  every share is a lower bound for support, for both marks alike. (2) Three labellers of one model: their agreement shows that they
  read the rubric alike, not that they are right; the owner's labels of the calibration subset would test that and have not been given.
  (3) A cell of 30 items has an interval of about plus or minus 17 points. (4) The content of the two marks differs: an `inferred` item
  has no supporting quote behind it, and 3 of the 4 items with no passages are `inferred`, which the labellers had to call
  `unsupported`; part of the gap is the method, not the items. (5) The cards were made over several days with different prompts
  (generations 1 to 4 and 6); the sample is the newest card of each book, not a controlled comparison of one prompt, and the form and
  model of each card were not examined. (6) These are shares of items in the
  sample, not the accuracy of the cards as a whole.
- **Verification as run.** The counts above are those of `card-accuracy` and `card-agreement`; the 120 labelled items of each file
  were accepted by the loader (no unlabelled item, no `inference` without a note); the totals add up to 120 for every labeller and
  mark; the transcripts were checked for the tool calls. No tracked code was changed by this increment.

### Increment D — The numbers, the options and the decision (2026-11-10)

- **Put to the owner.** The counts (`card-marks`, Increment A): in the newest card of each version, 209 topics and key ideas are marked
  `inferred` (196 on 96 cards of the earlier form, 13 on 10 cards of the sentence form), against 1,167 `stated` (1,025 and 142); caveats
  and limits are mostly `inferred` (83 and 80 percent in the earlier form) and are not part of this decision. The labels (Increment C):
  of 60 `inferred` and 60 `stated` topics and key ideas, three labellers judged 75 to 80 percent of the `inferred` and 82 to 83 percent of
  the `stated` supported by the passages shown (83.3 and 90.0 percent counting `inference`), with 16.7 and 10.0 percent `unsupported`,
  a difference within chance at this size (p = 0.42 and up); topics 90 to 93 percent supported for both marks, key ideas 60 to 73 percent.
- **The options and what each would do to today's library.** (a) Drop the `inferred` topics and key ideas when a card is made: the
  209 items would go, about three quarters of which held up against the passages. (b) Keep them on the card and leave them out of the
  keyword index (`cards_fts`): the same 209 items could no longer be found by their words. (c) Keep and index them and show the mark with
  the item, as `card-show` does now: no change to any card, the catalog or the vectors.
- **The recommendation** was (c), for the reasons above: most of the `inferred` items are good, the labelling found no difference from the
  `stated` ones that the sample can detect, and (a) and (b) would discard or hide them. Two cautions were given with it: caveats and
  limits are not covered by these figures, and the three labellers are of one model family, so the owner's labels of the calibration
  subset (not given) would be the test of how far they are right.
- **The owner's decision (2026-11-10): (c), on that recommendation** ("go with your recommendation"). The `inferred` topics and key ideas
  stay on the cards, stay in the keyword index, and are shown with their mark by `card-show`. Nothing in the cards, the catalog, the
  vectors or the display is changed by this decision.
- **What the decision leaves open.** (1) A search result today gives the counts of `stated` and `inferred` items of a card (`grounding`),
  not the mark of each item it finds; whether a result should carry the mark of the item that matched is the one point of (c) ("show the
  mark with the item") that `card-show` meets and a search result does not. It was not decided here. If the owner wants it, it is a
  small plan of its own; if not, the candidate's second half is already true. (2) Caveats and limits, and how they should be written
  when a quote cannot state them, remain outside this plan (the other half of the boundary of the candidate). (3) The roadmap is not
  changed by this plan: `cards#card-inferred-items` stays as written, and whether to close or reword it is the owner's decision
  (a change of direction), not made here. (4) The labellers' files stay in `~/.local/share/knowledge-base/trial/inferred-sample/`
  (outside the repository) with the key; the calibration subset is unlabelled; the staged copy for the labellers is in
  `inferred-sample-for-labellers/`.
- **Criteria.** 1 (`card-marks`), 2 (`card-sample --marks` and `card-accuracy --by-mark`), 3 (a labelled sample of 60 and 60 with 30 in each
  cell, with the figures and their limits) and 4 (the numbers and the options put, the decision recorded, and the candidate named as not
  complete with its open point) are met. 5: the card test modules (939 tests) pass and `wb run code-work check` finds no problems, both
  run at the end of the plan, and `card-marks` run again gives the counts written in the plan and in the Result of A.
