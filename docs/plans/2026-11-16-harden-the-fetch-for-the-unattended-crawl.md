# Harden the fetch and keep known-bad sites out of the unattended crawl

Status: Proposed
Created: 2026-11-16
Candidate: none (no roadmap holds a candidate for it: the crawl is specified in `docs/specs/population.md`, which the owner approved as the design to build; adding a roadmap candidate is the owner's change of direction and is not asked for here)
Specs: docs/specs/population.md, docs/specs/shelf.md

## Goal

The unattended crawl (`docs/specs/population.md`) fetches pages from any public site with no one watching. Today's fetch code (`capture_url.py`, `capture_arxiv.py`) is careful about private addresses, size, redirects and time, but it has no way to be told *who may be fetched*, how fast, as whom, or that a key must not follow a redirect. This plan builds the **web foundation** the rest of the crawl stands on, and the **owner's blacklist and the public lists of known-malicious sites**. The **runner** and the **discovery** half are other plans, built at the same time.

When it is done:

- one module canonicalises every address and host, and names a "site", so that identity keys, list matches and per-site caps agree;
- one shared web client makes every request the crawl makes, with the address checks at connect, a peer check, ports 80 and 443 only, pacing per site and per address, a choice of user-agent, extra headers, a mode that follows no redirect, a type gate with a sniff, and a hook that asks "may this address be fetched?" at the first request and at every redirect hop;
- `capture_url` and `capture_arxiv` can be given that policy (and a few arguments the runner needs) while every existing caller and test behaves as before;
- the owner's blacklist, an allow file and the public lists are read, downloaded, kept and matched by the rules of the spec, with the key for URLhaus handled as the spec says.

## Scope

**Files owned by this plan** (a change to any other file is outside it; stop and ask):

- New: `engine/kb/webaddr.py`, `engine/kb/webclient.py`, `engine/kb/weblists.py`, `engine/kb/urlhaus.py`, and their tests `engine/tests/test_webaddr.py`, `test_webclient.py`, `test_weblists.py`, `test_urlhaus.py`, with small hand-made fixtures under `engine/tests/fixtures/web/`.
- Changed, narrowly: `engine/kb/capture_url.py` and `engine/kb/capture_arxiv.py` (a `policy` argument, `auto_filed`, `types`; no change to their behaviour when the arguments are absent), and their existing tests, which must still pass unchanged.

**Interfaces the other plans build against** (these names are the contract; a change needs the owner):

- `webaddr.canon_host(name) -> str`, `webaddr.canon_address(url) -> str`, `webaddr.site_of(host, suffixes=None) -> str`, `webaddr.identity_key(url_or_arxiv_id) -> str`, `webaddr.load_suffixes(path) -> frozenset`.
- `webclient.Policy` (a plain object, with fields including `credential_headers` (a dict of header names to values) and `credential_host` (the one canonical host they may go to)), `webclient.get(url, *, policy, headers=None, max_bytes, timeout) -> (status, headers, body_bytes)`, `webclient.Refused` (a policy refusal, with a reason that is safe to log), and `webclient.PACER`, the shared pacing state the caller can reset in tests.
- `weblists.Matcher(owner_blacklist_path, allow_path, lists_dir, pinned_hosts)` with `.reload()`, `.blocked(address_or_host) -> None | Block(reason)` and `.update(get, now, lists_plan) -> report`, where **`lists_plan` is a plain dict with exactly the keys of the `[lists]` section of `population.md`'s plan format** (`phishing_domains`, `urlhaus_recent`, `phishing_domains_url`, `phishing_domains_format`, `public_suffix_url`, `refresh_hours`, `list_max_mb`, `list_min_share`, `list_max_change`, `urlhaus_keep_days`, `pinned_hosts`); a missing key takes the spec's default and an unknown key is refused.

## Non-goals

- The runner, the plan file, the stop file, the breaker, the log, the mover, the order of a run (the runner plan).
- Discovery, the queue, the sources (the discovery plan, which uses `webaddr` and `webclient` through the names above).
- **Limits on the sandboxed scan and conversion tools** (memory, PDF size, process count, decompression): a separate small plan that touches `convert_run.py` and the tool sandbox.
- Following links in HTML pages, PDFs on other hosts, plain text, `robots.txt` (not built; off), alternate copies after a refusal, and detecting a name that resolves to the owner's own outside address (a recorded residual risk, `population.md`).
- Judging a page, scanning it, or holding a book: those are the runner's.
- Any real network request in a test, any use of the owner's real key, library or config.

## Assumptions and constraints

- The spec's text on addresses ("Addresses, hosts and sites: one canonical form"), the shared client, the lists ("Sites that are off limits"), the key and URLhaus is the specification; where this plan is silent, the spec governs.
- The existing `capture_url` guard is kept as it is where it is already right: it resolves a host once, checks every answer and connects to the address it checked (`_connect_checked`), caps redirects at 5, refuses userinfo and percent-escaped hosts, refuses encoded responses and caps the size and the total time. **The shared client must keep each of those properties** and a test must show each.
- `capture_url` today sends an honest `knowledge-base/…` user-agent, accepts any port, has no pacing, accepts a response with no `Content-Type`, cannot take extra headers, and gives no hook for a blocklist at a redirect. Those are what this plan changes, for callers that ask.
- The Public Suffix List is read from a file in the index root that Increment D keeps current as one more list; without it `site_of` takes the last two labels and the caps are halved (the spec).
- **The URLhaus key** is a credential: it is read only from `~/.config/knowledge-base/urlhaus.key` (the path is an argument), only if the file is a regular file with mode 600 owned by the owner; it goes only in the `Auth-Key` header, only over https, only to `urlhaus-api.abuse.ch`, with no redirect followed; and it never appears in a log, an error, an environment variable, a command line, an address or a prompt. Tests use a canary string, never the real key.
- Method: tests first (see them fail for the right reason), deliberate breaks of each new module (each compile-checked, the file restored byte for byte, equivalent mutants dropped with the reason), the `reviewer` agent's reading of each increment, the Result recorded before the commit, a commit on the owner's word. **A `security-reviewer` run with experiments on a copy is asked of the owner for Increments B and D** (they decide what the crawl may fetch and carry the key), and a second look at any fixes.
- No test starts a process, opens a socket to anything but `127.0.0.1` or a fake, or reads the owner's library or config. Recorded data are made by hand from the lists' public pages, read first and cited by address, retrieval date and content hash.

## Completion criteria

1. **Canonical forms.** `evil.com`, `evil.com.`, `EVIL.com`, `evil.com:80` and an IDN form of a listed IDN host give one key and one match; a non-default port is refused; an address over 2,048 characters, a scheme other than `http` and `https`, and userinfo are refused; the common tracking parameters are removed; two names that resolve to one address count as one site in the pacer.
2. **The client.** A DNS answer that changes between the check and the connect is harmless and the peer of the connected socket is the checked address; a redirect to a private, loopback, link-local, metadata or non-80/443 address, at any hop, is refused; at most 5 redirects; a response with no `Content-Type`, or one that disagrees with a sniff of its first bytes, is refused; an endless, over-size, slow or encoded response is cut; `follow_redirects=False` treats any 3xx as a refusal.
3. **Pacing.** Requests to one registrable domain and to one address are one at a time, with the plan's gap and jitter, and the user-agent is the one the caller chose (a browser's for pages, an honest generic one for the scholarly and search sources).
4. **The hook.** A blocked address is refused before any request, at the first request and at every redirect hop.
5. **Capture.** `capture_url.capture` and `capture_arxiv.capture` take a `policy`, `types` and `auto_filed`; with none given they behave exactly as before (their existing tests pass unchanged); a book filed with `auto_filed=True` has the field set.
6. **The lists.** The owner's blacklist blocks a host and every host below it; a public host entry blocks that exact hostname only; a URL-list entry blocks that exact canonical URL and a whole host only for a bare IP; `github.com` in a URL list does not block the site; the pinned hosts are never blocked by a public list; an allow entry overrides a public list and never the blacklist; a failed download leaves the last good copy; a required list with no copy stops; an over-size, much smaller or too-changed list is refused; lines that are not hostnames are ignored; adding to the blacklist takes effect at the next `reload` with no other step.
7. **The key.** A list that needs a key is not requested without one; a key file that is not mode 600 or not the owner's is refused; a fake API that answers 302 to a second host sees no key there and the key is not sent again that day; the canary key appears in no log, report, error, prompt, environment, command line or address, including after a forced exception; when the rate-limit header reaches zero, or on any refusal, no more requests go to URLhaus that day.
8. The new modules' tests and breaks, the existing tests of `capture_url` and `capture_arxiv`, and `wb run code-work check` pass; nothing else in the repository changes but the files named in "Scope".
9. The owner has read the result.

