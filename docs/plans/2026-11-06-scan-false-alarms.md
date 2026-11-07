# Scan false alarms: ordinary figure-heavy PDFs should not say "scripts" or "incomplete"

Status: Proposed
Created: 2026-11-06
Candidate: none (a finding of the second walk-through: the scan reported two false alarms on a real arXiv paper; a correction that follows from a finding)
Specs: pipeline

## Goal

The PDF scan reports what a reader should know about a file, and it must never say nothing about a file it could not read (the plans
2026-11-06-first-walk-through-fixes and 2026-11-06-scan-hardening are built on that). The second walk-through, on 2026-11-06, fetched
eight real items. Seven scanned as they should. The eighth, the arXiv paper 2005.14165 (a 6.7 MB PDF with about 60 large figures), got
two alarms that are not true:

1. **`javascript` ("The PDF contains scripts.") from a coincidence.** The file holds the three bytes `/JS` once, inside the compressed
   bytes of a large image stream (`...t/JS(...` in the middle of deflate data). There is no script. The scan searches the raw bytes of
   the whole file as text, so any three-byte pattern turns up by chance in random-looking data: roughly one chance in four for a
   6 MB file of compressed images, and about one in two or more for a 50 MB one, which is the size the arXiv capture allows. Longer
   patterns (`/Launch`, `/EmbeddedFile`, `/Encrypt`, `/RichMedia`) do not turn up by chance; `/JS` does, and `/XFA` rarely.
2. **`scan_incomplete` ("a PDF it could not read to the end") from a budget.** The file has about 60 large images, each of which
   decodes past the per-stream limit of 2 MB. The first nine are reported as `large_image_streams`; the scan has then decoded 20 MB
   (the whole-file budget), stops decoding, and reports that it could not account for the rest. That is honest, and it is also a
   figure-heavy paper that is merely long.

An alarm that fires on ordinary files stops meaning anything. When this plan is done, an ordinary figure-heavy PDF
is not called incomplete for having many large images (increment B), a chance `/JS` in image bytes is not called a script (increment
C, if the owner chooses it), and a hostile file built to cost time or memory is still stopped inside the sandbox's 60 seconds and
reported `scan_incomplete`. For the paper above that means, after B alone, its large images and the one `javascript` caveat that a
chance match gives; after B and C, its large images and the weaker `pattern_in_binary_data`. No detection of the earlier plans'
attack corpus is lost.

## Scope

- Measure first (increment A): how often the two alarms occur on real PDFs (the 60 PDFs found on this machine, the three captured
  papers, and further arXiv papers that the owner approves one by one), where each pattern match sits, and why each
  `scan_incomplete` is said.
- Large images stop being a reason for `scan_incomplete` (increment B), under one resource model of three bounds: (1) the per-stream
  decode limit, 2 MB, which is what makes an image "large", unchanged; (2) memory: each decoded piece is scanned as soon as it is
  made and only the match counts are kept, so the memory held is one piece and a few counters however many streams there are;
  (3) work: a cumulative limit on the bytes decoded in all, which large images **do** count toward (that is what bounds a hostile
  file), set from the measurement of A at a size that a legitimate 50 MB file of large images stays under and a hostile 50 MB file
  does not. If A shows that the worst honest file cannot stay under the work limit and the 20 seconds with a 2 MB window, the
  window of a stream that is shaped like an image (the large-image rule, known from its dictionary before it is decoded) is
  reduced to a size chosen from A; that scans less of image pixels and is the owner's decision at the end of A.
- A match in the raw bytes of binary data the scan did not read to the end is named for what it is (increment C), if the owner chooses
  that after A.
- The new scan tool is approved by the owner, the twelve books are scanned again, and the result is recorded (increment D).

## Non-goals

- Scanning less, except by the owner's decision at the end of A: no pattern is dropped, no region of a file is skipped because it
  looks like an image or is large, and the guard against an object stream dressed as an image (the container keys) stays as it is.
  The one possible exception is the reduced window for streams shaped like images described under Scope.
- Excluding the raw bytes of streams that were decoded to the end. It would not remove the alarm that was found (it sits in a stream
  that was not decoded to the end), and the raw bytes of a deflate stream can hold a stored block of plain text that a viewer reads.
- Requiring a character after `/JS` that real files have (whitespace, `(`, `<`, a digit). It would cut chance matches by about a factor
  of eleven and still match the one found (`/JS(`); tolerant viewers read more spellings than a strict rule would allow.
- The memory use of a hostile file with millions of `#xx` name escapes (a Low note of the security review of the earlier plan, older
  than that plan), authors and abstracts as fields, the HTML scan, the conversion and the index.
