# Check the shelf matcher on the library's own books

Status: Proposed
Created: 2026-11-14
Candidate: none (the shelves, the fetch engine and the crawler are outside every roadmap, which say so; creating a roadmap for them is the owner's change of direction, and this plan is the evidence the owner asked for at the end of the plan `2026-11-14-measure-the-shelf-matcher`)
Specs: docs/specs/shelf.md, docs/specs/card.md

## Goal

The plan `2026-11-14-measure-the-shelf-matcher` measured the matcher on OpenAlex papers, with OpenAlex's own label as the truth. It found that embedding with `qwen3-embedding:4b` and a choice among the five nearest shelves by
`gemma4:12b` (prompt `place-1`) places 58.7 percent of 300 papers on the exact topic and 77.0 percent in the right field. The owner's reading was to accept that as a way to count, and **not to rely on one placement downstream until it has been checked on
the library's own books**, which is where the matcher is used (the spec places a paper that carries an OpenAlex topic by that topic, without the matcher). When this plan is done:

- there is a sample of the library's books (web pages and preprints), each with a short text made from its card by a rule fixed in advance;
- each of those books has been placed by the same pipeline as before (the five nearest shelves by the qwen vectors, then the model's choice), with nothing tuned;
- **the owner has marked, for each book, which of the five offered shelves is the best home, which others would also do, or that none does**, and the marks are recorded as given;
- the Result gives the figures of the marks (how often the model's choice is the owner's best, how often it is acceptable, how often the embedding's nearest shelf is, how often none of the five fits), split by kind of book, beside the figures for papers, with the sample's size said plainly;
- the owner has read the result and says what comes next.

## Scope

- A rule that makes one text from a card (title, summary and topics), and a sample of 40 books drawn by a fixed seed: 30 web pages and 10 preprints.
- One embedding of the 40 texts with the qwen entry already used (the 4,816 shelf vectors saved by the earlier plan are reused, after their hashes are checked), the five nearest home shelves of each book, and the choice of `gemma4:12b` with the same prompt.
- A sheet for the owner to mark, in batches of ten, and the report of the marks.
- Scripts and files held outside the repository and cited by hash, as in the earlier plans.

## Non-goals

- Any change to the library, the cards, the shelves of a book (a book's `shelf` field is not changed), the schema, the spec of shelves or a roadmap; no command in the engine; no filing or reshelving.
- Tuning: another model, prompt, text rule or number of candidates tried and picked by the marks. A variant is a new plan with a new sample.
- Placing all 175 books, the books' text beyond the card, the accuracy of the cards themselves, the state of a shelf, scouting, `schema-adopt` and the fetch engine.
- A security review of the scripts (they send text through the engine's own calls and read the library read-only; none is asked for).

## Assumptions and constraints

- **What the library holds** (read on 2026-11-14 from the catalog of cards, read-only): 175 current cards for 175 books, 135 web pages and 40 preprints; the card's summary is 203 to 645 characters (median 467); one card has no summary. The card is written by models from the book and is the library's own derived text, which is the only short text each book has.
- **The text rule (fixed here, not tuned):** `<title>. <summary> Topics: <topic 1>; <topic 2>; ...` made from the newest current card of the book, cut to 1,500 characters, with the same cleaning of control and hidden characters as for the papers; **the summary is the card's own summary field, in the source's vocabulary (the summary side of the card), and not the
  neutral fields**, which are written to cross fields and would blur the field. A book whose card has no summary, or a text under 100 characters, is left out and counted.
- **The population is saved before anything is drawn.** A script reads the catalog read-only and writes a **manifest** (a file of mode 600, hashed) with one line for each book that has a current card: the book id, its kind, **the identifier of the card generation used (the newest current card), the hash of the card's text fields the rule uses**, and whether the book is eligible (a summary and a text of at least 100 characters) or why not. **The draw operates on that manifest alone** (the eligible books sorted by book id), so that anyone with the manifest can repeat the draw and anyone can see that the library has not changed under it; the sample file records the manifest's hash.
- **The sample:** a seed of 1 for the draw of 30 of the eligible web pages and 10 of the eligible preprints from the manifest, in the order of the manifest; preprints are 10 of 40 and web pages 30 of 135, so each kind has enough books to read and the preprints are over-sampled (reported apart). **The draw also makes a reserve: the next 5 books of each kind in the draw's order.**
- **A book the owner drops** (after seeing the titles, before anything is sent, for any reason the owner gives, which is recorded) **is replaced by the next book of the same kind in the reserve, in order**; the sample stays 30 and 10. The owner may drop at most 5 books in all; a larger change, or **adding a book the owner names, is an amendment of this plan and needs the owner's new approval.** After the send, a book is not dropped: one the owner cannot judge is recorded as skipped with the owner's word and is not counted, and the report says how many. 40 books are a small sample: **a share of 0.75 has a 95 percent interval of about plus or minus 13 points**, so the plan can show a large failure or a clear success and not a small difference.
- **The pipeline is the earlier one, unchanged:** the embedding entry `embed-qwen` with no prefix (documents), the shelf vectors of `vectors-qwen` (schema hash and shelf texts checked), the five nearest home shelves by cosine, the prompt `place-1` to the `gemma` entry (`gemma4:12b`, thinking off) with the strict answer reader. The scripts of the earlier plan (`run_embed.py`, `run_choice.py`) are imported, not changed.
- **What is sent to the model server.** The texts of the 40 books (the library's own derived text, made from web pages and arXiv papers that the owner chose to keep; every book is on the one `default` shelf today) go to the embedding entry and then, in a prompt, to the chat entry, on the owner's network, over plain unauthenticated http, in the clear: **the same exposure as when the cards were made, but these are the owner's choices of reading and not public samples**, so the owner says "run it" before the send, is told what and how much, and may drop a book from the sample first. Nothing else of the library is sent, and no label or mark.
- **The owner's marks are blind.** Each book is shown with its title, its address and its summary, and the five offered shelves in alphabetical order (each with its path, domain, field, subfield and topic, and its scope sentence); **the sheet does not show which shelf the model chose, which the embedding found nearest, or any score or rank**, and the books are shown in an order that does not follow their kind or the model's answers (shuffled by the seed). The marks are compared with the model's choice only after the owner has given every batch and the file of marks is final; **a mark is not changed after the comparison**. For each book the owner gives: **`best`** (the number of the one shelf that is the best home among the five, or `none` if none of the five is a fair home), and **`also`** (the numbers of other shelves that would be acceptable, if any). The owner is asked to judge by the book, not by the card's summary. The marks are given in a message, in batches of ten, and are copied into the Result as given.
  **A mark is valid** only if `best` is a number from 1 to 5 or `none`; `also` is a set of numbers from 1 to 5, each once, not holding the best; **`also` must be empty when `best` is `none`**; every book of the batch is marked once; a skipped book carries the owner's word instead. A mark that is not valid is refused and asked again.
  **The figures** from the marks, each over **the marked books (the skipped ones are left out and counted)** unless it says otherwise, with the denominator printed:
  - *strict*: the model's choice is the owner's best; **if the model said `none` and the owner's best is `none`, that is right; if only one of them said `none`, it is wrong**;
  - *lenient*: strict, or the model's choice is one of the owner's `also` shelves;
  - *nearest*: the embedding's nearest shelf is the owner's best (wrong when the owner's best is `none`);
  - *ceiling*: the owner's best is a shelf (not `none`), the share of books for which one of the five is a fair home;
  - *model `none`*: the count of books where the model said `none` (and, apart, of those where the owner's best is also `none`);
  - *field*: the field of the model's choice is the field of the owner's best, **over the books where both are shelves**, with the number of books left out because one of them is `none` printed beside it;
  - each by kind of book (web page, preprint), and the main figure with an exact (Clopper-Pearson) 95 percent interval, **given as a rough guide and not as an inference: the interval assumes a random draw, and the owner's drops (before the send) and skips (after it) may be tied to a book's subject or difficulty**, so the figures describe the books judged;
  - **the whole drawn cohort is reported**: every book drawn, dropped (with the owner's reason and the replacement) or skipped (with the owner's word), and **a sensitivity figure that counts every skipped book as a wrong choice** beside the primary figure; if the two readings of the bar differ, the Result says so and the bar is read as not met.
- **The bar (my guess, the owner's to set before approving):** the choice step is good enough to rely on for books if **at least 75 percent of the model's choices are the owner's best or acceptable (lenient)** and **at most 15 percent of the books have no fair home among the five**; and it is **close** within five points. These numbers are guesses: nothing in the project says what the library needs. The strict figure and the comparison with the nearest shelf are reported whichever way they fall.
- **Order of work:** tests before code for every script, deliberate breaks of each script, and the `reviewer` agent's reading of each Result, as in the earlier plans.
- The scripts use the standard library and the engine's own modules; the engine's `catalog` is opened read-only; no file of the library is written.

## Completion criteria

1. The text rule, the manifest of the population (with the card generation and the text hash of each book), the sample, the reserve, the books the owner dropped with the owner's reasons and their replacements, and the counts of what was left out are recorded with the hashes of the manifest and the sample file; the rule was fixed before the manifest was made and the manifest before the draw.
2. The 40 texts were embedded, the five nearest shelves made, and the choice made, with the entries, the prompt version, the dimension and the times recorded, and the files cited by hash; nothing in the pipeline was changed from the earlier plan.
3. The owner marked every book of the sample **blind to the model's choice** (`best` and `also`, or `none`) and the marks are in the Result as given and final before they are compared; a book the owner could not judge is recorded as skipped with the owner's word, and is left out of the primary figures and counted as wrong in the sensitivity figure.
4. The report gives each figure with its denominator and a rough interval for the main one, split by kind of book, beside the paper figures, with the whole drawn cohort (every drop, replacement and skip with its reason) and the sensitivity figure, and with a recount of the figures by a snippet that does not use the report's script.
5. The owner has read the result against the bar and says what comes next.
6. `wb run code-work check` finds no problems, and nothing outside this plan changes in the repository.

## Increments

### Increment A — The text rule and the sample (no send)

**Outcome:** the rule that makes a book's text from its card, and the sample of 40 books, are fixed and recorded; nothing has been sent.
**Dependencies:** none (it reads the library's catalog read-only).
**Affected areas:** outside the repository only: a script, its tests and breaks, the sample file (mode 600); the plan's Result.
**Steps:**
1. Write the tests first and see them fail: the text rule (the title, the summary and the topics joined as above, cut to 1,500 characters, with control and hidden characters removed, an empty or missing summary left out with the reason), the draw (30 and 10 by kind, by the fixed seed, the same draw twice, a different seed a different draw, refusal when a kind has too few books), the read of the catalog (read-only: a test that the file is not changed and is opened with the read-only mode; the newest current card of a book only), and the output file (new, mode 600, never over one).
2. Write the script in two steps. **First** it reads the catalog read-only and writes the manifest (every book with a current card: id, kind, the card generation, the hash of the card text it uses, eligible or why not); the manifest is hashed and recorded before the second step. **Second** it draws from the manifest alone: 30 and 10 by the seed, the reserve of 5 of each kind, the texts made from the cards of exactly the generations the manifest names (a card that has changed since, by its text hash, stops the script); it writes `books-sample.json` with, for each book, its id, its kind, its title, its address, its summary, its text and the manifest's hash, and nothing the owner would use to mark by other than what the sheet shows; it records the counts of books and of those left out and why.
3. Deliberate breaks (the rule, the cut, the draw's counts and order, the kind, the seed, the read-only open, a missing summary, the output's mode and replacement) and their restoring.
4. Show the owner the rule and the 40 titles and kinds, and **wait for the owner to say whether any book is to be dropped** (up to 5, each with a reason, each replaced by the next of its kind in the reserve; the replacements are shown); a change beyond that, or a book the owner wants added, is an amendment and stops for the owner's new approval of the plan.
5. The `reviewer` agent reads the script, its tests and the sample's counts.
**Verification:** the script's tests and breaks, the sample's counts recounted by a second snippet from the catalog, `wb run code-work check`.
**Evidence:** the one local commit, which holds the plan's Result and Review record for A, with the trailer `Plan: 2026-11-14-check-the-matcher-on-the-librarys-books#A`; the script and the sample are outside the repository and cited by hash.

### Increment B — The five nearest shelves and the choice (sends the 40 texts)

**Outcome:** each book of the sample has its five nearest shelves and the model's choice, saved with the times; nothing is yet judged.
**Dependencies:** A and the owner's word on the sample.
**Affected areas:** outside the repository only: a script, its tests and breaks, the vectors of the 40 texts, the candidates and the answers; the plan's Result.
**Steps:**
1. Write the tests first and see them fail, with a fake embedder and a fake chat model: the shelf vectors of the earlier plan are used only after the hashes of the vectors, the schema file and the shelf texts are checked; the texts are embedded as plain documents with the entry's prefix not used; the five nearest home shelves by cosine, ties by the order of the file; the prompt is the earlier `place-1` unchanged (a test that the module of the earlier plan is the one imported, by its hash); the strict reader; one call for each book; an error is recorded and five in a row stop the run; the output files are new and mode 600.
2. Write the script. It imports `run_embed` and `run_choice` of the earlier plan and does not change them.
3. Deliberate breaks and their restoring.
4. `check` prints what would be sent (the number of texts and bytes, one whole prompt) and sends nothing; the owner says "run it"; the 40 texts are embedded and the 40 prompts are sent; the vectors, the candidates and the answers are saved.
5. The `reviewer` agent reads the script and the Result.
**Verification:** the tests and breaks, a recount of the candidates (the five nearest shelves of each book) by a snippet that does not use the script, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-14-check-the-matcher-on-the-librarys-books#B`; the scripts, vectors and answers are outside the repository and cited by hash.

### Increment C — The owner's marks and the report

**Outcome:** the owner's marks of the 40 books are recorded and the figures are reported.
**Dependencies:** B.
**Affected areas:** outside the repository: a script that makes the sheet and one that makes the report, with tests and breaks, the marks; the plan's Result.
**Steps:**
1. Write the tests first and see them fail: the sheet (each book once, in an order shuffled by the seed, the shelves in alphabetical order with their paths and scope sentences, the numbers 1 to 5, the title, the address and the summary; ten to a batch; **a test that nothing in the sheet reveals the model's choice, the embedding's rank or a score**), the reading of the marks (a mark is `best` as 1 to 5 or `none` and `also` as a set of other numbers; a repeated number, a number out of range, an `also` that holds the best, an `also` that is not empty when `best` is `none`, a missing book, a book twice are refused; a skipped book is allowed with a reason and left out of every denominator), and the figures exactly as the plan defines them (each with its printed denominator; the strict and the lenient figure with the rule for `none` on either side; the embedding's nearest as the best; the ceiling; the model's `none` and the `none` of both; the field of the choice against the field of the best over the books where both are shelves, with the count left out; by kind; the exact interval of the main figure), each tested on hand-worked marks.
2. Write the scripts; make the sheet; show the owner the books **in batches of ten, blind to the model's choice**, and take the marks from the owner's replies, one batch at a time, repeating each batch's marks back before going on; write them verbatim to a file (mode 600); **close the file when the 40 are marked and compare nothing before then**.
3. Report the figures against the bar, with the denominators, and list the books where none of the five fits with the owner's words, and the books where the embedding's nearest shelf was the owner's best and the choice was not.
4. Recount the figures by a snippet that does not use the report's script. The `reviewer` agent reads the Result.
5. **Wait for the owner's reading** (criterion 5).
**Verification:** the tests and breaks, the recount, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-14-check-the-matcher-on-the-librarys-books#C`; the marks are in the Result as given, and the sheet and the report files are cited by hash.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the hashes of the outside files that the Result names are recomputed and compared, the scripts' tests are rerun, and `wb run code-work check` is run. The engine's own tests are not rerun: nothing in the repository changes except this plan.

## Risks and sensitive actions

- **The library's own derived text leaves for the model server in the clear** (40 books, over plain unauthenticated http on the owner's network), which the earlier plans did only with public text. The owner is told what and how much and says "run it", and may drop a book first. The cards were made the same way from the same books.
- **The text is model-written.** A card's summary can be wrong, and the placement follows it; the owner is asked to judge by the book, and the sheet gives the address. A wrong summary shows as a miss that is not the matcher's fault; the Result says which marks the owner flagged this way.
- **The sample is small and chosen by seed.** 40 books give wide intervals, and 10 preprints and 30 web pages give wider ones by kind. The plan shows a large failure or a clear success, not a small difference, and says so.
- **The owner's time.** About 40 judgements of five shelves each; an hour or so, in four batches.
- **Marks could be influenced by the model's choice, so the owner does not see it.** The sheet is blind (no choice, no rank, no score, a shuffled order); the marks are final before they are compared with the choice or the nearest shelf. The cost is that the owner sees five shelves and no proposal, which is the question the matcher is asked.
- **Drops and skips are not random.** They are limited (at most 5 drops before the send, none after), recorded with their reasons and shown in a sensitivity figure; the interval is a rough guide.
- **No change** of the library, the cards, a book's shelf, the schema, the spec or a roadmap, and **no push** without the owner's word.

## Review record

### The plan (before approval)

Reviewed with Codex through the project's review engine, two rounds of three (the files are in `.workbench/workbench/review-engine/plan-b2233180b6eab4d8/`). **Round 1: four major findings.** Applied: the marks and the figures were not exact (an `also` with a `best` of `none`, the rule for `none` on either side, the denominators, the field figure; now defined); the sample could not be reproduced from the record (a manifest of the eligible population, with the card generation and the text hash of each book, is saved and hashed before the draw and the draw works from it alone); a dropped book had no rule (a reserve of five of each kind, at most five drops before the send, none after, and an added book or a larger change is an amendment). **Rejected, and reported to the owner:** that a plan with `Candidate: none` needs a roadmap candidate: a roadmap for the shelves and the crawler is a change of direction that only the owner makes, the plan's Candidate line says so, and the owner approved the two earlier plans of this work with the same line. **Round 2: two major findings, both applied:** the sheet showed the model's choice before the owner marked, which biases the marks (the sheet is now blind, shuffled, and the marks are final before any comparison and never changed after it); and drops and skips are not random, so the interval is a rough guide for the books judged, the whole drawn cohort is reported, and a sensitivity figure counts skipped books as wrong (if the two readings of the bar differ, it is read as not met).

## Deferred work

- A library command that places a text; the audit of sampled placements, the margin that counts as a tie and the secondary labels; the state of a shelf, `schema-adopt`, scouting and the fetch engine.
- A fresh sample and a variant (another model, prompt, text rule or the instruction for qwen) if the result calls for one.
- The check of OpenAlex's topic descriptions against their names.
- The books other than the 40, and the cards' own accuracy.

## Result

Empty until work starts.
