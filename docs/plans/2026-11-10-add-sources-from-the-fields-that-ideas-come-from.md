# Add sources from the fields that ideas come from

Status: Proposed
Created: 2026-11-10
Candidate: none (loading sources is outside the roadmaps `cards` and `cross-field-discovery`, and this is one batch of an operation the engine already does, not new work to build)
Specs: none (no spec changes; the plan only runs commands the engine has)

## Goal

The library holds the sources from which the best-known transfers between fields come, so that a second trial of cross-field search
can ask about problems whose answers the library holds in another field and an agent may not know by name. When the plan is done, 30
more pages from twelve fields are books of the library with a card that has a domain-neutral description and with vectors, the library
can be searched by meaning over them, and the Result records what was captured, what failed and how long the card run took.

## Scope

- One batch of 30 public web pages (the list below), captured, scanned, converted and indexed with the commands that already exist.
- A grounded card, with its neutral description, for each new book, made by the models of the owner's config.
- The catalog and the vectors rebuilt so that the search by meaning covers the new books.

## Non-goals

- Any change to the engine, the cards or the searches. No code is written.
- The second trial itself (a corpus of problems over the new books, its blind preparation and its run): it is a plan of its own, written
  when this one is done.
- Papers from arXiv. This batch is web pages only, so that every address is one that can be named now; papers can be a second batch.
- A crawler, shelves, or choosing sources by a program.
- Cards made again for the 79 books that have one.

## Assumptions and constraints

