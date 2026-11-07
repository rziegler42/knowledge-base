# Scan false alarms: ordinary figure-heavy PDFs should not say "scripts" or "incomplete"

Status: Proposed
Created: 2026-11-06
Candidate: none (a finding of the second walk-through: the scan reported false alarms on three of nine real arXiv papers; a correction that follows from a finding)
Specs: pipeline

## Goal

The PDF scan reports what a reader should know about a file, and it must never say nothing about a file it could not read (the plans
2026-11-06-first-walk-through-fixes and 2026-11-06-scan-hardening are built on that). The second walk-through, on 2026-11-06, fetched
eight real items and then, for increment A of this plan, six more papers. Of the nine real arXiv papers measured, three got an alarm
that is not true, from four causes (the measurements are in the Result of increment A):

1. **`javascript` ("The PDF contains scripts.") from three bytes that are not a script.** The pattern `/JS` is three bytes, and it turns
   up where no viewer would read it as text: (a) by chance in the raw compressed bytes of a large image (the 6.7 MB GPT-3 paper,
   arXiv 2005.14165), (b) by chance in the raw compressed bytes of a stream that the scan decoded to the end (PaLM, 2204.02311), and
   (c) **spelled by a picture**: a flat region of the colour #2F4A53 is `/JS` in three bytes repeated, so the decoded pixels of one
   ordinary image gave 24 matches (CLIP, 2103.00020, once the scan decoded it). Longer patterns (`/Launch`, `/EmbeddedFile`,
   `/Encrypt`, `/RichMedia`) do not turn up this way; `/JS` does, and `/XFA` rarely.
2. **`scan_incomplete` ("a PDF it could not read to the end") from two limits that ordinary files pass.** (a) The whole-file output
   budget of 20 MB: GPT-3 has 83 large images, each of which decodes past the per-stream limit of 2 MB; the first nine are reported
   as `large_image_streams` and the budget is then spent. (b) The count of streams: `MAX_STREAMS` is 2,000, and CLIP has 3,544
   decodable streams and no large image.

The two kinds of alarm are linked: **raising what the scan decodes to cure 2 makes 1 louder** (CLIP goes from `scan_incomplete` to
`javascript 24`), so they are cured together or not at all. An alarm that fires on ordinary files stops meaning anything. When this
plan is done, none of the nine papers is called incomplete for having many images or streams, a match of a pattern in binary data (the
bytes of an image, compressed or decoded, or of a compressed stream) is named for what it is and is never silent, a match that is
shaped like a real use stays at full strength wherever it is, and a hostile file built to cost time or memory is still stopped inside
the sandbox's 60 seconds and reported `scan_incomplete`. No detection of the earlier plans' attack corpus is lost.

## Scope

- Measure first (increment A, done up to the owner's confirmation): how often the alarms occur on real PDFs (the 60 PDFs found on this
  machine, the three papers captured earlier and the six further arXiv papers that the owner approved), where each pattern match
  sits, and why each `scan_incomplete` is said.
- Limits that ordinary files do not pass (increment B), under one resource model of three bounds: (1) the per-stream decode limit,
  2 MB, which is what makes an image "large", unchanged; (2) memory: each decoded piece is scanned as soon as it is made and only the
  match counts are kept, so the memory held is one piece and a few counters however many streams there are; (3) work: a cumulative
  limit on the bytes decoded in all and a limit on the number of streams decoded, both of which every stream counts toward (that is
  what bounds a hostile file), set from the measurements of A at sizes that a legitimate 50 MB file of large images or of many small
  streams stays under and a hostile 50 MB file does not. The rule that recognises an image (`_is_image`) no longer requires
  `/Type /XObject`, which the PDF format makes optional: an image is a stream with `/Subtype /Image` and none of the container keys
  (`/N /First /Extends /W /Size /Index`); the container-key guard against an object stream dressed as an image stays.
