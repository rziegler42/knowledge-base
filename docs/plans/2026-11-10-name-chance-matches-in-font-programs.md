# Name chance matches in font programs for what they are

Status: Completed
Created: 2026-11-10
Candidate: none (a correction that follows from a finding: the scan called a chance match inside a font program "scripts" on a real arXiv paper)
Specs: none (no statement of a spec changes; the scan keeps reporting every match, only under the milder name the scan already has)

## Goal

The PDF scan reports every match of the names of a script, launch or similar entry, and it never drops one. Since the plan
2026-11-06-scan-false-alarms, a match inside the bytes of a picture that does not have the shape of a real use (twelve printable
bytes before it, a byte after it that can begin its value) is reported as `pattern_in_binary_data` ("usually a coincidence") and not as
`javascript`; a match that has the shape of a use keeps its full name wherever it sits.

A finding of 2026-11-10 shows the same chance in another kind of binary data. Of the 40 PDFs in the library, one carries a `javascript`
finding: *Variational Inference: A Review for Statisticians* (arXiv 1601.00670, book `01M73JQHVAQZ0SMY0VM273CGNS`), count 1,
"The PDF contains scripts." Read on a copy, read only: the one match is the three bytes `/JS` followed by the byte `0xD0`, inside the
decoded embedded font program of object 1347 (its dictionary has `/Length1`); the word `/JavaScript` is nowhere in the file, the
catalog's `/OpenAction` is a `/GoTo` `/Fit`, and the six streams that do not decode are JPEG pictures with no match. The scan reads the
decoded content of any stream that is not a picture as text (a deliberate rule: an object stream is a place where a viewer reads
actions, and a dictionary can claim to be anything), so the font program was read as text and the chance match got the full name.

When this plan is done, a match without the shape of a use inside a stream that has the key of a font program (`/Length1`) and none of
the keys of an object stream or a cross-reference stream is reported as `pattern_in_binary_data`; a match with the shape of a use in
such a stream keeps its full name; a dictionary that forges `/Length1` on a container is still read as text; and the scan of the
Blei paper's PDF, run on a copy, gives `pattern_in_binary_data` 1 and no `javascript`. The card of a paper then does not say "scripts"
for a chance match.

## Scope

- Increment A: measure, read only, with the scan as it is: what the 40 PDFs of the library give, and which of them have a match
  inside a stream that has `/Length1`. Nothing in the repository changes.
- Increment B: tests first, then the change in `engine/kb/scan_tool.py`, the label of the scan tool and its history line, and the
  documented description of the rule.

## Non-goals

- A model, a second opinion, or any new caveat kind or field. A caveat keeps only its kind, its fixed sentence and a count; no byte of
  the file goes into one.
- An object parser, or any change to how HTML is scanned.
- Treating other font streams as binary (a font program without `/Length1`, such as some compact font programs): if A shows they
  matter, that is a later plan.
- Changing the stored scan results of books already filed. A book is scanned again only by a decision of the owner; the Blei book is
  one such decision and is left to the owner (see Deferred work).
- Writing the owner's config. The new label of the scan tool needs an entry in `~/.config/knowledge-base/config.json`, which only the
  owner writes.

## Assumptions and constraints

- The rule of the picture is the model: `_is_image` refuses a dictionary that has any key of an object stream or a cross-reference
  stream (`/N`, `/First`, `/Extends`, `/W`, `/Size`, `/Index`), whatever else it says, because a dictionary can claim anything but
  cannot leave out the keys a viewer needs to read objects from a stream. The same refusals apply to a font program: those keys, a
  `/Type` of `ObjStm` or `XRef`, and a stream marker inside the bytes (structure swallowed).
- A demotion is not an exemption. The match is still counted and reported; only its name changes, and only when it lacks the shape of
  a use. The safety of the rule rests on the refusals (the container keys, the `/Type` values, the stream marker), **not on
  `/Length1`**: the scan does not parse dictionaries, so `/Length1` can be written into any stream, as `/Subtype /Image` can. What
  a viewer reads as objects, and so as actions, is a container, and a container cannot leave out its keys; the decoded content of
  any other stream is not read as objects, so a name in it is not a live entry (a script held in a stream as source text carries
  no such name). A decoy `/Length1` on a stream that is not a container can therefore at most demote an unshaped chance match in
  bytes no viewer reads as objects, which is accepted and stated; a match with the shape of a use keeps its full name there too.
  The tests hold each of these cases, the decoy included.