- Fetching anything not approved by the owner, and pushing.

## Assumptions and constraints

- The scan tool is the standard library only and runs in the sandbox on untrusted bytes with a limit of 60 seconds; every loop in it is
  bounded, and nothing taken from a file is copied into a caveat.
- Each increment that changes `engine/kb/scan_tool.py` changes its hash. The tool's label (`approvals.SCAN_VERSION`, now 0.0.5) is
  raised by one each time and a line is added to the history in `ToolVersionTest`, because a label may not be used for two texts.
  The owner approves only the last one (increment D); the tests use temporary configs.
- The arXiv capture allows a PDF of up to 50 MB and a web capture 20 MB, so those are the sizes the worst cases are measured at.
- The twelve books of the two walk-throughs are the library; the scan runs on them again in increment D with the owner's word.
- Each increment is one verified, reviewed local commit. After the tests pass in increments B and C the work stops and the owner is
  asked whether to run a security review of the surface, once for each, and the answer is recorded.
- Nothing is pushed.

## Completion criteria

1. The stored copy of arXiv 2005.14165 scans with no `scan_incomplete`, and its caveats are exactly: after increment B,
   `large_image_streams` (its large images) and `javascript` 1; after increments B and C, `large_image_streams` and
   `pattern_in_binary_data` 1 (and no `javascript`). The increment that was last done states which of the two sets applies.
2. A file with a hundred large images, each past the per-stream limit, scans as `large_image_streams` only.
3. Measured on this machine with the scan run as the sandbox runs it, by `/usr/bin/time -l` (peak resident memory) and the wall
   clock, on generated files of 50 MB each: (a) a file of large images, built at 10, 100 and 1,000 images with the total size held
   at 50 MB, scans in at most 20 seconds and its peak memory is at most 600 MB and grows by at most 10% from 10 images to
   1,000; (b) a file of streams that each expand a thousandfold is stopped in at most 20 seconds, within the same memory limit, and
   is reported `scan_incomplete`. Increment A measures the current scan on the same files; if a baseline is already above a
   number here, A says so and the owner sets the number at the end of A.
4. Every test of `engine.tests.test_scan` that held before still holds, and the break-it runs of the new code are all caught.
5. If the owner chooses increment C: a coincidence is not called a script. A match only in the raw bytes of binary data the scan
   did not read to the end is `pattern_in_binary_data`, and it is never silent.
6. The twelve books are scanned again with the new label and the comparison is recorded: the caveats of the eleven books other than
   2005.14165 are unchanged.

## Increments

### Increment A — Measure how often the two alarms happen, and where

**Outcome:** a record, in the Result of this plan, of how many real PDFs raise either alarm, where each match of each pattern sits,
and the cause of every `scan_incomplete`; the owner has confirmed the numbers that increments B and C use.
**Dependencies:** none, and the owner's approval of each further arXiv id before it is fetched.
**Affected areas:** the Result section of this plan; a fixture generator and its test in `engine/tests/` (a new file, tracked); the
owner's library (new books, if the owner approves papers).
**Steps:**
1. List the PDFs: the 60 found on this machine (the list of the earlier comparisons), the three captured papers, and the arXiv papers
   the owner approves. The draft proposes figure-heavy papers of different makers: 1512.03385, 1810.04805, 2010.11929, 2103.00020,
   2204.02311 and 1409.1556. Nothing is fetched until the owner has approved the ids.
2. With a throwaway script outside the repository that calls the scan's own functions and changes nothing, record for each PDF its size,
   its caveats, the place of each match of each pattern (outside any stream; in an unfiltered stream; in the decoded text of a stream;
   in the raw bytes of a stream decoded to the end; of a large image; of an image codec), the number of streams that decode past the
   per-stream limit, the output decoded in all, the time taken, and the reason of each `scan_incomplete`.
3. Write the benchmark fixture generator as tracked test code, with a test of its own that fails first (a function of the arguments
   and a seed only; the same arguments give the same bytes). It builds two kinds of PDF of a stated size, where the size is that of
   the file on disk, within 1%: (a) **large images**: N objects, each `<< /Type /XObject /Subtype /Image /BitsPerComponent 8
   /ColorSpace /DeviceRGB /Filter /FlateDecode /Height h /Length n /Width w >>`, each stream the zlib compression at level 6 of
   seeded noise (`random.Random(seed)`) followed by zeros so that it decodes to at least 3 MB, the noise sized so that the N
   streams fill the stated size, in object order with nothing between them; (b) **expanding streams**: N objects with a plain
   `/Filter /FlateDecode` dictionary, each the zlib compression at level 6 of zeros that expand about a thousandfold, N chosen to
   fill the stated size. The generator is run for the sizes and counts of completion criterion 3 (10, 100 and 1,000 images; one
   expanding file), and the record gives its arguments, the seed, the Python and zlib versions, and the sha256 of each generated file.
