# Scan hardening: no way to hide an object stream from the PDF scan without saying so

Status: In Progress
Created: 2026-11-06
Candidate: none (no roadmap exists; these are findings of the security reviews of increments D and E of 2026-11-06-first-walk-through-fixes)
Specs: pipeline, book

## Goal

The PDF scan is a pattern scan: it looks for `/JavaScript`, `/Launch`, `/EmbeddedFiles` and the like in the file and in the
streams it can decode. Two ways were found, and one reproduced by hand on 2026-11-06, to hide a script from it with **no caveat at
all** (recorded as findings 3 and 4 under increment D in the Result of 2026-11-06-first-walk-through-fixes):

1. **A claim is trusted.** A stream that uses a predictor (`/Predictor` above 1), or parameters given as a reference, and whose
   dictionary text carries `/Type /XRef` or the words `/Subtype /Image`, is skipped before it is decoded, at any size. A real
   viewer reads an object stream through a predictor, and a dictionary can say what it likes, so an object stream dressed as an image
   or a cross-reference stream is never read.
2. **A string steers where the scan looks.** The scan finds a stream by the word `stream` and the dictionary in front of it by
   matching brackets backwards, with no knowledge of strings or comments. A string inside a real dictionary that holds a fake `>>`,
   `stream` and a small deflate stream makes the scan read the fake one and take the real stream for part of it. With a small decoy
   an object stream with a script in it gave **no caveat**; the same object stream without the trick reports `javascript`.

When this plan is done, a crafted PDF cannot do either: every stream the scan can decode is decoded and scanned whatever its dictionary
claims, each stream is found through its own object's dictionary read forward by a reader that knows strings and comments, and
anything the scan cannot account for is reported as `scan_incomplete`, never as an empty result.

## Scope

- The scan tool gets a version label of its own, so that changing it does not re-label (and so re-convert) the plain extractor.
- Streams that use a predictor are decoded and scanned: the PNG predictors (10 to 15) and the TIFF predictor (2) at 8 bits are undone;
  any other predictor, or parameters the scan cannot read, is `scan_incomplete`. A claim of `/Type /XRef` or `/Subtype /Image` no
  longer skips a stream; the large-image rule of the earlier plan (a stream that runs past the per-stream limit and is shaped like a
  picture) stays as it is.
- Streams are found by reading each object forward from its `N G obj` header, with a reader that knows strings, hex strings,
  comments, names, arrays and nested dictionaries, and between objects knows comments, cross-reference tables, trailers and
  `startxref`. A `stream` keyword the reader did not reach as part of an object it read is `scan_incomplete`.
- Bytes after the end of a stream's data (after the end of the deflate data, `~>` or `>`) other than white space, before
  `endstream`, are `scan_incomplete`.
- An attack corpus in the tests: generated PDFs for each trick, each with an honest twin.
- The new version of the scan tool is approved by the owner, the four books are scanned again, and the result is recorded.

## Non-goals

- A full PDF reader: following the cross-reference table or stream, `/Length`, linearisation, incremental updates as a viewer applies
  them, or encryption. A PDF that is encrypted stays `encrypted`.
- Decoding LZW, run-length, JBIG2, JPX or crypt filters (they stay `scan_incomplete`).
- Scanning the objects inside an object stream structurally. Their text is pattern-scanned, as it is now.
- Changing the large-image rule, the HTML scan, the conversion or the index.
- The title-safety plan (a title checked where it is stored or shown), which is separate.
- Fetching more PDFs. More real papers belong to the rest of the live walk-through, which needs the owner's list of addresses.
- Pushing.

## Assumptions and constraints

- The scan tool is the standard library only and runs in the sandbox on untrusted bytes: every loop in it is bounded, and nothing taken
  from a file is copied into a caveat.
- Each increment that changes `engine/kb/scan_tool.py` changes its hash. The tool's label (increment A) is raised by one each time and
  a line is added to the history in `ToolVersionTest`, because a label may not be used for two texts. The owner approves only the last
  one (increment E); the tests use temporary configs.
- A reader stricter than the viewers will report `scan_incomplete` on some real files that are merely odd. That fails safe, and the
  rate on real files is measured in increment E; if ordinary files begin to say `scan_incomplete`, the caveat loses its meaning and
  the rule is loosened for the case found, with a test.
