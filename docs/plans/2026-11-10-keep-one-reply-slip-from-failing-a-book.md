# Keep one reply slip from failing a book

Status: Proposed
Created: 2026-11-10
Candidate: cards#card-format-resilience
Specs: docs/specs/card.md

## Goal

A book is carded unless the card model's answer is wrong in substance. Today a card model that writes a list and its support list at
different lengths, or a note point a little too long, fails the call, and a book fails when two tries in a row do. When the plan is done:
a refused answer of the card, notes or second-round call is asked for once more with the reason, the support of a topic or a key idea in
the earlier form of the card is written inside the item it belongs to so that two lists of different lengths cannot be written, a note
point may be longer, and Newsvendor model (the one book of the 30 added on 2026-11-10 that failed twice) has a card in the earlier form.

## Scope

- A retry in the card call: a call whose answer is refused for its shape is made once more with the same prompt and the reason in a
  marked section of data; both refusals are kept aside as refusals are now; the call fails only if the second answer is refused too.
- The earlier form of the card call asks for the topics, key ideas and caveats, and the second round (which serves only the topics and
  key ideas, `MORE_FIELDS`) asks for those two, as items that each hold their support (`text` and `support`); the rest of the card code
  receives the same values as before (a list and its support list).
- The note point limit raised from 240 to 300 characters (the shape accepts a longer point than the 240 the prompt asks for and the
  notes count, as it already accepts a quote up to 600).
- One live run that makes the card of Newsvendor model again in the earlier form, on the owner's word.

## Non-goals

- A change of model, of what counts as support, of the checks, of the grounding, or of the marks on a card.
- The sentence form: its shape (three lists of the same length) is not changed; it gets the retry only, because the retry is made in the
  one place that asks every call. Fourteen of the 58 refusals kept so far belong to the sentence form, which is no longer the default.
- The note's two lists (`points` and `quotes`, three refusals in three books): left as they are, listed under Deferred work.
- A measure of the rate of refusals on a new batch of books, and a measure of whether the new shape changes what the cards hold beyond
  the one book of Increment D: see Deferred work.
- Making the 30 books' cards again, or any other book's card.

## Assumptions and constraints

- **The evidence.** 58 refused answers are kept aside in the index root, from 2026-11-08 to 2026-11-10 (counted from their reasons, with
  no book text read, on 2026-11-10 at commit `fd32d64`): 37 in 28 books are a list and its support list of different lengths (topics,
  key ideas or caveats); 14 in 12 books belong to the sentence form (its three lists, or an `inferred` support where a note is needed);
  3 in 3 books are the note's `points` and `quotes` of different lengths; 2 are a note point over 240 characters; 1 is more note points
  than the 6 allowed; 1 is a support list over its limit. The earlier-form run of 2026-11-10 (30 books, 201 calls) had 9 refusals, all
  of the first kind; the queue's second pass made 8 of those cards and Newsvendor model failed twice. Earlier runs record 13 of 65
  books needing a second attempt and 2 failing both times, and that the same two books were carded at the first attempt when tried
  again, so the slip is intermittent.
- A refused answer is untrusted data. The reason in a retry is the engine's own refusal text, which names the key and the kind of fault
  and may quote up to 40 cleaned characters of the answer for a support value; it goes into the retry as a marked section of data, with
  the same random markers as every other section, and the prompt says it is data and not an instruction.
- The queue's own retry stays: a book that fails in one pass is tried again in the next, and is reported failed after one more try. The
  retry of this plan is within a call and costs one more call only when an answer is refused.
- The values the card code receives do not change (`topics` and `topics_support` as two lists), so `pairs`, `ground`, the checks, the
  journal's saved values and `card.py` are untouched. If the earlier form cannot be changed without changing how the checks or the
  grounding work, Increment B stops and reports.
- A new prompt version makes a journal of the old version stale for the new one (the prompt version is in the journal header), as it
  should; no run is in progress.
- The card call uses a JSON schema file for structured output on the owner's server. Whether the server accepts the nested schema of
  Increment B is not known until a live call; Increment D finds out, and stops and reports if it does not.
- Book text, notes and items go only to the models the config names, on the owner's server, over plain HTTP; the live run says so
  and waits for the owner's word. The increments before it make no call.

## Completion criteria

1. A call of the card job whose answer is refused is made once more with the reason; the call fails only if the second answer is
   refused too; both refusals are kept aside; only an accepted answer is saved in a journal; a call that was not refused is made once.
2. In the earlier form the reply holds each topic, key idea and caveat with its support, and in the second round each topic and key
   idea; a reply of the old shape is refused, and a card made from the same content in the two shapes has the same stored values (same
   grounding, same marks).
