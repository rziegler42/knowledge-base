# Making the cards accurate

Status: Completed
Created: 2026-11-07
Candidate: cards#card-grounding
Specs: card

## Goal

The owner knows how accurate the cards are, and the cards are more accurate. When this is done, a card is made from notes in which
every point carries a short verbatim quote that the engine has checked against the piece it names; the card's key ideas, topics,
caveats and limits name the notes that support them (the summary and the other neutral fields are measured, not marked); each such
item that is kept is marked stated or inferred, and what is neither is dropped; an item is stated only if the note it cites is
verified, bears on the item and is confirmed by a second model to support it; the marks are
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
- A check that the note an item cites supports the item: a mechanical test that they share a content word, and then one call to a
  second model, named in the owner's config as the task `card-check`, for each ten items. Only an item that passes both is stated.
- A new card format that carries the marks; cards of the old format stay readable and are shown as not checked.
- A prompt with higher ceilings for key ideas and topics, the right word for the kind of source, and no mention of the pipeline's
  notes in the card.
- The marks in `card-show` and in the result of `card-search`.
- A live run on the 12 carded books as a new generation, the labelling of a blind sample of old and new items by a strong model
  and of a calibration subset by the owner, and a written comparison with the owner's decision on what comes next.

## Non-goals

- A further round by a second model when a list is full or an item's support is weak, agreement across two runs of the notes, and a
  higher cap on the pieces sampled from a long book. They are deferred until the labelled sample shows that they would pay (see
  Deferred work). The check of the note an item cites is not among them: it is increment D-A.
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
- The first live run of the grounded card (see the Result of increment E) showed that the engine's check of the quotes does not
  show that a cited note supports the item that cites it: the card call cited one note for nearly every item. Increment D-A adds
  the check that does. The owner names the model for it, which should not be the model that writes the card, by setting
  `tasks.card-check` in the config; the engine names no model and, as for the other tasks, refuses to make a card before any call
  if the setting is missing. The items, the notes' points and the quotes go to that model, as the text of the book goes to the
  other two.
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
8. An item that cites notes is marked stated only if one note it cites is verified, shares a content word with the item, and a call
   to the `card-check` model answers that the note's point and quote support it; an item that fails any of these three is dropped,
   not marked inferred; the check is tested against replies that reject the items an unrelated note was cited for, the generation
   records carry the counts checked and supported, and a missing `card-check` setting is refused before any call.

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

### Increment D-A — A mark must mean that the note supports the item

**Outcome:** an item of a card is `stated` only if a verified note that it cites shares a content word with it and a second model,
given the item with that note's point and quote, says that they support it; any other item that cites notes is dropped.
**Dependencies:** D.
**Affected areas:** `engine/kb/cardmake.py` (the pairs, the check calls, `ground`, the card prompt), `engine/kb/models.py` (the new
task `card-check`), `engine/kb/card.py` (an optional pair of counts in a generation record), `engine/kb/cardsample.py` and
`engine/kb/__main__.py` (`card-sample --book`), `engine/kb/schemas/` (the schema of the new job), `docs/specs/card.md`,
`engine/README.md`, and the tests `test_cardmake.py`, `test_card.py`, `test_models.py` and `test_cardsample.py`.
**Steps:**
1. Write the tests first, on hand-made replies. The mechanical test: an item that cites a verified note sharing no content word
   (a word of four or more letters outside a short list, compared by its first five letters) with the note's point and quote has no
   pair and is dropped; one that shares a word has a pair; an item with no content word has a pair, for the model to decide; of
   several verified notes the one that shares most words is the pair's note, and the first on a tie. The check call: the pairs go
   in batches of ten, each batch in one section of data with the item, the number of the note, its point and its quote; the reply
   has one verdict for each pair, each `supports`, `partly` or `no`, and any other word or any other length refuses the answer,
   which is kept aside; only `supports` confirms, and `partly` and `no` drop the item; an item the model calls an inference is not
   sent; no pairs, no call. `ground`: a confirmed item is stated, with the confirmed note as its only note and that note's quote;
   an item that cites verified notes and is not confirmed is dropped; the thin-card rule is as before. A card call that cites the
   same verified note for every item, with a checker that rejects the unrelated ones, keeps only the related ones. Settings: a
   missing `tasks.card-check` is refused before the first call, with the key to set. Records: the check calls carry `checked` and
   `supported`, only as a pair and only in a grounded card, and a grounded card made before this still validates. The card prompt
   asks for the one or two notes that best state each item and not for a note that is only loosely related.
