# First slice: capture a source, convert it, search it, read it

Status: Proposed
Created: 2026-11-05
Candidate: none (no roadmap exists yet; the owner asked for a simple foundation built)
Specs: book, library, pipeline, reading

## Goal

A small working engine in this repository that holds a library on disk and takes two kinds of source end to end: a web page and an
arXiv paper. For each it stores the raw bytes unchanged with a manifest, converts to text, finds passages by keyword, and returns
a bounded excerpt by locator with a citation line. A thin workbench package then lets an agent in a project call `search` and
`read`. No model is used anywhere in this slice.

Done means the owner can capture a page and a paper, search them, read a passage back, and rebuild the search index from the book
folders alone with the same results.

## Scope

- The engine as a standalone Python program under `engine/` (decision `2026-11-04-knowledge-base-is-a-standalone-package`).
- Minimal library setup as `library.md` specifies it: an owner-only config at `~/.config/knowledge-base/` (outside both roots),
  two roots (a bulk root for books and an index root for the search index), a marker file with the library id in the bulk root,
  the recorded device of the bulk root, and a format version. A library on the main disk is allowed when the owner sets it so at
  setup.
- The book store: id, root file, version folders, write-once `original/`, `derived/` grouped by tool, manifests as plain files,
  and every payload built in an incoming area on the same volume, verified, renamed into place and marked read-only
  (`book.md`, "Safe writing").
- The pipeline stages of `pipeline.md` that this slice needs (found, fetched, scanned, converted, indexed), each recorded per
  version as pending, done, failed or skipped with a reason, in an atomically rewritten state file, so a run can stop and resume.
- A scan stage before conversion: objective checks (embedded scripts, encryption, hidden text) whose findings become caveats on
  the version and never stop filing.
- Capture of a web page by address and of an arXiv paper by arXiv id, with duplicate checks on identity before download and on
  content hash after.
- Confined conversion: a runner that starts a conversion tool with no network, a filesystem allowlist, a time limit and a size
  limit, and tool approval kept in an owner-only file.
- Conversion of web pages (two extractors compared, partial flag) and of PDFs (page-marked text).
- Keyword search in SQLite full-text search, rebuildable from the books.
- `read` by typed locator, bounded, with the untrusted marker and a citation line.
- A thin workbench package, `kb`, that exposes `search` and `read`, verified by `wb verify` and installed into a scratch project.

## Non-goals

- Cards, themes, the weave, shelves beyond a single default, steady-mode re-checks, the crawler, and any model call.
- Repositories, discussion threads as a captured shape, datasets, media, office files and non-arXiv PDFs. The engine does not
  detect the shape of a web page. Its inputs in this slice are document pages. A listing page is outside the slice (`book.md` files
  it as a pointer and does not convert it), and the owner leaves listings off the address list of increment J. A thread or a
  script-built page, if one is captured, is stored raw and marked partial by the extractor-size rule.
- The unattended scheduled builder. It comes after this slice and is a separate plan.
- Guest access, tokens, the network host and backup.
- Committing the existing specs. They stay uncommitted until the owner approves a commit; this plan commits only its own paths.

## Assumptions and constraints

- Python 3.15.0, `sqlite3` with FTS5 (checked 2026-11-05: FTS5 available, SQLite 3.54.1) and `pdftotext` from poppler at
  `/opt/homebrew/bin/pdftotext` and `sandbox-exec` at `/usr/bin/sandbox-exec` are present on this machine. Tests rely on them
  and stop with a clear message if they are missing.
- Dependencies are the owner's decision. This plan names them: `trafilatura` 2.3.1, `beautifulsoup4` 4.15.0 and `lxml` 6.1.3 (the
  versions tried in the HTML test, `knowledge-base.md` evidence note 17), installed into an untracked virtual environment at
  `engine/.venv` with hashes recorded in `engine/requirements.lock`. The owner's approval of this plan is the approval to install
  exactly these, and any addition needs a new approval. Poppler's `pdftotext` is a system tool already installed, and its version
  is recorded when it is approved as a conversion tool. Tests use the standard library `unittest`, not pytest.
