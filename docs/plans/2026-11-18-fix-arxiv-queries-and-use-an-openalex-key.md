# Fix the arXiv queries of the unattended crawl and let OpenAlex use the owner's key

Status: Proposed
Created: 2026-11-18
Candidate: none (corrections that follow from a finding: on the first full day arXiv search found nothing in about 190 requests, and OpenAlex's keyless daily budget was spent by the first burst of each UTC day)
Specs: docs/specs/population.md

## Goal

Discovery's two scholarly sources limit what the crawl can find, and each for a cause that is now known.

**arXiv found nothing.** From 2026-11-17 to 2026-11-18 the arXiv source made about 190 requests (12 in the first burst, then 50 in each of seven runs, three seconds apart) and every answer had no candidate. `srcarxiv.search` turns a query into `all:w1 AND all:w2 AND ...` for up to 12 words, so every word, "and", "of" and "textbooks" included, must match. The queries are 6 to 10 word phrases from the owner's topics. Measured on 2026-11-18 against `export.arxiv.org` with ten real topic phrases (one request each, 3.5 seconds apart): all words gave no entry for all ten; the first 3 words that are not stop words gave 10 entries for nine of the ten; the first 4 gave 10 entries for six, 2 or 3 for three, and none for one; the first 5 gave entries for six of ten (10 for five of them, 8 for one). The phrase that gave nothing at any length ("comparative analysis of ngspice and LTspice for circuit simulation") names two niche tools.

**OpenAlex answers 429 and the engine gives up for the day.** OpenAlex's pages (read 2026-11-18) give a keyless daily budget (the engine's source says $0.10, about 100 searches), 10 times that for a free key ($1 a day), and a reset at midnight UTC. Its errors page lists the `reason` of a 429: `daily_budget` (today's budget is spent), `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search` (per-second limits that cost nothing), and `first_dollar` (a new account spending its first $1 faster than the pace of $0.10 every 5 minutes); and it says that some 429s, such as keyless traffic while search is under heavy load or an account they have throttled, carry no reason, and that the answer is to wait the `Retry-After` seconds and retry. The engine turns OpenAlex off for the UTC day on any 429, so each day buys about one burst (160 candidates on 2026-11-17, 74 on 2026-11-18). **The body of the 429 that ended the burst of 2026-11-18 (01:13Z, on the second request of a new UTC day, after 12 requests the day before) was not kept, so it is not known whether that day's budget was spent or the answer was a 429 with no reason; the log says only "status 429".** The second fits a 429 under load better than a spent budget. Increment B therefore also writes the reason token to the log, so the next 429 says which it is. The owner has a free key in the key file `openalex.key` of the config folder (mode 600; this plan reads no key and holds none).

When this plan is done: an arXiv query asks for its first three words that are not stop words, so most queries find papers; OpenAlex requests carry the key when the crawl plan says `openalex_key = on`, with the secret kept out of every log line and event; and a 429 that is not the daily budget stops OpenAlex for the rest of that refill only, not for the day. The shipped default is `openalex_key = off`; the owner turns it on in the crawl plan file and approves again.

Provenance of the facts above, retrieved with `curl` on 2026-11-18 (status 200; sha256 of the bytes served): `https://help.openalex.org/api/authentication/` 2e16efca000c8e7f1b60b687cf58e3d9d1f9408f214911d924705ec296dc1f8f (key from the account's API key settings, sent as `?api_key=` or as `Authorization: Bearer`, which "work identically"; a free key gives 10 times the keyless budget; the `reason` values `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search` and `daily_budget`; the new-account pace; per-second limits 10 without a key and 30 with one; the page does not mention `mailto`) and `https://help.openalex.org/api/errors/` 13cdb11199267e6e6607645eb49659a1bea1bf95090d11998e156d33f1e7f4e2 (the table of reasons, including `first_dollar`, and the 429s that carry no reason). The reason names and the new-account text were found in those bytes by a text search; no response from the API was fetched (the budget endpoint needs a key), so no real answer fixture exists yet: the tests write their own, from the table, and the owner's trial records a real one. The arXiv measurement used the API's own answers (a script that prints counts only, run on 2026-11-18). The costs per call are on OpenAlex's pricing page, which was not read.

## Scope

**Changed:**
- `engine/kb/srcarxiv.py` and its tests: the words of a query (stop words dropped, at most three kept).
- `engine/kb/srcopenalex.py` and its tests: a 429 is read for its reason (the body's `reason`), a daily budget is a refusal for the day as now, and any other 429 is a refusal for this refill only.
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
- A 429's body is data from outside: only its `reason` field, if it is one of a short fixed set, is read.
- Nothing tracked points to anything untracked: the plan names the key file by its name in the config folder, as the URLhaus key is named.

## Completion criteria

1. An arXiv query is cut into its letters and digits, the words of a fixed stop list are dropped, and at most the first three of the rest are asked as `all:w1 AND all:w2 AND all:w3`; a query of nothing but stop words keeps its first word; every other rule of the module is as before.
2. `openalex_key = on` makes every OpenAlex request carry the key in `Authorization: Bearer` over https to `api.openalex.org` with no redirect; no other source's request carries it; the key is in the log's secrets before the first request and is in no log line, event, reason, counter or status.
3. A key file that is missing, not mode 600, not the owner's, a link or malformed turns OpenAlex off for the day with a fixed reason that holds none of the file's text, with no request made and no fallback to the keyless request.
4. The 429 reasons are classified from a fixed table. **For the UTC day:** `daily_budget`; any other reason string; and a body that is not a JSON object, is over 2,000 bytes, or whose `reason` is not a short plain string (these fail closed). **For this refill only:** `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search`, `first_dollar`, and a 429 whose body is a valid JSON object with no `reason` (the page says that such a 429 is to be retried after its wait). A refusal for the refill ends OpenAlex's asks for it, is logged with the reason token (a token of the table, or `none`), and does not turn the source off for the day; the next run asks again, so at most one request a run is spent on it. No other text of a body is kept.
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
1. Read `srcopenalex._fetch` and `SourceRefused`, `discover.refused` and how a refusal marks `source_off`, and whether the web client returns the body of a 429.
2. Tests first, seen failing, with one fixture for each row of the table in completion criterion 4: `daily_budget` is a refusal for the day; each of `requests_per_second`, `broad_boolean_query`, `wide_or_filter`, `semantic_search` and `first_dollar` is a refusal for this refill, the next refill asks again, and the day's counter is not written; a JSON object with no `reason` (a 429 under load) is a refusal for this refill; a made-up reason string, a body that is not JSON, not an object, empty, over 2,000 bytes or with a `reason` that is not a short plain string is a refusal for the day; the reason token of the table (or `none`) is in the refusal's reason and nothing else of the body is; every other status is as before.
3. Write the change: a refusal that carries a flag for how long it lasts, read by discovery, which then keeps the source off for the rest of the refill without writing the day's counter. Deliberate single changes, each to be caught by a fixture (the flag, `daily_budget` read as the refill, a made-up reason read as the refill, a body that is not JSON read as the refill, the body's text into the reason). These changes make the behaviour the plan forbids, to see that the tests fail; the table above is the behaviour. The `reviewer`; the Result; the spec sentences.
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
- **A 429 body is outside data.** Only a short known `reason` is read, and no text of it is kept.

## Review record

- **Reviewer:** a second model through the project's review engine (`review-plan`, the `ask-codex` bridge, model `gpt-5.6-terra`, location class `unknown`), 2 rounds of the bound of 3; the reading after round 2 is that its last finding was applied.
- **Applied:** (round 1) the wording of the deliberate changes of Increment B, which read as behaviour and are now said to be mutations that the tests must catch; the complete table of 429 reasons with the duration of each and a fixture for each row; the provenance of the OpenAlex pages (addresses, date, sha256 of the bytes served), with the statement that no real API answer exists yet. (Round 2) a security review is asked of the owner and runs only if the owner asks, with the review or the decision recorded in the Result.
- **Rejected or changed, with reason:** one part of the suggestion on the 429 table was not taken as written: a 429 whose body is a valid object with no `reason` is a refill-only refusal and not a refusal for the day, because OpenAlex's errors page says such answers come under load and are to be retried after their wait; a made-up reason and any malformed or oversized body fail closed to the day.
- **Found while applying:** the cause of the 429 of 2026-11-18 is not proven (the body was not kept); the Goal says so and Increment B logs the reason token.
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
- **Not done:** Increments B and C; a first run of the crawl with this change (the owner's trial).
