# Measure the themes of PDFs that the size bound drops

Status: Proposed
Created: 2026-11-12
Candidate: none (a measurement that follows from a finding of the library run: 10.5 percent of the themes proposed for PDFs were dropped for the size bound; the fix depends on a number that is not known)
Specs: theme

## Goal

Know how far over the limit the spans are that the model names for PDFs, so that the owner can choose a fix with the numbers in hand. A theme points to the blocks from a first block to a last one, and its excerpt may be at most 6,000 characters (`theme.MAX_EXCERPT`). On the library run of
2026-11-11 (the Result of `2026-11-11-run-the-theme-extraction-over-the-library`), the owner's local library gave 578 themes of 666 proposed for 40 PDFs, so 70 (10.5 percent) were dropped for the size bound, against 1.2 percent for web pages. The dropped themes were not kept, so how far over the limit they were is not known.
That decides between the fixes the earlier plans named: cutting the span to the part that fits (cheap, but a theme whose span is far over would be cited by its first part only), asking the model again with the reason (a call for each piece affected, not sure to succeed), or showing the model how far it may reach (a longer header). The blocks of a PDF are small: read-only,
on 2026-11-12 over the owner's local library, the median block of a PDF is 11 characters against 126 for a web page, and 6,000 characters are a median of 44 blocks (10 percent of the places: 11 or fewer; 10 percent: 139 or more), so a range of blocks the model names can easily be far longer than it means.

When this plan is done, a trial on a sample of the PDFs has recorded, for every theme the model proposed, the size of the span it named (kept or dropped) and the blocks it named when they were not numbers, the owner has the report, and the owner has decided what comes next. No code of the project changes.

## Scope

- A sample of PDFs of the owner's local library, chosen so that it can be made again.
- A trial of the extraction as it is (prompt `theme` `v4`, the words to avoid as the run makes them) on the pieces of the sample, with no check of the themes, which records every answer of the model for the pieces and works out from it, independently of the extraction's own drop rule, the span of each theme in characters.
- A report of the sizes: how many themes were proposed, how many were over the limit and by how much, how many of the blocks named were not numbers, and what cutting the span would keep.
- The owner's reading of the numbers and a decision on the next step (which may be a plan for a fix).

## Non-goals

- Changing the extraction, the prompts, `MAX_EXCERPT`, the check or the form of a theme. Nothing is filed in the library. No fix is built here, and no variant of the prompt is tried; that is a plan of its own once the numbers are known.
- A measure of web pages, which lose 1.2 percent.
- Another run of the check, or of the library.

## Assumptions and constraints

- **My calls, not yet the owner's.**
  1. **The sample** is 12 of the 40 books whose conversion in use was made by `pdftotext` (as the library run counted PDFs), chosen with `random.Random(12).sample` from those books sorted by book id. It is about a third of the PDFs and, at 6 pieces a book, about 75 pieces; the figure is replaced by the plan of the trial that the owner is shown.
  2. **The trial is the production extraction**: `themeextract.extract` with the model the config names for `theme`, the prompt as it is, and the words to avoid made from the library as `themecheck.make_and_check_for_version` makes them. No theme is checked, filed or kept in the library. It is run with a wrapper that keeps each answer of the model.
  3. **Sizes are worked out from the answers, not taken from the drop reasons**: for each row of each answer the blocks named are read as the extraction reads them, the span is the characters from the start of the first block to the end of the last in the converted text, and the theme is put in a class: within the limit, over it (with the size), the blocks not numbers (with the raw text), not in the piece, or the first block after the last.
  4. **What cutting would keep** is worked out offline for each theme over the limit: the share of its span, in characters, that the first blocks that fit in 6,000 characters make up.
  5. **The rate is compared with the library run's**: the share over the limit in the sample should be near 10.5 percent. If it is far from it, the report says so, and the measure is read with that in mind.
  6. **The report records the input it was made from**: the seed and, for each selected book, the version id, the conversion reference (tool, version, generation), the sha256 of the converted text, the title sent, the generation of its card and the words to avoid as they were sent (the values, which are at most 80 words, and their sha256); and, for the trial, the model entry and model of the config for `theme` and the prompt version of the job. A later run of the same trial reads that manifest and uses those books, conversions, titles
     and words to avoid; if the model, the prompt version or any book's conversion, text, card or words to avoid is not what the manifest says, the run stops and says which, and does not replace it silently.
  7. **The trial script and its report are kept outside the repository** (mode 600) and cited by their sha256; they hold book ids, titles of themes and raw answers of the model about the books.
- Each live call goes to the model the owner's config names for `theme`, in the clear over the owner's network, as in the library run. No call to the model of the check is made.
- A defect found in the run stops it; the plan is not widened to get past it.

## Completion criteria