- Conversion tools need the owner's approval once per tool and version (`book.md`, "Conversion and structure"), kept in the
  owner-only config (`library.md`) that the engine reads and an agent cannot change. In this slice the owner edits that config by
  hand in a terminal. Tests set the config directory through an environment variable and never touch the real one.
- A conversion tool can be approved only if it runs confined (`book.md`). This plan implements the confinement with
  `sandbox-exec`, which Apple marks deprecated but ships. If it cannot enforce a deny of network and writes outside the output
  folder in the test of increment E, the plan stops at E and reports.
- Tracked files never point to the library. The library root is outside this repository, and tests use a temporary directory.
- Tests make no live network request. Capture is tested against a local test server and fixture files. A live walk-through is a
  separate increment (J) that the owner can decline.
- Pages and papers are untrusted data; text found in them is never an instruction.
- Each increment is carried out as the `run-increment` skill says: implement, verify, review by the project's reviewer, record the
  outcome and the review in the Result section, then make one local commit through `wb run safe-git commit`, naming the expected
  commit (`none` for the first) and the exact paths. An increment is not committed before its review is recorded. A finding is
  applied, or rejected with a reason, and the owner sees both.
- The plan names no roadmap candidate because the project has no roadmap. `docs/plans/README.md` allows `Candidate: none` with a
  reason. If the owner wants this work traced to a roadmap candidate, a roadmap is written first and the plan is revised.

## Completion criteria

1. `python3 -m unittest discover -s engine/tests` passes, run once when all increments are done.
2. A web page and an arXiv paper, both from the local test server, are captured, converted, searched and read back, and their
   `original/` bytes match the sha256 in the manifest.
3. The search index deleted and rebuilt from the book folders gives the same results for the test queries.
4. A conversion tool that tries to open a network connection or write outside its output folder is stopped by the runner, and a
   tool that is not on the approved list is refused.
5. `wb verify` accepts the `kb` package, and the owner has installed it into a scratch project where `wb run kb search` and
   `wb run kb read` return results.
6. Increment J is optional. Either its walk-through of at least ten real document pages and three arXiv papers is recorded with
   the failures listed, or the owner has declined live fetches and the Result section says so. Either outcome completes the plan.

## Increments

### Increment A — Skeleton, config and library setup

**Outcome:** `engine/` holds a Python package `kb` with a command line `python3 -m kb`. `setup <bulk-root> <index-root>` creates a
library: an owner-only config (mode 0600) in the config directory, a marker file holding the library id in the bulk root, the
recorded device of the bulk root, a format version, and an empty index root. Before any later write it checks that the marker is
present and the device matches, and stops with the reason if not. It refuses a root that already holds another library's marker, a
root that is a symlink or has a symlink in its path, and two roots that are the same folder.
**Dependencies:** none.
**Affected areas:** `engine/kb/__init__.py`, `engine/kb/__main__.py`, `engine/kb/config.py`, `engine/kb/library.py`,
`engine/tests/test_setup.py`, `engine/README.md`.
**Steps:**
1. Write the tests first: setup on empty temporary roots, setup twice with the same id (idempotent), setup on a root with a
   different marker (refused), symlinked root (refused), same folder for both roots (refused), config file mode, a missing marker
   or a changed device (writes refused), the config directory taken from the environment variable.
2. Implement `config`, `library.setup`, the write guard and the command line.
3. Write the README section that says how to run the tests and setup.
**Verification:** `python3 -m unittest engine.tests.test_setup` passes, and the tests failed before the code existed.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#A`.

### Increment B — The book store

