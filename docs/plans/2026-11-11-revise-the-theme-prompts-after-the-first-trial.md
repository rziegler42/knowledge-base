# Revise the theme prompts after the first trial

Status: Proposed
Created: 2026-11-11
Candidate: theme-weave#theme-unit
Specs: theme

## Goal

Fix what the first trial of the theme extraction found, and repeat the trial on the same six books to see whether it worked. The trial
(Increment E of `2026-11-11-make-the-theme-the-unit-of-the-weave`, report sha256
`844bafe09c361daaff9ed8d8e6dd57750b230151aee72fc7ff09cf67f0d9ae9f`, run on 2026-11-11 at commit `0e9211d` with `gemma4:12b` for the
extraction and `phi4:latest` for the check) found three things:

1. **A quarter of the proposed themes were lost to a fault of the drafting.** 29 of 118 were dropped because the confidence the model
   wrote was not a number; the confidence that did parse was 1.0 in 66 of 70 kept themes.
2. **Fourteen percent were lost to the size bound.** 16 of 118 named a span of blocks of more than 6,000 characters (up to 18,230),
   because the model cannot see how long a block is.
3. **The descriptions in words of no field use the field's words.** 63 of 70 kept themes (90 percent) hold a word of the book's
   vocabulary, and the sample showed Ising, Hamiltonian, Monte Carlo, Markov, Metropolis, degree distribution and power-law exponents.

When this plan is done, a theme is never dropped for its confidence, the model sees the length of each block, the prompt gives it the
words of the book's field to avoid and a worked example, and the trial has been repeated with the same books and the same measures, so
that the owner can compare the two reports and decide on Increment F.

## Scope

- Reading the confidence leniently and never dropping a theme for it; keeping what the model wrote when it cannot be read.
- Showing the length of each block in the prompt, and the limit on the span.
- Giving the extraction prompt a section of words to avoid, made from the vocabulary of the book (`themecheck`), and a worked example of a
  description with the field's words taken out.
- Repeating the trial on the same six books and writing the comparison.

## Non-goals