- `scan_tool.py` runs alone in the sandbox, and a change to it needs a new label in `approvals.SCAN_VERSION` and a line in the history
  of the tool-version test in `engine/tests/test_convert.py`. After the commit the owner must put the new entry in the config
  (`python3 -m kb describe-tool all`); until then the scan does not run on new material.
- Binary places cost more to read (a slash costs twice as much, `_work`), so a font-shaped stream must be charged like a picture and
  the cost tests must hold.
- Tests of the engine are run as the README says; `test_convert` uses the pinned environment.

## Completion criteria

1. The measurement of A is in the Result: the findings of the 40 PDFs by kind, and every `javascript`, `pattern_in_binary_data` and
   `external_actions` finding with the kind of stream its match sits in.
2. A test that failed before the change passes: a match without the shape of a use in a font-program stream gives
   `pattern_in_binary_data` and no `javascript`.
3. The twins hold, for a deflated stream and for an unfiltered one: the same bytes in a stream without `/Length1` give `javascript`;
   the same bytes in a stream with `/Length1` and an object-stream key, or a `/Type /ObjStm`, or a `/Type /XRef`, give `javascript`; a
   match with the shape of a use in a stream with `/Length1` gives `javascript`, a decoy `/Length1` on a stream that is not a
   container included.
4. The scan of the 40 PDFs before and after differs only where A predicted: the matches that A found in a stream with `/Length1`, an
   unshaped match and no container key, and no other (the Blei PDF's `javascript` becoming `pattern_in_binary_data` is the known
   case), and the Result says so, with the list.
5. The owner was asked once about a security review of the change and the answer is recorded.

## Increments

### Increment A — Measure what the scan says of the library's PDFs

**Outcome:** a record of what the scan, as it is, finds in each of the 40 PDFs, and where each script-like match sits.
**Dependencies:** none.
**Affected areas:** nothing in the repository; a measuring script outside it; this plan's Result. Nothing is sent anywhere.
**Steps:**
1. With the scan function (`scan_tool.scan_pdf`) on copies of the library's 40 PDFs, in a folder of its own and with `python3 -I`,
   record the caveats of each. Check the caveats against those stored on the books (they must be equal, else the scan changed and
   the record is not of the stored state).
2. For every PDF with a `javascript`, `pattern_in_binary_data` or `external_actions` finding, find the stream whose decoded bytes hold
   each match and record the key words of its dictionary (`/Length1`, `/Subtype`, `/Type`, the container keys) and whether the match
   has the shape of a use. Record counts and key words only; no bytes of a file go into the Result.
3. Record how many PDFs have a stream with `/Length1` at all, and how many matches in them lack the shape of a use.
4. Write the table in the Result, and say whether any match sits in a font stream without `/Length1`.
**Verification:** the 40 stored caveat lists equal the recomputed ones; the counts in the Result are the output of the script.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-name-chance-matches-in-font-programs#A`, holding the Result.

### Increment B — Treat a font program as a binary place

**Outcome:** the scan reports a chance match in a font-program stream as `pattern_in_binary_data`, with the twins and the forged
case held by tests.
**Dependencies:** A.
**Affected areas:** `engine/kb/scan_tool.py`; `engine/kb/approvals.py` (the label); `engine/tests/test_scan.py`;
`engine/tests/test_convert.py` (the history line); the description of the rule where the engine documents it
(`engine/README.md`, if it describes the rule); this plan's Result.
**Steps:**
1. Read the places that use `picture_shaped` in `scan_pdf` and decide, for each, whether a font program is treated like a picture
   there: the binary tally of the decoded bytes (yes), the span of compressed bytes kept as a binary place (yes), the cost charged
   (yes), and the parts that are about pictures only (the predictor and the count of large pictures: no). Write the decision in the
   Result.