**Outcome:** the library can create a book with an id, a root file and a version folder. A book's payload (originals, later the
converted text) is built in an incoming area on the same volume as the bulk root, its hashes are verified against the manifest,
and it is renamed into place and marked read-only, so a payload is never half filed. The store reads a book back, checks recorded
hashes, and refuses to overwrite a filed payload. Manifests are plain JSON files written atomically (temporary file, flush,
rename). Nothing stored holds an absolute path. Later stages read only promoted payloads. Each version also has a stage state
file (found, fetched, scanned, converted, indexed; each pending, done, failed or skipped, with a reason and the tool) that is
rewritten atomically, and a stage is re-run on resume only if it is pending or failed.
**Dependencies:** A.
**Affected areas:** `engine/kb/store.py`, `engine/kb/ids.py`, `engine/kb/incoming.py`, `engine/kb/stages.py`,
`engine/tests/test_store.py`, `engine/tests/test_stages.py`.
**Steps:**
1. Write the tests first: create and read a book; a second write to a filed payload is refused; a changed file fails the hash
   check; an interruption in the incoming area (before verification, and between verification and the rename) leaves no book
   visible and the old state intact; an interruption during a manifest rewrite leaves the old manifest; a filed payload file is
   read-only; a stored manifest contains no absolute path; books are sharded by id and a shelf is a field.
2. Implement ids (random, never reused), the root file and version file fields from `book.md` ("Root details"), the incoming area
   with verify-and-rename, the read-only marking, the atomic manifest write and the hash check.
3. Write the stage-state tests first: a new version starts with `found` done and the rest pending; a stage change is written
   atomically and an interruption leaves the old state; a failed stage records its reason and is retried on resume; a done stage
   is not re-run; a stage cannot be marked done before the stage it needs. Add the crash-between-steps test: a payload is
   promoted into place and the process stops before the stage is marked done; on resume the stage finds its promoted payload,
   validates its hashes against the manifest, adopts it and marks the stage done, without overwriting or duplicating it. A
   promoted payload that fails validation marks the stage failed with the reason and is not adopted.
4. Implement `stages`, including the adoption of a promoted, valid result on resume.
**Verification:** `python3 -m unittest engine.tests.test_store engine.tests.test_stages` passes.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#B`.

### Increment C — Capture a web page

**Outcome:** `capture-url <address>` fetches the page with one GET (honest user agent, a size cap, a timeout), records the address
asked for, the final address after redirects, the retrieval date, the kept response headers and the sha256, and stores the bytes
in `original/`. A page whose final address or content hash the library already holds is not stored again. The manifest requires
only those fields and treats title, author, published date, language and canonical address as optional.
**Dependencies:** B.
**Affected areas:** `engine/kb/capture_url.py`, `engine/kb/identity.py`, `engine/tests/test_capture_url.py`,
`engine/tests/fixtures/`.
**Steps:**
1. Write the tests first, against a local server started by the test: a normal page, a redirect, a page over the size cap
   (refused with the reason), a timeout, a repeated address (no second download), a different address with identical bytes
   (stored as a sighting on the existing book, not a new book).
2. Implement the fetch, the identity keys and the duplicate checks. A stored page has `fetched` done and `scanned` pending in its
   stage state; a refused or failed fetch records `fetched` failed with the reason.
**Verification:** `python3 -m unittest engine.tests.test_capture_url` passes. No test makes a request outside the machine.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#C`.

### Increment D — Capture an arXiv paper

**Outcome:** `capture-arxiv <id>` stores the paper's PDF as the primary original and the abstract metadata (title, authors, year,
the arXiv version label) in the root file. Each arXiv version label (v1, v2) is a version of one book. Asking again for a version
held is refused before download. A new label adds a version and moves current to it, keeping the old one unchanged.
**Dependencies:** B.
**Affected areas:** `engine/kb/capture_arxiv.py`, `engine/tests/test_capture_arxiv.py`, `engine/tests/fixtures/`.
**Steps:**
1. Write the tests first, against the local test server serving a small PDF fixture and a metadata fixture in the shape of the
   arXiv export API: capture v1; capture v1 again (refused); capture v2 (new version, old kept); an id of the wrong shape (refused);
   a response that is not a PDF (refused).
2. Implement the id parser, the metadata read and the version handling. The arXiv address prefixes are a setting, so the tests
   point at the local server. A stored version has `fetched` done and `scanned` pending, as for a page.
**Verification:** `python3 -m unittest engine.tests.test_capture_arxiv` passes.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#D`.

