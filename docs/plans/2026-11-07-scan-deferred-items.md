# Close the four deferred items of the PDF scan

Status: Proposed
Created: 2026-11-07
Candidate: none (no roadmap exists; these are the findings that 2026-11-06-scan-false-alarms recorded and left for the owner)
Specs: pipeline

## Goal

The PDF scan (`engine/kb/scan_tool.py`) has four open items from the security review of the plan `2026-11-06-scan-false-alarms`. When this
plan is done: (1) a hostile 50 MB file of name escapes no longer takes 1.2 to 2.13 GB of memory in the sandbox, which has no memory
limit on macOS; (2) a file attachment annotation that has no `/EmbeddedFile` text still raises the `embedded_files` caveat; (3) a
match count is bounded by one stated ceiling that the scan and the reader of its output agree on; (4) a decoded stream that only begins
like zlib data by chance no longer raises `scan_incomplete`, while one that really is compressed again still does.

## Scope

- Item 1, the memory of escapes. `_unescape_names` runs `re.sub` with a function over a whole piece (the file as it is, the joined
  binary spans, each decoded piece), and the list it builds holds 30 to 90 bytes for each `#xx`. The scan unescapes and counts in
  bounded chunks instead, so the memory held is one chunk and a few counters; a match, an escape or the twelve bytes of context that
  the shape of a use looks at is never cut by a chunk edge. The output of an ASCII85 or hex decode is cut at the same 2 MB window as
  a flate decode (one stream decoding to 39 MB of `#41` gave 1.22 GB).
- Item 2, the file attachment. `/FileAttachment` and `/EF` (the key of a file specification that holds an embedded file) count as
  `embedded_files`, as `/EmbeddedFile` and `/EmbeddedFiles` do now.
- Item 3, the ceiling of counts. A count is stored up to `MAX_COUNT` (1,000,000) and a count at the ceiling means "at least that
  many". `scan._read_result` accepts counts up to the same number, in place of 10^9, so a hostile file that makes 64 million matches
  gives a number the reader and the scan agree on.
- Item 4, the zlib start. The rule that a decoded stream beginning with a zlib header is "compressed again inside" now looks at any
  valid zlib header (`_deflate_header`: a method of 8 and a check value that makes the two bytes a multiple of 31, so a smaller window
  counts too), not only the four common ones of `_ZLIB_MAGIC`, and also asks that the bytes decode as zlib data (a bounded trial
  inside the remaining file-wide allowance, charged to the work limit). Data that begins like zlib and does not decode is not
  compressed again.
- One new tool label (`kb-scan 0.0.8`), the rescan of the owner's library with it, the comparison with the scan before, and the update
  of the approved label in the owner's configuration through the helper after the owner's yes.

## Non-goals

- The "title safety" authors, abstract and category fields, and the rest of the workbench package increment: other surfaces, other plans.
- Any change to a limit of the earlier plans (streams, work units, seconds, filters) beyond what the steps name.
- A change to the caveat kinds or to how search and read show a caveat. `embedded_files` and `scan_incomplete` already exist.
- The attacker-chosen weaker name for compact actions in image extents, and the over-count at stream ends: recorded limits of the earlier
  plan, accepted by the owner.
- A memory limit in the sandbox itself (a policy of the sandbox profile, not of the scan).

## Assumptions and constraints

- Python 3.15.0 and zlib 1.2.12 on this machine, the same as the earlier plans, and the standard library only in `scan_tool.py`.
- The scan runs in `sandbox-exec` with a 60 second limit and `MAX_SECONDS` of 25; every measure here is of the scan run as the sandbox
  runs it, with `/usr/bin/time -l` for peak resident memory and the wall clock.
- The benchmark generator `engine/tests/bench_pdf.py` and its recorded digests are the source of the hostile files; new files are added
  to it with their sha256, and the digests hold for this zlib build only.
- `ToolVersionTest.HISTORY` in `engine/tests/test_convert.py` holds the sha256 of `scan_tool.py` for the current label. The label moves to
  `0.0.8` once, in increment A, and the hash is recomputed after each later edit of the file.
- The owner's personal paths and configuration are never written to a tracked file. The configuration changes only through the helper,
  after a dry run and the owner's yes.
