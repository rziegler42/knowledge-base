# Show the model where each block sits

Status: Proposed
Created: 2026-11-11
Candidate: theme-weave#theme-unit
Specs: theme

## Goal

Stop the theme extraction losing themes in PDFs to the size bound, and measure whether it worked. The repeat trial of
`2026-11-11-revise-the-theme-prompts-after-the-first-trial` (Increment D; report sha256
`d236b2629b694691c3716123187109bb340f9cb8c231fc4e0ba4203da7428f6b`, run at commit `cb6a8c0` with `gemma4:12b` for the extraction and
`phi4:latest` for the check) found that, with the length of each block in the prompt, 13 of the 88 themes proposed (14.8 percent) were still dropped because
the blocks they named held more than 6,000 characters. All 13 were in the three PDFs (13 of 68 proposed, 19 percent); none of the 20
proposed in web pages was. Seven of the 13 were at most 9 percent over the limit; three were 7,952 to 8,265 characters; three were 10,947 to
18,202. PDF blocks are small (the median is 6 to 24 characters), so a model that is asked to add the lengths of dozens of blocks has to add dozens of numbers.

When this plan is done, each block header in the prompt says where its block starts and ends in the piece, so that the length of a span is one
subtraction: the end of the last block less the start of the first. And the three PDFs of the trial have been run again, with a
success test set before the build, so that the owner can decide on the library run (Increment F of
`2026-11-11-make-the-theme-the-unit-of-the-weave`).

## Scope

- The block header in `themeextract.pieces`, the rule in `theme_prompt` that says how a span is measured, and the prompt version (`v4`).
- A repeat trial on the three PDFs of the first trial and the comparison with the repeat trial's numbers for them.

## Non-goals

- A rewrite step, a change to the words to avoid or to the worked example, a change to the size bound (`theme.MAX_EXCERPT`, 6,000), to the
  form of a theme, to the check or to the config. The owner decided on 2026-11-11, after the repeat trial, that the wording of the prompt is not
  changed further and that there is no rewrite step.
- Cutting a span the model names to the limit, or choosing the blocks for the model. They change what a theme points to, and a theme would then point to text
  the model did not choose.
- The library run (Increment F of the earlier plan). It waits for the result of this plan.
- The web pages of the trial: they had no size-bound drop, and the header is the same code for them (see the risks).

## Assumptions and constraints

- **Why the fix is believed to work (a belief, which the trial tests).** The model is asked to do arithmetic it does badly. The unit tests cannot show a live
  model does better; only the trial can. Three of the 13 drops were far over the limit and may be the model ignoring the limit, which a header would not
  fix.
- **My calls, not yet the owner's.** (1) The numbers in a header count from the start of the piece, not of the book: they stay small, and the
  first block of every piece starts at 0. (2) They are the same offsets the code measures a span by (`Block.start` and `Block.end` in the converted text, as
  `theme._between` does), so the model's subtraction and the code's measure agree exactly, including the blank line between blocks, and
  any block of no text that a piece leaves out. (3) The rule keeps the limit and says the span is the end of the last block less the start of the first.
  (4) The success test below is a proposal; the owner may set another before the run.
- The prompt of the extraction job (`theme`) has the version `v3`; this plan makes it `v4`.
- The trial's PDFs are the three whose titles start with "Soft Actor-Critic", "A Conceptual Introduction to Hamiltonian Monte Carlo" and "The
  structure and function of complex networks". They are 4, 8 and 18 pieces long at the commit of the repeat trial.
- Each live run is said to the owner beforehand, with what is sent, and waits for the word. The models and the config are those of the repeat
  trial. The agent does not write the owner's config.

## Completion criteria

1. Each block of a piece is headed `<block N, characters A to B>`, where A and B are the start and the end of its block counted from the start of
   the piece, and a block shown cut still gives its real end. A test shows A and B are the offsets that `theme._between` measures a span by (so that
   the end of the last less the start of the first is the size the code checks), also across a block of no text that the piece leaves out.
2. The rules say that a span is as long as the end of its last block less the start of its first, and that it must be at most
   `theme.MAX_EXCERPT`. The prompt version is `v4`.
3. The three PDFs have been run again with the same models, and a report outside the repository holds, beside the repeat trial's numbers for
   them, the themes proposed, kept and dropped (and why), the sizes of the spans dropped for the limit, the flagged themes, the parts stated, inferred and
   not given, the calls, the time and the tokens.
4. The owner has the reading against the success test and has decided on the library run.

## Increments

### Increment A — A block header that says where the block sits

