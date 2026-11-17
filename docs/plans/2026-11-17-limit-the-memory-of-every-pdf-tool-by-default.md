# Limit the memory of every PDF scan and conversion by default

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from a finding: the security review of the PDF path of `2026-11-17-let-the-unattended-crawl-take-pdf-files` found that the limit of memory is given only by the crawl's own steps)
Specs: docs/specs/population.md

## Goal

The crawl's scan and convert steps give a PDF the plan's `tool_rss_mb` as a limit of memory. Any other caller of `scan.scan_version` or `convert.convert_version` gives none: the owner's `kb process` command scans and converts a PDF with no limit. The review showed that a book of the crawl that has been fetched and not yet scanned (a run ended on its time budget, the stop file or a disk floor) can be taken by `kb process`, and that a 437 KB PDF then used 1.9 GB (read from the review; the real `pdftotext` was measured); a scan-clean 8.5 KB PDF made `pdftotext` use more than 256 MB. The same holds for the PDFs the owner files himself.

When this plan is done a PDF is never scanned or converted without a limit of memory, whoever asks: with no limit given, `scan_version` and `convert_version` use a default of 2,048 MB for a PDF (the default of the plan's `tool_rss_mb`), and a caller that gives a limit (the crawl, with its plan's value) is not changed. Where the memory cannot be read the scan or the conversion of a PDF fails and says so, as it does in the crawl.

## Scope

**Changed:** `engine/kb/convert_run.py` (one constant, `DEFAULT_PDF_RSS_MB`), `engine/kb/scan.py` and `engine/kb/convert.py` (the default for a PDF), their tests (`engine/tests/test_scan.py`, `engine/tests/test_convert.py`, and `engine/tests/test_crawlsteps.py` where it pins the old call), `docs/specs/population.md` (what is built) and `README.md` (the line that says a PDF goes through `pdftotext`).