- Every increment is test-first, with the tests seen failing for the right reason, and gets a break-it check on its new rules.

## Completion criteria

1. The peak memory of the scan on each of these is at most 600 MB, and each is scanned in at most 20 seconds, measured as the sandbox
   runs it: a 50 MB file of `#41` escapes; a 50 MB file of `#2FJS ` repeats; an image of 8 million `#2FJS ` repeats; one ASCII85 stream
   that decodes to 39 MB of `#41`; the benchmark files of the earlier plan (`images_10` to `images_1000`, `expanding`, `tiny`, the three
   hostile files), whose memory and time do not rise by more than 10%.
2. For random inputs, including inputs dense with `#`, the chunked count is equal to the count of the unchunked reference
   (`_unescape_names` then the existing tally), for the plain and the shaped (binary place) count, and a pattern or an escape that lies
   across a chunk edge is counted once.
3. A page with a file attachment annotation (`/Subtype /FileAttachment`, `/FS << /EF 5 0 R >>`) and no `/EmbeddedFile` text gives
   `embedded_files`; a PDF with none of the three gives no such caveat.
4. A file that makes more than `MAX_COUNT` matches gives a count of exactly `MAX_COUNT`; the reader accepts `MAX_COUNT` and refuses one
   more; a count below the ceiling is exact.
5. Random-start streams (4 of the 1,000 generated images begin that way) no longer give `scan_incomplete`; a stream whose decoded bytes
   are a real second zlib stream still does, with any valid zlib header (`x\x9c` and also a smaller window such as `H\x89`), and so does
   one whose trial decode is cut by its limit. The trial never takes more than what is left of the file-wide allowance.
6. The 18 books of the library, rescanned with `0.0.8`, are compared with the scan of `0.0.7`: the differences are listed and each is
   explained by one of items 2 to 4, or there are none. `python3 -m kb tools` shows every tool `ok`.
7. The spec (`docs/specs/pipeline.md`) and `engine/README.md` say what is now true.

## Increments

### Increment A — Unescape and count in bounded chunks

**Outcome:** the memory held while unescaping and counting does not grow with the number of escapes, the shape of every match is judged as
before, and the output of ASCII85 and hex is cut at the window.
**Dependencies:** none.
**Affected areas:** `engine/kb/scan_tool.py` (`_unescape_names`, `_tally`, `_tally_binary`, `_decode_chain` for the two text filters,
`scan_pdf` where it calls them), `engine/kb/approvals.py` (`SCAN_VERSION` to `0.0.8`), `engine/tests/test_scan.py`,
`engine/tests/test_convert.py` (`HISTORY`), `engine/tests/bench_pdf.py` and `engine/tests/test_bench_pdf.py` (new hostile files).
**Steps:**
1. Add to the generator the hostile files of criterion 1 that it lacks (the file of `#41`, the file of `#2FJS `, the picture of 8 million
   `#2FJS ` repeats, the ASCII85 stream of 39 MB) with their sizes and sha256 digests, and measure the current scan on each (time and
   peak memory) as the baseline; record it in the Result.
2. Write the tests first: (a) a reference (the present functions) against the chunked count on 3,000 random inputs dense with `#`, with
   patterns, escapes and shaped matches placed on and across chunk edges (with a small chunk size set for the test); (b) a pattern, an
   escape and the twelve bytes of context split exactly at the edge; (c) the ASCII85 and hex output cut at the window, with the
   stream reported as cut (`limit`), not as ok. Watch them fail.
3. Replace the whole-piece `re.sub` with an unescape-and-count over chunks of about 1 MB that are cut where no `#` lies in the last two
   bytes and that overlap by the longest pattern plus the twelve bytes of context, counting each match once by where it starts. Cut ASCII85
   and hex output at `MAX_STREAM_OUT`.
4. Move the label to `0.0.8` and record the new hash of the file in `HISTORY`.
5. Measure criterion 1 on the new files and on the earlier benchmark files, and record both tables.
6. Stop and ask the owner whether to run a security review of this surface (hostile escapes and chunk edges decide what is counted, and
   a miscounted match is a missed caveat). It runs only on the owner's yes, and a fix gets a test first and a second look.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_bench_pdf` and
`engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest` pass, with the
measurements of step 5 and a break-it check (the overlap, the edge rule, the count by start, the cut of ASCII85). The wider risk is that
every caveat count comes through this tally; the equivalence test of step 2(a) covers it.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-scan-deferred-items#A`.

### Increment B — Count a file attachment

**Outcome:** a `/FileAttachment` annotation or an `/EF` key raises `embedded_files`.
**Dependencies:** A (the tally and the label).
**Affected areas:** `engine/kb/scan_tool.py` (`_PATTERNS["embedded_files"]`), `engine/tests/test_scan.py`, `engine/tests/test_convert.py`
(`HISTORY`), `docs/specs/pipeline.md` and `engine/README.md` where they name what the caveat covers.
**Steps:**
1. Write the tests first: the annotation of criterion 3 gives `embedded_files`; `/FileAttachments`, `/EFX`, `/E F` and `/Ef` give none; the
   spellings with escapes (`/File#41ttachment`) and a match inside a picture follow the existing rules for the other patterns. Watch them
   fail.
2. Extend the pattern to `/(?:EmbeddedFiles?|FileAttachment|EF)(?![A-Za-z0-9])`.
3. Record the new hash in `HISTORY`; update the spec and README wording.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run` and
`engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest` pass, with a break-it check
of the new alternatives. The wider risk is a new count on a book that has an attachment; increment E compares the library.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-scan-deferred-items#B`.

### Increment C — Bound the count at one ceiling

**Outcome:** no count above `MAX_COUNT` is written, and the reader accepts exactly that ceiling.
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py` (where counts become caveats), `engine/kb/scan.py` (`_read_result`),
`engine/tests/test_scan.py`, `engine/tests/test_convert_run.py` if its test of the reader limit lives there, `engine/tests/test_convert.py`
(`HISTORY`), `docs/specs/pipeline.md`, `engine/README.md`.
**Steps:**
1. Write the tests first: a count past the ceiling is written as the ceiling (the generator's `hostile_matches` file shows 64.5 million);
   the reader accepts the ceiling and refuses one more, and refuses a negative, a boolean and a text count as before. Watch them fail.
2. Add `MAX_COUNT = 1_000_000` to the scan and use `min(count, MAX_COUNT)` where a count is written. The reader takes its limit from the
   same constant, in a way that does not make `scan.py` import the scan tool's code (it must not run it); the number is written in both
   places with a test that the two are equal.
3. State in the spec that a count at the ceiling means "at least that many".
4. Record the new hash in `HISTORY`.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run engine.tests.test_search
engine.tests.test_read` and the `ToolVersionTest` run pass, with a break-it check. Search and read show counts, so both are in the run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-scan-deferred-items#C`.

### Increment D — Do not call a chance zlib header "compressed again"

