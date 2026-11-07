# A trial of whether the cards help

Status: Completed
Created: 2026-11-07
Candidate: cards#card-trial
Specs: card, testing

## Goal

The owner knows whether the cards help. For a set of questions the owner chooses, over the books the library holds, the trial
compares which books a search of the cards finds with which books a search of the full text finds, and reports on the cards
themselves: their length and shape, whether the neutral fields name the book's field, and whether the summaries only repeat the
words of the book. It ends with the owner's decision on whether to go on to search by meaning, to themes, or to neither. The trial
measures and reports; it does not decide, and it does not change the library.

## Scope

- An evaluation command, started by the owner, that reads a corpus file held outside the repository (questions, the queries
  written for each, and the books that answer each), runs each query as a search of the cards (all fields, the summary side, the
  neutral side) and as a search of the full text, and writes a report outside the repository. It reads the library and the two
  indexes and nothing else: it calls no model, sends nothing anywhere and changes nothing.
- Measures per query, per question and in all, by rules fixed in advance (below): whether each right book is found, and at what
  place, by each of the four searches; the books found by the cards and not by the text, by the text and not by the cards, by both,
  and by neither; and the books returned that are not right. For the cards: the number of words of a card and of each field, and for
  each card the words of its title and topics that its neutral fields repeat (a measure of leaking the field), with an optional list
  of field words from the corpus file.
- Coverage kept apart from search quality: a right book that has no card in the catalog is listed as uncovered and is left out of
  the measures of the card searches (and counted in those of the full text, with the reason stated), so that a missing card is never
  read as a card search that missed.
- An input manifest in the report: the library, and for each book of the corpus and each card the book, the current version, the
  generation of the newest card and a hash of it, or that there is none; and a hash of the catalog file and of the full-text index.
  The command refuses to run when the catalog is not the one the cards make (a card made after the last `card-index`).
- Cards for the books of the trial, made with the models the owner's config names, on the owner's word for the books and for sending
  their text.
- The questions and the books that answer them, supplied by the owner; the queries written for each question and fixed before the
  first run.
- A reading of some of the cards by the owner, who says for each whether its summary is too literal and whether its uses read like
  the questions an agent would ask.
- The written result and the owner's decision.

## Non-goals

- Building search by meaning, themes or the weave. This plan ends with a decision about them.
- Changing a card, the catalog, the prompts or the models. A finding about them is recorded for the owner.
- Proving that the library finds novel ideas across fields. That is a judgment over time (`testing.md`); this measures one
  mechanism on the books that are there.
- Committing the owner's questions, the report or a card. They stay outside the repository.
- A statistical claim. The library has eighteen books and a handful of questions; the numbers are a finding for the owner to weigh.

## Assumptions and constraints

- `testing.md` governs: the evaluation is a command the owner starts, it reports numbers and never fails a build, its corpus and
  report are held outside the repository, a set of questions with known answers may be kept in the repository only if it is
  synthetic, and a summary of results may be written into a document only if it names no personal project, path or machine, with a
  provenance line. The command refuses a corpus or a report path inside the project's own folder.
- A search of the cards is strict: every word of a query must match in one card, and words match as spelled (no stemming). A
  search of the full text is the same for one block. So a question is turned into short queries of plain words, as an agent would,
  and both searches get the same queries. The queries are written before the first run and are not changed after seeing results; a
  change makes a new corpus file, and the report records the hash of the file it was run on.
- The full-text search returns blocks. The books it finds are taken in the order in which they first appear, from at most 50 blocks;
  for a common word that limit is reached, so the books it returns are a lower bound, and a report says when it was reached.
- The rules of the measures, fixed here so that two implementations give the same report from the same corpus. A query's record is,
  for each search, the books found in order, each at a place counted from 1 by its first appearance. A question has one or more
  queries. For a question and a search, the books found are the union over its queries; a book's place is the smallest place it
  has in any of the queries (ties between books of the same place are ordered by book id); a right book is found if any query found
  it. A (question, right book) pair is the unit: recall is the share of pairs found; the sets "cards only, text only, both,
  neither" are over pairs, on the covered pairs; a question's reciprocal rank is one over the place of its best-placed right book
  in the union ordered by place, and zero if none is found, and the mean of these over questions is reported; the hit rate is the
  share of questions with at least one right book found; the noise of a question is the number of distinct books in the union that
  are not right. Every number is reported with its count (how many pairs, how many questions), never as a bare share.