- Where a match sits decides its name (increment C, required, released with B): the **binary places** are the raw and the decoded
  bytes of image-shaped streams, the raw bytes of streams with an image codec (`DCTDecode`, `JPXDecode`, `CCITTFaxDecode`,
  `JBIG2Decode`), and the raw bytes of any stream the scan decoded; every other place (the file outside streams, a stream
  dictionary, an unfiltered stream, the decoded content of a stream that is not image-shaped, a stream the scan could not decode) is
  a **text place**. A match in a text place is reported as before. A match in a binary place is reported as before if it has the
  shape of a use (the twelve bytes before it are printable ASCII or white space, and the byte after it can begin a value: white space,
  `(`, `<` or a digit), and otherwise as the weaker `pattern_in_binary_data`, one caveat with the count of such matches. No match
  is dropped.
- The new scan tool is approved by the owner, the library is scanned again, and the result is recorded (increment D).

## Non-goals

- Dropping a match, or a region from the scan. A match in a binary place is named for what it is and never silent, and the guard
  against an object stream dressed as an image (the container keys) stays as it is. Nothing in this plan reduces the window of 2 MB
  per stream.
- Requiring a character after `/JS` for a match to count anywhere: the shape-of-a-use test applies only to matches in binary places,
  where tolerant viewers read nothing as text; elsewhere every spelling still counts.
- Treating the decoded content of a stream that is not image-shaped as binary (a font, an ICC profile, an embedded file): it stays a
  text place, because an object stream or an embedded document is such a stream. Chance matches there are possible (about one in
  twenty for each megabyte of random decoded bytes); A counts them on the nine papers, and the decision about them is the owner's if
  they show up.
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
- The library holds eighteen books (the twelve of the two walk-throughs and the six papers of increment A); the scan runs on them
  again in increment D with the owner's word.
- Increments B and C are one release: B alone would turn `scan_incomplete` into a louder `javascript` (increment A measured it), so
  the tool's label is raised for B and again for C, but the owner approves only the last label (increment D), and B is not put in the
  config without C.
- Each increment is one verified, reviewed local commit. After the tests pass in increments B and C the work stops and the owner is
  asked whether to run a security review of the surface, once for each, and the answer is recorded.
- Nothing is pushed.

## Completion criteria

1. None of the nine real papers measured in increment A (arXiv 1706.03762, 2005.14165, 1409.0473, 1512.03385, 1810.04805, 2010.11929,
   2103.00020, 2204.02311, 1409.1556) scans as `scan_incomplete` or with `javascript`; each caveat it does get is one of
   `large_image_streams` and `pattern_in_binary_data`, and the count of the second is recorded with the place of each match.
2. A file with a hundred large images, each past the per-stream limit, and a file with ten thousand small streams each scan with no
   `scan_incomplete` (large images give `large_image_streams` only, apart from matches of C).
3. Measured on this machine with the scan run as the sandbox runs it, by `/usr/bin/time -l` (peak resident memory) and the wall
   clock, on generated files of 50 MB each: (a) a file of large images, built at 10, 100 and 1,000 images with the total size held
   at 50 MB, scans in at most 20 seconds and its peak memory is at most 600 MB and grows by at most 10% from 10 images to
   1,000; (b) a file of streams that each expand a thousandfold is stopped in at most 20 seconds, within the same memory limit, and
   is reported `scan_incomplete`; (c) a file of as many tiny streams as fit in 50 MB is stopped or scanned in at most 20 seconds,
   within the same memory limit. Increment A measures the current scan on the same files; if a baseline is already above a number
   here, A says so and the owner sets the number at the end of A.
4. Every test of `engine.tests.test_scan` that held before still holds, and the break-it runs of the new code are all caught.
5. A match is never silent: for every pattern, a match in a text place is its own kind; a match in a binary place with the shape of a
   use is its own kind; any other match in a binary place is `pattern_in_binary_data`; and a real action placed in a binary place by
   the extents of a stream is reported under one of those names (tested with hostile files).
6. The eighteen books are scanned again with the new label and the comparison is recorded: the caveats of the books that raised no
   alarm are unchanged, and the three that did report exactly the set criterion 1 allows.

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
   in the raw bytes of a stream decoded to the end; of a large image; of an image codec; in decoded image pixels), the number of
   streams that decode past the per-stream limit and the number decoded, the output decoded in all, the time taken, and the reason of
   each `scan_incomplete`. Done for the nine papers and the sixty PDFs; the findings are in the Result.
