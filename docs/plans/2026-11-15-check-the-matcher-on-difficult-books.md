# Check the shelf matcher on difficult books

Status: Proposed
Created: 2026-11-15
Candidate: none (the shelves, the fetch engine and the crawler are outside every roadmap, which say so; creating a roadmap for them is the owner's change of direction; this plan follows the plan `2026-11-14-check-the-matcher-on-the-librarys-books` and the owner's reading of it)
Specs: docs/specs/shelf.md, docs/specs/card.md, docs/specs/pipeline.md

## Goal

The plan `2026-11-14-check-the-matcher-on-the-librarys-books` found that the matcher (embedding by `qwen3-embedding:4b`, the five nearest of 4,534 home shelves, the choice by `gemma4:12b` with the prompt `place-1`) puts the model's pick at the owner's best or an acceptable shelf for 34 of 40 books (85 percent, rough interval 70 to 94 percent), and the owner's reading was that it passes on the easy case and no more. The library holds no hard cases: of its 175 books, 99 of the 134 not yet sampled are English Wikipedia articles, 30 are famous preprints and 5 are other pages. So a second sample drawn from the library would be the same easy case. **The owner asked to fetch difficult books first.** When this plan is done:

- 30 books chosen by hand from outside the library (listed below, each by one address) are in the library, with a card each: 8 niche preprints, 12 web pages that are not plain English Wikipedia (lecture notes, standards, an essay, a forum thread, a patent, a book, a museum record), 6 obscure English Wikipedia articles and 4 Wikipedia articles in other languages;
- each has been placed by the same pipeline as before, with nothing tuned;
- **the owner has marked each book blind** (the best of the five offered shelves, which others would also do, or none), as before, and the marks are recorded as given;
- the Result gives the figures of the marks beside those of the first 40 books and pooled over 70, against a bar fixed below before anything is fetched, and the owner says what comes next.

## Scope

- **The list of 30 books** (picked by me on 2026-11-15, not drawn; the owner may strike or swap any before the fetch). Addresses are unverified until Increment A fetches them; a failed capture is replaced by the reserve of its group, in order.
  - *Preprints (8):* arxiv.org/abs/1301.4655 (On bibliographic networks), 1212.0304 (ranking of universities by highly-cited papers), 1708.07251 (eddies in the Sea of Okhotsk), 1708.06072 (PM2.5 and weather in China), 1508.00607 (Euclidean embeddings for a weak class of orders), 1506.08743 (tax enforcement and transfer pricing), 2008.00745 (corporate board interlock networks), 2310.08029 (the Köhler equation at sea). *Reserve, in order:* 1302.2760, 1708.06114, 1507.00894, 2208.07302. These were taken from the middle of arXiv's own listings of four categories (digital libraries, atmospheric physics, general economics, social physics), read on 2026-11-15 through the arXiv API.
  - *Web pages, not plain English Wikipedia (12):* `ocw.mit.edu/courses/24-961-introduction-to-phonology-fall-2014/pages/lecture-notes/`; `ocw.mit.edu/courses/civil-and-environmental-engineering/1-72-groundwater-hydrology-fall-2005/lecture-notes`; `www.ltcc.ac.uk/courses/introduction-to-applied-topology`; `www.rfc-editor.org/rfc/rfc1149`; `www.rfc-editor.org/rfc/rfc3339`; `csrc.nist.gov/pubs/sp/1300/final`; `www.paulgraham.com/makersschedule.html`; `pubs.nmsu.edu/_circulars/CR672/` (soil compaction, an extension circular); `boards.straightdope.com/t/why-is-the-sky-blue/668120` (a forum thread); `patents.google.com/patent/US4372000` (a beehive frame patent); `gutenberg.org/files/205/205-h/205-h.htm` (Walden, a whole book); `si.edu/object/mariners-astrolabe%3Anmah_997159` (a museum record). *Reserve:* `nrcs.usda.gov/sites/default/files/2022-12/Rangeland_Soil_Quality_Compaction_0.pdf` (a PDF), `patents.google.com/patent/US1425295`, `si.edu/es/object/dorothy-liebess-personal-four-harness-treadle-loom-rams-head-1947%3Anmah_1080614`.
  - *Obscure English Wikipedia (6):* Ropewalk, Quipu, Zeugma, Tenebrism, Pomology, Gleaning. *Reserve:* Sloyd, Ogham.
  - *Wikipedia in other languages (4):* fr `Transhumance`, es `Acequia`, ja `折り紙`, de `Hufeisen`. *Reserve, in order:* fr `Glanage`, de `Tenebrismus`.
- Capture, scan, convert and card of those books with the engine's own commands (`capture-url`, `capture-arxiv`, `process`, `cards`, `card-index`); a book already in the library (by address) is not fetched again and is replaced by the reserve.
- A script that makes the sample of the 30 from the catalog by the earlier text rule `text-1` (no draw: the list is fixed), the five nearest shelves and the choice by the earlier scripts, a blind sheet and marks as before, and the report, with a pooled figure over the first 40 and these 30.
- Scripts and files held outside the repository and cited by hash, as in the earlier plans.

## Non-goals

- A finder or a crawler: the addresses are given by hand, and no engine code is written for fetching.
- Any change to the engine's code, the shelves, the schema, a book's `shelf` field, a spec or a roadmap; no filing or reshelving.
- Tuning: another model, prompt, text rule or number of candidates tried and picked by the marks. A variant is a new plan with a new sample.
- A fair random sample of "difficult" books: the 30 are my picks, not a draw, and the figures describe these books only.
- The accuracy of the cards themselves, the placement command, `schema-adopt` and scouting.
- A security review of the scripts (none is asked for; see the risks).