- Which books are right for a question is the owner's judgment. The owner sees the titles of the books and names them.
- The library of the trial is the walk-through library: eighteen web pages and papers, most of them about language models. A
  question about it is a test of the mechanism and not of the owner's real use; the report says so.
- Making cards sends the text of the books to the models the owner's config names, over the link the registry names, which for the
  owner's set-up is plain HTTP on their network. It happens only for the books the owner names, on the owner's word.
- Nothing here names the owner's server, models, questions or paths in a tracked file.

## Completion criteria

1. The command runs a corpus file against the library and writes a report outside the repository; it refuses a corpus or report
   path inside the project, a corpus that is not in the expected form, and a book id or a query that is not valid; and it changes
   nothing and calls no model.
2. The report holds, for each query and for the questions and in all, the measures of the scope for the four searches by the rules
   above, the number of blocks the full-text search was limited to and whether the limit was reached, the books that are
   uncovered, the leak measure and the word counts of the cards, the input manifest, and the hash of the corpus file and the date;
   the command refuses a catalog that is not the one the cards make.
3. Cards exist for every book named as a right answer, or the book is reported as uncovered with the reason, and the catalog was
   built from the cards that exist.
4. The queries were fixed before the first run, and the run is recorded with the hash of the corpus.
5. The owner has read the cards chosen for reading and has said what they found.
6. The result is written in this plan with no personal question, project, path or machine in it, with a provenance line, and the
   owner's decision on the next step is recorded.

## Increments

### Increment A — The evaluation command

**Outcome:** the owner can run a corpus of questions against the library and get a report of what the cards and the full text find.
**Dependencies:** none.
**Affected areas:** a new module `engine/kb/trial.py`, its tests `engine/tests/test_trial.py`, `engine/kb/__main__.py`, and
`engine/README.md`.
**Steps:**
1. Write the tests first, on a temporary library with cards filed from synthetic card text and a synthetic corpus; they fail because
   the module does not exist.
2. Define the corpus file: a format number, a list of questions each with an id, its text, its queries (plain words) and the ids of
   the books that answer it, and optionally a list of field words. Check every part (ids with the book-id rule, queries with the
   word rules of the searches, sizes), and refuse a file inside the project's folder.
3. Check the inputs: every book named is a book of the library; the catalog is the one the cards make (the generation of the newest
   card of each book is what the catalog holds), otherwise refuse and say to run `card-index`; and which right books have no card
   (uncovered). Build the input manifest.
4. For each query run the four searches: the cards (all fields), the summary side, the neutral side, and the full text taken to
   books in order of first appearance from at most 50 blocks. Record the books found in order, each with its place, and whether the
   full-text limit was reached.
5. Compute the measures by the rules in the assumptions: the places, the union and best place for a question, the sets over
   (question, right book) pairs on the covered pairs, the recall, the hit rate, the reciprocal rank and its mean, the noise, each with
   its counts. Test the rules on a small synthetic corpus whose answers are worked out by hand, including a question with two queries,
   a right book found by only one of them, a right book with no card, and a tie of places.