**Outcome:** the model is given, for each block, the characters at which it starts and ends in the piece, and told to measure a span by one subtraction.
**Dependencies:** none.
**Affected areas:** `engine/kb/themeextract.py` (`pieces`, `theme_prompt`, the prompt version of `THEME_JOB`, the module docstring); `engine/tests/test_themeextract.py`;
the engine README.
**Steps:**
1. Write the tests first and see them fail. The header of a block is `<block 12, characters 8400 to 9240>`: the first number is the start of its block less the
   start of the first block of the piece, the second is its end less that start; the first block of a piece starts at 0. For a conversion
   with a block of no text in the middle (if the reader can make one, otherwise a constructed conversion) the numbers still agree with
   `theme._between`: the end of the last block named less the start of the first is exactly the size that `anchor_of` refuses above `MAX_EXCERPT`, shown by
   building a span of exactly that size and of one more. A block shown cut gives its real start and end. The rules say that a span is the end of its last block less
   the start of its first and must be at most `theme.MAX_EXCERPT`; the old rule that adds the lengths and 2 for each blank line is gone;
   the prompt version is `v4`. A piece still holds at most `PIECE_BYTES` bytes with the longer headers.
2. Change `pieces` (the offset is the block's `start` less the first block's `start`) and `theme_prompt`; the tests of the header that
   gave the length (`<block N, L characters>`) change with it, and the old form must not appear.
3. Run the tests; break the code on purpose in the ways the tests name (an offset of the whole book, an end counted without the blank line,
   a start taken from the wrong block, the cut block's offsets taken from the shown text) and restore each; update the README.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themecheck`
and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-show-the-model-where-each-block-sits#A`.

### Increment B — The repeat trial on the three PDFs, and the owner's decision

**Outcome:** the owner has the report beside the repeat trial's numbers, has read a sample, and has decided on the library run.
**Dependencies:** A, and the owner's word.
**Affected areas:** a report outside the repository; this plan's Result. No tracked code unless a defect is found, which stops the run.
**Steps:**
1. Say what is sent and wait for the owner's word. It is what the repeat trial sent for these books: for each piece of the three PDFs (about 30
   pieces), the title, the words to avoid and up to 20 KB of text to the model set for `theme`; for each theme, its excerpt and up to five short
   sentences to the model set for `theme-check`; in the clear to the owner's server and nothing else. The repeat trial took 284 seconds for
   these books.
2. Run once, with the repeat trial's script cut to these books (kept outside the repository), and keep the report outside the repository with its hash.
3. Write into the Result, from the report, the numbers of the repeat trial beside the new ones, for each book and in all: themes proposed, kept and
   dropped and why; the sizes of the spans dropped for the limit (how many are near the limit and how many far over); themes with a flagged word and the flagged
   words; parts stated, inferred and not given; calls, time and tokens; refusals kept aside.
4. Give the owner the reading against the success test below, what cannot be concluded and a recommendation, and record the owner's decision.
**Success test** (set before the build; the owner may change it before the run): in the three PDFs, the themes dropped for the size bound are 5 percent or fewer of those proposed
(13 of 68, 19 percent, before), and no book stops. The other numbers are reported, not tested: a header that lowers the themes kept or
the share stated would be read as a cost. Where the test is not met, the owner chooses again; two fallbacks are named now so that they can be
weighed: a header that also says the last block a span starting there can reach, and a plan to treat a span a little over the limit differently.
**Verification:** the report holds the three books; the numbers in the Result are the report's; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-show-the-model-where-each-block-sits#B`, holding the Result and the owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun `test_themeextract`,
`test_themecheck` and `test_theme` once and `wb run code-work check`. A wider run is not named. What could break outside the tested area is the first live
call after the prompt changes: a model that followed the length form may read the offsets differently, which the trial measures.

## Risks and sensitive actions

- **Book text goes to models again** in Increment B, in the clear over the owner's network, as before. It is said to the owner beforehand, with what is sent, and waits for the owner's word.
- **The header is the same code for web pages**, which the trial does not run. A web page has no PDF-sized blocks, and the unit tests cover its headers, but a live
  change in how the model answers on web pages is not measured here; the library run would show it. The owner may add one web page (the Ising model page, about one minute) to the trial.
- **One run is noise as well as signal.** Five percent of about 70 proposals is three or four themes: a pass or a fail by one theme is not
  firm. The report gives the sizes of the spans dropped so that the owner can see how near they are.
- **No security surface is added:** the numbers are computed from the converted text and given as data inside the existing section; nothing from a reply reaches a path, a command or an
  unchecked field. No security review is proposed.

## Review record

Empty until a review is asked for.

## Deferred work