- A rewrite step that asks a model to say a flagged description again without the flagged words. It is the next step if the repeat trial
  shows the prompt is not enough, and it would be a plan of its own (a new kind of work, so a new line in the owner's config).
- Skipping blocks that are only references, changing the check or its prompt, storing the check's model and prompt in the generation,
  a journal, and the run over the library (Increment F of the earlier plan): each is left as it was.
- Changing the size bound, the form of a theme, or the config. The owner's config is not written by the agent.

## Assumptions and constraints

- The trial's numbers are those of the Result of Increment E. Six books chosen from a library of 175, one run, one extraction model and
  one checking model: they show what happened, not how often it happens.
- **My calls, not yet the owner's.** (1) The field-words problem is attacked in stages, cheapest first: the prompt now, a rewrite step only
  if the repeat trial shows the prompt did not do enough. (2) An unreadable confidence is stored as 0.5 with a flag that holds what the
  model wrote. (3) The words to avoid are the book's own vocabulary as `themecheck` defines it (title words, topic words of the card, the
  book's frequent and rare words, less the common ones), at most 80, in that order of strength: the same rule that flags a description
  is the rule that is told to the model. (4) The reading of the repeat trial, below, is a proposal of thresholds; the owner may set others
  before the run.
- The prompt of the extraction job (`theme`) has the version `v1`. Each increment that changes it raises the version (`v2` in B, `v3` in
  C), so that a record shows which prompt made a theme.
- The vocabulary of a book is known before the extraction (it needs the card, the text of the book and the frequencies of the library),
  and `make_and_check_for_version` already computes it first.
- The words to avoid come from the book's text and the card, which are untrusted: they reach the model as data in a section of their own
  between delimiters, as the book's text does, and they are words of letters only.
- Each live run is said to the owner beforehand, with what is sent, and waits for the word. The models and the config are those of the
  first trial.

## Completion criteria

1. A theme whose confidence cannot be read is kept, with the confidence 0.5 and a flag of the kind `confidence_unreadable` whose detail is
   the text the model wrote; a theme is never dropped for its confidence. Tests show it for words, empty-looking text, percentages and
   numbers outside 0 to 1.
2. Each block in the prompt is headed with its length in characters, and the rules give the limit on the characters from the first block
   to the last. A test shows the lengths are those of the blocks, and that a block shown cut still says its real length.
3. The prompt carries a section `WORDS TO AVOID` with the words of the book's vocabulary (none, when there is none), the rule that the
   five parts must not use them or other words that only the field's people use, and a worked example. A test shows the section is data
   between delimiters, the words are the book's in the order and number stated, less any word that the example's own description parts
   use (so that the prompt never tells the model to avoid a word its own example uses), and the book's text is only in its own section
   and not in the rules.
4. The repeat trial has been run on the same six books with the same models, and a report outside the repository holds the numbers named in
   Increment D beside those of the first trial.
5. The owner has read a sample of the new themes and decided whether to go on to Increment F of the earlier plan, to change the method
   again (the rewrite step), or to stop.

## Increments

### Increment A — A theme is never dropped for its confidence

**Outcome:** the drafting reads what the model wrote as a confidence as far as it can, and keeps the theme whatever it wrote.
**Dependencies:** none.
**Affected areas:** `engine/kb/themeextract.py` (`_confidence`, `_draft`); `engine/tests/test_themeextract.py`; the engine README.
**Steps:**
1. Write the tests first and see them fail. A number from 0 to 1 is read as it is. A number outside 0 to 1 is put to the nearest end (as
   now). A number with a percent sign (`90%`) is the share (0.9). The first number in a text such as `0.9 (high)` is read. The words
   `high`, `medium` and `low` (in any case, with a full stop) are 0.9, 0.6 and 0.3. Text with no number and none of those words, empty-looking text, and `nan`
   or `inf` are unreadable: the theme is kept with 0.5 and a flag `{"kind": "confidence_unreadable", "detail": <what was written, cleaned, at most 300 characters>}`.
   No theme is dropped for its confidence.
2. Change `_confidence` and `_draft`: the draft carries the flag, and `extract` adds it to the flags of the theme.
3. Run the tests; break the code on purpose in the ways the tests name and restore each; update the README (the sentence that says a theme
   with a confidence that is not a number is dropped).
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_theme
engine.tests.test_themecheck` and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-revise-the-theme-prompts-after-the-first-trial#A`.

### Increment B — The model sees how long each block is

**Outcome:** each block of a piece is headed with its length, and the rules say how long a span may be.
**Dependencies:** A.
**Affected areas:** `engine/kb/themeextract.py` (`pieces`, `theme_prompt`, the prompt version of `THEME_JOB`); its tests; the README.
**Steps:**
1. Write the tests first and see them fail: the header of a block is `<block 12, 840 characters>` with the true length of the block's text,
   including a block shown cut (which says its real length); the rules name the limit (`theme.MAX_EXCERPT`) and say that the characters of
   the blocks from the first to the last, with two for each blank line between them, must not pass it; the prompt version is `v2`.
2. Change `pieces` and `theme_prompt`.
3. Run the tests; break the code on purpose and restore each; update the README.
**Verification:** the nearest tests as in A, and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-revise-the-theme-prompts-after-the-first-trial#B`.

### Increment C — Words to avoid, and a worked example

**Outcome:** the extraction prompt tells the model which words of the book's field not to use in the parts of a description, and shows
how to say a field's text in general words.
**Dependencies:** B.
**Affected areas:** `engine/kb/themecheck.py` (a function `avoid_words` and its use in `make_and_check_for_version`);
`engine/kb/themeextract.py` (`theme_prompt`, `extract` takes the words, the prompt version `v3`); their tests; the README.
**Steps:**
1. Write the tests first and see them fail. `avoid_words(text, df, size, title, topics, limit)` returns a list: first the words of the
   title, then those of the topics, then the book's own frequent words by number of occurrences, most first, each once, none of them
   common, at most 80; on the twenty-book fixture of the existing tests it gives the words and the order written in the test. The prompt has
   three data sections in this order: the title, `WORDS TO AVOID` (one line of the words, or the word `none`), the text; the rules say the
   five parts must not use a word of the section or another word that only the field's people use; the worked example is a fixed
   constant in the rules, and the words of its description parts are left out of the list of words to avoid, whatever the book is (a
   test gives a book whose vocabulary holds a word of the example and shows the word is not in the section); a forged line in the words
   cannot close the section (the words have letters only, and the token is not in any input); `make_and_check_for_version` passes the
   words it computes and `make_for_version` passes none.
2. Write the function and change the prompt; the worked example is a fixed constant, written once: a short text from a field outside the
   library, its five parts in words that name no field, and a line saying that the model's answer must be about the book's text and not
   about the example.
3. Run the tests; break the code on purpose and restore each; update the README.
**Verification:** the nearest tests as in A, and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-revise-the-theme-prompts-after-the-first-trial#C`.

### Increment D — The repeat trial and the owner's decision

**Outcome:** the owner has the report of the repeat trial beside the first, has read a sample, and has decided what comes next.
**Dependencies:** A, B and C, and the owner's word.
**Affected areas:** a report outside the repository; this plan's Result. No tracked code unless a defect is found, which stops the run.
**Steps:**
1. Say what is sent and wait for the owner's word. It is what the first trial sent: for each piece of the same six books, the title, the
   words to avoid and up to 20 KB of text to the model set for `theme`; for each theme, its excerpt and up to five short sentences to the
   model set for `theme-check`; in the clear to the owner's server and nothing else. The first trial took about six minutes.
2. Run once, with the same script shape as the first (kept outside the repository, extended to count what is new), and keep the report
   outside the repository with its hash.
3. Write into the Result, from the report, the numbers of the first trial beside the new ones, for each book and in all: themes kept and
   proposed; themes dropped and why (the confidence should be none, and the excerpt over the bound should be fewer); themes kept
   with an unreadable confidence and what the model wrote; themes with a flagged word, the words per flag, and how many flagged words were in
   the list the model was given (none, if it obeyed); parts stated and inferred; time and tokens; and whether the example's own words
   (queens, brood, honey, or those of the example as written) appear in the themes of the books.
4. Show the owner a sample: 12 parts marked `stated` with their excerpts, and 8 descriptions that are flagged. Give the reading against the
   proposal below, what cannot be concluded, and a recommendation; record the owner's decision.
**Proposed reading** (the owner may change it before the run): the prompt did enough if no theme is dropped for its confidence, the
themes dropped for the size bound are 5 percent or fewer of those proposed (14 percent before), and the themes with a flagged word are 50
percent or fewer of those kept (90 percent before) with fewer words in a flag. If the size bound is met and the flags are not, the next
step is the rewrite step. If neither is met, the model or the prompt is not a fit and the owner decides.
**Verification:** the report holds the six books; the numbers in the Result are the report's; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-11-revise-the-theme-prompts-after-the-first-trial#D`, holding the
Result and the owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun `test_themeextract`,
`test_themecheck` and `test_theme` once and `wb run code-work check`. A wider run is not named: the changes are to the prompt, the drafting
and a new function, and no other module reads them. What could break outside the tested area is the first live call after the prompt
changes: the prompt is longer (a section of up to 80 words, a worked example and a length on each block header), and a model that
followed the shorter one may answer differently, which the repeat trial measures.

## Risks and sensitive actions

- **Book text goes to models again** in Increment D, with the words to avoid, in the clear over the owner's network, as before. It is said
  beforehand and waits for the owner's word.
- **The words to avoid are derived from untrusted text** (the book and the card). They are letters only, they are given as data between
  delimiters that hold a random token no input holds, and the rules say that the data holds no instructions. A model can still be steered
  by what it reads; the answer is checked for shape and cleaned, as before.
- **The worked example can be copied.** A model may put the example's words into a description. The repeat trial counts it.
- **A theme kept with an unreadable confidence carries 0.5**, which is a guess. The flag says so and holds what the model wrote.
- No secret is read or written, and the config is the owner's.

## Review record

Reviewer: Codex through the review engine (plan-2f43bf275389bd0d), 1 round of 3, verdict `changes_needed`, one major finding, applied. The
owner chose to go on to approval after round 1, so the review did not converge. The records are in
`.workbench/workbench/review-engine/plan-2f43bf275389bd0d/`.

- Round 1 (1 major, applied): the criterion that the fixed worked example holds no word of any book's vocabulary cannot be met, because
  the vocabulary is derived for each book. It now says that the words the example's own description parts use are left out of the list of
  words to avoid, so that the prompt does not contradict itself, with a test on a book whose vocabulary holds such a word.
- Rejected: none.
- Left for the owner: the confidence-reading rules (0.5 for an unreadable one, the three words, the percent), the staging of the fix (prompt
  first, a rewrite step later), the number and order of the words to avoid (at most 80, title, topics, then the book's frequent words), and
  the proposed thresholds for reading the repeat trial; the second and third rounds were not asked for.

## Deferred work

- The rewrite step for descriptions that still hold the field's words (a plan of its own, with a new kind of work in the config).
- A rule that skips blocks that are only references, and a measure of how lenient the check is, from more samples read by the owner.
- Storing the check's model and prompt version in the generation, batching the checks, and a journal, before the run over the library.

## Result

### Increment A (done; committed as c6ed985)

- **Done.** In `engine/kb/themeextract.py`, `_confidence` reads what the model wrote and `_draft` keeps the theme whatever it was: no theme is
  dropped for its confidence. Tests in `engine/tests/test_themeextract.py` (47 there, 158 over the three modules of the plan's
  verification), one test in `test_themecheck.py` (a flag the theme already has is kept and the check's flags follow), and the README.
- **The rules as built.** The first number is read (a comma between digits is a point; `%` or the word `percent` after it makes it a share; a
  number outside 0 to 1 goes to the nearest end; a hyphen after a letter is not a minus sign, so `high-0.8` is 0.8 and `-3` at the start is
  still 0.0); with no number the first of `high`, `medium`, `low` is 0.9, 0.6, 0.3. Anything else is unreadable: the theme is kept with 0.5 and
  a flag `{"kind": "confidence_unreadable", "detail": <what was written>}`, and an empty text is named `(empty)`.
- **Beyond the plan's list, from the review, and decided here.** (1) A fraction or a range (`8/10`, `3 / 5`, `0.5-0.9`, `1-5`) and a denied
  word (`not high`, `no low`, `never medium`) are unreadable and not read: the review traced them to wrong numbers with no flag (`8/10`
  read as 1.0). (2) The word `percent` counts as `%`. (3) In a merge of near-identical themes a confidence that was read beats one that was
  guessed, whatever the numbers: a guessed 0.5 would otherwise displace a stated 0.3. The plan says "the one of higher confidence is kept";
  this ranks a guess below any confidence read.
- **Tests first, seen failing.** 21 failed before the first code (a theme with an unreadable confidence was dropped, and nothing but a plain number
  was read); 13 more were added after the review and failed before the second change.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_theme
  engine.tests.test_themecheck`: 158 tests OK. `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 50 of `themeextract.py`, of which 17 of this increment, all caught and restored byte for byte (scratchpad
  `breaks_themeextract.py`). Four old break strings no longer matched the changed code and were updated, not dropped.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: the misreads above (1) and the merge rule (3), with tests for
  each. Recorded, not applied: `5 (50%)` is read by its first number (1.0), which is in the README as a known limit; the empty-text case is tested
  only through `_draft`, because the real answer check refuses an empty item; and the 0.5 for an unreadable confidence stays a guess,
  flagged as one. The reviewer found no path that drops a theme for its confidence and no way for the flag to fail the form of a flag (at most 3 flags
  in all against 10).
- **Not done.** B, C and D. No live call. No security review (none asked): a text from a model goes through a bounded regular expression and
  `textutil.clean` into a flag of at most 300 characters.

### Increment B (done; committed as 4914e53)

- **Done.** In `engine/kb/themeextract.py`: each block of a piece is headed `<block n, length characters>` with the whole length of the block's
  text in characters (a block shown cut, over 3,000 characters, still gives its whole length); the rules say how a span is measured (the lengths
  of its blocks added up, plus 2 for each blank line between two blocks) and that it must be at most `theme.MAX_EXCERPT` characters, a number read
  from the limit that `theme.anchor_of` checks and not copied, and that a theme with a longer span is thrown away; the old sentence about "about
  6,000 characters" is gone; the prompt version of the `theme` job is `v2`. Tests in `engine/tests/test_themeextract.py` (49 there, 160 over the
  three modules of the plan's verification) and the README. The form of the header is the plan's.
- **The arithmetic is the check's.** A test builds a conversion with `convert.build` and shows that the sum the prompt tells the model to make
  (lengths plus 2 for each blank line) equals `blocks[last].end - blocks[first].start`, and that `theme.anchor_of` accepts a span of exactly that
  many characters and refuses one character fewer, for four spans. The reviewer read `theme._between` and `convert.build` and confirmed it.
- **Tests first, seen failing.** 6 failed before the code (no length in the header, no rule, the version `v1`).
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themeextract engine.tests.test_theme
  engine.tests.test_themecheck`: 160 tests OK. `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 55 of `themeextract.py`, of which 5 of this change, all caught and restored byte for byte (scratchpad
  `breaks_themeextract.py`); one old break string was updated to the new header.
- **What it costs, measured read-only on the library (no model, no network).** The longer headers make more pieces: the whole library goes from
  559 to 597 pieces (7 percent more), the largest book from 24 to 27 (the limit is 150), and the six trial books from 33 to 36 (Soft Actor-Critic 3
  to 4, Hamiltonian Monte Carlo 7 to 8, the networks paper 17 to 18).
- **A risk the plan's form carries, found on the six books.** The PDFs break into very small blocks: Soft Actor-Critic has 336 blocks with a
  median of 6 characters, Hamiltonian Monte Carlo 505 with a median of 9, the networks paper 813 with a median of 24 (the Wikipedia pages have medians
  of 135 to 196). No block is over the limit alone (the largest is 3,471 characters), so every theme can be named. But a span of 6,000 characters
  in a PDF can be dozens of blocks, and the rule asks the model to add up dozens of small numbers. The reviewer thinks the concern is real. The
  alternative is a running offset in each header (for example `<block 12, characters 8400 to 9240>`), so that a span is one subtraction and the
  blank-line rule goes. It changes the header the plan fixes, so it is not built. **For the owner:** ship B as planned and let the repeat
  trial (Increment D) measure the drops for the size bound, PDFs apart from web pages; if the PDFs still overrun, the running offset is the next
  change, as an amendment or a plan of its own. The other way is to amend the plan now and avoid a second live run.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Confirmed: the arithmetic is the check's; the length is in characters of
  the whole text; the prompt holds nothing contradictory. Recorded, not applied: (2) `pieces` skips a block with no text, which would make the
  model's sum miss it, but both parsers drop such blocks before `convert.build`, so it is dead code for real conversions; (4) a block shown cut
  lets the model name a block for text it did not see, as before; (7) a line of the book that looks like a header (`<block 3, 5 characters>`) can sit
  inside a block and mislead the model, bounded because code resolves the numbers and a wrong span is dropped, and the same class as the book's
  text steering the model.
- **Not done.** C and D. No live call. No security review (none asked): the book text is untrusted input to the prompt as before, and nothing from
  a reply reaches a path, a command or an unchecked field.

### Increment C (done, not committed; waits for the owner's word to commit)

- **Done.** `engine/kb/themecheck.py`: `avoid_words(text, df, size, title, topics, limit)` returns the words of the book's vocabulary as a list,
  strongest first (the words of the title, then of the card's topics, then the book's own frequent and rare words, the one used most first
  and alphabetical among equals), each once, none of them common, none of more than 40 letters, at most 80; with the limit lifted they are the
  words of `field_vocabulary` of that length or less (the two now share one helper for the "common" rule and one for the book's own words);
  `make_and_check_for_version` computes the list and gives it to the extraction. `engine/kb/themeextract.py`: the prompt has a third data section,
  `WORDS TO AVOID` (the words, or `none`), between the title and the text; a rule that the five parts must not use any word of the section or any
  other word that only people of the book's field use; a fixed worked example (a beekeeping text and its five parts in general words, named
  as the answer's keys), with the line that the answer is about the book's text and not the example; the words of the example's parts are left
  out of the list whatever the book is; `extract(..., avoid=())` gives every piece the same words; `make_for_version` alone gives none; the prompt
  version is `v3`. `engine/kb/textutil.py`: `words`, moved from `themecheck` with its regular expression and its fold unchanged (checked against
  the committed version). Tests in `test_themeextract.py`, `test_themecheck.py` and `test_textutil.py` (206 over the four modules of the
  verification), and the README.
- **Beyond the plan's list, decided here.** (1) A word of more than 40 letters is not put in the list (`AVOID_WORD_MAX`): a run of letters of
  any length in a book, used five times, could otherwise make the prompt too large. (2) The tokenizer moved to `textutil`, because the prompt and the
  check both use it and `themecheck` imports `themeextract`; `themecheck.words` is the same function.
- **Tests first, seen failing.** 18 failed before the code (nothing existed), and 1 more for the 40-letter cap.
- **Verification as run.** `python3 -W error::ResourceWarning -m unittest engine.tests.test_textutil engine.tests.test_themeextract
  engine.tests.test_theme engine.tests.test_themecheck`: 206 tests OK. `wb run code-work check`: no problems. No live call.
- **Deliberate breaks.** 107 across three scripts (4 of `textutil.py`, 40 of `themecheck.py`, 63 of `themeextract.py`), all caught and restored byte
  for byte. Several were first missed or stale and led to changes: the "half the books" rule was written twice and is now one helper; a test of
  the order of the book's own words passed when the order was wrong (its test word sorted first alphabetically anyway) and was changed.
- **What the list would have covered, read-only on the first trial's report and the library (no model, no network).** Of the 354 words that the first
  trial flagged in the six books, the list of 80 holds 296 (84 percent): all of them for four books, 78 and 79 percent for the Hamiltonian Monte
  Carlo paper (vocabulary of 158 words) and the networks paper (303 words). So a model that obeyed the list perfectly would still leave about a
  fifth of the first trial's flagged words in the two large books; the flag, which uses the whole vocabulary, would still find them.
- **Review (1 round).** The `reviewer` agent: no blocking finding. Applied: the example's labels are the keys of the answer (`problems:`,
  `methods:`), because a model could copy the singular names; the docstring says the bounds on the words (letters only, at most 40 letters, at most
  80) are the caller's, and that the token of `cardmake._prompt` is what keeps a word from closing a section. Recorded, not applied: the words
  come from the book's text, title and card, so a hostile book can choose which 80 single words reach the section (the same class as the book's
  text steering the model, accepted in the plan's Risks); a flag still fires on a word of the example's parts (barrier, sizes, members) that a book's
  vocabulary happens to hold, though the model is not told to avoid it; the rule does not say what to do when no general word exists.
- **For Increment D, from the review (measures to add to the script, outside the repository).** (a) Count the parts that are `none` (the model
  may dodge the rule by writing `none`, and `none` is no text, no mark and no flag), beside the parts stated and inferred, before and after.
  (b) Count flags that are only words of the example's parts apart from the others, so that they are not read as disobedience. (c) The check marks a
  part `inferred` when the excerpt does not support it, so if the rule makes parts vaguer the share stated may fall: that is a trade-off to read, not
  a fault.
- **Not done.** D. No live call. No security review (none asked): the words are letters only, bounded in number and length by the caller, given as
  data between delimiters that hold a random token no input holds.