3. Write the benchmark fixture generator as tracked test code, with a test of its own that fails first (a function of the arguments
   and a seed only; the same arguments give the same bytes). It builds two kinds of PDF of a stated size, where the size is that of
   the file on disk, within 1%: (a) **large images**: N objects, each `<< /Type /XObject /Subtype /Image /BitsPerComponent 8
   /ColorSpace /DeviceRGB /Filter /FlateDecode /Height h /Length n /Width w >>`, each stream the zlib compression at level 6 of
   seeded noise (`random.Random(seed)`) followed by zeros so that it decodes to at least 3 MB, the noise sized so that the N
   streams fill the stated size, in object order with nothing between them; (b) **expanding streams**: N objects with a plain
   `/Filter /FlateDecode` dictionary, each the zlib compression at level 6 of zeros that expand about a thousandfold, N chosen to
   fill the stated size; (c) **tiny streams**: N objects with a plain `/Filter /FlateDecode` dictionary, each the zlib compression at
   level 6 of 100 seeded bytes, N chosen to fill the stated size. The generator is run for the sizes and counts of completion
   criterion 3 (10, 100 and 1,000 images; one expanding file; one tiny-streams file), and the record gives its arguments, the seed,
   the Python and zlib versions, and the sha256 of each generated file.
4. Time the current scan on those files and, separately, the decoding and the pattern search alone (`/usr/bin/time -l` for peak
   resident memory and the wall clock, the scan run as the sandbox runs it), to set the work limit of increment B.
5. Write the record with a provenance line (what was run, with which tool versions, at which commit, and the conclusion), and
   state the numbers chosen for B (the work limit and the limit on the number of streams) and the parameters of C (the window before
   a match and the delimiters after it). Stop and ask the owner to confirm them.
**Verification:** the record is in the Result; the generator's test passes and `git status` shows only this plan and the generator
and its test changed; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#A`, adding the generator, its test and the record
to the Result section.

### Increment B — The limits that ordinary files pass, and the image rule

**Outcome:** the scan works under the three bounds of the Scope (the per-stream limit, one piece of memory, and cumulative limits on
the bytes decoded and on the number of streams, which every stream counts toward, set from A); an image is recognised without
`/Type /XObject`; and a file with many large images or many streams is not `scan_incomplete` because of them. B is released with C:
alone it turns `scan_incomplete` into a louder `javascript` (increment A measured CLIP at 24).
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py` (`scan_pdf`: the haystacks, `MAX_TOTAL_OUT`, `MAX_STREAMS`, `_is_image`, the large-image
rule), `engine/kb/approvals.py` (the label), `engine/tests/test_scan.py`, `engine/tests/test_convert.py` (`ToolVersionTest`),
`engine/README.md`, `docs/specs/pipeline.md`.
**Steps:**
1. Write the tests first and see them fail: a file with a hundred large images is `large_image_streams` only; the same file with one
   stream that is not an image among them is still `scan_incomplete` when the work limit is passed; an image with no `/Type /XObject`
   is an image to the large-image rule (a large one is `large_image_streams`), and a stream with `/Subtype /Image` and `/N` and
   `/First` is not; ten thousand small streams are not `scan_incomplete`, and a file past the stream limit is, whatever mix of
   streams brought it there; the files and limits of completion criterion 3 (the 50 MB files of large images at 10, 100 and 1,000
   images, of expanding streams and of tiny streams), built by the generator of increment A with the arguments and seed recorded
   there (the tests and the benchmark use that one generator and check the sha256 recorded in A), with runtime and peak memory
   measured as that criterion says; every match is still counted once (a pattern in the first 2 MB of an image is found; the counts
   of patterns across streams are the same as before for small files).
2. Count matches per decoded piece as it is made and drop the piece; keep the cumulative limits with the values chosen from A; change
   `_is_image`.
3. Raise the label by one with its history line, and describe the limits in the README and the pipeline spec.
4. Run the break-it check on the new code, and compare the old and new scan on the PDFs of increment A (the caveats of the files that
   did not hit a limit must be identical, apart from the images that the image rule now recognises).
5. Stop and ask the owner whether to run a security review of this surface (decompression bombs, time and memory in the sandbox, and
   the image rule: can an object stream or another container pass as an image); record the answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run engine.tests.test_bench_pdf` and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest engine.tests.test_search.CommandLineTest` pass, with the break-it check and the comparison of step 4. The wider risk is the way matches are counted, which every caveat count depends on; the comparison covers it.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#B`.