## Increments

### Increment A — Canonical addresses, hosts and sites

**Outcome:** one module canonicalises everything, and the discovery plan can call it.
**Dependencies:** none.
**Affected areas:** `engine/kb/webaddr.py`, `engine/tests/test_webaddr.py`.
**Steps:**
1. Tests first for `canon_host`: lower-case; one trailing dot stripped; IDNA (UTS 46) to ASCII; refuse on failure, on an empty label, on a label over 63 or a name over 253 characters, on a bare number or an address-like name that is not a literal IP; an IPv4 or IPv6 literal is kept in its canonical text form; a name with a port or a path is refused (the port is for `canon_address`).
2. Tests for `canon_address`: only `http` and `https`; userinfo refused; the host canonicalised; the default port (80 for http, 443 for https) dropped, any other port refused; the fragment dropped; the common tracking parameters removed (**every parameter whose name starts with `utm_` or `mc_`**, and `fbclid` and `gclid`) and the other parameters kept in order; bidirectional and control characters in the address refused; over 2,048 characters refused; the result is idempotent (canonicalising a canonical address changes nothing).
3. Tests for `identity_key`: a page is its canonical address; an arXiv id (a bare id, an `arXiv:` form, an `abs` or `pdf` address) is `arxiv:<id without version>`; a DOI is refused (it is never a key).
4. Tests for `site_of(host, suffixes=None)` and `load_suffixes(path)`: with a suffixes set, the registrable domain by the Public Suffix List rules (including wildcard and exception rules); without one, the last two labels and a marker that the fallback was used; a literal IP is its own site; the file is read as data with a size cap, no link and no non-regular file.
5. Write the module with no import of any other `kb` module but `identity` where it already normalises, and no network. Deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_webaddr`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-16-harden-the-fetch-for-the-unattended-crawl#A`.