6. Compute for each card its word count and that of each field, and the words of its title and topics that its neutral fields repeat
   (and the corpus's field words, if given), with the share of cards that repeat at least one.
7. Write the report as JSON outside the project's folder with the corpus hash, the date and the input manifest, refuse an existing
   file unless asked to replace it, and print a short summary. Add the command `trial CORPUS REPORT`.
8. Say in `engine/README.md` what the command reads and writes, that it calls no model and changes nothing, the rules of the
   measures, and what the measures mean.
9. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_trial engine.tests.test_catalog engine.tests.test_card engine.tests.test_setup`.
The catalog and card tests are included because the command reads through them; the setup tests because `__main__.py` changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-trial#A`.

### Increment B — Cards for the books of the trial

**Outcome:** the books that the owner names have cards, and the catalog holds them.
**Dependencies:** none (it needs the owner's choice of books).
**Affected areas:** the owner's library (cards in the book folders, the catalog file in the index root); the plan's Result. No
tracked file other than the plan changes.
**Steps:**
1. List the books of the library with their titles, the length of their converted text and the number of pieces, and propose to the
   owner which to make cards for (every book with real text is the natural choice; a page with a few lines gets a card from its
   metadata). Say roughly what it costs: about a minute for a short paper, more for a long one, with the models loaded. Every book
   that will be named as a right answer in increment C must be among them, or it is reported as uncovered and left out of the
   card measures.
2. On the owner's word for the books and for sending their text to the models in the config, run `cards` for them, a few at a time.
   A book that fails is reported with its reason; a refused answer is kept aside and read, and the plan records what it shows.
3. Run `card-index` and check that the catalog holds the cards.
4. Record in the Result the books carded, the time, the calls, and each failure.
**Verification:** the runs of steps 2 and 3, read as written; `python3 -m unittest engine.tests.test_cardmake engine.tests.test_catalog`
once more, since no code changes and the result of this step depends on those.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-trial#B`, which holds the plan's Result.

### Increment C — The questions, the run and the decision

**Outcome:** the owner has the report, has read some cards, and has decided what comes next.
**Dependencies:** A and B.
**Affected areas:** the owner's corpus file and report (outside the repository) and the plan's Result.
**Steps:**
1. Ask the owner for the questions and, for each, the books that answer it (the owner is shown the titles). A set of questions
   about the books of the walk-through library, with known answers, is enough; it is a test of the mechanism.
2. Write the queries for each question as short plain words, show them to the owner, and freeze them: the corpus file is written
   once and its hash recorded.
3. Run `card-index` so that the catalog is the one the cards make, then run `trial` on the corpus. Record the report's numbers, the
   uncovered books, the hash, the date and the manifest's hashes.
4. Choose, with the owner, a few cards to read (one that the search found well, one that it did not, and one with a leak). The owner
   says for each whether the summary is too literal and whether its uses read like the questions an agent would ask. Record the
   counts.
5. Write the result in the plan: the numbers, what the cards found that the text did not and the reverse, the leak measure, the
   length and shape that worked, what the owner found on reading, and the limits (eighteen books, a few questions, the owner's own
   labels). Name no personal question, project, path or machine. Add a provenance line.
6. Give the owner a recommendation and record the owner's decision: search by meaning, themes, both, or neither for now.
**Verification:** the run of step 3, read as written, and `python3 -m unittest engine.tests.test_trial` once more.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-trial#C`, which holds the plan's Result.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After C, rerun
`python3 -m unittest engine.tests.test_trial engine.tests.test_catalog engine.tests.test_card engine.tests.test_cardmake
engine.tests.test_setup` once. The wider engine suite is not named: the plan adds one command and changes no stage, no index and no
card. A wider run is the owner's to ask for.

## Risks and sensitive actions

- **Book text goes to the models.** Increment B sends the text of the books the owner names, over the registry's link, which is
  plain HTTP on the owner's network. It needs the owner's word for the books. The books of the walk-through library are public pages
  and papers.
- **The owner's questions.** They may reveal the owner's projects. They are held outside the repository, the command refuses a
  corpus path inside it, and the result written in the plan names none.
- **Conclusions beyond the evidence.** Eighteen books and a few questions cannot show that cards help in real use. The report and the
  result say what they can and cannot show, and the decision is the owner's.
- **A query tuned after seeing results.** The queries are frozen and the corpus hash is recorded; a change makes a new corpus and a
  new report, and the old report stays.
- **Time.** Making cards for the remaining books takes tens of minutes of model time, and `cards` is run a few books at a time.

## Review record

Reviewer: Codex through the review engine (model gpt-5.6-terra). Round 1 of 3: changes needed, three findings, all applied.

- R1-F1, applied: the plan let the owner choose a smaller set of books while the questions could name a book that has no card, which
  would have counted a missing card as a card search that missed. The report now lists the right books that are uncovered and leaves
  them out of the card measures (counting them in the full-text ones, with the reason), and increment B says every right book must
  be among the books carded.
- R1-F2, applied: the measures were not defined for a question with several queries. The assumptions now fix the rules (the union
  over the queries, the best place of a book, the unit of a (question, right book) pair, the sets, recall, hit rate, reciprocal rank
  and its mean, noise, each reported with its counts), and the tests include a hand-worked synthetic corpus with a two-query
  question, a book found by one of them, a book with no card and a tie.
- R1-F3, applied: the report held only the corpus hash and the date. It now holds an input manifest (the library, each book's
  current version, the generation and hash of its newest card or that there is none, the hash of the catalog file and of the
  full-text index), and the command refuses a catalog that is not the one the cards make, so that a later reader can tell which
  cards and which catalog gave a result.

## Deferred work

- Search by meaning, themes and the weave, which this plan ends with a decision about.
- Catching the neutral fields' leaks by code in the cards themselves, and tuning the prompts, if the trial shows a problem.
- A larger library, questions from the owner's real projects, and a trial of whether a brainstorm is better for having the library
  (the success test of `knowledge-base.md`), which needs the workbench package.
- Stemming in the card search, a better excerpt, and telling the reader how old the catalog is, which the card-catalog run showed.

## Result

### Increment A — The evaluation command (built; not committed)

- Built `engine/kb/trial.py`, the `trial CORPUS REPORT [--replace]` command, `engine/tests/test_trial.py` (44 tests) and a README
  section. Tests were written first and failed because the module did not exist. The hand-worked corpus (five questions, four
  books, one with no card) was worked out on paper first; two of my own hand calculations were wrong where the code was right,
  and I corrected the tests.
- Verification as run: `python3 -m unittest engine.tests.test_trial engine.tests.test_catalog engine.tests.test_card
  engine.tests.test_setup` gave 204 tests, OK; the trial tests also pass with ResourceWarning as an error; `wb run code-work check`
  found no problems. Not run: any other test file, the command on the owner's library (increment C), any model.
- Deliberate breaks, each from a green baseline: 19 of the first build (all caught, after re-running one whose text did not match)
  and 13 of the review fixes, of which 11 were caught at once; a failed write leaving its claimed file behind survived, so a test
  was added and the break is now caught. One survivor stays: the check in `run` that a catalog row's book and version are the
  card's own is redundant, because `catalog.search` refuses such a row with the same message; it is kept as a second guard.
- Review: the `reviewer` agent, round 1, no blocking findings. Applied: F1 the reciprocal rank is one over the best place (not
  the position in the merged list), now tested and stated in the README; F2 a field word of any length, normalised and case-folded,
  is matched against all neutral words; F3 the report holds found, noise and per-question hit and reciprocal rank for each query
  and search; F4 a newest card that cannot be read is an uncovered book with its own reason and no longer blocks the trial with
  advice that could not fix it; F5 right books the text index does not hold are listed as `text_uncovered`, and inactive books get
  their own reason; F6 the report folder is resolved from its folder (a link at the report name is replaced, not followed) and the
  name is claimed with an exclusive create, so a file that appears after the check is not overwritten, and a failed write removes
  its claim; F7 the catalog and text index hashes are taken before the searches and checked again after (a change refuses the
  run), and each catalog row is checked against its card; F8 the README states the limits and the stop list.
- Recorded, not changed: F9, the plan's sentence that uncovered books are "counted in those of the full text" is looser than the
  code, which counts them only in the full-text recall over all pairs (`text_all_pairs`) and reports the hit rate, reciprocal rank
  and sets over covered pairs; the README and the module docstring state this. F6's remaining notes (a corpus opened by path after
  the check, a hard link to a file in the project, no check against the library's own folders) were not applied: the plan's threat
  model has no outside attacker, and the corpus and report are the owner's files. The rest of the review is in this entry.
- Committed as `61874f4`.

### Increment B — Cards for the books of the trial (run; not committed)

- The owner chose the 12 books with real text: the 3 already carded and 9 more (Simulated annealing, Hamming's talk, the sqlite3
  documentation, Quantenmechanik, Neural Machine Translation, ResNet, BERT, ViT, VGG), and said to send their text to the models
  in the config. Left out: the three short or thin pages (Quotes to Scrape, Hacker News, Hello world) and the three long
  documents (CLIP, PaLM, RFC 9110), so a right book among those would be uncovered.
- Run: `cards --book` once per book, one after another, with the two models the config names for the two tasks. All nine were
  carded at generation 1, none failed, none refused (no refused-answers folder exists). Pieces and calls: 2/3, 3/4, 4/5, 4/5, 4/5,
  3/4, 4/5, 5/6 and 12/13, 50 calls in all. Only the first run was timed (31 seconds for a two-piece page); the others were not.
- The Hamming card is marked partial: the talk has 14 pieces and 12 are sampled, the cap. The other eight are not partial.
- `card-index` then built the catalog: 18 books, 12 versions, 12 cards, 0 failed. `card-search annealing` found the annealing
  card with its citation; no other search was tried. Cards were not read for quality here; that is increment C.
- Verification as run: the runs above, read as written; `python3 -m unittest engine.tests.test_cardmake engine.tests.test_catalog`
  gave 159 tests, OK. Not run: any other test file.
- No code changed. The commit holds this entry only.
- Committed as `8db655f`.

### Increment C — The questions, the run and the decision (done)

Steps 1 to 3 and the numbers of step 5 were recorded first (commit `dc5554b`); the card reading, the rest of step 5 and the
decision of step 6 follow the numbers below.

- **The corpus.** Fifteen questions over the 12 carded books, with two short plain-word queries each and 17 (question, right book)
  pairs in all. I drafted twelve of them from my knowledge of the books, without reading any card, and the owner added three
  more about one book (the annealing page). The right books are my labels, which the owner saw and kept; they are not an independent
  judgment. The questions are about public papers and pages and name no project. The queries were frozen when the file was
  written. The corpus and the report are held outside the repository.
- **The run.** `python3 -m kb trial <corpus> <report>` at commit `8db655f`, Python 3.15.0, on 2026-11-07 (22:21 UTC), with the
  catalog built by `card-index` after the last card was made. The corpus sha256 is
  `fa7e0e4a5a8f104a8b6645a68141ddc615c0f05a77f6f561b9c3f5a8f6711961`. The manifest holds 12 cards, one per carded book, the catalog
  file sha256 `83291fd222dc67c7d6f42af83c6b65d61357e5773739f1bb8c737b28662dd39c` and the text index sha256
  `decc0ac6a2a8beb3c0cfdedc3f335cf3cf401b290fc495cefac69165c57298bb`. No right book was uncovered. No model was called.
- **The numbers** (the unit is a pair; every right book had a card):

  | | cards, all fields | summary side | neutral side | full text |
  |---|---|---|---|---|
  | recall, of 17 pairs | 16 | 16 | 13 | 15 |
  | questions with a right book found, of 15 | 14 | 14 | 11 | 14 |
  | mean reciprocal rank | 0.89 | 0.89 | 0.70 | 0.82 |
  | other books found per question, mean | 1.53 | 1.40 | 0.87 | 5.20 |

  Of the 17 pairs, 15 were found by both the cards (all fields) and the full text, 1 by the cards only, none by the text only,
  and 1 by neither. The full-text search reached its limit of 50 blocks for at least one query in 9 of the 15 questions, so its
  books, and its count of other books, are lower bounds.
- **What each found that the other did not.** The cards found one right book the text missed (a translation paper for a question
  about attending over source words). Neither found the right book for the stopping-criterion question about annealing; I suspect
  the page does not cover it, but I did not check, so that is unverified. The neutral side missed the question in German and two
  others, and the cards ranked one right book third where the text ranked it first.
- **The leak measure.** All 12 cards repeat words of their title or topics in their neutral fields (by the word-list measure of
  the README, which counts words such as "attention" in a card titled with it). Card length: 223 to 337 words, mean 280.8, over
  12 cards. The neutral side still found 13 of 17 pairs, which may be because of those repeated words; this was not tested.
- **What this can and cannot show.** The questions are easy: plain topical queries, mostly one right book, drafted from the books
  themselves, over 18 books, so both searches nearly reach the ceiling and a difference of one pair (16 against 15) is noise. Four
  of the 15 questions concern one book, so they are not independent. The labels are mine. It shows that a search of the cards does
  not do worse than a search of the full text on questions like these, and that it returns far fewer other books; it does not show
  that cards help in real use, and says nothing about questions that share no words with the book.
- Provenance: the `trial` command of `engine/kb/trial.py` at commit `8db655f` (increment A committed as `61874f4`), run once on
  the corpus with hash `fa7e0e4a…1961`; the numbers above are copied from its summary and from the per-question places in the
  report, and are not recomputed elsewhere.
- **Reading the cards (step 4).** Four cards were read with the owner: one the search found well (a pretraining paper), one that
  every search missed on a question (the annealing page, on stopping criteria), one with the most repeated words (a translation
  paper, 18) and one that ranked poorly (the prompt-injection page, third on the cards where the text put it first). I read and
  described them; the owner answered by chat. The owner's answers: the summaries are "almost too literal, but not quite"; the
  "useful for" lines are fine; on the size limits, the owner asked whether limits should scale, and then preferred deciding
  dynamically from the content while the card is made, and a second model to weigh in on whether to continue; and said they would
  spend time on preparing an accurate card over fast cards with padding. The poor rank of the injection page was caused by my
  queries (one found nothing in either search, the other was too broad), not by the card.
- **What I found in the cards.** The facts a paper or page states are well captured. Unsupported material appears in the limits,
  caveats and adjacent topics (for example a need for model internals, a limit on low-resource languages, a caveat about
  real-time deployment, none of which I could find in the sources), and some caveats mention the card's own "notes". Card size
  barely follows book length: 223 to 337 words for books of 16,000 to 238,000 characters. A read-only check of the items of the 12
  cards against each book's own text (a scratch script, not kept) found that word overlap is a weak detector of unsupported items:
  items I judged unsupported mostly passed it, and it mainly caught caveats about the card's own notes. The length and shape that
  worked: a summary of 34 to 79 words, three to four key ideas and the neutral fields as they are; nothing here shows a longer
  card would find more.
- **Recommendation.** Neither search by meaning nor themes for now. The trial found no keyword failure that meaning would fix, it
  cannot show whether one exists (the questions were easy and the library small), and the measured problems are in the accuracy
  of the cards, which meaning-based search would only spread. First make the cards accurate (the candidate below), then run a
  second trial on harder questions and more books.
- **The owner's decision.** The owner replied "Go with your recommendations" to a message that recommended exactly this and
  listed the follow-up work. I take that as: neither search by meaning nor themes for now, and the card-grounding candidate with
  the accuracy measures below. The owner did not state the decision in other words; if I took it wrongly, it is the owner's to
  correct.
- **Follow-up.** The candidate `cards#card-grounding` was added to the cards roadmap on the owner's word. My recommendations for
  it, to be shown to the owner as a revised candidate before the roadmap changes: ask each claim in the notes for a short verbatim
  quote that a check confirms occurs in the piece; measure the accuracy of the current cards on a sample of items the owner labels
  as supported, unsupported or inference, and test any model check against those labels before trusting it; mark each item as
  stated, inferred or unverified; fix the wording in the prompt (the right word for the kind of source, no mention of "notes");
  keep a second model's check and two-run agreement for later; and test whether covering every piece of a long book improves
  accuracy before raising the sample cap.
- Provenance of the card readings: `card-show` on four cards of the library at commit `dc5554b`, and a read-only scratch script
  that read the 12 cards and each book's converted text; nothing was written. The numbers are as printed.
- Limits of the whole trial: 12 carded books of 18, 15 questions drafted from the books with labels I chose, four questions about
  one book, and a few cards read. It shows the cards do not do worse than the text on easy questions; it does not show that they
  help in real use.
- Verification as run: the trial run above, read as written; `python3 -m unittest engine.tests.test_trial engine.tests.test_catalog
  engine.tests.test_card engine.tests.test_cardmake engine.tests.test_setup` gave 288 tests, OK (the whole-plan verification, which
  includes `engine.tests.test_trial` again). Not run: any other test file. No code changed in this increment.
- Evidence: this Result, to be committed with the trailer `Plan: 2026-11-07-card-trial#C`.