1. The measuring has been tested on a constructed conversion for the cases at the boundary, and the whole script has been tried against a fake model on two of the sample's books and gives the report in its form; the script is cited by its sha256 in the Result.
2. The trial has been run on the owner's word after the plan of it was shown, and its report (the manifest of the input (books, conversions, titles, words to avoid, model and prompt version), counts, sizes, the blocks not numbers, what cutting would keep, the comparison with the library run) is outside the repository with its sha256 and in the Result.
3. The owner has the Result and has decided what comes next.

## Increments

### Increment A — The trial on a sample of the PDFs

**Outcome:** the sizes of the spans that the model names for PDFs are known.
**Dependencies:** none. The owner's word for the live run, given after the plan of the trial is shown.
**Affected areas:** nothing tracked except this plan's Result; the script and the report are outside the repository.
**Steps:**
1. Write the sample (assumption 1), with its manifest (assumption 6), and the trial script outside the repository. Test the measuring on a constructed conversion whose blocks are made so that the spans are exactly 6,000 characters, 6,001, far over, a single block over the limit, blocks that are not numbers, blocks not in the piece and a first block after the last, and check that the class and the size worked out for each are right (as `theme.anchor_of` would judge them). Then try the whole script against a fake model on two of the sample's real books, to show that it runs end to end and gives the report in its form.
2. Show the owner the plan of the trial: the books (ids and the number of their pieces), the number of calls, the estimate (about 9 to 14 seconds a piece with the check; the extraction alone is shorter), what is sent and where, and that nothing is filed. Wait for the owner's "run it".
3. Run the trial. Keep the report outside the repository, mode 600, with its sha256.
4. Read the report and write the Result: the numbers, the comparison with 10.5 percent, what cutting would keep, and my reading marked as mine, with a recommendation.
**Verification:** the script on the fake model (step 1) and the report of the run. `wb run code-work check` for the plan. No test of the project changes, and nothing in the library changes: the library is read, never written.
**Evidence:** the Result of this plan, committed with the trailer `Plan: 2026-11-12-measure-the-size-bound-drops-of-pdfs#A`.

## Verification for the plan as a whole

The report of the trial and the plan check. No code of the project changes, so no test is rerun.

## Risks and sensitive actions

- **A live run** (step 3): the text of about 12 PDFs, up to 20 KB for each piece, with their titles and the words to avoid, goes in the clear to the server the owner's config names for `theme`. The owner's word is asked after the plan of the trial is shown.
- **The sample is a third of the PDFs and a few thousand blocks**, so a rate or a share from it is an estimate with a margin; the report gives the counts, not only the shares.
- **The report holds the model's answers about the books** (book ids, titles of themes, raw block strings), so it stays outside the repository, mode 600.
- **The trial script reads the library and writes nothing in it.** Security review: no new input reaches a privileged use and nothing of the project changes, so I do not propose one.

## Review record

- **Reviewer:** the review engine (`plan-22dcbce8a91220a4`), models `gpt-5.6-terra` (rounds 1 and 2) and `gpt-6.1-sol` (round 3). Rounds used: 3 of a bound of 3; the third converged with no meaningful finding.
- **Applied (3):** the report records the input it was made from, and a rerun uses that manifest and stops on a change (R1-F1); the boundary cases of the measuring are tested on a constructed conversion, and the real books are used only for the end-to-end check with a fake model (R1-F2); the manifest also pins the title, the card generation, the words to avoid as sent, the model and the prompt version (R2-F1).
- **Rejected:** none.
- **Left for the owner:** whether to approve the plan; the live run (step 3 of the increment) waits for the owner's word after the plan of the trial is shown. No security review (not asked; I do not propose one).

## Deferred work

- The fix itself (cutting the span, asking again, or showing the model how far it may reach) and its trial, as a plan of its own once the numbers are known.
- The 23 themes (1.2 percent of those proposed) whose blocks were not numbers: the trial records the raw text, and a fix would be decided with the same numbers.
- The other open items of `2026-11-11-run-the-theme-extraction-over-the-library`.

## Result

### Increment A (the trial on a sample of the PDFs; the owner decided on the cut; committed)

- **The tool.** The trial script and its tests are kept outside the repository (mode 600 where they hold data; the script holds none): script sha256 `4fb6b1cf790f2629b25ef4df96b83c6bba8774cc3753d6ff1c383688c024b201`, tests sha256 `ae268c341e020a4100b57d4f79002b8853d01b8203a1188fee3c300edc2fedac`.
  17 tests, run first: the measuring on a constructed conversion (a span of exactly 6,000 characters is within, 6,001 is over, far over, a single block over, blocks that are not numbers, blocks not in the piece, a first block after the last, blocks with no words), each case also judged by the extraction's own `_draft` and found to agree; the manifest (the sample, what it pins, each kind of change named, a run that stops on a difference);
  and the whole script on a fake model on two of the sample's real books, which agreed with the extraction's drop counts. 14 deliberate breaks of the script, all caught (after one test was added); file restored identical.