- The library run (Increment F of `2026-11-11-make-the-theme-the-unit-of-the-weave`), until this plan's result.
- The model's confidence is the word `one` in 17 of 74 themes and exactly 1.0 in all others that can be read, so it carries no information; reading `one` as 1, or dropping the
  confidence, is the owner's to decide.
- The flag for words of a field flags ordinary words (direct, power, target); a stricter rule, or none, is the owner's to decide.
- The rewrite step, skipping blocks that are only references, the leniency of the check, storing the check's model and prompt in the generation, and a journal for the library run.

## Result

### Increment A (done; committed with the trailer for A)

- **Done.** `engine/kb/themeextract.py`: each block of a piece is headed `<block n, characters a to b>`, where `a` and `b` are the block's `start` and
  `end` in the converted text less the `start` of the first block of the piece (so a piece starts at 0, and a later piece counts from its own first
  block); a block shown cut gives where it really ends; a block of no text that the piece leaves out still counts, because the numbers are the
  converted text's own. The intro of the rules describes the header, the rule on the span says that its length is the number after `to` in the header
  of its last block less the number after `characters` in the header of its first (the old rule that adds the lengths and 2 for each blank line is gone),
  and the limit is still read from `theme.MAX_EXCERPT`. The prompt version is `v4`. The module docstring and the engine README say so, and the README records
  that the repeat trial, with `v3`, still dropped 13 of 88 themes. Tests in `test_themeextract.py`: the header against the blocks; offsets that count from
  the piece's own first block; a long block shown cut; a block of no text in the middle; a book that opens with a block of no text; the rules (the two phrases,
  the example header, no "plus 2", the limit read from `theme`); the subtraction of the prompt against `theme.anchor_of` (a span of exactly that size is
  accepted and one character fewer of limit is refused); every block once, in order; a piece of tiny blocks within `PIECE_BYTES`; the version.
- **Tests first, seen failing.** Eight failed before the code (the new header form was absent); the guard on the bytes of a piece passed before and after,
  as a guard should.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_themeextract engine.tests.test_theme
  engine.tests.test_themecheck`: 210 tests OK. `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 16 new (an offset of the whole book; an end without the blank line; an end from the text shown; a start shifted; the origin of a piece
  the first block of the book, not reset, shifted, taken from block 0 or from the block before; the old header form; the old arithmetic in the rules; the wrong
  number named; the limit not read from `theme`; the version left; the byte limit doubled; the old form in the intro) and the 63 earlier: all caught, the file
  restored byte for byte. One new break was first missed (the origin of the first piece taken from block 0): it led to a test of a book that opens with a block
  of no text. One break was invalid code and was rewritten. Six earlier breaks had gone stale with the old header text and were updated to the new code.
- **Read-only measure, no model, no network.** Pieces of the whole library (175 books, one skipped for having no conversion that could be read): 597 with the length
  header, 622 with the offsets (4.2 percent more; PDFs 235 to 244, web pages 362 to 378). The three PDFs of the trial keep their 4, 8 and 18 pieces. The largest book
  is 29 pieces; none is near `MAX_PIECES` (150). So the library run is about 4 percent longer.
- **Review (1 round).** The `reviewer` agent: no blocking finding. It confirmed that the header numbers are what `theme._between` measures, for the first block of a
  later piece, after a block of no text, and for a cut block; that no other code, test or document outside the plans still uses the old form; that `PIECE_BYTES`
  and its comment still hold; and that the version is recorded from the job. Recorded, not applied: (1) a line in a book that looks like a header (`<block 3,
  characters 0 to 10>`) is not marked as not one; this was so with the old form, the effect is a wrong span that `anchor_of` refuses or that makes a theme
  point at other text, no path to a command, a file or an unchecked field was found, and one rules sentence is to be added only if the trial shows the problem;
  (2) the wording "less" is terse: whether a live model subtracts correctly is what Increment B measures; (3) the rule "use only numbers shown in this piece" is
  checked as a range, so the number of a block left out of the piece is accepted (as before this increment); (4) the tests of a first block at 0 cannot tell the
  offset from the book's position, and the multi-piece test and a break cover that.
- **Not done.** Increment B (the trial, which needs the owner's word and a statement of what is sent). No security review (none asked; no new input reaches a
  privileged use: the numbers are computed from the converted text).

### Increment B (done; the success test is not met; the owner chose to go on to a plan for the library run)

