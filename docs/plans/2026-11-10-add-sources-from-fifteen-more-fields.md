# Add sources from fifteen more fields

Status: Proposed
Created: 2026-11-10
Candidate: none (loading sources is outside the roadmaps `cards` and `cross-field-discovery`; this is the second batch of an operation the engine already does, not new work to build)
Specs: none (no spec changes; the plan only runs commands the engine has)

## Goal

The library holds the sources of fifteen more fields from which ideas travel to other fields, none of which it covers now: control,
information, statistical physics, inference, ecology and evolution, networks, economics, scheduling, distributed systems, cryptography,
learning in the brain, signals, optimisation, production and self-organisation. The pages come first and are measured alone; a small set
of papers follows and is measured apart, so that the effect of each kind of source can be read. When the plan is done, 60 public web
pages and up to 8 arXiv papers are books of the library, each with a card in the earlier form and with vectors, the library can be
searched by meaning over them, and the Result records what was captured, what failed, how long the card runs took, whether a
description of each field finds a page of it, and what the papers changed.

## Scope

- Stage one: one batch of 60 public web pages (the list below), captured, scanned, converted and indexed with the commands that
  already exist; a card for each; the catalog and the vectors rebuilt; and fifteen searches by meaning, one for each new field, whose
  sentences are fixed in this plan before any run. The result is recorded **before any paper is captured**.
- Stage two: up to 8 arXiv papers (the list below), by the same steps, and the same fifteen searches run again with the same sentences,
  compared with stage one.

## Non-goals

- Any change to the engine, the cards or the searches. No code is written.
- A second trial of cross-field search over the new books (a corpus of problems, its blind preparation and its run): a plan of its own,
  when the owner asks for it.
- Any paper or page not named below, a crawler, shelves, or choosing sources by a program.
- Cards made again for the 109 cards the library has, or any change to the 110 books it holds.

## Assumptions and constraints

- **The pages.** Each is `https://en.wikipedia.org/wiki/<title>`. The owner approves the list when approving this plan and again before
  the first request. A page that does not exist or cannot be converted is recorded as a failure and is not replaced by another; a
  title that is a redirect is captured at the address it leads to, and both addresses are recorded. None of the 60 is a page the library
  already holds (checked against the titles of the 110 books on 2026-11-10).

  | Field (what it stands for) | Pages |
  |---|---|
  | Control (feedback keeps a system near a target) | Control theory, PID controller, Kalman filter, Optimal control |
  | Information (coding, entropy, error correction) | Information theory, Entropy (information theory), Huffman coding, Error detection and correction |
  | Statistical physics (collective change at a critical point) | Ising model, Phase transition, Statistical mechanics, Renormalization group |
  | Inference (belief updated by evidence, hidden states) | Bayesian inference, Hidden Markov model, Expectation–maximization algorithm, Markov chain Monte Carlo |
  | Ecology and evolution (cycles of populations, selection, swarms) | Lotka–Volterra equations, Natural selection, Swarm intelligence, Particle swarm optimization |
  | Networks (structure of links, ranking) | Network science, Small-world network, Scale-free network, PageRank |
  | Economics (incentives, auctions, markets) | Auction theory, Vickrey auction, Market design, Principal–agent problem |
  | Scheduling (routes, packing, assignment, project time) | Travelling salesman problem, Knapsack problem, Assignment problem, Critical path method |
  | Distributed systems (agreement among failing machines) | Consensus (computer science), Paxos (computer science), CAP theorem, Conflict-free replicated data type |
  | Cryptography (secrets over open channels, proofs) | Public-key cryptography, Cryptographic hash function, Zero-knowledge proof, Merkle tree |
  | Learning in the brain (association, prediction, codes) | Hebbian theory, Reinforcement learning, Predictive coding, Neural coding |
  | Signals (sampling, wavelets, sparse recovery) | Nyquist–Shannon sampling theorem, Wavelet, Compressed sensing, Matched filter |
  | Optimisation (descent, constraints, geometry of closest points) | Convex optimization, Gradient descent, Lagrange multiplier, Voronoi diagram |
  | Production (pull, flow, bottlenecks) | Lean manufacturing, Kanban, Theory of constraints, Toyota Production System |
  | Self-organisation (order from local rules) | Self-organization, Reaction–diffusion system, Cellular automaton, Emergence |

  The fields and the pages are my choice, to fill gaps in a library that is strong in search, optimisation, game theory, learning,
  design and numerical methods, and they are the owner's to change. In all 60 pages from fifteen fields.
