# Fixes from the first walk-through

Status: Proposed
Created: 2026-11-06
Candidate: none (no roadmap exists; these are the findings of the first walk-through, recorded in the Result of 2026-11-05-first-slice-capture-search-read.md)
Specs: book, reading

## Goal

The first walk-through of the engine on four real sources (an essay, a Wikipedia article, a page built by scripts and an arXiv
paper) worked end to end and found four things that make the library less useful than it should be on ordinary sources. This plan
fixes them, adds the one operation needed to apply a fix to books that are already in the library, and applies the fixes to the
four books of the walk-through. When it is done:

- a page in an old encoding with no declaration (the essay) is read as the browser would read it, with no replacement characters;
- a captured web page has the title that the page gives itself, so a search result and a citation name it;
- a search hit in a long page (the essay is one block of 69,502 characters) reads from the matching passage and not from the top;
- a PDF with large pictures no longer carries the caveat "the scan could not read everything" for the pictures alone, while the
  caveat stays for a filter the scan does not read or a stream that is damaged;
- a book that was converted by an older version of a tool can be converted again by the tools now approved, and the search follows.

## Scope

- The plain extractor reads a page with no declared encoding that is not valid UTF-8 as Windows-1252.
- The plain extractor gives the page's `<title>`; the conversion stage sets the book's title from it when the book has none.
- Long blocks are indexed as several rows, each with a locator for its own place, so that a hit in a long block reads from there.
- The scan reports large image streams as their own caveat kind and keeps `scan_incomplete` for the other cases.
- A command puts the conversion, and so the index, of a book back to pending so that `process` makes them again; a tool whose script
  changed has a new version label, so that its old output is not taken for the new tool's.
- The first batch of the walk-through is converted again and the result is compared with the first run.

## Non-goals

- Reading the character set from an HTTP header. The capture keeps only some headers and none gave a charset for the essay.
- Titles from other places than `<title>` (an Open Graph title, the first heading).
- The article extractor's failure on old table-based pages; the size rule exists for it.
- Matching a query across the pieces of one long block (see increment C: for a block longer than the chunk, every word must be in
  one piece of it, and this is accepted).
- The rest of the walk-through (six more pages and two papers) and the workbench package (increment I of the first plan, deferred).
- Pushing.

## Assumptions and constraints

- The first plan, 2026-11-05-first-slice-capture-search-read, is approved and its increments A to H are committed; its Result holds the
  findings this plan answers. This plan changes code those increments committed.
- A change to a script of an approved tool (`extract_std.py`, `extract_traf.py`, `scan_tool.py`) changes its hash, so the owner puts
  the new entries in the config (`python3 -m kb describe-tool all`, then paste) before the tool runs again. Only the owner does that.
  Tests use temporary configs and do not touch the owner's config or library.
- Increments A to E are built and tested on fixtures and in temporary libraries. Only increment F uses the owner's library, and
  only with the owner's word.
