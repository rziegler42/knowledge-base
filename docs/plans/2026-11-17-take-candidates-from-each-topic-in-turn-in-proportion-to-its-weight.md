# Take candidates from each topic in turn, in proportion to its weight

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from a finding: the third supervised run showed that the fetches of the unattended crawl all went to one topic, and the plan `2026-11-16-build-the-safeguards-of-the-unattended-crawl` recorded the spec's order of work as not met)
Specs: docs/specs/population.md

## Goal

The spec says of the order of work: "for each run the batch is filled by round-robin over the topics in proportion to their weights, oldest `added` first within a topic, with `wander_share` of the batch taken from wandered candidates". `crawlstate.reserve` does something else: it takes the higher weight first, then the oldest, then the lower depth, then the lower id. A discovery run adds all its candidates in one second and every core topic has weight 10, so every tie falls to the id, which is the order in which discovery handled the topics. **The first topic's candidates are all taken before the second topic's**: the first six books of the crawl came from one topic ("FPGA architecture and design flow") and the queue holds 14 more of it before any other topic of the 12 queued is reached. With `filed_total` at 10, a library would be mostly one topic.

When this plan is done, `reserve` takes the next candidate from the **topic that has had the smallest share of fetches for its weight**, so that over time each topic's share of the fetches is its weight's share of the total (core 10, exploratory 5, low 1), and within a topic the oldest candidate first.

## Scope

**Changed:** `engine/kb/crawlstate.py` (the choice of the row in `reserve`, and its docstring), `engine/tests/test_crawlstate.py` (the tests of the order, and new ones), `engine/tests/test_crawlchain.py` (one test that shows the topics in turn through a run), `docs/specs/population.md` (the sentence on the order of work says what is built) and `README.md` (the known limits, if it says the order).

**Not changed:** discovery, the plan's keys, the ceilings, the per-site rules, the wandered share (below), the queue's columns.

## Non-goals

- **The wandered share (`wander_share`).** Candidates found by following citations (no topic, weight none) stay after every weighted candidate, as now. Giving them a share of each batch is a separate piece of work, and a todo item says so.
- A new plan key. The share of a topic is made from the weights it already has.
- Changing which candidates discovery adds, or how many of each topic.

## Assumptions and constraints

- **My reading of the spec's "round-robin in proportion to their weights" (a call of mine, for the owner to confirm in approving the plan):** a topic's turn comes by the ratio of **the fetches it has had to its weight**: the next candidate is taken from the topic whose `fetched / weight` is smallest, ties to the higher weight, then to the oldest candidate. A topic's fetched count is the number of its rows that have been taken at least once (`tries` above 0: kept, rejected, failed, or fetching), counted over the whole life of the queue and not per day or per run, so that the order does not start again from the first topic at each run. A topic with no queued candidate is skipped; the other rules of `reserve` (the ceilings, the site's day limit, the sites stopped for the day, a row's next try) are applied to a row **before** it is a candidate for its topic's turn.
- A candidate with no topic or no weight (a wandered one) counts as weight none and comes after all weighted rows, as now.
- One topic with weight 10 and one with 5 then get fetches in the ratio 2 to 1 over time; twelve topics of weight 10 get one in turn each.
- `reserve` already runs in one transaction; the counts are read in that transaction.
- No test uses the network, a model, the owner's library or config. Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward.

## Completion criteria

