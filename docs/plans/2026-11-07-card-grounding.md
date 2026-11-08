# Making the cards accurate

Status: In Progress
Created: 2026-11-07
Candidate: cards#card-grounding
Specs: card

## Goal

The owner knows how accurate the cards are, and the cards are more accurate. When this is done, a card is made from notes in which
every point carries a short verbatim quote that the engine has checked against the piece it names; the card's key ideas, topics,
caveats and limits name the notes that support them (the summary and the other neutral fields are measured, not marked); each such
item that is kept is marked stated or inferred, and what is neither is dropped; the marks are
shown to a reader and in a search result. The accuracy of the old cards and of the new ones is measured on a sample of items that
a strong model labels without knowing which card each came from, checked against a small subset that the owner labels.

## Scope

- A sample of card items, drawn blind from chosen generations of the cards and written outside the repository with the passages of
  the book that best match each item, a small calibration subset of it for the owner, a report of labels (supported, unsupported,
  inference) by field and by generation, and a report of how far two sets of labels of the same items agree.
- The notes stage asks for a quote with every point and checks each quote against its piece; a book of one piece goes through the
  notes stage too, so there is one path.
- The card call cites the notes that support an item; the engine marks each item, drops unsupported topics, key ideas, caveats and limits, marks a
  card with fewer than three supported key ideas as thin (it is not padded), and keeps the quotes that support an item as untrusted
  text in the card.
- A new card format that carries the marks; cards of the old format stay readable and are shown as not checked.
- A prompt with higher ceilings for key ideas and topics, the right word for the kind of source, and no mention of the pipeline's
  notes in the card.
- The marks in `card-show` and in the result of `card-search`.
- A live run on the 12 carded books as a new generation, the labelling of a blind sample of old and new items by a strong model
  and of a calibration subset by the owner, and a written comparison with the owner's decision on what comes next.

## Non-goals

- A second model that checks the card, agreement across two runs of the notes, and a higher cap on the pieces sampled from a long
  book. They are deferred until the labelled sample shows that they would pay (see Deferred work).
- Search by meaning, themes, or a cloud model as a card writer or checker. A cloud model is used only to label the accuracy
  sample, as the roadmap candidate allows.
- A second trial on harder questions and more books. The roadmap lists it as deferred work.
- Marks on the summary and on the neutral problem, approach, needs and provides. They are measured by the sample, and grounded in
  a later plan if the sample shows that they need it.
- Rewriting or deleting an existing card. A new card is a new generation; the old ones stay.
- Any change to the card search itself, beyond showing the marks.

## Assumptions and constraints

- The owner prefers accuracy to speed and accepts more model calls and time to get it (recorded in the Result of the card trial and
  in the roadmap candidate).
- The card trial found that facts a source states are well captured, that unsupported material sits in limits, caveats and adjacent
  topics, that word overlap with the book is a weak check, and that card size barely follows the length of the book. A verbatim
  quote that occurs in the piece is a check a model cannot fake without being caught; whether local models give usable quotes, and
  how often a correct quote fails to match because of how a PDF is converted (hyphenation, ligatures, line breaks), is not known
  and is measured here.
- Adjacent topics are by definition not in the book, so they carry no mark of support.
- A quote and a card are text taken from a book or written about it: untrusted, checked for shape and length, stored with the
  untrusted marker and shown inside it, as every card already is.
- The model-call layer takes the model for each task from the owner's config, and the calls go to the owner's models. The live
  run in the last increment needs the owner's word on the books and on sending their text; nothing else sends text anywhere.
- Most use of the library will be by agents, so a strong model, run as a subagent of this session and recorded by model and date,
  labels the sample. A model tends to be lenient, and it may miss support that lies outside the passages it is shown, so its
  labels are checked against a calibration subset that the owner labels in the same blind form, and the plan reports their
  agreement. The model's output is data, never a verdict, and the owner's labels win where they differ. The passages go to a cloud
  model, which needs the owner's word; the books of the walk-through library are public.
