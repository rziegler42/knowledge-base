# Fix the arXiv queries of the unattended crawl and let OpenAlex use the owner's key

Status: Proposed
Created: 2026-11-18
Candidate: none (corrections that follow from a finding: on the first full day arXiv search found nothing in about 190 requests, and OpenAlex's keyless daily budget was spent by the first burst of each UTC day)
Specs: docs/specs/population.md

## Goal

Discovery's two scholarly sources limit what the crawl can find, and each for a cause that is now known.

**arXiv found nothing.** From 2026-11-17 to 2026-11-18 the arXiv source made about 190 requests (12 in the first burst, then 50 in each of seven runs, three seconds apart) and every answer had no candidate. `srcarxiv.search` turns a query into `all:w1 AND all:w2 AND ...` for up to 12 words, so every word, "and", "of" and "textbooks" included, must match. The queries are 6 to 10 word phrases from the owner's topics. Measured on 2026-11-18 against `export.arxiv.org` with ten real topic phrases (one request each, 3.5 seconds apart): all words gave no entry for all ten; the first 3 words that are not stop words gave 10 entries for nine of the ten; the first 4 gave 10 entries for six, 2 or 3 for three, and none for one; the first 5 gave entries for six of ten (10 for five of them, 8 for one). The phrase that gave nothing at any length ("comparative analysis of ngspice and LTspice for circuit simulation") names two niche tools.

**OpenAlex answers 429 and the engine gives up for the day.** OpenAlex's pages (read 2026-11-18) give a keyless daily budget (the engine's source says $0.10, about 100 searches), 10 times that for a free key ($1 a day), and a reset at midnight UTC. Its errors page lists the `reason` of a 429: `daily_budget` (today's budget is spent), `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search` (per-second limits that cost nothing), and `first_dollar` (a new account spending its first $1 faster than the pace of $0.10 every 5 minutes); and it says that some 429s, such as keyless traffic while search is under heavy load or an account they have throttled, carry no reason, and that the answer is to wait the `Retry-After` seconds and retry. The engine turns OpenAlex off for the UTC day on any 429, so each day buys about one burst (160 candidates on 2026-11-17, 74 on 2026-11-18). **The body of the 429 that ended the burst of 2026-11-18 (01:13Z, on the second request of a new UTC day, after 12 requests the day before) was not kept, so it is not known whether that day's budget was spent or the answer was a 429 with no reason; the log says only "status 429".** The second fits a 429 under load better than a spent budget. Increment B therefore reads the headers of a 429 and writes their numbers to the log, so the next 429 says which it is. (Found on 2026-11-18 when Increment B was begun: the web client returns no body for a status other than 200, so OpenAlex's `reason` in the body cannot be read without changing the client. The client already passes `Retry-After` and `X-RateLimit-Remaining` through, and the classification uses them. The owner chose this on 2026-11-18, and the plan was changed and approved again.) The owner has a free key in the key file `openalex.key` of the config folder (mode 600; this plan reads no key and holds none).

When this plan is done: an arXiv query asks for its first three words that are not stop words, so most queries find papers; OpenAlex requests carry the key when the crawl plan says `openalex_key = on`, with the secret kept out of every log line and event; and a 429 that shows budget left (its `X-RateLimit-Remaining` header is a number above zero) stops OpenAlex for the rest of that refill only, not for the day. The shipped default is `openalex_key = off`; the owner turns it on in the crawl plan file and approves again.

Provenance of the facts above, retrieved with `curl` on 2026-11-18 (status 200; sha256 of the bytes served): `https://help.openalex.org/api/authentication/` 2e16efca000c8e7f1b60b687cf58e3d9d1f9408f214911d924705ec296dc1f8f (key from the account's API key settings, sent as `?api_key=` or as `Authorization: Bearer`, which "work identically"; a free key gives 10 times the keyless budget; the `reason` values `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search` and `daily_budget`; the new-account pace; per-second limits 10 without a key and 30 with one; the page does not mention `mailto`) and `https://help.openalex.org/api/errors/` 13cdb11199267e6e6607645eb49659a1bea1bf95090d11998e156d33f1e7f4e2 (the table of reasons, including `first_dollar`, and the 429s that carry no reason). The reason names and the new-account text were found in those bytes by a text search; no response from the API was fetched (the budget endpoint needs a key), so no real answer fixture exists yet: the tests write their own, from the table, and the owner's trial records a real one. The arXiv measurement used the API's own answers (a script that prints counts only, run on 2026-11-18). The costs per call are on OpenAlex's pricing page, which was not read.

## Scope

**Changed:**
- `engine/kb/srcarxiv.py` and its tests: the words of a query (stop words dropped, at most three kept).
- `engine/kb/srcopenalex.py` and its tests: a 429 is classified by its `X-RateLimit-Remaining` header: a plain number above zero is a refusal for this refill only, and anything else (zero, absent, not a plain number) is a refusal for the day as now; the numbers of `X-RateLimit-Remaining` and `Retry-After` are written to the log.
- `engine/kb/discover.py`, `engine/kb/crawlplan.py`, `engine/kb/crawlrefill.py`, `engine/kb/crawlapprove.py` and their tests: the plan value `openalex_key`, a keyed `get` for OpenAlex alone, the reading of the key file, the secret given to the log, a refusal that lasts for one refill, and the preview of `crawl-approve`.
- `docs/specs/population.md`: the sentences of the sources paragraph and the plan's example.

**Not changed:** the queue, the judgement, the web client (`get` already sends a credential over https to one host with no redirect), Wikipedia, DuckDuckGo, and every other step.

## Non-goals

- Searching arXiv with phrases, `OR`, other fields or a different API; the first version drops stop words and caps the words.
- Retrying a request after a 429, or waiting out a `Retry-After`: a refusal ends the source's asks for the refill.
- Reading OpenAlex's `/rate-limit` endpoint or its budget headers to plan the day; the log may say nothing of them.
- Other OpenAlex endpoints or paying for more budget; the key is a free account's.
- Reading the key from an environment variable, or any place but the owner's key file.
- A judgement on OpenAlex's terms; the owner's account and key are the owner's.

## Assumptions and constraints

- The key file is `openalex.key` in the owner's config folder, a regular file of the owner with mode 600, one printable line, read by the same checks as the URLhaus key (`urlhaus.read_key`). A test uses a made-up key in a temporary folder.
- The free account has no card and no prepaid balance, so a key can spend only the free daily budget (to be confirmed by the owner before the key is turned on).
- No test uses the network, a real key, a real model, or the owner's library or config.
- A byte of engine code changes the fingerprint of the approved crawl plan; the owner approves again when the owner chooses to stop the loop for it.
- The headers of a 429 are data from outside: only `X-RateLimit-Remaining` and `Retry-After` are read, each only as a plain number (digits with at most one point, at most 20 characters), and nothing else of a header or of a body is kept or logged. The web client keeps no body for a status other than 200 and is not changed.
- No real 429 answer from the API has been seen. OpenAlex's help page says that `X-RateLimit-Remaining` is what is left of the day's budget and is sent "on every response"; if a 429 carries no such header, the behaviour is today's (a refusal for the day).
- Nothing tracked points to anything untracked: the plan names the key file by its name in the config folder, as the URLhaus key is named.

## Completion criteria

1. An arXiv query is cut into its letters and digits, the words of a fixed stop list are dropped, and at most the first three of the rest are asked as `all:w1 AND all:w2 AND all:w3`; a query of nothing but stop words keeps its first word; every other rule of the module is as before.
2. `openalex_key = on` makes every OpenAlex request carry the key in `Authorization: Bearer` over https to `api.openalex.org` with no redirect; no other source's request carries it; the key is in the log's secrets before the first request and is in no log line, event, reason, counter or status.
3. A key file that is missing, not mode 600, not the owner's, a link or malformed turns OpenAlex off for the day with a fixed reason that holds none of the file's text, with no request made and no fallback to the keyless request.
4. A 429 is classified by its `X-RateLimit-Remaining` header, and nothing else decides. **For this refill only:** the header is a plain number above zero (`0.07`, `12`, `3.5`): budget is left, so the 429 is a pace or a load answer. **For the UTC day (fail closed):** the header is zero (`0`, `0.0`, `0.000`), absent, empty, negative, not a plain number, over 20 characters, or given twice with different values. A refusal for the refill ends OpenAlex's asks for it, does not turn the source off for the day, and is logged with the plain numbers of `X-RateLimit-Remaining` and `Retry-After` (or `none` for one that is absent or not a plain number) and no other text; the next run asks again, so at most one request a run is spent on it. A status other than 429 is as before.
5. `crawl-approve`'s preview says when the OpenAlex key is on and which file it comes from; the shipped default plan has `openalex_key` off.
6. `wb run code-work check` passes and the tests of every module changed pass.
7. The owner has read the Result, and the owner's trial (below) has been run once, or the owner has decided not to run it.

## Increments

### Increment A — Ask arXiv for three words, not all of them

**Outcome:** an arXiv search with a phrase from the owner's topics finds papers.
**Dependencies:** none.
**Affected areas:** `engine/kb/srcarxiv.py`, `engine/tests/test_srcarxiv.py`, `docs/specs/population.md` (the arXiv sentence).
**Steps:**
1. Read `srcarxiv.search`, `_text`, `_WORDS` and `MAX_WORDS`, and the nearest tests.
2. Tests first, seen failing: the request URL of "FPGA architecture and design flow overview" holds `all:FPGA AND all:architecture AND all:design` and no `and`, `flow` or `overview`; a phrase of ten words gives three terms; a phrase of only stop words keeps its first word; a one-word phrase is unchanged; the same query always gives the same URL; the limit, the pause, and the refusal rules are as before.
3. Write the change: a small fixed stop list (articles, prepositions, conjunctions, and the words that the topics put in front of a subject, such as "textbooks" and "overview" and "introduction", "advanced", "principles", "fundamentals", "comparative", "analysis"), `MAX_TERMS = 3`, one place that makes the terms. Deliberate single changes (the cap, the stop list, the `AND`, a stop-word-only query, the order of the words); the `reviewer`; the Result; the spec sentence.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_srcarxiv engine.tests.test_discover`; the deliberate changes; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-18-fix-arxiv-queries-and-use-an-openalex-key#A`.

### Increment B — Say why OpenAlex said 429

**Outcome:** a 429 that is not the daily budget no longer turns OpenAlex off for the whole UTC day.
**Dependencies:** none (it stands alone and helps keyless use too).
**Affected areas:** `engine/kb/srcopenalex.py`, `engine/kb/discover.py` (what a refusal that lasts one refill does), their tests, `docs/specs/population.md`.
**Steps:**
1. Read `srcopenalex._fetch` and `SourceRefused`, `discover.refused` and how a refusal marks `source_off`, and `webclient._read_response` (done when the increment was begun: it returns an empty body for a status other than 200 and passes `Retry-After` and `X-RateLimit-*` through).
2. Tests first, seen failing, with one fixture for each case of completion criterion 4: a 429 with `X-RateLimit-Remaining` of `0.07`, `12` and `3.5` is a refusal for this refill, the next refill asks again, and the day's counter is not written; a 429 with `0`, `0.0`, an empty value, `-1`, `abc`, `1e3`, `1,5`, a value of 21 characters, or no such header, or two different values, is a refusal for the day; the reason text of a refusal holds only the plain numbers of the two headers, or `none`, so a header that carries other text puts none of it into the reason or the log; the status of every other answer is as before.
3. Write the change: a refusal that carries a flag for how long it lasts, read by discovery, which then keeps the source off for the rest of the refill without writing the day's counter. Deliberate single changes, each to be caught by a fixture (the flag, a remaining of zero read as the refill, an absent header read as the refill, the `> 0` test as `>= 0`, header text into the reason). These changes make the behaviour the plan forbids, to see that the tests fail; the criterion is the behaviour. The `reviewer`; the Result; the spec sentences.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_srcopenalex engine.tests.test_discover engine.tests.test_srcwikipedia engine.tests.test_srcarxiv`; the deliberate changes; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-18-fix-arxiv-queries-and-use-an-openalex-key#B`.

### Increment C — Send the owner's key to OpenAlex

**Outcome:** `openalex_key = on` makes OpenAlex requests carry the key, and nothing else does.
**Dependencies:** Increment B (so that a pacing 429 of a new key does not cost the day).
**Affected areas:** `engine/kb/crawlrefill.py` (the policy, the keyed `get`, the key file and the log's secrets), `engine/kb/discover.py` (a `get` for each source), `engine/kb/crawlplan.py`, `engine/kb/crawlapprove.py`, their tests (including `engine.tests.test_crawlrefill`), `docs/specs/population.md` (the plan example and the sources paragraph).
**Steps:**
1. Read how `crawlrefill` builds its policy, `get` and the call of `discover.fill`, how `discover` makes `paced` from the one `get`, how `crawllists` reads a key file and gives it to the log (`add_secrets`), `webclient.get`'s credential rules, and `crawlapprove`'s preview.
2. Tests first, seen failing: `openalex_key = on` and `off` are read, any other word is refused naming the line; with it on, discovery's OpenAlex requests go through a policy with `credential_headers` (`Authorization: Bearer <key>`), `credential_host` `api.openalex.org`, no redirect, and no other source's request has the credential; the key is in the log's secrets before the request (tested through the refill step with a fake client), so a line that carries it is refused; a key file that is missing, mode 644, a link or empty turns OpenAlex off for the day with a fixed reason and no request; an OpenAlex address that is not `api.openalex.org` over https is refused before the credential is sent; the preview with the key on names the key file and says nothing of it when off; the shipped default plan has it off; the owner's plan file with no `openalex_key` line behaves as before.
3. Write the change. Deliberate single changes (the key not given to the log, the mode check skipped, the credential on another source, the host not checked, a redirect followed, the preview line dropped); the `reviewer`; before the commit the agent names what the change exposes (the key's whole path: file, policy, log, events, queue, status) and asks the owner whether to run a security review; it runs only if the owner asks, and the Result records the review or the owner's decision not to run it; the Result; the spec.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlrefill engine.tests.test_discover engine.tests.test_crawlplan engine.tests.test_crawlapprove engine.tests.test_srcopenalex engine.tests.test_webclient engine.tests.test_crawlstatus`; the deliberate changes; `wb run code-work check`. `test_webclient` is run unchanged to confirm that the client was not touched.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-18-fix-arxiv-queries-and-use-an-openalex-key#C`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. After C the agent reruns the tests of `srcopenalex` and `discover` (B and C both touch them) and `wb run code-work check`, and runs a read-only check that no file outside "Scope" changed. A wider run is not needed: the changes are the words of one query, the reading of one status, and a credential on one source's requests.

**The owner's trial (not a test, not a commit).** After the owner approves the crawl plan with `openalex_key = on`, the first refill is watched: the log shows OpenAlex's requests and any refusal and its reason, the owner reads the status for the day's counts, and, from a small script that prints only numbers, the response headers `X-RateLimit-Credits-Used` and `X-RateLimit-Remaining` of one request show what a request costs and how much of the day is left. The arXiv fix is seen in the first refill that asks arXiv: its lines should show entries where they showed none. The owner decides whether to leave the key on.

## Risks and sensitive actions

- **A secret.** The key is read from the owner's file and sent to one host. The tests, and a security review of C if the owner asks for one, look at the file's checks, the credential rules, the scrub of errors, the log, the events, the queue and the status. The key reaches none of them.
- **A change of engine code voids the approval.** Runs refuse until the owner approves again, which is the owner's act, at a time the owner chooses.
- **A new account's pacing.** A key made on or after 2026-11-03 spends its first $1 at up to $0.10 every 5 minutes, so the first bursts may still be limited. Increment B makes the pacing a refusal for the refill only, so the next run tries again.
- **The cost.** A free account has no payment method; if the owner has added one, the key could spend money. The owner confirms before turning the key on.
- **Fewer than hoped.** Three words may find papers that are only loosely on the topic; the judge step still decides whether each is kept.
- **A 429's headers are outside data.** Only two plain numbers are read and no other text is kept. If OpenAlex sends no such header on a 429, the behaviour stays as today (a refusal for the day), so the change may bring no gain until a real answer is seen; the log then shows what the 429 carried.

## Review record

- **Reviewer:** a second model through the project's review engine (`review-plan`, the `ask-codex` bridge, model `gpt-5.6-terra`, location class `unknown`), 2 rounds of the bound of 3; the reading after round 2 is that its last finding was applied.
- **Applied:** (round 1) the wording of the deliberate changes of Increment B, which read as behaviour and are now said to be mutations that the tests must catch; the complete table of 429 reasons with the duration of each and a fixture for each row; the provenance of the OpenAlex pages (addresses, date, sha256 of the bytes served), with the statement that no real API answer exists yet. (Round 2) a security review is asked of the owner and runs only if the owner asks, with the review or the decision recorded in the Result.
- **Rejected or changed, with reason:** one part of the suggestion on the 429 table was not taken as written: a 429 whose body is a valid object with no `reason` is a refill-only refusal and not a refusal for the day, because OpenAlex's errors page says such answers come under load and are to be retried after their wait; a made-up reason and any malformed or oversized body fail closed to the day.
- **Found while applying:** the cause of the 429 of 2026-11-18 is not proven (the body was not kept); the Goal says so and Increment B logs the reason token.
- **Changed after approval (2026-11-18, with the owner's choice and a new approval):** when Increment B was begun the web client was found to return no body for a status other than 200, so the review's reason table, which classified a 429 by the body's `reason`, could not be built. The classification now uses the `X-RateLimit-Remaining` header (above zero: the refill only; anything else: the day), fails closed, and the Goal, the Scope, the constraints, criterion 4, Increment B and one risk say so. The review's findings on the table (R1-F2) stand as history; its fixtures are replaced by the header cases.
- **Left for the owner:** whether to run a security review of Increment C; the confirmation that the OpenAlex account has no payment method before the key is turned on.

## Deferred work

- Using OpenAlex's rate-limit endpoint and budget headers to stop before a 429.
- Waiting out a `Retry-After` inside a refill.
- The key reader shared with URLhaus is reused by name; a neutral module and error class is a cleanup (also noted in the LangSearch plan).
- A second try of an arXiv query with fewer words when it finds nothing.
- The DOI links that lead to publishers that refuse automated requests (about half of the queued OpenAlex candidates): taking the open copy that OpenAlex names instead.

## Result

### Increment A — Ask arXiv for three words, not all of them (verified, not committed)

- **Changed (in a separate copy of the tree, moved to the main tree when the owner says to commit):** `engine/kb/srcarxiv.py` (`MAX_TERMS = 3` and `_STOP`, 34 words; the old `MAX_WORDS = 8` cut is gone; the words are cut into letters and digits, the stop words are dropped in any case, the first three of the rest are asked as `all:w1 AND all:w2 AND all:w3`, and a phrase of nothing but stop words keeps its first word; the docstring and the comment say so), `engine/tests/test_srcarxiv.py` (three old tests changed to the new rule, seven new: the small words, the topic words, every one of the 34 stop words in the first place, a whole-word check, the stop-words-only phrase, the same phrase giving the same request), `docs/specs/population.md` (one sentence at the OpenAlex and arXiv search line, with the measurement).
- **Seen failing first:** 7 of 49 tests failed before the change, each for the reason that the query still asked for every word.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_srcarxiv engine.tests.test_discover engine.tests.test_srcopenalex engine.tests.test_crawlrefill` gave 308 tests OK. Seven deliberate single changes (the cap of 4, the stop filter off, the case rule, the all-stop fallback, one topic word out of the list, `OR` for `AND`, a cut before the filter) were each caught by `test_srcarxiv`, and the file was restored byte for byte. One of them was first missed (a topic word out of the list); the test of every stop word in the first place was added, and a wrong count in that test (34, not 30) was found because a later run caught every change for the wrong reason, then fixed and the seven were run again. `git diff --check` clean. A `ResourceWarning` for an unclosed fixture file of a discovery test is printed in the copy with and without the change (not in the main tree; the cause is not known and it is not from this change).
- **Review:** the `reviewer` agent, one exchange: no blocking finding. Two small points applied: the module docstring now says the stop words are dropped and the terms capped, and a comment that said "six words or more" says "a long phrase" (that figure was not measured). The reviewer did not run programs, the plan check, or the whole of `test_discover`; those were run by the agent that made the change.
- **Measured, for the record (2026-11-18, `export.arxiv.org`, ten phrases of the owner's topics, one request each, 3.5 seconds apart):** all words found nothing for ten of ten; the first 3 non-stop words found 10 papers for nine of ten; the first 4 for six of ten (2 or 3 papers for three more); the first 5 for six of ten.
- **Committed:** `b2b0c2c`, with the trailer `Plan: 2026-11-18-fix-arxiv-queries-and-use-an-openalex-key#A`.
- **Not done:** Increment C; a first run of the crawl with these changes (the owner's trial).

### Increment B — Say how long OpenAlex's 429 lasts, from its headers (verified, not committed)

- **A change of the plan first:** when the increment was begun the web client was found to return an empty body for every status except 200 (`webclient._read_response`), so the 429 `reason` of the body that the approved plan classified on could not be read. The owner chose to classify by the `X-RateLimit-Remaining` header (which the client does pass through), the plan was edited and approved again (region 8e5c14d6feab...), and this increment was built to that wording.
- **Changed (in a separate copy of the tree, moved to the main tree when the owner says to commit):** `engine/kb/srcopenalex.py` (`SourceRefused.for_day`, default True; `_PLAIN_NUMBER` and `_plain_number`: the header, in any case, once only, a plain number of ASCII digits with at most one point and at most 20 characters; the 429 branch of `_fetch`: remaining above zero is `for_day=False`, anything else the day, and the reason is `status 429 (remaining <n or none>, retry-after <n or none>)`; the docstrings), `engine/kb/discover.py` (the local `refused` writes the day's `source_off` counter only when `for_day` is not False; two docstrings say so), `engine/tests/test_srcopenalex.py` (`RateLimitTest`, 8 tests with 19 non-number values and 6 numbers), `engine/tests/test_discover.py` (the `Source` fake takes `for_day`; four new tests: a refill-only refusal of a search, asked again by the next refill, one during a walk, and the real modules with a header above zero), `engine/tests/test_srcwikipedia.py`, `engine/tests/test_srcarxiv.py` and `engine/tests/test_srcwebsearch.py` (one test each: a 429 with budget left stays a refusal for the day for those sources), `docs/specs/population.md` (one passage at line 157).
- **Seen failing first:** the new tests failed (errors for the missing `for_day`, and the reason text) before the change.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_srcopenalex engine.tests.test_discover engine.tests.test_srcwikipedia engine.tests.test_srcarxiv engine.tests.test_srcwebsearch engine.tests.test_crawlrefill engine.tests.test_crawlsteps` gave 521 tests OK. Thirteen deliberate single changes (>= for >, the flag always for the day, an absent header read as budget left, a repeated header believed, the header read in lower case only, 40 characters allowed, a sign allowed, header text in the reason, another status read as a 429, `\d` for `[0-9]`, the counter always written, the counter never written, the flag read the wrong way round) were each caught, and both files were restored byte for byte. Two were first missed: a 21-character number with a point (a test was added) and a default of `getattr` that could not be reached (the code was simplified to `error.for_day`, and a change of the flag's sense was added). `git diff --check` clean.
- **Review:** the `reviewer` agent, one exchange: no blocking finding; four small points, all applied: a test that a Wikipedia, arXiv and web-search 429 with budget left stays a refusal for the day (their refusal's reason now also carries the two numbers for Wikipedia, because it re-uses OpenAlex's fetch, and its flag is dropped by its own wrapper); the two docstrings of `discover`; a test through the real modules with a header above zero; and `"9, 9"` as a value read as not plain. The reviewer did not run programs or `wb run code-work check`; those were run by the agent that made the change.
- **Not seen:** a real 429 answer from OpenAlex. If it sends no `X-RateLimit-Remaining` on a 429, nothing changes (a refusal for the day), and the log line will say `remaining none`.
- **Not done:** Increment C; a first run of the crawl with these changes (the owner's trial).