- Each increment is one verified, reviewed local commit. After the tests pass in increments B, C and D the work stops and the owner is
  asked whether to run a security review of the surface, once for each, and the answer is recorded.
- Nothing is pushed, and nothing is run on the owner's library before increment E and the owner's word.

## Completion criteria

1. For each trick in the corpus, the scan reports the script it hides (`javascript`, `launch_action`, ... as the case may be) or
   `scan_incomplete`, never an empty list and never `large_image_streams` alone; for its honest twin, the result is as it was. The corpus
   holds at least: an object stream behind a predictor with the words `/Subtype /Image`; the same with `/Type /XRef`; with both sets of
   keys; with parameters as a reference; a decoy stream marker in a string with a small decoy and with a large one; a fake `endstream`
   in the string with brackets balanced; a fake `N G obj` header in a string, in a comment and in stream data; a `%` comment between
   objects that holds a whole fake object; bytes after the end of the deflate data.
2. The five PNG predictors and the TIFF predictor undo correctly against a reference on generated data, and each other predictor
   and each unreadable parameter is `scan_incomplete`.
3. The dictionary the scan uses for a stream is the dictionary of that stream's object, whatever strings, comments or fake headers
   the file holds (tests in B).
4. On real files nothing new is said: the arXiv paper in the owner's library still reports `large_image_streams 3` and nothing else,
   and every PDF in `engine/tests/fixtures` gives the caveats it gave before. A generated, honest paper with twenty figures that use
   PNG predictors, of a million bytes each once decoded, reports no `scan_incomplete` (streams with a predictor were free before this
   plan and now count against the scan's budget of 2,000 streams and twenty million decoded bytes).
5. Time grows with the size of the file for each of: a file of a million small objects, one of a hundred thousand tricks, nested
   brackets to the limit, a long run of comments, a long string (timed tests, under the existing bounds).
6. The README says exactly what the scan covers and lists only the gaps that remain.
7. Every increment has its recorded verification, an independent review and a break-it check of its new code, and the security review
   question for B, C and D is answered and recorded.

## Increments

### Increment A — The scan tool has a version of its own

**Outcome:** `kb-scan` carries its own version label, `scan.TOOL_VERSION`, no longer the engine's `__version__`; it starts at the value it
has now (0.0.2), so nothing is re-labelled. The plain extractor keeps following the engine's version. A change to `scan_tool.py` can then
raise the scan's label alone.
**Dependencies:** none.
**Affected areas:** `engine/kb/scan.py`, `engine/kb/approvals.py` (`builtin_scan_entry`), `engine/kb/__main__.py` (the warning of
`reconvert`), `engine/tests/test_scan.py`, `engine/tests/test_convert.py` (`ToolVersionTest`), `engine/README.md`.
**Steps:**
1. Write the tests first: the entry the engine describes for `kb-scan` carries `scan.TOOL_VERSION`; raising the engine's `__version__`
   alone does not change it and raising the scan's does not change the plain extractor's; `ToolVersionTest` reads the scan's label from
   `scan.TOOL_VERSION`; the warning of `reconvert --scan` asks for the scan's label.
2. Move the label: one constant in `scan.py`, used by `approvals.builtin_scan_entry`, the stage and the warning.
3. Say in the README how a tool's label is raised: the scan tool by its own constant, the plain extractor by the engine's version.
**Verification:** `python3 -m unittest engine.tests.test_scan engine.tests.test_stages`, and `engine.tests.test_convert` and
`engine.tests.test_search` under the venv (the command tests of `reconvert`) pass, with the break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-hardening#A`.

### Increment B — Decode what a claim would have skipped

**Outcome:** a stream the scan can decode is decoded and scanned whatever its dictionary says. The predictor skip is gone: the PNG
predictors (10 to 15) and the TIFF predictor 2 (8 bits) are undone on the decoded bytes, with `/Colors`, `/BitsPerComponent` and
`/Columns` read from direct parameters (an array of parameters for a list of filters is followed), and the output is scanned like any
other. A predictor the scan does not know, parameters given as a reference, or parameters it cannot read are `scan_incomplete`. A
stream that runs past the per-stream limit keeps the large-image rule of the earlier plan unchanged.
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py`, `engine/kb/scan.py` (the label), `engine/tests/test_scan.py`, `engine/tests/test_convert.py`
(`ToolVersionTest`), `engine/README.md`.
**Steps:**
1. Write the tests first: object streams with a script, behind each predictor, dressed as an image, as a cross-reference stream and
   as both, with direct parameters and with a reference (all reported, or `scan_incomplete`); each PNG row filter (none, sub, up,
   average, Paeth) and the TIFF predictor against a reference undo on generated data, with `/Columns` and `/Colors` of several values
   and a last row that is short; every other predictor, and a predictor with a missing or absurd `/Columns`, is `scan_incomplete`;
   honest twins (a real image and a real cross-reference stream behind a predictor) report nothing new; the real paper is unchanged;
   an honest paper of twenty PNG-predictor figures of a million decoded bytes each, and one of fifteen hundred small ones, report no
   `scan_incomplete` (criterion 4); one of twenty-five hundred small ones does, because the limit of 2,000 decoded streams is kept
   as it is (it is the existing stream-limit behaviour, now reached by streams that used to be free).
2. Implement the undo in one linear pass bounded by the existing output limits, read the parameters with the same unescaped
   dictionary text as the filter, and remove the claim-based skip. If the twenty-figure test shows `scan_incomplete`, the budget is
   the cause and the lever is to charge a stream that is shaped like a picture (`_is_image`: no container keys, an XObject, an image)
   for no more than its first 256 KB of decoded bytes, and to scan only that much of it. That widens, by a stated amount, the part of
   a claimed image that is not read; the README says so, and it is the owner's call at the review stop, not a quiet default.
3. Raise the scan's label by one and add the line to `ToolVersionTest`.
4. Stop and ask the owner whether to run a security review of the scan's parser; record the answer.
**Verification:** `python3 -m unittest engine.tests.test_scan engine.tests.test_convert_run` and `ToolVersionTest` under the venv pass, with
the break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-hardening#B`.

### Increment C — Read each object forward, with strings and comments known

**Outcome:** the scan finds a stream through its own object. It reads forward from each `N G obj` header with a reader that knows
literal strings (with nesting, escapes and octal), hex strings, comments, names, arrays, nested dictionaries and indirect references,
takes the exact text of the dictionary it read, and takes the data from the `stream` keyword and its end of line to the first
`endstream`. Between objects it knows comments, cross-reference tables, trailers, `startxref` and `%%EOF`. The backward bracket walk
is gone. A `stream` keyword that is not part of an object the reader read, a dictionary that does not close within the limits, or an
object the reader cannot finish, is `scan_incomplete`. The check that every `/Filter` key lies inside a dictionary the scan read stays,
now by exact spans.
**Dependencies:** B.
**Affected areas:** `engine/kb/scan_tool.py`, `engine/kb/scan.py` (the label), `engine/tests/test_scan.py`, `engine/tests/test_convert.py`
(`ToolVersionTest`), `engine/README.md`, `docs/specs/pipeline.md` (one sentence on what the scan promises, if the review finds the spec
says more than the scan does).
**Steps:**
1. Write the tests first, from the corpus: the small and the large decoy marker in a string; a fake `endstream` in the string with the
   brackets balanced; a fake `N G obj` header inside a string, inside a comment and inside stream data; a `%` comment between objects
   that holds a whole fake object; a string with `\(`, `\)`, octal and line-continuation escapes and unbalanced-looking parentheses;
   hex strings and `<<` and `>>` look-alikes; a name with `#xx`; an object that never closes; nesting to the limit and one past it;
   a dictionary at and past `MAX_DICT`; each is reported as the script it hides or as `scan_incomplete`, and its honest twin as before.
   Honest shapes the reader must accept without a caveat: objects written with no white space between tokens (`1 0 obj<</A 1>>endobj`),
   carriage-return-only and carriage-return-and-line-feed line ends, a stream keyword followed by a space and a line end, junk before
   the `%PDF` header and after `%%EOF`, an incremental update (a second cross-reference section and trailer), an object stream, a
   cross-reference stream, and a stream with a missing `endstream` at the very end of the file (which is `scan_incomplete`, as it is
   now).
   The real paper, and each PDF in `engine/tests/fixtures`, give what they gave.
2. Implement the reader, linear in the size of the file, with the budgets the scan has (look-back is no longer needed), the depth and
   length limits, and a cap on the objects read; remove `_dictionary_before` and the bracket walk.
3. Raise the scan's label by one and add the line to `ToolVersionTest`.
4. Stop and ask the owner whether to run a security review of the reader; record the answer.
**Verification:** `python3 -m unittest engine.tests.test_scan engine.tests.test_convert_run` and `ToolVersionTest` under the venv pass, with
the break-it check of the new code, and the timed tests of criterion 5.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-hardening#C`.

### Increment D — Nothing but white space after a stream's data

**Outcome:** a stream whose data goes on after the end of its deflate data (or after `~>` for ASCII85, or `>` for hex) with anything but
white space before `endstream` is `scan_incomplete`, as is a stream whose deflate data ends early. This closes the case where the
length of a stream is not what the scan took it to be, as a second line behind increment C.
**Dependencies:** C.
**Affected areas:** `engine/kb/scan_tool.py`, `engine/kb/scan.py` (the label), `engine/tests/test_scan.py`, `engine/tests/test_convert.py`
(`ToolVersionTest`), `engine/README.md`.
**Steps:**
1. Write the tests first: a stream followed by extra bytes after a clean end, for each of the three kinds of filter; a stream followed
   by white space, an end-of-line and a carriage return with a line feed only, which reports nothing new; a large image (a limit state) is unchanged.
2. Implement it where the filters are undone (the leftover bytes of the decoder), and raise the scan's label by one with the history line.
3. Stop and ask the owner whether to run a security review of this change; record the answer.
**Verification:** `python3 -m unittest engine.tests.test_scan` passes, with the break-it check of the new code.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-hardening#D`.

### Increment E — Approve the new scan and scan the four books again

**Outcome:** the owner has put the new scan entry in the config, the four books of the walk-through are scanned again with it, and
what changed is recorded.
**Dependencies:** A to D, and the owner's step of putting the new entry in the config.
**Affected areas:** the Result section of this plan; the owner's library (four books), with the owner's word.
**Steps:**
1. Print the entries (`python3 -m kb describe-tool all`), check every pinned hash against the file, that the scripts are the committed
   ones and that no readable folder is, contains or lies inside the config, the library, the index or the home folder; show the owner,
   and have the owner replace the `approved_tools` list (the helper used before may be used); confirm with `python3 -m kb tools`.
2. Run `python3 -m kb reconvert --scan` for each of the four books by id, then `python3 -m kb process`.
3. Compare each book's caveats with those before and record them, with the time taken. The arXiv paper must still report
   `large_image_streams` and nothing else.
4. Record the counts, and anything that said `scan_incomplete` that did not before, with the reason and what was done about it.
**Verification:** the recorded comparison; `python3 -m kb tools` shows every tool `ok`.
**Evidence:** one local commit with the trailer `Plan: 2026-11-06-scan-hardening#E`, adding the record to the Result section.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. All of A to D change the scan tool's
script, so after D the whole of `test_scan`, `test_convert_run`, `ToolVersionTest` and the command tests of `reconvert` are run together,
and the engine suite once: the risk is a test that names the scan's label, or one of the stage tests that files a scan output. Increment
E's comparison confirms the result on real files.

## Risks and sensitive actions

- The scan reads untrusted PDFs and the reader of increment C is a new parser of them. It is the surface under review in B, C and D;
  each is a stop for the owner's security-review decision.
- A stricter reader raises the rate of `scan_incomplete` on odd but honest files. This is measured in E on real files, and the fix, if
  needed, is a rule for the case found, with a test, never a quiet exception.
- The change makes the scan do more (it decodes more streams and undoes predictors): the cost is bounded by the existing output
  limits and checked by timed tests.
- Each change of `scan_tool.py` changes the hash of an approved tool, so the tool does not run until the owner approves the new entry
  (increment E). This is the intended behaviour of the approval.
- Increment E rewrites stage state of the owner's four books (through `reconvert`) and runs the tools on their files. The originals are
  not touched, and the old outputs are kept.

## Review record

- **Reviewer:** Codex through the review engine (bridge `ask-codex`). Rounds 1 and 2 reported the model `gpt-5.6-terra`, the configured
  one; round 3 reported `gpt-6.1-sol`, as it did for the previous plan's third round. The cause was not found.
- **Rounds:** 3 of 3. Round 1 converged with no findings. Before round 2 I read the plan critically myself and added, on my own
  finding, a completion criterion and tests for the cost of predictor streams (they were free before this plan and now count against
  the scan's budgets, so a paper with many PNG figures could begin to report `scan_incomplete`), a stated lever for that case, and
  honest shapes the reader of increment C must accept. Round 2 then found one problem in my addition (R2-F1, below); round 3
  converged with no findings. A converged review is not an approval.
- **Applied (1):** R2-F1 (a test for three thousand small predictor streams could not pass under the kept limit of 2,000 decoded
  streams; it is now fifteen hundred, which report nothing, and twenty-five hundred, which reach the limit).
- **Rejected:** none.
- **Left for the owner:** reading the plan and the word to approve it.

## Deferred work

- Following the cross-reference table or stream the way a viewer does, which would make "what a viewer reads" exact. The scan stays a
  pattern scan that reports when it cannot account for something.
- Decoding the filters the scan does not read (LZW, run-length, JBIG2, JPX, crypt).
- Scanning the objects inside an object stream structurally.
- More real PDFs for the false-alarm rate, with the rest of the live walk-through.
- A cap on the generations of a scan that fails after its output was filed (the conversion has one).
- Title safety: a title checked where it is stored or shown (arXiv titles and the citation line). A separate plan.

## Result

### Increment A — The scan tool has a version of its own (committed as c25e1d45ee2ef8718eaf7043e200d127f3a8bd4e, not pushed)

- **Changed:** `engine/kb/approvals.py` (`SCAN_VERSION = "0.0.2"`, used by `builtin_scan_entry`; the unused engine-version import is gone),
  `engine/kb/scan.py` (`TOOL_VERSION = approvals.SCAN_VERSION`), `engine/kb/__main__.py` (the `reconvert --scan` warning asks for the
  scan's label), tests in `test_convert.py` (`ToolVersionTest`) and `test_search.py` (`CommandLineTest`), and two README sentences.
  The value is unchanged (0.0.2), so no label moves and the owner's approved entries still match.
- **A deviation in where the constant lives, on purpose.** The plan says one constant in `scan.py`. `scan.py` imports `approvals`, so
  `approvals.builtin_scan_entry` cannot import `scan` at load time; the constant is in `approvals.py` and `scan.TOOL_VERSION` is set from
  it. The plan's outcome (`scan.TOOL_VERSION` is the scan's label and is no longer the engine's) holds.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_stages` (Python 3.15.0):
  110 tests, OK; `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert engine.tests.test_search`:
  269 tests, OK. The new tests failed first. Break-it run on 4 places (the entry ignores the constant, the stage ignores it, the warning
  asks for the engine's version, the extractor check asks for the scan's): all caught.
- **Review:** independent `reviewer` agent, 1 exchange, no blocking findings, no security risk (a constant moved and a label compared).
  Applied: two stale comments in the tests and one in `__init__.py`. Not changed: the plan's wording of where the constant lives (the
  approved text is not edited; the deviation is recorded above); the two label values are equal today, so one half of the warning test
  cannot tell `approvals.SCAN_VERSION` from `scan.TOOL_VERSION` (harmless: they are the same object by construction).
- **Security review:** none asked for (the plan puts that stop at B, C and D).
- **Left for the owner:** the word to commit A.

### Increment B — Decode what a claim would have skipped (implemented, reviewed and security-reviewed, not yet committed)

- **Changed:** `engine/kb/scan_tool.py` (the parameter reader `_parms`; `_undo_predictor` for the PNG predictors 10 to 15 and the TIFF
  predictor at 8 bits; `_decode_chain` undoes the predictor of a deflate step; the skip of a stream with a predictor or indirect
  parameters on the words `/Type /XRef` or `/Subtype /Image` is gone, and `_INDIRECT_PARMS`, `_PREDICTOR` and `_XREF` with it),
  `engine/kb/approvals.py` (the scan's label, 0.0.3), `engine/tests/test_scan.py`, `engine/tests/test_convert.py` (the history line of
  `ToolVersionTest`), `engine/README.md`.
- **The rule.** A stream the scan can decode is decoded whatever its dictionary says. A predictor that is not 2 or 10 to 15, bits or
  colours that make no sense, a row longer than 4,000,000 bytes, a row type that is no PNG filter, parameters that are a reference, given
  twice, not a whole number, not direct or more entries than filters, and more than 2,000,000 passes over predicted rows in a file (a row
  is charged one for each byte of a pixel) are `scan_incomplete`, and what was decoded before such a predictor is still read. The large-image
  rule of the first fix plan is unchanged and applies to a picture behind a predictor too.
- **Measured cost** (plain Python, this machine): 20 MB of Paeth rows of 3,000 bytes in 3.7 s, ten streams of 2 MB of Average rows in
  1.7 s, 2,000,000 Paeth rows of 3 bytes in 1.5 s, against the tool's 60 s limit; the scan tests build twenty figures behind a predictor
  and 1,500 small streams that give no caveat, and 2,500 small ones that reach the existing limit of 2,000 decoded streams.
- **Verification run:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan engine.tests.test_convert_run` (Python
  3.15.0): 164 tests, OK; `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest engine.tests.test_convert.ToolVersionTest
  engine.tests.test_search.CommandLineTest`: 14 tests, OK. The new tests were written first and failed where the behaviour is new. Break-it
  run on about thirty places of the new code: all caught, after several strengthenings (the checks of bits, colours and columns, the
  size of the previous-row buffer by memory, the decoy cases). The real arXiv paper in the owner's library still reports
  `large_image_streams 3` and nothing else, and both PDF fixtures report nothing, as before.
- **Review:** independent `reviewer` agent, 2 exchanges (the second on the fixes). The fixes of the first exchange:
  1. *Blocking, reproduced and fixed:* a decoy `/DecodeParms` in a string of the dictionary, with no real one, made the scan undo a
     predictor that a viewer never applies, and an object stream with a script in it gave **no caveat at all** (`{}`). The scan reads
     a dictionary as text and does not know strings, so it cannot tell; the bytes from before each predictor that was undone are now read
     for the patterns as well as the undone ones, so the script shows whichever way the viewer reads the stream. Two parameter keys are
     refused as before.
  2. *Cost, fixed:* the budget counted rows, but a Sub or TIFF row costs a pass for each byte of a pixel (32 colours: 32 passes of a
     33-byte row), so about 20 MB of such rows could take 30 to 60 s. It now charges a row for its passes; a test builds the case.
  3. *Cost, fixed:* the buffer for the row before was a whole row of zeros (up to 4 MB) even for a stream of a few bytes; it is now the
     size of the data (tested by memory, since the time is not visible).
  The second exchange found the first two closed and one more hole, **older than B**: the first `/Filter` the scan reads can be a decoy
  in a string that says an image codec (`/DCTDecode`), which the scan does not look into, ahead of the real `/FlateDecode`; the real
  stream was then neither decoded nor reported. It is the same kind of claim the plan is about, so it is fixed here: a dictionary with
  more than one `/Filter` key is `scan_incomplete` (tests for a decoy in a string, in a nested dictionary, written with an escape,
  after the real key, and for the honest single key). Not changed, with reasons: a chain such as `[/FlateDecode /ASCIIHexDecode]`
  with a decoy predictor leaves a residual case (the garbled bytes would have to be valid hex or base-85 text too while the raw bytes
  are; judged implausible, not testable); memory is at most about twice the 20 MB budget more than before (no unbounded growth);
  random bytes in pictures are now searched twice for a three-byte pattern, about one false match in 16 MB, which only adds a count.
- **Security review (run on the owner's word, 2026-11-06):** one `security-reviewer` agent, 2 exchanges, asked to hunt dictionary tricks,
  hostile predictor parameters, cost and memory, and ways to get a script past both the raw and the undone bytes. The first pass ran 32
  experiments on a copy (hand-built PDFs through `scan_pdf`, not the sandboxed run); the second pass could not run anything (its scratch
  path was refused after the working directory changed) and read the code, so its one new finding is from reading and was
  **reproduced by me with a test before it was fixed**. Found sound (tested): the predictor undo against an independent
  reference written from the specifications on 5,283 random cases (PNG types 0 to 4, TIFF, colours 1 to 32, bits 1, 2, 4, 8 and 16, odd
  columns, a partial last row, mixed row types) with **0 differences**; chains `[AHx Fl]`, `[A85 Fl]`, `[Fl Fl]` and `[Fl AHx]` with
  parameters as an array; decoy names such as `/Columns_` and `/Colors-x`; `/FFilter` and `/FDecodeParms` not read as keys; rows at exactly
  MAX_ROW and one more; the large-image rule not made worse; and cost: seven streams of 2 MB of Paeth rows of 3,000 bytes 2.4 s, Average
  1.2 s, one-byte rows 0.4 to 0.7 s, 32 colours 0.7 s, parameter dictionaries near the size limit 0.15 s for 100 of them, peak memory
  about 150 MB at the 20 MB cap (131 MB for ten streams of `#41`, about twice what it was without a predictor). Findings:
  1. *High, fixed:* `/DecodeParms<</A#3E#3E /Predictor 12 /Columns 8>>`: the scan unescaped the whole dictionary before reading it,
     so the escaped `>>` closed the parameter dictionary early, the scan read predictor 1, a viewer read predictor 12, and an object stream
     with a script in it gave **no caveat** (`[]`; the honest twin gave `javascript`). The raw bytes did not help (they are filtered).
     The structure is now read from text where an escape that spells white space, a delimiter, `%` or `#` is left as written (those
     are part of the name, as in a viewer), while the haystacks still use the full unescape.
  2. *High, fixed:* a comment hid the predictor or a reference: `<< %>>` ended the parameter dictionary early; `/Predictor 1 %c` then a
     line with `0 R` (object 1 being 12) hid a reference; `/Columns 1000%c` and a line with `0 R` changed the row geometry. A
     comment in a parameter dictionary or in an array of parameters is now `scan_incomplete`, and a number must end at white space, `/`
     or the end (a number that runs into letters, a hash or a point is refused).
  3. *Medium, fixed (older than B):* a comment in the `/Filter` array closed it early (`[/FlateDecode %]` then `/ASCIIHexDecode]`), so
     the scan read one filter where a viewer reads two. The second pass found the same with a string that holds `]`, an empty array or a
     number in the list. A list of filters is now accepted only if it holds names and white space and nothing else; any other is
     `scan_incomplete`. Each shape has a test, with honest twins (`[/Fl /AHx]`, no spaces, line ends) that read as before.
  Notes, not changed: the stream is still found by the word `stream` and the dictionary before it by matching brackets (increment C);
  a decoy `/Filter` or `/DecodeParms` that looks like the real one is refused when there are two; a name such as `/ASCIIHex-Decode` in a
  list is refused as an unknown filter further on (the stricter character class in the list pattern adds nothing a test can see);
  ASCII85's `z` expands 4 times with no per-stream cap, which is older than B and bounded by the size of the input; a residual case of
  a chain with a filter after deflate and a decoy predictor (the garbled bytes would also have to be valid text for the next filter)
  was judged implausible.
- **Verification after the security review's fixes:** `python3 -B -W error::ResourceWarning -m unittest engine.tests.test_scan
  engine.tests.test_convert_run`: 170 tests, OK; `engine/.venv/bin/python -B -W error::ResourceWarning -m unittest
  engine.tests.test_convert.ToolVersionTest engine.tests.test_search.CommandLineTest`: 14 tests, OK. Break-it run on the fixes (the
  full unescape again, each member of the delimiter set, the parameter comment check, the number boundary, the filter list check): all
  caught, and one check that turned out to be dead code was removed. The real arXiv paper still reports `large_image_streams 3` and
  nothing else, and both PDF fixtures report nothing.
- **Left for the owner:** the word to commit B. This commit changes the scan tool's script, so its entry in the owner's config no longer
  matches (label 0.0.3); increment E is where it is put in. Increment C (the reader that knows strings and comments) is what closes the
  rest of the class.

### Increment C — Read each object forward, with strings and comments known (implemented, reviewed and security-reviewed; not committed)

- **Done:** `engine/kb/scan_tool.py` no longer walks backward from the word `stream`. It reads the file forward, object by object,
  from `N G obj` headers (and `trailer`), reading each value with strings, hex strings, comments, names and nesting known, so a
  bracket or the word `stream` inside a string or a comment is part of it. Label 0.0.4 (`approvals.SCAN_VERSION`, with its
  hash in `ToolVersionTest.HISTORY`); `engine/README.md` describes the reader and what `scan_incomplete` now covers.
- **Bounds:** 16,384 bytes of stream dictionary, 100 levels of nesting, a million objects, twelve million steps, and 20 objects it
  could not finish (the reader stops there and says so). At the 50 MB capture limit the slowest hostile shape measured 5.6 s
  (1,000-byte unclosed strings after each header); 4 MB of the same shape took 44 s before the cap.
- **Verification run:** `unittest engine.tests.test_scan engine.tests.test_convert_run`: 205 tests, OK; `unittest
  engine.tests.test_convert.ToolVersionTest engine.tests.test_search.CommandLineTest`: 14 tests, OK. Break-it runs on the reader (about
  30 mutations over three rounds): every one caught after tests were added for the ones missed (one equivalent mutant and some dead
  code removed). 62 real PDFs (the arXiv paper, 2 fixtures, system PDFs): the same caveats before and after, none newly incomplete,
  slowest 0.1 s.
- **Review (independent reviewer, two rounds):** round one found a quadratic hex-string search, a quadratic unclosed-string search (44 s at
  4 MB), a real object swallowed into a string with an unusual header (a comment between its numbers, many digits) giving **no caveat**,
  an object whose value is the next header, and decoy tests that passed for a weak reason: all fixed with a test that failed first (the
  cap of 20 unfinished objects; the word `obj`/`endobj` in a value is structure; a header as a value is unfinished; decoy tests now
  assert the real stream is read). Round two found a header written `9 0obj` (no white space before `obj`) missed by the new structure
  check, and a comment with no line end after each of many objects searching to the end of the file every time (60 s at 0.6 MB): both
  fixed (a header may have no white space before `obj`; the position after which no line end exists is remembered). Not fixed here, by
  design: hex or ASCII85 data that holds the word `endstream` in its middle is cut there (increment D); the word `obj` as a whole word
  in an honest string (for example a title) is `scan_incomplete`, a false alarm that fails safe and is to be counted in increment E.
- **Security review (independent, run on a copy; 6 million fuzzed inputs, 5 million insertion cases, a 45-case evasion battery, hostile
  shapes up to 60 MB, none slower than 8 s):** no crash, no early stop that left `scan_incomplete` unset, nothing else silent. One
  Medium finding, **fixed:** the letters of `endstream` are ASCII85 digits, so an ASCII85 stream a viewer reads whole by its `/Length`
  can hold them; the scan cut the data there, the truncated text decoded cleanly and the action after it gave **no caveat**
  (reproduced: `{}` against `javascript` for the same file without the letters). Fix: an ASCII85 step whose text holds no `~>` is
  unreadable, so the file is `scan_incomplete`. The second look (read only; its tools were refused) found the same hole for ASCIIHex
  (the scan cuts before the letters and the cut text has no `>`): reproduced by a test that failed first, fixed the same way (no `>`
  means unreadable). Both have tests (the honest twins are read as before) and failed under a break-it run. Three old fixtures built
  ASCII85 or hex text without its end mark and were given it. Low notes, not changed: 16 million `#41` escapes in 48 MB pushed one
  process to about 1.4 to 2.6 GB (older than C; not checked against the sandbox's limit), and the cap of 20 unfinished objects bounds
  the number of retries and not the bytes each reads (no real impact found). The hex fix has not had an independent run of its own.
  Verification after the fixes: 208 tests, OK (`test_scan`, `test_convert_run`); 14 tests, OK; 62 real PDFs unchanged.
- **Not run:** the scan on the four books (increment E); viewer
  behaviour for `0obj` was not checked against any viewer (the scan treats it as a header and as the word `obj` both ways, which fails safe).
- **Left for the owner:** the word to commit C (and whether the hex fix wants a second independent run). This commit changes the scan
  tool's script, so its entry in the owner's config no longer matches (label 0.0.4); increment E puts it in.