### Increment C — Where a match sits decides its name

**Outcome:** a match of a pattern is named by where it sits: in a text place or with the shape of a use, as its own kind; in a binary
place without the shape of a use, as `pattern_in_binary_data` (one caveat, with a detail that says it is usually a coincidence and was
not read as a viewer would). Nothing is dropped. The places and the shape of a use are those of the Scope.
**Dependencies:** A, B (the two are released together).
**Affected areas:** `engine/kb/scan_tool.py` (`KINDS`, the reader yielding the span of each stream's data, `scan_pdf`: the search of
the file with the spans known, the tallies), `engine/kb/approvals.py` (the label), `engine/tests/test_scan.py`,
`engine/tests/test_convert.py`, `engine/tests/test_read.py` and `engine/tests/test_search.py` (the caveat list in a result),
`engine/README.md`, `docs/specs/pipeline.md`.
**Steps:**
1. Write the tests first and see them fail, with an honest twin for each: the stored shape of the coincidence (`/JS(` in the middle of
   the deflate data of a large image) and of the picture that spells it (a flat region of #2F4A53 in a decoded image, with and
   without `/Type /XObject`) are `pattern_in_binary_data` and not `javascript`; the same bytes in a stream dictionary, in the file
   outside streams, in an unfiltered stream, in the decoded content of an object stream and of any stream that is not image-shaped
   are `javascript`; a real action dictionary (`/S /JavaScript /JS (...)`) placed inside the raw bytes of an image-codec stream, of
   an image-shaped stream and of a deflate stream, by a fake extent, keeps its own kind because it has the shape of a use; the same
   with the preceding bytes made non-printable is reported as `pattern_in_binary_data`, never silent; every pattern kind follows the
   same rule; the caveat is accepted by `scan._read_result` and shown in a search result and a read.
2. Make the reader yield the span of each stream's data, search the file as it is (with the escaped spellings of each pattern, so the
   positions are those of the file), and tally each match by place and shape; the decoded pieces are tallied as they are made. Raise
   the label by one with its history line.
3. Run the break-it check, and compare on the PDFs of increment A: the only changes are matches in binary places and the images
   recognised by the image rule.
4. Measure on the nine papers the matches in each place and how many keep full strength, and record them.
5. Stop and ask the owner whether to run a security review of this surface (the new name is a weaker label than `javascript`; can an
   attacker place a real action where it gets the weaker label, and what do the shape-of-a-use test and the places allow); record the
   answer.
**Verification:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run engine.tests.test_search engine.tests.test_read` and `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest` pass, with the break-it check and the comparison. The wider risk is a new caveat kind that the search and read code must accept; those two modules are in the run.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#C`.

### Increment D — Approve the new scan and scan the library again