- **Run.** Once, at commit cd126b6, on the owner's word ("Run it") after the owner was told what is sent. The three PDFs, the models set for `theme` (gemma,
  answering as gemma4:12b) and `theme-check` (local, answering as phi4:latest), prompt versions `theme` v4 and `theme-check` v1, nothing filed. The script is
  kept outside the repository (the repeat trial's, cut to these books, and counting the sizes of the spans dropped). Report outside the repository, mode 600,
  sha256 `2cb5f921fc76cd3c1821210dd0c7c2eb58d86dc253dbe803ab8ad98430a02913`; the repeat trial's report is sha256 `d236b2629b694691c3716123187109bb340f9cb8c231fc4e0ba4203da7428f6b`.
  The script reproduced the repeat trial's numbers for these three books from that report before the run (68 proposed, 13 dropped for the size bound, the same 13 sizes).
- **A book stopped.** The Soft Actor-Critic paper stopped: an answer to one of its pieces was refused (`the lists of the answer are not all of the same length`)
  and, asked again, refused again, so the run of the book ended and it has no themes in this trial. In the repeat trial the same book completed (4 kept of 8 proposed).
  Answers refused and kept aside, per book (this trial, then the repeat): Soft Actor-Critic 3, 1; Hamiltonian Monte Carlo 3, 3; complex networks 7, 5; 13 and 9 in all
  (12 of the 13 were lists of unequal length, one a method over 300 characters). The refusals are of the same kinds as before, and one trial cannot say whether the
  header raises their number.
- **Per book (this trial, then the repeat): kept of proposed; dropped.** Soft Actor-Critic: stopped; 4 of 8 (3 for the size bound at 6,302, 6,517 and 10,947, 1 a proof).
  Hamiltonian Monte Carlo: 24 of 25 (1 for the size bound, at 6,658); 16 of 18 (2 for the size bound). Complex networks: 41 of 48 (5 for the size bound, at
  6,437, 7,952, 8,265, 12,311 and 18,230, and 2 for `the blocks are not numbers`); 34 of 42 (8 for the size bound).
- **Reading against the success test.**
  1. *No book stops:* **not met** (one of three).
  2. *Themes dropped for the size bound 5 percent or fewer of those proposed:* **not met.** 6 of 73 proposed (8.2 percent) in the two books that completed. The repeat trial's
     13 of 68 (19 percent) is for three books and so is not the like of it; for the same two books it was 10 of 60 (16.7 percent). So the share about halved and did not reach 5 percent.
     The spans dropped for the limit: before, in these two books, 6,007, 6,030, 6,292, 6,300, 6,332 (all at most 6 percent over), 7,952, 8,233, 8,265, 18,120 and 18,202; now 6,437
     (7 percent over), 6,658 (11 percent over), 7,952, 8,265, 12,311 and 18,230. The near misses fell from five to two; the spans far over the limit (more than 30 percent) fell from five
     to four, and two of those four have exactly the sizes of two of the earlier spans (7,952 and 8,265): the model names those spans again.
  3. *New, not in the plan:* 2 of the 73 proposed (one with no title) were dropped because their `blocks` were not numbers; there were none in the 88 of the repeat trial. The report keeps only
     the reason, not what the model wrote, so what it wrote is not known; whether it wrote offsets where block numbers were wanted cannot be said.
- **Other numbers, for the two books that completed (this trial, then the repeat).** Themes kept 65, 50. Themes with a flagged word 61 of 65 (94 percent), 46 of 50 (92 percent); flagged
  words 227, 169. Parts stated 239 of 293 given (82 percent), 178 of 219 (81 percent); inferred 54, 41; not given 32, 31. Unreadable confidences 45 of 65 (69 percent: the model's word `one` in 44,
  `one.0` in 1), 8 of 50 (16 percent). The example's own words appear in no theme. Calls: `theme` 26, 26; `theme-check` 65, 50. Tokens in 243,897, 215,343; out 13,294, 11,431. Time: 298.4 s
  for the two books, 250.7 s before; 317.6 s for the three, 284.5 s before.
- **What cannot be concluded.** One run on three books and one model pair. The stop of a book and the 13 against 9 refusals could be sampling and could be the longer header; one trial does not separate them.
  Whether the offsets fixed the near misses or the model happened to name shorter spans this time is not known; the repeated sizes suggest that for the spans far over the limit the model ignores it
  and that a header cannot fix them.
- **The owner's decision** (after the reading above and my recommendation, "Go with your recommendation"): stop changing the prompt; go on with the prompt `v4` as it is to a plan for the
  library run (Increment F of `2026-11-11-make-the-theme-the-unit-of-the-weave`), which is to handle a book whose answers are refused without ending the run, keep a journal, give an estimate
  and settle what is done with the model's confidence (`one` in 69 percent of these themes). The fallbacks named in this plan (a header that says the last block reachable, a retry
  that tells the model its span is too long) are not built. The Soft Actor-Critic stop is not repeated on its own.
- **Not done.** The plan for the library run. No change to tracked code; no security review (none asked).
