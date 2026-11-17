# Make a put-off redirect hop wait a day, not an hour

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from a finding: the review of the per-day tests, `engine/tests/test_crawldays.py`, found that a candidate whose redirect leads to a site that is stopped or at its limit for the day can fail for good within hours)
Specs: docs/specs/population.md

## Goal

A candidate whose first request is answered by a redirect to another site is **put off** (`deferred`) when that site is stopped for the day (it has refused `domain_refusals` times) or has reached its limit for the day (`per_domain_per_day`). Today a put-off is finished as an ordinary failed try (`crawlfetch.outcome`, the branch for `stopped` and `deferred`): it counts a try, and the row waits **1 hour, then 6, then 24** (`crawlstate.WAIT_HOURS`). With `retries` at 3 the third put-off makes the candidate `failed` for good, **about 7 hours after the first**, though the site's limit or stop ends with the day. Each of those tries also made a real request to the first site and used a unit of the day's fetches and of that site. For a resolver such as `doi.org`, whose candidates lead to a few strict publishers, an unattended crawl loses good candidates this way and spends the resolver's units on tries that cannot succeed the same day.

When this plan is done a put-off try waits **a day**, as a refusal of a site does (`crawlstate.REFUSAL_WAIT_HOURS`), so its next try falls on a later day, when the limit or the stop has gone. It still counts as a try, so a candidate whose publisher stays stopped or at its limit on three days in a row is `failed after 3 tries`, which is the plan's `retries` and not an accident of the hour waits. No schema, no new counter and no new function: `crawlstate.finish` already takes a failed try that waits a day and charges no site (`refusal=True, count=False`), and `crawlfetch` uses it for the put-off. A stop (the stop file) keeps its own waits.

## Scope

**Changed:** `engine/kb/crawlfetch.py` (`Run.outcome`: the `deferred` kind is finished as a failed try that waits a day and charges no site; `stopped` is unchanged), `engine/tests/test_crawlfetch.py` and `engine/tests/test_crawldays.py` (the tests that pin the one-hour wait and the retry on the next day), `docs/specs/population.md` (the sentence that gives the waits).

**Not changed:** `crawlstate` (its `finish` already does this), the queue's schema and format, the hop counters, which site is charged for what, the breaker (a put-off is nothing for it, as now), `classify`, and every other wait.

## Non-goals

- Giving back the fetch unit or the first site's unit of a put-off try. The request to the first site was made, so the units are true; and a day's wait keeps one candidate from spending them more than once a day.
- Waiting until the start of the next plan day. The wait is 24 hours from the try, which always falls on a later day; the exact time of day does not matter.
- A bound on put-offs apart from `retries`. A schema column for it is not worth a change of the queue's format the day before it is used unattended.
- The `stopped` kind (the stop file) and every other failed try.

## Assumptions and constraints

- `crawlstate.finish(..., refusal=True, count=False)` is a failed try that waits `REFUSAL_WAIT_HOURS` (24) and bumps no site's refusal counter; `count=False` is already used by the refusal that another site answered.
- A put-off try is counted by `reserve` (`tries + 1`) and its units are taken there. This plan changes none of that.
- No test uses the network, a real model, the owner's library or config.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. A candidate that is put off ends its try as `queued` with its try counted, its reason as before, and `next_try` 24 hours after the try; no refusal is charged to any site and the breaker's history does not change.
2. It is not taken again the same day, and is taken on the next day after its wait, and kept when the site then allows it.
3. A candidate put off on `retries` days in a row is `failed` with `failed 3 times` and the reason, not after hours.
4. A stop by the stop file keeps its waits and is not changed.
5. `wb run code-work check` passes and the tests of the modules changed pass.
6. The owner has read the result.

## Increments

### Increment A — A put-off hop waits a day

**Outcome:** a candidate that is put off is tried again on a later day, and is given up only after `retries` such days.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlfetch.py`, `engine/tests/test_crawlfetch.py`, `engine/tests/test_crawldays.py`, `docs/specs/population.md`.
**Steps:**
1. Read `crawlfetch.Run.outcome` and `classify`, `crawlstate.finish` and `_wait`, and the tests that pin the put-off: in `test_crawlfetch` (`test_a_redirect_to_a_site_at_its_daily_limit_is_deferred_with_its_own_reason`, `test_a_deferred_row_is_not_a_reason_to_end_the_batch`, the deferral at line 1505) and in `test_crawldays` (the two tests that assert `next_try` one hour on and the retry at 00:30 of the next day).
2. Tests first: a put-off row has `next_try` 24 hours after the try and its try counted; it is not reserved again before that time and is reserved after it; three put-offs on three days make it `failed` with `failed 3 times`; no `refusal:` counter and no change of the breaker's history; a stop by the stop file is finished as before (its wait is the hour wait). Change the two tests in `test_crawldays` that pinned the old waits, and say why.
3. Write the change: in `outcome`, the `deferred` kind is finished with `refusal=True, count=False`, and `stopped` as it was. Deliberate breaks (the kind that takes the new finish, the two flags, the unchanged `stopped`); the `reviewer`'s reading; the Result; the sentence of the spec that gives the waits.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_crawldays engine.tests.test_crawlstate engine.tests.test_crawlchain`; the breaks; `wb run code-work check`. A wider run is not needed: only the end of one kind of try changes, and the four modules cover its callers.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-make-a-put-off-redirect-hop-wait-a-day#A`.

