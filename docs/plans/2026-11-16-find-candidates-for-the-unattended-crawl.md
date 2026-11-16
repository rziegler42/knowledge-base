# Find candidates for the unattended crawl: the queue, the topics and the sources

Status: In Progress
Created: 2026-11-16
Candidate: none (no roadmap holds a candidate for it: the crawl is specified in `docs/specs/population.md`, which the owner approved as the design to build; adding a roadmap candidate is the owner's change of direction and is not asked for here)
Specs: docs/specs/population.md, docs/specs/shelf.md

## Goal

The unattended crawl (`docs/specs/population.md`) needs a stream of candidate books to fetch. This plan builds the **discovery half**: the candidate queue that discovery and the runner share, the owner's topics and the queries made from them, the sources that turn queries into candidates (OpenAlex with its citation links, arXiv, Wikipedia, and a web search engine as a best effort), and one entry point, `discover.fill`, that the runner calls to refill the queue. The **runner**, the fetching, the judgement, the moves, the web client and the lists are other plans, built at the same time by another engineer. The two halves meet only at the queue table and the function signatures below.

When it is done:

- `kb/crawlqueue.py` creates and checks `candidates.sqlite` exactly as the spec's table says, and can add candidates to it within the caps;
- the owner's topics file is read strictly, and each topic is turned into a few search queries without ever looking at page text;
- each source returns candidates (and, for OpenAlex, wandered candidates through citation links) as rows the queue accepts, with no real network request made by any test;
- `discover.fill(...)` fills the queue up to a target from all the sources that are on, within the plan's caps, and stops a source for the day when it refuses;
- `python3 -m kb crawl-discover --check` prints what a run would send and sends nothing.

## Scope

**All new files, owned by this plan** (a change to any other file is outside it; stop and ask):

- `engine/kb/crawlqueue.py`: the table, `connect`, `enqueue`, `insert_blocked`, `insert_rejected`, `kept_sources`, `counts`.
- `engine/kb/crawltopics.py`: the topics file reader and the shares.
- `engine/kb/crawlqueries.py`: the queries made from a topic.
- `engine/kb/srcopenalex.py`, `srcarxiv.py`, `srcwikipedia.py`, `srcwebsearch.py`: one source each.
- `engine/kb/discover.py`: `fill`.
- One new optional model task, `crawl-query`, in `engine/kb/models.py` (`OPTIONAL_TASKS`) and a paragraph in `docs/specs/models.md`; without a configured entry the queries are made without a model (see Increment B).
- One command, `crawl-discover`, added to `engine/kb/__main__.py` (a few lines; the only shared file touched).
- Tests: `engine/tests/test_crawlqueue.py`, `test_crawltopics.py`, `test_crawlqueries.py`, `test_srcopenalex.py`, `test_srcarxiv.py`, `test_srcwikipedia.py`, `test_srcwebsearch.py`, `test_discover.py`, and small recorded fixtures under `engine/tests/fixtures/crawl/`.

**Two things this plan takes from the other plans and must not build** (the engineer uses injected stand-ins until they arrive):

- `kb/webaddr.py` (`canon_address`, `canon_host`, `site_of`), built by the web-foundation plan. Every function here that needs them takes them as arguments with a default that imports `webaddr` when called, so the tests pass fakes.
- `kb/webclient.py` (the shared client with the address checks, pacing and user-agent). Every source takes a `get(url, headers=None, timeout=...)` argument that returns `(status, headers, body_bytes)`; tests pass a fake, and the default is the shared client once it exists.

## Non-goals

- The runner, the fetching of any page, capture, scan, convert, the judgement, cards, placement and moves.
- The plan file parser and `crawl-approve`: `fill` is given the plan's values as a plain dict.
- Following links in HTML pages to other sites, PDFs, Wikipedia's own links, the shelf entries and scouts, alternate copies, keyed search engines. All are designed and not built (`population.md`).
- Any real network request in a test, and any file outside the new files above (apart from the one command and the one task name).
- The owner's key, the lists, the blacklist and the allow file. The queue records a `blocked` row when the caller says an address is blocked; it does not decide.

## Assumptions and constraints

- The queue table, its statuses, who writes what, and the order of work are those of `population.md` ("The queue and the seen list"), including the two clarifications of 2026-11-16: the column `source_id`, and discovery's right to insert `rejected` rows with the reason `type`.
- **Discovery inserts `queued` rows, `blocked` rows and `rejected: type` rows, and nothing else.** It never changes a row's status afterwards, never deletes a row, and reads only the rows of status `kept` that have a `source_id` (to wander from).
- Everything a source returns is untrusted data: sizes are capped, JSON and XML are parsed strictly with no entity expansion (reuse the strict Atom parser of `capture_arxiv.py`), text is cleaned before it is stored, and an address over 2,048 characters is dropped.
- The scholarly and search sources are asked **without a contact address** and with an honest generic user-agent. If a source refuses that (a 401, 403 or 429, a CAPTCHA, or a changed page), it is **off for the rest of the day**, the log says so, and nothing is worked around.
- **The owner's topics are the owner's interests, and queries made from them leave this machine** (to OpenAlex, arXiv, Wikipedia, and a search engine). The owner decided to use those sources (`population.md`). The first real run is a **send** and waits for the owner's word after `--check` has shown what would be sent.
- The method is the project's: tests first (see them fail for the right reason), deliberate breaks of each new module (each compile-checked, the file restored byte for byte, equivalent mutants dropped with the reason), the `reviewer` agent's reading of each increment, the Result recorded before the commit, a commit on the owner's word to the branch `crawl-discovery`. Nothing is pushed to `main` and the plan file lives on that branch only until the plan is `Completed`. A `security-reviewer` reading is asked of the owner once for Increment C (it parses untrusted network data).
- No test starts a process, opens a socket or reads the owner's library or config. The recorded fixtures are made by hand from the sources' public documentation, which Increment C, D and F read first and cite by URL, retrieval date and content hash.

## Completion criteria

1. `crawlqueue.connect` creates `candidates.sqlite` with the spec's exact shape (a test compares the created schema, column by column, with the spec's table as written in the test) and `PRAGMA user_version = 1`, in WAL mode with a 30-second `busy_timeout`; it refuses a file with another shape or version; two connections can write at once.
2. `enqueue` inserts with `INSERT OR IGNORE` on the identity key, never deletes or changes an existing row, refuses an address over 2,048 characters, and stops at the total cap and the per-domain cap; `insert_blocked` and `insert_rejected` do the same and set the status and reason.
3. `crawltopics.read_topics` reads the owner's format strictly (sections with integer weights, comments, one topic to a line), refuses a malformed, oversized, linked or non-regular file, and `shares` gives each topic its weight over the total.
4. `crawlqueries.make_queries` gives at most `n` queries for a topic, from a fixed prompt that holds only the topic, read back by a strict reader that cleans and bounds them; the same topic and prompt version give the same queries from a cache; with no model configured it gives topic-only queries.
5. `srcopenalex` turns search results into candidates by the spec's resolution rules (an arXiv id when the work has one; else an HTML landing page of an open-access work; else a `rejected: type` row), and **wanders**: from each kept work it takes the works it cites and the works that cite it, to depth 2, at most 5 for each work.
6. `srcarxiv` and `srcwikipedia` return candidates from a query; each respects its source's pause between requests and stops for the day on a refusal.
7. `discover.fill` fills the queue to its target within the caps, by the topics' shares and the plan's `wander_share`, does nothing when the queue holds more than the low-water mark, makes no request when every source is off, and records each refusal so that the source stays off for the day.
8. `python3 -m kb crawl-discover --check` prints the sources that are on, the topics, the number of queries each source would be sent, and the model call count, and **sends and writes nothing** (a test shows the library, the index and the queue file unchanged and no `get` call).
9. The new modules' tests and breaks, the tests of the files touched (`test_models`), and `wb run code-work check` pass; nothing else in the repository changes but the files named in "Scope".
10. The owner has read the result.