- The files of the labelled sample and its key are held outside the repository, and the commands refuse a path inside it, as
  `trial` does. They name the books by id and title; the books of the walk-through library are public.
- Model names, the owner's paths and server names are not written into any tracked file.
- Anything the decision of the card trial leaves open stays open: this plan does not decide search by meaning or themes.

## Completion criteria

1. `card-sample` writes a blind sample, a calibration subset and a separate key outside the repository; `card-accuracy` reports
   labels by field and by generation, with counts, and refuses labels that are incomplete or do not match the key; and
   `card-agreement` reports how far two labellings of the same items agree. All three are tested on a hand-made library with a
   known answer.
2. A quote is accepted only if it occurs in the piece it names, after the normalisation of hyphens, ligatures, case and white space
   that the code states, and the tests show a quote that is not in the piece, one that is too short and one that spans a piece
   boundary being refused.
3. The notes stage returns a quote with every point; a point whose quote does not occur is kept and marked unverified; a book of
   one piece gets its notes by the same path as a long one.
4. A card of the new format marks every key idea, topic, caveat and limit it keeps as stated (cites a verified note) or inferred
   (the model says so), and drops every other one (a limit that is dropped leaves its field empty); it marks a card thin when
   fewer than three key ideas remain (it is not padded back to three), and keeps the supporting quote of a stated item. A card
   of the old format is still read, shown as not checked and searched as before.
5. `card-show` and `card-search` show the marks, and a result gives a count of items by mark.
6. On the 12 carded books a new generation is made; a strong model has labelled a blind sample drawn from the old and the new
   generation and the owner has labelled a calibration subset; the report gives the supported, unsupported and inference counts
   of each generation, the agreement of the model with the owner, and the disagreements; and the plan records what the numbers
   show, the share of quotes that verified, the cost in calls, and the owner's decision on the deferred work.
7. The tests named for each increment pass, and the whole-plan verification passes.

## Increments

### Increment A — Measuring the accuracy of the cards

**Outcome:** a blind sample of card items can be labelled by a model and, for a small subset, by the owner; the labels give counts
of supported, unsupported and inference items by field and by generation, for any set of cards; and two labellings of the same
items can be compared.
**Dependencies:** none.
**Affected areas:** new `engine/kb/cardsample.py`; `engine/kb/__main__.py` (the commands `card-sample`, `card-accuracy` and
`card-agreement`);
`engine/kb/trial.py` (the rule that a path is outside the project moves to one shared place and `trial` uses it from there);
new `engine/tests/test_cardsample.py`; `engine/README.md`.
**Steps:**
1. Write the tests first on the fixture library of the card tests, with cards of two generations: the sample has the number of
   items asked for, drawn with a recorded seed so that the same seed gives the same sample; it is stratified over cards and over the
   fields topics, key ideas, caveats, the five neutral fields and the sentences of the summary (adjacent topics are left out,
   since nothing is expected to support them); every item is of a card that validates; the file of items says nothing of the generation, and the key file maps each
   item to its book, version, generation, field and position.
2. Write `card-sample OUTDIR --items N --calibration K --seed S --generation G ...`: it draws from each generation named (default:
   the newest of each version), writes `items.json` (the order shuffled, each item with an id, the book id and title, the field,
   the text, up to five passages of the book that share the most content words with it, each cut to 600 characters, and `"label":
   null, "labelled_by": null, "note": ""`), `rubric.md` (the three labels and skip), `calibration.json` (K of the same items, spread over the fields, with the same ids) and `key.json`,
   all with mode 600 in a folder of mode 700, and refuses a folder inside the project, a folder that exists with files in it, and
   a book whose converted text cannot be read. The passages come from the converted text and are untrusted; they are written as
   data. A passage is the best-matching block with the block before and after it, so the evidence is not a single sentence.