- **The sample and the manifest.** 12 of the 40 PDF books (`pdftotext`), `random.Random(12).sample` of the books sorted by id; 57 pieces. The manifest (the books, versions, conversions, text hashes, titles, card generations, the words to avoid as sent, the model `gemma4:12b` and the prompt version `v4`) is kept outside the repository, mode 600, sha256 `bec8791badceb11d9412b4cd5ec0251acfccea046667af4ee2e4958320fa8826`. The run checked it against the library before it began and found no difference.
- **The trial** was run on the owner's word ("run it") after the plan of the trial was shown: the production extraction on the 57 pieces, with no check and nothing filed, 492 seconds in all (about 9 seconds a piece). The report is kept outside the repository, mode 600, sha256 `357c7f38b837cefce9e972910a7fe70ef250322241bd2a56981150dd748fe534`.
- **Numbers.** 155 themes proposed in 12 books. **10 over the limit (6.5 percent)**, 141 within, 3 proofs or definitions, 1 with blocks not in the piece, **0 with blocks that are not numbers**. In the 11 books that finished: 142 proposed, 9 over (6.3 percent), and our count of the spans over the limit agrees with the extraction's own count of its size-bound drops (9 and 9).
  **The library run dropped 10.5 percent (70 of 666)**; this sample is lower, and with 10 spans over the limit the margin is wide (roughly 3 to 12 percent), so it does not contradict that rate. The 1.2 percent of themes whose blocks were not numbers in the library run did not appear in this sample.
- **How far over.** The 10 spans are 6,124, 6,517, 7,336, 7,712, 8,880, 9,107, 9,792, 11,258, 11,784 and 13,938 characters: **1.02 to 2.3 times the limit, median 1.5 times (8,994 characters)**; none is more than 14,000 characters, none is a single block, and no first block is too big to cut. They name 4 to 95 blocks (median 11.5), so the blocks are small and a range of a dozen of them is not far from the limit.
  By size: 2 up to 7,000, 3 up to 9,000, 4 up to 12,000, 1 up to 20,000. The earlier plan's phrase "far-over spans remain" is not borne out by this sample: no span is more than twice and a third the limit.
- **What each fix would do on this sample** (10 spans; estimates): **raising the limit** to 9,000 characters would keep 5 of the 10, to 12,000 would keep 9 and to 14,000 would keep all 10 (a longer excerpt for the check model and for the reader of a theme); **cutting the span to the part that fits** would keep all 10, each with a median 49 percent of the span it named (4 of the 10 keep half or more, 9 keep a third or more),
  so the excerpt would be the first part of what the theme describes and the check would mark the parts about the rest `inferred`; **asking again with the reason** costs a call for each piece that has an over-long span (here 10 of 57 pieces, so about 18 percent more calls) and may not succeed; **leaving it** loses about 6 to 10 percent of the PDF themes.
- **A book failed.** One book of the 12 (`01M6Y2SA3KVY39RDRS3WFRM9KZ`, 4 pieces) failed after 3 pieces had been answered (a `KbError`; its class does not say whether it was a refused answer or a failed call). It is the same kind of failure as the book that failed twice in the library run. A run over the library now keeps the answered pieces in a journal (`2026-11-12-keep-the-pieces-of-a-book-when-one-is-refused`), so such a book would be tried again from its fourth piece.
- **My reading, marked as mine** (a judgement on a small sample): the loss for PDFs is mostly near misses: every dropped span is within a factor of 2.3 of the limit, and it is the model's count of blocks, not an ignoring of the limit, that is off. That favours a fix that does not need another model call. **Cutting to fit** recovers every one of them and is cheap, but it makes a citation point to the beginning of the idea; **raising the limit to 12,000** recovers 9 of 10 and keeps the whole span, but makes every excerpt that the check reads up to twice as long.
  **I recommend cutting to fit, with a flag on the theme saying that its span was cut** (a new kind of flag; correction made after this was written: `theme.py` takes any short text as the kind of a flag, so the form of a theme does not change), as a plan of its own with a trial on these 12 books, and not raising the limit. The owner may prefer the limit; the numbers above say what each does.
- **Decision (2026-11-12).** On the owner's word ("go with your idea") after the numbers and my recommendation: **cut the span to the part that fits and flag the theme**, as a plan of its own with a trial on the same 12 books; the limit is not raised. That plan is `2026-11-12-cut-a-span-to-fit-and-flag-it`.
- **For the owner to decide:** nothing further in this plan. Criteria 1 and 2 are met with the evidence above and criterion 3 by the decision.
- **Not done.** No push. No change to any code of the project, and nothing was filed in the library. No security review (not asked).