### Increment E — The confined tool runner and the scan stage

**Outcome:** the scan stage runs before conversion: for a PDF it checks for encryption, embedded JavaScript and embedded files;
for a page it counts script elements and flags hidden text (elements hidden by inline style or the `hidden` attribute). Findings
are stored as caveats on the version and never stop filing; the stage is marked done, or failed with the reason. The scan checks
run through the same confined runner as conversion tools. A tool runs only if it is on the owner's approved list (name, exact
version, formats, order), as a child
process under a `sandbox-exec` profile that denies network and writes outside its output folder and allows reads only of its input
and the tool itself, with a time limit and an output size limit. Its output is stored under `derived/<tool>/` with the tool
name and version and carries the untrusted marker. A tool that exceeds a limit fails the stage with the reason.
**Dependencies:** B.
**Affected areas:** `engine/kb/convert_run.py`, `engine/kb/approvals.py`, `engine/kb/scan.py`,
`engine/tests/test_convert_run.py`, `engine/tests/test_scan.py`, `engine/tests/fixtures/tools/`.
**Steps:**
1. Write the tests first with fake tools: one that opens a socket (stopped), one that writes outside the output folder (stopped),
   one that reads a file outside its input (stopped), one that runs past the time limit (killed, stage fails with reason), one that
   writes past the size limit (stopped), one not on the approved list (refused), one whose version differs from the approved version
   (refused). For the scan: an encrypted PDF, a PDF with a JavaScript marker, a page with a script element and with hidden text each
   give a caveat and filing continues; a clean file gives none; a scan tool that fails marks `scanned` failed with the reason and
   the book stays filed.
2. Implement the approved-list reader (the owner-only config, refused if group- or world-writable), the profile and the runner.
   A conversion's output is written to the incoming area of increment B and promoted by rename, so an interrupted conversion
   leaves no partial `derived/` payload; a test interrupts one.
3. Stop and report if the sandbox does not deny network and the outside write in step 1; do not weaken the profile to pass.
4. When the tests of steps 1 to 3 pass and before the commit, and before increment F begins, stop and ask the owner whether to
   run the installed `security-review` module on this increment's real sandbox profile, runner and scan (untrusted input, a
   subprocess, parsing and the filesystem), with the bypasses tried on a copy. Record the owner's answer in the Result section.
   If the owner says yes, the review runs, its findings are decided and any fix gets its own regression test before the commit;
   if no, the plan goes on and the answer is recorded. Increment F's converters run under the same runner and are covered by the
   question: the owner is asked again at the end of F only if F changes the runner or the profile.
**Verification:** `python3 -m unittest engine.tests.test_convert_run engine.tests.test_scan` passes, with every denial test
failing first when the profile is replaced by an allow-all profile (the check that the tests can fail).
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#E`.

### Increment F — Converters and locators

**Outcome:** a captured web page is converted by two tools (the standard-library extractor and trafilatura) and a captured arXiv
paper by `pdftotext`, each through the runner of E. Each conversion records its tool, version, structure quality (full, partial or
flat) and its blocks. When the two web extractors differ by far in size, the book is marked partial. A locator names its
conversion (tool, version, generation), a block index and a hash of the excerpt, and is found again against the same conversion.
**Dependencies:** C, D, E.
**Affected areas:** `engine/kb/convert_html.py`, `engine/kb/convert_pdf.py`, `engine/kb/locator.py`,
`engine/tests/test_convert.py`, `engine/tests/fixtures/`, `engine/requirements.lock`.
**Steps:**
1. With the owner's approval of the plan, create `engine/.venv` and install the three pinned packages, recording hashes in
   `engine/requirements.lock`. The owner records the approved tools in the owner-only file.
2. Write the tests first, on fixtures shaped like the ten-page test: a clean document, a flat page with no paragraph tags, a
   thread whose comments one extractor drops, a script-built page with almost no text, a PDF with page breaks.
3. Implement the converters and the partial rule. The size ratio is a setting with a first value taken from the test (a ratio of
   about two), and the plan records that it rests on ten pages.