- **The papers.** A paper is in the list only if its subject is the field's own idea, in the field's own terms (the origin of the idea,
  or an overview written for the field), and not that idea applied to machine learning or machine learning seen through the field; and
  only for a field where such a paper is on arXiv; at most two for a field. The test is applied to the title and the subject, not to
  how well a paper is known. The list below is fixed now. It is by title, authors and year, because I could not check an arXiv number
  from here: before any request, each is looked up, its number and title shown to the owner, and one that is not found on arXiv, or whose
  title differs from the one named, is dropped and not replaced. The owner approves the list again at that point. (The first draft
  of this list held five more papers, a control view of reinforcement learning, auctions by deep learning, two papers on backpropagation
  in the brain and an overview of gradient descent for deep learning; they fail this test and were removed after the review.)

  | Field | Candidate papers (authors, year) |
  |---|---|
  | Information | The information bottleneck method (Tishby, Pereira, Bialek, 1999) |
  | Statistical physics | Determining computational complexity from characteristic "phase transitions" (Monasson, Zecchina, Kirkpatrick, Selman, Troyansky, 1999) |
  | Inference | Variational Inference: A Review for Statisticians (Blei, Kucukelbir, McAuliffe, 2016); A Conceptual Introduction to Hamiltonian Monte Carlo (Betancourt, 2017) |
  | Networks | Emergence of scaling in random networks (Barabási, Albert, 1999); The structure and function of complex networks (Newman, 2003) |
  | Signals | Robust uncertainty principles: exact signal reconstruction from highly incomplete frequency information (Candès, Romberg, Tao, 2004) |

  That is 8 papers in five fields. Ten fields have no paper: control, ecology and evolution, economics, scheduling, distributed
  systems, cryptography, learning in the brain, optimisation, production and self-organisation, because I could not name a paper of
  the field in its own terms that is on arXiv. They are the control of stage two, and with ten of fifteen they are the larger part of it.
  arXiv holds mostly physics, mathematics and computer science, and for these fields much of what it holds about the fields' ideas is in
  machine-learning terms (the library holds about 25 papers that are); that is a limit of what arXiv holds, and it is the reason the
  list is short. Papers of the ten fields can be a later batch.
- **How the papers are kept from skewing the result.** (1) The pages and their fifteen searches are done and recorded (Increment C)
  before any paper is captured, so the pages are measured alone, as the first batch was. (2) The same fifteen sentences are run again
  after the papers, unchanged, and the Result compares the two runs sentence by sentence. (3) What is counted is kept apart by source:
  a hit for a sentence is still a page of its field among the first five; a paper of its field is counted separately and does not
  rescue a miss of the pages. (4) The effect of the papers is read as the change in the first five of each sentence: pages of its field
  that left it, papers that entered it, and the same for the ten fields without papers, whose first five should change little. (5) The
  cards of the papers are counted apart (partial cards, empty parts, marks, pieces read), because a long paper is sampled. (6) No paper is
  added after a result is seen, and no sentence is changed.
- **The fifteen sentences of Increments C and F**, fixed here before any run, one for each field, written without the name of the method
  and never changed after a result is seen. A page "of the field" is one the table lists for it, a paper "of the field" one of its row of
  the second table.

  1. Control: A quantity is measured and compared with a target, and the difference is used to adjust the input all the time, so that
     the quantity stays near the target in spite of disturbances.
  2. Information: Messages are written so that their average length is as short as possible given how often each symbol occurs, and so
     that errors added in transmission can be found and corrected.
  3. Statistical physics: Many simple units that each influence their neighbours switch together at a critical value of one setting,
     so that the whole system changes abruptly from disordered to ordered.
  4. Inference: Belief about an unknown quantity is updated by each new observation, and states that cannot be seen directly are worked
     out from the sequence of what can be seen.
  5. Ecology and evolution: Two populations, one feeding on the other, rise and fall in repeating cycles, each lagging a little behind
     the other.
  6. Networks: Most members of a large network have few links and a few have very many, yet any two members are joined by a short chain
     of links.
  7. Economics: Bidders who each know their own value for an item are asked to bid in such a way that telling the truth is the best
     strategy and the item goes to the one who values it most.
  8. Scheduling: A courier must call at every one of a set of addresses once and return to the depot by the shortest route, and the
     number of possible routes grows faster than a computer could list them.
  9. Distributed systems: Several computers that can fail or lose messages must agree on one value, so that all of those still working
     end up with the same value.
  10. Cryptography: Two parties who have never met must exchange secret messages over a channel that anyone can read, using a key that
      can be made public without revealing how to read the messages.
  11. Learning in the brain: Connections between nerve cells that are active at the same time grow stronger, so that a network of them
      comes to store the patterns it is shown.
  12. Signals: A continuous signal is recorded as a series of samples taken often enough that the original can be rebuilt exactly, and
      a signal that is mostly empty can be recovered from far fewer samples than that rate asks for.
  13. Optimisation: Find the lowest point of a function by taking repeated small steps in the direction in which it falls fastest.
  14. Production: Work is pulled through a production line only when the next step is ready for it, so that the stock waiting between
      steps stays small and the slowest step sets the pace of the whole line.
  15. Self-organisation: Simple units that follow only local rules, with no leader and no plan, produce ordered patterns over the whole
      system, such as spots and stripes.