2. Add `card-check` to the tasks the engine knows; write the pairs, the mechanical test, the prompt of the check, its job and
   schema, and the confirmation in `ground`; move the card prompt to v4; add the counts to the generation record and the figures
   `checked` and `supported` to the report of `cards`.
3. Add `--book` (repeatable) to `card-sample`, which the function already takes, so that a sample can leave out a book: the first
   live run made a generation-2 card of one book before this increment, and it is not comparable with the cards made after it.
4. Update `docs/specs/card.md` (a stated item is one whose note a second model confirmed to support it) and `engine/README.md`
   (the task `card-check`, the pairs, the verdicts and what is dropped).
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models
engine.tests.test_catalog engine.tests.test_quotes engine.tests.test_trial engine.tests.test_cardsample`, since the task list and
the card record are shared; deliberate breaks of the mechanical test, the batching, the forms of a verdict, the confirmation, the drop
of an item that is not confirmed and the refusal of a missing setting.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#D-A`.

### Increment E — A live run, the labelled sample and the comparison

**Outcome:** a blind sample of old and new items is labelled by a strong model and a calibration subset by the owner, the plan
records what the numbers show and how far the two labellings agree, and the owner has decided what comes next.
**Dependencies:** A, B, C, D and D-A. It needs the owner's setting of `tasks.card-check`, the owner's word on the books, on sending
their text to the local models, on sending the sample's items and passages, and the whole text of a few books for the second look,
to a cloud model, and on the time to label the calibration subset.
**Affected areas:** the owner's library (a new card generation for the books named, the catalog), files outside the repository,
and the plan's Result. No tracked file other than the plan changes.
**Steps:**
1. Propose the books to the owner (the 12 carded books are the natural choice), the size of the sample (about 80 items) and of the
   calibration subset (about 15), and say what it costs: about twice the calls of the first run, because of the notes stage for
   every book, and one more call for each ten items that cite a note; a cloud model reading the items and passages; and the owner's
   time for the subset only. The page that the first live run carded (generation 2, made before D-A) is left out of the comparison.
   Wait for the owner's word.
2. Run `cards --again` for the books named, a few at a time. Record, for each book, the calls, the points and the share whose quote
   verified, the items marked and dropped, the items checked and the verdicts (`supports`, `partly`, `no`), and every failure; a refused answer is kept aside and read. If fewer than half of the
   quotes verify on a book, stop and report before going on: the check may be failing for a reason of conversion, not of the model.
3. Run `card-index`, then `card-sample` drawing from generations 1 and 2 of the books named with `--book`. The key file is kept by me and is not given to the labeller
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
engine.tests.test_cardmake engine.tests.test_card engine.tests.test_catalog engine.tests.test_trial engine.tests.test_models` once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-grounding#E`, which holds the plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After E, rerun once
`python3 -m unittest engine.tests.test_cardsample engine.tests.test_quotes engine.tests.test_cardmake engine.tests.test_card
engine.tests.test_catalog engine.tests.test_trial engine.tests.test_models engine.tests.test_setup`. The wider engine suite is not
named: the plan changes the card format, the notes and card jobs and the list of tasks, and adds three commands, but no stage, no index and no store. The risk a wider run
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

- **A third model reads items, notes and quotes.** The `card-check` model is named by the owner and is reached over the registry's
  link as the others are; without the setting the engine refuses to make a card. It can be lenient or wrong: the labelled sample in
  increment E measures how many of the items it let through are unsupported, and the share it rejected is recorded.
