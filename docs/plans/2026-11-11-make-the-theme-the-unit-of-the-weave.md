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

### Increment A (done; committed as d68f6d8)

- **Reused (step 1).** From `card.py`: the shape of `generations`, `file` and `read` (a payload `derived/<tool>/<n>`, one JSON file,
  `store.file_payload` with `untrusted=True`, `store.verify_payload` on reading, `models._loads` for strict JSON), the cleaned form of
  text (`textutil.clean`, and `textutil.title` for the title), and the checks of a record's model and prompt version (`models._valid_model`,
  `models._VERSION`). From `locator.py`: `check` for each end of an anchor and the patterns of the conversion. Not reused: card's
  rule that a read without a number refuses when the newest fails; the plan says the newest that passes is read, so this differs on purpose.
- **Done.** New `engine/kb/theme.py` (the form of a generation and of a theme as the plan's table gives it, `check_theme`, `validate`,
  `make`, `generations`, `file`, `read`, and `damaged`), new `engine/tests/test_theme.py` (43 tests), and a section "Themes" in
  `engine/README.md`. No other tracked file changed. No model call, no command and no other module uses the new module yet.
- **Tests first.** The module did not exist, so the first run failed on the import. One test then failed on the first implementation
  (a read without a number gave only a general reason, hiding "nothing else in the payload"); the module was changed to carry the newest
  generation's reason, not the test weakened.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_theme engine.tests.test_card`: 138 tests OK.
  `wb run code-work check`: no problems.
- **Deliberate breaks.** 26, each caught and restored byte for byte (scratchpad `breaks_theme.py`): the rules of marks (3), duplicate ids,
  the kinds and conversion of the ends, a theme of another book, the bound on themes, a boolean confidence, the order of the ends of an
  offset and of a page, the sizes on filing and on reading, the list of damaged generations, the marker-words guard of the title, the
  cleaned form of text, the excerpt hash, reusing a generation number, filing as trusted, not verifying the payload, another file in
  the payload, a book of another version on reading, not skipping an invalid newest generation, a link taken as a generation, a boolean
  as a generation number, no check before filing. Two were missed at first: `math.isfinite` was redundant (the range check already
  refuses nan and infinity) and was removed; a boolean generation number was refused by another layer with another message, and the test
  now asserts the message.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: (1) the end of an anchor of kind page or offset may not come
  before its start (a section cannot be ordered without the text, so it is left to B), with tests; (2) `theme.damaged` lists the
  generations that fail, because a read without a number otherwise rolls back silently to an older one, and the README says so;
  (3) a test that could pass for the wrong reason on the size check at reading was replaced by one that cannot; (5) the comment on the
  size limits now says a theme at every limit is about 9 KB; (7) an unused import removed. Not applied: (4) the checks are asserted by
  the kind of refusal, not by the one check that fired, which the reviewer called adequate; (6) see below.
- **For the owner.** The limits I added that the plan's table did not give, and which you may change: at most 2,000 themes and 8 MB for a
  generation, at most 10 flags with a kind of 1 to 40 and a detail of 1 to 300 characters, and a heading path of at most 6 parts of 1 to
  80 characters.
- **For Increments B to F.** (a) The anchor `path` is not tied to the `path` in a section locator; B decides whether they must agree.
  (b) `validate` accepts a generation with no themes, so a later failed or empty extraction, once filed, would become the active
  generation and hide an earlier one with themes: C and F decide whether an empty result is filed. (c) Only the title is guarded against the
  words of an untrusted-text marker; when themes are shown, the summary, the neutral parts and the flags need the same guard that
  `card._shown` gives card text.
- **Not done.** Nothing of B to F. No live call was made. No security review was run (none asked): the surface is a file read and
  checked, with no path, command or network use of any field.

### Increment B (done; committed as 7394125)

- **The shapes of a pointer a model can name (step 1).** `{"kind", "start", "end"}`. The kind must be that of the conversion
  (`locator._kind_of`: `section` if it has headings, `page` if it has pages, otherwise `offset`). Each end is the `at` of a locator of
  that kind: for `section`, `{"path": [headings, 1 to 6, each 1 to 80 characters], "paragraph": n}` (the heading itself is paragraph 0;
  the numbers are those `convert.build` gives); for `page`, `{"page": p, "block": b}` (the block counts from 1 among the blocks of the
  page); for `offset`, `{"offset": n}` (a character offset in the converted text, which must lie inside a block and not in the blank line
  between two). The span is the whole blocks from the block at the start to the block at the end; an offset only chooses its block. A
  span may cross sections and pages; its path is that of its first block.