- **Live requests.** Each page is one request to a third-party site, made by `capture-url`, which sends an honest user agent, follows
  the limits the engine sets (size, time, redirects) and is run three seconds apart, as in the first batch; sixty requests take about
  three minutes. A paper is fetched by `capture-arxiv` (its PDF and its metadata), one at a time and not faster than the engine
  allows. Nothing is sent to either site but the request for the page or the paper.
- **Model runs.** The card runs send the text of each new book, in pieces, to the models the config names on the owner's server `ned`
  over plain HTTP, and the vectors steps send the neutral descriptions of the new cards to the embedding model there, and each search
  sends its sentence. The owner is told what is sent before each and says yes. A card run can be stopped and started again
  (`cards-queue`) and takes the books of its plan only. A call whose answer is refused is asked once more with the reason, so a call
  can be made twice.
- **Time.** The first batch of 30 pages took about 16 minutes of calls for 29 cards (201 calls); 60 pages should take 30 to 40 minutes
  if the server is well, and a long paper makes more calls than a page (up to 12 pieces are read). The real figures are recorded.
- **The library is the owner's.** The new books are added to the bulk root like the others. The plan does not delete or change a book.
- Wikipedia text is licensed for reuse with attribution; arXiv papers are held under the licence each carries, which the metadata
  records; each book keeps its source address and retrieval date, and its citation line carries them.

## Completion criteria

1. Of the 60 pages, the number captured, scanned, converted and indexed is recorded, with the reason for each that was not, and none
   of the 110 existing books changed.
2. Each new book that converted has a card in the earlier form, or the Result gives the reason it has none.
3. The catalog and the vectors cover the new cards (`card-vectors` reports them as made and a second run sends nothing), with 0 stale.
4. For each of the fifteen sentences, a page of its field is among the first five books of `card-search --meaning`, or the Result says
   which sentences did not and what came instead. This is recorded before any paper is captured. The sentences are not changed after a
   result is seen, and a miss is a finding to report and not a failure of the plan.
5. The papers named, as many as are found on arXiv with the title named, are captured, converted and carded, with the same records, and
   the list that was approved is in the Result with the numbers and the papers dropped.
6. The fifteen searches run again give, for each sentence, the first five books before and after, and the Result states, by field and by
   source, the pages that left the first five, the papers that entered it, and the same for the ten fields without papers.
7. `wb run code-work check` finds no problems.

## Increments

### Increment A — Capture and process the 60 pages

