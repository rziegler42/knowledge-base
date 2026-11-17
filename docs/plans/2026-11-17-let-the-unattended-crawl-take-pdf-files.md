# Let the unattended crawl take PDF files, behind a limit of memory and a switch

Status: Proposed
Created: 2026-11-17
Candidate: none (a correction that follows from findings: the supervised runs showed that most scholarly works that are not on arXiv or Wikipedia have a PDF as their only full text, which the crawl rejects for its type; the spec, `docs/specs/population.md`, names the conditions on which a PDF may be taken)
Specs: docs/specs/population.md

## Goal

The unattended crawl takes HTML pages only. Of the candidates that OpenAlex finds, those whose only full text is a PDF are rejected at discovery for their type (`rejected: type`), and a PDF found at fetch is refused (`pdf not safe to convert`). The spec says why and on what condition this may change: "before any PDF is taken, the sandbox gets a limit on **resident memory (the plan's `tool_rss_mb`, default 2,048; the watchdog kills the tool above it)**, and the crawl takes a PDF only up to `pdf_max_mb`"; "a stub tool that allocates past `tool_rss_mb` is killed; where the memory limit cannot be enforced the runner takes no PDF and says so in the report". Today **memory is not limited on macOS** (`convert_run`).

When this plan is done:

- the sandbox that runs the scan and the converters kills a tool whose resident memory goes past `tool_rss_mb`, and a run that cannot enforce that limit takes no PDF and says so;
- the plan has two keys, **`pdf_max_mb`** (the largest PDF the crawl takes, in megabytes; **0 means no PDF is taken**, which is the default) and **`tool_rss_mb`**; the summary the owner reads before approving shows both;
- with `pdf_max_mb` above 0 the crawl fetches a PDF through the same shared client and policy as a page (the blacklist, the address checks, the pacing, the redirects), checks that the bytes are a PDF, files it as a book, **scans it first** (a held kind holds the book, as for a page), converts it in the sandbox with the memory limit, and carries it through the index, the judgement and the card like any book;
- one switch turns it all off again with no change of code: set `pdf_max_mb` to 0 and approve the plan again.

## Scope

**Changed:** `engine/kb/convert_run.py` (the memory limit of the sandbox, for the scan and the converters), `engine/kb/crawlplan.py` and `engine/kb/crawlapprove.py` (the two keys and their line in the summary), `engine/kb/crawlfetch.py` and `engine/kb/discover.py` or `engine/kb/crawlrefill.py` (a PDF is not rejected for its type when `pdf_max_mb` is above 0), `engine/kb/crawlsteps.py` only if the convert step needs to name the type, their tests (`test_convert_run` or the module that tests it, `test_crawlplan`, `test_crawlapprove`, `test_crawlfetch`, `test_crawlsteps`, `test_crawlchain`), `docs/specs/population.md` (where it states what is built) and `README.md`.

**Not changed:** the scan's rules and hold kinds, the converters' code (`convert_pdf.py`), the judgement, the card step, the move step, the shared client's address policy, and every other plan key.

## Non-goals

- A change of what the scan or the converter looks for in a PDF. They are used as they are; the memory limit and the size limit are added around them.
- OCR, scanned PDFs, or a PDF over `pdf_max_mb`: such a PDF is rejected for its size, as the spec says.
- More books per hour. A card of a full paper takes several pieces and several minutes of the model, against about a minute for a page: the card step's own cost cap (12 pieces) stays, and the owner should expect fewer books an hour once PDFs are on.
- Turning the switch on. This plan builds it with `pdf_max_mb` at 0; setting it is the owner's edit of his plan and his approval.

## Assumptions and constraints