- **Done.** In `engine/kb/theme.py`: `anchor_of` (pointer to anchor), `find` (a stored anchor found again in a conversion, with the status
  `found`, `found_by_text` or `not_found` and a reason), `check_against` (refuses all but `found`), and `MAX_EXCERPT` = 6,000. 30 new
  tests in `engine/tests/test_theme.py` (73 in all there). A paragraph in the engine README. `locator.py` and `convert.py` are used
  and not changed.
- **Decisions made here.** (1) The size bound of 6,000 characters is measured on the converted text from the start of the first block
  to the end of the last, the blank line between blocks counted, and it is checked before the text is copied; the plan's "1 to 6,000
  characters" is read as this, and the lower bound is "has words". (2) The anchor's heading path must be that of the first block: in
  the conversion the anchor was made against, `find` calls an anchor `found` only if it is exactly the anchor code makes for that text,
  so a false path, or an end that is not at the start of its block, does not hold (this answers the question left from Increment A).
  (3) `find` returns a status for an anchor that does not hold, and refuses (`KbError`) an anchor that is not in the form of an anchor and
  a text too large to search.
- **Tests first, seen failing.** The functions did not exist, so the new tests failed on the missing names. Later tests (the false path,
  an end in the middle of a block, the size known before the copy) were each seen failing before the code that makes them pass.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_theme engine.tests.test_read
  engine.tests.test_card engine.tests.test_convert`: 389 tests OK. There is no `test_locator`; locators are tested through
  `test_read` and `test_convert`. `wb run code-work check`: no problems.
- **Deliberate breaks.** 21 of the new code and the 26 of Increment A, all caught and restored byte for byte (scratchpad
  `breaks_theme_b.py`, `breaks_theme.py`). Two of B's were missed at first: an inverted span was refused only by accident as an empty
  excerpt (the test now asserts the reason), and no test took an anchor found only by its words to `check_against` (added).
- **On real books (read-only, nothing written, no model, no network).** `anchor_of`, `find` and `check_against` on a span of three
  blocks of each of 8 converted books of the library, 4 with sections and 4 PDFs: all accepted as `found`. No flat text was in the
  sample, so the kind `offset` is tested on invented text only.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: (1) `find` compared the hash only, so a false path or a
  non-canonical end held (decision 2 above, with tests); (2) the size is computed before the text is copied, so a pointer across a huge
  book does not copy it first (a test with a text that refuses to be sliced); (3) the docstring of `find` says which cases are refusals;
  (4) the meaning of the size bound is stated (decision 1); (6) tests of `find` on pages and a flat text. Not applied: the refusal tests of
  the places of a pointer assert that a refusal happens and not which rule fired, which the reviewer called acceptable given the breaks.
- **Not done.** C to F. The reviewer could not check non-ASCII text against the test helper `words_hash` (the tests use ASCII), and
  nothing was run on real flat text. No security review (none asked): a model's pointer reaches the code only as checked integers and
  strings compared with the block paths, so it cannot read outside the conversion, and its cost is bounded by the size check and by
  `locator.resolve`'s own limit.

### Increment C (done; committed as 3eb7df2)

- **Reused (step 1).** From `cardmake.py`: `_prompt` (sections between delimiters that hold a random token no input holds, the rules
  naming the token), `_TOKEN`, `retry_prompt` (asked once more with the reason in a marked section), `similar` (repeats), the shape of the
  call (`models.run_job` with a `Job`, a schema file, `AnswerRefused` carrying the reply), and `refused.keep` for the refused answer. Not
  reused: the journal, the pause for a model that is not being served, and the sampling of pieces. Pieces are rebuilt here because
  a theme names blocks, so each piece keeps its block numbers.
- **Done.** New `engine/kb/themeextract.py` (`THEME_JOB` v1, `theme_prompt`, `pieces`, `extract`, `make_for_version`, `ThemeRefused`) and
  `engine/kb/schemas/theme.json`; `models.OPTIONAL_TASKS` now holds `theme` (left unset by default; a card does not need it);
  `engine/tests/test_themeextract.py` (41 tests); a paragraph in the README. `make_for_version` files nothing: it returns a
  generation for `theme.file`. Changes outside the plan's list of areas, each small: `theme.py` (a section pointer may have an empty heading
  path, because a block before the first heading has one; a test in `test_theme.py`), and three existing assertions that the card jobs are
  the engine's kinds of work, which now say all kinds except `theme` (`test_models.py` line ~950, `test_cardmake.py` ~1688,
  `test_cardmake_earlier.py` ~1371).
- **Decisions made here.** (1) The model names block numbers, never quotes: the prompt shows `<block n>` before each block, code builds
  the pointer from the numbers and `theme.anchor_of` finds the text; a theme whose numbers are not in the piece is dropped with that reason.
  (2) Every non-empty part of a description is marked `inferred` here; the later check (Increment D) raises a part to `stated`. (3) A
  reply of more than 24 themes is a runaway: raised with its answer, not asked again, nothing made, and `make_for_version` keeps it aside.
  At most 8 themes are asked for in a piece. (4) A book of more than 150 pieces is refused, not sampled. (5) No journal. (6) Of two near-identical
  themes (blocks overlapping by 80 percent or more, summaries that repeat each other) the one of higher confidence is kept.
  (7) A part the text says nothing of is the word `none` in the reply and no text in the theme, because the answer check of the model layer
  refuses an empty item.
- **A defect the review found, and what it showed.** My first tests replaced `models.run_job` with a fake that skipped the shape check
  of the real one, and the prompt asked for an empty string for a part the text did not state. The real check refuses an empty item, so most
  real replies would have been refused whole. The reviewer found it by reading `models._text`. The fake now runs `models._check_answer`
  as `run_job` does, which made 30 tests fail until the prompt and the tests were changed (the word `none`, read as no text by code). What
  the tests still do not show: how often a real model answers in the shape, uses `none`, or names blocks that hold. That is what Increment E
  is for.
- **Tests first, seen failing.** The module did not exist, so the first run failed on the import. A harness fault (the fake not recorded
  on a raised refusal) was mine and was fixed in the test.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_theme`, `test_themeextract`, `test_models`, `test_card`,
  `test_cardmake`, `test_cardmake_earlier`, `test_read` and `test_convert`: 987 tests OK. `wb run code-work check`: no problems. No live
  call; nothing was sent anywhere.