3. Write `card-accuracy ITEMS KEY`: it reads the labelled items, requires every label to be one of `supported`, `unsupported` or
   `inference` (or the item to be set aside with `skip`, counted), a `labelled_by` on each, and a `note` where the rubric asks for one, joins the key, and reports for each
   generation and field the counts and shares with their totals. It refuses items that are not the ones the key was made for
   (ids, count, text) and prints no item text.
4. Write `card-agreement FIRST SECOND`: the comparison is over the ids of the smaller file, which must be a subset of the larger
   (the model labels `items.json` and the owner labels `calibration.json`, whose ids are among them). It refuses a file with an id
   that the other lacks and ids whose item text differs. For the ids both label, it reports the share on which the labels agree, a
   table of the label pairs, the ids that differ, and the count of items either file skipped, and it prints no item text.
5. Fix the three labels in one rubric, held as one text in the code, written to `rubric.md` by `card-sample`, quoted in the
   README and given to every labeller. **supported:** a shown passage states the item, and if it has several parts, states all of
   them. **inference:** no shown passage states it, but it follows from what the passages say (a limit or a use drawn from them),
   and the labeller names the passage it follows from in the item's `note`. **unsupported:** no shown passage states it or
   supports it, a passage contradicts it, or only part of it is stated (the note says which part). **skip:** the item is about the
   card's own source or process and not about the book, or cannot be judged from the passages. A labeller sees only the passages
   shown, so an item whose support lies elsewhere in the book is labelled unsupported. The two labellers share the passages, so
   their agreement cannot measure that; increment E measures it separately (a second look at the full text), and until then the
   counts are of support within the passages shown. `card-accuracy` also counts the notes and the skips.
6. Document the commands in `engine/README.md`, including that labelling is blind: the generation is not shown in the items file.
**Verification:** `python3 -m unittest engine.tests.test_cardsample engine.tests.test_trial engine.tests.test_card`, since the
shared path rule is used by `trial`; deliberate breaks of the stratification, of the blindness, of the seed, of the join with the
key, of the agreement count and of the refusals, each shown to fail a test from a green baseline.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#A`.

### Increment B — Notes with quotes that are checked

**Outcome:** every point in the notes on a piece carries a quote, and the engine knows whether the quote occurs in the piece.
**Dependencies:** none (it can follow A).
**Affected areas:** new `engine/kb/quotes.py`; `engine/kb/cardmake.py` (the notes job and its prompt, a book of one piece going
through the notes stage); `engine/kb/schemas/` (the schema of the notes job); `engine/tests/test_quotes.py` and
`engine/tests/test_cardmake.py`.
**Steps:**
1. Write the tests first. `quotes.normalize` and `quotes.occurs` on text worked out by hand: a quote that occurs; one that differs
   by case, a ligature, a soft hyphen, a hyphen at a line end or runs of white space (accepted); one that is not in the piece; one
   under the minimum length (12 characters after normalising); one over 240; one made of the words of two different pieces; and
   one that occurs only in the title or the outline (refused).
2. Write `quotes.py`: the normalisation (NFKC, case folded, the hyphens and the soft hyphen taken out or made one, a hyphen before
   a line break joined, white space made one space), and `occurs(quote, piece)` which is true only if the normalised quote is a
   substring of the normalised piece. The rule is stated in the module and in `engine/README.md`.
3. Change the notes job to version `v3`: up to four points, each a short claim with a quote of the piece, as two lists of the same
   length (the shape layer has no list of records; a reply with lists of unequal length is refused). The prompt says to quote the
   book's own words, never to quote the title or the headings, and that a quote that is not in the text will be discarded.
4. After each reply, mark each point verified or not with `occurs`, and hand the card call the points labelled with the number of
   the piece and the point (`2.1`) and their mark. Count the points and the verified ones in the record of the call.
5. A book of one piece goes through the notes stage too (one more call), so that every card has the same path.
**Verification:** `python3 -m unittest engine.tests.test_quotes engine.tests.test_cardmake engine.tests.test_card`; deliberate
breaks of the normalisation, of the length limits, of the substring test and of the unequal-lists refusal.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#B`.

