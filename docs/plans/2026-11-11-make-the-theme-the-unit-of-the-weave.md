# Make the theme the unit of the weave

Status: Proposed
Created: 2026-11-11
Candidate: theme-weave#theme-unit
Specs: theme, card, book, models

## Goal

Each book of the library gets themes: idea-level pieces of what the book says, each with a description in words of no field, an
anchor that points back to the exact text, and a mark of what the text states and what a model infers. They are made by the models of
the owner's config, are kept in the book's own folder as a generation that is never overwritten, and are checked so that a theme
cannot cite text that is not there. When the plan is done the engine can make the themes of a book, the owner has read a sample from
real books and decided whether the method is good enough to run over the library, and, only if the owner says so, the library has them.

The reason is the purpose in `2026-11-11-the-library-equips-a-research-agent-to-extrapolate`: the weave links themes, and a walk from
one to a distant one needs a unit finer than a book and a description of it that does not use its field's words. Today the field-free
description is a single set of strings on the book, and the key ideas of a card are three to five short sentences in the book's own
terms with no anchor.

## Scope

- The format of a theme and of a generation of themes, their check, and where they are kept (`theme.md`, "What a theme holds",
  "Storage", "Stability").
- Finding the anchor: the model names the section or paragraph a theme comes from, and code finds the exact span with the locator of
  the engine and records the hash of the excerpt.
- The extraction of themes from a converted book, piece by piece, with the model of a new kind of work in the config, the merge of
  near-duplicates in a book, the skipping of proofs and local definitions, and a bound that catches a runaway.
- A check of each description in words of no field: that it does not use the field's vocabulary, and which of its parts the excerpt
  supports (the mark of stated or inferred).
- A trial on a few books the owner chooses, a report, and the owner's decision.
- If the owner decides so, a run over the library with a report.

## Non-goals

- Vectors for themes, links between themes and the walk (`theme-weave#theme-vectors`, `#theme-links`, `#theme-walk`).
- Changing a card, its key ideas or how cards are made or searched.
- Searching the themes in any way. Reading a theme is by its file and the anchor only.
- Judging whether a theme is novel, or any measure of novelty.
- Writing the owner's config: the owner adds the new kind of work to it.

## Assumptions and constraints

- **My call, not yet the owner's:** the themes are made as `theme.md` designs them, from the text of the book, and are not the key ideas
  of the cards promoted. The reasons are that a card keeps three to five key ideas made from at most the notes of the pieces read (a
  long book is sampled), where the throwaway experiments of `theme.md` found about ten themes a paper with 98.6 percent of anchors
  valid; that a key idea has no anchor; and that a walk between themes needs many more nodes than five a book. The plan is changed if
  the owner decides otherwise.
- The anchor is a locator (`engine/kb/locator.py`): the kind (section, page or offset) and the place, with the hash of the first twelve
  words of the excerpt, found again by those words if the conversion changes. The model does not quote its own start and end; the
  experiments found that failed for 44 percent of the themes.