**Not changed:** the HTML paths, the crawl's steps (they give their own limit), the converters, the scan, the tools' approved entries and their timeouts, `kb/process.py`, the plan keys, and the decision of what `kb process` does with a book that a scan flagged (it converts it; that is the owner's own command and its design).

## Non-goals

- Skipping a crawl-owned book in `kb process`, or holding a flagged book there. That changes what an owner's command does and is the owner's decision.
- A faster poll, the physical footprint instead of `ps rss`, a lower converter timeout, or a page cap for PDFs (todo items of the owner).
- The kind of a book whose first capture failed (a label only).

## Assumptions and constraints

- `read_group_rss` works on this machine (macOS) and on Linux; where it does not, a PDF's scan and conversion fail closed with the text of the sandbox ("its limit of memory could not be enforced here"). The owner's own PDFs are then not converted until it works: this is a change of behaviour for the owner, and the plan names it.
- The default is the same number as the plan key's default (2,048 MB); a caller's explicit limit wins.
- No test uses the network, a real model, the owner's library or config. The tests that need the real memory kill use the existing stub tool and a patched default.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. `scan_version` and `convert_version` on a PDF with no limit given run the tool with `DEFAULT_PDF_RSS_MB`; with a limit given, with that limit; on any other kind of file, with none.
2. A stub tool that allocates past the default is killed when a PDF is scanned or converted with no limit given.
3. Where the memory cannot be read, the scan and the conversion of a PDF fail with the sandbox's text and the tool does not run; a page is unaffected.
4. The tests of the crawl's steps, which give an explicit limit, still pass unchanged.
5. `wb run code-work check` passes and the tests of the modules changed pass.
6. The owner has read the result.

## Increments

### Increment A — A PDF is scanned and converted under a limit of memory by default

**Outcome:** no caller can scan or convert a PDF without a limit of memory.
**Dependencies:** none.
**Affected areas:** `engine/kb/convert_run.py`, `engine/kb/scan.py`, `engine/kb/convert.py`, `engine/tests/test_scan.py`, `engine/tests/test_convert.py`, `engine/tests/test_crawlsteps.py`, `docs/specs/population.md`, `README.md`.
**Steps:**
1. Read `scan.scan_version` and `convert.convert_version` as they are, their `MemoryLimitTest` classes, and the callers (`process.py`, `crawlsteps._limited`).
2. Tests first, on the stub tool and the real sandbox: a PDF scanned and converted with no limit given is run with the default (a spy on `run_to_payload`, as the tests have); the default is used by a stub that allocates past a patched small default and is killed, for the scan and for the conversion; an explicit limit is passed through unchanged; a page gets none; a reader that fails fails the PDF's scan and conversion with the sandbox's text and the tool does not run, and a page is not affected. The tests that pinned "with no limit the call is exactly as it was" are changed for a PDF and kept for a page.
3. Write the change: `DEFAULT_PDF_RSS_MB = 2048` in `convert_run`; in `scan_version` and `convert_version` a PDF with `rss_limit_mb=None` gets the default. Deliberate breaks (the constant, the condition on the kind of file, the pass-through); the `reviewer`'s reading; the Result; the spec and the README say what is built.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert engine.tests.test_convert_run engine.tests.test_crawlsteps engine.tests.test_capture_arxiv`; the breaks; `wb run code-work check`. A wider run is not needed: the HTML paths are not touched, and the callers other than the crawl's are `kb process` (covered by `test_search` and `test_read`, which build PDFs through the same functions: they are added to the run).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-limit-the-memory-of-every-pdf-tool-by-default#A`.

## Verification for the plan as a whole

The one increment's verification stands. `test_search` and `test_read` are rerun with it, since they scan and convert PDFs through `process`; `wb run code-work check` is run; a read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again** (the engine code changed). The owner is asked whether to run a second look of the security review on the change; the plan recommends none, because it adds a limit and removes no check.

## Risks and sensitive actions

- **A change of behaviour for the owner's own PDFs:** they are scanned and converted with a limit of 2,048 MB, and where `ps` cannot be read they fail closed. On this machine `ps` works (the review ran it).
- **A PDF that needs more than 2,048 MB** is killed and its conversion fails; the default is generous for a paper (the review's real converter peaked at 383 MB against 256 MB on a bomb), and the owner can still pass a higher limit through the crawl's plan key.
- Polling is coarse; the limit is a bound on a hostile file, not an exact one (recorded in the PDF plan).
- The change of the code makes the approval of the crawl plan stale; the runs refuse until the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

What `kb process` does with a crawl book that is flagged, or that the crawl has not yet scanned; a faster poll or the physical footprint; the converter's timeout and a page cap for PDFs; the kind of a book whose first capture failed. All are on the owner's list or are his decisions.

## Result

### Increment A — A PDF is scanned and converted under a limit of memory by default (verified, not committed)

- **Changed:** `engine/kb/convert_run.py` (`DEFAULT_PDF_RSS_MB = 2048` and its docstring), `engine/kb/scan.py` (`scan_version`) and `engine/kb/convert.py` (`convert_version`): a PDF given no limit gets the default, a given limit wins, a page gets none; `engine/tests/test_scan.py` and `engine/tests/test_convert.py` (`MemoryLimitTest`: the two tests that pinned "no limit, no look" for a PDF now pin the default and keep it for a page; a PDF with no limit given is killed past a patched small default in the scan and in the conversion; where the memory cannot be read a PDF fails with the sandbox's text and a page is done); `docs/specs/population.md` and `README.md` (one sentence each). `test_crawlsteps.py` needed no change: the crawl still passes its own limit. Done on this machine.
- **Verification.** `test_scan`, `test_convert`, `test_convert_run`, `test_crawlsteps`, `test_capture_arxiv`, `test_search` and `test_read`: 824 tests OK (before the review's one test change); `wb run code-work check` and `git diff --check` clean. **12 single mutations of the three modules, all killed** (the constant, the kind of file, the choice between the default and a given limit, in both callers). The real `ps` and the real sandbox ran in these tests; the real converters were not run here (the security review ran them on its copy).
- **Review** (`reviewer`, one exchange): no blocking finding. **Applied:** the page half of the scan's kill test depended on a 0.3 s allocation against a 0.25 s poll and asserted only a negative; it was dropped, since the spy test pins that a page gets no limit. **Recorded, not changed:** (1) the crawl's `_limited` passes the bare function when a plan has no usable `tool_rss_mb`, so such calls also get the default: no real plan can do that (every key has a default and bounds); (2) **the plan's Risks said the owner can pass a higher limit through the crawl's plan key; that does not reach `kb process`**: for the owner's own command a PDF that needs more than 2,048 MB fails on every run, and the only way to change that is the constant; (3) a failed scan or conversion is retried by the next `kb process` (stage `failed` is not skipped); whether a memory kill leaves an output generation, and so whether `MAX_FAILED_GENERATIONS` stops the retries, was **not checked**; (4) `engine/README.md` lines 308 and 1268 describe the calls without a limit; they are not wrong and were not changed (outside Scope).
- **Not done:** the plan-as-a-whole check beyond this increment's line; a second security look (the plan recommends none); the owner's approval of the crawl plan again (engine code changed).