- The search index is derived and can be rebuilt; a change in its format is a refusal that says to run `index`.
- Each increment is one verified, reviewed local commit. After the tests pass in increments B, C and D, the work stops and the owner
  is asked whether to run a security review of the surface (untrusted text into stored fields, the index, the scan's parser),
  once for each, and the answer is recorded.
- Nothing is pushed.

## Completion criteria

1. A page with no declared encoding that is not valid UTF-8 is read as Windows-1252, a valid UTF-8 page is unchanged, and a page
   cut at the read limit in the middle of a character is not misread (tests under the venv).
2. A captured web page's book gets the page's `<title>`, cleaned and cut, when it has no title, and a title the book already has is
   not replaced (tests).
3. A hit in a block longer than the chunk size has a locator for the chunk, `read` from it starts at the chunk, and deleting the
   index and rebuilding gives the same results (tests).
4. A PDF whose only unread streams are large images has `large_image_streams` and no `scan_incomplete`; a large stream that is not
   an image, an unknown filter or a damaged stream still gives `scan_incomplete` (tests).
5. After the tools get new version labels and a book is reset, `process` converts it again as a new generation, the old payload is
   kept, the old output is not adopted, and the index follows (tests).
6. On the four books of the walk-through, with the tools approved again by the owner: the essay has no replacement characters, each
   web page has a title, a search hit in the essay reads the matching passage, the paper has no `scan_incomplete` for its figures,
   and a rebuild of the index gives the same results. The counts are recorded.
7. Every increment has its recorded verification and review, and a break-it check of its new checks.

## Increments

### Increment A — Read a page with no declared encoding

**Outcome:** the plain extractor decodes a page that has a byte-order mark or a declared character set as before; a page with
neither is read as UTF-8 if it is valid UTF-8 (a cut in the middle of a character at the read limit is not an error) and as
Windows-1252 if it is not, with the five bytes Windows-1252 leaves undefined replaced.
**Dependencies:** none.
**Affected areas:** `engine/kb/extract_std.py`, `engine/tests/test_convert.py`, `engine/README.md`.
**Steps:**
1. Write the tests first, in the style of the existing extractor tests: a page with the dash byte 0x97 and no declaration gives an
   em-dash; Windows-1252 quotes and accented letters come out right; valid UTF-8 with no declaration is unchanged; a UTF-8 page cut
   in the middle of a character by the read limit is read as UTF-8 and not as Windows-1252; a declared character set, a byte-order
   mark and a name that is not on the list behave as before; a page of random bytes does not crash.
2. Implement `decode()`: the order is byte-order mark, declared character set on the list, UTF-8 read with an incremental decoder
   that accepts an unfinished character at the end, and Windows-1252 if that fails.
3. Update the README sentence about character sets.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_convert.StdExtractorTest engine.tests.test_convert.ExtractorFunctionsTest`
passes, and the break-it check of the new rule (each branch removed in turn) is caught.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#A`.

### Increment B — The title of a web page

**Outcome:** the plain extractor writes the page's `<title>` in `blocks.json` as an optional `title`; the conversion stage checks it
(text, cleaned, at most 300 characters) and, when the book's title is empty, sets it; the search index and the citation then show it.
**Dependencies:** A (the same script).
**Affected areas:** `engine/kb/extract_std.py`, `engine/kb/convert.py` (the check of `blocks.json`, the stage), `engine/tests/test_convert.py`,
`engine/tests/test_search.py`, `engine/tests/test_read.py`, `engine/README.md`, `docs/specs/book.md` (one sentence).
**Steps:**
1. Write the tests first: a page with a `<title>` gives it; a page with two takes the first; a title that is empty, hidden by
   hidden characters, very long, or full of markup is cleaned and cut; a page with none gives none; `parse_blocks_json` accepts
   the optional field and refuses a title that is not text; a book with a title keeps it; a book without one gets it, once; the title
   is in the search result and the citation; a title with control characters or a library folder in it is cleaned and scrubbed
   like any other.
2. Implement the extraction (the text of the first `<title>`, read as the parser gives it), the check, and `set_metadata` from the stage.
3. Stop and ask the owner whether to run a security review of this surface (text from a page into a stored field); record the answer.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_convert engine.tests.test_search engine.tests.test_read`
passes, with the break-it check of the new checks.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#B`.

### Increment C — Index long blocks in pieces

**Outcome:** a block longer than a chunk size (2,000 characters at first) is indexed as several rows, each cut at a word and each with
an `offset` locator for its own start; a hit in a long block therefore reads from the matching piece. The rule that every word of
a query must be in one row now means one piece for a block longer than a chunk: two words 3,000 characters apart in the same long
block no longer match together. The index format number is raised, and an index of the old format is refused with the
instruction to run `index`; the spec says that the search index is derived and is not a book format, so the rule that a reader
reads an older format does not apply to it.
**Dependencies:** none.
**Affected areas:** `engine/kb/index.py`, `engine/kb/search.py` (the tie order), `engine/kb/textutil.py` (the cutting of text at a word,
moved from `engine/kb/read.py` so that both use it), `engine/kb/read.py`, `engine/tests/test_search.py`, `engine/tests/test_read.py`,
`engine/README.md`, `docs/specs/book.md` (the sentence about older formats).
**Steps:**
1. Write the tests first: a block of 69,000 characters gives about as many rows as pieces and no row longer than the chunk; a word
   in the middle of it finds the row, and `read` at its locator returns text that contains the word and starts near it; short blocks
   keep their section or page locator; the pieces together cover the block with no gap or repeat; a block of one very long word is
   cut at the chunk size; two words in the same piece match together and two words in different pieces of one long block do not
   (the boundary of the new rule, tested at the edge of a piece); deleting the index and rebuilding gives identical results; an index of the old format is refused with a
   message that says to run `index`; the counts of blocks and rows are reported.
2. Move the cutting at a word into `textutil` and use it in `read` and `index`.
3. Index the pieces, make the order of ties fixed (block, then row), raise the format number, and add to the sentence of
   `docs/specs/book.md` that a reader of an older format number reads it that the search index is derived and not a book format:
   one of another format is refused with the instruction to rebuild it, and the rebuild is the owner's command.
4. Stop and ask the owner whether to run a security review of the index change; record the answer.
**Verification:** `python3 -m unittest engine.tests.test_search engine.tests.test_read engine.tests.test_textutil` passes, with the
break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#C`.

### Increment D — Large images are not an incomplete scan

**Outcome:** the scan counts the image streams that are too large to decompress within its limit, reports them as the caveat kind
`large_image_streams` with a fixed sentence and a count, and does not report `scan_incomplete` for them. `scan_incomplete` is
reported as before for an unknown filter, a damaged stream, a filter the scan does not read, and a large stream that does not
declare itself an image. The first part of each large image stream is still scanned.
**Dependencies:** none.
**Affected areas:** `engine/kb/scan_tool.py`, `engine/kb/scan.py` (it takes the kinds from the tool), `engine/tests/test_scan.py`,
`engine/README.md`.
**Steps:**
1. Write the tests first, with generated PDFs: a Flate image of 3 MB of zeros gives `large_image_streams` 1 and no `scan_incomplete`;
   a Flate stream of the same size that is not an image gives `scan_incomplete`; both in one file give both; a script hidden in
   the first part of a stream that declares itself an image is still found; an unknown filter and a damaged stream still give
   `scan_incomplete`; the count is capped and the sentence is fixed; the stage accepts the new kind and refuses an unknown one.
2. Implement the count and the new kind in the tool's vocabulary.
3. Record in the README the limit this keeps: a script placed after the first part of a very large stream that declares itself an
   image is reported only as a large image stream.
4. Stop and ask the owner whether to run a security review of the scan's parser change; record the answer.
**Verification:** `python3 -m unittest engine.tests.test_scan` passes, with the break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#D`.

### Increment E — Convert a book again

**Outcome:** `python3 -m kb reconvert [--book ID ...]` puts the `converted` and `indexed` stages of the active books named (all, if none
is named) back to pending, so that the next `process` converts them again with the tools now approved, as a new generation, and
indexes them again. The old payloads stay as they are. A scan can be put back the same way (`--scan`). A conversion or a scan whose
output was made by another version of the tool than the one approved now is not adopted. The tools whose scripts changed in A, B and D
have new version labels (the engine's version, and the revision of the article extractor's wrapper).
**Dependencies:** A, B, D (the new labels are the ones those changes need).
**Affected areas:** `engine/kb/stages.py`, `engine/kb/scan.py` (the label check), `engine/kb/__main__.py`, `engine/kb/__init__.py`
(the version), `engine/kb/convert_html.py` (the revision), `engine/tests/test_stages.py`, `engine/tests/test_convert.py`,
`engine/tests/test_scan.py`, `engine/tests/test_search.py`, `engine/README.md`.
**Steps:**
1. Write the tests first: after the label changes and a reset, `process` makes generation 2 and the record names the new label; the
   old payload is kept and not adopted; a stage that is not reset is untouched; a reset of a version that is not fetched or of a book
   that is not active does nothing; resetting `converted` also puts `indexed` back and resetting the scan puts back all three;
   the search shows the new conversion and no row of the old one; a stop between the reset and the next `process` loses nothing;
   a scan output made by another version is not adopted; the command reports what it reset.
2. Implement the reset in `stages`, the label check in the scan stage, the command, and the new labels.
**Verification:** `python3 -m unittest engine.tests.test_stages engine.tests.test_scan engine.tests.test_search engine.tests.test_read`
and `engine.tests.test_convert` under the venv pass, with the break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#E`.

### Increment F — Apply the fixes to the first four books

**Outcome:** the four books of the first walk-through are converted again with the fixed tools, and what changed is recorded.
**Dependencies:** A, B, C, D, E, and the owner's step of putting the new entries in the config.
**Affected areas:** the Result section of this plan; the owner's library (four books), with the owner's word.
**Steps:**
1. Ask the owner to run `python3 -m kb describe-tool all`, read the entries (the scripts and the versions changed) and put them in
   the config; confirm with `python3 -m kb tools` that all four are `ok`.
2. List the active books first and check that they are the four of the walk-through (`01M6RHND3BA35XENA5FJQ9GRB1`,
   `01M6RHP1R51VQ7S9TR119J8Y1G`, `01M6RHP57RZDJKWQVCG7AEAKK4`, `01M6RHP8XK1QB55KSG14JX17J0`); then run
   `python3 -m kb reconvert --scan --book <id>` for each of the four by name (the scan is included because its script changed;
   otherwise the finished scan would be kept and the new scanner would not run), and then `python3 -m kb process`, which converts
   and indexes the new generations. No separate `index` is run before `process`, because it would index the old conversions and mark
   them done. Record for each book the tools, the structure quality, the characters, the partial check, the caveats and the title,
   next to the first run, and check that each book's scan was made again (a second generation of the scan output that names the new
   version), that the old one was not reused, and that the index rows name the new conversion generations.
