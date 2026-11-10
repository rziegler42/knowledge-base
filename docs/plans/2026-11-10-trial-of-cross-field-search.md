# A trial of cross-field search

Status: Completed
Created: 2026-11-10
Candidate: cross-field-discovery#cross-field-trial
Specs: docs/specs/testing.md, docs/specs/card.md

## Goal

The owner knows whether the library finds, for a problem stated in the words of one field, a source from another field, and how a
keyword search of the text, a keyword search of the cards, a search by meaning of the problem as written and the problem search compare.
When the plan is done, twelve problems (ten with an expected source from another field and two controls with none) have been run
through the four searches, a report holds the place of each expected book in each search, and the plan's Result gives the counts,
reads them against a rule written before any search ran, says what cannot be concluded, and records the owner's decision on whether to
go on to `cross-field-discovery#pair-judging`. The roadmap makes pair judging depend on the result showing that search alone is not
enough, so if the reading is "enough" or "unclear" the recommendation is not to start it, and the Result says what else the numbers
point to (for example more books or a second corpus). Starting pair judging against that reading would be a change of the roadmap's
direction and stops for the owner as such.

## Scope

- A command of the engine, `python3 -m kb trial-problems CORPUS REPORT`, that runs a corpus of problems through the four searches and
  writes a report outside the repository (it reports numbers and decides nothing), with a `--check` that reads the corpus and the
  library and sends nothing.
- The corpus: the twelve problems of this plan, each with the queries and the sub-problems that an agent wrote **without seeing the
  expected books or the library**, held outside the repository and hashed.
- One live run, with the owner's word, that sends the problems and sub-problems to the owner's embedding server.
- The reading of the result and the owner's decision.

## Non-goals

- Judging pairs, themes, adding books to the library, or any change to the searches, the cards or the vectors: the plan measures what
  there is. A decision to build something is a later plan.
- Measuring how well an agent sets aside the books of the problem's own field. The report simulates a perfect setting aside by removing
  the books the owner lists as home books; a trial of an agent doing it with the skill, in a project, is deferred.
- A claim about how the library would do when it is larger or covers other fields.

## Assumptions and constraints

- The library holds about eighty books in seven fields (game theory, game players, learning models, algorithms, high performance
  computing, CAD and 3D printing); 78 cards have a neutral description and 230 vectors are made by `qwen3-embedding:4b` with the
  query prefix that the config sets. `card-embed` must name that model and the vectors must be current, or the command refuses.
- **The twelve problems** (the owner approved them with this plan; the expected books are the owner's judgment, taken from the
  proposal of 2026-11-10, and are by title as the catalog stores it; `(W)` means a Wikipedia article):

  | # | Home field | Problem, in the words of its field | Expected from another field | Home books (set aside) |
  |---|---|---|---|---|
  | 1 | 3D printing | A slicer must order the many separate islands of each layer so the nozzle spends as little time as possible moving without printing. | Simulated annealing (W), Genetic algorithm (W) | G-code (W), Fused filament fabrication (W), 3D printing (W) |
  | 2 | CAD / engineering | Tuning the dimensions of a part to the best strength, when each trial is a slow finite element simulation. | Genetic algorithm (W), Simulated annealing (W) | Finite element method (W), Computer-aided design (W), Solid modeling (W) |
  | 3 | Poker bots | A bot must decide how much to bet when it cannot see the opponent's cards, without a rival learning to exploit its pattern. | Nash equilibrium (W), Minimax (W) | DeepStack, Deep Reinforcement Learning from Self-Play in Imperfect-Information Games |
  | 4 | LLM training | Training a very large model runs out of GPU memory because every GPU holds a full copy of the weights, gradients and optimizer state. | Message Passing Interface (W) | ZeRO, Megatron-LM, Horovod |
  | 5 | Web scraping | A crawler must remember millions of visited addresses in little memory, and an occasional repeat fetch is acceptable. | Bloom filter (W) | Quotes to Scrape, RFC 9110: HTTP Semantics, Hacker News |
  | 6 | Deep learning | A training run should take big steps early and ever smaller ones later, so it ends settled and not bouncing. | Simulated annealing (W) | Adam, Proximal Policy Optimization Algorithms, Trust Region Policy Optimization, Soft Actor-Critic |
  | 7 | Databases | An index over keys that follow a smooth distribution uses far more memory than the data's pattern needs. | The Case for Learned Index Structures | sqlite3 documentation |
  | 8 | Route planning | Finding the shortest route across a huge road network without examining every road. | Dijkstra's algorithm (W), A* search algorithm (W) | none |
  | 9 | Economics of pricing | Several sellers each react to the others' prices, and we want to know whether the prices settle or cycle. | Multi-Agent Reinforcement Learning: A Selective Overview, Evolutionary game theory (W) | Nash equilibrium (W), Prisoner's dilemma (W), Mechanism design (W) |
  | 10 | Scientific computing | A recursive calculation recomputes the same sub-results over and over and takes exponential time. | Dynamic programming (W) | Supercomputer (W) |
  | 11 | Control | A bakery must decide how much bread to bake each day when demand is uncertain and unsold bread is wasted. | none in the library | none |
  | 12 | Control | A clinical trial must decide when evidence is strong enough to stop early. | none in the library | none |

  The titles above are shorthand. A card's title is stored in full (for example `Simulated annealing - Wikipedia`), and the corpus uses
  the full titles, which Increment A's `--check` resolves; a title that matches no book or two books is refused.

  Known weak spots, written down before any run: in #3 and #9 the expected and the home books are all game material, so "another field"
  is blurred; #1, #2 and #6 share two expected books; a generic optimization book would match many problems.
