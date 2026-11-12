# Cut a span that is too long to the part that fits, and flag the theme

Status: Proposed
Created: 2026-11-12
Candidate: none (a correction that follows from a finding: the Result of `2026-11-12-measure-the-size-bound-drops-of-pdfs`; the owner chose this fix on 2026-11-12)
Specs: theme

## Goal

Stop dropping a theme only because the model named a few blocks too many. A theme points to the blocks from a first block to a last one, and the excerpt between them may be at most 6,000 characters (`theme.MAX_EXCERPT`). Today a theme whose span is longer is dropped whole. On the owner's local library (not in this repository) that dropped 10.5 percent of the themes proposed
for 40 PDFs on 2026-11-11, and a trial on 12 of those PDFs on 2026-11-12 found 10 spans over the limit in 155 themes, all within 2.3 times the limit (median 1.5 times), none a single oversized block. Cutting each to the blocks from its first block that fit would have kept all 10, with a median 49 percent of the span each.

When this plan is done, a theme whose named span is over the limit is kept with its span cut to the longest run of blocks, from its first block, that fits in the limit, and carries a flag that says so (`span_cut`, with the size named and the size kept); a theme whose first block alone is over the limit is dropped as before; the check of support reads the cut excerpt, so a part that
the cut-off blocks supported stays `inferred`; the code, the spec and the README say so; and a trial on the same 12 PDFs has shown what it does to the themes made and to their marks. The limit is not raised, the prompt is not changed, and the themes already made are not touched.

## Scope

- In the extraction (`themeextract._draft`): a span over `MAX_EXCERPT` is cut to the last block from the first that fits, the theme is kept with its anchor over the cut span, and a flag `span_cut` is added. A span with no block that fits (the first block is over alone) is dropped with the reason it has now.
- The statement in the theme spec and the engine README; the figures from the trial, labelled as the owner's local library.
- A trial of the extraction and the check, with the new code, on the 12 PDFs of the earlier trial (same manifest), run on the owner's word.

## Non-goals

- Raising `MAX_EXCERPT`, changing the prompt (`THEME_JOB` stays at `v4`), the check of support, the form of a theme or of a flag (the kind of a flag is any short text), or the config.
- Making the themes of the library again. The themes already made keep their flags and their drops. Making the PDFs again (`themes-run plan --again` for them, or all) is a run on the owner's word and a decision of its own, after the trial.
- A second call to the model for a span that is too long, a longer header, or any other fix.

## Assumptions and constraints

- **My calls, not yet the owner's.**
  1. **The cut keeps the blocks from the first named block to the last block that makes the excerpt at most 6,000 characters**, counted as `theme` counts it (the start of the first block to the end of the last, with the blank lines between). It never keeps less than the first block. It is the same for web pages and for PDFs: the rule is on the size, not on the source. **The cut is the longest prefix that fits; if that prefix has no words** (the first blocks are numbers or punctuation only and nothing with words fits after them), `theme.anchor_of` refuses it as it refuses any excerpt with no words, and **the theme is dropped with that reason**. A short block with no words
     at the start of a span, followed by blocks with words that fit, is kept inside the cut.
  2. **The flag is `span_cut`**, and its detail says the size named and the size kept and the blocks named and kept, in at most 300 characters (`theme.MAX_DETAIL`): for example `named 8994 characters in blocks 12 to 45; kept 5010 characters in blocks 12 to 31`. The flag is added after the flags the extraction puts, and before those the check adds.
  3. **The prompt is not changed.** It still tells the model that a theme whose span is longer "is thrown away", which is now less than true (it is cut); it keeps the model's pressure to name fewer blocks, and changing the rules text means a new prompt version, which would make every book of the library eligible to be made again. That is the owner's call and is not made here.
  4. **A journal of pieces is unaffected**: the journal keeps the model's answers, and the cut is made when a theme is drafted from an answer, so a book resumed from a journal after this change gets cut themes where it would have had dropped ones.
  5. **The drops that `themes-run` reports** by kind lose the cut spans: `span_over_limit` then counts only the spans with no block that fits. The cut themes are counted in the flags (`span_cut`).
  6. **The trial keeps the model's raw answers and compares the two rules on the same answers.** The earlier trial's report holds the class and size of each row and not the answers, so it cannot be replayed; this trial records every checked answer of the model for the pieces (in the report, which stays outside the repository, mode 600), and from them works out, with no further call, what the old rule (a span over the limit is dropped) and the new rule (it is cut) keep. That comparison is exact for those answers and is reported on its own; a fresh answer
     differs from the earlier trial's, so the figures against the earlier trial are an estimate of the same kind of thing, not a replay. The later replay of the raw answers is possible with no call to a model.
  7. **The trial uses the manifest of the earlier trial** (sha256 `bec8791badceb11d9412b4cd5ec0251acfccea046667af4ee2e4958320fa8826`: the books, conversions, titles, words to avoid, the model and the prompt version), so the input is the same; the model's answers will differ from the earlier run's, so the number cut is an estimate and not a replay. The trial runs the extraction and the check (both models), files nothing and keeps nothing in the library.