### Increment B — The shared web client

**Outcome:** one function makes every request of the crawl, under one policy.
**Dependencies:** A.
**Affected areas:** `engine/kb/webclient.py`, `engine/tests/test_webclient.py`.
**Steps:**
1. Read `capture_url.py` (`_connect_checked`, `_guarded_handlers`, `make_redirect_handler`, `_opener`, `_fetch`, `is_public`, `resolve_checked`) and the tests of it first, and write down in the Result which of its properties the client reuses by import and which it restates.
2. Tests first, each against a fake resolver and a fake server on `127.0.0.1` (allowed in the test through the existing `allow_private` switch) or a fake transport: (a) DNS rebinding: a name answers public, then private; the connection goes to the first, checked address and the socket's peer equals it, or the request is refused; (b) a redirect to a private, loopback, link-local, metadata, `file:`, `ftp:` or `data:` target, at any hop, or to a port other than 80 and 443, is refused; (c) at most 5 redirects; (d) `follow_redirects=False` makes any 3xx a refusal and the extra headers are not sent anywhere else; (e) a custom header is **not** copied to a redirect target on another host; (f) an endless stream, a declared over-size body, a slow body past the total deadline, a `Content-Encoding`, 500 headers and a conflicting `Content-Length` are cut or refused; (g) a response with no `Content-Type`, or a PDF served as `text/html`, is refused by the sniff, and a type outside `types` is refused; (h) the user-agent and the extra headers are exactly what the caller chose, and a credential header is refused unless the policy has `follow_redirects=False`, a `credential_host` equal to the address's canonical host, and an `https` address, and is never sent to another host; (i) the blacklist hook `policy.check(url)` is called with the canonical address before the first request and at every hop, and a refusal makes no request.
3. Tests for pacing: with an injected clock and sleeper, two requests to one registrable domain, or to one resolved address, are separated by at least the gap plus a jitter drawn from the plan's range; requests to different domains and addresses are not delayed by each other; the pacer is process-wide, `PACER.reset()` clears it for tests, and a request that is refused makes no entry.
4. Write `webclient.Policy` (user-agent, extra headers, gap, jitter, max redirects, follow-redirects flag, allowed types, a `check` hook, `allow_private`) and `webclient.get`. The client imports the address checks of `capture_url` rather than copying them; where it must restate one, a test shows the same behaviour on the same inputs as `capture_url`. **A credential header is accepted only through `Policy.credential_headers`, and only in a call whose policy also has `follow_redirects=False`, a `credential_host` (a canonical host name), and an `https` address whose host is exactly that host; any other call that carries `credential_headers` is refused before a request, the headers are never copied to a redirect, and they are never written to an error message, a log line or the exception text (tests use a canary).**
5. Deliberate breaks; the `reviewer`'s reading; **the owner is asked once whether to run a security review** (it decides what the crawl may fetch); the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_webclient engine.tests.test_webaddr engine.tests.test_capture_url`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — The capture functions take a policy