- **The list.** Each is `https://en.wikipedia.org/wiki/<title>`, and the owner approves the list when approving this plan and again
  before the first request. A page that does not exist or cannot be converted is recorded as a failure and not replaced by another.

  | Field (the transfer it stands for in the project's evaluation set, or the owner's choice) | Pages |
  |---|---|
  | Statistical physics (annealing into search) | Annealing (metallurgy), Metropolis–Hastings algorithm |
  | Bandits (into game-tree search) | Multi-armed bandit, Thompson sampling |
  | Sequential testing (into stopping rules) | Sequential analysis, Sequential probability ratio test, Optimal stopping |
  | Foraging (into search stopping) | Optimal foraging theory, Marginal value theorem |
  | Epidemics (into spread of information) | Compartmental models in epidemiology, Percolation theory |
  | Immune systems (into anomaly detection) | Artificial immune system, Immune system |
  | Ant trails (into routing) | Ant colony optimization algorithms, Stigmergy |
  | Visual cortex (into image recognition) | Visual cortex, Neocognitron |
  | Operations research (the owner's choice; the Newsvendor model answers a problem the library cannot answer today) | Operations research, Linear programming, Queueing theory, Newsvendor model |
  | Discrete mathematics (the owner's choice) | Discrete mathematics, Graph theory, Combinatorics |
  | Numerical methods (the owner's choice) | Numerical analysis, Newton's method, Monte Carlo method |
  | Linear algebra (the owner's choice) | Linear algebra, Singular value decomposition, Eigenvalues and eigenvectors |

  The pages of the last four fields are my choice within the fields the owner named, four for operations research (which holds the
  Newsvendor model) and three for each of the other three, and are the owner's to change. In all 30 pages from twelve fields.
- **The twelve sentences of Increment C**, fixed here before any run, one for each field, written without the name of the method and
  never changed after a result is seen. A page "of the field" is one the table lists for it.

  1. Statistical physics: A system is cooled slowly so that it settles into a state of low energy, and random moves that raise the
     energy are accepted with a probability that falls as the temperature falls.
  2. Bandits: Choose again and again among options whose payoffs are unknown, balancing the use of the option that looks best against
     the learning of how good the others are.
  3. Sequential testing: After each new observation, decide whether the evidence so far is enough to stop and choose or whether to
     collect one more observation.
  4. Foraging: An animal searching one patch of food after another must decide when the rate of gain in the present patch has fallen
     far enough to leave and look for another patch.
  5. Epidemics: The members of a population move between states such as susceptible, infected and recovered, and the spread through
     contacts is described by rates and by the structure of the network of contacts.
  6. Immune systems: A system learns what its own normal patterns look like and responds to anything that does not match them.
  7. Ant trails: Many simple agents leave traces that fade with time and follow the strongest traces, so that short routes between two
     places come to carry the most traces.
  8. Visual cortex: Layers of units respond to simple local features such as edges, and later layers combine those responses into
     responses to larger patterns and whole objects.
  9. Operations research: Decide how much to order or to allocate before the demand is known, when too much is wasted, too little
     loses sales, and resources and capacity are limited.
  10. Discrete mathematics: Count the ways of arranging or choosing items under conditions, and describe how a set of objects is
      connected by links.
  11. Numerical methods: Find an approximate answer when no exact formula exists, by repeating a calculation that improves the
      estimate or by averaging many random trials.
  12. Linear algebra: Represent data as tables of numbers and break them into a few directions that carry most of their variation, so
      that a large table can be replaced by smaller ones.

- **Live requests.** Each page is one request to a third-party site, made by `capture-url`, which sends an honest user agent, follows
  the limits the engine sets (size, time, redirects) and is run three seconds apart as in the earlier walk-through. Nothing is sent
  to the site but the request for the page.
- **Model runs.** The card run sends the text of each new book, in pieces, to the models the config names on the owner's server `ned`
  over plain HTTP, and the vectors step sends the neutral descriptions of the new cards to the embedding model there. The owner is told
  what is sent before each and says yes. The card run can be stopped and started again (`cards-queue`) and takes the books of its plan
  only.
- **The library is the owner's.** The new books are added to the bulk root like the others. The plan does not delete or change a book.
- Wikipedia text is licensed for reuse with attribution; each book keeps its source address and retrieval date, and its citation line
  carries them.

## Completion criteria

1. Of the 30 pages, the number captured, scanned, converted and indexed is recorded, with the reason for each that was not, and none of
   the 79 existing books changed.
2. Each new book that converted has a grounded card with a neutral description, or the Result gives the reason it has none.
3. The catalog and the vectors cover the new cards (`card-vectors` reports them as made and a second run sends nothing), with 0 stale.
4. For each of the twelve sentences listed above, a new page of its field is among the first five books of
   `card-search --meaning`, or the Result says which sentences did not and what came instead. The sentences are not changed after a
   result is seen, and a miss is a finding to report and not a failure of the plan.
5. `wb run code-work check` finds no problems.

## Increments

### Increment A — Capture and process the 30 pages

**Outcome:** the pages that can be fetched and converted are books of the library, scanned, converted and indexed for text search.
**Dependencies:** none.
**Affected areas:** the library's bulk root and index root (new books only); this plan's Result. No tracked code.
**Steps:**
1. **Checkpoint, before any request.** Name to the owner the surfaces this batch uses and what has been reviewed: capture, the scan and
   the conversion (security reviews are recorded in the Results of the plans for the first slice and the scan); the card queue
   (reviewed on 2026-11-08 at the owner's request); and the model call and the card prompts, which receive the text of pages from
   outside (the Results of their plans say that no security review was asked for or run). Ask once whether to run the installed
   security-review module on that path before the batch, and record the answer in the Result. A review runs only if the owner asks.
2. Show the owner the list as it stands and the number of requests (30, three seconds apart, to one site, so about a minute and a half) and wait for a yes.
3. Run `python3 -m kb capture-url ADDRESS` for each address, one at a time, and record `filed`, `held` or `failed` and the reason.
4. Run `python3 -m kb process` and read its report: scanned, converted, indexed, and the books that failed or were marked partial.
5. Read a passage of two of the new books with `search` and `read`, and compare the existing 79 books before and after (the same
   count, the same text hashes).
**Verification:** the counts and the reasons recorded; the 79 books unchanged; a search of the text finds a word of a new page.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-add-sources-from-the-fields-that-ideas-come-from#A`, holding the Result.

### Increment B — Cards for the new books

**Outcome:** each new book that converted has a grounded card with a domain-neutral description.
**Dependencies:** A.
**Affected areas:** the new books' folders (a card each) and the card runs in the index root; this plan's Result. No tracked code.
**Steps:**
1. Run `python3 -m kb cards-queue plan --book ID ...` with the ids of the new books only; it makes no call. Show the owner the number of
   books and the calls that can be counted, say that the text of these books goes to the models on `ned`, and wait for a yes.
2. Run `python3 -m kb cards-queue run RUN`, and again if books are left, up to the passes the queue allows. Record the time the run took,
   the cards made, the books that failed twice and their reasons.
3. For a failed book, record the reason and stop; a new attempt or a fix is the owner's decision and not part of this plan.
**Verification:** `cards-queue status RUN`; a card for each converted book or a recorded reason; `card-show` on two of them.
**Evidence:** the one local commit, with the trailer `...#B`, holding the Result.

### Increment C — The catalog and the vectors

**Outcome:** the search by meaning covers the new cards.
**Dependencies:** B.
**Affected areas:** the catalog and the vectors in the index root; this plan's Result. No tracked code.
**Steps:**
1. Run `python3 -m kb card-index`. Then say what is sent (the neutral fields of the new cards, three for each, to the embedding model on
   `ned`, in the clear) and wait for the owner's yes before `python3 -m kb card-vectors`; a second `card-vectors` must send nothing.
2. For each of the twelve sentences listed under the assumptions, run `python3 -m kb card-search '<the sentence>' --meaning` (this sends
   the sentence to `ned`; say so and wait for a yes) and record the first five books and whether a new page of that field is among them.
3. Check that the corpus file of the earlier trial is the one recorded: `shasum -a 256` of the owner-held file must give
   `f9bdc6268b6b65bdf0c174236f6370c7314d1051a1bd65a63ac9a3f36e91af67` (recorded in the Result of the plan
   `2026-11-10-trial-of-cross-field-search`). Then run `python3 -m kb trial-problems CORPUS REPORT --check` with that file as CORPUS and,
   as REPORT, a name in the same owner-held folder that does not exist yet; the check makes no call and writes no report. It confirms
   that the library still passes the checks of the command (the titles still resolve, the vectors are current). Nothing tracked
   names the file by path; the hash is the citation.
**Verification:** the counts of `card-vectors` (made, kept, stale 0), the twelve searches recorded, `--check` accepted.
**Evidence:** the one local commit, with the trailer `...#C`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changes its inputs. At the end, confirm the counts of books,
cards and vectors from the three Results, and run `wb run code-work check`. No code is changed, so no test run is named. What could
break outside what is checked is the library's existing books and cards: Increment A compares them before and after, and the card run
takes the books of its plan only.

## Risks and sensitive actions

- **Requests to a third-party site** from the owner's machine, 30 in all, each said to the owner beforehand. A page can be a
  redirect, large or malformed; the engine's limits and the scan apply as to every capture.
- **Text sent to the owner's server in the clear** (the card run and the vectors). The pages are public; the server is the owner's.
- **Disk and time.** The new books are small. The card run's time is not known until it is measured; the earlier run made 13 cards in
  about 29 minutes of logged time, about two minutes a book, which would make roughly an hour or more for 30 books, and the queue can
  be stopped and started again without losing the cards made.
- **The new books change what a search returns.** Searches that agents run after this will find them. That is the purpose, and the
  vectors are rebuilt only for the new cards (the others are kept).
- **A wrong or missing page** is a recorded failure, not a substitution.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, five findings (four major, one minor):

- **R1-F1 (major), rejected.** The plan says `Candidate: none`, although a 30-source batch is substantial and the plan itself defers a
  roadmap for loading sources. Codex suggested a loading-sources candidate. That would need a new roadmap, which is a change of
  direction and the owner's to decide; the owner went with the recommendation to keep `Candidate: none`: the plan writes no code and
  only runs commands the engine has, the owner directed the batch and the fields, and a roadmap would need a finish line that cannot be
  stated precisely today. The Deferred work keeps the note that such a roadmap can be written if the owner wants one.
- **R1-F2 (major), applied in part.** The plan omitted the once-per-surface question about a security review. Checked against the
  earlier Results: capture, scan, conversion and the card queue have had reviews, but the Results of the model-call and card-stage plans
  say that none was asked for, and a card run sends text from outside pages to a model. Increment A now begins with a checkpoint that
  names the surfaces and what was reviewed, asks the owner once and records the answer.
- **R1-F3 (major), applied.** The twelve searches of Increment C were only "a sentence about the field", open to being chosen after a
  result. The plan now lists the twelve exact sentences, fixed before any run, says which pages count for each field, and says that a
  miss is reported and the sentences are not changed.
- **R1-F4 (major), applied.** `CORPUS` and `REPORT` of the check in Increment C were not named. The plan now names the earlier corpus by
  its recorded hash (verified against the file), requires a hash check before the run, and names a report that does not exist so that
  the check writes nothing.
- **R1-F5 (minor), applied.** "Three each" was wrong for operations research, which has four pages. Fixed; the total of 30 was right.

A second round has not been asked for.

## Deferred work

- The second trial of cross-field search over the new books: new problems from these fields, a blind corpus and a run, as the earlier
  trial did. A plan of its own.
- A second batch with arXiv papers for the same fields, and sources from other fields.
- A roadmap for loading sources (what to load, in what order, with what check), if the owner wants one; none exists.

## Result

Empty until work starts.
