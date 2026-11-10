# Add sources from the fields that ideas come from

Status: Completed
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

### Increment A — Capture and process the 30 pages (done)

- **Checkpoint and list, both said beforehand (steps 1 and 2).** The surfaces and what had been reviewed were named to the owner:
  capture, scan and conversion (reviewed), the card queue (reviewed 2026-11-08), and the model call and card prompts (no review asked for
  or run). The owner was asked once whether to run the security review before the batch; my recommendation was no, and the owner's
  answer was **no** (no security review was run for this batch). The 30 addresses were then shown with the number of requests (30,
  three seconds apart, one site) and the owner said **yes**. I added one safeguard of my own, that the first three requests would be
  looked at before the other 27.
- **Before the batch.** The store listed **80 books** (79 of them with a card; the plan's "79" meant the carded ones). A read-only
  snapshot recorded, for each, one hash over the path and content of every file of its folder.
- **Capture (steps 3).** `python3 -m kb capture-url` for each address in the order of the table, one at a time, three seconds apart, by a
  small driver script outside the repository, on 2026-11-10 at commit `0d0e8b5`. The first three were looked at (all `filed`), then the
  other 27. **All 30 were `filed`; none `held`, none `failed`.** The new books, in the order of the table: Annealing (metallurgy)
  `01M72RYSF85XRRWQ3777BQXES7`; Metropolis–Hastings algorithm `01M72RYWV9M3N66616WWGQ6GSA`; Multi-armed bandit
  `01M72RZ06V3JF52J3ZAZA428N2`; Thompson sampling `01M72RZ77M6BQ01MQK6KQW2HZX`; Sequential analysis `01M72RZAJ0KPX6DW0B2XJE9176`;
  Sequential probability ratio test `01M72RZDTTXXG6JNJZ8XD6PQCV`; Optimal stopping `01M72RZH684MNWQ2TWS56B71AX`; Optimal foraging theory
  `01M72RZMGYXBPQ7JZSD18JTCZS`; Marginal value theorem `01M72RZQTD3N5DG90AHHTY2D78`; Compartmental models in epidemiology
  `01M72RZVAAQMM72E3Z8NP03XES`; Percolation theory `01M72RZYRCB2KCSXFZCR22YQEK`; Artificial immune system
  `01M72S024N2PYAKDQDAZY6WXPX`; Immune system `01M72S05H2S9BVX0GWD24WZPC3`; Ant colony optimization algorithms
  `01M72S08ZQR5X7BC1NYS1ZWGWH`; Stigmergy `01M72S0CCJZJPD3M4Z4YMTJE01`; Visual cortex `01M72S0FSJS7KNK5CFWM45XQK9`; Neocognitron
  `01M72S0K618P8C11TA42DR0G2M`; Operations research `01M72S0PH765EM1KZW3GEQZ1NS`; Linear programming `01M72S0SWRH2HD71S7Z8Z47DXM`;
  Queueing theory `01M72S0X7DQKV4B301VVBW4JD5`; Newsvendor model `01M72S10KDCX8GDV97FQE7Z18Q`; Discrete mathematics
  `01M72S13Y315F6PCPN84TZ4CD7`; Graph theory `01M72S179VTSK44PKHT3BMG4Y0`; Combinatorics `01M72S1AN46TVA37SKENKTCBQG`; Numerical
  analysis `01M72S1E5GXNYR1E2BSVXYSBEM`; Newton's method `01M72S1HHSPR8FNSWGBP52HCQN`; Monte Carlo method
  `01M72S1MXQXAB106HVMB18R9GR`; Linear algebra `01M72S1RA7D5YJ1AAE6P28536G`; Singular value decomposition
  `01M72S1VQBY820CG8ZN6KKJN7H`; Eigenvalues and eigenvectors `01M72S1Z4DKCTE9FSBGETWY5J6`.
- **Process (step 4).** `python3 -m kb process --book ID` for the 30 ids only, so that nothing else was touched. Its report holds 90
  results (30 scanned, 30 converted, 30 indexed), **all `done`**, none failed.
- **Checks (step 5).** The same snapshot taken again: **80 books before, 110 now, none of the 80 changed, 30 new.** A text search of
  three queries ("Metropolis Hastings", "Thompson sampling", "eigenvalues eigenvectors") returned five results each, all from the new
  books. A passage of the Thompson sampling page was read back with `read` (status `found`, the citation line with the address and the
  retrieval date, the text between the untrusted-text markers).
- **Not checked here.** Whether a page is marked partial or carries a scan caveat is not in the report of `process`; the cards, made in
  Increment B, carry it. The index was not rebuilt from the book folders for a comparison; no code or test changed, so no test was run.
- **Verification as run:** the counts above; `wb run code-work check` found no problems. (Committed as `7638d78`.)

### Increment B — Cards for the new books (run; decided: option (b), a plan of its own)

- **Plan, said beforehand (step 1).** `python3 -m kb cards-queue plan --book ID ...` with the 30 new ids made the run
  `20261110t133834z-efd82d` (30 books, none skipped; no call). Shown to the owner with the order of the models (`gemma4:12b` for the
  notes, `gpt-oss:20b` for the card, `phi4` for the checks, `qwen3:14b` for the second round), 97 calls known (67 notes, 30 card) and
  about two calls of checks for each card, and the statement that the text of the pages goes in pieces to those models on `ned` over
  plain HTTP. The owner said **yes**.
- **A stop on the owner's word.** The run was started at about 13:39 UTC and, within a minute or two, the owner asked to pause it: the
  GPU of `ned` had crashed and needed a reboot (the owner then said that the crash had happened several days before and was noticed
  only then). The background task was stopped; no `cards-queue` or `ask-ollama` process was left; the run's state was 30 waiting, none
  made. After the reboot the owner said to start again (13:48:26 UTC), and the run went on from its journal.
- **Result.** The run finished at 14:10:25 UTC, 22 minutes after the restart, in 2 passes: **27 books done, 3 failed, none dropped.** The
  27 cards are generation 1 of their books. **The 3 that failed** (each tried twice and kept aside, as designed): Sequential analysis
  `01M72RZAJ0KPX6DW0B2XJE9176` and Queueing theory `01M72S0X7DQKV4B301VVBW4JD5`, both with "the support of a sentence of this part is
  the numbers of notes; inferred and none are not allowed: 'inferred'", and Stigmergy `01M72S0CCJZJPD3M4Z4YMTJE01` with "the answer's
  sentence_fields, sentences and sentences_support are not lists of the same length" (the intermittent slip of the earlier runs). As the
  plan says, a new attempt or a fix is the owner's decision.
- **Calls and time** (read from the records of the 27 cards; the calls of the failed attempts are not in them and are not counted): 211
  calls (63 notes, 27 card, 94 check, 27 second round); 207 of them after the restart, in 21.8 minutes, **6.3 seconds a call**. The
  earlier queue run (2026-11-08 and 09, 66 books) took about 5 seconds a call in 495 calls, with a `keep_alive` of 10 minutes; this run
  had 30 seconds, after a reboot, and a different mix (more check calls, 45 percent against 33), so the two are not a controlled
  comparison. About 25 percent slower a call, not more.
- **What the cards are like — a finding that stops the plan before Increment C.** The cards were made by the card call that the engine
  has now, which asks for the summary and the five neutral parts as *sentences* with support and drops a sentence that no verified note
  supports (the form built in the plan `2026-11-09-ground-the-summary-and-neutral-fields`). **24 of the 27 cards are marked partial**,
  against 8 of 63 in the earlier run, because a part of the card is empty: no sentence was left for the problem in 13 cards, the
  provides in 9, the approach in 8, the needs in 22, the limits in 3, the summary in 1; 3 cards also have fewer than three key ideas.
  Of the three fields that the search by meaning uses (problem, approach, provides) the 27 cards hold **51 of the 81 possible**; 8
  cards have all three, 10 have two, 7 have one and 2 have none. The 78 older cards with a model part, made in the earlier form, have
  4 empty fields among the same 234. 457 items are marked stated and 102 inferred over the 27 new cards. The books are otherwise
  intact: the same snapshot as in Increment A shows **80 books before, 110 now, none of the 80 changed**.
- **Why, and what I missed.** The engine has no choice of card form: `card.py` can read a card of the earlier form, but `cardmake` and
  `cardqueue` make only the sentence form. On 2026-11-09 the owner decided, on my recommendation, that "the old form is not replaced and
  the library is not carded again with the new form", and the recommendation said to "keep the new form as an option"; no option was
  built, so any new carding gives the new form. I did not check which form this plan's card run would make when I drafted it, and the
  plan's goal ("a grounded card with a domain-neutral description") assumed the complete neutral parts of the older cards. I should have
  caught this when drafting the plan.
- **Options for the owner** (recorded for the decision; none is done): (a) go on to Increment C with the cards as they are, and retry
  the three failures once; the vectors would be 51 (up to about 60 with the retries), two cards would be unsearchable by meaning, and a
  miss in the twelve searches could be a miss of the card form and not of the library; (b) a small plan of its own to give the engine a
  choice of card form, as the decision of 2026-11-09 meant, and to card the 30 books again in the earlier form as a new generation (the
  new-form cards stay as generation 1, never overwritten); (c) stop here.
- **Owner's decision:** option (b), on my recommendation. A plan of its own, `2026-11-10-a-choice-of-card-form`, gives the engine a
  choice of card form (the earlier form the default) and cards these 30 books again in the earlier form as generation 2, keeping the
  27 sentence-form cards as generation 1. This plan goes on with its Increment C (the catalog, the vectors and the twelve searches)
  after that, so that the twelve searches are made over the cards the owner wants. The three books that failed are carded again by
  that plan. The 27 cards of this run stay in the library as they are.
- **Not done:** `card-index`, `card-vectors` and the twelve searches (Increment C); no card was read with `card-show`.

### Increment C — The catalog and the vectors (run, 2026-11-10)

- **Cards at this point.** The plan `2026-11-10-a-choice-of-card-form` carded the books again: 29 of the 30 have a card in the earlier form
  as their newest generation (26 as generation 2 above the sentence-form generation 1; Sequential analysis, Queueing theory and
  Stigmergy as generation 1); Newsvendor model failed twice there and has only its sentence-form card (generation 1). The searches below
  are therefore over earlier-form cards for 29 books and a sentence-form card for 1.
- **Catalog.** `python3 -m kb card-index`: 110 books, 109 cards, 109 versions with a card, 0 failed (the run of the other plan had
  already rebuilt it with the same counts).
- **Vectors.** Before: 78 cards searched, 0 stale, 30 without a vector (found with `vectors.coverage`, which sends nothing). The owner said
  yes to sending the neutral fields of the new cards (problem, approach, provides) to the embedding model on `ned`, in the clear.
  `python3 -m kb card-vectors` (4 seconds): 109 cards, 1 with no model fields (a card built from the metadata), 0 left out, 319 vectors,
  230 kept, 89 made, 89 texts sent, model `qwen3-embedding:4b`, dimension 2560, nothing replaced. (At most 90 texts were expected; one
  field is empty and nothing is sent for an empty field.) A second `card-vectors` made 0, kept 319 and sent 0 texts. Coverage after: 108
  cards searched, 0 stale, 0 without a vector.
- **The twelve searches.** The owner said yes to sending the twelve fixed sentences, one `card-search '<sentence>' --meaning` each, to
  the embedding model on `ned` (sentence 1 was sent twice, once to see the shape of the output, so 13 sends). The sentences were not
  changed. Result: **a page of the field is among the first five books for 12 of 12 sentences**; a page of the field is first for 11
  (sentence 1, statistical physics, has the library's older Simulated annealing page first and Metropolis–Hastings second). The pages of
  the field found, and the place of the first one:

  | # | Field | Pages of the field among the first five (place) |
  |---|---|---|
  | 1 | Statistical physics | Metropolis–Hastings (2) |
  | 2 | Bandits | Multi-armed bandit (1), Thompson sampling (2) |
  | 3 | Sequential testing | Sequential probability ratio test (1), Optimal stopping (2), Sequential analysis (3) |
  | 4 | Foraging | Marginal value theorem (1), Optimal foraging theory (2) |
  | 5 | Epidemics | Compartmental models (1), Percolation theory (2) |
  | 6 | Immune systems | Artificial immune system (1) |
  | 7 | Ant trails | Stigmergy (1), Ant colony optimization (2) |
  | 8 | Visual cortex | Neocognitron (1), Visual cortex (3) |
  | 9 | Operations research | Newsvendor model (1), Operations research (2), Queueing theory (3) |
  | 10 | Discrete mathematics | Combinatorics (1), Graph theory (2), Discrete mathematics (3) |
  | 11 | Numerical methods | Monte Carlo method (1), Newton's method (3), Numerical analysis (5) |
  | 12 | Linear algebra | Singular value decomposition (1), Eigenvalues and eigenvectors (2), Linear algebra (5) |

  No sentence missed, so there is no miss to explain. Observations: the scores of the first hit are mostly 0.55 to 0.73, lower for
  epidemics (0.57, then 0.41), discrete mathematics (0.45) and operations research beyond the Newsvendor model (0.45); new pages of other
  fields also turn up in the first five (for example Ant colony optimization for the immune sentence, Optimal stopping for bandits and
  foraging), which is the cross-field result the library was widened for. Newsvendor model, the one page with a sentence-form card, is
  still found first for its sentence. The searches show that the new pages are found by a description of what they are about; they do not
  show that a hard transfer would be found, because I wrote each sentence about a page that was in the library.
- **The corpus of the earlier trial.** `shasum -a 256` of the owner-held file gave `f9bdc6268b6b65bdf0c174236f6370c7314d1051a1bd65a63ac9a3f36e91af67`,
  the recorded hash. `python3 -m kb trial-problems CORPUS REPORT --check` with that file and a report name that did not exist was
  accepted: 12 problems (10 positive, 2 controls), every title resolved, 108 cards searched, 0 stale, 0 without a vector, 49 sentences
  that a full run would send; it made no call and wrote no report (confirmed: no such file). Nothing tracked names the file by path.
- **Verification as run.** The counts of `card-index` and `card-vectors` above (made 89, kept 230 then 319, second run 0 sent, stale 0);
  the twelve searches recorded above (scratchpad script, run 2026-11-10 at commit `535a282`); `--check` accepted;
  `wb run code-work check` after this entry. No code was changed.