**Outcome:** the runner can capture a page or an arXiv paper under the shared policy and mark the book as filed by the crawl.
**Dependencies:** B.
**Affected areas:** `engine/kb/capture_url.py`, `engine/kb/capture_arxiv.py`, their existing tests, and new tests in `test_webclient.py` or `test_capture_policy.py`.
**Steps:**
1. Run the existing tests of both modules first and record that they pass.
2. Tests first for the new arguments, each leaving the old behaviour unchanged when absent: `capture(store, ident, address, ..., policy=None, types=None, auto_filed=False)`: with a `policy`, the request is made by the shared client under it and a blocked address raises the policy refusal **before** any book or identity entry is created; with `types`, the type gate uses them; with `auto_filed=True`, the book's root file has `auto_filed` true (it exists on `store.create_book` and neither capture passes it today). The same for `capture_arxiv.capture` (`policy`, `auto_filed`; its API and PDF requests go through the policy; its Atom parser is unchanged).
3. A test that a fetch refused by the policy **creates no book and no identity entry** (the existing code creates the book before it knows the fetch worked; a refusal before the request must not).
4. Change the two modules by the narrowest edit; the existing tests must pass **unchanged**; deliberate breaks of the new paths; the `reviewer`'s reading; the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_capture_url engine.tests.test_capture_arxiv engine.tests.test_webclient engine.tests.test_store`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`.

### Increment D — The owner's blacklist, the allow file and the public lists

**Outcome:** a host the owner or a public list names is never requested; a list is fetched, kept and refreshed by the spec's rules.
**Dependencies:** A, B.
**Affected areas:** `engine/kb/weblists.py`, `engine/tests/test_weblists.py`, fixtures.
**Steps:**
1. **Read the Phishing.Database repository's page and a real download of its active-domains list** (its address, its format, its size, its line shapes, any comments and header lines) and write down in the Result the address, the retrieval date and a content hash; build a fixture from the shape actually seen. **The spec leaves the format unread, and gives the address as read on 2026-11-16; this step confirms or corrects both, and the spec's defaults in `[lists]` are corrected if the real file differs.** Also read the Public Suffix List's page and format the same way.
2. Tests first for the parsers: a list of domains (one per line, comments and blank lines ignored; a line that is not a valid host or address is ignored and counted; a host is canonicalised by `canon_host`); the Public Suffix List format (rules, wildcards, exceptions, section markers) into the set `site_of` takes; a hard cap on lines and bytes.
3. Tests for `Matcher`: the **owner's blacklist** blocks the host and every host below it; a **public host list** blocks that exact hostname only; a **URL list** (kept as exact canonical URLs) blocks that exact URL and a whole host only when it is a bare IP address; `github.com` in a URL list does not block `github.com/other`; the **pinned hosts** are never blocked by a public list; the **allow file** overrides a public list for the hosts in it and never the blacklist; `evil.com.`, `EVIL.com`, `evil.com:80` and an IDN form all match one entry; `reload()` reads the blacklist again and a host added to it is blocked at once; a file that is a link or not regular, or over the size cap, is refused; a hit returns `Block(reason)` with `owner`, `list:<name>` or `allow`.
4. Tests for `update(get, now, lists_plan)`: each list named in `lists_plan` (the addresses and formats of `phishing_domains_url` and `public_suffix_url`) is downloaded at most once in `refresh_hours` (a conditional request with the saved `ETag` or `Last-Modified`; a 304 changes nothing); a download is stored with its retrieval date and hash in the lists folder (mode 600), written to a temporary file and renamed into place; a failed download, a refusal or a bad parse leaves the last good copy in use; a list over `list_max_mb`, **smaller than `list_min_share` of its last copy**, or **changed by more than `list_max_change` of its entries** in one refresh is refused and the last copy stays; a **required** list with no copy at all makes `update` report `stop`; an optional one is skipped and reported; every request goes through `webclient.get`, whose own policy refuses a private address, so a list address that resolves to one is refused.
5. Write the module; deliberate breaks; the `reviewer`'s reading; **the owner is asked once whether to run a security review** (list data decides what is blocked; a poisoned list must not switch the sources off); the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_weblists engine.tests.test_webaddr engine.tests.test_webclient`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#D`.