## Assumptions and constraints

- **The pipeline is the earlier one, unchanged:** text rule `text-1` (title, the card's own summary and topics, cut to 1,500 characters), the embedding entry `embed-qwen` with no prefix, the shelf vectors `trial/matcher/vectors-qwen` (hashes checked), the five nearest home shelves by cosine, the prompt `place-1` to the `gemma` entry with the strict answer reader. The scripts of the earlier plans are imported, not changed; if a path in one of them is fixed, a copy with only the paths changed is used and its tests are rerun.
- **The bar is fixed here, before anything is fetched** (my guess, the owner's to set before approving). Over the books marked: **lenient at least 75 percent** (the model's pick is the owner's best or acceptable) and **none of the five fits at most 15 percent**, the same bar as before. **Clearly good:** lenient at least 75 percent and the lower end of its rough interval at least 55 percent. **Clearly poor:** lenient under 60 percent. Between those, the result is **not settled** and is reported as such. The hard set is compared with the first 40 by the figures and not by a test: 30 books cannot tell a small difference from none.
- **The rule for `none`:** when the model says `none`, the book counts wrong in the strict and lenient figures if the owner's best is a shelf, and right in the strict one if the owner's best is also `none`. Apart, the report says for each such book whether the embedding's nearest shelf was the owner's best or acceptable (this follows from the marks as given; the owner is asked nothing more). The earlier reading stands: a bare `none` means "unsure, ask the owner".
- **The marks are blind, as in the earlier plan:** each book is shown with its title, its address and its summary and the five shelves in alphabetical order (path and scope sentence); the sheet hides the kind, the rank, the scores and the model's choice, in a shuffled order, in batches of ten; the marks are final before any comparison and never changed after it; the reply format and the validity rules are the earlier ones. For a book in a language the owner does not read, the owner may mark by the card's summary and the address, and says so; a book the owner cannot judge is skipped with the owner's word and counted wrong in a sensitivity figure.
- **A drop before the send:** after seeing the 30 titles, before any text goes to the model, the owner may drop up to 4 books, each with a reason, each replaced by the next of its group's reserve; adding a book the owner names is an amendment that needs the owner's new approval of the plan.
- **What leaves the machine.** (1) Increment A makes about 30 plain GET requests to public sites (arXiv, Wikipedia, MIT, NIST, rfc-editor, Project Gutenberg, the Smithsonian, Google Patents and others) from the owner's address, one for each book, as `capture-url` does today; no script of the page is run, and the engine refuses private addresses. (2) Increments B and D send the books' text and the 30 texts to the model server `ned` on the owner's network over plain unauthenticated http, in the clear, as the cards were made. All of it is public text. The owner says "fetch it" before A and "run it" before B and before D.
- **The shell here could not reach the network** on 2026-11-15 (`curl` to arXiv timed out after 20 seconds; the page-reading agent reached it). Increment A starts with one capture to find out whether `capture-url` can; if it cannot, the plan stops there and the owner decides (a different route is an amendment).
- **The sample's size.** 30 books: a share of 0.75 has a 95 percent interval of about plus or minus 15 points. Pooled over 70 books, about plus or minus 10. The figures describe the books judged and are a rough guide, not an inference about the library.
- **Order of work:** tests before code for every script, deliberate breaks of each script and their restoring, the `reviewer` agent's reading of each Result, a recount by a snippet that does not use the script's own code, as in the earlier plans.

## Completion criteria

1. The 30 books (or their reserves, each swap named with its reason) are in the library, each captured, scanned, converted and carded, with the capture records and the card count recorded and no book of the earlier 175 changed (by the hashes of their cards, checked before and after).
2. The sample of 30 was made from the catalog by the rule `text-1` fixed before the fetch, with the manifest and sample files cited by hash, and the owner's drops recorded.
3. The 30 texts were embedded, the five nearest shelves made, and the choice made, with the entries, the prompt version, the dimension and the times recorded; nothing in the pipeline was changed from the earlier plans.
4. The owner marked every book blind to the model's choice, and the marks are in the Result as given and final before they were compared; a skipped book is recorded with the owner's word.
5. The report gives each figure with its denominator and a rough interval for the main one, split by kind of book (preprint, web page, other-language, Wikipedia) where the counts allow, beside the first 40 and pooled over 70, with the whole cohort, the sensitivity figure and a recount by a snippet that does not use the report's script; the reading against the bar (clearly good, not settled, clearly poor) is stated.
6. The owner has read the result and says what comes next.
7. `wb run code-work check` finds no problems, and nothing in the repository changes except this plan.

## Increments

### Increment A — Fetch and process the 30 books

**Outcome:** the 30 books are in the library, each captured, scanned and converted, and the library's earlier books are unchanged.
**Dependencies:** the owner's approval of this plan and the owner's word "fetch it", after the owner has seen the list and struck or swapped what they like.
**Affected areas:** the library's store and index (30 new books), and outside the repository a list file and a record of the results; the plan's Result. No code of the engine changes.
**Steps:**
1. Record the hash of the card of every book now in the library, and read the catalog read-only to find whether any address of the list is already a book (by the engine's identity keys); one already held is not fetched and is replaced by the reserve.
2. Capture one address (the RFC) and read the result, to find whether `capture-url` reaches the network from here. If it does not, stop and report; do not try another route.
3. Capture the rest one at a time with `python3 -m kb capture-url` and `python3 -m kb capture-arxiv`, reading each result: a refused, failed or empty capture is recorded with its reason and replaced by the reserve of its group, in order; no address is retried more than once.
4. Run `python3 -m kb process` (scan, convert, index) and read each book's stage record: a book that does not convert is recorded and replaced by the reserve. No text goes to a model in this step.
5. Check that the cards of the earlier books are byte for byte what step 1 recorded, and that the 30 new books are all in the catalog's books list with their kinds and addresses.
6. The `reviewer` agent reads the Result.
**Verification:** the capture and process results as printed, the stage record of each of the 30 books, the unchanged hashes of the earlier cards, `wb run code-work check`. Nothing is new code, so there are no new tests; the engine's own tests are not rerun because nothing in the engine changes.
**Evidence:** the one local commit holding the plan's Result and Review record for A, with the trailer `Plan: 2026-11-15-check-the-matcher-on-difficult-books#A`; the list file and the record are outside the repository and cited by hash.

### Increment B — Cards for the 30 books (sends their text to `ned`)

**Outcome:** each of the 30 books has a current card with a summary, and the catalog holds them.
**Dependencies:** A and the owner's word "run it" for the cards.
**Affected areas:** the library's cards and the catalog (30 new cards); the plan's Result.
**Steps:**
1. Say to the owner how many books and about how many bytes of text go to the model server, and wait for "run it". (The cards of the earlier books were made the same way.)
2. Make the cards one book at a time with `python3 -m kb cards --book <id>`, as the library's other cards were made (card accuracy is more important than speed), reading each result; a book whose card fails or has no summary is recorded and replaced by the reserve (which then goes through A and B).
3. Run `python3 -m kb card-index` and check the catalog holds 30 new current cards and that the earlier 175 cards are unchanged by their hashes.
4. The `reviewer` agent reads the Result.
**Verification:** each card's result as printed, the catalog's counts, the unchanged hashes, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-check-the-matcher-on-difficult-books#B`.

### Increment C — The sample (no send)

**Outcome:** the sample of the 30 books, with the text of each by the rule `text-1`, is recorded; nothing is sent.
**Dependencies:** B.
**Affected areas:** outside the repository only: a script that makes the manifest and sample for a named list of books, its tests and breaks, the files (mode 600); the plan's Result.
**Steps:**
1. Write the tests first and see them fail: the list is read from a file; each book is found in the catalog by its address; the newest current card is used; the text rule is the earlier one (the earlier function is imported, and a test shows it by its hash); a book with no summary or a text under 100 characters is refused with the reason; a name in the list that is not in the catalog stops the run; the output is new, mode 600, never over one; the manifest and the sample record the hash of the list.
2. Write the script and make the manifest and sample.
3. Deliberate breaks (the rule, the cut, the address lookup, the card generation, the output mode and replacement) and their restoring.
4. Show the owner the rule and the 30 titles, kinds and addresses, and **wait for the owner to say whether any book is to be dropped** (up to 4, each with a reason, each replaced by the next of its group's reserve).
5. The `reviewer` agent reads the script, its tests and the sample's counts.
**Verification:** the script's tests and breaks, the sample's counts recounted by a second snippet from the catalog, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-check-the-matcher-on-difficult-books#C`; the script and the files are outside the repository and cited by hash.

### Increment D — The five nearest shelves and the choice (sends the 30 texts)

**Outcome:** each book of the sample has its five nearest shelves and the model's choice, saved with the times; nothing is yet judged.
**Dependencies:** C and the owner's word on the sample.
**Affected areas:** outside the repository only: the run (the earlier `run_books.py` with the paths of this sample, or a copy that differs only in its paths, with its tests rerun), the vectors, the candidates and the answers; the plan's Result.
**Steps:**
1. Rerun the tests of the script used and see them pass on its paths (or, for a copy, write the test that its code differs only in its paths).
2. `check` prints what would be sent (the number of texts and bytes, one whole prompt) and sends nothing; the owner says "run it"; the 30 texts are embedded and the 30 prompts are sent; the vectors, candidates and answers are saved.
3. Recount the five nearest shelves of each book by a snippet that does not use the script. The `reviewer` agent reads the Result.
**Verification:** the tests, the recount, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-check-the-matcher-on-difficult-books#D`; files outside the repository cited by hash.

### Increment E — The owner's marks and the report

**Outcome:** the owner's marks of the 30 books are recorded and the figures are reported against the bar.
**Dependencies:** D.
**Affected areas:** outside the repository: the earlier sheet and report scripts used with a new seed (`sheet:hard`, a different shuffle) and a small script for the pooled figure, with tests and breaks, the marks; the plan's Result.
**Steps:**
1. Write the tests first for what is new (the pooled figure over two sets, the denominators, the kinds of this set) and see them fail; rerun the earlier scripts' tests.
2. Make the sheet; show the owner the books in batches of ten, blind to the model's choice, repeat each batch's marks back before going on, write them verbatim (mode 600), and **close the file when all 30 are marked and compare nothing before then**. Paste the tool's output exactly, and say when anything is retyped.
3. Report the figures with the denominators, the whole cohort, the sensitivity figure, the books where none of the five fits (with the owner's words), the books where the nearest shelf was right and the choice was not, the model's `none` books with the nearest shelf's status, the figures beside the first 40 and pooled over 70, and the reading against the bar.
4. Recount the figures by a snippet that does not use the report's script. The `reviewer` agent reads the Result.
5. **Wait for the owner's reading** (criterion 6).
**Verification:** the tests and breaks, the recount, `wb run code-work check`.
**Evidence:** the one local commit with the trailer `Plan: 2026-11-15-check-the-matcher-on-difficult-books#E`; the marks are in the Result as given, and the sheet and report files are cited by hash.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the hashes of the earlier 175 cards are checked once more, the hashes of the outside files that the Result names are recomputed and compared, the scripts' tests are rerun, and `wb run code-work check` is run. The engine's own tests are not rerun: no engine code changes. The 30 new books stay in the library, which is a change the plan makes on purpose.

## Risks and sensitive actions

- **The library gains 30 books** the owner did not pick one by one, and they stay in it afterward; they can be weeded by the library's own rules (a removed book is not fetched again). The list is shown to the owner before the fetch.
- **About 30 requests go to public sites from the owner's address**, one each, with the engine's fixed fetcher (no script run, private addresses refused). Google Patents, the Smithsonian and a forum may refuse an automated GET; a refusal is recorded and the reserve is used. The fetched pages are data and can carry text that addresses an AI agent; such text is ignored, and nothing from a page is run.
- **Text goes to the model server in the clear** (cards in B, texts in D), as for the earlier books; all of it is public text.
- **The picks are mine, and the set is small.** The figures describe these 30 books, not the library or a population of hard books; a result in the "not settled" range stays not settled.
- **Language and format.** A page in a language the owner does not read, a PDF and a long book may make the card poor; a poor card shows as a miss that is not the matcher's fault, and the Result says which marks the owner flagged this way.
- **Marks could be influenced by the model's choice**, so the owner does not see it: the sheet is blind and the marks are final before any comparison.
- **No push** and no change of the engine, the shelves, a spec or a roadmap without the owner's word.

## Review record

### Increment E

The `reviewer` agent, one exchange (fifth of the plan), read only: it read the plan, the sheet, the marks file, the report, the pooled file, the choices and the first plan's report, and **recounted the figures by hand from the raw marks, sheet and choices**; it did not read the scripts, tests or breaks. **No blocking finding.** It confirmed: each `said` line equals its parsed marks (all 28), the closing line and the sheet hash, a sheet with no kind, group, rank, score, choice or item (a key search, and a read of books 1 to 19), the 28 books' figures, the three misses, the pooled counts from the two reports and the reading "clearly good". Applied: the stale heading of the Result, the model's `none` books with the nearest shelf's status (and that the report's `none_books` is the owner's `none` books), the seed named as a departure, the pooled count of 68, the check run, and the interval method named. It could not check the hash chain, the shasum values, the counts of tests and breaks, or that the owner never saw the choices before closing (the closing came before any comparison in this session).

### Increment D

The `reviewer` agent, one exchange (fourth of the plan), read only; it was told not to read the answers file, so that it does not need them and the owner's marks stay blind. **No blocking finding.** It read the plan, the wrapper, its tests and breaks, the earlier script and the final sample, and ran nothing: it found no way for the patch to change what is sent or which texts are sent (the validated texts are the texts sent; `group` and `item` reach no call). Applied: the limits above are said in the Result (nothing saved ties the files to the wrapper, the pin is checked after the import, some types are not checked, the plan says 30 where the sample is 28). It could not compute hashes, run the tests or breaks, or check the counts of the sends and the answers; those are read here from the commands as run.

### Increment C

The `reviewer` agent, one exchange (third of the plan), read only: it read the plan, the script, its tests and breaks, the earlier text rule, the list, the manifest and (by search) the sample, and ran nothing. **No blocking finding.** Applied: the second departure from step 1 and the partial departure about drops are said in the Result (a drop in three of the four groups can be replaced by going back through A and B; the owner chooses), the three latent faults are recorded, the account of the first break run is made exact. Not applied: the leftover construction in two break texts (harmless); a test of the full hash of the earlier file (the prefix is tested, the full hash is cited in the Result and recomputed at the close). It could not run the tests or the breaks, recompute hashes or read the real catalog; those are read here from the commands as run.

### Increment B

The `reviewer` agent, one exchange (second of the plan), read only. **No blocking finding.** Applied: the fifth book without a card is said to be unexplained (175 + 29 + 4 is 208, not 209), the hash is named exactly (the whole card's JSON), the 7 partial books are named, and the run of `wb run code-work check` is stated. Not applied as changes: that no byte count was printed before "run it" (the Result says so; the owner gave the word on the plan's own description), and that the counts of the engine's outputs could not be read by the reviewer (they are read here from the commands as run).

### Increment A

The `reviewer` agent, one exchange of the cap of 6, read only: it read the plan, the Result and the four files of the folder, and ran nothing. **No blocking finding.** Applied: that the second half of step 5 was not reported (the Result now says it was not checked and moves it to B), and that the test of addresses already held covers carded books only (the Result says so). Not applied as changes, since the Result already says them and the owner decides: the owner's word "implement" taken as "fetch it" (the owner is asked to confirm), the script without tests, `wb run code-work check` not rerun, and the redirect failure's cause left as the engine's own words. It could not check the logs, the hashes, the failed books in the store or the approval record; those are read here from the commands as run (the hashes are those printed by `shasum -a 256` after the run).

## Deferred work

- The placement command, built on the reading that a bare `none` means "unsure, ask the owner" (after this plan's result).
- A finder and a crawler to bring in books without hand-picked addresses, `schema-adopt`, and keeping slugs stable across versions of the schema file (the owner's roadmap decision).
- A side check of OpenAlex topic descriptions that disagree with their names.

## Result

### Increment E — the owner's marks and the report (done on 2026-11-15; not yet committed; the owner's reading is still to come)

**What was made** (outside the repository, in `~/.local/share/knowledge-base/trial/hard/`, mode 600): `sheet_hard.py` (`aba03b14…3b3fd0`) and `report_hard.py` (`a6224a6d…4a64f0`), thin wrappers of the earlier plan's `sheet_books.py` (pinned `e74c3399…cad1`) and `report_books.py` (pinned `bea9742b…ba85d`), both unchanged; tests `test_sheet_hard.py` (`c8308ef8…96f70`, 27 at the last run) and breaks `breaks_sheet_hard.py` (`bc7a3b6b…64b9`, 20; 20 of 20 caught, files restored byte for byte; the first run missed 7, of which 1 was an equivalent break that was removed and 6 showed gaps in the tests, for which tests were added). The earlier scripts' own tests were rerun and pass (49, 36, 52). **Departures, said plainly:** the sheet has **four batches of seven, not batches of ten** (28 books do not split into tens, and the earlier script fixes the batch size, so the wrapper sets 4 by 7, which keeps all its checks); the shuffle seed is 2; the wrappers replace the earlier scripts' loader, counts and batch size and nothing else. For the wrappers the tests were written before the code and failed first (the module was missing).

**The sheet and the marks.** `sheet-hard.json` (`976e7e1c…bcd5`): 28 books in four batches of seven, blind (title, address, summary and five shelves in alphabetical order; no kind, group, rank, score or choice). The owner marked in four batches (messages of 2026-11-15) and each batch was repeated back before the next; **the marks are the owner's as given** (`marks-hard.jsonl`, `91a02c06…94ca58`, closed with a last line holding the hash of the four batch lines, `d96a1775…ee3cf`; 28 marked, 0 skipped; the file was closed on the owner's word "close" and compared with nothing before that). **Retyping, said plainly:** the batches were shown to the owner as messages that I retyped from the tool output (the owner's view of tool output was not sure); I said so each time and found these slips: book 5, shelf 4 of batch 1 (`sociolinguistic` written `sociolinguistics`), straight apostrophes for curly ones throughout, and book 28, shelf 5 of batch 4 (the scope sentence of "Power Line Inspection Robots" shortened); none changes a shelf name or an address, and the owner's marks are of the numbers.

**The figures** (`report-hard.json`, `66879414…f2173f`, made by `report_hard.py report …` on the closed file; **recounted by a snippet that uses none of these scripts, from the raw marks, sheet, choices and candidates files: the counts agree**):

| figure | all 28 | web pages 20 | preprints 8 |
|---|---|---|---|
| strict (the model's pick is the owner's best; `none` against `none` is right) | 25 (89.3%) | 18 | 7 |
| lenient (strict, or one of the owner's `also` shelves) | 25 (89.3%), rough interval 71.8 to 97.7% | 18 | 7 |
| nearest shelf is the owner's best | 13 (46.4%) | 10 | 3 |
| ceiling (the owner's best is a shelf: one of the five is a fair home) | 26 (92.9%) | 18 | 8 |
| none of the five fits | 2 (7.1%) | 2 | 0 |
| model said `none` (and the owner's best was also `none`) | 2 (1) | 1 (1) | 1 (0) |
| field of the pick = field of the best (books where both are shelves) | 25 of 25 (3 left out) | 18 of 18 | 7 of 7 |

The sensitivity figure (skipped counted wrong) is the same (none skipped). **Reading against the bar fixed in the plan before anything was fetched** (lenient at least 75 percent and none-of-five at most 15 percent): **meets, on both readings**; and by the plan's own words, **clearly good** (lenient at least 75 percent with the lower end of the rough interval, 71.8 percent, at least 55 percent). **The lenient figure equals the strict one: no `also` shelf rescued a pick.**

**The three books the pick missed** (the owner's words are the marks): book 3, *Existence of continuous euclidean embeddings…* (model `none`; the owner's best is shelf 2, Advanced Topology and Set Theory, so a fair home was offered); book 5, *Zeugma* (the owner's best is `none`; the model picked Linguistic research and analysis); book 12, *NIST SP 1300* (the nearest shelf, Cybersecurity and Information Systems, was the owner's best; the model picked Diverse Interdisciplinary Research Studies). **The two books where none of the five fits** are the beehive-frame patent US1425295 (the model also said `none`: right) and Zeugma. **Where the nearest shelf alone is right and the choice is wrong:** book 12 only (the report's own list). Compared with the figures the plan names: the first 40 books had lenient 34 of 40 (85.0%), strict 29 of 40, nearest 21 of 40 and none-of-five 0 of 40; the 300 papers had exact 58.7 percent and nearest 46.7 percent.

**The model's two `none` books, with the nearest shelf's status, as the plan asks** (note that the report's `none_books` list holds the books where the *owner's* best is `none`, books 1 and 5, not these): **book 1**, the beehive-frame patent US1425295: the model said `none`, the owner's best is `none` (right); the nearest shelf (Insect and Pesticide Research) is not the owner's best, since the owner's best is `none`. **Book 3**, the Euclidean-embeddings paper: the model said `none`, the owner's best is shelf 2 Advanced Topology and Set Theory (wrong); the nearest shelf (Fixed Point Theorems Analysis) is neither the owner's best nor acceptable (the owner gave no `also`), so the nearest shelf would have been wrong too. The earlier reading stands: a bare `none` means "unsure, ask the owner".

**More departures from the plan's text, said plainly:** the plan names the new shuffle `sheet:hard`; the earlier script needs an integer seed, so the seed is 2. The pooled figure is over 68 books, not the 70 the plan's first words imply (the sample is 28, not 30: Increments A to C record why). The intervals are the earlier script's exact (Clopper-Pearson) intervals, called rough because the picks were not a random draw. `wb run code-work check` was run after this Result was written: no problems.

**An error of mine in the conversation, said plainly:** after the marks I told the owner that four of their marks were `none`; the report shows two (books 1 and 5). I corrected it as soon as I read the report.

**The pooled figure over the first 40 and these 28 (68 books)**, made by `pool_hard.py` (`97d6142f…1dcfd2`; tests `test_pool_hard.py` `84461043…567fd`, 25; breaks `breaks_pool_hard.py` `476c4643…97ae9`, 35 of 35 caught after the first run missed 10, which showed that several checks were caught only by a neighbouring check and tests for each were added; file restored byte for byte), which imports the earlier script's interval and bar functions unchanged and is pinned with them; output `pooled-hard.json` (`500e9093…940cea`). **The two samples were chosen in different ways (the first drawn at random, the second picked by hand), so the pooled figure is a rough guide to the books judged and not an estimate for a population.**

| pooled over 68 books | all 68 | web pages 50 | preprints 18 |
|---|---|---|---|
| strict | 54 (79.4%), rough interval 67.9 to 88.3% | 38 | 16 |
| lenient | 59 (86.8%), rough interval 76.4 to 93.8% | 42 | 17 |
| nearest shelf is the owner's best | 34 (50.0%) | 25 | 9 |
| one of the five is a fair home | 66 (97.1%) | 48 | 18 |
| none of the five fits | 2 (2.9%) | 2 | 0 |
| model said `none` | 5 | 4 | 1 |
| right field when both are shelves | 58 of 62 | 41 of 45 | 17 of 17 |

The bar (lenient at least 75 percent, none-of-five at most 15 percent) is met on the pooled counts. **The second sample by group** (strict and lenient are equal in each): other web pages 9 of 10, English Wikipedia 5 of 6, Wikipedia in other languages 4 of 4, preprints 7 of 8 (the three misses are one in each of the first three: NIST SP 1300, Zeugma and the Euclidean-embeddings paper). **The pooled counts were also worked by hand in the tests** (the real-report test expects 68, 54, 59, 34, 66 and 2).

**Not done yet:** the `reviewer` agent's reading; the owner's reading (completion criterion 6); the commit. **The shell's gate closed during this step** (`packages/workbench/code-work`, the sixth time in the session that it closed after the owner cleared it, with a different package); the owner cleared it again.

### Increment D — the five nearest shelves and the choice (done on 2026-11-15; not yet committed)

**What was run.** `run_hard.py` (`b5317d14…7816ca6`), a wrapper of the earlier `run_books.py` (pinned by hash `02b70ba4…eaff8`; unchanged, and its 52 tests were rerun and pass); its tests `test_run_hard.py` (`41ccfd41…ab4aa88`, 20) and breaks `breaks_run_hard.py` (`cbdbb076…19f65`, 24), all in `~/.local/share/knowledge-base/trial/hard/` (mode 600). **Two departures from the plan, said plainly.** (1) The plan says the earlier script is used with its paths, or in a copy that differs only in its paths. The final file of this sample has another shape (28 books; a group and a list item for each; no seed or reserve), so the wrapper **replaces the earlier script's loader and its counts** (20 web pages and 8 preprints) and nothing else; the earlier file is imported, not changed, and the wrapper stops unless it is the pinned file. (2) **Tests first was not followed for the wrapper:** I wrote its tests and its code in one step and ran the tests once, so I never saw them fail first; the breaks stand in for that (the first run of the 25 breaks missed 4: one was an equivalent break and was removed, three showed gaps in the tests, for which tests were added; the final run: 20 tests pass, **24 of 24 breaks caught**, file restored byte for byte, each broken text compiled first).

**The sends** (on the owner's words "run it" for the embedding and again for the choice, after the plan's description and the printed counts): to the model server `ned`, over plain unauthenticated http, in the clear (`wb run ask-ollama check` printed the warning): (1) **the embedding**: 28 texts, 19,749 bytes (346 to 945 each), one call to `qwen3-embedding:4b` (dimension 2560, no prefix), 2.96 seconds; vectors in `vectors-hard/books.f32` (`2a598826…9499287`) with `books-meta.json` (`6fa8b0a2…7160a37`). (2) **the choice**: 28 prompts, one call each, 2,098 to 3,006 bytes (70,955 in all), prompt `place-1`, entry `gemma` (`gemma4:12b`); 19.5 seconds; answers in `choices-hard.jsonl` (`d41dc34a…909686f208`, 28 lines in the order of the sample, **0 errors**). The addresses, book ids, groups and list items were not sent.

**What came back, counted only** (the owner is not shown which shelf was chosen for which book, so that the marks stay blind): the model picked a shelf for 26 books and said `none` for 2. The five nearest shelves are in `candidates-hard.json` (`7ab8f231…725ab15`), **recounted by a snippet that uses none of these scripts** (numpy, the 4,534 home shelves of the schema file, the unit vectors, cosine, ties by the order of the file): all 28 books agree with the file on the five shelves and their order, scores within 1e-5.

**Limits of the wrapper that the reviewer named, said plainly:** nothing saved ties the vectors, candidates or answers to the wrapper: `books-meta.json` records the hash of `run_books.py` (`02b70ba4…eaff8`, which it computed itself) and the pins of the two earlier files, and the hash of `run_hard.py` is only in this Result. The pin of `run_books.py` is checked after the file has been imported (and so after its top-level code has run), as the earlier script does for its own two files; the folder is the owner's. The wrapper checks the key sets and the fit of group and kind, not the types of `group`, `item`, `not_eligible`, `missing` or the three hashes (none is sent). The plan's Increment D speaks of 30 texts and 30 prompts; the sample is 28 (Increments B and C record why).

**Not done:** the commit.

### Increment C — the sample (done on 2026-11-15; not yet committed; no send)

**What was made** (outside the repository, in `~/.local/share/knowledge-base/trial/hard/`, mode 600; hashes as printed by `shasum -a 256` after the last change): `hard_sample.py` (`0362e8f2…c92af0a`), its tests `test_hard_sample.py` (`1cee0750…a015e3`), its breaks `breaks_hard_sample.py` (`19ab0a96…ff096`), the manifest `hard-manifest.json` (`4b05c6b1…ab278a865`) and the sample `hard-sample.json` (`28f61b71…b371b736c`). The list is `hard-list.json` (`aecd713d…c12c6e`, unchanged). **The text rule is the earlier file `books_sample.py`, unchanged** (hash `ac7e05f4…02b1`; a test checks the first characters of its hash and that the new script imports that very module): `hard_sample.py` imports its `card_text`, `_entry`, `_book`, the catalog reader and the file writer and adds only what a named list needs (matching an item to a book by the address asked, the final address or the arXiv id; a group may not hold more books than it has main items; the owner's drops).

**Order of work, as run.** The tests were written first; the first run failed because the script did not exist. The script was written; 45 tests ran and **2 errors came from my own fixture** (a second card of a book needs its own version), which I fixed in the tests. **The first run of the breaks: 63 were written, 2 of them did not compile (a colon missing from my break text, which I corrected), and of the 61 that ran, 11 were missed.** Two of those 11 were not faults at all (sorting keys still gives the same bytes) and I removed those two breaks, which leaves 61 breaks in all. The other 9 showed real gaps: the test of a key given twice passed for another reason (the list had no groups), nothing tested an item that is not a web address, a manifest that lists a book twice or names a group it does not count, a card changed in place with the same generation, a card of a newer generation with the same text, or the words of a refusal for a missing file. **Tests were added for each; the final run: 51 tests pass; 61 of 61 breaks are caught, none missed, none that do not compile (`compile()` is run on each broken text), and the file is restored byte for byte.** One break (a hash that is not a hash) was caught only after the test was made to check the reason of the refusal (the check is otherwise covered by a later one).

**On the real library** (read-only; nothing sent): the manifest holds **29 books in the library of the 41 items of the list** (12 items are not in the library: the 4 failed captures and the 8 reserve items never fetched), **28 eligible, 1 not (no summary)**; the sample holds the **28 books**: 8 preprints and 20 web pages (10 other web pages, 6 obscure English Wikipedia articles, 4 Wikipedia articles in other languages); each carries its title, address, summary and the text of the rule. **Recount by a snippet that uses none of these scripts** (the library's catalog read with `sqlite3` read-only, the 29 new books taken from the snapshots of A and B): 29 new books, 28 with a summary (20 web pages, 8 preprints), the one without is `01M7FKBME7T7ETRVXHPZ5XS74Q`, the same 28 as the sample, 28 unique, by group 8, 10, 6, 4; each text begins as its card's summary does.

**Two departures from the plan's text, said plainly.** (1) Step 1 says a name in the list that is not in the catalog stops the run; the script lists such items apart (12 here: 4 failed captures and 8 reserve items never fetched) and goes on, which a test pins. (2) The plan says a dropped book is replaced by the next of its group's reserve. **In this script a drop removes the book and the sample shrinks** (recorded with the owner's reason); the reserve items are not in the library. For a drop in the preprint, English Wikipedia or other-language group the replacement can still be made, by fetching and carding the next reserve item (Increments A and B again) and running this script again, because a reserve item may stand in for a missing main one (a test covers it); the web group's reserve is used up. The owner is asked to choose between a smaller sample and that.

**Latent faults the reviewer named, none affecting these 28 books:** the address comparison lowercases the whole address (two paths that differ only in case would be refused as two books for one item, which fails safe) and does not decode percent escapes (a list item written with raw non-ASCII characters would show as missing and not as an error; the one such item is written percent-encoded and matched); the manifest check does not validate `kind`, `slot` or `item` (a hand-edited manifest could change the kind on the sheet; the manifest's hash in the sample would show the edit). `wb run code-work check` was run after this Result was written (below).

**The owner's drops: none** ("commit c, no drops", after the 28 titles were shown). The final sample is `hard-final.json` (`968c951f…f869369`), made by `hard_sample.py drop` with the empty list `hard-no-drops.json` (`37517e5f…985b570`, the same empty list as in the earlier plan); it holds the same 28 books as `hard-sample.json`, `dropped` empty, and records the hash of the sample it came from. **Nothing has been sent.**

**Not done:** the commit.

### Increment B — cards for the books (done on 2026-11-15; not yet committed)

**What was run.** On the owner's word "run it" (given with the word to commit A, after the plan said how the cards go: the books' text to `ned` in the clear, as for the earlier cards), `python3 -m kb cards --book <id>` was run for each of the 29 books, one at a time, in the order of Increment A; then `python3 -m kb card-index`. The models are the library's own entries: `gemma4:12b` (card-notes), `gpt-oss:20b` (card), `phi4` (card-check), `qwen3:14b` (card-more where needed). No byte count was printed beforehand; the books are public pages and papers.

1. **All 29 books were carded** (`status: carded`, generation 1; 29 results of 29). **7 of them are marked `partial: true`** (the engine's own flag; I did not look into what it means beyond the flag): the NIST SP 1300 page (01M7FKBHE2MR0E9HQ1NWNGGFX1), the Paul Graham essay (01M7FKBHZZD28VZG85AH9QZ9Q7), the London Taught Course Centre page (01M7FKBME7T7ETRVXHPZ5XS74Q, the one with no summary), *Walden* (01M7FKBWW1BGYBARA8SCP181Z0), Zeugma (01M7FKC95JN97WWN33ND187H99), Pomology (01M7FKCA4QBF18W6TQDKZP14K4) and the preprint 1506.08743 (01M7FKD1FZ45203KXJWD290FPK). One card (the patent US1425295) went through no check call (`checked` 0), which is the engine's own output.
2. **The catalog** now reads 209 books, 204 cards, 0 failed (204 cards are the 175 earlier and the 29 new; of the 5 books without a card, 4 are the failed captures of A, and **the fifth is not explained here**: 175 + 29 + 4 is 208, and I did not look into the one more). **The 175 earlier cards are unchanged**: `snapshot-after-cards.json` (`2f324650…c53478`) holds 204 cards and the generation and the hash of the whole card (`card_sha256`, of the card's JSON) of each earlier one equals `snapshot-before.json`. The 29 new cards are 21 web pages and 8 preprints, each with the address of its page (the two RFCs carry `rfc-editor.org/info/…` as their final address).
3. **The text rule (`text-1`, read-only, run on the 29 new cards): 28 are eligible and 1 is not: the London Taught Course Centre page (`01M7FKBME7T7ETRVXHPZ5XS74Q`) has no summary in its card.** The plan says a book whose card has no summary is recorded and replaced by the reserve; the web reserves are used up. The sample stands at **28 books** unless the owner decides otherwise (options: go on with 28; make the card again as a new generation, `kb cards --book … --again`, once, which is not tuning but is a second model call on the same text; or name another page, an amendment).

4. **The owner's decision ("go with your recommendation", after the recommendation to make that card again once and, if it still has no summary, to go on with 28):** the card of the London Taught Course Centre page was made again once with `kb cards --book … --again`. The result was generation 2, `partial: true`, **0 pieces and 0 model calls**, and after `kb card-index` the card still has no summary (the text rule still reads it as `no summary`). **The sample is 28 books** (8 preprints, 10 web pages, 6 obscure English Wikipedia articles, 4 Wikipedia articles in other languages). The book keeps its card of generation 2 in the library and is not in the sample. Nothing else was changed.
5. `wb run code-work check` was run after this Result was written: no problems.

**Not done:** the commit.

### Increment A — fetch and process the 30 books (done on 2026-11-15; not yet committed)

**What was run.** The plan was committed at `111f17c` and approved with `wb approve-plan` at the level `ask` (digest `ab0a38cf…`). The owner's word "implement" was taken as the word "fetch it": the list had been written in the plan and its groups shown in chat before. Outside the repository, in `~/.local/share/knowledge-base/trial/hard/` (mode 600): `hard-list.json` (`aecd713d…c12c6e`, 41 items), `snapshot_hard.py` (`3731eadb…5549b9`, a read-only script; it has no tests, which is a departure from the order of work for a short throwaway reader, said here), `snapshot-before.json` and `snapshot-after.json` (both `e274bb4b…8b75f3`).

1. **Before the fetch** the catalog held 175 current cards, and none of the 41 addresses of the list was already held (by the address or arXiv id of a card).
2. **The route:** `python3 -m kb capture-url` reached the network from here (the RFC filed); the shell's `curl` had timed out earlier, so the two routes differ.
3. **Captures**, one at a time, in the order of the plan: **29 filed, 4 failed.** Failed: `ocw.mit.edu/.../1-72-groundwater-hydrology-fall-2005/lecture-notes` (too many redirects, or a redirect loop; book 01M7FKBTMXH06BYG5325XDNT21), `si.edu/object/mariners-astrolabe…` (HTTP 403; 01M7FKBXG0NQQA8B2P78WYGF5H), the first web reserve `nrcs.usda.gov/…Rangeland_Soil_Quality_Compaction_0.pdf` (`capture-url` refuses a PDF: not a web page; 01M7FKC79VW76Z1WS5RJNR9ST7), and the third web reserve `si.edu/es/object/dorothy-liebess-…` (HTTP 403; 01M7FKCNG94X2R3VYKBMTDTPZK). The second web reserve (`patents.google.com/patent/US1425295`) filed. **No address was retried.** The four failed attempts are books in the store with a failed fetch; they have no payload and no card.
4. **By group:** preprints 8 of 8 (all main, none of the reserve used); web pages 11 of 12 (**the group's three reserves are used up: the group is one book short**); obscure English Wikipedia 6 of 6; Wikipedia in other languages 4 of 4. Total **29 books, not 30.**
5. **`python3 -m kb process`** ran scan, convert and index; a second run found nothing left to do. The stage record of each of the 29 books reads found, fetched, scanned, converted and indexed, all `done`.
6. **The earlier books are unchanged:** the hash of the card of each of the 175 books (generation and text) is the same before and after (`snapshot-before.json` and `snapshot-after.json` are identical). The 29 new books have no card yet.

**Narrower than step 5 asks, said plainly:** the second half of step 5 (the 29 new books are in the catalog's list of books with their kinds and addresses) was **not** checked: the catalog lists books through their cards and the 29 have none yet. What shows they are in the library is the `filed` result and the stage record of each. The check of the catalog is moved to Increment B (step 3 there counts 30 new current cards by kind and address). The test for an address already held covers carded books only (a book with no card, such as an earlier failed fetch, would not show); no earlier failed fetch of these addresses is known.

**The owner's decision on the short group:** "go with 29". The sample is 29 books (8 preprints, 11 web pages, 6 obscure English Wikipedia articles, 4 Wikipedia articles in other languages); the figures say 29 and no book is added. The plan's text speaks of 30 and is not changed; the Result's numbers stand for it.

**Not done:** the commit. **For the owner:** the web group is one short (a PDF or a museum record could not be captured). Options: go on with 29 (the figures say so), or add one web page the owner names (an amendment, since the reserve is used up and the plan lets only the owner add a book). `wb run code-work check` has not been rerun since the plan was approved.