4. Time the current scan on those files and, separately, the decoding and the pattern search alone (`/usr/bin/time -l` for peak
   resident memory and the wall clock, the scan run as the sandbox runs it), to set the work limit of increment B.
5. Write the record with a provenance line (what was run, with which tool versions, at which commit, and the conclusion), and
   state the numbers chosen for B (the work limit, and whether the reduced window is needed) and the options for C with their rates.
   Stop and ask the owner to confirm them.
**Verification:** the record is in the Result; the generator's test passes and `git status` shows only this plan and the generator
and its test changed; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#A`, adding the generator, its test and the record
to the Result section.

### Increment B — Large images no longer use up the whole-file budget

**Outcome:** the scan works under the three bounds of the Scope (the per-stream limit, one piece of memory, and a cumulative work
limit that large images count toward, set from A), and a file with many large images reports them as `large_image_streams` and
is not `scan_incomplete` because of them.
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py` (`scan_pdf`: the haystacks, `MAX_TOTAL_OUT`, the large-image rule), `engine/kb/approvals.py`
(the label), `engine/tests/test_scan.py`, `engine/tests/test_convert.py` (`ToolVersionTest`), `engine/README.md`, `docs/specs/pipeline.md`.
**Steps:**
1. Write the tests first and see them fail: a file with a hundred large images is `large_image_streams` only; the same file with one
   stream that is not an image among them is still `scan_incomplete`; the files and limits of completion criterion 3 (the 50 MB
   file of large images at 10, 100 and 1,000 images, and the hostile file of streams that each expand a thousandfold), built by the
   generator of increment A with the arguments and seed recorded there (the tests and the benchmark use that one generator and
   check the sha256 recorded in A), with runtime and peak memory measured as that criterion says; every match is still counted once (a pattern in the first 2 MB of an image is
   found; the counts of patterns across streams are the same as before for small files); a file that goes past the cumulative work
   limit is `scan_incomplete`, whatever mix of streams brought it there.
2. Count matches per decoded piece as it is made and drop the piece; keep a cumulative limit on the bytes decoded in all, which
   large images count toward, with the value chosen from A; if A and the owner chose the reduced window for streams shaped like
   images, apply it before the decode.
3. Raise the label by one with its history line, and describe the budget in the README and the pipeline spec.
4. Run the break-it check on the new code, and compare the old and new scan on the PDFs of increment A (the caveats of the files that
   did not hit the budget must be identical).
5. Stop and ask the owner whether to run a security review of this surface (decompression bombs, time and memory in the sandbox);
   record the answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run` and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest engine.tests.test_search.CommandLineTest` pass, with the break-it check and the comparison of step 4. The wider risk is the way matches are counted, which every caveat count depends on; the comparison covers it.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#B`.

### Increment C — A match in binary data the scan did not read to the end is named for what it is

**Outcome:** (runs only if the owner chooses it after A; otherwise this increment is recorded as not done, with the reason) a match
of a pattern only in the raw bytes of a large image or an image codec stream, and not in any dictionary the reader read or any
decoded or unfiltered text, is reported as its own caveat, `pattern_in_binary_data`, with a detail that says it is usually a
coincidence and was not read as a viewer would; any match anywhere else is reported as before.
**Dependencies:** A, B.
**Affected areas:** `engine/kb/scan_tool.py` (`KINDS`, `scan_pdf`), `engine/kb/approvals.py` (the label),
`engine/tests/test_scan.py`, `engine/tests/test_convert.py`, `engine/tests/test_search.py` (the caveat list in a result),
`engine/README.md`, `docs/specs/pipeline.md`.
**Steps:**
1. Write the tests first and see them fail: the stored shape of the coincidence (`/JS(` in the middle of the deflate data of a large
   image) is `pattern_in_binary_data` and not `javascript`; the same bytes in a dictionary, in an unfiltered stream, in the decoded
   text of a stream and in an object the reader reads are `javascript`; a real action placed where the scan takes data to be binary
   (a fake extent, in the data of a stream with an image filter) is not silent, whichever name it gets; every pattern kind follows
   the same rule; the caveat is accepted by `scan._read_result` and shown in a search result and a read.
2. Implement the classification (a match is looked for in the places a viewer reads first, and only what remains in binary data
   takes the new name) and raise the label by one with its history line.
