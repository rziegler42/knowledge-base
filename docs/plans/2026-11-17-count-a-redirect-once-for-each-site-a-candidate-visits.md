# Count a redirect once for each site a candidate visits

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from a finding: the second supervised run of the unattended crawl, and the todo item made from it)
Specs: docs/specs/population.md

## Goal

The fetcher counts the requests that a redirect leads to, to a site other than the candidate's first, in `hop:<site>`, and refuses a hop once the site's hops have reached `per_domain_per_day` (`crawlstate.charge_hop`, called from the policy hook of `crawlfetch._policy` **for every request after the first**). A normal DOI address goes `doi.org`, then to a publisher (`springer.com`), then often on inside that publisher (`www.springer.com`, `link.springer.com`): two or three requests to **one site** for **one paper**. The second supervised run showed it: hops to `springer.com` reached the limit of 3 in one run, and the next candidate was deferred with "the site it leads to is at its limit for the day". With the limit at 3 a queue of DOI addresses yields about one paper a day for each publisher, whatever the day's fetch ceiling. The rule before the plan `2026-11-17-close-the-small-gaps-found-before-the-agent-is-installed` had the same effect on `fetch:<site>`.

When this plan is done, a candidate's chain of redirects takes **one unit of `hop:<site>` for each site other than its first that it visits, once**, however many requests it makes to that site. A hostile chain is still bounded: a fetch makes at most `MAX_REDIRECTS` (5) hops, every request still goes through the blacklist, the address checks and the pacing gap of the shared client, and a site is still refused when it is stopped for the day or at its limits.

## Scope

**Changed:** `engine/kb/crawlfetch.py` (the policy hook of `_policy`), `engine/tests/test_crawlfetch.py`, `docs/specs/population.md` (the comment on `per_domain_per_day`) and `README.md` (the known limit "a site can see up to twice its daily fetch limit in requests").

**Not changed:** `crawlstate.charge_hop` and its rules, the counters, `reserve`, the shared client and its pacing, the refusal count (`note_refusal`), the plan's keys.

## Non-goals

- The refusals that a hostile redirect can add to another site (the open todo item of the earlier plan). A hop to a site that answers 403 or 429 still counts as that site's refusal.
- A change of `per_domain_per_day` or of the pacing. The owner may also raise the limit in his plan; this plan does not choose a value.
- Counting requests for any other purpose.

## Assumptions and constraints

- The hook already knows a candidate's first site and its latest site (`self.hop`), and a hook is made for each candidate (`_policy` is called once for a candidate), so a set of the sites already charged for this candidate can live in the same small state.
- A request to a site that this candidate has already been charged for, or to its first site, makes no new count but is still checked by the shared policy (the blacklist and public lists, the address checks, the pacing gap): only the daily counter is skipped.
- A site that has become **stopped for the day** between two requests of one candidate (a refusal is counted when a fetch ends, not during it) cannot happen inside one fetch; a site that was stopped before the fetch is refused at its first visit, as now.
- No test uses the network (the fake servers of the tests), a model, the owner's library or config.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. A chain `first` to `a.example` to `a.example` (two requests to one other site) charges `hop:a.example` once, and the candidate is fetched where it was deferred before (with `per_domain_per_day` of 1 or 2).
2. A chain through two other sites charges each once; a chain that leaves a site and returns to it charges it once; the candidate's first site is never charged.
3. A site at its hop limit, or at its limit of real fetches, or stopped for the day, is still refused at the **first** request to it by a candidate, with the same reasons as before; a hostile chain of five hops makes at most five requests and charges at most the sites it visits once each.
4. `wb run code-work check` passes; the tests of `crawlfetch`, `crawlstate` and `crawlchain` pass.
5. The owner has read the result.

## Increments

### Increment A — Count a hop once for each site a candidate visits

**Outcome:** a chain of redirects takes one hop unit for each site it visits.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlfetch.py`, `engine/tests/test_crawlfetch.py`, `docs/specs/population.md`, `README.md`.
**Steps:**
1. Read `crawlfetch._policy`, `crawlstate.charge_hop`, the redirect tests of `test_crawlfetch` (the class `Redirects`, including the same-site test and the public-suffix test), and `webclient`'s loop over the hops.
2. Tests first: a redirect that stays inside a site other than the first (two requests to `victim.test`, or `www.` then a bare host of it) takes one unit, and with a limit of 1 the candidate is kept; a chain through two other sites takes one unit each; a chain that returns to a site it left takes one unit for it; the first site is never charged; the refusal that follows a hop is still charged to the site that answered it; a site at its limit is refused at the first visit with the same reason, and a second candidate to a site at its hop limit is deferred as before; the existing tests of hops still pass.
3. Write the change (a set of the sites already charged for this candidate in the hook's state); deliberate breaks; the `reviewer`'s reading; the Result; the spec comment and the README limit say what is built.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_crawlstate engine.tests.test_crawlchain`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-count-a-redirect-once-for-each-site-a-candidate-visits#A`.