1. With candidates queued for several topics of equal weight, successive calls of `reserve` take one from each topic in turn, not all of the first topic's first; the oldest of a topic first within it.
2. With topics of weights 10 and 5, the fetches over a long run are in the ratio 2 to 1, and a topic of weight 1 gets one in 10 of a weight-10 topic's.
3. A topic with nothing eligible (all its rows waiting for a next try, at the site's limit or stopped) is skipped, and the turn goes to the next topic; a wandered candidate is taken only when no weighted row is eligible, as now.
4. The counts do not start again at each run: two runs of a batch of 3 over 12 equal topics take 6 different topics.
5. `wb run code-work check` passes; the tests of `crawlstate`, `crawlrefill`, `crawlfetch` and `crawlchain` pass.
6. The owner has read the result.

## Increments

### Increment A — The next candidate comes from the topic with the smallest share

**Outcome:** `reserve` takes candidates from the topics in turn, in proportion to their weights.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlstate.py`, `engine/tests/test_crawlstate.py`, `engine/tests/test_crawlchain.py`, `docs/specs/population.md`, `README.md`.
**Steps:**
1. Read `crawlstate.reserve` and the tests of the order (`Order`), the queue's columns (`topic`, `weight`, `tries`, `status`, `added`, `depth`), `crawlrefill` (how rows get their topic and weight) and the chain tests' queue fixtures.
2. Tests first: the cases of the criteria (equal weights in turn; 10 and 5 in the ratio 2 to 1 over 30 calls; weight 1 in one in 10; a topic with nothing eligible skipped; wandered rows last; the counts carried across runs: two runs of 3 over 12 topics; the oldest first within a topic; ties to the higher weight, then the oldest, then the lower id; a row of a site at its limit does not take its topic's turn); the existing tests of the order are changed where they pinned the old rule, and each change is said in the Result.
3. Write the change (one pass over the eligible rows with the counts of fetched rows by topic read once in the transaction); deliberate breaks; the `reviewer`'s reading; the Result; the spec sentence and the README say what is built.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlstate engine.tests.test_crawlrefill engine.tests.test_crawlfetch engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-take-candidates-from-each-topic-in-turn-in-proportion-to-its-weight#A`.

## Verification for the plan as a whole

The increment's recorded verification stands. The tests of the six R1 modules, `test_crawlfetch`, `test_crawlsteps` and `test_crawlchain` are rerun together, because `reserve` is read by all of them; `wb run code-work check` is run. The engine's whole suite is not rerun unless the owner asks. **After this plan the owner approves the crawl plan again.**

## Risks and sensitive actions

- **A change to which pages the crawl fetches first**, not to what it does with them: no new request kind, no new write. A mistake would only skew the mix of topics, which the report shows.
- The cost of the choice: one pass over the eligible queued rows (the queue is bounded at `queued_total`, 20,000) in the transaction of each `reserve`; acceptable for a few fetches a run.
- The change of the code makes the approval of the crawl plan stale; the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

The wandered share of the batch, and the choice of how many candidates discovery adds for each topic, stay for later.

## Result

### Increment A — The next candidate comes from the topic with the smallest share (verified, not committed)

- Changed `engine/kb/crawlstate.py` (`reserve`: the choice of the next row, its docstring, and `import fractions`), `engine/tests/test_crawlstate.py` (the class `Order`: one old test replaced and twelve new ones; `add` takes a `topic`), `engine/tests/test_crawlchain.py` (`add` takes `topic` and `weight`; the class `TheTopicsInTurn`), `docs/specs/population.md` (the sentence on the order of work) and `README.md` (one bullet). Verification: `test_crawlstate`, `test_crawlrefill`, `test_crawlfetch`, `test_crawlchain` and `test_crawlsteps`, OK; `wb run code-work check` and `git diff --check` clean.
- **The rule as built.** Among the queued rows that can be taken now (the site usable and under its day limit and not stopped, `next_try` reached; the ceilings `fetches_per_day`, `filed_total` and `batch` are looked at before), the next row is the one with the smallest key: for a weighted row `(0, fetches / weight, -weight, added, depth, id)`, for a wandered row (weight 0 or none) `(1, 0, 0, added, depth, id)`. `fetches` is the number of rows of the same topic and weight with `tries` above 0, over the whole life of the queue, so a run carries on where the last left off; exact fractions are used. **My reading of the spec's "round-robin in proportion to their weights" (approved with the plan):** the topic whose fetches for its weight are the fewest, ties to the higher weight.
- **What changed in the tests (said as the plan asks).** `test_higher_weight_first_then_oldest_then_lower_depth_then_the_first_found` pinned the old rule (a weight-5 group wholly before a weight-1 one) and is replaced by `test_within_a_group_oldest_first_then_lower_depth_then_the_first_found_and_a_wandered_row_last`, which keeps what is still true. New: equal topics in turn; the exact order for weights 10 and 5 (`core exploratory core core exploratory ...`: it pins fetches over weight and not the next fetch over weight); 10 to 5 gives 20 to 10 over thirty; 10 to 1 gives 10 to 1; a topic with nothing eligible is skipped; a row of a site at its cap does not take its topic's turn; the counts are kept across runs (two runs of three over twelve topics take six); rows tried and kept, rejected or failed count, rows never tried (rejected at discovery or blocked) do not; a wandered row comes last; and a chain test through two real runs.
- Breaks: 19 single mutations of the selection, one survived (`(fetches + 1) / weight`, which has the same long-run ratio and a different order), closed by the test that pins the exact order and killed.
- Review (`reviewer`, one exchange): no blocking finding. **Recorded, not changed:** (1) **a catch-up burst**: a topic that is new in the plan, or one that ran dry and is refilled, starts at none and takes every turn until its share has caught up with the topic next to it (about as many fetches as that topic has had), bounded by `fetches_per_day`, `batch`, `filed_total` and its own eligible rows; no window is added (it would need a date for each row's first try and would break the counts kept across runs); for a library of this size it is a few fetches over one to three days; (2) **a topic whose weight is changed in the plan** has two groups (a row keeps the weight it was added with), each with its own share, until the old rows are used up; low likelihood (a weight change needs a new approval), noted in the docstring; (3) a test that was too weak (the one on a queued row tried before) is made stronger and a test is added for rows never taken; (4) the cost is one grouped count and a pass over the eligible rows (at most `queued_total`, 20,000) in the transaction of each `reserve`, a few times a day.
- **After this plan the owner approves the crawl plan again** (the code fingerprint changed). Not run: the engine's whole suite.