2. Write the tests first and see each fail for the right reason: (a) a generated PDF with a deflated stream whose dictionary has
   `/Length1` and whose decoded bytes hold `/JS` followed by `0xD0`: `pattern_in_binary_data` 1 and no `javascript`; (b) the same
   bytes in a stream without `/Length1`: `javascript` as before; (c) the same with `/Length1` and `/N` and `/First`, and with a `/Type
   /ObjStm`: `javascript`; (d) a font-program stream whose bytes hold `/S /JavaScript /JS (...)` with the shape of a use:
   `javascript`; (e) a stream marker inside the font bytes: read as text; (f) a font-shaped stream of two million slashes stays
   within the limits the picture's twin does; (g) a PDF with no font stream gives what it gave; (h) a `/Type /XRef` twin of (c);
   (i) a decoy `/Length1` on a stream that is not a container: a match with the shape of a use stays `javascript`, an unshaped one is
   `pattern_in_binary_data` (the accepted case of the Assumptions); (j) the unfiltered twins: an unfiltered stream with `/Length1`
   whose bytes hold the unshaped match gives `pattern_in_binary_data`, and with a container key, a `/Type` of `ObjStm` or `XRef`, a
   stream marker, or the shape of a use it gives `javascript`.
3. Add the least code that passes: a predicate beside `_is_image` for a font program, with the refusals of the Assumptions, used where
   step 1 decided, **including the branch for a stream with no filter**, which today keeps an unfiltered picture's bytes as a binary
   place and would otherwise leave an unfiltered font program read as text. Raise `approvals.SCAN_VERSION` and add the history line.
4. Break it on purpose, from green copies: remove the container-key refusal, remove the refusal of `/Type /ObjStm`, remove the refusal
   of `/Type /XRef` (each alone), remove the stream-marker refusal, drop the unfiltered branch, treat every stream as a font program;
   the test that should catch each must fail. Record which did.
5. Run the scan of step 1 of A again on the 40 PDFs with the new code and compare with A's record.
6. **Stop and ask the owner whether to run a security review of this change** (bytes of an untrusted file decide the name of a
   finding; a mistake could let a real script be named as a coincidence), with a recommendation, and record the answer. A review runs
   only if the owner asks; the review's findings are evaluated before the commit.
