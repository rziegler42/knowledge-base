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

### Increment A — Capture and process the 60 pages (done, 2026-11-10)

- **Checkpoint and list, both said beforehand (steps 1 and 3).** The surfaces and what had been reviewed were named to the owner: capture,
  scan and conversion (reviewed in earlier plans); the card queue (reviewed 2026-11-08 at the owner's request); the reader of the model's
  nested reply (security-reviewed on 2026-11-10 at the owner's request, two Low findings fixed); and the retry that feeds a refusal back
  to the model (the independent reviewer only; the owner had declined a security review of it). The owner was asked once whether to run
  the security review on that path before the batch; my recommendation was no, and the owner's answer was **no** (no security review was
  run for this batch). The owner then said **yes** to the 60 requests (one site, three seconds apart, about three minutes), and I
  added the safeguard of looking at the first three before the other 57.
- **Before the batch.** The store listed **110 books**. A read-only snapshot recorded, for each, one hash over the path and content of
  every file of its folder.
- **Capture (step 4).** `python3 -m kb capture-url` for each address in the order of the table, one at a time, three seconds apart, by a
  small driver script outside the repository (the addresses built from the table by script, with en dashes percent-encoded: 5 of the
  addresses, 3 with brackets), on 2026-11-10 at commit `d445735`: the first three at 19:25:17Z, which were looked at (real pages of 384 KB,
  508 KB and 1.0 MB, at the addresses asked for), the other 57 from 19:25:50Z to 19:29:03Z. **All 60 were `filed` with exit code 0 and
  nothing on stderr; none `held`, none `failed`, none redirected** (the final address was the address asked for in every case). The pages
  are 156 KB to 1.0 MB (median 383 KB, 24.5 MB in all). The new books, by field: Control: Control theory `01M73ER0W5XX18BSQEFVPSB792`; PID controller `01M73ER47KR4KDZXE2ZECTFJES`; Kalman filter `01M73ER7VF2DTN3JSBG639W0XE`; Optimal control `01M73ERZYCMVQ86408QQB33HP7`. Information: Information theory `01M73ES3ANEPR4WNNDZYXK8HX2`; Entropy (information theory) `01M73ES6P98CPMMHGHBNHPV8GY`; Huffman coding `01M73ESA04ZAEPXJ9WGC4BEDCF`; Error detection and correction `01M73ESDABJ9B0MDYSBXXPNPJ5`. Statistical physics: Ising model `01M73ESGP27VF5GV7H2FSDH7HD`; Phase transition `01M73ESM2ATH9TSB7NVC8RMGRE`; Statistical mechanics `01M73ESQHV56FQ7PDQQVCAX20K`; Renormalization group `01M73ESTWA0C4QN6PAC11EF7PT`. Inference: Bayesian inference `01M73ESY8KJV1ZZS9JJV7KMNVH`; Hidden Markov model `01M73ET1KK8F5A3ZJSWAV4RHYV`; Expectation–maximization algorithm `01M73ET4YTPWZ5MXVSZTBCZBNA`; Markov chain Monte Carlo `01M73ET89PCAQ58R2B1E6BXST8`. Ecology and evolution: Lotka–Volterra equations `01M73ETBMCEVX3SQGMHWKCZC5A`; Natural selection `01M73ETF0MYGYM7T6DQVD6QK4B`; Swarm intelligence `01M73ETJC5VK2CS2YTNYFKFDZN`; Particle swarm optimization `01M73ETNQ5N9D7B32Q8ZDC02BE`. Networks: Network science `01M73ETSB7WCHPK7QF4KN9JKWD`; Small-world network `01M73ETWTT5DVGDFJSYGRWCV21`; Scale-free network `01M73EV096QRM8DS99G0GBX98G`; PageRank `01M73EV3MFZA6TJW8N8VGMB62B`. Economics: Auction theory `01M73EV6YTN0YSDQ53HR49TJYA`; Vickrey auction `01M73EVA9D5EH3CYCJVJ9DMNM0`; Market design `01M73EVDQAT48DCQJPKXHF9GVD`; Principal–agent problem `01M73EVH1P78Y8CSKG1PBZXRTB`. Scheduling: Travelling salesman problem `01M73EVMDJ2987AQCX853PH2D3`; Knapsack problem `01M73EVQR854TECFQMCPCJ5CSP`; Assignment problem `01M73EVV4JH6ZWRZTASHVVHFVC`; Critical path method `01M73EVYEFCMZE7V3QVCKCQ11E`. Distributed systems: Consensus (computer science) `01M73EW1VTBTY7QXSZWRQYCNXJ`; Paxos (computer science) `01M73EW57G50GT5KW4QQTZZPWK`; CAP theorem `01M73EW8GQAACGFPNKDKB7SVKQ`; Conflict-free replicated data type `01M73EWBTTHMSC9GN0K52BB2PF`. Cryptography: Public-key cryptography `01M73EWFAPMMMJVEHBFPBN59XQ`; Cryptographic hash function `01M73EWJV1E971EFR2SEXBCX1B`; Zero-knowledge proof `01M73EWP6CG8J6SVDRNS4GF6GP`; Merkle tree `01M73EWSFQVBZ58HA1X8XFW94F`. Learning in the brain: Hebbian theory `01M73EWWT3ZMCTZJ6X12HGWW2V`; Reinforcement learning `01M73EX05SYVJV1WMK7AGPM86V`; Predictive coding `01M73EX3GJ418DWZ4QCR01JZY9`; Neural coding `01M73EX71EM1N3KJC5A05JMX2M`. Signals: Nyquist–Shannon sampling theorem `01M73EXAC7X1QX2NR282EGSXKR`; Wavelet `01M73EXDQJ0P7AY8W0Q3X02R3M`; Compressed sensing `01M73EXH2S6KHSA7MJYBN2HADX`; Matched filter `01M73EXMD794KBR2CXA0H5WNP0`. Optimisation: Convex optimization `01M73EXQQMTN8Q5MVRX5AD58G6`; Gradient descent `01M73EXV2PNVVJ4NNPMPWWJMMF`; Lagrange multiplier `01M73EXYE9V9J33QENXVDHKF6C`; Voronoi diagram `01M73EY1SHPAVSE1B8TNEY651M`. Production: Lean manufacturing `01M73EY53VGSA8V6E709AV1RMT`; Kanban `01M73EY8DSYSAVN3Q0FC9QH58X`; Theory of constraints `01M73EYBRB6TGJVTE7KMB0VRBS`; Toyota Production System `01M73EYF3BMWZNQZB80DJ0VNJY`. Self-organisation: Self-organization `01M73EYJKPX2M65V6X8BKB59JH`; Reaction–diffusion system `01M73EYNXWQ1FZPTWJX12FP2YS`; Cellular automaton `01M73EYS9A1DRDW49KJ9Y080VD`; Emergence `01M73EYWM6MV433MAS0QH1N26V`.
- **Process (step 5).** `python3 -m kb process --book ID` for the 60 ids only, so that nothing else was touched (19:29:33Z to 19:30:05Z,
  32 seconds). Its report holds 180 results (60 scanned, 60 converted, 60 indexed), **all `done`**, none failed.
- **Checks (step 6).** The same snapshot taken again: **110 books before, 170 now, none of the 110 changed, 60 new.** Four text searches
  ("Kalman filter prediction update", "Huffman coding prefix", "Ising model spins", "Vickrey auction truthful") returned results only from
  the new books (4, 7, 7 and 1). A passage of the Kalman filter page was read back with `read` (status `found`, the citation line with the
  address, the retrieval date and the hash, the text between the untrusted-text markers).
- **Not checked here.** Whether a page is marked partial or carries a scan caveat is not in the report of `process`; the cards, made in
  Increment B, carry it. The index was not rebuilt from the book folders for a comparison; no code or test changed, so no test was run.
- **Verification as run:** the counts above; `wb run code-work check` found no problems. (Committed as `a0943f3`.)

### Increment B — Cards for the new pages (run, 2026-11-10)

- **The plan and the owner's word.** `cards-queue plan --book ID ...` for the 60 ids (run `20261110t194623z-6efd35`; the plan made no call):
  60 books, form `earlier` (the default), models by entry `gemma`, `gptoss`, `local`, `checker`, `local`, 146 notes calls and 60 card calls
  counted. The owner was told, before the run: that the text of the 60 pages goes to the models on `ned` in the clear over plain HTTP
  (public text, nothing else), the expected 430 calls and 30 to 45 minutes, that any call can be asked twice and a book up to four times
  at one call, that 58 refused answers were kept before the run (the baseline), and that nothing would be sent for the catalog's
  vectors or the searches without a further word. The owner said **yes**.
- **The run.** `cards-queue run`, one pass, from 19:51:47Z to 20:20:59Z (about 29 minutes): **60 done, 0 failed, 0 dropped, and no book
  needed a second attempt** (`attempts` 0 for all). 411 calls were recorded on the cards: 146 notes, 60 card, 153 check and 52 second
  round (6.85 a card; the first batch of 30 pages made 6.9). The queue rebuilt the catalog: 170 books, 169 versions with a card.
- **The retry was used 6 times, each in a different book, and each time the second asking was accepted.** The kept refused answers rose
  from 58 to 64. The six: a notes call with more than 6 points; a notes call with points and quotes of unequal length; a card call with
  a topic over 60 characters; a card call with a support `2.3 inferred`; and the second round twice with a topic over 60 characters. No
  book failed, so no second asking was refused. **None of the six is a list and its support list of different lengths**, the fault that
  made all 9 refusals kept in the earlier-form run of the first batch of 30 pages (before the support was written with its item); the
  shape no longer allows it. The books differ, the numbers are small, and this shows consistency with that change and not proof of its effect.
  Observation, not acted on: 3 of the 6 are a topic over the limit of 60 characters.
- **The cards** (60, all in the earlier form, all generation 1; counted apart as the plan says; the 29 earlier-form cards of the first
  batch are given for comparison, different pages): **1 partial** (Kanban: only 2 key ideas were supported; 7 of 29 in the first batch);
  **5 cards with an empty part**, each the limit (Statistical mechanics, Hidden Markov model, Critical path method, Public-key
  cryptography, Wavelet), no other part empty (5 of 29 had an empty part); key ideas 5.4 a card on average and topics 8.2; 1 to 5 pieces
  read, so none was sampled. Marks (`card-marks` on the 60): topics 404 `stated` and 90 `inferred` (18 percent), key ideas 275 and 49
  (15), caveats 12 and 114 (90), limits 2 and 53 (96); in all 693 `stated` and 306 `inferred` (31 percent; 31 percent in the first
  batch, 141 of 455). Two cards were read with `card-show` (Kalman filter, a clean card; Kanban, the partial one) and read sensibly.
- **The rest of the library.** The snapshot compared again: **110 books before, 170 now, none of the 110 changed, 60 new.**
- **Not done, by design.** `card-index` was run by the queue only; no `card-vectors` and no search by meaning (Increment C, each on the
  owner's word). The 60 cards have no vectors yet, so they are not found by the search by meaning until C.
- **Verification as run:** `cards-queue status` before and the run's report after (counts above); the kept-file counts (58, 64); the
  snapshot comparison; `card-marks` on the 60; `card-show` of two; `wb run code-work check` after this entry. No tracked code changed.
  (Committed as `035c69e`.)

### Increment C — The catalog, the vectors and the fifteen searches, the pages alone (run, 2026-11-10)

- **Catalog and vectors (step 1).** `python3 -m kb card-index`: 170 books, 169 versions with a card, 0 failed. The vectors before, read
  without sending anything (`vectors.coverage`): 108 cards searched, 0 stale, **60 without a vector**, the new cards. The owner was told
  what `card-vectors` would send (the problem, approach and provides fields of the 60 cards, up to 180 short texts of about 120
  characters, about 20 KB, to the embedding model on `ned` in the clear over plain HTTP) and said **yes**. `python3 -m kb card-vectors`
  (6 seconds, 20:24:41Z): 169 cards, 1 with no model fields, 0 left out, 500 vectors, **320 kept, 180 made, 180 texts sent**, model
  `qwen3-embedding:4b`, dimension 2560, nothing replaced. A second `card-vectors` made 0, kept 500 and sent 0 texts. Coverage after: 168
  cards searched, **0 stale, 0 without a vector**.
- **The fifteen searches (step 2).** The owner was told what would be sent (the 15 sentences of this plan, parsed from its text by script
  and not retyped, 2,417 characters in all, 110 to 214 characters each, one at a time to the embedding model on `ned` in the clear) and
  said **yes**. `python3 -m kb card-search '<sentence>' --meaning` for each, on 2026-11-10 at 20:26Z at commit `035c69e`, by a small
  driver outside the repository. The first run of the driver stopped after the first search because of a mistake in the driver (it read a
  `title` that a result does not carry), so **sentence 1 was sent twice, 16 sends in all**; the driver was fixed and all 15 were run again.
  Every search saw 168 cards, 0 stale, 0 without a vector. The record of the first five books of each is below (own = a page the table
  lists for the sentence's field; new = a page of another new field, named; older = a book the library already held; the score is the
  cosine); the file of the record has SHA-256 `8514f67dde492a4eebba78fc394a73bb6b9e1fc0d195b03ce80af9d42bc3f59d`.

  1. Control: Control theory (own, 0.686); PID controller (own, 0.631); Ant colony optimization algorithms (older, 0.423); Kanban (new: Production, 0.407); Theory of constraints (new: Production, 0.391).
  2. Information: Error detection and correction (own, 0.706); Huffman coding (own, 0.596); Information theory (own, 0.590); Entropy (information theory) (own, 0.484); Merkle tree (new: Cryptography, 0.425).
  3. Statistical physics: Self-organization (new: Self-organisation, 0.574); Cellular automaton (new: Self-organisation, 0.551); Stigmergy (older, 0.535); Ising model (own, 0.528); Swarm intelligence (new: Ecology and evolution, 0.504).
  4. Inference: Bayesian inference (own, 0.677); Kalman filter (new: Control, 0.632); Hidden Markov model (own, 0.594); Expectation–maximization algorithm (own, 0.509); Sequential analysis (older, 0.437).
  5. Ecology and evolution: Lotka–Volterra equations (own, 0.672); Evolutionary game theory (older, 0.459); Optimal foraging theory (older, 0.447); Marginal value theorem (older, 0.433); Swarm intelligence (own, 0.413).
  6. Networks: Small-world network (own, 0.597); Scale-free network (own, 0.551); Network science (own, 0.479); Percolation theory (older, 0.473); PageRank (own, 0.437).
  7. Economics: Vickrey auction (own, 0.757); Auction theory (own, 0.595); Mechanism design (older, 0.581); Market design (own, 0.545); Principal–agent problem (own, 0.492).
  8. Scheduling: Travelling salesman problem (own, 0.686); Knapsack problem (own, 0.526); Ant colony optimization algorithms (older, 0.520); Dynamic programming (older, 0.513); Dijkstra's algorithm (older, 0.452).
  9. Distributed systems: Paxos (computer science) (own, 0.702); Consensus (computer science) (own, 0.675); CAP theorem (own, 0.560); Stigmergy (older, 0.529); Conflict-free replicated data type (own, 0.518).
  10. Cryptography: Public-key cryptography (own, 0.654); Zero-knowledge proof (own, 0.560); Merkle tree (own, 0.464); Information theory (new: Information, 0.452); Paxos (computer science) (new: Distributed systems, 0.448).
  11. Learning in the brain: Hebbian theory (own, 0.642); Neural coding (own, 0.497); Artificial immune system (older, 0.462); Predictive coding (own, 0.455); Neocognitron (older, 0.446).
  12. Signals: Compressed sensing (own, 0.683); Nyquist–Shannon sampling theorem (own, 0.556); Wavelet (own, 0.469); Fast Fourier transform (older, 0.451); Matched filter (own, 0.423).
  13. Optimisation: Gradient descent (own, 0.646); Particle swarm optimization (new: Ecology and evolution, 0.453); Simulated annealing (older, 0.440); Newton's method (older, 0.432); Ant colony optimization algorithms (older, 0.426).
  14. Production: Kanban (own, 0.649); Theory of constraints (own, 0.543); Lean manufacturing (own, 0.521); Toyota Production System (own, 0.513); Critical path method (new: Scheduling, 0.433).
  15. Self-organisation: Self-organization (own, 0.651); Stigmergy (older, 0.646); Swarm intelligence (new: Ecology and evolution, 0.642); Cellular automaton (own, 0.623); Reaction–diffusion system (own, 0.547).

- **Reading.** **A page of the sentence's own field is among the first five for 15 of 15 sentences, and first for 14.** The exception is
  the statistical physics sentence (3), whose own page, the Ising model, is fourth, behind Self-organization, Cellular automaton and
  Stigmergy; the sentence describes many simple units that switch together at a critical value, and those are neighbours of that idea in
  another field, not misses of the library. Of the 75 places, 44 are pages of the sentence's own field, 12 are pages of another new field and
  19 are books the library already held. The places held by other fields are the cross-field result the library is for: the control
  sentence finds Kanban and the Theory of constraints (feedback on a flow) and Ant colony optimization; the information sentence finds
  the Merkle tree; the inference sentence finds the Kalman filter and Sequential analysis; the ecology sentence finds Evolutionary game
  theory, Optimal foraging theory and the Marginal value theorem; the scheduling sentence finds Ant colony optimization, Dynamic
  programming and Dijkstra's algorithm; the distributed systems sentence finds Stigmergy; the cryptography sentence finds Information theory
  and Paxos. Scores of the first own-field page run from 0.528 (Ising model) to 0.757 (Vickrey auction).
- **Limits.** I wrote each sentence about pages that I put in the library, so the hits show that the new pages are found by a
  description of what they are about; they do not show that a hard transfer, a problem stated in one field whose answer lies in another,
  would be found (the same limit as the first batch). One run of each sentence, the scores of one embedding model, and no test of
  chance. This is the baseline of Increment F: it is recorded before any paper is captured and is not changed.
- **Verification as run:** the counts of `card-index` and `card-vectors` above (made 180, kept 320 then 500, second run 0 sent, stale 0);
  the fifteen searches recorded; `wb run code-work check` after this entry. No tracked code changed.
  (Committed as `833842f`.)

### Increment D — The papers (run, 2026-11-10)

- **Checkpoint (step 1).** Before any request the owner was told what the Results of the earlier plans say of the PDF path: the first-slice
  plan's security review (the sandbox held; one High in the network fetchers, the private-address guard, fixed; a hostile arXiv answer could
  claim a DOI as an identity key, fixed), the scan-hardening and first-walk-through reviews (one High, a large object stream posing as an
  image, fixed), the scan-deferred-items review (no way found to hide content from a strict zlib reader; two Low, one fixed, one waiting
  for the owner), and nine real arXiv papers measured for false alarms; and their stated limits (no real PDF reader, so claims about
  lenient decoders are models). The recommendation was not to review again, since no code changes here. The owner answered
  **"No security review"**.
- **The lookup (step 2).** Seven candidates were looked up by title and authors with a web search (only public titles were sent). Six were
  found on arXiv with the title named; **the Monasson et al. paper (statistical physics) has no arXiv preprint of that title** (only the
  Nature version; the nearest arXiv item is a different, later review) and was **dropped, not replaced**. Statistical physics joins the
  ten fields without a paper: **four fields have papers (Information, Inference, Networks, Signals), eleven do not.** The Newman number was
  not confirmed on arXiv's own page by the search; the owner approved the list of six on the condition that its title be checked at
  capture. The owner said **yes**.
- **The capture (step 3).** `capture-arxiv` for each, one at a time with a pause: all six `filed` (none `held`, none `failed`). The
  title and authors stored in arXiv's metadata match the titles named for all six, Newman's included, so none was dropped.
  The snapshot of the library's books was taken before (170 books).

  | Field | Paper (arXiv number) | Book id | PDF bytes | Text chars | Scan caveats |
  |---|---|---|---|---|---|
  | Information | The information bottleneck method (physics/0004057) | `01M73JQC5FMY1JBJEWW61V406M` | 136,267 | 26,533 | none |
  | Inference | Variational Inference: A Review for Statisticians (1601.00670) | `01M73JQHVAQZ0SMY0VM273CGNS` | 1,822,810 | 116,786 | `javascript` (count 1): "The PDF contains scripts." |
  | Inference | A Conceptual Introduction to Hamiltonian Monte Carlo (1701.02434) | `01M73JQQV5TA621H5KTWTC1VB9` | 1,673,324 | 129,241 | `large_image_streams` (count 2) |
  | Networks | Emergence of scaling in random networks (cond-mat/9910332) | `01M73JQW939GCQ1N7SHXSRZ401` | 211,825 | 19,805 | none |
  | Networks | The structure and function of complex networks (cond-mat/0303516) | `01M73JR134RB5TFD5D4DJ3EHN5` | 1,242,567 | 309,195 | `scan_incomplete` (count 1) |
  | Signals | Robust uncertainty principles (math/0409186) | `01M73JR5VSPN9VZ9KWT5WRK605` | 446,499 | 86,092 | none |

- **The conversion.** `process --book` for the six new ids: scanned, converted and indexed, **18 of 18 stages `done`**, 2 seconds
  (20:35:39Z). Text by `pdftotext`, in the sandbox.
- **The caveats, as they stand.** Three of six papers carry one; they are kept on the books and will show on the cards. Not investigated
  further: the `javascript` caveat of the Blei paper (the file's catalog has an `/OpenAction` that points at object 98, which I did not
  resolve, and the word `/JavaScript` is not in the plain bytes, so it may be inside a compressed object stream); the earlier plans
  measured false alarms of this kind on figure-heavy papers. No viewer opened any PDF. This is an observation for the owner, not a finding.
- **The rest of the library.** The snapshot compared again: **170 books before, 176 now, none of the 170 changed, 6 new.**
- **Not done, by design.** No card, vector or search yet (E and F). Nothing but the requests to the search service and to arXiv left
  this machine; no paper text has gone to `ned`.
- **Verification as run:** the lookup table and the stored metadata compared; the `capture-arxiv` statuses; the `process` report (18 of 18
  `done`); the snapshot comparison; the scan files read; `wb run code-work check` after this entry. No tracked code changed.
  (Committed as `c3351be`.)

### Increment E — Cards for the papers (run, 2026-11-10)

- **The plan and the owner's word.** `cards-queue plan --book ID ...` for the six ids (run `20261110t203740z-231385`; no call): 6 books,
  form `earlier`, the same five model steps as for the pages, 33 notes calls and 6 card calls counted. The owner was told, before the run,
  that the text of the six papers (about 790,000 characters, in pieces) goes to the models on `ned` in the clear over plain HTTP (public
  arXiv papers), the expected 80 to 100 calls and 10 to 15 minutes, that a long paper is sampled (up to 12 pieces), that any call can be
  asked twice, that 64 refused answers were kept before (the baseline), and that no vector or search would run before F. The owner said
  **yes**.
- **The run.** One pass, 20:37:52Z to 20:42:51Z (**about 5 minutes**, under the 10 to 15 expected): **6 done, 0 failed, 0 dropped, no
  book needed a second attempt.** 62 calls were recorded on the cards: 33 notes, 6 card, 17 check and 6 second round (10.3 a card; the
  pages made 6.85). The queue rebuilt the catalog: 176 books, 175 versions with a card.
- **The retry was used once**: a check call of the Blei paper, whose answer had `verdicts` longer than 16 characters; the second asking was
  accepted. Kept refused answers: 64 before, 65 after.
- **The cards** (6, earlier form, generation 1; counted apart from the pages' 60): pieces read 2, 6, 7, 1, 12 and 5 (information
  bottleneck, variational inference, Hamiltonian Monte Carlo, scaling, Newman, Candès). **1 partial: Newman, 12 of 17 pieces read, evenly
  spaced, so the card may miss parts** (the only sampled paper; the 60 pages had none). **No empty part** in any of the six (5 of 60
  pages had one). Key ideas 3, 8, 7, 3, 5 and 4; topics 8, 11, 17, 8, 16 and 6. Marks (`card-marks --book` for the six): topics 66 `stated`
  and 0 `inferred`, key ideas 30 and 0, caveats 3 and 6, limits 0 and 6; in all **99 `stated` and 12 `inferred` (11 percent; the pages
  had 31 percent)**. Every limit is `inferred`, as for the pages. Two cards were read with `card-show` (Newman, the partial one; Candès,
  a clean one) and read sensibly; both limits are marked `inferred`.
- **The scan finding on the cards.** The Blei card shows `scan finding: javascript (found 1 times): The PDF contains scripts.`; the
  card of a paper carries what the scan found, as designed. The alarm itself was still not investigated.
- **The rest of the library.** The snapshot taken at the start of the run was compared after it: of 176 books exactly six changed, **and
  they are exactly the six papers** (checked against their ids): each gained its card. The other 170 are unchanged.
- **Not done, by design.** No vector and no search (F). Only the text of the six papers went to `ned`.
- **Reading, with its limits.** The papers' cards are fewer (6) and from two long-text kinds of source; the lower share of `inferred`
  items (11 against 31 percent) and the absence of empty parts are a difference of six cards from sixty and are not a finding. The
  calls a card, 10.3 against 6.85, follow the length of a paper.
- **Verification as run:** `cards-queue plan` before; the run's report (counts above); the kept-file counts (64, 65); `card-marks` on
  the six; `card-show` of two; the snapshot comparison with the changed ids checked; `wb run code-work check` after this entry. No
  tracked code changed.