### Increment E — URLhaus, recent mode (built last; off if not finished)

**Outcome:** the URLs abuse.ch lists as recently added feed the URL list, with the key handled as the spec says.
**Dependencies:** D.
**Affected areas:** `engine/kb/urlhaus.py`, `engine/tests/test_urlhaus.py`, fixtures.
**Steps:**
1. **Read abuse.ch's current URLhaus API page and its terms** and record the address, the retrieval date and a content hash in the Result; record that the owner's key and the use of it are the owner's, and that the terms say not-for-profit use under fair-use limits.
2. A fixture by hand from the documented reply (query status, the list of URLs with their status and host). **No real request is made by any test, and the real key is never read by a test.**
3. Tests first, with a canary key in a temporary file: `read_key(path)` refuses a file that is not a regular file, not mode 600, not the owner's, empty, or with more than one line; `recent(get, key, now, lists_plan)` builds a `Policy` whose `credential_headers` is `{"Auth-Key": key}`, `credential_host` is `urlhaus-api.abuse.ch` and `follow_redirects` is false, so the header goes **only** to that host over https; **a fake API that answers 302 to another host sees no key there and the key is not sent again that day**; any 3xx, 401, 403 or 429 turns the source off for the day; the `X-RateLimit-Remaining` header at zero, or a refusal, makes no further request that day; the URLs are kept (canonical, with the date they were added) for `urlhaus_keep_days` and old ones are dropped; **the canary string is in no log line, no report, no exception text, no environment, no command line and no address** (a test forces an exception and searches all of them).
4. The list feeds `Matcher` as a URL list (exact canonical URL; a bare IP host blocks the host).
5. Write the module; deliberate breaks; the `reviewer`'s reading; the Result. **If this increment is not finished by the supervised run, the source stays off and the plan is complete without it.**
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_urlhaus engine.tests.test_weblists engine.tests.test_webclient`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#E`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the tests of every new module and the existing tests of `capture_url`, `capture_arxiv` and `store` are rerun together; the code hashes cited in the Results are compared with the files; `wb run code-work check` is run; and a read-only check shows that no file outside the files named in "Scope" changed. The engine's other tests are not rerun: nothing else changes.

## Risks and sensitive actions

- **This code decides what an unattended crawl may fetch and carries a credential.** Every refusal path is tested, every test uses fakes and a canary, and a security review with experiments on a copy is asked of the owner for B and D, with a second look at any fix.
- **A change to `capture_url`** can alter how every existing capture behaves: its existing tests must pass unchanged, and the new arguments default to the old behaviour.
- **A poisoned or wrong list** can block good sites or a source: the pinned hosts, the size and change checks, the allow file and the last good copy bound it, and the report names every list that could not be refreshed.
- **A list's terms are the owner's to have read.** The Result for D and E record the terms as read, not as a legal opinion.
- **Two engineers touch two files** (`capture_url.py`, `capture_arxiv.py`) and one new interface; the other plans use only the names under "Interfaces".

## Review record

Empty until a review is asked for.

## Deferred work

- Limits on the sandboxed scan and conversion tools (resident memory, PDF size, processes, decompression): its own small plan.
- Following HTML links, PDFs and plain text from other hosts, `robots.txt`, alternate copies, URLhaus lookups, other public lists.
- Detection of a name that resolves to the owner's own outside address.

## Result

Empty until work starts.
