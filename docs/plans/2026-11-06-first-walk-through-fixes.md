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

### Increment A — Read a page with no declared encoding (committed as 3314480d3464c0dcec7239c2bfbddc2f662775f9, not pushed)

- **Changed:** `engine/kb/extract_std.py` (`decode()`), `engine/tests/test_convert.py` (4 new tests, `import random`), `engine/README.md`.
- **Rule:** byte-order mark, then a declared charset on the list (as before), then strict UTF-8, where an incomplete last character (the
  read limit) still counts as UTF-8, and otherwise Windows-1252 with undefined bytes replaced.
- **Verification run:** `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ExtractorFunctionsTest
  engine.tests.test_convert.StdExtractorTest` (Python 3.15.0): 25 tests, OK. The 4 new tests failed first (the dash byte 0x97 came out
  as a replacement character). Break-it run on the file with a restore: removing the Windows-1252 fallback, the cut-character tolerance,
  the strict attempt, or sending a declared charset to the wrong codec was each caught; dropping an end-of-data check was an
  equivalent change (Python reports "unexpected end of data" only at the end), so that check was removed. Not run: the rest of
  `test_convert` (it does not use `decode`); a search of the tests found no other one that feeds the plain extractor invalid UTF-8.
- **Review:** independent `reviewer` agent, 1 exchange, no blocking findings, no security risk found. Applied: the cut-character test now
  compares exactly (one replacement, nothing dropped); the README states the two misreads the rule accepts (an undeclared Windows-1252
  page whose only non-ASCII byte is its last, and a UTF-8 page with one stray bad byte and no declaration). Not changed: the check
  relies on CPython's message `unexpected end of data` (tests would catch a change); the random-bytes test only shows no crash,
  which is what the step asks.
- **Not run:** a security review. The change decodes untrusted page bytes but adds no lookup, no path and no command; the list of
  charsets is unchanged. Say if you want one.
- **Left for the owner:** the word to commit A.

### Increment B — The title of a web page (committed as 57887a6bcda4cb40d8de5630ad00d07ff973a669, not pushed)

- **Changed:** `engine/kb/extract_std.py` (the first `<title>` outside an SVG is read, to 2,000 characters, and written to `blocks.json`
  as an optional `title` of at most 300), `engine/kb/convert.py` (the optional `title` is checked and cleaned in `parse_blocks_json`;
  `Parsed` and `Conversion` carry it; `_take_title` sets the book's title when it has none, from the conversion in use and then the
  other, with `metadata_source`, after `set_version_conversions` and before the stage is marked), tests in `test_convert.py`,
  `test_search.py` and `test_read.py`, `engine/README.md`, one sentence in `docs/specs/book.md`.
- **Verification run:** `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert engine.tests.test_search
  engine.tests.test_read` (Python 3.15.0): 284 tests, OK. The new tests failed first (missing `title`, `TITLE_CHARS`, `page_title`).
  Break-it run on 18 places of the new code: all caught; one (the raw-limit guard while reading) was first missed, so a test that
  feeds a title in 5,000 small pieces was added and catches it. Not run: the other test modules (they do not use the changed
  functions beyond what these three cover).
- **Seen, not caused here:** a `ResourceWarning` for an unclosed database comes from the existing test
  `test_one_row_for_each_block_and_nothing_else_in_the_index_folder` (`with sqlite3.connect(...)` commits but does not close). Left
  alone: unrelated cleanup.
- **Review:** independent `reviewer` agent, 1 exchange, no blocking findings, no security risk beyond one that existed before. Not
  applied, with reasons: (1) on a parser older than 3.15 a nested or empty `<title>` can end capture at the wrong point or take
  the first, empty one; the result is still bounded and cleaned, and the engine's Python is 3.15; a title is also taken from
  inside a template or hidden element (only SVG is excluded), a content-quality matter since `<title>` is always in the skipped head.
  (2) The test for a title that is never closed checks only that it is bounded and cheap. (3) The "once" step of the first stage test
  passes because a finished stage returns early; the guard itself is tested by two other tests. (4) Search results scrub no library
  folder from a title, only `read` does; this predates B, a page cannot normally know the owner's folders, and the plan's wording is
  met for `read`. (5) `metadata_source` is overwritten when a title is set; current capture paths create web pages with an empty
  title and no other metadata. (6) `MAX_TITLE_RAW` has the same value in the two files with two meanings, both commented.