## Verification for the plan as a whole

The increment's recorded verification stands. Only `crawlfetch.py` changes, so the tests of the modules that read it (`test_crawlfetch`, `test_crawlchain`, `test_crawlsteps`) are the rerun named; the engine's whole suite is not rerun unless the owner asks. **After this plan the owner approves the crawl plan again** (`crawl-approve`), because the code fingerprint changed.

## Risks and sensitive actions

- **A network boundary is touched** (the accounting of the fetcher's redirect hops). A change that counted too little would let a hostile page send a candidate through the same site more often than the limit says: it is bounded by the five hops of a fetch, by the pacing gap and by the daily fetch ceiling, and the tests cover a hostile chain. The owner is asked whether to run a security review once the increment is done; none runs unless he asks.
- The change of the code makes the approval of the crawl plan stale: the runs refuse until the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

The refusals that a hostile redirect adds to another site, the memory limit of the converters, the sweep of `incoming` and the card stop file inside a pass stay on the owner's todo list.

## Result

### Increment A — Count a hop once for each site a candidate visits (verified, not committed)

- Changed `engine/kb/crawlfetch.py` (the policy hook of `_policy`: a set `counted` in `self.hop`, and the condition `site != first and site not in counted`; the docstring), `engine/tests/test_crawlfetch.py` (the class `Redirects`: helpers `chain` and `hops`, 7 new tests), `docs/specs/population.md` (the comment on `per_domain_per_day`) and `README.md` (the known limit). Verification: `test_crawlfetch`, `test_crawlstate` and `test_crawlchain`, 229 tests, OK; with `test_crawlsteps` (the plan-level rerun) 345 tests, OK; `wb run code-work check` and `git diff --check` clean. (A line "TypeError: a bytes-like object is required" printed when the three modules were run together does not appear when any one is run alone or at the committed head: it is noise of the combined run, not of this change.)
- **What it does.** Every request still goes through `base(address)` first (the blacklist and public lists, the address checks), and the pacing gap of the shared client applies to every request. After that a site other than the candidate's first takes one unit of `hop:<site>` **only the first time this candidate visits it**; the site is added to `counted` after `charge_hop` returned no refusal (a refused hop ends the fetch). `_policy()` is called once for each candidate, so `counted` starts empty for each. The refusal charge after a chain (`hop["last"]`) is unchanged: a 403 after two requests to a site is one hop and one refusal.
- Tests first (4 failed on the old rule, the others stand as controls): two requests to one other site with a limit of 1 keep the candidate (it was deferred before); a chain through two other sites takes one unit each; a chain that leaves a site and returns takes one unit for it and never charges the first site; a refusal after two requests is one hop and one refusal; a site already at its hop limit is still refused at the first visit of the next candidate; a hostile chain between two sites makes at most `MAX_REDIRECTS + 1` requests and counts each site once; a public IP address is its own site and is counted once. **A correction of mine while writing them:** a redirect to a public IP literal is allowed (not blocked), so the test says that.
- Deliberate breaks: 12 single mutations of the hook; 3 survived and stay: a no-op reset of the set, the set filled before the refusal returns (the fetch ends at the refusal), and a set that holds `None` (no address that reaches the hook has no site); each is equivalent.
- Review (`reviewer`, one exchange): no blocking finding; the rule, the bound and criteria 1 to 3 hold. **Recorded, not changed:** (1) skipping the check for a second request to a site the candidate has already visited is acceptable: a refusal is counted when a fetch ends (`outcome`), no other writer of `refusal:` exists in the engine, and the run lock allows one run; (2) a test asserts only `status != kept` for the IP-no-site case that was replaced; the counters carry the other tests; (3) no test sets a site stopped for the day and checks the first-visit refusal reason in this class (the existing tests of the refusal case and of `charge_hop` cover it); (4) the retry path of `one()` creates a new policy for each candidate; if it ever shared one, the set would be shared.
- **After this plan the owner approves the crawl plan again** (`crawl-approve`): the code fingerprint changed. Not run: the engine's whole suite.