- **Deliberate breaks.** 34 of `themeextract.py`, all caught and restored byte for byte (scratchpad `breaks_themeextract.py`), and the
  47 of Increments A and B still caught. One was missed at first and led to removing a check that `theme.anchor_of` already makes.
- **Read-only on the library (no model, no network).** `themeextract.pieces` on the 175 versions that have a conversion and a card: a
  median of 3 pieces, at most 24, 559 in all, none near 150. So a run over the library is 559 calls, one for each piece, at a rate the
  trial will measure.
- **Review (1 round).** The `reviewer` agent: one blocking finding (the empty item, above), fixed. Not blocking, recorded: (2) a section
  whose heading path is the same as another's cannot be named, so its themes are dropped with a reason; (3) no bound on the themes of a
  whole book (`theme.md` has one that scales with the book) other than 24 a reply and 2,000 a generation; (4) a truncated or partial
  conversion gives themes with no mark of it; (5) no journal, so a failure at piece 40 of 60 loses 39 calls, which Increment F must
  plan for, and the merge is one pass; (6) the test that a token is not in the input was weak and was replaced by one in which the first
  token drawn is one that the book holds; (7) only the title is guarded against the words of the untrusted-text marker (open since A).
  **Second review (2 rounds in all, on the fix only):** no blocking finding; the fake now does what `run_job` does with a reply (shape
  check, the job's check, cleaned values), and `none` is read as no text only when it is the whole part. Applied: the instruction that
  no item of any list may be empty now covers every list and not only the five parts; `NONE` and the set of spellings are tied together.
  Recorded, not applied: an empty or all-blank item in titles, types, summaries, blocks or confidences, which the answer check would
  refuse, costs the whole book (after one retry) because there is no journal; a spelling such as "none stated" or "(none)" stays as text
  marked `inferred`; the prompt does not state the shape limits of types, blocks and confidences. What no test can show is whether a
  real model follows the `none` instruction, which Increment E measures.
- **For the owner, before Increment E.** You add `"theme": "<name>"` to `tasks` in your config (I never write it), and the model should
  be one that follows a list-shaped JSON reply; the card notes model is a candidate. The extraction sends the text of the book, piece by
  piece, to that model.
- **Not done.** D, E, F. No live call. No security review (none asked): a reply reaches only checked fields, numbers pass a regular
  expression, the range check and `anchor_of`, and the refused-answer file is written by the existing `refused.keep`.

### Increment D (done; committed as 0e9211d)

- **Reused (step 1).** From the cards: the verdict words and the shape of the check (`cardmake.VERDICTS`, the job with one verdict for
  each item, `card-check`'s rule that a verdict is one of the three words after strip and fold), `_prompt` and `retry_prompt`. Not
  reused: the notes and quotes of the card grounding (a theme is checked against its excerpt, not against notes) and `cardmarks`
  (it counts marks of cards).
- **Done.** New `engine/kb/themecheck.py` (`words`, `frequencies`, `library_frequencies`, `field_vocabulary`, `field_flag`, `check_job`,
  `check_prompt`, `check_themes`, `make_and_check_for_version`), `engine/kb/schemas/theme-check.json`, `engine/tests/test_themecheck.py`
  (35 tests); `models.OPTIONAL_TASKS` now also holds `theme-check`; `theme.excerpt_text`; in `themeextract.py`, `_ask` takes the job and
  `prepare` is split out of `make_for_version` (same behaviour); the three assertions about the card's kinds of work now exclude both
  theme kinds; a paragraph in the README. Nothing is filed by the new code.
- **Deviation from the plan, stated.** The plan's fixture for the vocabulary is four small books. With four books no word can pass the
  15 percent rule (one book of four is 25 percent), so the fixture has twenty small books, and the boundaries of each constant are tested on
  both sides (4 and 5 occurrences; 3 of 20 books and 4 of 20; 10 of 20 and 9 of 20).
- **Decisions made here.** (1) A part is `stated` only when the check says `supports`; `partly` and `no` leave it `inferred`. (2) One call
  for each theme that has a part with text; parts with no text are not asked about, and a theme with none is flagged `no_description`. (3) A
  theme whose check is refused twice is dropped as `unchecked` and both refusals are kept aside; a call that fails is raised. (4) A flag does not
  change a mark and does not drop a theme. (5) The anchor of every theme is checked against the text, and both models are found, before
  the first call. (6) The vocabulary is the plan's rule as written.
- **Tests first, seen failing.** The module did not exist (import error). Two tests of mine were wrong against the algorithm and were
  corrected before the code (a string-literal precedence slip in the fixture, and one expectation in the 9-of-20 case).
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest` on `test_theme`, `test_themeextract`, `test_themecheck`,
  `test_models`, `test_card`, `test_cardmake`, `test_cardmake_earlier`, `test_read`, `test_convert`: 1022 tests OK. `wb run code-work
  check`: no problems. No live call; nothing sent anywhere.
- **Deliberate breaks.** 32 of `themecheck.py`, all caught and restored byte for byte (scratchpad `breaks_themecheck.py`), after two were
  missed at first (a test of the compatibility forms that `casefold` already handled, and no test of the library counted from the store);
  the 81 of Increments A, B and C still hold.
- **What the rule does on the real library (read-only, no model, no network).** The library is 175 books and 42,263 distinct words; 328
  words are common. A book's vocabulary has a median of 47 words (2 to 442). Applied to the neutral fields of the existing cards, the rule
  flags 174 of 175; with the title alone it flags 119, with the title and topics 173, and the constants of the text rule (5 to 40
  occurrences, 15 to 2 percent) change the number by 1 or 2, so they hardly matter. Of the 1,445 words flagged, 822 come from the card's
  topics, 425 only from the text and 198 from the title. The most flagged are mostly terms of a field (training, distributed, neural,
  transformer, stochastic, reinforcement, quantum, hash, cryptographic) with some generic words (search, language, memory, critical, scaling).
  Reading: the rule finds the field's words that the cards let through, and has some false flags from generic topic words. It says nothing
  yet about the descriptions of themes: the prompt for themes gives the same instruction as the card prompt (no name of a field, game,
  product or person), so whether they leak less is what Increment E measures. If E shows the flag fires on nearly every theme it carries
  no information, and the owner then decides the constants; I have not changed them.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: (1) my README said the descriptions of themes are made under
  a stricter prompt, which the prompts do not show, and the claim is removed; the most flagged words were listed and read, as it
  suggested; (6, in part) `library_frequencies` counts one text at a time instead of holding them all, and a book file that cannot be read is
  left out; (7) a comment in a test. Recorded, not applied: (2) the model and prompt version of the check are in the records that
  `make_and_check_for_version` returns and not in the generation, because the plan's form of a theme has no field for them, so the rule of
  Increment F that skips a book "made with the same prompt version and models" cannot see the check, and F must keep the records beside the
  generation or the plan must be revised; (3) a failed call during the checks loses the extraction and the checks before it (no journal; one call
  for each theme makes it about one more call for each theme); (4) the prompt calls a part supported if the excerpt "clearly leads to it",
  which widens `stated` toward inference as the card check does, so E should read a sample of `stated` parts against their excerpts; (5) a
  text in the book that tells the checking model to say `supports` could raise marks wrongly, which delimiters and a rule against
  following the data make harder and no test can show; (6) the rest: a book that is not current or not active is not in the count, so the
  count of the checked book can be one low, the whole library is counted again for every book unless `frequencies` is passed (F passes
  it), the skip of inactive books is not tested, and the library is counted from the conversion in use, which is what the plan calls the
  newest of the current version only if they coincide; (8) a theme that arrives with ten flags drops with that reason.
- **For the owner, before Increment E.** You add `"theme-check": "<name>"` to `tasks` as well as `"theme"` (I never write the config). The
  check is a judgment of whether an excerpt states a sentence, and the extraction model is a poor judge of its own output, so a second,
  different model is the better choice if you have one. The check sends each excerpt and the parts to that model.
- **Not done.** E and F. No live call. No security review (none asked): the excerpt and the parts reach only the prompt of the second
  model, in delimited data sections, and only the verdict words come back into any field.

### Increment E (run on 2026-11-11; the owner decided to revise the prompts and repeat the trial)

- **What was sent, and said beforehand.** For each piece of the six books, the title and up to 20 KB of the book's text to the model set
  for `theme`; for each theme, its excerpt and up to five short sentences to the model set for `theme-check`; in the clear to the owner's
  server, as card work goes, and nothing else. The owner added `"theme": "gemma"` and `"theme-check": "local"` to `tasks` and said "run it".
  The models that answered were `gemma4:12b` and `phi4:latest`. Nothing was filed in the library.
- **Provenance.** Run once on 2026-11-11 at commit `0e9211d`, by a script kept outside the repository (it calls
  `themecheck.make_and_check_for_version` for each book with the frequencies of the library, times each call, and writes a report), prompts
  `theme` v1 and `theme-check` v1. The report is outside the repository, mode 600, 130,684 bytes, sha256
  **`844bafe09c361daaff9ed8d8e6dd57750b230151aee72fc7ff09cf67f0d9ae9f`**, and holds the numbers below and, for each kept theme, its
  parts, marks, flags and the start of its excerpt. The books were the owner's choice from my proposal.
- **Cost.** 348 seconds for six books, 33 extraction calls (mean 6.5 s) and 68 check calls (mean 1.8 s), 255,934 tokens in and 18,487 out.
  So the whole library (559 pieces) would be about an hour for the extraction and about as long again for the checks, at the themes found
  here, and more if themes that were dropped are kept. No book failed; 6 replies were refused for their shape (1 in HMC, 5 in the networks
  paper) and kept aside, and each was asked again and accepted.
- **The numbers by book** (pieces; themes kept of proposed; themes per 1,000 tokens, tokens taken as characters over 4; seconds; kept themes
  flagged for the field's words; parts marked stated of parts with text):
  Sequential analysis, 1 piece, 4 of 4, 1.63, 18 s, 4 of 4, 13 of 16. Stigmergy, 1 piece, 0 of 1, 0, 7 s, none kept. Soft Actor-Critic, 3
  pieces, 3 of 12, 0.23, 26 s, 3 of 3, 13 of 13. Ising model, 4 pieces, 20 of 21, 1.24, 57 s, 17 of 20, 71 of 89. Hamiltonian Monte Carlo, 7
  pieces, 16 of 24, 0.50, 82 s, 16 of 16, 55 of 74. Complex networks, 17 pieces, 27 of 56, 0.35, 158 s, 23 of 27, 81 of 101. **In all:
  70 kept of 118 proposed, 0.49 themes per 1,000 tokens, 63 of 70 flagged (90 percent), 233 of 293 parts stated (80 percent).**
  The earlier throwaway experiment found a median of 0.42 themes per 1,000 tokens. No runaway, no merge of near-identical themes, no
  theme dropped as `unchecked`.
- **Why 48 of 118 themes were dropped.** *29 for "the confidence is not a number"* (25 percent of all proposed; 1, 7, 6 and 15 in four
  books): my drafting drops a theme if its confidence does not parse, and the model does not always give a number. *16 for an excerpt over
  6,000 characters* (13 of them in the networks paper, up to 18,230 characters): the model names a span of blocks it cannot measure. *1 for blocks
  not in the piece, 2 for a proof or a definition that serves only the text.* Of the 116 themes that reached the pointer step, 99 (85 percent)
  had a pointer that held; every kept theme's anchor was checked by code and holds.
- **What the kept themes look like.** Types: 37 concept, 21 method, 10 finding, 2 problem. Confidence: 66 of 70 are exactly 1.0, so it
  carries no information. The median excerpt is 2,315 characters (largest 5,725). Marks by part: problem 57 of 65 stated, method 61
  of 67, provides 56 of 64, needs 39 of 63, limits 20 of 34. Words flagged most: degree, target, phase, integration, correlations, energy,
  attachment, lattice, exponents, typical, curvature, trajectories; the flags hold 5.6 words on average and some hold 12 to 16.
  I read a sample of 10 themes against their excerpts (shown to the owner). The summaries and the descriptions are accurate to the text in
  nine; one theme is a bibliography (a list of references of the Ising article), kept as "Historical and Mathematical Foundations of the
  Ising Model", with parts marked `stated` that the list does not state, which shows that the prompt's "skip references" is not obeyed and that
  the check marked a bibliography's parts as supported.
- **What this says, and what it does not.**
  (1) **The descriptions in words of no field use the field's words.** 90 percent of the kept themes are flagged, and the sample shows
  real terms (Ising, Hamiltonian, Monte Carlo, Markov, Metropolis, degree distribution, power-law exponents, spontaneous magnetization,
  phase space). The flag is informative here (it finds real leaks, with a few generic words such as "target", "typical", "sets"). The weave
  needs descriptions that match across fields; with the field's vocabulary in them they will mostly match within a field. This model, with this
  prompt, does not meet "in words that name no field" (the prompt for themes gives the same instruction as the card prompt, which the
  cards' own descriptions did not meet either).
  (2) **A quarter of the proposed themes are lost to a defect of mine**: dropping a theme because its confidence is not a number loses the
  theme and keeps nothing, and the confidence that does parse is almost always 1.0.
  (3) **Fourteen percent of the proposed themes are lost to the size bound**, because the model cannot see how long a block is.
  (4) **The check marks 80 percent of parts as stated**, including the parts of a bibliography; one clear wrong case in ten is too few to say
  how lenient it is, and the owner's reading of more `stated` parts against their excerpts is what shows it.
  What cannot be concluded: six books chosen by me from a library of 175, one run, one first reply per piece from one extraction model and
  one checking model, the sample of ten read by two people at most, no repetition, and no comparison with another model or another prompt.
- **Recommendation (given before the owner's decision).** Do not run Increment F now. Make three changes to the method and repeat this
  trial on the same six books, so the numbers can be compared: (a) a theme is never dropped for its confidence (an unreadable one is
  kept with a neutral value and a flag, or the field is dropped from what the prompt asks); (b) each block in the prompt shows its length
  in characters, so that a span can be kept under the bound; (c) the descriptions in words of no field get a second try: a prompt with a
  worked example, or a rewrite step that is given the words the flag found and asked to say the same without them, or a larger model for that
  step. Those are changes to Increments C and D (a plan of their own, or a revision of this one), not to the trial. The check's leniency and
  the bibliography blocks are for the owner to judge from more samples before deciding on (d), a rule that skips blocks that are only
  references.
- **Owner's decision (2026-11-11):** "Go with your recommendation": do not go on to Increment F now; revise the method and repeat the trial
  on the same six books. The changes are to Increments C and D of this approved plan, so they are made under a plan of their own
  (`2026-11-11-revise-the-theme-prompts-after-the-first-trial`). This plan stays `In Progress` and Increment F is not started.