3. A note point of 300 characters is accepted and one of 301 is refused; the prompt still asks for points of at most 240.
4. Newsvendor model has a card in the earlier form as its newest generation, or the Result gives the reason it has none; the other
   109 cards are unchanged.
5. The card tests pass, the sentence form's tests pass as they are, and `wb run code-work check` finds no problems.

## Increments

### Increment A — Ask again once, with the reason

**Outcome:** `cardmake.make_model_part` asks a call again once, with the reason in a marked section, when its answer is refused for
its shape; the first refusal is kept aside; the call fails only if the second answer is refused too.
**Dependencies:** none.
**Affected areas:** `engine/kb/cardmake.py` (the function that asks each call, a retry prompt, the part's account of the refusals it
kept), `engine/kb/cardqueue.py` and `cardmake.run` only to keep the first refusals aside, `engine/tests/test_cardmake.py`,
`engine/tests/test_cardmake_earlier.py`, `engine/tests/test_cardqueue.py`.
**Steps:**
1. Read how `ask` in `make_model_part` records a call (records, the journal, `Pause`, `JournalFault`), how a refusal reaches `keep_aside`,
   and how the queue turns it into a pass-level retry. Write down where the first refusal can be kept aside without the part knowing the
   store.
2. Write the tests first, with a fake launcher: a refused answer followed by a good one makes the card in one more call, and the
   second prompt holds the reason in a marked section and the first prompt unchanged; two refused answers fail the call, with both
   kept aside; a good answer makes one call; the saved journal holds the good answer and never the refused one; a failed call (not
   a refused answer) is not asked again; a retry is made for the notes call, the card call, the second round and the check call alike;
   a resumed card does not ask again for a call that is in its journal; a hostile reply text (control characters, a marker, a long
   value) is cleaned and bounded in the retry prompt. See each new test fail for the right reason.
3. Add the retry. The retry prompt is the original prompt and one more section with the reason, labelled as the engine's note on
   the last answer and as data.
4. Deliberate breaks, each from green: the retry made twice, the retry made without the reason, the reason outside a marked section,
   the first refusal not kept, the refused answer saved in the journal, a failed call asked again, the retry skipped for one job.
5. The independent `reviewer` agent.
6. **Checkpoint, after the review and before the commit.** This increment feeds text derived from a model's answer into the next prompt
   to a model. Name this to the owner and ask once whether to run a security review with the installed module on this surface; record
   the answer in the Result. A review runs only if the owner asks.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_cardmake_earlier
engine.tests.test_cardqueue engine.tests.test_cardstate engine.tests.test_card` and `wb run code-work check`. No call is made to the
owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-keep-one-reply-slip-from-failing-a-book#A`.

### Increment B — The support written with its item

**Outcome:** the earlier form of the card call asks for each topic, key idea and caveat, and the second round for each topic and key
idea, with its support in one object, and the card code receives the same two lists as before.
**Dependencies:** A.
**Affected areas:** `engine/kb/models.py` (a shape type for a list of items that each hold a text and a support, and the reading of
it), `engine/kb/cardmake.py` (the earlier job, the second-round job, their prompts and prompt versions), `engine/kb/schemas/card-earlier.json`
and the schema of the second round, `engine/tests/test_models.py`, `engine/tests/test_cardmake_earlier.py`, `engine/tests/test_cardmake.py`,
`engine/README.md`.
**Steps:**
1. Read `models._check_answer`, `_value`, the shapes of the earlier job and of `MORE_JOB`, `_recheck` and the schema files, and write
   down what must stay the same for the code that receives the values. If the change cannot be made without changing how the checks
   or the grounding work, stop and report.
2. Write the tests first: a reply with each item holding its text and support is read into the same two lists as the old shape gave;
   a reply of the old shape is refused with a plain reason; an item without a support, with a support over its limit, with a key it
   was not asked for, or that is not an object, is refused; a list over the number asked for is refused as now; the card made from
   the same content in the two shapes has equal stored values, grounding and marks; the second round likewise; a saved journal answer
   is checked again in the stored form; other jobs (the notes, the check, the sentence form) are unchanged. See them fail.
3. Add the shape type to `models.py` and use it for the topics, key ideas and caveats of the earlier job and for the topics and key
   ideas of the second round (it has no caveats; its schema and tests are for those two); write their prompts; raise the prompt versions; change the two schema files. The sentence form keeps its job and schema.
4. Deliberate breaks, each from green: a support dropped from an item and read as none, supports and texts paired out of order, the
   old shape still accepted, the number of items unchecked, the stored lists built with different lengths, the sentence form moved to
   the new shape, a text left uncleaned.
5. The independent `reviewer` agent.
6. **Checkpoint, after the review and before the commit.** This increment adds a reader for a nested reply of a model. Ask the
   owner once whether to run a security review with the installed module on this surface; record the answer in the Result.