- **The four searches**, the same library for each: (T) the text search (`search`, what an agent has today through `wb run kb search`),
  with the keyword queries of the corpus; (K) the keyword search of the cards (`card-search`, all sides), with the same queries; (M) the
  search by meaning (`card-search --meaning`) with the problem as written; (P) the problem search (`problem-search`) with the
  sub-problems of the corpus, at `--limit 10` for each.
- **How a book is placed in each search, one rule for each.** T and K: the rules of `engine/kb/trial.py` (a book's place is counted
  from 1 by its first appearance in one query's results; over several queries a book's place is the smallest it has; books of the
  same place are ordered by book id). M: the order of its one list. P: the order of the merged list that `problem-search` returns,
  that is by best score and then by book id, which is what an agent is given; the place of a book is its position in that list, up
  to 50, and the per-sub-problem ranks are not used for placing. The command and the report use these rules and no other.
- **The measures** (every number reported with its count) are these. For each of the ten problems with expected books and each search: the place of each expected
  book (up to 50, or "not found"); **hit at 5** (an expected book among the first five books); **hit at 5 after setting aside** (the
  same, after the home books of the problem are removed from the list); the reciprocal rank of the best-placed expected book; and the
  number of home books among the first five. For all twelve: the first five books of each search and, for M and P, the best score.
- **The reading, written before any search runs** (a proposal that the owner may change when approving the plan; it is a guide and
  the owner decides). Let T5, K5, M5 and P5 be the number of the ten problems whose hit at 5 after setting aside is true for each
  search, and B5 the largest of the four. It answers two questions, each against all four searches.
  1. *Is search alone enough?* (the question on which the roadmap makes pair judging depend). **Enough** if B5 is 7 or more; **not
     enough** if B5 is 4 or fewer; **unclear** at 5 or 6, and then the plan says what it would take to tell. A tie for the best
     counts as the best.
  2. *Does the problem search add anything?* **Yes** if P5 exceeds the larger of T5, K5 and M5 by 2 or more; **no** if P5 is no larger
     than that; **unclear** if it exceeds it by 1.
  In every case the Result also gives the places and not only the counts, and how the controls look.
- **The corpus is prepared blind.** The queries and the sub-problems are written by an agent that is given only the text of one
  problem (and, for the sub-problems, the text of the skill `pose-a-problem`), one agent for each problem, and never the expected
  books, the home books or the library; the number of tools it used is recorded as evidence that it read nothing. One attempt each:
  the trial measures a first attempt and not an agent that tries again after seeing results. Up to three keyword queries of one to
  three words each, and one to five sub-problems.
- The corpus is held outside the repository (`~/.local/share/knowledge-base/trial/`), is hashed, and is read by the owner before any
  search. The twelve problems are synthetic and stand in this plan; the corpus adds what the agents wrote. Nothing tracked points to
  the file by path; the Result cites it by hash.
- Every sentence of M and P goes to the owner's server over plain HTTP: at most 12 problems and 60 sub-problems. The twelve problem
  texts also go to a cloud model for the blind preparation (Increment B). Each is said to the owner before it runs.

## Completion criteria