- Each live call goes to the models the owner's config names for `theme` and `theme-check`, in the clear over the owner's network, as before.
- A defect found in the run stops it; the plan is not widened to get past it.

## Completion criteria

1. A theme whose named span is over 6,000 characters is kept with its span cut to the longest run of blocks from its first block that fits, never over 6,000 characters, with a `span_cut` flag whose detail gives the sizes; a span of exactly 6,000 characters is kept whole with no flag; a span whose first block alone is over the limit is dropped with its reason; a cut whose longest prefix has no words is dropped with the reason it has now (no words), and a first block with no words followed by blocks with words that fit is kept inside the cut. Tests show each, with the boundary cases.
2. The anchor of a cut theme is over the cut span (its excerpt hash is that of the cut text), the theme passes the form check of a theme, a cut theme is merged and ordered by its cut span, and the prompt and its version are unchanged. Tests show each.
3. The check of a cut theme reads the cut excerpt. A test shows that the excerpt given to the check model is the cut one.
4. The spec and the README say what is cut and flagged and that the themes already made are not changed.
5. The trial has been run on the owner's word, and its report (the manifest, the raw answers, themes proposed, kept, cut and dropped, the old rule and the new rule on the same answers, the marks of the cut themes against the others, the flags, the time) is outside the repository with its sha256 and in the Result.
6. The owner has the Result and has decided what comes next.

## Increments

### Increment A — The cut in the extraction

**Outcome:** a theme whose named span is over the limit is kept, cut to fit and flagged.
**Dependencies:** none.
**Affected areas:** `engine/kb/themeextract.py` (`_draft` and what it hands to the merge); `engine/tests/test_themeextract.py`, `engine/tests/test_themecheck.py`, `engine/tests/test_themerun.py` where the drop kinds or the flags are counted; `docs/specs/theme.md`; the engine README.
**Steps:**
1. Write the tests first and see them fail, on constructed conversions whose blocks give the spans exactly: 6,000 characters (kept whole, no flag), 6,001 (cut to the blocks that fit, flagged), far over (cut, flagged), a first block alone over the limit (dropped with the reason it has now), a single block within the limit, a first block with no words followed by blocks with words that fit (kept, cut), a prefix with no words that remains unanchorable (dropped with the reason it has now), a span of blocks that all fit but two and the like; the flag's kind, order and detail (at most 300 characters); the anchor of a cut theme (start and end blocks of the cut span, the excerpt hash of the cut text, the check of the form of a theme);
   the merge and the order by the cut span; the prompt text and `THEME_JOB` version unchanged; the excerpt that `themecheck` hands to the check model for a cut theme is the cut one; `themerun`'s counts: a cut theme is in the flags and not in the drops, an uncuttable span is in `span_over_limit`.
2. Change `_draft`; run the tests; break the code on purpose, one break at a time (the limit off by one either way, the cut keeping a block too many, the first block lost, the flag left out, the flag detail wrong, an uncuttable span kept, the anchor over the whole named span, the merge by the named span), and restore each.
3. Write the statement in the spec and the paragraph in the README (what is cut, the flag, that the prompt still says "thrown away", and that the themes already made are not changed), with the figures of the trial labelled as measured on the owner's local library.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_themerun engine.tests.test_themejournal` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-cut-a-span-to-fit-and-flag-it#A`.