4. Implement locators and the test that a locator is found again by its own conversion and, by excerpt hash, after a different one.
5. Conversion runs only on a version whose `scanned` stage is done or failed (a scan failure does not block conversion). It marks
   `converted` done, or failed with the reason, and a failed conversion leaves the raw capture and the earlier stages intact.
**Verification:** `python3 -m unittest engine.tests.test_convert` passes under the venv.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#F`.

### Increment G — Keyword search and rebuild

**Outcome:** `index` builds an FTS5 index in the library's index folder from the converted text of every book, one row per block
with the book id, version, conversion and locator. `search <query>` returns ranked results, each with the book id, title, locator,
a short excerpt, the untrusted marker, the date the book was added, the scan caveats of the version, and how complete its source
and conversion were (full, partial or flat, and the partial flag of the extractor-size rule), so a partial extraction never
looks complete. Deleting the index and running `index` again gives the same results, including those fields, for the test queries.
**Dependencies:** F.
**Affected areas:** `engine/kb/index.py`, `engine/kb/search.py`, `engine/tests/test_search.py`.
**Steps:**
1. Write the tests first: three books across two kinds, queries that hit each, a query with FTS5 special characters (treated as
   text, never as syntax), delete and rebuild giving equal results, a book marked removed excluded, and a flagged fixture (a
   page with a script caveat and a partial conversion) whose caveat and partial status appear in the result before and after a
   rebuild.
2. Implement indexing and search with bound parameters only. Indexing covers only versions whose `converted` stage is done and
   marks `indexed` done.
3. Write the test first, then implement `process`: it advances every version through its pending or failed stages in order
   (scan, convert, index), records each outcome, and resumes after a simulated stop in the middle without redoing a done stage.
   For each stage that writes a payload (scan caveats, conversion, index), the stop is simulated between the promotion of the
   result and the update of the stage state, and resume adopts the valid promoted result as in increment B.
**Verification:** `python3 -m unittest engine.tests.test_search` passes.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#G`.

### Increment H — Read by locator

**Outcome:** `read <book> <locator>` returns a bounded excerpt around the locator (a character limit, with where the next piece is),
the untrusted marker, and a citation line of source address, retrieval date and content hash. A locator whose conversion is gone is
found by its excerpt hash against the current conversion, or reported as not found. An unknown locator kind shows its raw value.
**Dependencies:** G.
**Affected areas:** `engine/kb/read.py`, `engine/tests/test_read.py`.
**Steps:**
1. Write the tests first: a normal read, a read at the end (no next piece), a locator from a replaced conversion found by hash, a
   missing book, an unknown locator kind, and a check that the output never contains an absolute path to the library.
2. Implement the read and the citation line.
**Verification:** `python3 -m unittest engine.tests.test_read` passes.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#H`.

### Increment I — The thin workbench package

**Outcome:** a package `kb` in `package/` with a module `kb` that provides `kb:knowledge-search` and exposes the commands `search`
and `read` through a helper that calls the engine as a program on the same machine, with a size limit and a time limit on its
output. No command accepts a path, an address or a token as an argument. The helper finds the engine and the library only
through the owner-only config in `~/.config/knowledge-base/` (the same-machine host that `reading.md` allows), never through the
project's files. `wb verify` accepts the package. The owner approves and installs it into a scratch project in a terminal, and
both commands return results there. This is a narrower interface than the host service of `reading.md`: it has no network
listener, no tokens, no guests and no privacy filter, and it is for the owner's own use on this machine.
**Dependencies:** H.
**Affected areas:** `package/package.json`, `package/kb/module.json`, `package/kb/helper/kb`, `engine/tests/test_package.py`.
**Steps:**
1. Write the declaration and the helper in the shape of the stub that passed the stub gate (`kb-stub`). The helper reads the
   engine location from the owner-only config. Write the tests first: a command given a path, address or token argument is
   refused; the output contains no absolute path to the library; an oversize output is cut with the cut marked.
2. Run `wb verify` on `package/`.
3. The owner runs `wb approve` on the package and `wb install` into a scratch project. The agent stops and asks; it does not run
   these.