1. `python3 -m kb trial-problems` refuses a corpus in the wrong form, inside the project, naming a title that is not in the catalog
   or is not unique, or a report that exists; with `--check` it sends nothing; it writes a report of the measures above and never
   fails a build.
2. The corpus of twelve problems exists outside the repository with its hash, written blind, and the owner has read it.
3. One run of the four searches over the twelve problems, with the owner's word, wrote a report outside the repository.
4. The Result gives the counts and places per search, the reading against the rule above, the controls, what cannot be concluded and
   the owner's decision.
5. `wb run code-work check` finds no problems.

## Increments

### Increment A — The command that runs the trial

**Outcome:** `python3 -m kb trial-problems CORPUS REPORT [--replace] [--check]` reads a corpus (format 1, JSON outside the project:
for each problem its id, text, a control flag, the titles of its expected books and home books, one to three keyword queries and one
to five sub-problems), runs the four searches, and writes a report with the measures of the plan. With `--check` it reads the corpus and
the library, resolves the titles and prints what it would run, and sends nothing.
**Dependencies:** none (builds on `trial.py`, `search.py`, `catalog.py`, `vectors.py` and `problem.py`).
**Affected areas:** `engine/kb/problemtrial.py` (new), `engine/kb/__main__.py`, `engine/tests/test_problemtrial.py` (new),
`engine/README.md`, `docs/specs/testing.md`.
**Steps:**
1. Write the tests first, with a fake bridge and the fixture library of `test_vectors`: the corpus is refused if it is not format 1,
   is larger than a bound, has no problem or more than 50, has a text over 1,000 characters, has more than three keyword queries or
   five sub-problems, names a title that is not in the catalog or matches two books, repeats an id, or lies inside the project; the
   report is refused if it exists (unless `--replace`) or lies inside the project; a missing or stale catalog, text index or vectors
   is refused; `--check` makes no bridge call and writes no report; each search gives the places by its own rule above (T and K:
   first appearance, smallest place over queries, ties by book id; M: the order of its list; P: the position in the merged list, even
   when a book has a better rank in one sub-problem than its position there); hit at 5, hit at 5 after setting aside, the reciprocal rank and the count of home
   books among the first five are right on a hand-made case, including a home book that is removed and shifts the others up; a control
   has no measures but lists its books; M sends the problem text and P the sub-problems, each once, with the query prefix; one failing
   call fails the command and writes no report; the report holds the corpus hash, the hashes of the catalog, the text index and the
   vectors, the model, `query_prefix` as a flag and never the prefix, and no path of the machine.
2. Add the module and the subcommand. It reads the library and writes only the report. Its help says that the problem texts and
   the sub-problems go to the embedding model's server.
3. Deliberate breaks, each from green: P placed by the smallest per-sub-problem rank, the place taken from the last query and not the smallest, the home books not removed, removed
   but the places not shifted, hit at 5 counting the sixth book, a control measured, M sent the sub-problems, P sent the problem text,
   the corpus inside the project accepted, a title matching two books accepted, `--check` sending a call, the report overwritten
   without `--replace`.
4. Document the command in `engine/README.md` and the built evaluation in `docs/specs/testing.md` (Evaluation).
5. **Checkpoint.** The command reads a file the owner names, writes a file outside the project and sends the sentences of the corpus to
   a server. Name this to the owner and ask once whether to run a security review with the installed module; record the answer in the
   Result. A review runs only if the owner asks.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_problemtrial engine.tests.test_problem
engine.tests.test_vectors engine.tests.test_catalog` and `wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-trial-of-cross-field-search#A`.

### Increment B — The corpus, written blind

**Outcome:** the corpus file for the twelve problems exists outside the repository, passes `--check`, and the owner has read it.
**Dependencies:** A.
**Affected areas:** this plan's Result and the corpus file outside the repository. No tracked code.
**Steps:**
1. Tell the owner what is sent: the text of each of the twelve problems, and for the sub-problems the text of the skill, to a cloud
   model through twelve subagents (one for each problem, in parallel). The problems are synthetic. Run only on the owner's word.
2. For each problem, give one agent only the problem text (and the skill text for the sub-problems) and ask for up to three keyword
   queries of one to three words and for one to five sub-problems, as JSON, one attempt, reading nothing. Record, for each, the number
   of tools it used (the evidence that it read nothing). If an agent used a tool, discard its answer, say so, and ask again once.