**Outcome:** the pages that can be fetched and converted are books of the library, scanned, converted and indexed for text search.
**Dependencies:** none.
**Affected areas:** the library's bulk root and index root (new books only); this plan's Result. No tracked code.
**Steps:**
1. **Checkpoint, before any request.** Name to the owner the surfaces this batch uses and what has been reviewed: capture, the scan and
   the conversion (security reviews are recorded in the Results of the plans for the first slice and the scan); the card queue
   (reviewed on 2026-11-08 at the owner's request); the model call and the card prompts (the retry of a refused answer and the reader
   of the nested reply were reviewed on 2026-11-10, the second by the security reviewer at the owner's request). Ask once whether to
   run the installed security-review module on that path before the batch, and record the answer in the Result. A review runs only if the
   owner asks.
2. Take a read-only snapshot of the 110 books (one hash over the path and content of every file of each folder), outside the repository.
3. Show the owner the list as it stands and the number of requests (60, three seconds apart, to one site, so about three minutes) and
   wait for a yes. The first three requests are looked at before the other 57.
4. Run `python3 -m kb capture-url ADDRESS` for each address, one at a time, and record `filed`, `held` or `failed` and the reason.
5. Run `python3 -m kb process --book ID` for the new ids only, and read its report: scanned, converted, indexed, and the books that
   failed or were marked partial.
6. Read a passage of two of the new books with `search` and `read`, and take the snapshot again.
**Verification:** the counts and the reasons recorded; the 110 books unchanged; a search of the text finds a word of a new page.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-add-sources-from-fifteen-more-fields#A`, holding the Result.

### Increment B — Cards for the new pages

**Outcome:** each new book that converted has a card in the earlier form, or the Result gives the reason.
**Dependencies:** A.
**Affected areas:** the cards of the new books (generation 1 each) and the card runs in the index root; this plan's Result. No tracked code.
**Steps:**
1. Run `python3 -m kb cards-queue plan --book ID ...` with the ids of the new books that converted; it makes no call. Its form is the
   earlier one by default. Show the owner the number of books, the form, the models, the calls that can be counted and the estimate,
   say that the text of these pages goes to the models on `ned` in the clear and that any call can be made twice, and wait for a yes.
2. Run `python3 -m kb cards-queue run RUN`. Record the time, the cards made, the answers refused (the count of the kept files before and
   after) and, for a book that fails twice, its reason; a new attempt is the owner's decision.
3. Read two of the new cards with `card-show`. Count the cards marked partial, the parts that are empty and the marks (`card-marks`).
4. Check that the 110 books are unchanged.
**Verification:** `cards-queue status RUN`; the counts; the snapshot comparison; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`, holding the Result.

### Increment C — The catalog, the vectors and the fifteen searches (the pages alone)

**Outcome:** the search by meaning covers the new cards of the pages, and the fifteen searches are recorded, before any paper is captured.
**Dependencies:** B.
**Affected areas:** the catalog and the vectors in the index root; this plan's Result. No tracked code.
**Steps:**
1. Run `python3 -m kb card-index`. Say what is sent (the neutral fields of the new cards, three for each, to the embedding model on
   `ned`, in the clear) and wait for the owner's yes before `python3 -m kb card-vectors`; a second `card-vectors` must send nothing.
2. For each of the fifteen sentences, run `python3 -m kb card-search '<the sentence>' --meaning` (this sends the sentence to `ned`; say
   so and wait for a yes) and record the first five books (title, whether a page of the field, a page of another new field, or an
   older book) and whether a page of that field is among them. Keep the full record: it is the baseline of Increment F.
**Verification:** the counts of `card-vectors` (made, kept, stale 0), the fifteen searches recorded.
**Evidence:** the one local commit, with the trailer `...#C`, holding the Result.

### Increment D — Find and capture the papers

**Outcome:** the papers of the list that are on arXiv with the title named are books of the library, scanned, converted and indexed.
**Dependencies:** C.
**Affected areas:** the library's bulk root and index root (new books only); this plan's Result. No tracked code.
**Steps:**
1. **Checkpoint, before any request.** Name the surface that is new in this stage, the PDF of a paper (`capture-arxiv` and the
   conversion of a PDF), and what has been reviewed of it (read from the Results of the plans for the arXiv capture and the PDF
   conversion, and said as they say it). Ask once whether to run the installed security-review module on that path, and record the
   answer. A review runs only if the owner asks.
2. Look each candidate up (by its title and authors, on the public web or arXiv's own listing; this sends the titles of public papers to a
   search service and nothing else), and show the owner a table of title, arXiv number, year and field. Drop any that is not found with
   the title named. Wait for the owner's approval of the list. Take a read-only snapshot of the library's books.
3. Run `python3 -m kb capture-arxiv NUMBER` for each, one at a time, and record `filed`, `held` or `failed` and the reason; then
   `python3 -m kb process --book ID` for the new ids only, and read its report.
4. Check the snapshot again: only the new books differ.
**Verification:** the counts and the reasons recorded; the existing books unchanged; the approved list in the Result with the papers dropped.
**Evidence:** the one local commit, with the trailer `...#D`, holding the Result.

### Increment E — Cards for the papers

**Outcome:** each new paper that converted has a card in the earlier form, or the Result gives the reason.
**Dependencies:** D.
**Affected areas:** the cards of the papers (generation 1 each) and the card runs in the index root; this plan's Result. No tracked code.
**Steps:**
1. Plan the run for the papers' ids as in Increment B step 1 (no call), say what goes to `ned`, and wait for a yes.
2. Run it. Record the time, the cards made, the answers refused, the pieces read of each and the cards marked partial.
3. Count, apart from the pages, the partial cards, the empty parts and the marks (`card-marks` with `--book` for the papers).
**Verification:** `cards-queue status RUN`; the counts; the existing books unchanged; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#E`, holding the Result.

### Increment F — The vectors and the fifteen searches again

**Outcome:** the search by meaning covers the papers, and the fifteen searches are compared with those of Increment C.
**Dependencies:** E, and C for the baseline.
**Affected areas:** the catalog and the vectors in the index root; this plan's Result. No tracked code.
**Steps:**
1. Run `python3 -m kb card-index`, then, on the owner's yes (what is sent is said first), `python3 -m kb card-vectors`; a second run
   sends nothing.
2. Run the same fifteen sentences again, unchanged (on the owner's yes), and record the first five books as in Increment C.
3. Compare, sentence by sentence, with the record of Increment C, and write: for each sentence the pages of its field that left the
   first five, the papers that entered, and whether a paper of its field is among them; the totals for the five fields with papers and
   the ten without; and a reading that says what is and is not shown (a change in the ten fields without papers is the size of the
   change that is not due to a paper of their field).
**Verification:** the counts of `card-vectors` (stale 0), the second record complete, the comparison written.
**Evidence:** the one local commit, with the trailer `...#F`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changes its inputs. At the end, confirm the counts of books,
cards and vectors from the Results, and run `wb run code-work check`. No code is changed, so no test run is named. What could break
outside what is checked is the library's existing books and cards: Increments A and D compare them before and after, and the card runs
take the books of their plans only.

## Risks and sensitive actions

- **Requests to third-party sites** from the owner's machine, 60 to Wikipedia and up to 8 to arXiv, each said to the owner beforehand.
  A page can be a redirect, large or malformed, and a PDF is a harder input than a page; the engine's limits and the scan apply as to
  every capture, and Increment D asks the owner about a security review of the PDF path.
- **Text sent to the owner's server in the clear** (the card runs, the vectors and the searches). The pages and papers are public; the
  server is the owner's.
- **Skew from the papers.** Named above: stage one is recorded before any paper, the sentences are fixed, the sources are counted apart,
  and ten fields have no paper. What this cannot remove: arXiv holds little of these fields in their own terms, so only five fields have a paper;
  the Result says so and does not read the comparison as more than it shows.
- **A broad page.** A few pages (Emergence, Reinforcement learning, Statistical mechanics) are long and general; they are converted and
  carded in pieces like any other, and a long one is sampled, which the card says.
- **The new books change what a search returns.** Searches that agents run after this will find them. That is the purpose, and the
  vectors are made only for the new cards (the others are kept).
- **Disk and time.** The new books are small. The card runs' times are recorded; the queue can be stopped and started again without
  losing the cards made.
- **A wrong or missing source** is a recorded failure, not a substitution.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, one finding (major), applied:

- **R1-F1, applied (major).** The rule for choosing papers excluded applications of a field's idea to machine learning, but the list held
  papers framed that way (auctions by deep learning, backpropagation in the brain), and the later remark that several papers lean to
  machine learning did not resolve the conflict. The rule was kept and applied as written, with the test stated more plainly (the
  subject is the field's own idea in the field's own terms, and not that idea applied to machine learning or machine learning seen
  through the field): five candidates were removed (a control view of reinforcement learning, auctions by deep learning, two papers on
  backpropagation in the brain, an overview of gradient descent for deep learning). Eight papers in five fields remain, and ten fields
  have no paper and are the control of stage two. The Goal, Scope, the table, the criteria, Increment F, the risks and the deferred work
  were changed to the new numbers. The other option the reviewer offered, to permit machine-learning papers and class them apart, was
  not taken: it would put back the skew the stage-two design is meant to avoid.

A second round has not been asked for.

## Deferred work

- A second trial of cross-field search over the enlarged library, with problems whose answers lie in the new fields (a plan of its own).
- Papers for the ten fields without one, if a paper of the field in its own terms is found; and a further batch of papers.
- The sentence form of the cards for any of these books, if it is ever wanted (the option exists: `--form sentences`).

## Result

Empty until work starts.