4. Run `wb run kb search <query>` and `wb run kb read <book> <locator>` in the scratch project and record the output.
**Verification:** `wb verify` on the package and the two `wb run` commands against a library built from the test fixtures. The
approval and install are the owner's steps and are recorded as done only when the owner says so.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#I`.

### Increment J — Loading walk-through

**Outcome:** the engine is run end to end on at least ten real document pages (no listing pages) and three arXiv papers chosen
with the owner, and what failed is written down. This increment is optional. It makes live requests to third-party sites and runs
only if the owner says so after reading the list of addresses. If the owner declines, the Result section records that and the
plan is still complete.
**Dependencies:** I.
**Affected areas:** `docs/plans/2026-11-05-first-slice-capture-search-read.md` (Result section only).
**Steps:**
1. List the addresses and ids to the owner and wait for a yes.
2. Capture, convert, index and read a passage from each. Record the count that captured, converted and read cleanly and the reason
   for each failure.
3. Rebuild the index from the book folders and compare results.
**Verification:** the recorded counts, and the rebuild comparison.
**Evidence:** one local commit with the trailer `Plan: 2026-11-05-first-slice-capture-search-read#J`, adding the walk-through to
the Result section.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changes its inputs. F changes the converter inputs that E
tests, so the E tests are rerun after F. Everything else is confirmed from its own record. The full suite
(`python3 -m unittest discover -s engine/tests`) runs once at the end, because completion criterion 1 requires it, and the risk it
covers is an increment breaking an earlier one through the shared store.

## Risks and sensitive actions

- **Untrusted input and a subprocess.** The engine parses fetched pages and PDFs with third-party tools. The confinement of E is
  the control. Step 4 of increment E is an explicit stop, after the sandbox profile and its denial tests exist and before F,
  that asks the owner whether to run the installed `security-review` module on E's real runner and scan, and records the answer.
  A review runs only when the owner asks.
- **A narrower interface than the specs.** The package of increment I is a same-machine, owner-only interface and not the host
  service of `reading.md` and `library.md`: no listener, tokens, guests or privacy filter. It must not be shared with other
  people or machines, and the host design is a later plan. Increment I is the part to defer if the owner prefers to wait for it.
- **Network.** Increments C, D and J fetch from third-party sites. Tests use a local server. J needs the owner's yes.
- **Filesystem.** The engine writes a library under a root and reads fixtures. Path handling refuses symlinks. Writes are atomic.
- **Dependencies.** Three Python packages and their dependencies are installed into an untracked virtual environment, named and
  pinned above. The owner's approval of this plan covers exactly these.
- **Sandbox.** `sandbox-exec` is deprecated by Apple. If it is removed or behaves differently, E's tests fail and conversion is
  not run.
- **The existing specs are uncommitted.** They remain so; the plan's commits touch only its own paths.
- **Test coverage of the HTML rules.** The partial rule and the size ratio rest on ten pages. A wrong ratio gives false partial
  flags, not lost data, since the raw bytes are kept.

## Review record

- Reviewer: Codex through the project's review engine (bridge `ask-codex`, model `gpt-5.6-terra`, effort medium). Key
  `plan-6f4f3c2f49488a62`. Round 1 of 3 used; the verdict was changes needed, with six findings.
- Applied: R1-F2 (each increment is reviewed and the review recorded before its commit, now stated in the assumptions), R1-F3
  (two roots and the config directory as `library.md` specifies, with the marker and device check), R1-F4 (an incoming area with
  verify and rename, read-only payloads and interruption tests, for originals and derived output), R1-F5 (listing pages are
  outside the slice and off the walk-through list), R1-F6 (increment J is optional and a recorded decline completes the plan).
- Rejected: R1-F1, because `docs/plans/README.md` allows `Candidate: none` with a reason and the project has no roadmap. The
  assumptions now say a roadmap can be written first if the owner wants the trace.