**Verification:** the same test modules as A with `engine.tests.test_models` and `engine.tests.test_catalog`, and `wb run code-work
check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — A note point may be longer

**Outcome:** the notes shape accepts a point of up to 300 characters, though the prompt still asks for at most 240 and the notes count
240, as it already accepts a quote up to 600. The two points that were refused so far were 246 and 249 characters long, so 300
leaves a margin without a large prompt.
**Dependencies:** none (it can follow A or B).
**Affected areas:** `engine/kb/cardmake.py` (the notes shape, the notes prompt version), `engine/tests/test_cardmake.py`,
`engine/tests/test_cardmake_earlier.py`.
**Steps:**
1. Read how a point is counted, cut and put into the card prompt. Work out the largest card prompt at the new limit: at 20 pieces and
   6 points of 300 characters the notes are about 40 KB, against the 32 KB at 240 that the comment on `MAX_CARD_PIECES` records, and at
   the default 12 pieces about 22 KB. Compare with the window of the model the config names for the card. If the worst case no longer
   fits, stop and report; do not lower the pieces limit in this plan.
2. Write the tests first: a point of 300 characters is accepted and one of 301 is refused; the prompt still asks for points of at
   most 240; a point of 241 to 300 characters is kept whole as the model wrote it; the prompt version is raised. See them fail.
3. Raise the limit to 300 and the notes prompt version.
4. Deliberate breaks, each from green: the old limit kept, no limit, a limit of 301 or 299, the prompt version not raised, a point cut
   instead of refused.
5. The independent `reviewer` agent.
**Verification:** the same test modules as A and `wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `...#C`.

### Increment D — Card Newsvendor model again

**Outcome:** Newsvendor model has a card in the earlier form as its newest generation (generation 2), or the Result gives the reason.
**Dependencies:** A, B, C.
**Affected areas:** the card of one book (a new generation) and the refused answers, if any, in the index root; this plan's Result. No
tracked code.
**Steps:**
1. Run `python3 -m kb cards-queue plan --form earlier --again --book 01M72S10KDCX8GDV97FQE7Z18Q`; it makes no call. Show the owner the
   number of books, the form, the models and the calls that can be counted, say that the text of this page goes to the models on
   `ned` in the clear, and wait for a yes.
2. Run `python3 -m kb cards-queue run RUN`. Record the time, the calls, whether any answer was refused and kept aside (the files
   in the index root) and whether the retry was used, and, if the server refused the nested schema, stop and report.