3. Check each of the fixes on its book: no replacement characters in the essay; a title on each web page; a search for a phrase in
   the middle of the essay reads that phrase; the paper has `large_image_streams` and no `scan_incomplete`; delete and rebuild the
   index and compare ten test queries.
4. Record the counts and anything that failed in the Result section.
**Verification:** the recorded comparison and the rebuild comparison.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-first-walk-through-fixes#F`, adding the record to the Result section.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increments A, B and D change the
scripts of tools and E changes the stage rules and the labels, so after E the tests of the files that A to D changed are run
together (`test_convert` under the venv, `test_scan`, `test_search`, `test_read`, `test_stages`, `test_textutil`), and the
whole engine suite once at the end of E, because the version number and the stage rules reach every part of the engine; the risk is
a test that names the old version or assumes a stage never goes back. Increment F's comparison confirms the fixes on real files.

## Risks and sensitive actions

- The changed scripts change the hashes of three approved tools, so the tools do not run until the owner approves the new entries.
  This is the intended behaviour of the approval, and F asks for it explicitly.
- Increment B puts text from a page into the book's title, which is shown in search results and citations. It is cleaned and cut like
  other text from outside, and the results are already marked untrusted.
- Increment C changes the format of the index; an old index is refused and rebuilt. It also narrows what a query can find in a long
  block (every word in one piece of 2,000 characters); the owner may find that too strict for some queries.