### Increment C — A card that is grounded in the notes

**Outcome:** a card made from the new notes carries a mark for each item that can be supported, drops what is unsupported, and is
valid in a new format; cards of the old format are still valid.
**Dependencies:** B.
**Affected areas:** `engine/kb/card.py` (the format, the shape, the validation, the rendering); `engine/kb/cardmake.py` (the card
prompt and the marking); `engine/kb/schemas/`; `docs/specs/card.md`; `engine/tests/test_card.py` and
`engine/tests/test_cardmake.py`.
**Steps:**
1. Write the tests first, against hand-made model replies: a key idea that cites a verified point is stated and kept with its
   quote; one that cites only an unverified point, a point that does not exist or nothing is dropped, and if fewer than three key
   ideas remain the card is marked thin and says why, with no unsupported idea kept to fill it; an item the model labels
   `inferred` is kept and marked so; a caveat that has no verified quote and is not labelled inferred is dropped, and so is a
   limit (its field is then empty and is left out of the display); adjacent topics carry no mark; a reply that cites a
   reference in a form other than `piece.point` is refused; a card of format 1 still validates and a card of format 2 with a
   missing, extra or malformed mark does not.
2. Move the card to format 2: a top-level `grounding` record that, for each of topics, key ideas, caveats and the neutral limits,
   gives for each item its mark, the notes it cites, and the first supporting quote (at most 240 characters); format 1 is still
   accepted for reading, and the catalog accepts either. In format 2 the neutral limits may be empty, which the shape check and
   the validation of a format 1 card do not allow.
3. Change the card job to version `v3`: the ceilings for key ideas and topics rise (up to 8 and 20, asking for at most 7 and 12),
   the model gives for each item the notes that support it or the word `inferred`, the prompt is told the kind of source (a web
   page, a paper) and uses its word, may not speak of "notes" in the card, and may not write a caveat that holds for any source.
   Items from a source in another language are written in English as now.
4. After the reply, compute the marks, apply the drops and the thin mark, and record the counts in the generation record. The marks
   come from the engine's check of the quotes, never from a claim of the model.
5. Render the quote with its item as untrusted text; keep the withheld rule for any text that holds a marker.
6. Update `docs/specs/card.md` ("What a card holds", "Making and regenerating a card", "Quality", and the acceptance criteria) to
   say what is built, in the statements' existing style. The non-goal about verifying claims was narrowed, on the owner's word,
   before this plan was approved (it now says that the engine checks the support of an item and not that the claim is true); it
   is not changed again here.
**Verification:** `python3 -m unittest engine.tests.test_card engine.tests.test_cardmake engine.tests.test_catalog
engine.tests.test_quotes`, since the catalog reads cards of both formats; deliberate breaks of each mark rule, of the drop and the
thin mark, of the reading of format 1 and of the refusal of a malformed mark.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#C`.

### Increment D — The marks where a reader sees them

**Outcome:** `card-show` and `card-search` show whether an item is stated or inferred, and a search result says how many
items of each mark its card has.
**Dependencies:** C.
**Affected areas:** `engine/kb/card.py` (render), `engine/kb/catalog.py` (the result), `engine/kb/__main__.py`,
`engine/README.md`, `engine/tests/test_catalog.py` and `engine/tests/test_card.py`.
**Steps:**
1. Write the tests first on a library with a card of each format.
2. Show the mark after each item in the rendered card; a card of format 1 says `not checked`.
3. Add to each search result a `grounding` count of items by mark (or `not checked`); the excerpt and the score are as before.
   Searching is unchanged: the marks are shown, never used to rank or filter.
**Verification:** `python3 -m unittest engine.tests.test_catalog engine.tests.test_card engine.tests.test_trial`, since `trial`
reads the catalog.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#D`.

### Increment E — A live run, the labelled sample and the comparison