- The memory of a tool is read as the resident size of its process group, by polling (`ps -o rss=` for the group's processes, which macOS and Linux both have), by the watchdog that already runs outside the sandbox; a tool above `tool_rss_mb` is killed with its group, and the book is a failed try of its stage as for any tool that dies. Polling is coarse (a tool can allocate past the limit between two looks); the interval is short (a quarter of a second) and the tool's own CPU, file-size and time limits stay.
- Where a run cannot read the resident size (a platform with no `ps`, or a tool of which it gets none), the converter does not run, and **the crawl takes no PDF** and says so in the log and the report.
- A PDF is taken only if its bytes begin with `%PDF-` as well as its `Content-Type`, so a page served as a PDF and a PDF served as a page are both refused (as now for a page).
- The size limit is `pdf_max_mb` megabytes; the shared client's byte cap for a response is raised for a PDF to it and no higher.
- A PDF book carries the same `crawl_found` and `auto_filed` marks as any crawl book, goes through the same steps in the same order (scan before convert), and is held, judged and carded by the same rules; the card step's cost cap (12 pieces) bounds a long paper.
- No test uses the network, a real model, the owner's library or config. Hostile PDFs for the tests are made by the tests or are those that the scan's own tests already hold.
- Changing engine code changes the fingerprint of the approved crawl plan: the owner approves the crawl plan again afterward, which is his act.

## Completion criteria

1. A stub tool that allocates past `tool_rss_mb` is killed by the sandbox, within a second, with its group; a tool under the limit runs as before; where the size cannot be read the tool does not run.
2. `pdf_max_mb` and `tool_rss_mb` are plan keys with defaults (0 and 2,048) and bounds, are shown in the summary the owner approves, and a plan without them reads as before (PDFs off).
3. With `pdf_max_mb` at 0 the crawl behaves exactly as today for a PDF (rejected for its type, as now). With it above 0, a PDF under the limit is fetched, checked, filed, scanned, converted with the memory limit, and carried through the chain to a card; a PDF over the limit is rejected for its size; a page served as a PDF, a PDF served as a page and bytes that do not begin with `%PDF-` are refused; a hostile PDF that the scan flags is held and never converted.
4. A run that cannot enforce the memory limit takes no PDF and says so.
5. The log and the queue still compare the same for a library with a PDF book in it (the report's comparison).
6. `wb run code-work check` passes; the tests of the modules changed pass.
7. The owner has read the result.

## Increments

### Increment A — The sandbox kills a tool that uses too much memory

**Outcome:** a tool run by the sandbox cannot use more resident memory than `tool_rss_mb`.
**Dependencies:** none.
**Affected areas:** `engine/kb/convert_run.py` and its tests.
**Steps:**
1. Read `convert_run` (the sandbox, the limits, the watchdog that starts outside it and kills the group), `scan_tool` and `convert_pdf` as callers, and the tests of the sandbox.
2. Tests first: a stub tool that allocates past a small limit is killed and the error says so; one that stays under runs and its output is unchanged; the poll reads the whole group (a tool that starts a child that allocates); a tool that exits before the first look is not an error; the reader of the resident size is replaceable in the tests and a reader that fails stops the tool from running; the limit is a number in megabytes and a bad one is refused.
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest` over the tests of `convert_run` and the scan and convert modules; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-17-let-the-unattended-crawl-take-pdf-files#A`.

### Increment B — The plan keys `pdf_max_mb` and `tool_rss_mb`, shown in the summary

**Outcome:** the plan can say how large a PDF may be, and the owner sees it before he approves.
**Dependencies:** none.
**Affected areas:** `engine/kb/crawlplan.py`, `engine/kb/crawlapprove.py` and their tests; `docs/specs/population.md` (the sample plan).
**Steps:**
1. Read `crawlplan.PLAN` and how a key, its default and its bounds are declared, the summary's lines, and the tests that pin the summary's text.
2. Tests first: the two keys read with their defaults when absent; bounds (0 to a ceiling for `pdf_max_mb`, a floor for `tool_rss_mb`); a bad value is refused; the summary says "PDF files: not taken" for 0 and "up to N MB, in a tool limited to M MB of memory" otherwise; the digest changes when a value changes.
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlplan engine.tests.test_crawlapprove`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#B`.

### Increment C — The crawl takes a PDF when the plan says so

**Outcome:** with `pdf_max_mb` above 0 a PDF becomes a book that goes through the whole chain.
**Dependencies:** A and B.
**Affected areas:** `engine/kb/crawlfetch.py`, the discovery or refill code that rejects a PDF for its type, `engine/kb/crawlsteps.py` if needed, their tests, `engine/tests/test_crawlchain.py`, `docs/specs/population.md`, `README.md`.
**Steps:**
1. Read `crawlfetch` (`classify`, `PDF_REASON`, `_path_is_pdf`, the capture through the policy), `capture_url.policy_fetch` and `capture`, `webclient` (the type check and the byte cap), `discover` (where a work is rejected for its type), the scan and convert steps and `scan_tool`/`convert_pdf` for what they take, and `capture_arxiv` (which already files a PDF).
2. Tests first, on the fake network and a real sandbox with stub tools where the real ones are not needed: the cases of criteria 3, 4 and 5 (off by default; a PDF under the limit through the chain to a card; over the limit; a page served as a PDF; a PDF served as a page; bytes with no `%PDF-`; a flagged PDF held before any conversion; a run that cannot enforce the memory limit takes no PDF; the log and the queue compare the same).
3. Write the change; deliberate breaks; the `reviewer`'s reading; the Result; the spec and the README say what is built and how to turn it off.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_crawlfetch engine.tests.test_crawlsteps engine.tests.test_crawlchain engine.tests.test_crawlrefill`; the breaks; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `...#C`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end the tests of the six R1 modules, `test_crawlfetch`, `test_crawlsteps`, `test_crawlcards`, `test_crawlmove`, `test_crawljudge`, `test_crawlstate`, `test_crawlplan`, `test_crawlapprove`, the scan and convert tests and `test_crawlchain` are rerun together; `wb run code-work check` is run; a read-only check shows that no file outside "Scope" changed. **After this plan the owner approves the crawl plan again.** The first PDFs are taken under the owner's eye (a small `pdf_max_mb`, a run by hand) before the agent is left to run with it.

## Risks and sensitive actions

- **Hostile files, the scan and the converters are touched.** A PDF is the most dangerous file the crawl would take. The defences are the ones already built (the sandbox without network, the scan's hold kinds, a byte and time limit) plus the memory limit and a size limit added here, and the whole path is off by default. **The owner is asked whether to run a security review of the path once the increments are done; the plan recommends one before `pdf_max_mb` is set above 0 in an unattended run.**
- **Memory polling is coarse.** A tool can pass the limit between two looks; the CPU limit, the time limit and the file-size limit stay, and the polling interval is short.
- **Model cost.** A paper's card takes several pieces; with PDFs on, fewer books an hour are carded, and the card ceilings of the plan limit the day.
- The change of the code makes the approval of the crawl plan stale; the runs refuse until the owner approves again, which is his act.

## Review record

Empty until a review is asked for.

## Deferred work

OCR and scanned PDFs, a smarter choice between the landing page and the PDF of a work, and the PDFs of other kinds (Word, EPUB) stay for later.

## Result

Empty until work starts.