3. Check that the card is generation 2, read it with `card-show`, that the other 109 cards are unchanged (the counts of the
   catalog), and run `card-index` and `card-vectors` only if the owner says so (the card's text is then sent to the embedding model).
**Verification:** `cards-queue status RUN`; the catalog counts; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the card test modules once
and `wb run code-work check`. A wider run is not named. What could break outside what is tested is the prompt of the earlier form, which
the 29 cards made on 2026-11-10 were not made with: they stay as they are, and a book carded again will be made with the new prompt.

## Risks and sensitive actions

- **A model's text goes into the next prompt.** The retry puts the engine's refusal text, which can quote up to 40 cleaned characters
  of an answer, into a marked section of data. Increment A asks the owner about a security review before it is committed.
- **A reader for a nested reply.** Increment B adds it; it asks the owner once more, on its own surface.
- **A prompt that changes.** The earlier form's prompt changes shape, so cards made after this plan may hold a different number of
  items than those before. One card is made in Increment D; whether the change matters is Deferred work.
- **A schema the server may not take.** Increment D finds out with one book and stops if the server refuses the nested schema.
- **Text sent out.** One page's text goes to the owner's models in the clear on the owner's server, said before the run.
- **Two cards for a book.** The catalog holds the newest; Newsvendor model's sentence-form card stays as generation 1. Nothing is deleted.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, two findings (both major), both applied:

- **R1-F1, applied.** The plan said the second round would take topics, key ideas and caveats as item and support objects. The second
  round serves only the topics and key ideas (`MORE_FIELDS`), and its schema has no caveats. The scope, criterion 2 and Increment B now
  say that the earlier card reply changes three fields and the second-round reply two.
- **R1-F2, applied.** The new note point limit was never named. It is 300 characters (the prompt still asks for at most 240 and the notes
  still count 240), chosen because the two refused points so far were 246 and 249 characters long. Increment C uses the number in its
  outcome, tests and breaks, and has a step that works out the worst-case card prompt at 20 pieces and stops if it no longer fits.

A second round has not been asked for.

## Deferred work

- The note's `points` and `quotes` written as pairs, as the support is in Increment B (three refusals in three books so far).
- The same change for the sentence form's three lists, if the owner ever makes it the default again (fourteen refusals in twelve books).
- A measure of the rate of refusals and of the retry on a fresh batch of books, and of whether the new shape changes what a card holds
  (the number of topics and key ideas, the marks), when the next batch is carded.
- `cards#card-inferred-items`, the decision on items the model only infers, which the numbers of the card-form plan bear on
  (141 inferred items in 29 earlier-form cards against 85 in 27 sentence-form cards).

## Result

### Increment A — Ask again once, with the reason

- **Done.** In `engine/kb/cardmake.py`, the function that asks each call inside `make_model_part` asks a call once more when its answer is
  refused for its shape (`models.AnswerRefused`): the same prompt and one more section, `LAST REFUSAL` (`retry_prompt`), that holds the
  program's note on the fault, written in ASCII only (other characters as escapes), cleaned and cut at 300 characters (`MAX_REASON`), marked
  with a token that neither the prompt nor the note holds, and said to be data. The first refusal is given to a new parameter
  `on_refused`; `make_for_version` and the queue's `_serve` pass a callback that calls `keep_aside`, so both answers are kept aside. A
  second refusal is raised as before; a call that failed (a plain `KbError`) is not asked again. Only the accepted answer gets a record and
  a journal entry, so `calls` counts the accepted calls and the records stay aligned with the journal. It applies to the notes, card, check
  and second-round calls, in both forms.
- **Deviations.** (1) The plan's "the part's account of the refusals it kept" is a callback (`on_refused`), not a field of the part, so
  that the part need not know the store. (2) `engine/README.md` and the `calls_note` text of `cardqueue.plan` are changed though A's
  Affected areas do not list them: the README said that a refused answer fails the call at once and is tried again in the next pass, which
  is no longer true, and the note on calls now says any call can be made twice. (3) Eight older tests that assumed a refusal fails the
  call at once were changed to the new behaviour and keep their purpose: a note of the wrong shape still stops the card (now after two
  askings, two calls); a failed card keeps two refused answers (one for each asking); in the queue a single refusal is absorbed in the same
  pass and a book refused twice is tried again in the next pass (four askings in all before it is reported failed). (4) An error in the
  callback is ignored, so that keeping an answer aside cannot stop the retry or hide the refusal (the reviewer's finding 1).
- **Cost.** Every call of a card (a notes call for each piece, the card, each batch of checks, the second round and its checks) can now be
  asked twice, and in the queue a book refused twice in a pass is asked again in the next pass: up to four askings at the failing call and
  up to four files in `refused/` (it keeps at most 200). A card that is not refused costs what it did. Increment D must say this when it
  asks the owner for the live run.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_cardmake_earlier`, `test_cardmake`, `test_card`,
  `test_cardstate`, `test_cardqueue`, `test_cardsample`, `test_catalog`: 725 tests, OK; `wb run code-work check`: no problems. The new
  tests were seen to fail first (a TypeError for the missing `on_refused`, and for the two later ones the callback's error and a
  non-ASCII body). 21 distinct deliberate breaks, each from green (the retry made twice, without the reason, with the reason outside a
  marked section, uncleaned, uncut, with a token the reason or the prompt holds, escapes removed, the first refusal not kept by the
  command or by the queue, the refused answer saved in the journal, a failed call asked again, the retry skipped for each of the four
  jobs, the end line of the prompt lost, the callback's error not contained) were each caught; eight were first missed or were invalid
  edits (four of the retry skipped for a job had a syntax error and were done again), and tests were added (direct tests of `retry_prompt` with a hostile reason, a prompt that holds a token, and a prompt with no
  usual end). No call was made to a model server.
- **Review.** Independent `reviewer`, one exchange, no blocking finding. Applied: the callback's error contained (finding 1); the
  reason written in ASCII only, which closes the route by which an unknown key of the answer is quoted with characters outside ASCII
  (finding 2, a surface the plan had not named: `models._check_answer` quotes a cleaned unknown key, `parse_support` and the verdict check
  quote up to 40 and 20 characters); the README and `calls_note` brought up to date (finding 3). The cost (finding 4) is recorded above.
  Not done: a test of `Pause` with a retry (the retry uses an entry that has already passed the `allow` check; the reviewer found the
  logic clear by reading). The reviewer could not run anything or read the diff of the older tests; I judged those changes myself.
- **Security review checkpoint.** Asked once, about feeding text derived from a model's answer into the next prompt. I recommended no
  review for this increment: the text goes only to the model that wrote the answer, is at most 300 ASCII characters in a marked data
  section, and the next answer passes the same checks as any other, so no new privileged use is reached; the reviewer rated the
  exposure low and its one unnamed route was closed. The owner took the recommendation (2026-11-10): no security review; none was run.
  The question is asked again in Increment B, which adds a reader for a nested reply.