- Increment D keeps a limit: a script placed after the first part of a very large stream that declares itself an image is reported
  as a large image stream and not as a script.
- Increment E adds an operation that makes old derived items stale and new ones; the old payloads stay on disk, which costs space.
- Increment F fetches nothing; it uses the four books already in the owner's library and the tools the owner approves.

## Review record

- **Reviewer:** Codex through the review engine (bridge `ask-codex`). Rounds 1 and 2 reported the model `gpt-5.6-terra`, the
  configured one; round 3 reported `gpt-6.1-sol`. The cause of the difference was not found.
- **Rounds:** 3 of 3. Round 3 converged with no meaningful findings. A converged review is not an approval.
- **Applied (5):** R1-F1 (the walk-through must also include the scan, and check that it was made again); R1-F2 (the narrower rule for
  long blocks is stated, tested at its boundary and listed as a risk); R1-F3 (the spec's sentence about older formats is edited in
  increment C for the derived index); R2-F1 (`process` runs without an earlier `index`, and the index rows are checked for the new
  generations); R2-F2 (the four books are named by id).
- **Rejected:** none.
- **Left for the owner:** reading the plan and the word to approve it.

## Deferred work

- Reading the character set from the HTTP header, which needs the capture to keep it.
- Titles from the Open Graph tags or the first heading when a page has no `<title>`.
- The rest of the walk-through (six more pages and two papers) and the workbench package, after these fixes.
- Caching a loaded conversion while following `next`, if reading a very large book proves too slow.

## Result

Empty until work starts.