3. Run the break-it check, and compare on the PDFs of increment A: the only changes are matches in binary data.
4. Stop and ask the owner whether to run a security review of this surface (the new name is a weaker label than `javascript`; can an
   attacker place a real action where it gets the weaker label); record the answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run engine.tests.test_search` and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest engine.tests.test_read.ReadTest` pass, with the break-it check and the comparison. The wider risk is a new caveat kind that the search and read code must accept; those two modules are in the run.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#C`.

### Increment D — Approve the new scan and scan the twelve books again

**Outcome:** the owner has put the new scan entry in the config, the twelve books are scanned again with it, and what changed is
recorded.
**Dependencies:** B (and C, if it was done), and the owner's step of putting the new entry in the config.
**Affected areas:** the Result section of this plan; the owner's library (twelve books), with the owner's word.
**Steps:**
1. Print the entries (`python3 -m kb describe-tool all`), check every pinned hash against the file, that the scripts are the committed
   ones and that no readable folder is, contains or lies inside the config, the library, the index or the home folder; show the
   owner, and have the owner replace the `approved_tools` list (the helper may be used, after a dry run, with the owner's word);
   confirm with `python3 -m kb tools`.
2. Run `python3 -m kb reconvert --scan` for each of the twelve books by id, then `python3 -m kb process`.
3. Compare each book's caveats with those before and record them with the time taken: the eleven books other than 2005.14165 must be
   unchanged, and 2005.14165 must report exactly the set that completion criterion 1 gives for the last increment done.
4. Record the counts, and anything that said `scan_incomplete` that did not before, with the reason and what was done about it.
**Verification:** the recorded comparison; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#D`, adding the record to the Result section.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increment C changes the scan that B's
tests ran against, so after C the modules of B (`engine.tests.test_scan`, `engine.tests.test_convert_run`) are rerun once together with
the comparison on the PDFs of increment A. `python3 -m kb tools` is run in increment D. A wider run (the whole engine suite) is not
planned: the changes are in the scan and in the caveat list that search and read show, and both of those modules are named.

## Risks and sensitive actions

- The scan is the control that tells the owner what a file holds. Every change here either makes it cheaper to run (B) or changes a
  name (C); neither may make it say nothing, and the plan's tests include hostile files for each.
- B changes how the budget is spent. A budget that is too large lets a hostile file cost time or memory in the sandbox; it is set from
  the measurement of A and tested at the 50 MB size, and the sandbox's limit of 60 seconds stays as the last bound.
- C gives a real action a weaker label if the scan misplaces it in binary data. It is never silent, and the label says it was not read
  as a viewer would; the owner decides after A whether the trade is worth it, and a security review is asked about.
- Increment A may fetch papers (owner-approved ids only) and add books to the library; increment D rescans twelve books and changes
  the owner's config (with the owner's word).
- Touching untrusted input, parsing and a sandboxed subprocess is a place to look for a security surface: the owner is asked at
  increments B and C.

## Review record

Reviewed with the project's review engine (a second model, `gpt-5.6-terra` for rounds 1 and 2, `gpt-6.1-sol` for round 3): 3 rounds of
a bound of 3, and round 3 found nothing meaningful (the review converged). Every finding was checked against the plan text before
it was applied. All four were applied.

1. *Major, applied (round 1):* the budget text said both that large images stop counting and that a total cap on the bytes decoded
   stays, which could still give the false `scan_incomplete`. The plan now states one resource model of three bounds (the per-stream
   limit, one piece of memory, and a cumulative work limit that large images do count toward), and the owner decides at the end of
   increment A whether a reduced window for streams shaped like images is needed.
2. *Major, applied (round 1):* with only increment B the paper would still get one `javascript` caveat, so "large images and nothing
   else" was wrong for that path. The goal and completion criterion 1 now give the exact caveat set after B alone and after B and C,
   and the last comparison uses the set for the increment done last.
3. *Major, applied (round 1):* the time and memory checks had no method or numbers. Criterion 3 now names `/usr/bin/time -l` and the wall
   clock with the scan run as the sandbox runs it, generated 50 MB files at 10, 100 and 1,000 images with the total size held constant,
   and limits of 20 seconds and 600 MB with at most 10% growth in memory.
4. *Major, applied (round 2):* the benchmark inputs would have come from an untracked script. Increment A now writes a tracked, seeded
   generator with its own test, fixes the shapes and sizes of both kinds of file, records its arguments, seed, library versions and the
   sha256 of each file, and increment B's tests and benchmark use that same generator.

What is left for the owner: read the plan, and say whether to approve it. The plan check (`wb run code-work check`) finds no problems.

## Deferred work

- The memory use of a hostile file with millions of name escapes, in the sandbox, which has no memory limit on macOS.
- The rest of the workbench package increment of the first plan.

## Result

Empty until work starts.