3. Assemble the corpus with the expected and home titles of the plan, write it outside the repository, run
   `python3 -m kb trial-problems --check`, and show the owner the whole corpus. Record its hash. The owner reads it and says whether it
   stands; a change by the owner is recorded with the reason and the hash is taken again.
**Verification:** `--check` accepts the corpus; every agent used no tool or its answer was replaced; the owner has read the corpus.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-trial-of-cross-field-search#B`, holding the Result and the hash.

### Increment C — The run and the reading

**Outcome:** one report of the four searches over the twelve problems exists outside the repository, the Result gives its counts and
places and the reading against the rule, and the owner has decided whether to go on to pair judging.
**Dependencies:** B.
**Affected areas:** the report file outside the repository; this plan's Result. No tracked code.
**Steps:**
1. Say what is sent: the twelve problem texts and at most 60 sub-problems, each with the query prefix, to the owner's server `ned`
   over plain HTTP, and nothing else. Run only on the owner's word.
2. Run `python3 -m kb trial-problems CORPUS REPORT` once. Record the report's hash.
3. Write into the Result, from the report: for each search the counts T5, K5, M5, P5, the places of the expected books, the reciprocal
   ranks, the home books among the first five; the first five books for each control and the scores of M and P; the reading against the
   rule (enough, not enough or unclear); and what cannot be concluded (twelve problems that one author chose, a library of about eighty
   books in seven fields, one first attempt by each blind agent, a simulated setting aside, one run).
4. Give the owner a recommendation that follows the reading (pair judging is recommended only if the reading of the first question is
   "not enough") and record the owner's decision.
**Verification:** the report holds all twelve problems and four searches; its counts are the ones written in the Result; `wb run
code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-trial-of-cross-field-search#C`, holding the Result and the
owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun `test_problemtrial` once
and `wb run code-work check`. A wider run is not named: the plan adds one module and one subcommand and changes none of the search, card
or vector code. What could break outside the tested area is the shared use of `search`, `catalog.search` and `vectors.search`, which
are called and not changed; their tests are part of Increment A's run.

## Risks and sensitive actions

- **The expected books are one person's judgment** and the problems are twelve: the result is a first look, and the plan says so.
- **Sentences go out.** M and P send the problem texts and sub-problems to the owner's server in the clear, and the blind
  preparation sends the problem texts to a cloud model. The problems are synthetic. Each send is said to the owner and waits for the
  word.
- **A blind agent may not stay blind.** Its tools cannot be taken away by this plan; the count of tools it used is the evidence, and an
  answer from an agent that used one is discarded.
- **The corpus and the report hold nothing private** (the problems are synthetic) but stay outside the repository, as the corpus and
  the report of the earlier trial of the cards do, and are cited by hash; the command refuses a corpus or a report inside the
  project.
- **A security surface**: a file read, a file written and a network send; Increment A asks the owner once about a review.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, three findings, all major and all
applied:

- **R1-F1, applied.** The reading compared the problem search only with the two keyword searches and left out the search by meaning.
  It now answers two questions, each against all four searches: whether search alone is enough (the best of the four), and whether the
  problem search adds anything over the best of the other three.
- **R1-F2, applied.** The plan gave two rules for placing a book in the problem search (the smallest per-sub-problem place, and the
  order returned), and the merged list is ordered by best score. Each search now has one rule, and the problem search uses its merged
  list; the tests and the breaks of Increment A name it.
- **R1-F3, applied.** The roadmap makes pair judging depend on the result showing that search alone is not enough. The plan now
  recommends it only on that reading, and says that starting it against the reading is a change of direction that stops for the owner.

A second round has not been asked for.

## Deferred work

- A trial of an agent using the skill in a project, with its own setting aside of the home field and its reasons, on the same twelve
  problems (this plan simulates the setting aside).
- A second corpus with more variety and, above all, more books and fields in the library: the result of this trial holds for a
  library of about eighty books and says nothing of a larger one.
- Running the same trial again after books are added or the cards are made again (the corpus and the command make that cheap).

## Result

### Increment A — The command that runs the trial (done)