**Outcome:** the owner has put the new scan entry in the config, the eighteen books are scanned again with it, and what changed is
recorded.
**Dependencies:** B and C, and the owner's step of putting the new entry in the config.
**Affected areas:** the Result section of this plan; the owner's library (eighteen books), with the owner's word.
**Steps:**
1. Print the entries (`python3 -m kb describe-tool all`), check every pinned hash against the file, that the scripts are the committed
   ones and that no readable folder is, contains or lies inside the config, the library, the index or the home folder; show the
   owner, and have the owner replace the `approved_tools` list (the helper may be used, after a dry run, with the owner's word);
   confirm with `python3 -m kb tools`.
2. Run `python3 -m kb reconvert --scan` for each of the eighteen books by id, then `python3 -m kb process`.
3. Compare each book's caveats with those before and record them with the time taken: the books that raised no alarm must be
   unchanged (apart from a changed count of `large_image_streams`, which the image rule can raise), and the three papers that did
   (GPT-3, CLIP, PaLM) must report only what completion criterion 1 allows.
4. Record the counts, and anything that said `scan_incomplete` that did not before, with the reason and what was done about it.
**Verification:** the recorded comparison; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-false-alarms#D`, adding the record to the Result section.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increment C changes the scan that B's
tests ran against, so after C the modules of B (`engine.tests.test_scan`, `engine.tests.test_convert_run`, `engine.tests.test_bench_pdf`)
are rerun once together with the comparison on the PDFs of increment A. `python3 -m kb tools` is run in increment D. A wider run (the whole engine suite) is not
planned: the changes are in the scan and in the caveat list that search and read show, and both of those modules are named.

## Risks and sensitive actions

- The scan is the control that tells the owner what a file holds. Every change here either makes it cheaper to run (B) or changes a
  name (C); neither may make it say nothing, and the plan's tests include hostile files for each.
- B changes how the limits are spent. A limit that is too large lets a hostile file cost time or memory in the sandbox; the limits are
  set from the measurements of A and tested at the 50 MB size, and the sandbox's limit of 60 seconds stays as the last bound. The
  image rule is widened (no `/Type /XObject`); the container-key guard stays, and a security review is asked about it.
- C gives a real action a weaker label if the scan misplaces it in a binary place and its bytes do not have the shape of a use. It is
  never silent, the shape-of-a-use test keeps a real dictionary at full strength wherever it sits, and a security review is asked
  about what that test allows. Pixels of a colour that spells a pattern can still keep full strength if the pixels around it look like
  syntax; A and C count how often.
- Increment A fetched six papers (owner-approved ids only) and added six books to the library; increment D rescans eighteen books and
  changes the owner's config (with the owner's word).
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