## Verification for the plan as a whole

The one increment's verification stands. A read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again** (the engine code changed). The Linux box's soak test (`crawl-soak`, not on `main`) has a test of today's put-off behaviour that this change breaks on purpose; it is to be updated there, and it is told.

## Risks and sensitive actions

- **A put-off candidate is tried at most once a day instead of three times in seven hours.** The units it uses (a fetch and one of the first site's) are the same for each try, so the waste a day is lower and the chance of a later success is higher. Its total over `retries` tries is unchanged.
- **A candidate whose publisher stays stopped is now given up after three days, not after seven hours**; it stays in the queue, occupying a row, for that time. The queue's per-site cap and total cap bound this.
- **The wait is 24 hours from the try, not the start of the plan's next day**, so a candidate put off at 23:00 is next tried at 23:00 the next day.
- The change of the code makes the approval of the crawl plan stale; the runs refuse until the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

A count of put-offs apart from tries, if the owner wants the two to differ (it needs a change of the queue's format); starting the next try at the beginning of the next plan day.

## Result

### Increment A — A put-off hop waits a day (verified, not committed)

- **Changed:** `engine/kb/crawlfetch.py` (`_Run.outcome`; the plan's text says `Run.outcome`: the class is `_Run`): the `deferred` kind is finished with `refusal=True, count=False`, so the try is counted, the row waits 24 hours (`REFUSAL_WAIT_HOURS`) and no site's refusal counter is bumped; the `stopped` kind (the stop file) is a branch of its own with the old finish and the old hour wait. `engine/tests/test_crawlfetch.py` (four tests in `Redirects`: a put-off waits a day with its try counted, charges no site and leaves the breaker's history alone; a hop to a stopped site waits a day and only the site that refused is charged; a put-off row is not taken the same day and is kept when its wait is over; a candidate put off on three days in a row is `failed 3 times` and not after hours; and `StopWaits`: a stop still waits an hour) and `engine/tests/test_crawldays.py` (the put-off row's `next_try`, and two next-day expectations, now at 09:30 and not 00:30, because the wait is a day from the try). `docs/specs/population.md`: one sentence at the retry waits. Done on this machine.
- **The changes to the old tests, and why:** a put-off row's `next_try` is a day after the try (it was an hour); in the two day tests the row is not taken at 00:30 of the next day and is taken at 09:30. In the refusals test the three rows that were refused on day 1 and the put-off one are now **all due at 09:00 on day 2**, are taken in that order, and the publisher is asked four times that day (the test said once, because the put-off one used to be tried alone at 00:30); the test now serves the publisher's pages again before day 2 and says so. The reviewer read each as the new behaviour and not a hidden regression.
- **Verification.** `test_crawlfetch`, `test_crawldays`, `test_crawlstate` and `test_crawlchain`: 291 tests OK; `wb run code-work check` and `git diff --check` clean. **Nine single mutations of the branch, all killed** (each of the two flags, both removed, the kind that takes the branch, the `stopped` branch given the new finish, the two kinds merged). Not run: the rest of the engine's tests (only the end of one kind of try changed, and the four modules cover its callers).
- **Review** (`reviewer`, one exchange): no blocking finding. It read `crawlstate.finish`: nothing in `crawlguard`, `crawlreport` or `crawlstatus` can read a row finished with `refusal` as a refusal (only the `refusal:<site>` counters are read, and none is bumped); `Outcome.retry` is read nowhere; the topic turns count rows with `tries > 0`, so a put-off row adds one to its topic once, as the hour waits did; and from the code the futile requests a day fall: a candidate asks its first site at most once a day, where it asked up to three times in seven hours, and the total over `retries` tries is unchanged. **Recorded:** (1) rows put off on one day all come due at the same time of day on the next and are taken ahead of newer rows of their topic, so if the publisher is still stopped they are put off again, each costing a fetch unit and one of the first site's: bounded by the resolver's `per_domain_per_day` and `fetches_per_day`, and smaller than before; (2) the spec sentence names this plan, so the plan and the spec are committed together; (3) the soak test on the branch `crawl-soak` has a test of the old behaviour that this change breaks on purpose; it is to be updated there (the owner's other session).
- **Not done:** the owner's approval of the crawl plan again (engine code changed).