- **More calls and a stricter card.** The check adds a call for each ten items that cite a note, and items it does not confirm are
  dropped, so cards will hold fewer topics and key ideas and more of them may be thin. That is the intent; E reports it.

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
- Amendment, 2026-11-07, after the first live run (see the Result of increment E): increment D-A and the changes it needs in the
  Goal, Scope, Non-goals, Assumptions, Completion criteria (criterion 8), Increment E, the verification for the whole plan, the Risks
  and the Deferred work. The amendment was written for the owner's new approval and has not been through a round of the review.
- Left for the owner: whether to ask for a further round of review (the bound is reached; extending it is the owner's level
  `ask`) or to approve the plan as it stands.

## Deferred work

- A further round by the second model when a list is full or an item's support is weak, tested against the owner's labels before it
  is trusted; agreement across two runs of the notes; and a test of whether covering every piece of a long book
  improves accuracy before the cap of twelve pieces is raised. Increment E ends with a recommendation on each.
- A second trial on harder questions and more books, to see whether more accurate cards find more.
- Search by meaning and themes, which the card trial decided against for now.
- A threshold below which a card is marked partial for having few verified claims, until the share that verifies is known.

## Result

### Increment A — Measuring the accuracy of the cards (committed)

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

### Increment B — Notes with quotes that are checked (committed)

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

### Increment C — A card that is grounded in the notes (committed)

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
- Committed as `dca5ce5`.

### Increment D — The marks where a reader sees them (committed)