**Outcome:** a blind sample of old and new items is labelled by a strong model and a calibration subset by the owner, the plan
records what the numbers show and how far the two labellings agree, and the owner has decided what comes next.
**Dependencies:** A, B, C and D. It needs the owner's word on the books, on sending their text to the local models, on sending the
sample's items and passages, and the whole text of a few books for the second look, to a cloud model, and on the time to label the calibration subset.
**Affected areas:** the owner's library (a new card generation for the books named, the catalog), files outside the repository,
and the plan's Result. No tracked file other than the plan changes.
**Steps:**
1. Propose the books to the owner (the 12 carded books are the natural choice), the size of the sample (about 80 items) and of the
   calibration subset (about 15), and say what it costs: about twice the calls of the first run, because of the notes stage for
   every book; a cloud model reading the items and passages; and the owner's time for the subset only. Wait for the owner's word.
2. Run `cards --again` for the books named, a few at a time. Record, for each book, the calls, the points and the share whose quote
   verified, the items marked and dropped, and every failure; a refused answer is kept aside and read. If fewer than half of the
   quotes verify on a book, stop and report before going on: the check may be failing for a reason of conversion, not of the model.
3. Run `card-index`, then `card-sample` drawing from both generations. The key file is kept by me and is not given to the labeller
   or shown to the owner.
4. Have a strong model label the items file as a subagent that is given the file and the rules for the three labels, and not the
   key, the generation or the plan's reading of the old cards. Record the model, the date and the instructions it was given. Give
   the owner the calibration file to label, blind. Its output and its labels are data.
5. Run `card-accuracy` on the model's labels, and `card-agreement` between the model's labels (of the whole items file) and the
   owner's labels (of the calibration file), which it compares over the calibration ids. The labeller is given the rubric.
   Then take every item on the calibration ids that the model labelled unsupported and give it, with the book's whole converted
   text and not only the passages, to a second look by the same kind of labeller under the same rubric. The share of those that
   change label is the estimate of retrieval misses; report it apart from the agreement, with its count. The agreement itself
   is of support within the passages shown. Read the disagreements with the owner. If they agree on most items, the model's labels carry the sample; if not, say so
   and report the owner's labels alone for the subset. Run `trial` again on the same corpus into a new report, to see whether the
   search changed.