- **Security review (run on the owner's word, 2026-11-06):** a `security-reviewer` agent ran 30 experiments on a copy and a second one
  looked at the fixes. No critical or high finding. Cleaning, the type, size and extra-key checks, the raw cap, the SVG handling,
  never replacing a title (also across versions), resuming after a stop, and no write outside `book.json` were found sound
  (tested). Findings and what was done:
  1. *Medium, applied:* a page title could carry the text of the untrusted-text markers (`search.MARKER`, `read.END_MARKER`) and
     imitate the end of the untrusted section. A title whose letters contain `untrustedtext` (case, spacing, joiners, accents and
     compatibility forms folded) is now dropped; tests cover the markers themselves and fullwidth, bold, circled, hyphenated,
     underscored and accented spellings, and the break-it run catches removing the check or either folding step. **Partial:** a
     look-alike letter from another alphabet (Cyrillic) still gets through, and a title with plain instructions and no marker words
     is not blocked. The result is flagged `untrusted` as a whole and the README says to treat the title as data.
  2. *Low, applied:* an unclosed `<title>` swallowed the rest of the page and its markup became the title. A title that was never
     closed is now no title (tests). It relies on Python 3.15's parser, where `<title>` holds raw text; on an older Python an
     ancestor's end tag can still end it.
  3. *Low, accepted:* search results do not scrub library folders from titles, as `read` does; a page can only echo a path its author
     wrote. *Low, accepted:* look-alike letters and long runs of combining marks survive cleaning.
  4. *Second look, not done in B (for the owner):* the check sits where a tool's title is read. An arXiv title (the paper's author
     controls it) is stored without it, as before this change, and the book's `set_metadata` and the citation line (a title can
     put a fake address and date before the real ones) are unchanged. A check where titles are stored or shown would cover all of
     them. This reaches back into the capture and read code that A to H committed, so it is not in this plan.
- **Verification after the fixes:** the same three modules, 287 tests, OK; break-it run on the fixes (marker check, each folding
  step, unclosed title) all caught.
- **Left for the owner:** the word to commit B, and whether to open a small plan for finding 4 (checking titles where they are stored
  or shown, for arXiv titles and the citation line).

### Increment C — Index long blocks in pieces (committed as 26b1a9dea7da5b9fb91e81a204a7e241b431defd, not pushed)