- **What was built:** `engine/kb/problemtrial.py` and the subcommand `python3 -m kb trial-problems CORPUS REPORT [--replace] [--check]`
  (in `engine/kb/__main__.py`), with the README section "The trial of cross-field search" and a bullet under "Evaluation" in
  `docs/specs/testing.md`. The corpus (format 1) is checked in full (form, sizes, ids, texts that can be sent, one to three keyword
  queries, one to five sub-problems, titles that match exactly one book, no expected book in a control, none both expected and home)
  and must lie outside the project. The four searches are T (`search`), K (`card-search` all sides), M (`vectors.search` of the problem
  text) and P (`problem.search` at limit 10); each is placed by its own rule, P by its position in the merged list. The report has, for
  each problem and search, the order, the books at a place of 5 or less with their titles, the scores of M and P, and for a problem with
  expected books the places, the places after setting aside, hit at 5 (both ways), the reciprocal rank and the home books among the
  first five; a control has no measures. The summary counts the hits, the pairs within ten and the mean reciprocal rank over the
  problems with expected books. The report holds the hashes of the catalog, the text index and the vectors, the model, whether a query
  prefix was used (never the prefix), the cards covered, and no path. `--check` resolves the titles and prints what would be sent
  (`sentences_to_send`) with no call and no report.
- **Tests first:** `engine/tests/test_problemtrial.py`, 45 tests on six books with chosen vectors, a hand-worked case of four problems
  and a fake bridge; the first run failed on the missing module. Three more failures after the first implementation were my own: the
  text and card searches were placed by position in the merged order, which lost the ties of the `trial.py` rule (fixed in the code
  and the test), and two tests that expected "nothing was sent" for failures that happen after a send.