**Outcome:** a decoded stream is flagged as compressed again inside only when its bytes decode as zlib data (or the trial could not be
finished).
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py` (the `_ZLIB_MAGIC` test in `scan_pdf`, `_inflate`), `engine/tests/test_scan.py`,
`engine/tests/test_convert.py` (`HISTORY`), `engine/README.md` and `docs/specs/pipeline.md` where the rule is described.
**Steps:**
1. Write the tests first: the random-start cases of criterion 5 give no `scan_incomplete` (by construction: a stream that decodes to
   `x\x9c` and noise that fails to inflate); a stream compressed twice with one filter listed still gives it; a second zlib stream that is
   valid for its first block but damaged later still gives it (it decoded, so it is hidden content); a trial cut by its limit gives it;
   a real inner stream with a valid non-`0x78` header (`H\x89`, `(\x15`) gives it; chance prefixes of those headers do not; and a file
   whose first decode leaves only a small part of `MAX_TOTAL_OUT` and ends in an inner zlib header has a trial that takes no more than
   that part. Watch them fail.
2. Replace the `_ZLIB_MAGIC` test by `_deflate_header`. When it holds, run the existing bounded inflate on the decoded bytes with a
   limit of `min(MAX_STREAM_OUT, MAX_TOTAL_OUT - total)`, taking `total` after the first decode's charge. If it raises before it has
   produced any output, the start was chance and the stream is not flagged. In every other case it is flagged. Add the trial's output
   to `total` before the next stream, as any other decode.
3. Record the new hash in `HISTORY`.
4. Stop and ask the owner whether to run a security review of this surface (it removes a case that raised `scan_incomplete`, and a
   missed one is a script that is not looked at). It runs only on the owner's yes.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_bench_pdf` and the
`ToolVersionTest` run pass, with a break-it check of the three branches of the trial. The wider risk is that a real hidden second
compression stops being reported; the tests of step 1 cover each shape of it.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-scan-deferred-items#D`.

### Increment E — Rescan the library and approve the label

**Outcome:** the library is scanned with `0.0.8`, the changes against `0.0.7` are listed and explained, and the owner's configuration
approves `0.0.8`.
**Dependencies:** A, B, C and D.
**Affected areas:** the plan's Result; the owner's configuration (not tracked, not committed); the stages of the owner's books.
**Steps:**
1. Snapshot the caveats of every book, show the owner the dry run of the configuration change that moves the approved `kb-scan` label to
   `0.0.8`, and write it with the helper only on the owner's yes.
2. Run `reconvert --scan --book <id>` for each book and `process`, as in the earlier plan, and snapshot again.
3. Compare. Every difference is listed with the item (2, 3 or 4) that explains it. An unexplained difference stops the plan.
4. Run `python3 -m kb tools` and read that every tool is `ok`.
**Verification:** the recorded comparison; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** the one local commit of the Result, with the trailer `Plan: 2026-11-07-scan-deferred-items#E`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. B, C and D each change the file that A's
tests and memory measurements ran against, so after D the modules of A (`engine.tests.test_scan`, `engine.tests.test_bench_pdf`) are
rerun once together, and the memory table of criterion 1 is measured again on the final file for the escape files and the benchmark
files. `python3 -m kb tools` is run in increment E. A wider run (the whole engine suite) is not planned: the changes are in the scan, in
the limit of the reader of its output, and in the counts that search and read show, and the modules for those are named.

## Risks and sensitive actions

- The scan reads untrusted PDFs in a sandbox, so a change to how matches are counted is a security surface: a miscounted match is a
  missed caveat. A and D ask the owner about a security review; B and C do not change what input reaches a privileged use.
- Chunk edges are a new place for a match to be lost or counted twice. The equivalence test against the present functions on random
  inputs, with small chunks, is the guard.
- Item 4 removes a case that raised a caveat. The rule keeps every case that decodes, so hidden content still raises it; the risk is a
  shape the tests miss.
- The configuration change is outward-facing to the owner's setup: it is made only by the helper, after a dry run and the owner's yes,
  and its backup is kept by the helper.
- No fetch, no push and no network are part of this plan. A push needs the owner's separate word.

## Review record

- **Reviewer:** `gpt-5.6-terra` through the review engine (bridge `ask-codex`), 1 round of a bound of 3. Verdict: changes needed, two
  major findings, both checked against the code and applied.
- **Applied:** (1) the trial inflate of increment D is limited by what is left of the file-wide allowance and added to the total
  (scope item 4, criterion 5, D steps 1 and 2). (2) The rule used four fixed zlib headers while `_deflate_header` already accepts any
  valid one: D now uses it with the trial, so a real inner stream with another window size is still reported and chance prefixes are not.
- **Rejected:** none.
- **Left for the owner:** whether to approve the plan as it stands or to ask for a second round.

## Deferred work

- The authors, abstract and category fields of the title-safety plan, and the rest of the workbench package increment.
- The attacker-chosen weaker name for compact actions in image extents, and the over-count at stream ends: accepted limits.

## Result

### Increment A — Unescape and count in bounded chunks (done, reviewed and committed)

- **What was done:** `_unescape_names` works in pieces of `_CHUNK` (1 MB) and joins the results; a piece is cut before a `#` within its last
  two bytes, so no escape is split, and a piece with no escape is kept as a view, not a copy. The output of ASCII85 and ASCIIHex is cut at
  the window and reported as `limit`. The label is `kb-scan 0.0.8`. The generator has three new files (`escape_text`, `escape_image`,
  `ascii85_escapes`) with tests.
- **Differences from the plan text (for the owner):** (1) the plan says the scan "counts in bounded chunks" with overlapping pieces. The
  scan unescapes in chunks and then counts the whole unescaped text with the unchanged tally. No match, escape or context is ever split, so
  overlap and counting by start are not needed, and every count equals that of the whole by construction. The memory held is the input, the
  unescaped output and one piece's substitution list, so it grows with the file (about a byte per byte), not with the number of escapes; the
  measured results meet criterion 1. (2) Criterion 2 is tested as equality of the unescaped bytes with those of the whole-text
  substitution (1,500 random `#`-dense inputs, piece sizes 4, 5, 7 and 16, plus every cut position of an escape), not as 3,000 counts.
  (3) An ASCII85 or hex stream that decodes to more than 2 MB is now `scan_incomplete`, as a deflate stream is; the 39 MB file had no
  caveat before.
- **Provenance:** run on 2026-11-07 on this machine with Python 3.15.0 and zlib 1.2.12, at commit 88d45ed plus the uncommitted changes of
  this increment; `python3 -I -B engine/kb/scan_tool.py` under `/usr/bin/time -l`.
- **Files (sha256, this zlib build):** `esc_text_41` 49,999,999 bytes `18233d14b62e7f65d55a7629d18541e8aecac232bff727bf574c8232cb109948`
  (`escape_text(50_000_000, b"#41")`); `esc_text_js` 49,999,999 `ac97e608afe3b41bea98e01871eb12b2141a115c90aa24aed73b28f911b56e20`
  (`escape_text(50_000_000, b"#2FJS ")`); `esc_image_js` 48,000,198 `708a31ae71111bd214b134087a519fca287acd7c6332af01e36f8b40e07ae672`
  (`escape_image(8_000_000, b"#2FJS ")`); `esc_a85_41` 48,750,122 `c3b1fa06d7171ffe33329e40653333c8cc10b61c88d267e6d397ae0f82dbb463`
  (`ascii85_escapes(13_000_000, b"#41")`, 39 MB decoded).
- **Measurements (time / peak memory), before (0.0.7) and after:**

  | File | Before | After |
  |---|---|---|
  | `esc_text_41` | 5.0 s / 1.55 GB | 4.3 s / 173 MB |
  | `esc_text_js` | 4.4 s / 1.85 GB | 3.6 s / 230 MB |
  | `esc_image_js` | 5.6 s / 1.80 GB | 4.9 s / 299 MB |
  | `esc_a85_41` | 4.2 s / 1.40 GB | 0.5 s / 272 MB (now `scan_incomplete`) |
  | `images_10` | 0.46 s / 337 MB | 0.43 s / 335 MB |
  | `images_100` | 1.11 s / 313 MB | 1.12 s / 292 MB |
  | `images_1000` | 8.0 s / 318 to 324 MB | 7.9 s / 296 MB |
  | `expanding` | 8.9 s / 181 MB | 8.1 s / 181 MB |
  | `tiny` | 3.8 s / 331 MB | 3.8 s / 330 MB |
  | `hostile_predictor` | 11.9 s / 205 MB | 11.1 s / 204 MB |
  | `hostile_escapes` | 5.1 s / 203 MB | 4.9 s / 208 MB |
  | `hostile_nested` | 7.0 s / 179 MB | 7.1 s / 180 MB |

  The counts of the four new files are those of 0.0.7 (`javascript` 8,333,317 and 8,000,000 for the two with scripts; none for the
  others) except the added `scan_incomplete`. Two first attempts raised memory on files with no escapes (+54%) and on the nested file
  (+27%), from copying the pieces; keeping a piece with no escape as a view removed it, and the table is of the final file.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_bench_pdf` (212 tests,
  OK) and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest` (4, OK); the hash
  in `HISTORY` is that of the final file. **Break-it:** three mutations of the new code (a window of one byte, no cut rule, the ASCII85 limit
  off by one) each failed a test; the third survived at first, so a test of the limit plus one was added. **Not run:** the rest of the
  engine suite; the security review (below).
- **Review (independent reviewer, one round):** no blocking finding. Not blocking, all applied or recorded here: the plan wording against the
  implementation (recorded above, the plan text unchanged because editing it needs a new approval); the test is of output equality (above);
  `a85decode` and `fromhex` still build the whole decode before the cut, so their transient memory is a few times the input (it is inside
  the measurement of `esc_a85_41`); bookkeeping (this record).
- **Security review (step 6), kept in place:** recommended against (the unescaped bytes equal those of the whole-text substitution, so no count can differ,
  and the review found no new exposure); the owner said to commit and go on, so none was run. The plan asks again at the end of D.

### Increment B — Count a file attachment (done, reviewed and committed)

- **What was done:** the `embedded_files` pattern is `/(?:EmbeddedFiles?|FileAttachment|EF)(?![A-Za-z0-9])`. Three tests in `PdfScanTest`: the
  attachment cases (an annotation with a file specification, 2; the annotation alone, 1; a file specification alone, 1; escaped name and key,
  1 each; with the older spelling too, 2), the near misses (`/FileAttachments`, `/FileAttachmen`, `/EFX`, `/Ef`, `/E#20F`, `/EF2`, `/EFF`,
  `/E F`: none), and the binary places (a bare `/EF` and `/FileAttachment` in an unfiltered picture give `pattern_in_binary_data` 2; shaped
  ones give `embedded_files` 2). The first two failed before the change (no caveat on the attachment); the third was added after the review
  and passes by construction, as every pattern goes through the same shape check. The label stays `0.0.8` (never approved or released); the
  hash in `HISTORY` is that of the final file. `docs/specs/pipeline.md` and `engine/README.md` say "embedded files" and name no pattern, so no
  wording changed.
- **Provenance:** run on 2026-11-07 on this machine with Python 3.15.0, at commit bbb6e0e plus the uncommitted changes of this increment.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run` (257 tests
  before the picture test was added; OK) and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest
  engine.tests.test_convert.ToolVersionTest` (4, OK). **Break-it:** three mutations (without `EF`, without `FileAttachment`, without the name
  boundary) each failed a test. **Not run:** the library comparison (increment E); the rest of the engine suite.
- **Review (independent reviewer, one round):** no blocking finding. Applied: the missing picture test. Recorded, not changed: the name boundary
  `(?![A-Za-z0-9])` lets `/EF_x` or `/EF-x` match, as it does for every other pattern; `/EF` can match by chance in a decoded font or object
  stream at a very low rate (the reviewer's estimate is about 0.05 a megabyte of random binary, less than for `/JS`); a normal attachment
  now counts 2 or 3 (one for each name), which increment E's comparison will show.

### Increment C — Bound the count at one ceiling (done, reviewed and committed)

- **What was done:** `scan_tool.MAX_COUNT = 1_000_000`; `caveat()` writes `min(count, MAX_COUNT)`, and every caveat of the tool (PDF and HTML)
  goes through it. `scan._read_result` accepts `0 <= count <= MAX_COUNT` (was 10^9); `scan.py` holds its own copy of the number because it
  must not run the tool's code, and a test holds the two equal. `docs/specs/pipeline.md` and `engine/README.md` each say that a count stops at
  1,000,000 and means "at least that many". `read.py` and `store.py` still accept stored counts up to 10^9: looser than the scan's gate,
  which runs first, so nothing was changed there.
- **Tests:** a writer test (1, ceiling - 1, ceiling, ceiling + 1 and 64.5 million, for every kind) and a reader test (accepts the ceiling,
  refuses the ceiling + 1 and 10^9) were written first and failed (no `MAX_COUNT`). Four existing tests that expected a count above one
  million now expect the ceiling (3 and 5 million matches, and the two binary-place cases, now `max(...) == MAX_COUNT`).
- **Provenance:** run on 2026-11-07 on this machine with Python 3.15.0, at commit 056d770 plus the uncommitted changes of this increment.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run
  engine.tests.test_search engine.tests.test_read` (427 tests, OK; the one failure of the first run, a binary-place test that expected
  more than a million, was the old bound and is fixed) and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest
  engine.tests.test_convert.ToolVersionTest` (4, OK); the hash in `HISTORY` is that of the final file. After the review the binary-place
  assertion was tightened and `PlacesTest` rerun (15, OK); the full run was not repeated for it. **Break-it:** three mutations (ceiling
  one too high, reader refusing the ceiling, reader back at 10^9) each failed a test. **Not run:** the library comparison (increment E).
- **Review (independent reviewer, one round):** no blocking finding. Found sound by reading: no code assumes a count above one million or an
  exact count; every writer goes through `caveat()`; a capped kind cannot hide or lower another kind. Applied: the weak sum in the
  binary-place test. Left for E: a book scanned with 0.0.7 may hold a count above one million in its stored caveats; those are read by
  `read.py` and `store.py` (both accept it) and are replaced by the rescan.

### Increment D — Do not call a chance zlib header "compressed again" (done, reviewed, security reviewed and committed)

- **What was done:** `_ZLIB_MAGIC` (four fixed headers) is gone. In `scan_pdf` a flag `again` is true when the decoded bytes begin with any valid
  zlib header (`_deflate_header`) and `_compressed_again` does not call the start chance. The trial gives zlib the first 4,096 bytes and asks
  for at most `min(16, room)` bytes, where `room` is what is left of `MAX_TOTAL_OUT` after the first decode was charged; if zlib raises within
  those bytes the start is chance. A trial that gives its bytes, stops for want of input, or has no room (`room <= 0`: nothing is tried) is
  "again". The flag is used in the two places the old rules were: the picture test (was `not _deflate_header(out)`, so a large image that
  only begins like a header is a large image) and `elif state != "ok" or again` (was `out[:2] in _ZLIB_MAGIC`). The bytes read and tallied do
  not depend on it, only which caveat is raised. `engine/README.md` has one sentence on the rule.
- **Differences from the plan text (for the owner):** (1) the plan says the start is chance if zlib "raises before it has produced any
  output"; the trial uses 16 bytes, because of 800 random 100-byte inputs with a valid header 36 got through the first byte and 3 through
  sixteen. A real inner stream that fails inside its first 16 output bytes (or asks for a preset dictionary, which zlib refuses at once)
  is called chance. (2) Two older tests encoded the old rule and were rewritten: a large image of a header plus zeros is now a large image
  (`large_image_streams`), and the incomplete cases use a real inner zlib stream of each window size (9 to 15 bits).
- **Provenance:** run on 2026-11-07 on this machine with Python 3.15.0 and zlib 1.2.12, at commit d7191fe plus the uncommitted changes of
  this increment.
- **Tests:** `ChanceHeaderTest` (five tests: the trial itself, a large image that only begins like a header, other content that does,
  content compressed again inside for each window size whole, damaged at the end and cut short, and the room) failed before the change and
  pass. The ten headers of the tests include one that asks for a preset dictionary.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_bench_pdf` (222 tests, OK;
  after the last two edits, a dictionary header in the tests and a blank line, only `ChanceHeaderTest` was rerun, 5 OK) and
  `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest` (4, OK); the hash in
  `HISTORY` is that of the final file. **Break-it:** five mutations (an error counted as "again"; no byte counted as chance; a room of zero
  allowed; four fixed headers only; the trial ignoring the room) each failed a test. The charge of the trial (`total += used`, at most 16
  units) is not tested and is equivalent for any real file. **Not run:** the rest of the engine suite; the library comparison (E).
- **Measurements:** `images_1000` went from 996 large images plus `scan_incomplete` (and `pattern_in_binary_data` 3) to 1,000 large images
  with no `scan_incomplete` (`pattern_in_binary_data` 13: the `/EF` of B matching in the noise, also 4 to 8 on `images_100`). The generated
  `tiny` file (about 330,000 random streams of 100 bytes) still ends `scan_incomplete`: 6 of 525 trials answered "again" (the old rule would
  give about 22, from 27 in 400,000 random starts); with a trial of one byte the rate was 36 in 400,000, higher than before, which is why
  the trial is 16 bytes. Times and memory are those of the earlier table (`images_1000` 7.9 s / 326 MB, `tiny` 3.8 s / 329 MB,
  `hostile_predictor` 11.1 s / 204 MB, `expanding` 8.1 s / 182 MB, `hostile_nested` 7.0 s / 180 MB, `hostile_escapes` 5.0 s / 208 MB).
- **Review (independent reviewer, one round):** no blocking finding. It found the `again` flag cannot hide content (only which caveat
  appears changes), `room` correct, no test wrongly encoding the new rule, and nothing else relying on `_ZLIB_MAGIC`. It named one
  exposure for the owner's security question: an inner stream built to fail inside its first 16 bytes is called chance, and a lenient
  decoder (one that keeps the output before an error, ignores a bad check value or resynchronises) could read more of it than zlib; no
  viewer decodes a second layer when one filter is listed, and what is hidden before the failure is under 16 bytes. Applied: a header with a
  preset dictionary in the tests, and the blank lines before `MAX_DICT`.
- **Security review (owner said yes; independent, on a copy, Python 3.15.0 and zlib 1.2.12; no real PDF reader was available, so every claim
  about lenient decoders is a model):** no way found to hide content from a strict zlib reader; two Low findings. **Low 2, fixed:** the
  trial was charged its output (none for empty blocks) while it reads up to 4 KB of input: 20,000 tiny streams of empty blocks took 4.8 s
  against 0.56 s under the old rule (about 212 microseconds a trial, 15 times what was charged). It now costs `TRIAL_UNITS` (20) units for
  each input byte, so about 29,000 such streams fill the allowance, about 7 s; a test written first failed (fifty streams with a start that
  is chance did not exhaust a small allowance) and passes; hash of `HISTORY` renewed; `test_scan` and `test_bench_pdf` rerun (223, OK) and
  `ToolVersionTest` (4, OK). The fix has no second look yet. **Low 1, waits for the owner:** an inner stream that zlib rejects inside its
  first 16 output bytes is now called chance for every header, where the old rule called it "again" for the four common headers
  (`78 01`, `78 5E`, `78 9C`, `78 DA`). Reachable only through a reader that decodes a second layer although one filter is listed (a
  dictionary the scan reads differently than the reader does, or a reader that guesses) and is more lenient than zlib (a bad stored length
  check, an invalid distance, a preset dictionary ignored, a resynchronisation); none is known. The new rule also closes the old gap that
  any other header (`68`, `28` and so on) was clean even when the inner stream was real. The smallest correction is a floor: the four common
  headers stay "again" whatever the trial says. It would keep about 27 of 36 chance survivors per 400,000 random starts (the old plain-stream
  rate), would still remove the false alarm of large images (any other header), and contradicts the plan's criterion 5 for `x\x9c`
  followed by bytes that do not decode, so it needs the owner's approval of an edited plan. Also noted by the reviewer, unchanged and older:
  a preset dictionary or a window above 15 bits is not flagged.
- **Owner's decision on Low 1:** accept as a recorded limit (the owner said to go with the recommendation); the plan text is unchanged.
- **Second look at the fix of Low 2 (independent security reviewer, on a copy):** no bypass. Measured through the real `scan_pdf` and
  `/usr/bin/time -l python3 -I -B`: the hostile file of 80-byte streams (each 78 9C plus 4,096 bytes of empty dynamic blocks) takes 4.8 s at
  3 MB, and 7.2 to 7.4 s from 10 MB to 50 MB (peak 37 to 184 MB, `scan_incomplete`), stopped by the allowance after about 29,000 trials, as
  predicted; with the charge off the same 60,000-stream file took 14.9 s. The worst cost of one trial over the shapes tried (empty dynamic
  blocks, large and deep code tables, fixed blocks, stored blocks, long matches, random bytes) is 54 ns for each input byte against a charge
  of 20 units (about 60 ns), a margin of about 10%; a unit measured 2.9 ns against the 3 ns assumed. The charge cannot be skipped (one call
  site, applied to `total`, never negative; a refused trial is "again"). **Low, applied:** `TRIAL_UNITS` is 40 (twice the worst shape
  measured), for margin against another zlib or machine; the trial test and `HISTORY` were renewed, and `ChanceHeaderTest` rerun (6, OK).
  Not tested: another zlib (zlib-ng) or machine; an exhaustive search for the costliest deflate stream.
- **Left for the owner:** nothing for D.