## Increments

### Increment A — The candidate queue

**Outcome:** `candidates.sqlite` can be created, checked and added to, and the contract between discovery and the runner is a tested fact.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlqueue.py`, `engine/tests/test_crawlqueue.py`.
**Steps:**
1. Write the tests first, copying the spec's table into the test as the expected shape: `connect` creates the file with mode 600 in a given folder, sets `user_version` 1, WAL and `busy_timeout` 30000, and a second `connect` accepts it; a file with a missing, extra or changed column, or another `user_version`, is refused; a path that is a link or not a regular file is refused.
2. Tests for `enqueue(conn, candidate, *, canon_address, site_of, limits, now)`: a new address is `queued` with `domain` filled by `site_of`, `depth`, `added` and `updated` set; the same identity key again returns `duplicate` and changes nothing; an address over 2,048 characters returns `too_long`; the total cap and the per-domain cap return `capped` and insert nothing; a candidate is a plain dict with the columns of the table, and unknown keys are refused; `canon_address` and `site_of` are arguments with a default that imports `webaddr` when called.
3. Tests for `insert_blocked(conn, candidate, reason)` and `insert_rejected(conn, candidate, reason)`: they set the status and reason, obey the same duplicate rule, and are not counted against the queued caps.
4. Tests for `kept_sources(conn, source, max_depth)` (the `source_id` and `depth` of rows with status `kept` and a `source_id`) and `counts(conn)` (rows by status).
5. A **contract test** that builds the table from the spec's text and checks that `crawlqueue.connect` accepts it, so that a change to either is seen.
6. Write `crawlqueue.py`. No function deletes a row or changes the status of an existing row.
7. Deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlqueue`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-find-candidates-for-the-unattended-crawl#A`.