- **Verification as run:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_problemtrial engine.tests.test_problem
  engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_trial engine.tests.test_models` gave 483 tests, OK;
  `wb run code-work check` found no problems. No call was made to the owner's server.
- **Deliberate breaks, each from green:** 28, of which 27 were caught: P placed by the smallest per-sub-problem rank, the place taken from
  the last query, the home books not removed or removed without moving the others up, hit at 5 counting the sixth (both ways), a control
  measured, M sent the sub-problems, P sent the problem text, a corpus inside the project, a title matching two books or none,
  `--check` sending a call, a report overwritten without `--replace`, a change of the library not noticed, six sub-problems allowed, a
  sub-problem not checked, a book both expected and home, a control with expected books, the prefix flag always false, a pair at the
  eleventh place counted, the mean reciprocal rank, no stale-catalog check, stale vectors accepted, cards without a vector accepted, no
  coverage check, and the counts left out of the report. The one not caught is redundant: the explicit check of the vectors' model,
  dimension and prefix is now also made by `vectors.coverage`, so removing the first changes nothing.
- **Review:** the read-only `reviewer` agent, one round, **one blocking finding, applied**: the command did not refuse stale vectors,
  although the plan says it does. `vectors.search` leaves out a stored vector whose card text changed and a card with no vector, and
  only counts them, so a half-stale file would have given a trial that looked clean. Fixed with a test first (4 failures): a new
  `vectors.coverage(index_root, cfg)` returns the counts of a search without sending a query, and the command refuses, before
  anything is sent, when `stale` or `without_vector` is not zero, naming `card-vectors`; `--check` shows the counts and the report holds
  them. To share the counting, `vectors.search` was refactored (`_catalog_rows`, `_usable`) with no change of behaviour: `test_vectors`
  gave 119 tests, OK, with 3 new ones for `coverage`. **This changes `vectors.py` and `test_vectors.py`, which the plan's list of affected
  areas does not name.** Not blocking, recorded: (2) for T and K over several queries "hit at 5" and "the first five" mean a place of 5
  or less by the rule of `trial.py`, so up to three books can share a place and the list of the first five can hold more than five; for
  M and P it is the first five exactly; the README says so. The plan's words "among the first five books" are read that way. (3) A
  card's title is its book's title (`root["title"]`), the same for every version, so the finding that a book with versions of different
  titles would not resolve does not apply. (4) The question about a security review (step 5) is put to the owner after this report.
  The fix itself had no second round of review; it was checked by its tests and four breaks.
- **Not done, and why:** the plan says a stale text index is refused; only its presence is checked, as `trial` does, because there is
  no cheap way to compare the index with the books (the README says to run `index` after adding books).
- **Security review (step 5).** Asked once of the owner, with the surface named: a corpus file the owner names is read, a report file is
  written outside the project, and the problem texts and sub-problems are sent to the owner's server in the clear through the existing
  path (the new `vectors.coverage` only reads). My recommendation was no (the corpus is the owner's own bounded file, and the send path
  and the file-writing code are ones already reviewed). The owner's answer: **no**. No security review was run for this surface.
  (Committed as `3daece5`.)

### Increment B — The corpus, written blind (done)

- **What was sent, and said beforehand:** the text of each of the twelve problems and steps 1 and 2 of the skill `pose-a-problem` (the
  parts that say how to restate and split; the plan says "the text of the skill", and the rest of the skill is about calling the tool and
  reading its answer, so it was left out), to a cloud model through twelve subagents, one for each problem, run in parallel. The owner
  said "start b" after being told this. The problems are synthetic.
- **Blindness:** each agent was given only its problem and told to use no tool and to answer once. The transcript of each shows one tool
  call, the `SubagentHandback` that delivers its report, and no other: no file, search or shell tool. No answer was discarded, none was
  asked for twice. One attempt each. The agents were never given the expected books, the home books or the library.
- **The corpus:** `~/.local/share/knowledge-base/trial/cross-field-problems-corpus.json` (outside the repository, mode 600), 11,727
  bytes, **sha256 `f9bdc6268b6b65bdf0c174236f6370c7314d1051a1bd65a63ac9a3f36e91af67`**. Twelve problems (ten with expected books, two
  controls), the expected and home titles of the plan in the full form the catalog stores, 36 keyword queries and 37 sub-problems. I
  typed the agents' answers into a script that wrote the file and then compared each with its agent's transcript: all twelve are
  identical, character for character. No sub-problem has an apostrophe or a quotation mark.
- **`--check`** (`python3 -m kb trial-problems CORPUS REPORT --check`): accepted. Every title resolves to exactly one book; the model is
  `qwen3-embedding:4b` with a query prefix; 78 cards would be searched, 0 stale, 0 without a vector; **49 sentences would be sent** (12
  problem texts and 37 sub-problems; the plan's bound was 72). Nothing was sent and no report was written.
- **Something the owner should weigh when reading the corpus.** The blind agents brought their own knowledge, as a real agent would, and
  in several problems named the answer outright in a keyword query or a sub-problem: p05 ("Bloom filter"), p06 ("annealing schedule"),
  p07 ("learned index", and a sub-problem about a learned model of the cumulative distribution), p09 ("Nash equilibrium", "best response
  dynamics"), p10 ("dynamic programming", "memoization"), and p01 ("traveling salesman"). For those problems the keyword searches (T and
  K) and the problem search (P) start from the answer's name and are not a test of a vocabulary gap; the search by meaning (M) uses the
  problem as written and is. The Result of Increment C must say so when it reads the counts.
- **The owner's reading.** The whole corpus (every keyword query and sub-problem, with the caveat above) was shown to the owner, who
  then said "commit b" and made no change. That is recorded as the corpus standing as it is, with the hash above; the owner did not
  otherwise comment on it, and no wording was changed or asked for again. (Committed as `41aaea4`.)

### Increment C — The run and the reading (done)

- **What was sent, and said beforehand:** 49 sentences (the 12 problem texts and the 37 sub-problems), each with the query prefix, to the
  owner's server `ned` over plain HTTP, and nothing else; the keyword searches sent nothing. The owner said "start c" after being told.
- **Provenance.** Run on 2026-11-10 at commit `41aaea4`: `python3 -m kb trial-problems CORPUS REPORT`, once, with the corpus of
  Increment B (sha256 `f9bdc626…91af67`), against the catalog `76728081…`, the text index `5056fe38…` and the vectors `a30b6c73…` (78
  cards covered, 0 stale, 0 without a vector), model `qwen3-embedding:4b` with a query prefix. The report is outside the repository,
  sha256 **`214185068f6f4e24f1be1a1e7ee3df93c42f42f6a37785d6b10d53ca99466f3b`**. The command finished without a failed call.
- **The counts** (ten problems with expected books; fifteen pairs of problem and expected book): hit at 5 — **T 9, K 7, M 8, P 9** of
  10, and the same after setting aside the home books (taking the home books out of the lists changed no hit). Pairs within the
  first ten — T 12, K 8, M 12, P 14 of 15. Mean reciprocal rank — T 0.833, K 0.633, M 0.644, P 0.825.
- **The places of the expected books** (`-` = not in the list of at most 50, or at most 10 books for each sub-problem for P):

  | | expected | T | K | M | P |
  |---|---|---|---|---|---|
  | p01 | Simulated annealing, Genetic algorithm | 2, 1 | -, - | 26, 42 | 1, 5 |
  | p02 | Genetic algorithm, Simulated annealing | 1, - | -, - | 3, 1 | 3, 1 |
  | p03 | Nash equilibrium, Minimax | 1, 3 | 1, - | 8, 5 | 6, 4 |
  | p04 | Message Passing Interface | - | - | - | - |
  | p05 | Bloom filter | 1 | 1 | 1 | 1 |
  | p06 | Simulated annealing | 1 | 1 | 5 | 1 |
  | p07 | The Case for Learned Index Structures | 1 | 1 | 1 | 1 |
  | p08 | Dijkstra's algorithm, A* search algorithm | 3, 1 | 1, 1 | 1, 2 | 2, 1 |
  | p09 | Multi-Agent Reinforcement Learning, Evolutionary game theory | 3, - | 3, - | 5, 1 | 6, 1 |
  | p10 | Dynamic programming | 1 | 1 | 1 | 1 |

  Every search missed p04 (the expected book is not among the first five of any; MPI is not in the first 50 of M nor the first ten of any
  sub-problem of P). In M the home books were among the first five in p01 (three of them), p04 (three), p09 (three), p03 (two) and
  p02, p05 and p06 (one each); in P in p04, p06 and p09 (three each) and p03 (one).
- **The reading against the rule written before the run.** B5, the best of the four, is 9: **search alone looks enough** (7 or more).
  P5 is 9 and the larger of T5, K5 and M5 is also 9, so **the problem search adds nothing** by the rule (it needed 2 more); P5 is 1 more
  than M5 (8), from one problem, p01, where the search by meaning put the expected books 26th and 42nd, behind the three home books,
  and the problem search, with the restatement of the blind agent, put them 1st and 5th.
- **The controls.** The keyword searches and both meaning searches return books for the bakery (p11) and the clinical trial (p12) all
  the same: M gave Minimax, Training Compute-Optimal Large Language Models, Dynamic programming, Simulated annealing and Mechanism
  design for p11; P gave Minimax and A* search first for p11 and p12 (T gave Nash equilibrium, Evolutionary game theory and a
  multi-agent paper for p12, and nothing for p11). So an agent has to judge every list, as the skill says. The best score of M for the
  controls is 0.359 and 0.365 and that of P 0.397 and 0.428, below the best score of every problem with an expected book (M from 0.42, P
  from 0.51). With two controls this is an observation and no threshold.
- **What cannot be concluded, and what weakens the reading.** (1) Ten problems that one person chose, with expected books that are
  one person's judgment, in a library of about eighty books in seven fields where many of the expected books are the Wikipedia article
  of the very method: "enough" holds for this corpus and this library, not for a larger one. (2) The blind agents brought their own
  knowledge and named the answer in p05, p06, p07, p09, p10 and p01; T and K and P are strong where they did. T's 9 of 10 is largely a
  measure of an agent that knows the name of the method and a library that holds an article about it; it does not show that the
  keyword search would find a source for a problem whose answer the agent does not know. M, which uses the problem as written, needs
  no such knowledge and found 8 of 10. (3) The setting aside of the home field is simulated by the list of home books, and it changed
  nothing here. (4) One first attempt by each blind agent, one run, no repetition. (5) p03 and p09 are blurred between fields, as the
  plan warned; p01, p02 and p06 share expected books. (6) The two controls cannot support a threshold.
- **Recommendation (given before the owner's word).** Do not go on to pair judging now: by the plan's own rule search alone looks
  enough, and the roadmap allows pair judging only if the trial shows it is not. The one miss everywhere, p04, is an analogy at a
  distance (splitting the state of a training run across workers, matched with message passing), which is the kind of case where a judge
  of pairs might help; one problem is too few to build on. What the numbers point to instead is a test that this trial cannot make: a
  second corpus whose problems come from fields the blind agent does not know the answer to, or from a larger library, where the
  keyword search has no name to start from. That would be a plan of its own.
- **Owner's decision:** the owner said to go with the recommendation: **do not go on to pair judging now**
  (`cross-field-discovery#pair-judging` is not started; the roadmap is not changed). The second corpus, with problems whose answers the
  blind agent does not know, or a larger library, is not planned yet; it is listed under Deferred work and would be a plan of its own.
- **Verification as run:** the report holds all twelve problems and four searches; the counts above are the ones it holds (read from
  the report, with the summary printed by the command); `wb run code-work check` found no problems.