### Increment B — The trial on the 12 PDFs

**Outcome:** what the cut does to the themes made and to their marks is known.
**Dependencies:** A. The owner's word for the live run, given after the plan of the trial is shown.
**Affected areas:** nothing tracked except this plan's Result; the trial script and the report are outside the repository.
**Steps:**
1. Extend the trial script of the earlier trial (outside the repository) to run the extraction and the check with the new code on the manifest's books, and to record the checked answers of the model for the pieces and, for each theme, whether it was cut, its marks and its flags, and the totals; and to work out from the recorded answers, with no call, what the old rule and the new rule keep. Try it against a fake model first on two of the books.
2. Show the owner the plan of the trial: the books and pieces (57 pieces, the same books), the calls (about 57 for the pieces and about 2 to 3 for each piece for the check), the estimate, what is sent and where (the pieces to the `theme` model and each theme's excerpt and parts to the `theme-check` model, in the clear), and that nothing is filed. Wait for the owner's "run it".
3. Run the trial; keep the report outside the repository, mode 600, with its sha256.
4. Write the Result: how many themes were cut, kept and dropped, the old rule and the new rule on the same answers (exact for them), and against the earlier trial (an estimate); the marks of the cut themes against the others; my reading, marked as mine; and a recommendation on making the PDFs of the library again.
**Verification:** the script on the fake model (step 1) and the report of the run; `wb run code-work check`.
**Evidence:** the Result of this plan, committed with the trailer `Plan: 2026-11-12-cut-a-span-to-fit-and-flag-it#B`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increment B changes no project code. The card tests are not run: the card code is not touched.

## Risks and sensitive actions

- **A cut theme cites the beginning of an idea.** Its description was written from the full span the model named, and its excerpt is the first part. The check marks the parts the excerpt does not support `inferred`, and the flag says the span was cut, so a reader can tell; but a citation can point to less than the theme is about. The trial measures how often and how far.
- **The prompt says "thrown away".** Left as it is, on purpose (assumption 3).
- **A live run** (Increment B): the text of 12 PDFs, up to 20 KB for each piece, and the excerpt and parts of each theme go in the clear to the servers the owner's config names for the two kinds of work. The owner's word is asked after the plan of the trial is shown.
- **The themes already made are not changed**, so the library holds themes made under both rules until the PDFs are made again; the flag `span_cut` marks those made under the new one.
- **Security review checkpoint:** the change reads the same text and answers as before and adds no input that reaches a privileged use, so I do not propose a security review; the owner is asked once, before Increment A, and a review runs only if the owner asks.

## Review record

- **Reviewer:** the review engine (`plan-81aa3f2634777944`), model `gpt-5.6-terra`. Rounds used: 2 of a bound of 3; the second converged with no meaningful finding.
- **Applied (2):** the trial now records the model's raw answers and compares the old rule and the new rule on the same answers, which is exact for them, and marks the comparison against the earlier trial as an estimate (R1-F1; the reviewer took the earlier trial to have kept its raw answers, but its report holds only the class and size of each row, so it cannot be replayed);
  the cut is defined as the longest prefix that fits, a prefix with no words is dropped with the reason it has now, a first block with no words followed by blocks with words that fit is kept inside the cut, and tests are named for each (R1-F2).
- **Rejected:** none.
- **Left for the owner:** whether to approve the plan; the live run (Increment B) waits for the owner's word after the plan of the trial is shown. No security review (not asked; I do not propose one).

## Deferred work

- Making the PDFs of the library again with the new rule (a run on the owner's word, with `--again`), and the decision whether to change the prompt's sentence (a new prompt version).
- The other fixes the earlier plans named (a second call for a long span, a longer header), unless the trial shows the cut is not enough.
- The 23 themes (1.2 percent) of the library run whose blocks were not numbers: none appeared in the earlier trial of 155 themes.
- The other open items of `2026-11-11-run-the-theme-extraction-over-the-library`.

## Result

### Increment A (the cut in the extraction; committed)

- **Done.** In `engine/kb/themeextract.py`: `_cut(conversion, first, last)`, which gives the last block of the longest run from `first` that fits in `theme.MAX_EXCERPT` (counted as `theme._between` counts a span, the start of the first block to the end of the last) and the flag `span_cut`, and `_draft`, which keeps the theme with its anchor, its merge and its order over the cut span and puts the flag after
  `confidence_unreadable` (and before the flags the check adds). A span that fits is not touched (no flag, exactly 6,000 characters included); a span whose first block is over the limit alone is dropped with the reason it had (the size of the span named); a run that fits but has no words is dropped with `no words`; a range that runs backwards is refused as before. The detail of the flag reads
  `named 10018 characters in blocks 0 to 9; kept 5008 characters in blocks 0 to 4` and cannot pass 300 characters. The prompt and `THEME_JOB` (`v4`) are unchanged, and the prompt still says that a longer span is thrown away. `docs/specs/theme.md`: one [proposed] statement under "Extraction". `engine/README.md`: the passage on what the extraction drops now says what is cut and flagged.
- **Verification as run.** Tests first: the new tests failed because nothing was cut. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_themerun engine.tests.test_themejournal` printed `Ran 362 tests ... OK`; `wb run code-work check` clean.
  New tests: 16 in `CutTest` (spans of exactly 6,000 and 6,001 characters, far over, from the middle of a piece, a first block alone over the limit, a single block within, a first block with no words followed by blocks with words that fit, a run with no words, the order of the flags, the anchor and its excerpt hash, the merge and the order by the cut span, the prompt unchanged, a saved answer drafted again, the sizes of the blocks asked for), one in `test_themecheck`
  (the check model reads the cut excerpt and not the blocks cut off, and the check keeps the flag) and one in `test_themerun` (a cut theme is in the flag counts and a span with no block that fits is in the drops, and the record accepts it). One existing test, `test_a_span_over_the_limit_drops_the_theme`, passed for a different reason after the change (its first block was over the patched limit alone) and was renamed to say so.
  Deliberate breaks: 15 one-line breaks of `themeextract.py` (the limit off by one either way, a block too many or too few kept, the cut stopping at the first block, the blank lines left out of the count, a first block over the limit cut anyway, the flag left out, before the other flag, of the wrong kind or with the wrong sizes or blocks, the anchor or the merge over the span named, the order by the span named): all caught after two redundant lines of code were removed
  and two tests made exact; file restored identical (sha256 prefix `629c56c07d5a`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: a test in which two themes have the same cut span and the order of the answer is kept (the "ordered by the cut span" half of an earlier test passed with the span named too); the blocks the tests construct are asserted to be the sizes asked for. The 1.02 in the spec and the README is the smallest span of the earlier trial (6,124 characters, 1.02 times the limit), recorded in the Result of `2026-11-12-measure-the-size-bound-drops-of-pdfs`.
- **Not run.** The whole suite; any live call; the trial of Increment B. Nothing was filed in the library, and the themes already made are not changed. No security review (not asked; the reviewer named no exposure: the flag detail is built from integers only).
- **Not done.** Increment B, the trial on the 12 PDFs, on the owner's word after its plan is shown.

### Increment B (the trial on the 12 PDFs; the owner's decision is pending; committed)

- **The tool.** The trial tool of the earlier plan, extended and kept outside the repository: script sha256 `fc8aacae5e69b71ea875c2b6c38d7704a92bb7b6c881f70fe01f1c3926bb4ab7` (it uses `pdf_trial.py`, sha256 `4fb6b1cf790f2629b25ef4df96b83c6bba8774cc3753d6ff1c383688c024b201`), tests sha256 `915235ef1b1a8afe8f53428b297ae2317004e6249c0e845bc213abca6bf172be`.
  It runs the extraction and the check as `themes-run` does (`themecheck.make_and_check_for_version`) with the code now in the project, files nothing, keeps every raw answer of the model for the pieces, and replays those answers with no call through the old rule and the new rule. 11 tests, run first (on fake models, on two real books): the old rule keeps a span of exactly 6,000 characters and drops 6,001; the replay of a run's answers gives the run;
  the new rule keeps exactly what it cut more than the old; a book that fails is named and left out of the comparison; nothing is filed in the library; the run stops when the input is not the manifest's. 10 deliberate breaks of the script, all caught (three had been missed: swapped marks, no count of the check's calls, a no-op break replaced); file restored identical.
- **The trial** was run on the owner's word ("run it") after its plan was shown, on the manifest of the earlier trial (sha256 `bec8791badceb11d9412b4cd5ec0251acfccea046667af4ee2e4958320fa8826`, checked against the library before the run, no difference): 12 PDF books, 57 pieces, `gemma4:12b` for the themes and `phi4:latest` for the check, 647 seconds, 177 calls. The report is kept outside the repository, mode 600, sha256 `889e57cb44f78cdf5ca3433ce90e84dc017fb5cfcf1c0358b819e521023a6015`.
- **A book failed.** One of the 12 (`01M6Y2SRDJQY2TXTK3S0FS754E`, 6 pieces) failed with `ThemeRefused` on its first piece (an answer refused for its shape twice). It was not the book that failed in the earlier trial of the same books, which finished this time, so such a refusal is not tied to a book. The comparison below is over the 11 books that finished (130 themes proposed).
- **The old rule and the new on the same 130 answers** (exact, no call): the old rule keeps **116** themes and drops **10 for the size bound** (7.7 percent of those proposed, against 10.5 percent in the library run and 6.5 percent in the earlier trial); the new rule keeps **126**, **cuts 10** and drops none for the size bound. It drops the same 3 proofs or definitions and 1 theme whose blocks are not in the piece as the old. So the new rule keeps 10 more themes (116 to 126, 8.6 percent more), exactly the 10 it cut; no merge differs. The live run (with the check) kept the same 126.
- **The cut themes.** The 10 named 6,517 to 11,784 characters (1.09 to 1.96 times the limit, median 1.56) and kept 4,048 to 5,952 characters, **37 to 89 percent of what they named (median 55 percent; half or more for 5 of the 10, a third or more for all 10)**. They named 4 to 108 blocks and kept 3 to 99. Ten of the 126 themes (7.9 percent) carry `span_cut`.
- **The marks.** Of the parts of descriptions that the check read, **93 percent of those of the cut themes were marked `stated` (40 of 43), against 79 percent for the others (406 of 512)**; 8 of the 10 cut themes have every part `stated`, against 48 of the 116 others. The cut themes are not worse supported than the rest; they are better. With 10 themes this is an indication and not a measure, and a cause could be that their excerpts are long (4,000 to 6,000 characters),
  so that the check reads more text for each part than for a short excerpt, or that the model names long spans for themes the text states fully; the trial does not separate them. It does not show that the check is lenient or strict.
- **Flags.** 44 of the 126 themes (35 percent) carry `field_words` (the limit of 5 percent of the books is in force) and 10 carry `span_cut`.
- **My reading, marked as mine** (a judgement on a small sample): the cut does what it was meant to. It recovers every theme the size bound dropped in this sample, none of the cut themes is poorly supported, and what a reader gets is the first 37 to 89 percent of the span the theme was about, with a flag that says so. It costs no call. The loss it removes is about 8 percent of the themes of a PDF.
  **I recommend keeping it**, and making the 40 PDFs of the library again, as a run on the owner's word, a decision of its own with the following cost: about 244 pieces at about 13 seconds each, so about 53 minutes, and the whole set of themes of each of those books is made again (the model's answers differ from run to run), not only the ones the cut recovers. The newest generation is the one a reader gets and the older ones stay. Whether the gain (about 8 percent more themes of PDFs: the trial recovered 10 themes in 11 books, so about one more for each book and some 35 in the 40 PDFs, and the new flags) is worth that is the owner's call; the web pages, which lose 1.2 percent, need not be made again.
- **For the owner to decide:** keep the cut (it is committed once Increment A is); whether to make the PDFs of the library again with it, and when; whether to change the sentence in the prompt ("is thrown away"), which would be a new prompt version and would make every book of the library eligible to be made again.
- **Not done.** No push. Nothing was filed in the library and no project code changed. No security review (not asked). The owner's decision on making the PDFs again.