6. Write the result in the plan, naming no personal question, project, path or machine: the counts by generation and field, the
   share of quotes that verified, the agreement and where the labellers differed, what the cards lost and kept, the cost, and the
   limits (twelve books, a small sample, a model's labels checked on a small subset). Add a provenance line.
7. Give the owner a recommendation on the deferred work (a second model's check, two runs, a higher cap, a second trial) and
   record the owner's decision.
**Verification:** the runs of steps 2 to 5, read as written; `python3 -m unittest engine.tests.test_cardsample engine.tests.test_quotes
engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog engine.tests.test_trial` once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#E`, which holds the plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After E, rerun once
`python3 -m unittest engine.tests.test_cardsample engine.tests.test_quotes engine.tests.test_cardmake engine.tests.test_card
engine.tests.test_catalog engine.tests.test_trial engine.tests.test_setup`. The wider engine suite is not named: the plan changes
the card format and the notes and card jobs, and adds two commands, but no stage, no index and no store. The risk a wider run
would address is a place that reads a card and was not tested here; the readers are `catalog`, `trial` and `card-show`, which the
list covers. A wider run is the owner's to ask for.

## Risks and sensitive actions

- **Book text goes to the models again.** Increment E sends the text of the books the owner names, over the registry's link, with
  about twice the calls of the first run. It needs the owner's word. The books of the walk-through library are public.
- **The quote check can fail for the wrong reason.** A correct quote may not match because of hyphenation, ligatures or line
  breaks in a converted PDF, and a model may paraphrase. The share that verifies is recorded for every book, a book below half
  stops the run, and the normalisation is stated and tested, not tuned to pass.
- **Quotes are untrusted book text kept in a card.** They are short (at most 240 characters), cleaned, shown inside the untrusted
  marker and withheld if they hold a marker's words, as every other card text is; they are not used by any search or ranking.
- **The format changes.** A card of format 2 must not break the reading of the 12 existing cards, the catalog or `trial`; both
  formats are tested through every reader, and an old card is never rewritten.
- **The model can still steer a card.** A verified quote shows that a claim is in the book, not that the claim is right or that the
  book was not written to mislead. The marks say stated or inferred, and the labels measure how far to trust
  them.
- **Items, passages and some whole books go to a cloud model.** Increment E sends the sample's items and the passages of the
  books to a cloud model to be labelled, and, for the second look, the whole converted text of the books of the calibration items
  that were labelled unsupported. It needs the owner's word, and the books are public. Nothing from the owner's own projects is in it.
- **A model labeller may be lenient or may miss support outside the passages.** The owner labels a calibration subset in the same
  blind form, the agreement and the disagreements are reported, and where they differ the owner's labels win. A labeller that
  is shown the key, the generation or the plan's reading of the old cards would not be blind; it is given none of them.
- **A sample of a few dozen items is small.** The numbers are for the owner to weigh, with their counts; the result says so.
- **The sample files name books and hold passages.** They are held outside the repository with private modes; the commands refuse
  a path inside the project.
- **Time.** The run takes tens of minutes of model time, and the labelling takes the owner's time.

## Review record

Reviewer: Codex through the review engine. Round 3 of 3 (the bound): ten findings in all, ten applied, none rejected. The fix of
the last finding has not been reviewed again.

- Round 1, five findings, all applied. The plan had drifted from the roadmap candidate and the card spec in what the owner agreed
  in conversation. On the owner's word: the candidate now lets a cloud model label the accuracy sample, has the sample labelled by
  a strong model and checked on a calibration subset that the owner labels, names the four fields that are marked (the summary and
  the other neutral fields are measured by the sample), and moves the second trial to the roadmap's deferred work; the spec's
  non-goal now covers verifying that claims are true, with a statement of what the engine does check.
- Round 2, four findings, all applied: the agreement command compares over the ids of the smaller file; one rubric defines the
  three labels and skip; unverified key ideas are dropped and a short card is marked thin, not padded; unsupported caveats and
  limits are dropped too, so a kept item is marked stated or inferred (on the owner's word the roadmap and the spec say so).
- Round 3, one finding, applied: the two labellers share the passages, so their agreement cannot measure support missed outside
  them. The claim was removed, the agreement is stated as support within the passages shown, and a second look at the full text of
  the items labelled unsupported on the calibration ids estimates the retrieval misses apart.
- Left for the owner: whether to ask for a further round of review (the bound is reached; extending it is the owner's level
  `ask`) or to approve the plan as it stands.

## Deferred work

- A second model that checks the card for support when a list is full or an item's support is weak, tested against the owner's
  labels before it is trusted; agreement across two runs of the notes; and a test of whether covering every piece of a long book
  improves accuracy before the cap of twelve pieces is raised. Increment E ends with a recommendation on each.
- A second trial on harder questions and more books, to see whether more accurate cards find more.
- Search by meaning and themes, which the card trial decided against for now.
- A threshold below which a card is marked partial for having few verified claims, until the share that verifies is known.

## Result

### Increment A — Measuring the accuracy of the cards (built; not committed)

- Built `engine/kb/cardsample.py` (the commands `card-sample`, `card-accuracy` and `card-agreement`), `engine/kb/paths.py` (the
  rule that a file is held outside the repository, which `trial` now uses from there), `engine/tests/test_cardsample.py` (41 tests)
  and a README section. The tests were written first and failed because the module did not exist. No model is called and nothing
  in the library changes. The commands have not been used on the owner's library; that is increment E.
- Verification as run: `python3 -m unittest engine.tests.test_cardsample engine.tests.test_trial engine.tests.test_card` gave
  140 tests, OK (also with ResourceWarning as an error); `wb run code-work check` found no problems. Not run: any other test file.
- Deliberate breaks, each from a green baseline: 27 of the first build (24 caught at once; two test gaps, the spread of the
  calibration subset and the case of an unreadable book that the draw happened not to pick, were strengthened and are now caught;
  the third survivor was one of three layers of the project-path rule and removing all three is caught) and 23 of the build after
  the review (22 caught). The survivor is a guard against deep nesting in the JSON readers, which this Python refuses by itself,
  so the guard is redundant here and is kept.
- A break that removed every layer of the project-path rule made a folder of test data in the project during the run; I looked
  at it (four sample files of the fake test library), removed it, and the working tree held only the intended changes.
- Review: the `reviewer` agent, round 1. One blocking finding, applied: a passage could run past 600 characters when the best
  block was 597 to 599 characters (the room for its neighbours went negative and the slice took nearly the whole next block, up to
  about 100,000 characters, which `card-accuracy` would then have refused); I confirmed it with a direct call (5,599 characters),
  clamped the room at zero, and added a test over lengths 590 to 605. Other findings applied: a failed write now removes only the
  files this call wrote and leaves a file of someone else in the folder; the default (the newest card of each version) is one group,
  so books whose newest card has a different generation no longer split the quota or make the sample refuse; cards that cannot be
  read are counted in the printed summary (`unreadable_cards`); the readers refuse a pipe, a number out of range and over-long
  numbers with a refusal and not a traceback, and read at most the size limit.
- Not applied, with reasons: a note for a partly stated `unsupported` item is not enforced (the rubric asks, but it cannot be
  checked mechanically); `position` in the key means the index in the card's own list for topics, key ideas and caveats and the
  index of the sentence for the summary, which is only descriptive; `passages` and `title` in a labelled file are not compared with
  the key, since the labeller changing them alters no number and the check on text, field and book already holds.
- For increment E: the wording of an item can reveal its generation to a labeller (the new prompt will not say "notes", for
  example), which no code here can prevent. Increment E should say so in its result, and the printed summary of `card-sample`
  shows counts by generation to the operator and is not to be passed to the labeller.
- Committed as `822abac`.

### Increment B — Notes with quotes that are checked (built; not committed)

- Built `engine/kb/quotes.py` (the normalisation and `occurs`), the notes job at version v3 in `engine/kb/cardmake.py` (up to four
  points, each with a quote, as two lists of equal length), an optional `check` on a model job in `engine/kb/models.py` (a refusal
  by the check keeps the answer aside like any other refused answer), the notes schema, the `points` and `verified` counts in the
  result of `make_model_part` and in the `cards` report, tests (`engine/tests/test_quotes.py`, and changes to `test_cardmake.py`
  and `test_models.py`) and README text. The quote rule is stated in the module and in the README.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_quotes engine.tests.test_cardmake
  engine.tests.test_card` gave 164 tests, OK; `python3 -m unittest engine.tests.test_models engine.tests.test_catalog
  engine.tests.test_trial engine.tests.test_cardsample engine.tests.test_setup` gave 293, OK, since the model layer and the fixtures
  of the card tests changed; `wb run code-work check` found no problems. Not run: any other test file, and any live model call.
- I wrote `quotes.py` in the same step as its tests, so I did not see the tests fail first; deliberate breaks stand in for that.
  Breaks, each from a green baseline: 14 of the quote rule, 17 of the notes stage and 3 of the job check were all caught (two
  breaks of the first set survived at first, which led to a test of letters of other forms and to replacing an invisible soft
  hyphen in the source with a named escape), then 8 of the changes made after the review, of which 7 were caught at once and the
  eighth, the boundary of the letters minimum, after one more test.
- Two differences from the plan's wording. (1) The counts of points and verified points are not in the card's generation
  record, because the validator of a card requires the record to have exactly its keys; they are in the result of
  `make_model_part` and in the `cards` report, and increment C, which changes the card format, puts them in the record. (2) A
  book of one piece is also given its text in the card call, besides its notes, so that a short page does not lose detail.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: a quote that is too long (over 240 characters, up to a
  shape limit of 600) now makes its point unverified and no longer refuses the whole reply, as criterion 3 says; a quote copied
  across a line-end hyphen is now matched when its line break has become a space, as it does in a cleaned reply (the rule is a
  hyphen between two letters followed by white space); a quote must hold at least eight letters or digits, so a run of dots or
  dashes does not pass; the prompt now says not to quote "the title or a heading" and "marked unverified". Limits recorded and not
  changed: an empty quote still refuses the reply, since the shape layer refuses empty text; a quote of a heading occurs, since a
  heading is a block of the piece, so the engine cannot refuse it; word-by-word normalisation is done twice for each point, a cost
  and not a risk.
- Do not run increment E on this state: the card call receives `[N.K verified]` lines that the v2 card prompt does not explain,
  and a one-piece book gets both its text and its notes. Increment C changes the card prompt and the card format.
- Committed as `2357614`.

### Increment C — A card that is grounded in the notes (built; not committed)

- Built card format 2 in `engine/kb/card.py` (the `grounding` record with a mark, notes and quote for each topic, key idea, caveat
  and neutral limit, and the number dropped for each; higher ceilings of 20 topics and 8 key ideas; key ideas may be few; the
  neutral limit may be empty; optional `points` and `verified` counts in the generation record of a notes call; the quote of a
  stated item rendered under it as untrusted text), the card job at v3 in `engine/kb/cardmake.py` (support lists, the check that
  refuses a support of a wrong form or length, `parse_support`, `ground`, the new prompt with the kind word), the card schema,
  tests (`test_card.py`, `test_cardmake.py`, and a class in `test_catalog.py` for the catalog reading cards of both formats), the
  statements of `docs/specs/card.md` and a README bullet. A card made without a grounding record is still format 1, and a card of
  format 1 is read, searched and shown as before. The counts that increment B reported only in the `cards` report are now in the
  generation record, which closes the difference noted there.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_card engine.tests.test_cardmake
  engine.tests.test_catalog engine.tests.test_quotes` gave 282 tests, OK; `python3 -m unittest engine.tests.test_models
  engine.tests.test_trial engine.tests.test_cardsample engine.tests.test_setup` gave 218, OK, since those read cards or use the
  card fixtures; `wb run code-work check` found no problems. Not run: any other test file, and any live model call.
- Deliberate breaks, each from a green baseline: 41 (18 of the card format, 23 of the marking and prompt). 37 were caught at once;
  four survived (a note cited twice, the tool name recorded for a payload, the kind word reaching the prompt, the wording that lets
  the model give fewer key ideas) and a test was added for each, after which each was caught. The tests of the card format were
  written before the code; the cardmake tests too, apart from the fixtures that the new reply shape changed.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: the reason a thin card gives said that the key ideas left
  were "supported by a quote", which is wrong for an inference; it now says how many key ideas were left after the ones without
  support were dropped. Recorded, not changed: (1) the engine's check cannot tell whether a verified note supports the item that
  cites it, so a model that cites one verified note for every item keeps every item, and the quote shown beside an item may be
  unrelated to it; (2) `inferred` is the model's own word and is not checked, so the drop rule bites only on items cited with
  unverified or missing notes or marked `none`; the marks that come from the engine alone are the `stated` ones; (3) a support
  value in a slightly wrong form (a trailing full stop, `inferred 1.1`) refuses the whole card answer, which is kept aside; this
  follows the plan and errs on the safe side. Increment E should report how often each happens: the share of items that are
  `inferred`, the labels of `stated` items whose quote does not bear on them, and the number of refused card answers.
- Not run on a real book: the card prompt, the support lists and the marking have been run only against fake model replies, so
  nothing is known yet about how often local models give a quote that verifies, cite correctly, or write a support in the form
  asked.
- Next: the owner's word to commit increment C; then D (the marks in `card-show` and in the result of `card-search`).