- Round 2 of 3 (changes needed, three findings), all applied: R2-F1 (the package of increment I reads the engine location only
  from the owner-only config, takes no path, address or token, and is stated to be narrower than the host service, with I named
  as the part to defer), R2-F2 (stage state in B, the scan stage in E, conversion, indexing and a resume command following the
  states in F and G), R2-F3 (a stop in E asks the owner about a security review and records the answer; at the owner's word the stop was moved from before
  any code to step 4, after the sandbox profile and its tests exist and before F).
- Round 3 of 3 (changes needed, two findings), both applied: R3-F1 (search results carry the version's scan caveats, date added and
  completeness, tested through a rebuild) and R3-F2 (resume adopts a valid promoted result after a crash between promotion and the
  stage update, tested in B and in G). The review engine reported the model of rounds 1 and 2 as `gpt-5.6-terra`, as
  `.workbench/review.json` names it, and the model of round 3 as `gpt-6.1-sol`; the cause is not established here.
- The cap of three rounds is used. The fixes of round 3 were not reviewed again. A further round needs the owner to extend the
  bound.
- Left for the owner: the approval, and whether to extend the bound for a round 4.

## Deferred work

- The unattended builder (a scheduled program, arXiv-only first), after this slice.
- Cards, themes, a model stage and the weave; the weave needs a broader library and a baseline first (`weave.md`).
- Threads, listings and script-built pages as their own shapes; non-arXiv PDFs and office files.
- Committing the existing specs and decision records.
- A larger HTML test, including a second fetch to see whether a page changes between fetches.

## Result

### Increment A — Skeleton, config and library setup (implemented and reviewed, not yet committed)

- **Done.** `engine/kb/` (`__init__`, `config`, `library`, `__main__`), `engine/tests/` (`__init__`, `test_setup`) and
  `engine/README.md`. `python3 -m kb setup <bulk-root> <index-root> [--allow-main-disk]` creates the owner-only config
  (file 600, directory 700, outside both roots; `KB_CONFIG_DIR` overrides the directory), a marker with the library id in the
  bulk root, the recorded device of the bulk root, a format version and the index root. `python3 -m kb check` is the write guard.
- **Verification as run.** `python3 -m unittest engine.tests.test_setup` from the repository root: 28 tests, OK, also with
  `-W error::ResourceWarning`. The first 20 tests failed before the code existed (the module `kb` did not import). Fifteen
  deliberate breaks of the code, made on scratch copies, were each caught by at least one test: seven for the first 20 tests, and
  eight for the fixes below, which were each tested to fail when undone.
- **Not run.** Nothing on a real unmounted volume or a real mount point: the device and main-disk checks were tested with injected
  values only. No other test suite exists. No security review was run on this increment; the plan puts that question at step 4 of
  increment E.
- **Review.** A read-only reviewer agent (`reviewer`), one exchange, recommendation: no blocking findings; seven findings, none
  blocking. It ran nothing and said so.
  - Applied: 1 (setup is not crash-safe: it now removes the files it wrote when a later step fails, so a rerun works), 2 (a stale
    temporary file or a system error: the temporary name is random, and a system error prints `failed: <reason>` with exit code 1
    and no traceback), 4 (the config is opened without following a symlink, checked on the opened file for owner and mode 600,
    and refused if its directory is writable by others), and the symlink part of 6 (the guard checks both roots for symlinks
    again, and roots that differ only in letter case count as the same folder).
  - Rejected: 5 (a repeated setup that ignores a changed `--allow-main-disk` flag): the flag is a first-setup choice, `check` is
    the guard that reads the recorded value, and the README says that a repeat changes nothing.
  - Deferred: 3 (`KB_CONFIG_DIR` lets any process redirect the config, which matters once the list of approved conversion tools
    lives in that config): record for the security-review question at step 4 of increment E, and restrict or remove the variable
    in production use before the list exists; 6, the rest (a hard-link or bind-mount alias, and a root nested inside the other,
    are not refused; the plan only asks for the same folder); 7 (the spec says setup creates the empty catalog, which is
    increment G, and shows a one-time notice that rights and legality are the owner's, which no increment lists: for the owner
    to decide).
- **Left for the owner:** the word to commit, and the decision on the one-time rights notice.