### Increment B — The topics and the queries

**Outcome:** the owner's topics are read, weighted and turned into queries without a page's text ever reaching a model.
**Dependencies:** A (for the types only).
**Affected areas:** `engine/kb/crawltopics.py`, `engine/kb/crawlqueries.py`, `engine/kb/models.py` (the optional task `crawl-query`), `docs/specs/models.md`, their tests, `engine/tests/test_models.py`.
**Steps:**
1. Tests first for `read_topics(path)`: the format of the spec (a line starting with `[` opens a section `[name weight=N]` with N a positive integer; `#` starts a comment; a blank line is ignored; a topic before any section, a repeated topic, a weight that is not a positive integer, a topic over 300 characters, a file over 256 KB, a link or a non-regular file is refused with a clear message); control, format and bidirectional characters are removed from a topic; the result is a list of `(topic, weight, section)`.
2. Tests for `shares(topics)` (each topic's weight over the sum) and `quota(topics, n, day_index)` (n queries spread by weight, deterministic, and rotating with `day_index` so that every topic is reached over days; the quotas sum to n).
3. Tests for `make_queries(topic, n, chat, cache, prompt_version)`: the prompt is a fixed text that contains the topic and nothing else; `chat` is an argument; the reply is read by a strict reader (one query to a line, numbering removed, 3 to 120 characters, letters, digits, spaces and a few marks, cleaned and de-duplicated, at most n kept); a reply that cannot be read gives the topic-only fallback; the same topic and prompt version are served from the cache and `chat` is not called again; with `chat=None` the queries are the topic and one or two plain variants of it.
4. Add `crawl-query` to `OPTIONAL_TASKS` in `models.py` with its test, and a paragraph in `docs/specs/models.md` saying the owner may name a chat entry for it and that without one the queries are made without a model.
5. Write the modules, the breaks, the `reviewer`'s reading, the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawltopics engine.tests.test_crawlqueries engine.tests.test_models`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — OpenAlex: search, resolution and wandering

**Outcome:** OpenAlex gives candidates for a query and, from kept works, the works they cite and are cited by.
**Dependencies:** A.
**Affected areas:** `engine/kb/srcopenalex.py`, `engine/tests/test_srcopenalex.py`, fixtures.
**Steps:**
1. **Read OpenAlex's current API documentation and terms first** (the search and filter parameters, the fields for open access, locations, `referenced_works`, `related_works`, citing works by `cites:`, paging, whether a key or a contact address is now required, the rate limit) and write down in the Result what was read: the address, the retrieval date and a content hash of each page. **If a key is now required, the source is off, the Result says so, and the increment ends there.**
2. Make small fixtures by hand from that documentation (a search page; a work with an arXiv location, a work with an HTML landing page, a work with only a PDF, a work that is not open access; a work's references; a page of citing works).
3. Tests first for `search(query, get, limit, now)`: a request is built with the honest generic user-agent and no contact address; a fake `get` answers from the fixtures; the response size is capped and parsed strictly; each result becomes a candidate dict by these rules: an open-access work with an arXiv id is `arxiv:<id without version>` with the abstract address and `source_id: openalex:<id>`; an open-access work with an HTML landing page is its canonical address; **a work whose only full text is a PDF is a `rejected` row with the reason `type`**; a work that is not open access is skipped; the candidate's `found_from` is the query.
4. Tests for `wander(kept_sources, get, per_work, max_depth)`: for each kept work, the works it cites and the works that cite it are fetched in batches, at most `per_work` taken for each (strongest first, by a stated rule), at `depth + 1`, never beyond depth 2, never a work already seen, with `found_from: openalex:<id of the kept work>`; a work whose id is malformed is skipped.
5. Tests for refusal: a 401, 403 or 429, a body that is not the expected JSON, or an over-size body, raises a `SourceRefused` carrying the reason, and no further request is made by that call.
6. Write `srcopenalex.py`; the breaks; the `reviewer`'s reading; **ask the owner once whether to run a security review of this increment** (it parses untrusted network data); the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_srcopenalex engine.tests.test_crawlqueue`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`.

### Increment D — arXiv and Wikipedia

**Outcome:** arXiv's search and Wikipedia's search give candidates for a query.
**Dependencies:** A.
**Affected areas:** `engine/kb/srcarxiv.py`, `engine/kb/srcwikipedia.py`, their tests, fixtures.
**Steps:**
1. **Read arXiv's API documentation and its rule on the pause between requests, and Wikipedia's API documentation and its rule on user-agents and request rates**, and record the address, the retrieval date and a content hash of each page in the Result. Wikipedia asks for a user-agent with contact details; there is none to give, so the generic honest agent is used, the question is recorded, and a refusal turns the source off for the day.
2. Fixtures by hand: an arXiv Atom reply with two entries and one with no results; a Wikipedia search reply with two pages and one with none.
3. Tests first for `srcarxiv.search(query, get, limit, now)`: the query is URL-encoded; the Atom reply is read with the strict parser of `capture_arxiv.py` (imported, not copied; it refuses `DOCTYPE`, entities, NUL and non-UTF-8); each entry is `arxiv:<id without version>` with the abstract address; the pause between two calls is the source's rule, enforced by an injected clock; an over-size or malformed reply raises `SourceRefused`.
4. Tests first for `srcwikipedia.search(query, get, limit, now)`: each hit is a page address on the language edition in use (English), canonical, with `source: wikipedia`; the title is cleaned; a disambiguation or list page is kept (the judgement is the runner's); refusals as above.
5. Write both modules; the breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_srcarxiv engine.tests.test_srcwikipedia`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`.

### Increment E — `discover.fill` and the command

**Outcome:** the runner has one function to call, and the owner has a command that shows what discovery would do.
**Dependencies:** A, B, C, D.
**Affected areas:** `engine/kb/discover.py`, `engine/kb/__main__.py` (the command only), `engine/tests/test_discover.py`.
**Steps:**
1. Tests first for `fill(conn, plan, topics, *, now, get, chat=None, sources=None, log=None) -> dict`, with `plan` a plain dict holding exactly these keys, which `population.md`'s plan format defines with their defaults: `queued_total`, `queued_per_domain`, `queue_low`, `discover_target`, `queries_per_topic`, `wander_share`, `wander_depth`, `wander_per_work`, the switches `openalex`, `arxiv`, `wikipedia` and `web_search`, and the gaps `gap_openalex_s`, `gap_arxiv_s`, `gap_wikipedia_s`, `gap_web_search_s` and `web_search_per_day`. A key that is absent takes the spec's default; an unknown key is refused. It returns early with zero when the queue holds `queue_low` or more rows; otherwise it adds up to `discover_target` rows: `(1 - wander_share)` of them from topic queries (the topics' quota for the day, queries made by `crawlqueries`, the sources in the order OpenAlex, arXiv, Wikipedia) and `wander_share` from wandering, never above a cap; a source that is switched off or that raised `SourceRefused` today is skipped and not asked again that day (recorded in the queue's `counters` table under the key `source_off:<name>`), and a refusal does not stop the other sources.
2. Tests: with every source off or refused, `fill` makes no request and returns zero; the function is idempotent within a day (a second call with the same inputs adds nothing new that the first would not); every row it inserts passes the queue's own checks; it logs each step through the `log(step, outcome, **fields)` argument with the step names `discover`, `enqueue` and `block` and the outcomes of the spec.
3. Tests for the command: `crawl-discover --check` builds the same plan from a given plan file path and topics file path (the plan's values are read by a minimal reader for these keys only, since the real parser is the runner's plan), prints the sources on, the topic count, the queries each source would get, whether a model would be called, and nothing else; **it sends nothing, writes nothing, and a test shows it**; without `--check` the command is refused with a message that a real run needs the owner's word and the runner.
4. Write the module and the command; the breaks; the `reviewer`'s reading; the Result; **the first real send waits for the owner's "run it" after the output of `--check`.**
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_discover engine.tests.test_crawlqueue engine.tests.test_crawltopics engine.tests.test_crawlqueries engine.tests.test_srcopenalex engine.tests.test_srcarxiv engine.tests.test_srcwikipedia engine.tests.test_models`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#E`.

### Increment F — The web search adapter (built last; off if not finished)

**Outcome:** a web search engine, best effort, gives candidates. Per `population.md` this source is built last: **if it is not finished by the supervised run it is off, and the plan is complete without it.**
**Dependencies:** E.
**Affected areas:** `engine/kb/srcwebsearch.py`, its test, `engine/kb/discover.py` (to register the source), fixtures.
**Steps:**
1. **Read what DuckDuckGo's HTML results page and its terms say about automated use** (the retrieval date and a content hash in the Result), record that its terms are unresolved (`population.md`), and make a fixture by hand of a results page and of a CAPTCHA or block page.
2. Tests first for `search(query, get, limit, now)`: the query is URL-encoded; results are read from the markup with a strict parser (the result address is decoded from the redirect parameter, only `http` and `https`, canonical, not a DuckDuckGo address); **a page with no results markup, an answer other than 200, a CAPTCHA or a block page raises `SourceRefused`**, which turns the source off for the day; the gap between queries is the plan's; nothing is worked around.
3. Register it in `fill` as the last source and off unless the plan switches it on; the breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_srcwebsearch engine.tests.test_discover`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#F`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the tests of every new module and of `test_models` are rerun together; the code hashes cited in the Results are compared with the files; the contract test of Increment A is rerun against the spec's table as it stands then (the spec may have changed); `wb run code-work check` is run; and `crawl-discover --check` is run on the owner's real plan and topics files (it sends nothing). The engine's other tests are not rerun: nothing else in the engine changes.

## Risks and sensitive actions

- **Untrusted network data is parsed here.** Sizes are capped, JSON and XML are parsed strictly, entity expansion is refused, every string is cleaned before it is stored, and a malformed reply is a refusal of that source for the day, never a crash of the run.
- **The owner's interests leave the machine** in the queries sent to the sources. The first real run is a send, preceded by `--check` and the owner's word.
- **A source can change or refuse at any time.** A refusal turns the source off for the day and is logged; nothing is worked around; a source that needs a key is off.
- **The queue can be flooded** by a source that returns many results or a work with many citations: the caps (total, per domain, per work) and the per-call limits bound it.
- **Two engineers touch one file** (`__main__.py`, the command and `models.py`, one name): the changes are a few lines each and are merged by hand.
- **Shared contract:** if the spec's table changes, the contract test fails on both sides, which is the point.

## Review record

**Increment A.** Reviewer: the project's `reviewer` agent (read-only; it ran nothing), **one exchange, one round** of the caps (3 rounds, 6 exchanges). Recommendation: no blocking findings; nine findings, none blocking, one extra remark on the exactness of the shape check.

Applied:

- `INSERT OR IGNORE` on the identity key, as the spec and Criterion 2 say (the duplicate check before it stays, so the two are equivalent under the lock; `rowcount` decides `duplicate`).
- A canonicaliser's answer is checked as data: a non-string, a `ValueError` from `urlsplit`, a control or invisible character, a host with no registrable domain are all `refused`.
- Upper bounds on `weight` (1,000,000) and `depth` (1,000), so a huge number is a `KbError` of ours and not an `OverflowError` of SQLite; `ip` must be an IP address.
- The shape check also compares the text of each table with the spec's, white space apart, so a `CHECK`, `STRICT`, `WITHOUT ROWID` or a generated column is seen (the reviewer's remark that `table_info` cannot show them).
- Tests: a changed type, NOT NULL, default and extra constraint each are refused (the old test's name claimed more than it did and was renamed); a test runs every public function against a table of all six statuses and compares every original row; the text guard now also names `ON CONFLICT`, `DO UPDATE`, `ALTER`, `executescript`, `writable_schema` and `VACUUM`; the second connect's `busy_timeout` and WAL, and the mode of the `-wal` and `-shm` files, are checked.
- The docstring says that a lock held over 30 seconds, or a transaction a caller left open, is SQLite's `OperationalError` and not a refusal of ours.

Rejected:

- Tests with two processes instead of threads: the plan says no test starts a process. The threads each hold their own connection, so SQLite's file locking is what they exercise; behaviour across processes and on macOS is not shown here.
- The gap between the checks on the file and `sqlite3.connect` (finding 9): the folder is the owner's index root and the file is mode 600; no one else can swap it. Recorded as a residual, not acted on.
- Wrapping `OperationalError` in `KbError` (finding 7): a held lock or a caller's open transaction is a fault of the environment or the caller, and hiding the type would hide the cause; documented instead.

Left for the owner: nothing from the review. The plan asks about a security review at Increment C, not here.

**Increment B.** Reviewer: the project's `reviewer` agent (read-only; it ran nothing), **one exchange, one round** of the caps. Recommendation: no blocking findings; nine findings, none blocking.

Applied:

- The topics file reader took a topic of one or two characters (`AI`, `Go`, `R`), and `make_queries` refused anything under three, so such a topic would have aborted a fill: `make_queries` now takes 1 to 300 characters, and a test reads a file and passes every topic it gives to `make_queries`.
- A word that a search source reads as syntax drops the line: a word that starts with `-` or `+` (a lone ` - ` stays), or that holds a colon that is not its last character (`site:`, `filetype:`, `au:`, `ti:`). The marks that stay are still free text.
- The fallback cuts a long topic at a word, not in the middle of one; the fallback keeps the owner's words as written (`C#` stays), by design, and the docstring says a source must put every query in its address as free text.
- A path with a NUL character is a refusal of ours, not a `ValueError`.
- The `quota` docstring says that day `d` takes picks `d*n+1` to `d*n+n` of one endless sequence, so a changed `n` still follows on and takes no pick twice, and that a small topic is reached about once in `1/(share*n)` days (the weight-1 topic of the owner's list, 1 in 956, about once in 48 days at 20 a day); a test now shows that the days of any `n` are slices of the one sequence.
- Test names that claimed more than they showed were renamed or made to show it (the cache is never longer than `n`; the cache key; the day test); the file test's obscure expected value was made plain.

Rejected:

- A well-formed but off-topic entry in the cache is served as it stands (finding 4): a cache cannot be tied to the topic it answers, the entry is at most `n` plain queries, and the cache is the owner's own file. **For Increment E (and the runner):** keep the cache file in the index root with mode 600.
- A proof of reach for any list (finding 6): not given; the docstring now says how often a topic of a given share is reached.

Left for the owner: the todo list holds an item that the behaviour fingerprint of the crawl spec (`population.md`) names the models section "for the card, placement and embedding tasks" and not the entry set for `crawl-query`, which decides what an unattended run sends; it is a change to a spec's direction and so the owner's. The sources of Increments C and D must put each query in the address as free text (the reader drops syntax words, but the fallback sends the owner's topic as written).

## Deferred work

- Following HTML links from fetched pages to other sites, and Wikipedia's own links (`population.md`, "designed, built later").
- PDFs on other hosts and plain text, alternate copies after a refusal.
- A keyed search engine (Brave) as another adapter, and a search of other languages' Wikipedias.
- The runner's use of the queue (state transitions, counters, order of work): the runner plan.

## Result

### Increment A — The candidate queue (not yet committed)

**Done.** `engine/kb/crawlqueue.py` (311 lines, sha256 `f4c2065e9a44916db5504f376974e7f2ce91fe66351a5c90c2bf5632faaf92c4`) and `engine/tests/test_crawlqueue.py` (712 lines, sha256 `73c0dc51259900c37fd776ad04b838d0592c8701a716d344ee9bcaab9953d16d`), made on the branch `crawl-discovery` from `f26d812`. No other file changed but this plan's status, review record and result.

- `connect(folder)` makes `candidates.sqlite` with mode 600, `user_version` 1, WAL and a 30,000 ms `busy_timeout`, by the first of two openers (`BEGIN IMMEDIATE` decides who makes the table); it refuses a link, a folder, a pipe, a file of another owner or one that others can read, another version, another table, an extra table, index, view or trigger, and a table whose text is not the spec's.
- `enqueue`, `insert_blocked`, `insert_rejected` return `queued` / `blocked` / `rejected`, `duplicate`, `too_long`, `refused` or `capped`; discovery's only reasons are `owner`, `list:<name>` and `type`; only rows with status `queued` count against the caps; nothing in the module deletes or changes an existing row. `kept_sources` and `counts` read only.
- `webaddr` is not built; `canon_address` and `site_of` are arguments, and the default (import `webaddr`) is a refusal that says so until it exists.

**Verification as run (Linux, Python 3.14.4, at `f26d812` plus the two new files):**

- `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawlqueue`: 68 tests, OK, three runs in a row; with `engine.tests.test_models` added (not named by the increment, run once for the check that nothing else moved): 243 tests, OK.
- Deliberate breaks (`crawlqueue.py`, 61 single changes, each compile-checked, the file restored byte for byte and its hash compared; the bytecode cache removed before each run, because a first pass showed that a same-size change made in the same second ran from the old cache and gave false survivors): **52 killed, 9 survived**, all judged equivalent: no `O_NOFOLLOW` on create (`O_EXCL` already fails on a link and the `lstat` check refuses it); the plain-file check (a link, a folder and a pipe are refused by the mode check, and SQLite refuses a pipe or folder of mode 600 itself; a test covers the pipe); the owner check (cannot be tested without a second user); `timeout=30` of `sqlite3.connect` (the explicit `PRAGMA busy_timeout` overrides it); the unique, table-name and column checks (the comparison of the table's text with the spec's covers each, and a test per kind of change is in the suite); plain `INSERT` for `INSERT OR IGNORE` and the `rowcount` test (the duplicate check before them makes them equivalent under the lock).
- `wb run code-work check`: checked 51 plans, no problems, run after the review fixes and the plan's own edits; `wb plan-status` still says `approved`.

**Not run:** the engine's other tests (nothing else in the engine changed); any test with two processes (the plan forbids a process in a test); anything on macOS; the contract test against `webaddr` (not built).

**Open:** the default `canon_address` and `site_of` stay a refusal until `kb/webaddr.py` exists (another plan); the contract test reads `docs/specs/population.md` by two text anchors and will fail loudly if they move.

### Increment B — The topics and the queries (not yet committed)

**Done.** Four new files and three changed, on the branch `crawl-discovery` from `9167a16`:

| file | lines | sha256 |
|---|---|---|
| `engine/kb/crawltopics.py` | 138 | `b1f7adf9b8b07ec5fc0a8e3b2887ba4309e1ec4bd8a511507ea86c9e7ce0c895` |
| `engine/kb/crawlqueries.py` | 142 | `c59e81e8b0ddd546e62cb9a38ec00a8ee95b1a09e1e7a97a3a603129bb387f58` |
| `engine/tests/test_crawltopics.py` | 279 | `3319da5571181e2d45ef00e83bf4b6e6b9366ec7c1df262a666426a1eca3bdfe` |
| `engine/tests/test_crawlqueries.py` | 323 | `403993146097cfc5821206fa7609e1b415991c169e2f19fe4e5c5a9964316eca` |
| `engine/kb/models.py` (one name and a comment) | | `14451817395d8e93a9a1d50137477bfb00f8c352c4b59dfaec5a3076af60a625` |
| `engine/tests/test_models.py` (the `TASKS` assertion and one new test) | | `f69d2c9720c968292f81d9a6567184ca9368b6a1fce1c924e71c28d409868ed5` |
| `docs/specs/models.md` (one paragraph for `crawl-query`) | | `fae41f2d212c484c875964a77c4d17f24f1916ef3484e743817a335174b26a52` |

- `read_topics(path)` reads the owner's file strictly (a plain file of at most 256 KB, UTF-8, no NUL; sections `[name weight=N]` with N from 1 to 9,999,999; a topic of up to 300 characters under a section, cleaned of control, invisible and direction characters, none repeated in any case; at most 5,000 topics; a refusal names the line and never quotes the text). **A hash starts a comment only at the start of a line**, so `C#` and `F#` are topics; the spec says only "`#` starts a comment", and this is the reading chosen.
- `shares(topics)` gives each weight over the sum. `quota(topics, n, day_index)` gives each topic its count of `n` picks for the day, from one endless golden-ratio sequence over the cumulative weights (integers only; deterministic; the counts add up to `n`).
- `make_queries(topic, n, chat, cache, prompt_version)` sends the model one fixed text with the topic and `n` and nothing else, reads the reply strictly (one query to a line, numbering and quotation marks off, 3 to 120 characters, at most 12 words, letters, digits, spaces and ` -+/&.,:'()`, no web address, no syntax word, no heading), caches a good answer by version, number and topic and reads it again before trusting it, and falls back to the topic and two plain variants when there is no model, the model does not answer (`KbError`), or its reply holds no line it can read.
- `crawl-query` is an optional task of `models.py` (a chat entry; it may be left unset), with its paragraph in `docs/specs/models.md`.

**Verification as run (Linux, Python 3.14.4):**

- `python3 -W error::ResourceWarning -m unittest engine.tests.test_crawltopics engine.tests.test_crawlqueries engine.tests.test_models`: 263 tests, OK, repeated; the files hold no control, invisible or direction character (a first version did: the tool wrote escapes as raw characters, and the files were converted back to escapes and checked).
- Deliberate breaks, each compile-checked, each file restored byte for byte and its hash compared, the bytecode cache removed before each: `crawltopics.py` 43 of 46 killed, `crawlqueries.py` 75 of 79, `models.py` 1 of 1: **119 of 126**. The 7 survivors are equivalent: the size check before the read and the one after it (each covers the other); the golden-ratio constant changed in its last bit (no pick below 2^60 moves); a quote strip for a one-character line (such a line is under 3 characters and dropped anyway); the spacing in the key for repeats and an empty list in the cache (both are already ruled out by the cleaned text and by `if hit:`); the `rstrip` after a cut (the text has single spaces).
- `wb run code-work check`: checked 51 plans, no problems.

**Not run:** the engine's other tests; any call to a model server (the model is a fake function in the tests; no test opens a socket or reads the owner's file); anything on macOS. The owner's real topics file was not read.

**Decisions to know:** a topic of the owner's file goes out as a query as written when no model is set or it fails (so `C#` stays), while a line of a model's reply must be a plain query; the cache is held by the caller and must be kept in the index root with mode 600 (Increment E); `quota` reaches the weight-1 topic of a list shaped like the owner's about once in 48 days at 20 a day.

**Open:** the todo items named in the review record (the fingerprint of the crawl spec, and the invisible characters in the committed test of Increment A).
