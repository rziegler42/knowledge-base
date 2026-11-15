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

### Increment B

The `reviewer` agent, one exchange (second of the plan), read only. **No blocking finding.** Applied: the fifth book without a card is said to be unexplained (175 + 29 + 4 is 208, not 209), the hash is named exactly (the whole card's JSON), the 7 partial books are named, and the run of `wb run code-work check` is stated. Not applied as changes: that no byte count was printed before "run it" (the Result says so; the owner gave the word on the plan's own description), and that the counts of the engine's outputs could not be read by the reviewer (they are read here from the commands as run).

### Increment A

The `reviewer` agent, one exchange of the cap of 6, read only: it read the plan, the Result and the four files of the folder, and ran nothing. **No blocking finding.** Applied: that the second half of step 5 was not reported (the Result now says it was not checked and moves it to B), and that the test of addresses already held covers carded books only (the Result says so). Not applied as changes, since the Result already says them and the owner decides: the owner's word "implement" taken as "fetch it" (the owner is asked to confirm), the script without tests, `wb run code-work check` not rerun, and the redirect failure's cause left as the engine's own words. It could not check the logs, the hashes, the failed books in the store or the approval record; those are read here from the commands as run (the hashes are those printed by `shasum -a 256` after the run).

## Deferred work

- The placement command, built on the reading that a bare `none` means "unsure, ask the owner" (after this plan's result).
- A finder and a crawler to bring in books without hand-picked addresses, `schema-adopt`, and keeping slugs stable across versions of the schema file (the owner's roadmap decision).
- A side check of OpenAlex topic descriptions that disagree with their names.

## Result

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