- **Changed:** `engine/kb/index.py` (a block longer than `CHUNK_CHARS` = 2,000 is several rows, each cut at a word and each with an
  `offset` locator for its own start; format number 2; counts `blocks`, `rows`, `skipped`; the resume check compares rows),
  `engine/kb/locator.py` (new `in_block`, which names a place in a given block without scanning the blocks; `MAX_LOOKAHEAD`),
  `engine/kb/textutil.py` (`window`, moved from `read.py`, and new `pieces`), `engine/kb/read.py` (uses `textutil.window`),
  `engine/kb/search.py` (tie order ends with the row, docstrings), tests in `test_search.py` (new `LongBlockTest`), `test_read.py`
  (`PieceReadTest`; `WindowTest` moved to `test_textutil.py`), `test_textutil.py`, `test_convert.py`, `engine/README.md`, and the
  sentence about older formats in `docs/specs/book.md` (the search index is derived: another format is refused with the instruction to
  build it again, which is the owner's command).
- **Verification run:** `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_search engine.tests.test_read
  engine.tests.test_textutil engine.tests.test_convert` (Python 3.15.0): 325 tests, OK (`test_convert` is added to the plan's list
  because `first_words` in the locator changed). The new tests failed first. Break-it run on 18 places: all caught, after four
  fixes of the tests (a dead `rstrip` was removed; the resume check is now tested through `index._current`; pieces must start and
  end at a word and equal the converted text at their locator's offset). One mutation cannot be observed: dropping the row from the
  end of the search's `ORDER BY`, because SQLite returns ties in row order anyway; the key is kept so the order is stated.
- **Expected changes of existing tests:** a search in an 800 KB block of one repeated word now returns the full 10 results (about 400
  pieces) and not one; a 4,000-character block built to grow now counts 2 skipped (two pieces) and not 1.
- **Review:** independent `reviewer` agent, 2 exchanges. Round 1 found one **blocking** problem, which I reproduced before fixing: the
  first twelve words of a place were looked for to the end of its block, so a long block with hardly a word in it (a rule of dots)
  made every piece read the rest of the block, which is quadratic: 1.1 s, 3.8 s and 17.7 s for 0.5, 1 and 2 million characters,
  and hours near the 50-million limit, from a crafted page or PDF. Fixed with `MAX_LOOKAHEAD` = 16,384 characters, used by every
  use of those words (making, naming, checking a locator), so they agree: 4 million characters now take 0.4 s and 10 million 1.0 s.
  The second look found no blocking finding. Costs the owner should know: (a) a place with fewer than twelve words in the next 16,384
  characters has the words that are there, or none (then its first 64 characters); a locator issued before on such text is found
  again by its words (`found_by_text`) and not by its place; (b) a word cut by the bound can never equal a whole word, so a locator
  on such text made against another conversion may be `not_found`; (c) a run of text with no space or line break (a very long
  address, Chinese or Japanese without spaces) is cut at 2,000 characters wherever that falls, and a query for a run across the cut
  does not match; (d) `process` on an index of format 1 reports the instruction to run `index` for each version until it is run.
- **Effect on the owner's library:** the index in the owner's index root is format 1. After this is committed, `search` is refused with
  "run `python3 -m kb index`" until the owner runs it. Nothing was run on the owner's library.
- **Seen, not caused here:** none new (the `ResourceWarning` of an existing test, noted under B, is still there).
- **Security review (run on the owner's word, 2026-11-06):** one `security-reviewer` agent worked on a copy with a fake store and
  fake conversions (not the real converter tools or their 1,000,000-byte output cap), sizes up to 2 MB a block and 10 MB in all; 50 MB
  figures are extrapolated. No critical or high finding. Found sound (tested): coverage of the text by the pieces and every piece
  locator resolving to its own block; `next` chains over random sizes, through text built to grow; hostile locators through
  `read.read` (refused, or `found_by_text`/`not_found`, never wrong text); FTS syntax in text and queries; transactional writes with
  a rollback on an error, a stop or a full memory, and the old index left byte for byte after a failed rebuild; the refusal of a
  format-1 file, an extra trigger or view, an empty file, a file that is not a database, and a read-only index folder, with `process`
  reporting once for each version and neither looping nor stalling; no private path in any result. Findings:
  1. *Medium, fixed:* `locator._kind_of` looked at every block for a heading on every locator made, so a page of N short blocks with
     no early heading cost N squared in the index (10 s for 20,000 blocks; extrapolated to some 16 minutes near the block limit, from a
     crafted page of about 1.5 MB). It predates C, which put it on the path under review. `Conversion` now finds out once
     (`has_headings`); a test fails without it, and the break-it run catches putting the scan back.
  2. *Informational, fixed:* the index signature did not include the size of a piece, so rows cut at another size but with the same
     number of rows would have been taken as current. `chunk` is now in the facts that the signature covers (tested with a case of
     equal row counts). Effect: an index of format 2 written before this fix has another signature, so each version is written
     once again by the next `process`; nothing is refused.
  3. *Low, accepted:* one long block can fill a whole page of results. A 1.8 MB block of one repeated word gave 900 dense pieces and a
     search for it returned 50 of 50 results from that book. Nine hundred short blocks did the same before; it now costs a crafted
     page one block. A cap per book in the results, or grouping, is not done here.
  4. *Low, accepted and in the README:* the check that text does not grow too much when normalised runs on the window of up to
     16,384 characters that starts at a piece, so a clean piece just before a stretch of text that grows (some 800 characters of
     U+FDFA) is left out of the index and counted as skipped, though `next` still reads it.
  5. *Low, accepted:* text that grows under normalisation is expensive though linear: about 4 ms for each piece skipped, some 100 s
     for 50 MB of it, at each `index`, twice in `index_version`, and in a rebuild. Testing the whole block once would avoid it.
  6. *Informational, accepted:* after a change of format, a version marked `indexed` is not revisited by `process` (only `search`
     says to run `index`); `forget_inactive` does nothing on an unusable index, which is harmless because it is refused.
  Second look at the two fixes: an independent `reviewer` agent, no findings (it also confirmed that `Conversion` is built in one
  place, `build`, and that no other whole-conversion scan is on the index write path).
- **Verification after the fixes:** the same four modules, 327 tests, OK; break-it run on the two fixes, all caught.
- **Left for the owner:** the word to commit C, whether findings 3 to 5 should be fixed later, and that the real index must be built
  again with `python3 -m kb index` once C is committed.

### Increment D — Large images are not an incomplete scan (implemented, reviewed and security-reviewed, not yet committed)

- **Changed:** `engine/kb/scan_tool.py` (new caveat kind `large_image_streams` with a fixed sentence and a count; in `scan_pdf` a deflate
  stream that declares itself an image and runs out at the per-stream limit is counted instead of setting `incomplete`),
  `engine/tests/test_scan.py` (a helper `image()` and 14 tests), `engine/README.md` (the paragraph on what the scan leaves).
  `scan.py` is unchanged: it takes the allowed kinds from `scan_tool.KINDS`.
- **The rule, as it ended up.** A stream is a large image, and not an incomplete scan, only when all of these hold: the decode stopped at
  the per-stream limit (not at what was left of the total budget); deflate is the one and last of its filters (the decoder stops at the
  step that ran out, so an ASCII85 or hex step after it was never undone); the dictionary names a filter once (a decoy `/Filter`
  in a nested dictionary can hide the real list); what comes out does not begin like deflate data of any window size; and the
  dictionary text holds `/Subtype /Image` and gives `/Type /XObject` wherever it gives a type, and at least once (added after the
  security review, below). Anything else keeps its old result. The first two million bytes of a large image are scanned like any
  stream.
- **On the real paper (arXiv 1706.03762, read-only, outside the sandbox):** `large_image_streams 3` and no `scan_incomplete`. This is
  finding 4 of the walk-through.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run`
  (Python 3.15.0): 127 tests, OK before the security review's fixes (130 after, see below). The new tests were written first and
  failed first where the behaviour is new. Break-it run on 15 places of the new code: all caught, after three strengthenings of the
  tests (a case for a wrong deflate check value, a case for each chain, a case for a decoy filter key).
- **Review:** independent `reviewer` agent, 2 exchanges. Round 1 found one **blocking** problem, which I reproduced before fixing: when
  a deflate step runs out the chain stops, so `[FlateDecode ASCII85Decode]`, `[FlateDecode ASCIIHexDecode]`, `[FlateDecode
  FlateDecode]` and `[FlateDecode ASCII85Decode FlateDecode]` were reported only as a large image though a later step was never
  undone (before D they were `scan_incomplete`); and a valid deflate header other than the four common ones was taken for pixels.
  Both are closed by the rule above. The second look found no blocking issue and one more route (a decoy `/Filter` in a nested
  dictionary), which is also closed. Not changed: a stream whose dictionary merely contains `/Subtype /Image` (even in a nested
  dictionary or a string) counts as an image; that is the limit the plan accepted, and the README says so. More than about ten
  large figures (the twenty million bytes the scan decodes in all) still give `scan_incomplete`. A large figure whose first
  bytes happen to look like a deflate header (about one in five hundred) gives `scan_incomplete`; that fails safe.
- **Effect on the owner's library:** the scan tool's script changed, so its entry in the owner's config no longer matches its hash and
  the scan will not run on new material until the owner puts the new entry in the config (`python3 -m kb describe-tool all`, in plan
  increment F). Nothing was run on the owner's library; the real PDF was only read.
- **Security review (run on the owner's word, 2026-11-06):** one `security-reviewer` agent worked on a copy, with synthetic PDFs and the
  scan function (not the sandboxed end-to-end run, which it could not start). Found sound (tested): the budget interplay (an image
  cut short by what was left of the total budget, or arriving after it was used up, is `scan_incomplete`; nine images then a script
  stream finds the script; ten images then a script stream gives both); a second `/Filter`, deflate not last and two deflates are not
  exempt; a stream whose dictionary cannot be located is `scan_incomplete`; the validation in `scan.py` (kind from `KINDS`, detail
  equal to its sentence, count 0 to 10**9, at most 50 caveats, nothing from the file in a caveat); no added cost (10 large images
  0.06 s, 2,100 small streams 0.02 s). Findings:
  1. *High, fixed:* a large **object stream or cross-reference stream** with the words `/Subtype /Image` in it (as a name, in a string
     or in a comment) was reported only as a large image, so a script placed after its first two million bytes, which a viewer reads
     when it parses the whole object stream, was not reported at all; before D it was `scan_incomplete`. The exemption now needs
     `/Type /XObject` wherever a type is given and at least once (`_is_image`); regression tests for both kinds and the three ways of
     writing the words, and for a missing, wrong, doubled, nested or wrongly cased type; the break-it run catches going back to the old
     test. The cost: a large image whose dictionary names no `/Type` is `scan_incomplete` as it was before D (pdfTeX and most
     producers write `/Type /XObject`; the real paper does).
     **A third look at that fix found it still forgeable** (rated blocking): a dictionary is the attacker's, so an object stream could
     simply write `/Type /XObject /Subtype /Image` (or a type the scan's pattern cannot read: `/Type %c` and a line break, a null
     byte, an indirect reference, a decoy in a string) next to its `/N` and `/First`. The check was therefore changed to what a
     dictionary cannot forge: a viewer cannot read objects out of a stream without `/N` and `/First` (object stream) or `/W` (and
     `/Size`, `/Index`) (cross-reference stream), so a dictionary holding any of `/N /First /Extends /W /Size /Index` is never
     exempt, whatever else it says. A script's action dictionary has to be in the file's plain text or in an object stream for a
     viewer to find it, so this is the closing of the route. Tests: forged object and cross-reference streams under four ways of
     typing and seven ways of writing the keys, each key alone, and real large images with look-alike keys (`/Intent`,
     `/Indexed`, `/Sizes`...) that keep the exemption; the break-it run catches dropping the check, any one key, or the name boundary.
     The third option of the reviewer, scanning large streams in chunks, was not taken: the figures of the real paper decode to
     well over the twenty million bytes the scan decodes in all, so it would bring back the original false alarm.
     **A fourth look found that the key check reads the text the scan located, not the stream's own dictionary**, and I reproduced
     the attack by hand: a real object stream whose dictionary has `/Type /XObject /Subtype /Image /Filter /FlateDecode` first, then
     a string holding `>>`, a stream marker and a deflate stream, then `/N /First`, then the real stream marker and data with a
     script in it. The scan takes the first marker for the stream, reads the dictionary in front of the fake marker, decodes the
     decoy, and takes the real data for the rest of the same stream. With a **small** decoy the result was **no caveat at all**
     (an honest object stream with the same script reports `javascript`); that is older than D and is not changed by it. With a
     **large** decoy the result was `large_image_streams` only, where before D it was `scan_incomplete`: this is the part D touches,
     and it is closed by one more condition: a stream whose bytes hold the word `stream` is not exempt (an honest compressed
     image never does). A test builds that decoy; the break-it run catches removing the condition.
  2. *Low, fixed:* the caveat sentence now ends "code after that part would not be found", so it does not read as a harmless note
     about pictures.
  3. *Medium, **not fixed here (older than D, outside this increment)**:* a stream that uses a predictor (`/Predictor` above 1) or an
     indirect `/DecodeParms`, and carries `/Type /XRef` or the words `/Subtype /Image`, is skipped before it is decoded and with no
     caveat at all, whatever its size. The reviewer tested a small object stream with a script in its compressed body, a predictor and
     the words in a string: no caveat. It is easier to exploit than finding 1. It is in code that increment E committed, so it is
     for a new plan to fix (undo a PNG predictor, or skip only a real cross-reference stream and a real image); the README now
     names it as a known gap.
  4. *Medium, **not fixed here (older than D, outside this increment)**:* the scan locates a stream by the word `stream` and its
     dictionary by matching brackets, without parsing strings or comments, so a crafted file can steer which text it reads and swallow
     a real stream (the attack described under finding 1; with a small decoy it gives no caveat at all). A second route to hiding an
     object stream, like finding 3. Both are in code that increment E committed. The reviewer's options: track strings and comments
     when finding dictionaries, count a stream whose bytes hold anything after the end of its deflate data (and the word `stream`
     or `endobj`) as incomplete, or check that every stream found belongs to an object (`N G obj`). For a new plan, together with
     finding 3: the owner's decision.
  Second look at the fix of finding 1: an independent `reviewer` agent (the third and fourth exchanges on D) rated the first form of
  the fix forgeable, then the container-key form sound for what D changed, and described the location-steering route of finding 4.
- **Verification after the fixes:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run`:
  134 tests, OK (`test_scan` alone 71); the new tests failed first; break-it run on the new predicate, each container key, the name
  boundary, the stream-marker condition and the sentence, all caught; the real paper still gives `large_image_streams 3` and nothing else.
- **Left for the owner:** the word to commit D, and whether to open a plan for the two older ways of hiding an object stream from the
  scan (findings 3 and 4), which D neither caused nor fixed; the owner's old config entry for the scan tool stops matching when D is
  committed (increment F).