- Built in `engine/kb/card.py`: the rendering of a card of format 2 shows `[stated]` or `[inferred]` after each topic, key idea,
  caveat and neutral limit, a card of format 1 that has a model part carries one line `grounding: not checked`, and
  `grounding_counts(card)` gives `{"stated": n, "inferred": n}` or `"not checked"`. In `engine/kb/catalog.py` each search result has
  a `grounding` field from it. Search is unchanged: the marks are not indexed, a search for the word `stated` finds nothing, and
  two cards that differ only in format get the same score, matches and excerpt (tested). Tests in `test_card.py` and
  `test_catalog.py`, README text and one statement in `docs/specs/card.md`, which the plan does not list for this increment but which
  states what is true now.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_catalog engine.tests.test_card
  engine.tests.test_trial` gave 202 tests, OK; `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake
  engine.tests.test_cardsample engine.tests.test_quotes engine.tests.test_models engine.tests.test_setup` gave 311, OK;
  `wb run code-work check` found no problems. Not run: any other test file, and any live model call.
- Deliberate breaks, each from a green baseline: 11 of the rendering, the counts and the result field (all caught), then 5 of the
  rule added after the review (all caught). The tests were written first and failed.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: text of a card that looks like an engine mark (`[stated]`,
  `[inferred]`, with spaces or capitals) could be read as one, in an item with no mark or beside a real one; it is now shown with
  round brackets, by the one function that every shown card text passes through (`_shown`), so titles, excerpts and quotes too.
  Item text cannot start a line, since white space is collapsed, so the lines of a card cannot be forged. A test was added for a
  card of format 2 whose topics together hold the words of a marker (the whole line is withheld, with no marks); the code was
  already right and the test fixes it.
- Outside the plan's list for this increment: (1) the sentence in `docs/specs/card.md`, as above; (2) one test of `trial`
  (`test_trial.py`) opened a database with `with sqlite3.connect(...)`, which commits but does not close, and left a
  `ResourceWarning: unclosed database` at the end of the run; it is a defect of a test of mine from the trial plan, found when I ran
  with warnings as errors, and it now closes the connection.
- Next: the owner's word to commit increment D. Then E, which needs the owner's word on the books, on sending their text to the
  local models again, on sending the sample's items and passages (and a few whole books for the second look) to a cloud model, and
  the owner's time to label about 15 items.
- Committed as `710d7c6`.

### Increment D-A — A mark must mean that the note supports the item (committed)

- Built in `engine/kb/cardmake.py`: `pairs` (for each item that cites notes, the verified note it cites that shares most content
  words with it, by the first five letters of words of four letters or more, the first cited on a tie; no such note, no pair, and
  the item is dropped; an item with no content word of its own is paired with the first verified note it cites), `check_prompt` and
  `check_job` (one verdict, `supports`, `partly` or `no`, for each pair, ten pairs to a call; a wrong word or count refuses the
  answer and it is kept aside), `ground(values, notes, confirmed)` (an item is stated only if the check confirmed it, with the
  confirmed note as its only note and that note's quote), the card prompt at v4 (the one or two notes that best state each item,
  none that is only loosely related), `unpaired`, and the report fields `checked`, `supported`, `partly`, `no` and `unpaired`. In
  `engine/kb/models.py` the task `card-check`; in `engine/kb/card.py` a generation record may carry the pair `checked`/`supported`
  (or `points`/`verified`, not both), in a grounded card only; the schema `card-check.json`; `card-sample --book`; the spec and the
  README. `cards` now checks all three tasks before it tries any book.
- Verification as run: `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardmake engine.tests.test_card
  engine.tests.test_models engine.tests.test_catalog engine.tests.test_quotes engine.tests.test_trial engine.tests.test_cardsample`
  gave 516 tests, OK; `python3 -m unittest engine.tests.test_setup` OK; `wb run code-work check` found no problems. Not run: any
  other test file, and any live run of the check (the first live run was before D-A, with the old design).
- Deliberate breaks, each from a green baseline: 25 of the pairs, the check call, the marking and the record (23 caught at once; two
  survived, words of three letters counted as content words and verdicts not read without regard to case, and a test was added for
  each, after which both were caught), then 5 of the changes made after the review (all caught). The tests were written first and
  failed.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: the spec and the README said that the marks never come from
  the card model's word, which is false for `inferred`; they now say that a `stated` mark comes only from the checks and that
  `inferred` is the model's own unchecked word. The report of `cards` now also gives `partly`, `no` and `unpaired` (the items that
  cite notes but had no pair), which E step 2 needs. `cards` checks all three tasks before it tries any book, so a missing
  `card-check` refuses the command and does not report each book as failed.
- Recorded, not changed, for E to measure: (1) `inferred` is unchecked, so a card model can keep items by calling them inferences;
  E should report the share of items that are inferred; (2) the mechanical test drops a topic that is an alias sharing no
  four-letter word with its note, though the prompt asks for other names of an idea, so fewer topics are to be expected; (3) a
  caveat or a limit is a claim about the source or where the book would not work, which a quote rarely states, so more of them
  will be dropped or marked inferred; (4) the check prompt says an item is supported if the point and quote "state the item or
  clearly lead to it", which is more lenient than "support", and gives no separate guidance for caveats and limits; (5) one verdict
  reply with a wrong word or count fails the whole book (its answer is kept aside); (6) a list of verdicts of the right length
  but in the wrong order cannot be detected; (7) a verified quote that holds an instruction can steer the checker as any text in a
  data section can, which is the exposure the notes and card calls have too; (8) the card prompt does not tell the model that an
  item sharing no word with its note is dropped, which I chose not to say so as not to teach the model to pad items with words.
- Next: the owner's word to commit this amendment and increment D-A; then the owner's setting of `tasks.card-check`, and E.

### Increment E — A live run, the labelled sample and the comparison (run; not committed)

- On the owner's word to start E I ran `cards --again` for one book, a web page of two pieces, as a new generation (generation 2;
  generation 1 is unchanged). Three calls, about 45 seconds. The notes had 8 points, and 7 of the 8 quotes were found in their
  piece (88%), well above the stop line of half. No answer was refused. The card has 12 topics, 7 key ideas, 3 caveats and a limit,
  and is not partial.
- **Finding: the marks do not mean what the card says.** The card call cited note 1.2 (or 1.1) for all 19 kept topics and key
  ideas, so all 19 are marked `stated` and none was dropped, and the quote shown beside each of the seven key ideas is the same
  sentence, which bears on only one of them. The three caveats and the limit were marked `inferred`. The engine checks that a quote
  is in the book and not that the note it belongs to supports the item that cites it; a model can keep every item by citing one
  verified note. This is the limit that the review of increment C recorded; the first real run shows it is not a corner case. Fake
  model replies in the tests could not have shown it.
- I did not run the other eleven books or draw the sample: more cards of this kind would have marks that read as support and are
  not, and the labels would then measure a design that is already known to be weak. The library now has one card of generation 2,
  so the catalog (built before it) is stale for that book until `card-index`, and `trial` refuses a stale catalog.
- The owner chose to add a mechanical check of the cited note and a check by a second model; this became increment D-A, written as an
  amendment to the plan for the owner's new approval. E resumes after it.
- **The check model was chosen by a test.** On the owner's word `phi4:latest` (the registry entry `local`) was set for `card-check`
  after a bake-off: 30 hand-labelled pairs (23 firm labels; real card items and real sentences of the books, including the six
  unrelated key ideas of the first live run) were put to four variants of local model with the engine's own prompt and reply rules,
  twice each. All four said `no` to the six unrelated key ideas. `phi4` never said `supports` where the label was `no`, found every
  real `supports`, was never refused, and gave the same answer on both repetitions (19 of 23 firm labels correct, its other errors
  softer: `partly` for `no`, `no` for `partly`, and one `partly` passed as `supports`). `gemma4:12b`, which also writes the notes,
  passed an unsupported item (the O(n squared) claim backed by a sentence about recurrence) in both repetitions. `qwen3:14b` with
  thinking off was refused on one of three calls in both repetitions (a wrong number of verdicts); with thinking on it was the most
  accurate (21 of 23) but 10 to 25 times slower and not fully consistent. The test is small and the labels are mine.
- **The local run.** `cards --again` for 11 books (the page carded before D-A was left out). First pass: 7 carded and 4 failed; a
  second try of the four carded 2 more. 9 of 11 books have a card of generation 2 (note quotes verified 65 to 89 percent; the
  checker supported 63 to 93 percent of the items put to it; one card, of the longest paper, is thin). Two books failed twice. Of
  the 15 card calls made over the two passes, 5 were refused for format by the card model (`gpt-oss`): three times a list of
  supports with fewer entries than its list of topics (12 topics against 5 to 7 supports), once more than 8 key-idea supports, and
  once (a notes call) a point 9 characters over the limit of 240. A refused answer fails the whole book, and the engine retries
  nothing. A fix that makes a mismatch impossible (the support written with its own item) would change the design and needs the
  owner's approval of an amendment; it is not made.
- **The sample.** `card-index` was run (12 cards). A first sample of 80 items had only 23 in the four fields the pipeline changes
  (the draw takes fields in turn and six of nine fields are unmarked), too few to compare; it was replaced by a sample of 300 items,
  150 from each generation of the nine books that have both, 181 of them in topics, key ideas, caveats and the limit. Both are held
  outside the repository. Nothing has been sent to a cloud model.
- **The labelling.** With the owner's word, six cloud-model subagents (Opus class) each labelled 50 of the 300 items, given the
  items file, the rubric and the passages, and not the key, the generation or the plan's reading of the old cards (300 of 300
  labelled, no format problem). 143 labels carry a note. The owner labelled the 15 calibration items blind, through a private page
  that showed the same passages and no model label.
- **Accuracy by generation** (`card-accuracy`; skipped items are left out of the shares):

  | | generation 1 (old) | generation 2 (grounded) |
  |---|---|---|
  | items / skipped | 150 / 6 | 150 / 3 |
  | supported | 41.7% | 62.6% |
  | inference | 17.4% | 8.2% |
  | unsupported | 41.0% | 29.3% |

  By field, generation 1 to 2 (supported of items): topics 27/30 to 39/40 (one skipped in each); key ideas 12/26 to 26/37;
  caveats 0/27 to 1/8; the limit 0/9 to 0/4; summary 9/22 to 10/25; the four other neutral fields 12/36 to 16/36. Topics and key
  ideas, the fields the pipeline checks, rose; key ideas also lost the weakest items (unsupported 8 of 26 to 6 of 37). The fields it
  does not mark did not improve: summary and the neutral fields are written from the whole outline, as before, and `neutral_needs`
  and the limit remain almost all unsupported. Caveats and the limit are claims about where the book would not work, which a passage
  rarely states; they are nearly all `inferred` and nearly all unsupported.
- **The marks.** In generation 2, `stated` items of topics and key ideas: of 73 judged, 64 supported (88%), 5 inference and 4
  unsupported. `inferred` items (caveats, the limit, a few key ideas and one topic): of 13 judged, 2 supported, 1 inference and 10
  unsupported (77%). So `stated` means what it says, and `inferred` is a mark for items to distrust.
- **Agreement with the owner.** On the 15 calibration items the model and the owner agreed on 12 (80%): all 7 the owner called
  supported and 5 of the 7 the owner called unsupported (the owner's one inference was not matched). The three differences were all at the edge between
  inference and unsupported (two items the model gave inference that the owner called unsupported, one the owner called inference
  that the model called unsupported), in both directions. No item was supported to one and unsupported to the other. With 15 items
  this is a rough estimate; the supported and unsupported shares carry the sample, and the inference share is approximate.
- **The second look.** The 5 calibration items that both the model and the owner called unsupported were given, with the whole
  converted text of their book, to one Opus-class labeller each under the same rubric. All 5 stayed unsupported, so no retrieval
  miss was found among them (0 of 5, the sample being small). In four the book states part of the item and not an added clause:
  "high safety requirements", "real-time inference on limited hardware" (the book shows the opposite for small datasets),
  "especially on long sentences" (true only against a weaker baseline of the same paper) and "careful architectural choices" (the
  paper argues for the fewest possible changes); the fifth is a generic caveat about age. One labeller searched for terms and read the
  relevant section and not the book end to end. Note for a next design: the commonest error is a true statement with an unsupported
  extra clause, which neither the quote check nor a check of the item as a whole catches; a check clause by clause would.
- **Search again.** `trial` on the same corpus (same hash) into a new report, 15 questions: the neutral search found 13 questions
  (before 11), rank 0.87 (0.70), books found 15 (13); the card and summary searches found 13 (14), rank 0.82 (0.89), books found 15
  (16); one question is now found by the text search only. The cards are 251 words on average (281). Nine of twelve books have a new
  card, so old and new cards are mixed, and one or two questions are within noise. The earlier decision (neither search by meaning
  nor themes for now) is unchanged.
- **Failures and cost.** Of 11 books, 9 got a new card; two failed twice on the format of the card model's reply (support lists of
  the wrong length, one over the ceiling, and a note point 9 characters over its limit). A failed book keeps its old card, so no
  wrong card is made, but coverage is lost and a refused answer is not retried. Time was 25 to 136 seconds per book on the local
  models; quote verification 65 to 89 percent; the check supported 63 to 93 percent of the items put to it.
- **Limits.** Twelve books, nine in the comparison; 300 items by one labeller class, checked against the owner on 15 and the books on
  5; the owner's labels and the bake-off labels are one person's; the labeller sees at most five passages, so a statement whose
  support is elsewhere counts as unsupported (the second look found none such among 5); the unmarked fields were not changed.
- **Recommendation and the owner's decision.** The owner chose to record the following as candidates for later plans and not to
  amend this plan: (1) support written with its own item, and a longer note-point limit, so that a format slip does not fail a
  book; (2) a check clause by clause, since the commonest error is an extra clause; (3) the same grounding for the summary and the
  neutral fields; (4) treat `inferred` items as untrustworthy in display or search (drop or hide them), for the owner to decide;
  (5) a queue per model so that loading a model is paid once for many books. None is made here; adding a candidate to a roadmap
  waits for the owner's word.
- Provenance: run on this repository at commit `674ea3d` plus the uncommitted plan edits, in the owner's library, with local models
  `gemma4:12b` (notes), `gpt-oss:20b` (card), `phi4:latest` (check) through the owner's bridge, and cloud-model labellers (Opus
  class) for the 300 items and the 5 whole-book looks; the sample, its key and the labels are held outside the repository.
