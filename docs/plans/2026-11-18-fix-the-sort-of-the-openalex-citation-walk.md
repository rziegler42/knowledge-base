# Fix the sort of the OpenAlex citation walk, which OpenAlex rejects

Status: Proposed
Created: 2026-11-18
Candidate: none (a correction that follows from a finding: on the first day with the owner's key the walk's last request was answered with HTTP 400, and the cause was read from the real answer)
Specs: docs/specs/population.md

## Goal

The citation walk (`srcopenalex.wander`) makes two to five requests for each kept work: the work itself (for its references), none to three batches of those references (none when it has no usable reference, one for each 100 of the first 300), and last the works that cite it. The last asks `sort=-cited_by_count`. OpenAlex now answers that with **HTTP 400, "_cited_by_count is not a valid field"**, so no walk has ever completed in the live crawl (no work is marked walked), the first kept work's walk ends in a refusal, and the refusal turns OpenAlex off for the rest of the UTC day.

Read on 2026-11-18, each request asked once of the real OpenAlex without a key, by a script that prints only the status and the counts (Python 3.15, at commit `6cbabb3` of `main`; the requests were built by the module's own address builder `srcopenalex._url`, for the work `W2741809807`):

| Request | Answer |
|---|---|
| the work, `select=id,referenced_works` | 200 |
| a batch of 20 of its references, `filter=openalex:...\|...,open_access.is_oa:true` | 200, 14 results |
| who cites it, `sort=-cited_by_count` (as the code writes it today) | **400**, "_cited_by_count is not a valid field" |
| who cites it, `sort=cited_by_count:desc` | 200, 15 results, the most cited first |

The probe built that last request with the colon left as it is (the address builder's `safe` characters for the `sort` value were `:`), so the 200 above is for the address `...&sort=cited_by_count:desc&...` on the wire. When this plan is done the request for the works that cite a work is written that way, and a walk against a server that refuses the old form completes. The other requests are not changed.

## Scope

**Changed:**
- `engine/kb/srcopenalex.py`: the one `sort` parameter of the request for the works that cite a kept work, that is its value and the third element of its tuple (the characters left unencoded), which becomes `":"` so that the colon is sent as it is, as in the probe; `_url` itself is not changed. Also the sentence of the `wander` docstring that counts the requests (three, and more over 100 references), which becomes two to five.
- `engine/tests/test_srcopenalex.py`: the test that pins the old value is changed to the new one, and a test is added in which the fake server answers 400 to the old form, as the real one does.

**Not changed:** the other two requests of the walk, the ranking of what comes back (`_ranked` sorts by the count locally), the search, discovery, the plan file, the spec (it does not name the sort), and every other module.

## Non-goals

- A check against the live API in a test: no test uses the network.
- A general validator of OpenAlex's parameters, or a change of how a refusal of the walk is handled (a refusal of the walk still turns OpenAlex off for the day, as every refusal of a source does; the walk comes after the topic queries, so the day's topic queries are not lost).
- Using the key to look at an error body: the web client keeps no body for a status other than 200, and the cause was found with a request made without the key.

## Assumptions and constraints

- The form `field:desc` is what OpenAlex accepts on 2026-11-18 (one answer each, recorded above); no documentation page was fetched, so its text and hash are not recorded. If OpenAlex changes the form again the walk's request for citing works is refused again, and the log line says `status 400` (the reason holds the status and no server text).
- The ranking inside the module does not depend on the order in which OpenAlex returns the works, because `_ranked` orders them by count and id; the sort decides which `per_page` works come back, so the strongest are among them.
- No test uses the network, a real key or the owner's library or config.
- The change is engine code, so it changes the fingerprint of the approved crawl plan. The owner approves the crawl plan again, which is the owner's act.

## Completion criteria

1. The address of the request for the works that cite a kept work holds the text `&sort=cited_by_count:desc&` as it stands on the wire (a test asserts the raw address, not only the decoded parameters, which cannot tell a colon from `%3A`) and no `-cited_by_count`.
2. The parameters of the other requests of the walk (the work, a batch of references) are pinned by tests and are unchanged.
3. A walk against a fake server that answers 400 to the old sort and 200 to the new one completes and returns its candidates; against the old code the same test fails.
4. `wb run code-work check` passes and the tests of the modules changed pass.
5. The owner has read the Result, and after the owner approves the crawl plan again the first walk is looked at in the log (the walked counters appear, and OpenAlex is not turned off after its topic queries).

## Increments

### Increment A — Write the sort of the citation request in the form OpenAlex takes

**Outcome:** the walk's request for the works that cite a work (its last) is answered 200 and the walk completes.
**Dependencies:** none.
**Affected areas:** `engine/kb/srcopenalex.py`, `engine/tests/test_srcopenalex.py`.
**Steps:**
1. Read `srcopenalex.wander` and `_url`, and the tests of the walk (the test that pins `sort`, the router that fakes the server, and the one that makes a request refuse).
2. Tests first, seen failing: the pinned parameters of the request for the works that cite a work become `sort: cited_by_count:desc`; a new test makes the fake server answer 400 to a request whose `sort` is `-cited_by_count` (as the real one does) and 200 to the other, and asserts that the walk completes with its candidates and asks nothing after a refusal as before; a test asserts the raw address of the request for citing works (the text `&sort=cited_by_count:desc&`); the full parameter sets of the work request and of the batch request are pinned.
3. Write the change: the one parameter and its safe characters, and the count in the docstring. Deliberate single changes (the old form back, the sort dropped, `asc` for `desc`, the colon percent-encoded by leaving the safe characters empty, a different field), each to be caught; the `reviewer`; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_srcopenalex engine.tests.test_discover engine.tests.test_crawlrefill`; the deliberate changes; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-18-fix-the-sort-of-the-openalex-citation-walk#A`.

## Verification for the plan as a whole

The one increment's verification stands. A read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again** (the engine code changed), and the first walk of OpenAlex is looked at in the log.

## Risks and sensitive actions

- **A change of engine code voids the approval of the crawl plan.** Runs refuse until the owner approves again, which is the owner's act, at a time the owner chooses.
- **A walk that works adds rows.** For each kept work up to `wander_per_work` (5) citing and cited works join the queue, up to `wander_share` (0.2) of a refill, one level deeper each time (to depth 2). The queue caps (`queued_total`, `queued_per_domain`) and the daily OpenAlex budget bound this. OpenAlex's budget is spent faster, two to five requests for each kept work walked (at most 5 with 3 batches for over 200 references, and 2 when it has none).
- **The form can change again.** Then the walk is refused with `status 400` in the log, as today, and nothing else is lost.

## Review record

Reviewer: `ask-codex` (model `gpt-5.6-terra`), through `review-engine`, 2 rounds of a bound of 3; the second round converged with no meaningful finding.

- Round 1, two major findings, both applied after reading the code: (R1-F1) `_url` percent-encodes a value unless its tuple lists safe characters, so the plan now puts the colon in the tuple's safe characters and asserts the raw address; (R1-F2) the walk makes two to five requests for each work, not three, so the plan and the docstring say so.
- Round 2, one minor finding applied: the citing request is named by what it asks, not as the third.
- Rejected: none. Left for the owner: nothing from the review.

## Deferred work

- A refusal of the walk could end the walk only and not the day of OpenAlex's search; today every refusal of a source is for the day.
- A test against a recorded real answer, if a fixture of one is ever wanted.

## Result

Empty until work starts.