- **The form of a theme (my proposal, settled here so that the tests can be written; the owner may change a limit).** A theme holds:

  | field | form |
  |---|---|
  | `id` | text, unique within a generation |
  | `book_id`, `version_id` | as the book has them |
  | `conversion` | the tool, its version and its generation, as the locator names them |
  | `anchor` | one contiguous span of the converted text, held as: `start` and `end`, each a locator (kind `section`, `page` or `offset`, the place, and the hash of the first twelve words at that place), the heading path, and `excerpt_sha256`, the hash of the whole excerpt (its words, lower-cased, without punctuation, joined by single spaces), which is 1 to 6,000 characters |
  | `title` | text, 1 to 120 characters |
  | `type` | one of `problem`, `method`, `finding`, `concept`, `other`; a theme without a clear type is `other` and is kept |
  | `summary` | the source's own words, 1 to 600 characters |
  | `neutral` | five parts, `problem`, `method`, `needs`, `provides`, `limits`, each 0 to 300 characters in words of no field (empty when the excerpt says nothing of that part), and a mark for each non-empty part, `stated` or `inferred` |
  | `confidence` | a number from 0 to 1 |
  | `made` | the model, the prompt version and the date |
  | `flags` | a list of departures found by the checks of Increment D (for example the field's words found in the description), empty if none |

  A key that is not in the table, a field of another type, a text over its limit or a part with a mark and no text, is malformed.
- A model's reply is untrusted data. A book's text is given to the model in a section of its own between delimiters made for the call,
  as `cardmake.py` does, and the reply is checked for shape before anything is stored. A theme is stored and shown as untrusted.
- The engine attaches no model to any kind of work: `models.TASKS` names the kinds and the owner's `tasks` setting names the model.
  A new kind (or two) is added to the engine and the owner adds it to the config. Until then the run is refused, as for other kinds.
- A theme belongs to one version of one book and to one generation. A new generation never overwrites an earlier one. As for cards
  (`card.py`), the active generation is the newest one that passes its check, and a generation can be read by its number.
  `theme.md` also says an earlier generation can be restored as the active one; this plan does not build that (see Deferred work), and
  the two statements are reconciled when `theme.md` is next revised.
- **Themes are extracted after the card, as `theme.md` says.** A book needs a current card and a conversion. **Pointer-only books are out of this plan:** `theme.md` says
  they would get themes from their captured snapshot, marked partial, but the engine has no pointer-only book and no code that makes
  one (a search of `engine/kb/` for the kind finds none), so there is nothing to extract from; the run report lists every book that has
  no conversion with that reason, and the case is left to the plan that adds pointer books. The card is also the
  source of the field's vocabulary that the check of Increment D uses. A book with a conversion and no card is not given themes and is
  reported with that reason.
- The number of themes in a book is not targeted. A bound catches a runaway only and is never a target (`theme.md`).
- Book text is sent to the models the owner's config names, as for cards: today the owner's server over plain HTTP. Each live run is
  said to the owner beforehand and waits for the word.
- The library holds 176 books, 175 with a card, from a few fields; the owner's choice of books for the trial is the owner's.

## Completion criteria

1. A theme of the specified form is accepted by a check and every departure is refused: a false anchor, an excerpt that is not at the
   anchor, a hash that does not match, a field of the wrong type or length, an unknown key.
2. Themes are filed as the next generation of a version of a book and read back checked against their hashes, filing never changes
   an earlier generation, and reading without a number returns the newest generation that passes its check.
3. For a book, the extraction makes themes whose anchors the code has found and checked, merges near-duplicates, skips proofs, and
   stops at the bound with the output kept aside. A reply that is not in the shape asked for makes no theme and is kept for reading.
4. Each description in words of no field is checked against the vocabulary of the book's field (the words defined in Increment D) and
   for support in the excerpt, and each part is marked stated or inferred; a part with no support is not kept as stated. A description
   that holds a word of the field's vocabulary is kept, flagged, and counted in the report.
5. A trial on the owner's chosen books produces a report of the numbers named in Increment E, outside the repository, and the owner
   has read a sample of the themes and decided whether to run over the library, change the method or stop.
6. If the owner decides to run, every book that has a conversion and a current card has a generation of themes or a stated reason why
   not, and every book with a conversion and no card, and every book with no conversion, is listed with that reason; the report says which.

## Increments

### Increment A — The theme and its generation: form, check and keeping

**Outcome:** the engine can file a generation of themes for a version of a book, read it back checked, and refuse every malformed
theme. No model is used.
**Dependencies:** none.
**Affected areas:** a new module under `engine/kb/` for the theme (form, check, filing and reading); a new test module; the engine
README. The card's code is read, and reused where its way of keeping generations and hashes fits, and is not changed.
**Steps:**
1. Read `theme.md`, the way `card.py` files and reads generations (`generations`, `read`, the hashes), `book.md` on where model output
   lives, and `locator.py`. Write down in the Result what is reused.
2. Write the tests first and see them fail: a valid theme and generation are accepted; each departure of criterion 1 is refused; a
   second filing makes generation 2 and leaves generation 1 byte for byte; a generation changed on disk is refused when read.
3. Write the module: the fields of a theme as the table of the assumptions gives them, their limits, the check, and filing and
   reading, with the newest generation that passes its check as the one read without a number. The tests enumerate that table: one
   test for each field and each limit, for a wrong type, for an unknown key, and for a part with a mark and no text.
4. Run the tests and break the code on purpose in the ways the tests name (a check removed, a generation overwritten, a hash not
   compared), seeing a test fail each time; restore each.
**Verification:** the new test module and `engine.tests.test_card` (the shared way of keeping generations), and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#A`.

### Increment B — Finding the anchor of a theme in the book

**Outcome:** given a conversion and a pointer to a section or paragraph, code finds the exact span of text, records the locator and the
hash of the excerpt, and refuses a pointer that does not hold. No model is used.
**Dependencies:** A.
**Affected areas:** the theme module; the tests; `locator.py` is used and not changed.
**Steps:**
1. Read how a conversion is split into blocks and sections (`convert.py`, `read.py`) and write the shapes of pointer the model can name
   (a heading path and a paragraph number, a page and a block, an offset range for a flat text) in the Result.
2. Tests first, seen failing: a pointer to a real paragraph gives the span with its `start` and `end` locators, its heading path and
   the hash of the whole excerpt; a pointer to nothing, to a heading with no such paragraph, to a span beyond the text, with a wrong
   kind, or to an excerpt over 6,000 characters is refused; the stored excerpt hash is checked against the text found at the anchor and
   a mismatch is refused; a conversion that shifts blocks finds the same excerpt again by the locators, and is accepted only if the
   hash of the whole excerpt found equals the stored one, and flagged as not found otherwise.
3. Write the function and run the tests; break the code on purpose in the ways named and restore each.
**Verification:** the new tests, `engine.tests.test_locator` if it exists or the nearest tests of the locator, `test_read`, and the
code check.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#B`.

### Increment C — The extraction job

**Outcome:** the engine makes the themes of one book that has a current card, with a model, from the converted text, piece by piece,
and refuses a book that has no card. It returns themes whose
anchors are checked, with the reasons for any it drops; nothing is filed by this step except through the filing of A. A fake bridge is
used in the tests; no live model call is made.
**Dependencies:** A and B.
**Affected areas:** a new module for the job and its prompt and schema (`engine/kb/schemas/`); `models.py` (a new kind or kinds of work
in `TASKS`, left unset by default, and the tests of the registry); the tests; the engine README.
**Steps:**
1. Read `cardmake.py` (pieces, the delimiters that hold a random token, the schema, the handling of a refused reply and of partial
   books) and reuse its shape.
2. Tests first, seen failing, with the fake bridge: a reply with themes gives themes with anchors found by code; a theme whose pointer
   does not hold is dropped with its reason; two near-identical themes of one book are merged; a theme the prompt should skip (a proof, a
   local definition) is dropped when the reply marks its type so; a reply over the bound makes no theme, keeps the output aside and
   says "runaway"; a reply that is not valid makes no theme and is kept for reading; the text of the book is in a section of its own
   between delimiters and never in the rules; the new kind of work is refused when the config does not name a model for it; a book with no current card is refused.
3. Write the prompt, the schema and the job; add the kind of work to `models.py`; run the tests; break the code on purpose in the
   ways named and restore each.
**Verification:** the new tests, `engine.tests.test_models`, `engine.tests.test_cardmake` (the shared prompt and piece handling, if
changed), `engine.tests.test_card`, and the code check. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#C`.

### Increment D — The check of the description in words of no field

**Outcome:** each description in words of no field is checked for the vocabulary of the book's field and for support in the excerpt, and
each part is marked stated or inferred; a part with no support is not kept as stated. A fake bridge is used; no live call.
**The vocabulary of a book's field (my proposal; the constants are proposals the owner may change, and are read in Increment E).**
A word is a run of letters of Unicode (after NFKC normalisation and lower-casing) of 4 or more letters; there is no stemming. Let L be
the books of the library that have a conversion, using the newest conversion of each current version. The document frequency of a
word is the number of books of L whose text holds it. A word is common if its document frequency is at least half of L, and common
words are never in a vocabulary. The vocabulary of a book is the set of: (1) the words of its title; (2) the words of the topics and
the adjacent topics of its current card; and (3) the words that occur at least 5 times in its converted text and whose document
frequency is at most 15 percent of L. Common words are removed from all three. A theme is flagged when its `neutral` text holds a word
of the vocabulary as a whole word; the flag lists the words found. A flagged theme is kept, and the report counts the flagged. The
fixture test builds a library of four small books and asserts the vocabulary this algorithm gives for one of them, word for word.
**Dependencies:** C.
**Affected areas:** the theme job and its checks; the tests; a new kind of work for the check in `models.py` if the check uses a second
model, as `card-check` does for cards.
**Steps:**
1. Read how `cardmarks.py`, `quotes.py` and the grounding of cards decide that a note supports a point and mark it stated or inferred,
   and what the sample of the card marks found (the measured accuracy is in the Results of the card plans). Write down what is reused.
2. Tests first, seen failing: the vocabulary of a book of the four-book fixture comes out word for word as the algorithm above gives
   it, and a description that holds one of those words is flagged with the words found and kept; a part the excerpt supports is marked
   `stated`; a part the check says is partly supported or not supported is kept and marked `inferred` (it is the model's own
   abstraction); a check that gives no valid answer for a theme drops that theme, with the reason `unchecked`, so that no theme with
   an unmarked part is ever filed.
3. Write the checks; run the tests; break the code on purpose in the ways named and restore each.
**Verification:** the new tests, `test_cardmarks` and the tests of what is reused, `test_models`, and the code check. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#D`.

### Increment E — The trial on a few books and the owner's decision

**Outcome:** the owner has a report and has read a sample of real themes, and has decided whether to run over the library, to change
the method, or to stop. The books are the owner's choice, about six, of different lengths and fields.
**Dependencies:** D, and the owner's addition of the new kinds of work to the config.
**Affected areas:** the report file outside the repository; this plan's Result. No tracked code unless a defect is found, which stops the
run.
**Steps:**
1. Say what is sent: the text of the chosen books in pieces, and the excerpts and descriptions of the checks, to the models the owner's
   config names for the new kinds of work (today the owner's server over plain HTTP), and nothing else. Run only on the owner's word.
2. Run the extraction and the checks once for each book and keep the report outside the repository, with its hash.
3. Write into the Result, from the report: for each book the number of themes, themes per thousand tokens, the share whose anchor
   holds, the share dropped and why, near-duplicates merged, runaway hits, the share of descriptions flagged for the field's words, the
   shares marked stated and inferred, and the time taken.
4. Show the owner a sample of the themes with their excerpts (the owner reads them), and what cannot be concluded (a few books, one
   run, the checks made by models). Give a recommendation and record the owner's decision.
**Verification:** the report holds every chosen book and every number named in step 3, the numbers in the Result are the report's, and
`wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#E`, holding the Result and the owner's decision.

### Increment F — The run over the library

**Outcome:** only if the owner decided to run: every book with a conversion and a current card has a generation of themes or a reason why
not, every other book is listed with its reason (no card, no conversion), and a report
says which.
**Dependencies:** E and the owner's word.
**Affected areas:** the library (untracked), a report outside the repository, this plan's Result. The queue of `cardqueue.py` is reused
if it fits, and extended in this increment only if a plan-sized change is not needed; otherwise this increment stops and a plan of its
own is drafted.
**Steps:**
1. Say what is sent and the time it is expected to take, using the rate measured in E, and run only on the owner's word. The run is
   resumable and idempotent: a book whose newest valid generation was made with the prompt version of the code and the models the
   config now names is not made again, and a book whose generation was made otherwise is made again, as a new generation, only if
   the owner's word says so. A book with no card is listed with that reason and given no themes.
2. Run, read the report, and record in the Result the counts and the books that failed with the reasons.
**Verification:** the report holds every book of the library, each with its themes or its reason; the books that failed are listed; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-make-the-theme-the-unit-of-the-weave#F`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the new test modules once
and `wb run code-work check`, and rerun `test_models` and `test_card` if `models.py` or the card code changed after their last run. A
wider run is not named. What could break outside the tested area is `models.py`: the list of kinds of work is read by every model call
and by the config check, so a change to it could refuse a config that was accepted before; the tests of the registry cover that, and
the first live call after the change is the one in E.

## Risks and sensitive actions

- **Book text goes to models.** The text of the books chosen for the trial, and later of the library, goes to the models the owner's
  config names, in the clear over the owner's network as card work does. Each live run is said beforehand and waits for the owner's word.
- **A model's reply is untrusted** and decides a pointer into the book and text that is stored. The pointer is resolved by code against
  the book and refused if it does not hold; the text stored is checked for shape and length and is shown as untrusted. A security review
  of this surface is asked of the owner once, and runs only if the owner asks.
- **The owner's config is not written by the agent.** The new kinds of work are added by the owner.
- **A long run over the library is expensive in time** and is not started without the owner's word and an estimate from E.
- **A defect found in E or F stops the run**; the plan is not widened to get past it.

## Review record

Reviewer: Codex through the review engine (plan-491835da4c01f718), 2 rounds of 3, both with the verdict `changes_needed` and all findings
major. The owner chose to commit and approve after round 2, so the review did not converge. The records are in
`.workbench/workbench/review-engine/plan-491835da4c01f718/`.

- Round 1 (4 major, all applied): the schema of a theme was left to a draft spec (a table of fields with limits was added); the field's
  vocabulary had no source (derived from the title, the card and the book's text); extraction was allowed for books with no card
  against `theme.md` (a current card is required); the active generation was undefined (the newest valid one, as for cards).
- Round 2 (4 major, three applied and one applied in part): the anchor lacked an end and a hash of the whole excerpt (added); the
  vocabulary algorithm was not fully defined (defined, with its constants as proposals); pointer-only books were excluded (the engine
  has none, so the limit is stated and the case deferred, not built); the outcome of a failed support check contradicted the schema (a
  part not fully supported is kept as `inferred`, and a theme with no valid check answer is dropped as `unchecked`).
- Rejected: none.
- Left for the owner: the proposed limits of the schema table and the constants of the vocabulary rule; the choice to build themes from
  the book text and not to promote the key ideas; and the missing third round.

## Deferred work

- Vectors for the themes, the links and the walk: the later candidates of `theme-weave`.
- Whether the type set is right (`theme.md`, open questions), after themes from a more varied corpus exist.
- Themes of a pointer-only book from its captured snapshot, marked partial (`theme.md`): when the engine has such books.
- Restoring an earlier generation of themes as the active one (`theme.md`): this plan reads the newest valid generation and any
  generation by its number, as cards do.
- Re-extraction of only the changed sections of a new version (`theme.md`, an idea).
- A stronger model for the extraction, if the trial shows the local one is not enough (`theme.md`, open questions).

## Result

Empty until work starts.