**Amendment after approval (2026-11-06).** The plan was approved at region `ee1d92f8…b011a2`. Increment A then measured nine real papers
and found what the reviewed text did not cover (Result of increment A): a third cause of `scan_incomplete` (the count of streams), a
second kind of false `javascript` (pixels that spell `/JS`, 24 times in one CLIP image), an image rule stricter than the format
(`/Type /XObject`), and that raising the decoding limits alone makes the first alarm louder. The owner asked for the plan to be
amended; the Goal, Scope, Non-goals, completion criteria, increments B, C and D, the verification and the risks were rewritten
(B takes the stream limit and the image rule; C is required and decides a match's name by where it sits and by whether it has the shape
of a use; the library is eighteen books). The owner extended the review by one round (bound 4 of a ceiling of 5, after a preview and the
owner's confirmation of the command), and **round 4** (`gpt-6.1-sol`) found no meaningful defect and no drift from the pipeline spec: the
review converged on the amended text with no findings, so none was applied or rejected. The plan reads "changed since approval" until the
owner approves it again.

## Deferred work

- The memory use of a hostile file with millions of name escapes, in the sandbox, which has no memory limit on macOS.
- The rest of the workbench package increment of the first plan.

## Result

### Increment A — Measure how often the alarms happen, and where (done, reviewed and confirmed by the owner)

- **Provenance:** run on 2026-11-06 and 2026-11-07 (UTC) on this machine with Python 3.15.0 and zlib 1.2.12, at commits 401ac55 (the
  plan as first approved) and 07c2984 (as amended); the measuring scripts are throwaway and outside the repository, as the plan
  says, and call the scan's own functions; the arXiv papers were fetched with the engine's capture (two requests each) and processed.
  Sizes in megabytes are 10^6 bytes.
- **The tracked generator** `engine/tests/bench_pdf.py` (`large_images(total, count, seed=1, zeros=3_000_000)`,
  `expanding_streams(total, zeros=2_000_000)` and `tiny_streams(total, seed=1, size=100)`) with `engine/tests/test_bench_pdf.py` (12
  tests, OK; they failed first; the break-it run on the generator is all caught but one equivalent mutant: an impossible size raises
  `ValueError` either way). Files generated at 50 MB with `large_images(50_000_000, N, seed=1)` for N = 10, 100, 1,000,
  `expanding_streams(50_000_000)` and `tiny_streams(50_000_000, seed=1)`:

  | File | Bytes | sha256 |
  |---|---|---|
  | `images_10` | 50,002,817 | `8b1fe2a2f30d3de91090fda1c59b356831a5034832bca3a6a1e8de5ed7d39a0d` |
  | `images_100` | 49,988,391 | `a7ee4e6c1a6186af14a8026b6f60e4b5d24b5d02bcb262a1d44bca5a5e59521a` |
  | `images_1000` | 50,206,882 | `802ab5cd9b34e17a0e7d0a15f3c097aba3fd9949f760403ef1c4a85f4e770c78` |
  | `expanding` | 49,999,322 | `3f7c0769e7c6a96651ed02f5ca2b20226ae5a31ee314ab3e891c6d78cde65ed0` |
  | `tiny` | 49,999,960 | `cb5666db1134b8473c1853761047177caf172b5c0dad36c5a4bcbcecbc959d85` |

  The digests hold for this zlib build only (`zlib.compress` output is not fixed across builds): B's check of them is on this
  machine, and a different zlib needs the digests recorded again. The sizes are within 1% (`images_1000` is +0.41%; the tests assert
  0.1% for 8 MB and 100 images). What the generator is not: the noise is incompressible and the zeros inflate and search faster than
  pictures do, so the cost per megabyte differs between the three image files; there is no predictor (`/DecodeParms`), which the CLIP
  image uses; and no content built to make the pattern search slow. B's benchmarks add a stream with a predictor and bytes dense in
  `/` and `#`.
- **The current scan on the generated files** (`/usr/bin/time -l`, `python3 -I -S engine/kb/scan_tool.py`, at 401ac55): 0.25 to
  0.36 s and 175 to 191 MB peak resident memory on all five, because the 20 MB output budget (and the 2,000-stream limit) stop it
  early: `images_10` gives `javascript 2` and `large_image_streams 10`; `images_100` and `images_1000` give `javascript 2`,
  `large_image_streams 10` and `scan_incomplete`; `expanding` and `tiny` give `scan_incomplete`. The `javascript 2` are chance matches
  of `/JS` in 50 MB of seeded noise. These are baselines of a scan that does not work through the whole file, so the memory bound of
  completion criterion 3 is measured in B, not here.
- **Cost:** decoding plus the pattern search is about 3 ms per decoded megabyte (inflate 0.3 ms; name unescaping and the seven patterns
  2.5 to 3.5 ms) on the generated files and on the real GPT-3 paper; the real-data rate comes from that one paper. The scan takes 7.9
  microseconds a stream on the 266,548 tiny streams (2.12 s with the stream limit raised in-process; peak 242 MB in that process, which
  also held the CLIP paper) and 104 microseconds a stream on CLIP's 3,544 (0.38 s).
- **The nine real papers** (the stored copies; "decoded" is the number of streams the scan can decode; "past" is the number of those
  that decode past the 2 MB window; "decoded MB" is the output of all decodable streams at that window):

  | Paper | Size | Caveats now | Streams | Decoded | Past | Decoded MB | Scan |
  |---|---|---|---|---|---|---|---|
  | Attention (1706.03762) | 2.22 MB | `large_image_streams 3` | 2,712 | 147 | 3 | 11.3 | 0.10 s |
  | GPT-3 (2005.14165) | 6.77 MB | `javascript 1`, `large_image_streams 9`, `scan_incomplete` | 360 | 360 | 83 | 253.2 | 0.08 s |
  | Bahdanau (1409.0473) | 0.44 MB | none | 172 | 172 | 0 | 0.8 | 0.01 s |
  | ResNet (1512.03385) | 0.82 MB | none | 72 | 71 | 0 | 1.2 | 0.02 s |
  | BERT (1810.04805) | 0.78 MB | none | 131 | 97 | 0 | 2.3 | 0.02 s |
  | ViT (2010.11929) | 3.74 MB | none | 1,109 | 852 | 0 | 9.8 | 0.61 s |
  | CLIP (2103.00020) | 6.81 MB | `scan_incomplete` | 3,611 | 3,544 | 0 | 16.3 | 0.17 s |
  | PaLM (2204.02311) | 2.71 MB | `javascript 1`, `large_image_streams 4` | 1,289 | 1,286 | 4 | 14.7 | 0.10 s |
  | VGG (1409.1556) | 0.20 MB | none | 27 | 26 | 0 | 0.6 | 0.01 s |

  Three of nine raise an alarm that is not true. *Where every match of every pattern sits* (all seven patterns counted): only `/JS`
  ever matches, and only in binary places: GPT-3 one, in the raw bytes of a large image; PaLM one, in the raw bytes of a stream
  decoded to the end; CLIP twenty-four, in the decoded pixels of one image (`/Subtype /Image`, no `/Type /XObject`, a predictor,
  567 x 567 RGB, 964,467 bytes) when the stream limit is raised (the scan as it is stops before that image). In **text places**
  (outside streams, unfiltered streams, the decoded content of streams that are not image-shaped) the nine papers have **no match at
  all**, so the chance rate there is not yet seen (about one in twenty for each random megabyte is expected). The CLIP matches are
  24 in nine runs of a repeated three bytes (the colour #2F4A53): a flat region repeats `/JS`, so the byte after a run is the next
  pixel's (the last run is followed by `/JT`).
- **The sixty PDFs found on this machine** (10.1 MB in all, the largest 2.9 MB, the slowest scan 0.06 s) hold 1,437 decodable streams
  and 22 unfiltered ones, no large image and no stream past the limit; five say `malformed` (not PDFs) and one says `javascript` for a
  match outside any stream. They say nothing about the hard case.
- **What the plan did not anticipate (measured):** (1) a third cause of `scan_incomplete`, the stream-count limit of 2,000 (CLIP has
  3,544 decodable streams); (2) a second kind of false `javascript`, pixels that spell the pattern, so that raising what the scan
  decodes makes the first alarm louder (CLIP goes from `scan_incomplete` to `javascript 24`); (3) `_is_image` requires
  `/Type /XObject`, which the format makes optional. These led to the owner's amendment of the plan (see the Review record).
- **Shape of a use** (the twelve bytes before a match printable or white space, and a byte after it that can begin a value: white
  space, `(`, `<` or a digit) on the matches in binary places of the nine papers: **none of the 26** has it. With C, all 26 become
  `pattern_in_binary_data`, three of the nine papers (GPT-3 1, PaLM 1, CLIP 24) still carry that weaker caveat, and none shows
  `javascript` or `scan_incomplete`. The "none" is not robust against another colour: a different flat colour could leave a digit or
  a space after a run.
- **Numbers proposed for B and C (for the owner to confirm):** a limit of **2,500 MB** decoded in all (about 7.5 s at 3 ms a
  megabyte; GPT-3 at the full 2 MB window decodes 253 MB, all of its 360 decodable streams; `images_1000` at the full window is about
  2,000 MB and so passes, while a file with more than 1,250 images that each decode to the window does not: the limit is a work bound,
  and such a file is `scan_incomplete` by design, which the Goal and criterion 2 do not promise against); a limit of **500,000
  streams** decoded (about 4 s at 8 microseconds; the reader allows 1,000,000 objects); the 2 MB per-stream window unchanged; memory
  held to one piece plus the file and the reader (175 to 242 MB measured, against the 600 MB of criterion 3, whose real measurement
  is B's); the shape of a use as above. A hostile file adds the stream time, the decoding time and the reader's pass (under 1 s on
  50 MB): about 4 + 7.5 + 1 seconds, inside the 20 seconds of criterion 3.
- **Open for the owner:** with C as written three of nine papers still carry a weaker caveat. The plan keeps it so that nothing is
  silent; dropping binary-place matches that have no shape of a use would silence them, and with them the (rare) real action hidden in
  image bytes behind non-printable bytes. That is the owner's decision, at the checkpoint of C.
- **Review (independent reviewer, one round):** no blocking finding; applied here: the stale test count, the superseded statements,
  the arithmetic and the meaning of the limit for `images_1000`, the source of the 242 MB, the per-paper table, the counts per place
  for all seven patterns, the CLIP runs, and the limits of the generator. Not changed: the type checks of the generator's arguments
  (a `bool` is accepted as a whole number) and the helper `streams()` in the test, which uses the reader's private function and will
  be adapted in C.
- **Confirmed by the owner (2026-11-06):** the limits of **2,500 MB** decoded in all and **500,000 streams** decoded, the 2 MB window
  unchanged, and the shape of a use as above, for increments B and C. The question of binary-place matches without the shape of a use
  stays open for the checkpoint of C (the plan's text keeps them as the weaker `pattern_in_binary_data`).
- **Done in A:** all of its steps; the commit adds the generator, its test and this record.