7. Ask the `reviewer` agent for an independent review of the increment and evaluate its findings.
**Verification:** `python3 -m unittest engine.tests.test_scan` and `python3 -m unittest engine.tests.test_bench_pdf`;
`engine/.venv/bin/python -m unittest engine.tests.test_convert` for the tool-version test (the scan tool's text and label); the
comparison of step 5; `wb run code-work check`. No wider run is named: the change is in the scan tool alone, and the one other part
that reads its output (`kb/scan.py`) checks the kinds and counts, which do not change.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-name-chance-matches-in-font-programs#B`, holding the code,
the tests and the Result.

## Verification for the plan as a whole

The Result of A stands unless B changed what it measured; B repeats the measurement and compares. Confirm from the Results that the
Blei PDF, scanned on a copy with the new code, gives `pattern_in_binary_data` 1 and no `javascript`, and run `wb run code-work check`.
What could break outside what is checked: the new label means the scan does not run on new material until the owner updates the
config entry, and books already filed keep their stored scan results until the owner has them scanned again.

## Risks and sensitive actions

- The change decides the name of a finding from bytes an attacker controls. The mitigations are the container-key, `/Type` and
  stream-marker refusals, the shape-of-a-use test (a real action dictionary always has it), the fact that nothing is dropped, and the
  forged cases held by tests. The owner is asked about a security review at step 6 of B.
- The label of the scan tool changes, so the owner's config entry must be updated by the owner. The agent does not write the config.
- Nothing is sent to any service. The measurement reads copies in a folder of their own, with `python3 -I`, and no viewer opens a file.

## Review record

- **Codex plan review (the owner's request), 2026-11-10, model `gpt-5.6-terra`, round 1 of the bound of 3.** Verdict: changes needed;
  four findings (three major, one minor), each checked against the code before it was decided.
  - **R1-F1 applied:** the safety of the rule rests on the container refusals and not on `/Length1`, which can be written into any stream;
    the Assumptions now say so, state the accepted case of a decoy marker on a stream that is not a container, and a test holds it.
  - **R1-F2 applied:** an unfiltered font program is a separate branch of the code (today only an unfiltered picture keeps its bytes as
    a binary place); step 3 of B changes it, and the unfiltered twins and a break for dropping the branch are added.
  - **R1-F3 applied:** the `/Type /XRef` refusal had no test; a twin is added, and the breaks remove each type refusal alone.
  - **R1-F4 applied:** completion criterion 4 now takes the expected difference from the matches that A finds, with the Blei paper as
    the known case.
  - **Left for the owner:** whether to ask for a second round; the review is at 1 of 3.
- **Reviewer agent on Increment B** (read only, cannot run commands), 2026-11-10, one exchange: no blocking finding, four not-blocking
  notes, all applied (the Result entry, a test that a font program cut at the limit is not a large picture, the order of the two tests
  in `_is_font_program`, two README sentences). It named no new security exposure beyond the accepted decoy case, and said what it could
  not check (test results, the hash). A security review was not asked for by the reviewer; that question is the owner's (Result of B).
- **Security review of Increment B (the owner's word: "perform security review"), 2026-11-10:** two `security-reviewer` agents on copies,
  one exchange each, and a third for a second look at the fix. Evaluated with `evaluate-findings`, each checked against the code and
  most by my own reproduction on HEAD and on the working copy. **Applied:** the swallowed-object finding (refuse `obj` in the bytes,
  twice: the first form, the reader's own pattern, was widened to the plain bytes on the second look). **Recorded and not closed, with
  the reason:** the Medium (fake stream header inside a real object stream), because the code before the plan already does it for
  pictures and closing it needs a resolver of indirect `/Length` in the reader (outside this plan; in the README and held by a test);
  the unmetered final pass (measured, bounded by the 50 MB cap); a large font read as incomplete (as before). **Rejected:** giving
  pictures the same refusals (it would add false alarms on large pictures; a change to existing behaviour for the owner). **Left for the
  owner:** the reader that goes by `/Length` (a candidate for a later plan), whether to meter the final pass, and the pictures question.
  No Critical or High finding.

## Deferred work

- Whether and how to scan the Blei book again so that its stored finding and its card change (the owner's decision after B).
- Font programs without `/Length1`, if A finds matches in them.
- An object parser that would tell a real action from a chance match structurally.
- A note from a model beside a finding: judged unsafe as a clearing step and unnecessary here; at most advisory, and not planned.

## Result

### Increment A — What the scan says of the library's 40 PDFs (run, 2026-11-10)

- **Method.** `python3 -I` on a script outside the repository: each PDF of the library was copied to a folder of its own and the copy
  scanned with the scan's own function (`scan_tool.scan_pdf`, label `kb-scan 0.0.8`). The scan's own functions were wrapped to
  record what they are given, not reimplemented: the dictionary of each stream (does it have `/Length1`, which container keys, which
  `/Type`, is it taken for a picture) and every match with whether it has the shape of a use. No viewer opened a file, nothing was
  sent anywhere, and no byte of a file is written here. The script and the copies are untracked; the record of the run has SHA-256
  `7b8317649dcc7dfc533f84ce6c674aeb7c5fa4bb3e2f45a54398f179975ce783`.
- **Step 1, the check.** For **all 40 PDFs the recomputed caveats equal those stored on the books** (kind and count; 21 were stored by
  `kb-scan 0.0.8`, the other 19 have no caveat, so no label). The recorder also agrees with the scan's own counts for every pattern and
  for `pattern_in_binary_data` on all 40: the matches it saw are the ones the scan counted.
- **The findings of the 40 PDFs.** 9 have a `javascript`, `pattern_in_binary_data` or `external_actions` finding: `javascript` in 1
  PDF, `pattern_in_binary_data` in 8, `external_actions` in 1. (Others: `large_image_streams` in 13, `scan_incomplete` in 4.)
- **Step 2, where each match sits** (place = how the scan read the bytes; "picture" = a stream the scan takes for an image; "compressed
  bytes" = the raw bytes of a decoded stream or a picture codec's data, kept as a binary place):

  | Book (paper) | Name in the stored caveats | Where the matches sit | Shaped like a use |
  |---|---|---|---|
  | Language Models are Few-Shot Learners | `pattern_in_binary_data` 1 | compressed bytes: `javascript` 1 | no |
  | An Image is Worth 16x16 Words | `pattern_in_binary_data` 1 | a picture: `embedded_files` 1 | no |
  | Learning Transferable Visual Models (CLIP) | `pattern_in_binary_data` 24 | a picture: `javascript` 24 | no |
  | PaLM | `pattern_in_binary_data` 1 | compressed bytes: `javascript` 1 | no |
  | Dota 2 with Large Scale Deep Reinforcement Learning | `pattern_in_binary_data` 2 | a picture and compressed bytes: `embedded_files` 1 and 1 | no |
  | Soft Actor-Critic | `external_actions` 2, `pattern_in_binary_data` 1 | an object stream (`/N`, `/First`, `/Type /ObjStm`), read as text: `external_actions` 1, not shaped; the file as it is: `external_actions` 1, shaped; compressed bytes: `javascript` 1, not shaped | one of the two `external_actions` |
  | 3D Gaussian Splatting | `pattern_in_binary_data` 18 | pictures (8 recorded pieces) and compressed bytes: `javascript` 4, `embedded_files` 14 | no |
  | Fusion 360 Gallery | `pattern_in_binary_data` 1 | compressed bytes: `javascript` 1 | no |
  | **Variational Inference (the Blei paper)** | **`javascript` 1** | **one stream with `/Length1` and no container key, read as text: `javascript` 1** | **no** |

- **Step 3, the font marker.** 35 of the 40 PDFs have `/Length1` in their plain bytes (fonts are embedded in most papers). **Exactly
  one match in the library sits in a stream that has `/Length1`, no container key and no `/Type` of `ObjStm` or `XRef`, read as
  text: the Blei match** (not shaped). In the 8 other PDFs with a finding, no match sits in such a stream: they sit in pictures and
  in compressed bytes, which are already binary places, and in one object stream (Soft Actor-Critic), which the plan keeps at full
  strength. **No match sits in a font stream without `/Length1`** (no stream is read as text with a match except the Blei stream and
  that object stream), so the scope of B, streams with `/Length1`, covers every case found.
- **What B will therefore change in the library's 40:** one finding, the Blei `javascript` 1 becoming `pattern_in_binary_data` 1. The
  rest of the stored caveats must come out equal.
- **Not shown, or not done.** The records show only where matches occur, not how many font streams the 40 PDFs hold. The Soft
  Actor-Critic `external_actions` in an object stream (unshaped, so possibly a chance match like the others) stays as it is: it is
  in a container, the case the plan keeps at full strength, and it is outside this plan. Forty PDFs are a small sample, mostly machine
  learning papers; the Blei match is the only one of its kind among them.
- **Verification as run:** the 40 stored caveat lists against the recomputed ones (equal); the recorder against the scan's counts
  (equal on all 40); the counts above are the output of the script. `wb run code-work check` after this entry. No tracked code changed.
  (Committed as `ad29e05`.)

### Increment B — A font program is a binary place (run, 2026-11-10)

- **Step 1, the decisions** for each use of `picture_shaped` in `scan_pdf`, now one new local `binary_shaped = picture_shaped or
  _is_font_program(dictionary, blob)`: **the branch for an unfiltered stream or an image codec's data** (keeps the bytes as a span: yes,
  so an unfiltered font program is a binary place, the gap that review round 1 found); **the work charged** for the decoded and raw
  pieces (yes, a slash costs twice as much, as for pixels); **the span of the compressed bytes** kept as a binary place when the
  stream is a picture or a font program, or when the scan decoded it (yes); **the choice between `_tally_binary` and `_tally`** for the
  decoded pieces (yes). **The count of large pictures** (`picture`, which asks `_is_image`) **and the predictor stay about pictures**
  (no change). Where `scan_pdf` reads `picture_shaped` for anything else there is no other use.
- **Step 2, the tests first.** A new class `FontProgramTest` in `engine/tests/test_scan.py`, 14 tests in the end (12 at first, 2 added
  for the security review below): the chance match in a deflated
  and an unfiltered font program; the same bytes without `/Length1` (`javascript` as before); each container refusal alone (object-stream
  keys, cross-reference keys, `/Type /ObjStm`, `/Type /XRef`, `/Type/ObjStm` without a space), deflated and unfiltered; a match with the
  shape of a use keeps its kind; a stream marker in the bytes; the decoy `/Length1` (an unshaped match demoted, the accepted case; a
  shaped one not) and the names in a stream dictionary that holds `/Length1` and an action (full strength); a PDF with no font stream;
  the cost (bounded time, and the charge at the picture's rate against a small allowance); a damaged font program keeps its raw bytes as a
  binary place and is `scan_incomplete`; and a font program cut at the limit is not counted as a large picture. **Seen failing before
  the code, for the right reason**: the chance match, the decoy and the unshaped cost case each gave `javascript` where
  `pattern_in_binary_data` is right (3 of the first 9; the others are twins that hold before and after). One test of mine had a wrong
  expectation (a stored-block deflate puts the match in the compressed bytes as well) and was corrected before the code was written.
- **Step 3, the code.** `_LENGTH1`, `_CONTAINER_TYPES` and `_is_font_program(dictionary, blob)` in `engine/kb/scan_tool.py`, beside
  `_is_image`: `/Length1` is looked for first (cheap), then the refusals: a key of an object stream or a cross-reference stream, a
  `/Type` of `ObjStm` or `XRef`, the word `stream` in the stream's bytes, and (added after the security review) the three bytes `obj`
  in the stream's bytes, in any spelling. `approvals.SCAN_VERSION` 0.0.8 to **0.0.9**, with the history line in `ToolVersionTest`
  (SHA-256 of the script `4ba3f096e6d152932b80dd5f92af99cb23932829d5f136e22a182cac513d2c4e`). The paragraph "Where a match sits" of
  `engine/README.md` names font programs, the damaged-stream case, the refusals and the residuals below.
- **Step 4, the deliberate breaks** (each on the real file, one at a time, restored byte for byte, checked): **12 of 12 caught** in the
  end (the last run, after the security review's fix): the `obj` refusal removed; the container-key refusal removed; the `/Type /ObjStm` refusal alone; the `/Type /XRef` refusal alone; the stream-marker refusal;
  the count of large pictures taken for font programs too; the unfiltered branch dropped; every stream taken for a font program (with
  and without the other refusals); the decoded bytes not tallied as binary; the cost charged as text; the compressed bytes of a font
  program not kept as a binary place. **The first run missed two** (the cost charged as text, and the compressed bytes of a damaged
  font program): the cost test only looked at time, and a damaged stream was not tested. Two tests were added for them and the run
  repeated.
- **Step 5, the 40 PDFs again** with the new code (the script of Increment A; record SHA-256
  `046b7e2b1a8d04df7361dd432d20509f73439f462d1eed4e4cea69cf8639ba95`): **one result differs from A's record: *Variational Inference:
  A Review for Statisticians*, `javascript` 1 becomes `pattern_in_binary_data` 1.** The other 39 are equal, and no match is left read as
  text in a stream with `/Length1` and no container key. This is the difference A predicted (completion criterion 4).
- **Step 7, the reviewer agent** (read only, one exchange): no blocking finding; four notes, all applied: the Result entry (this one);
  a test that a font program cut at the limit is `scan_incomplete` and not a large picture (added, with a break); the cheap `/Length1`
  test moved before the stream-marker test (which reads every byte of a stream); and two README sentences. It could run nothing, so the
  results above are mine, not its.
- **Observation, not acted on.** For a picture the stream-marker refusal is used only in the count of large pictures (`picture`), not in
  the decision that the bytes are a binary place; for a font program the refusal is in the decision, as this plan says. Whether pictures
  should be refused the same way is a question for the owner and outside this plan.
- **Step 6, the security review** (completion criterion 5). The owner was asked, with a recommendation to run it, and answered **yes:
  "perform security review"**. Two `security-reviewer` agents worked on copies (neither could run git; both read the code and ran probes
  on synthetic PDFs; no real PDF reader was available, so what a viewer does is argued from the format, not tested). One looked at
  forging the rule, one at cost, limits and edge values. A third took a second look at the fix.
  - *Critical, High: none.*
  - **Medium (forging), confirmed by me against the real HEAD code, recorded as a residual and not closed:** a real object stream
    whose data holds a fake stream header in a string (`(endstream\n7 0 obj <</Length1 1>> stream\n)`) is read by the scan as two
    streams, because it ends a stream at its first `endstream` and a viewer goes by `/Length`; its actions then sit in the bytes of
    the second, and if that has `/Length1` they are reported as `pattern_in_binary_data` (nothing dropped, a shaped match keeps its
    kind). **The code before this plan does the same with `/Subtype /Image`** (checked on HEAD: `pattern_in_binary_data` 2), so this
    plan adds a second key to a documented residual (README: "a stream extent that a viewer does not see the way the scan does"), not
    a new class. A plain object with the fake header in a string or a comment is caught by the forward reader (full kind and
    `scan_incomplete`). The only unforgeable fact is the container's declared `/Length`; measured on the 40 PDFs: 18,965 streams have a
    direct `/Length` equal to the located extent, 0 disagree, 969 are indirect, and 24 of the 40 PDFs (the Blei paper included) have an
    indirect one, so a check on direct lengths alone would be evaded by an indirect one, and a complete fix needs a resolver of
    indirect lengths in the reader, for pictures too. **Not built; outside this plan.** It is in the README and held by a test that
    records the behaviour (`..._residual_the_readme_names...`) so that a future fix changes it on purpose. This also corrects a phrase
    of this plan's Assumptions ("in bytes no viewer reads as objects"): the decoy case is read by a viewer as objects.
  - **Low 1 (cost and edges), confirmed and fixed:** a `/Length1` stream with no `endstream` of its own swallows the next real object
    (an action written without the shape of a use became `pattern_in_binary_data`; HEAD: `javascript`). Test written first and seen
    failing; fix: refuse a stream whose bytes hold `obj` (first the reader's own `_STRUCTURE` pattern, then, on the second look's
    finding that its look-around leaves spellings such as `obj1`, `xobj`, `/obj` and `objx`, the plain three bytes). A deliberate break
    is caught. What stays: a swallowed object with no `obj` in it at all (not a header a viewer reads it by), in the README. A real
    font program whose raw bytes hold `obj` by chance loses the demotion (a few percent for megabyte fonts, measured 1 in 200 random
    300 KB blobs by the second look): a false alarm only, never a missed one.
  - **Low 2 (cost), not changed, measured:** the final pass over the binary spans is not metered by `_work`, and is 1.4 to 2.3 times
    slower on match-dense bytes than a text pass. At the largest accepted capture (50 MB, `capture_arxiv.PDF_MAX_BYTES`) the worst
    case built took about 12 to 13 s on this machine against 9 to 10 s before, with `MAX_SECONDS` = 25 between streams and a 60 s kill;
    memory about four times the file. The same constant factor already applied to pictures. Not changed: the margin is about 4 to 5
    times on this machine and the cap bounds it; metering the final pass is deferred.
  - **Low 3 (false alarm), not changed:** a font program that decodes past 2 MB gives `scan_incomplete`, as it did before this plan.
  - *Second look at the fix:* sound (cost linear, 0.6 to 1.4 s for a 50 MB blob with no hit; no exception; it can only strengthen a
    name). It found the look-around gaps above (applied), a README precision point (applied by the change itself), and that the
    refusals cover font programs only and not pictures (stated in the README; **giving pictures the same refusals was not done**: it
    would add false alarms on large pictures, whose raw bytes hold `obj` by chance, and is a change to existing behaviour for the
    owner to decide).
  - *Found sound by the reviews* (tested unless marked): the edge spellings of `/Length1` and of the container keys and types
    (`/#4E`, `/Obj#53tm`, `/Length#31`, twice, in a string, nested); the refusals; empty, one-byte and damaged streams; span order and
    non-overlap and equal totals old against new over 6,000 random PDFs; the cost of a font-shaped stream equal to a picture's; a
    deflate bomb (0.01 s); no exception path (read only for the new function).
- **Verification as run:** `python3 -m unittest engine.tests.test_scan` (217 tests, OK, 97 s); `engine.tests.test_bench_pdf` (20, OK);
  `engine/.venv/bin/python -m unittest engine.tests.test_convert.ToolVersionTest` (4, OK); the 12 breaks; the 40-PDF comparison;
  `wb run code-work check`. Not run: the other test modules (the change is in the scan tool, its label and its history line; the one
  other reader of its output checks kinds and counts, which did not change).
- **For the owner after the commit.** The label of the scan tool is now `kb-scan 0.0.9`, so the entry in
  `~/.config/knowledge-base/config.json` must be renewed (`python3 -m kb describe-tool all`, then the config) before the scan runs on new
  material; `process` warns until then. The Blei book's stored scan result and card still say `javascript` until the book is scanned
  again, which is the owner's decision.
- **After the commit (2026-11-10).** The owner renewed the entry in the config: `python3 -m kb tools` then read `kb-scan` 0.0.9, `ok`,
  with the other three tools `ok`. On the owner's word the Blei book was scanned again (`reconvert --book ... --scan`, then
  `process --book ...`; nothing sent anywhere, nothing deleted): its stored scan result is now `pattern_in_binary_data` 1 by
  `kb-scan 0.0.9` (the first output is kept as `derived/kb-scan/1`, the new one is `2`), and a snapshot of all 176 books showed that
  only that book changed. **Its card (generation 1) still shows `scan finding: javascript ... [kb-scan 0.0.8]`**: a card stores the
  scan result of the moment it was made. The owner was told what a new card generation would send to `ned` and **decided to leave
  the card as it is.**
