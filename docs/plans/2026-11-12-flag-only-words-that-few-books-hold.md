# Flag only the words that few books hold

Status: Proposed
Created: 2026-11-12
Candidate: none (a correction that follows from a finding of the library run: the flag fires on 77 percent of the themes; the roadmap `theme-weave` is not changed)
Specs: theme

## Goal

Make the flag on a theme's description (`field_words`) mean something. It is raised when a description holds a word of the book's field, so that the owner can see where a description is not in words of no field. On the library as it stands it is raised for 77 percent of the themes,
and it does not tell the descriptions that leak the field from those that do not. When this plan is done, a word counts as the field's only if few books of the library hold it; the flag is raised on far fewer themes, with nearly all of them holding a word that is specific to a few books; the themes already made have the
flags the new rule gives (without a call to a model); and the owner has read a sample of what the old and the new rule flag.

The measure behind the plan, a read-only count on 2026-11-12 over the 1,913 themes of the 175 books (the themes made with the extraction prompt `v4` and the check `v1`, at commit `83a4bb9`): 1,479 themes (77.3 percent) carry the flag. A flagged word comes from the card's topics (1,567 times), from the book's own frequent words (2,284) or from its title (318),
and 1,380 of the flagged-word occurrences are words that at least 15 percent of the books hold, because only the words of the book's text pass the filter on how many books hold them, while the words of the title and of the card's topics do not. If a vocabulary word counted only when fewer than N percent of the books hold it (and this applied to title and topic words as well), the share of
the themes flagged would be 4.0 percent (N = 1), 11.6 (2), 18.0 (3), 27.4 (5), 40.3 (8), 63.1 (15) and 69.5 (30). A sample of 20 descriptions read by the owner's session on 2026-11-12 found the words flagged in the sample mostly ordinary ones (`outcomes`, `classical`, `honest`, `party`, `segment`, `target`, `walk`), with a few real leaks
(a description of algebraic graph theory that says "algebraic invariants"). There is no ground truth of leak or no leak, so 5 percent is a call and not a measurement; this plan adds a sample for the owner to read against it.

## Scope

- A rule for the flag: the vocabulary of the flag is the vocabulary of the book's field (the words of its title, its card's topics and its own frequent rare words, as now) **less any word that at least 5 percent of the books of the library hold**. Words that nobody else holds, and words that few books hold, are kept.
- The check of the themes of a book uses that vocabulary for the flag. The words the extraction is told to avoid are unchanged.
- A command that gives the themes already made the flags of the new rule without a call to a model: `themes-reflag plan` (read-only: counts) and `themes-reflag run` (a new generation for each book whose flags change).
- The statement of the flag in the theme spec and in the engine README, with the figure.
- A sample of themes flagged by the old rule and by the new, for the owner to read, kept outside the repository with its hash.
- The run of `themes-reflag run` over the library, on the owner's word after the plan is shown.

## Non-goals

- Changing what the extraction is told to avoid (`avoid_words`), the prompts, the check of support, the form of a theme or of a flag (the kind stays `field_words`), or the config. A change that makes the model avoid more words costs nothing, and flagging them was the noise.
- Limiting the flag to some parts of a description, a count of the words found, or a weight for each word. Deferred (below).
- Judging whether a description is good, or a measure of leak with a ground truth. The sample is read by the owner; the plan records the reading.
- A run of the models. Nothing in this plan is sent to a model.
- Changing the skip rule or the records of `themes-run`: a generation made by `themes-reflag` keeps the `made` of its themes, so `themes-run` still skips the book.

## Assumptions and constraints

- **My calls, not yet the owner's.** (The owner said yes to the threshold of 5 percent as a recommendation, and to the re-flag in this plan; the others are mine.)
  1. **The threshold is a constant, `FLAG_SHARE = 5`.** A word counts for the flag only if the number of books that hold it (`df`, which counts the book itself) times 100 is less than 5 times the number of books. On the library of 175 books that is a word held by at most 8 books. The share is of the active books with a conversion in use that `library_frequencies` counts.
  2. **It applies to every word of the vocabulary**, including the words of the title and of the card's topics. A word in the title that 40 books hold is not flagged.
  3. **One function makes the vocabulary of the flag** (`flag_vocabulary(text, df, size, title, topics)`), and `field_vocabulary` stays as it is, so the avoid list is made as before.
  4. **A flag is recomputed from the descriptions, not stored with its rule.** The flags of a theme other than `field_words` (`no_description`, `confidence_unreadable`) are kept as they are; the `field_words` flag is replaced by the new one or left out. The order of the flags is the order in which the check puts them (the others, then `field_words`).
  5. **`themes-reflag run` files a new generation of a book only if a flag changes.** A book whose themes already have the flags of the rule files nothing, so the command can be run again. The older generations stay. The themes keep everything else they have (`made` included).
  6. **It takes no model, server or address**, as `themes-run` does, and it holds the shared lock (the lock of the card queue and of the theme run, taken through the folder of the journals), so it never runs with them against one index root.
  7. **A book is left out of the re-flag, with the reason**, when it is not active, has no theme, has no card that can be read or has no conversion in use (the vocabulary cannot be made).
  8. **The sample** is of up to 40 themes, chosen so that it can be made again: the population is every theme of the newest valid generation of every book that has themes, in the order of the book id and then the theme id. Stratum one is the themes that the old rule flags and the new does not; stratum two is the themes that the new rule flags. From each stratum, in that order,
     `random.Random(12).sample` takes 20 (a fresh generator with the seed 12 for each stratum); a stratum with fewer than 20 gives all it has, and the report says so. Each theme is shown with its book title, its title, its five parts and the words flagged by each rule. The report names the seed, the size of each stratum and the ids chosen. It is written outside the repository, mode 600, and cited by its hash.
- A defect found in the run stops it; the plan is not widened to get past it.

## Completion criteria

1. The vocabulary of the flag leaves out the words that at least 5 percent of the books hold, including the words of the title and of the topics, and the words to avoid are as they were. Tests show each.
2. A theme made and checked now carries the flag by the new rule; the existing tests of the check still stand or are changed with a stated reason.
3. `themes-reflag plan` counts, with no write, the books whose flags would change, the books left out with the reason, and the themes flagged before and after; `themes-reflag run` files a new generation for exactly those books, changes only the `field_words` flags, keeps the older generations, can be run again without filing anything, and holds the lock. Tests show each.
4. The re-flag has been run over the library on the owner's word, and the Result holds the counts before and after, a read-only check of the library afterwards, and the hash of the report outside the repository.
5. The sample has been written outside the repository with its hash (its seed, strata and ids in it), the owner has read it, and the Result holds the owner's reading (or says it is not given).
6. The owner has the Result and has decided what comes next.

## Increments

### Increment A — The rule

**Outcome:** the check of a book flags only the words of its field that fewer than 5 percent of the books hold.
**Dependencies:** none.
**Affected areas:** `engine/kb/themecheck.py` (`FLAG_SHARE`, `flag_vocabulary`, `make_and_check_for_version`); `engine/tests/test_themecheck.py`; `docs/specs/theme.md` (a statement of what is true now); the engine README (the paragraph on the words of the field, with the figure).
**Steps:**
1. Write the tests first and see them fail: a word of the title that 40 of 100 books hold is in the vocabulary and not in the flag vocabulary; a word held by 4 of 100 books is in both; a word held by exactly 5 of 100 is not in the flag vocabulary; a word held by no other book is in it; a word of a topic held by 10 of 100 books is not; the common half of the books is left out as before;
   `avoid_words` returns what it returned (the same list for the same input); `make_and_check_for_version` flags a description by the flag vocabulary and returns the number of words of it; a description holding only a word held by many books is not flagged; the flags other than `field_words` are as they were.
2. Write `flag_vocabulary` and use it in `make_and_check_for_version`; run the tests; break the code on purpose, one break at a time (the threshold left out, `<=` for `<`, the title words exempt, the topic words exempt, the avoid list made from the flag vocabulary), and restore each.
3. Write the statement in the spec and the paragraph in the README (the rule, the figure of 27 percent against 77 percent from the count above, and that 5 percent is a call).
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themecheck engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themerun` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-flag-only-words-that-few-books-hold#A`.

### Increment B — The re-flag of the themes already made

**Outcome:** `themes-reflag plan` and `themes-reflag run` give the themes already made the flags of the new rule, with no call to a model.
**Dependencies:** A.
**Affected areas:** a new `engine/kb/themereflag.py`; `engine/kb/__main__.py` (the parser and its handler); `engine/tests/test_themereflag.py`; `docs/specs/theme.md`; the engine README.
**Steps:**
1. Write the tests first and see them fail, on a store with books of each kind (a book with themes whose flags change; one whose flags do not; one with no theme; one not active; one with no card that can be read; one with no conversion; a book whose newest generation is damaged and whose older one is valid): `plan` writes nothing and counts the books to change, the books left out with the reason and the themes flagged before and after;
   `run` files one new generation for each book to change, with only the `field_words` flags changed and every other key of every theme equal, leaves the older generations as they were, files nothing for a book whose flags already match, files nothing on a second run, holds the lock (a second holder is refused), and stops on an unexpected error of a book by reporting it and going on to the next; the parser takes no model, server or address.
2. Write `themereflag.plan` and `themereflag.run` and wire the command; run the tests; break the code on purpose, one break at a time, and restore each.
3. Run `python3 -m kb themes-reflag --help` and `python3 -m kb --help` to show the command line.
4. Read the plan of the real library, read-only: the books to change and the themes flagged before and after; record them in the Result.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themereflag engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_themerun engine.tests.test_cardqueue` and `wb run code-work check`. No live call, and nothing filed in the library.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-flag-only-words-that-few-books-hold#B`.

### Increment C — The run over the library and the sample

**Outcome:** the themes of the library have the flags of the new rule, and the owner has a sample to read.
**Dependencies:** B. The owner's word, given after the plan is shown.
**Affected areas:** the library's generations of themes (a new one for each book whose flags change); nothing tracked except this plan's Result.
**Steps:**
1. Run `themes-reflag plan` and show the owner what it prints: the books and the themes it would change, and that nothing is sent to a model and a new generation is filed for each book that changes (the older ones stay). Wait for the owner's "run it".
2. Run `themes-reflag run`; keep its report outside the repository, mode 600, with its sha256.
3. Check the library read-only: for each book that changed, the newest valid generation is the new one, none is damaged, the themes equal the old ones but for the `field_words` flags, and a second `themes-reflag plan` finds nothing to change.
4. Write the sample of assumption 8 outside the repository, mode 600, with its sha256, and give it to the owner with my reading marked as mine.
5. Write the Result with the counts, the check, the hashes and the owner's reading when given.
**Verification:** the report of the run, the read-only check of step 3 and the second `plan`.
**Evidence:** the Result of this plan, committed with the trailer `Plan: 2026-11-12-flag-only-words-that-few-books-hold#C`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increment B uses the check of A, so the tests of A are run again in B with the others. The run of C changes the library and not the code. The card tests are run once in B (`engine.tests.test_cardqueue`) because the lock is shared and is not changed.

## Risks and sensitive actions

- **Filing a new generation for many books** (Increment C): about as many as the flags change for (up to 175). A generation is never changed or deleted by this, the older ones stay, and a reader gets the newest valid one. It changes what a reader sees of the flags, so the owner's word is asked after the plan is shown.
- **Nothing is sent to a model**, so nothing leaves the machine.
- **The threshold is a judgement.** 5 percent flags 27 percent of the themes; 3 percent flags 18 percent and 8 percent flags 40 percent. The constant can be changed and the re-flag run again, which is why the command is idempotent.
- **A change of the rule makes older and newer themes differ in how they were flagged** unless the re-flag is run. The themes made after Increment A and before the run of C carry the new rule already; nothing records the rule in a generation, so a later change of the rule needs another re-flag run.
- **Security review checkpoint:** the command reads and files through the existing functions of `theme` and `cardstate` and takes no input from a book beyond what the check already reads, so I do not propose a security review; the owner is asked once, before Increment A, and a review runs only if the owner asks.

## Review record

- **Reviewer:** the review engine (`plan-45f0fbe9163d794b`), model `gpt-5.6-terra`. Rounds used: 2 of a bound of 3; the second converged with no meaningful finding.
- **Applied (2):** the candidate line made `none` with the reason that the plan corrects a finding of the library run, because the roadmap `theme-weave` still says in its current state that themes are not built, and a change to a roadmap is the owner's checkpoint, so the roadmap is not edited here (R1-F1);
  the sample made reproducible: the population and its order, the seed 12 for each stratum, the rule when a stratum has fewer than 20, and what the report records (R1-F2).
- **Rejected:** none.
- **Left for the owner:** the stale "Current state" paragraph of `docs/roadmaps/theme-weave.md` (it says themes are not built; 1,913 themes of 175 books exist); whether to ask for a security review of the re-flag command (not asked; I do not propose one); whether to approve the plan.

## Deferred work

- Limiting the flag to some parts of a description, a count of the words found, or a weight for each word.
- A ground truth of leak or no leak, and a threshold chosen against it.
- Recording the rule in a generation, so that a flag says which rule raised it.
- The PDF size bound, the check's leniency and the other open items of `2026-11-11-run-the-theme-extraction-over-the-library`.

## Result

### Increment A (the rule; committed)

- **Done.** In `engine/kb/themecheck.py`: `FLAG_SHARE = 5` and `flag_vocabulary(text, df, size, title, topics)`, the field's vocabulary less any word that 5 percent or more of the books hold (`df.get(w, 0) * 100 < FLAG_SHARE * size`, so exactly 5 percent is not kept and a word no book holds is); `make_and_check_for_version` builds the vocabulary of the flag with it
  and the words to avoid with `avoid_words`, which is unchanged, as is `field_vocabulary`. The module docstring says so. `vocabulary_words` in the result of `make_and_check_for_version` is now the size of the flag vocabulary (nothing else reads it). `docs/specs/theme.md`: one [proposed] statement under "What a theme holds" (the rule, "would flag about 27 percent", that the themes already made keep the earlier flags until flagged again).
  `engine/README.md`: the paragraph on the words of the field, with the counts of the plan, and a note that the older figures there are those of the flag before the limit.
- **Verification as run.** Tests first: the new tests failed because `flag_vocabulary` did not exist. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themecheck engine.tests.test_themeextract engine.tests.test_theme engine.tests.test_themerun` printed `Ran 305 tests ... OK`; `wb run code-work check` clean. No existing test of the check had to be changed: one was added for the new behaviour
  (a word held by a third of the books is not flagged and is still avoided).
  Deliberate breaks: 11 one-line breaks of `themecheck.py` (the share left out, `<=` for `<`, the share of 100 and not of the library, shares of 10 and 3 percent, title words exempt, topic words exempt, a word no book holds dropped, the check flagging by the whole vocabulary, the avoid list made from the flag vocabulary, the vocabulary itself narrowed): all caught; file restored identical (sha256 prefix `936821ec0739`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: the spec says "would flag" and that the stored themes keep the earlier flags (it said "flags"); the README no longer points to `themes-reflag` as if it existed; the test of a library of one now names what it shows (only title and topic words that no book holds are kept) and a library of none is tested;
  the comment on `FLAG_SHARE` says "fewer than"; `vocabulary_words` has a comment saying it is the flag vocabulary. Noted, not changed: `avoid_words` drops words longer than 40 letters while the docstring says "the whole vocabulary" (an imprecision that was there before).
- **Not run.** The whole suite; any live call; nothing was filed in the library. No security review (not asked; the reviewer named no concrete exposure: a filter over words counted from the library).
- **Not done.** Increments B and C.

### Increment B (the re-flag of the themes already made; committed)

- **Done.** New `engine/kb/themereflag.py` and the command `python3 -m kb themes-reflag plan|run` in `engine/kb/__main__.py` (no model, server or address; `plan` opens the library to read, `run` to write; exit 1 when a book failed). For each active book with a card, a conversion in use and themes, the newest valid generation is read; for each theme the flags other than `field_words` are kept in their order and the flag of the rule now (`themecheck.flag_vocabulary`, `field_flag`) is put after them;
  a book whose flags change gets its themes filed as the next generation with everything else as it was (`made` included), and the older generations are never changed; a second run files nothing. `run` holds the shared lock (`cardstate.lock` through the folder of the journals), works the survey out under it, and a book that fails does not end the run (a fixed reason, or the kind of an unexpected error).
  Books left out are named with a reason: `inactive`, `no_themes`, `damaged` (every generation fails its check), `no_card`, `no_conversion`, `unreadable` (a book whose reading raised: the others go on). `docs/specs/theme.md`: the statement of the flag says what `themes-reflag` does. `engine/README.md`: a paragraph "The flags again", and the list of reasons.
- **The plan of the real library, read-only (step 4).** `python3 -m kb themes-reflag plan` on 2026-11-12, run twice (before and after the review's changes), the same both times: **166 books would change, 9 would not, 1 is left out (`no_themes`)**; 1,913 themes, **1,479 flagged now and 525 (27.4 percent) after**, in a library of 175 books. This matches the count that made the plan (525 under 5 percent). 47 of the 166 books would lose every flag; none gains flags in a book that was flagged less (no book has more themes flagged after than before). Nothing was filed.
- **Verification as run.** Tests first: the module did not exist. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themereflag engine.tests.test_themecheck engine.tests.test_theme engine.tests.test_themerun engine.tests.test_cardqueue` printed `Ran 317 tests ... OK` (the card queue shares the lock; it is not changed); `wb run code-work check` clean.
  `python3 -m kb themes-reflag --help` and `python3 -m kb --help` show the command. Deliberate breaks: 26 one-line breaks of `themereflag.py` and `__main__.py` (the kept flags dropped or the field flag kept, the new flag first or none, a book that does not change filed or one that changes not filed, an inactive book not left out, each reason, the lock not held, the whole vocabulary used for the flag, a failure ending the run, the message of an error shown, the old themes filed, the counts of themes and of flags, the title not cut, the plan opening the library to write, the run opening it to read, no exit code): all caught after two tests were added (themes counted one by one; a long title)
  and one useless break replaced; files restored identical (sha256 prefixes `4dc978832b8c`, `4140bfcb1daf`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: a book that cannot be read, or whose survey raises, is left out with the reason `unreadable` and the others go on (before, one such book would have stopped the plan); a library whose generations all fail their check is `damaged` and not `no_themes`; a test that did not make anything fail was removed (its case is covered by two others); the lock test checks the message.
  Noted, not changed: a process that does not take the lock (a conversion change, a card edit) could move the state between the survey and the filing; the generation filed then has flags from the earlier vocabulary and the next run would correct it; `plan` takes no lock and may show counts from a mixed moment if a run of the theme extraction is going.
- **Not run.** The whole suite; no live call; nothing was filed in the library. No security review (not asked; the reviewer named no concrete exposure).
- **Not done.** Increment C: the run over the library and the sample, on the owner's word after the plan is shown.

### Increment C (the run over the library and the sample; the owner's reading is pending; committed)

- **Run.** `themes-reflag plan` was shown to the owner (166 books to change with 1,874 themes, 9 unchanged, 1 with no themes; flagged 1,479 now and 525 after; no model, a new generation for each changed book, the older ones kept) and on the owner's word ("run it") `python3 -m kb themes-reflag run` was run at commit `e0e5827`; it exited 0.
  The report is kept outside the repository, mode 600, sha256 `67d59034e782583c0c8737a751527a393e85a9abb24a8b2ef459b9a8dc89c101`.
- **Outcome.** 166 books filed, none failed. Themes 1,913, flagged 1,479 before and **525 (27.4 percent) after**; 47 of the 166 books lost every flag; no book has more themes flagged after than before.
- **Verified against the library, read-only.** Generation lists: 166 books `[1, 2]`, 9 books `[1]`, 1 book with none; for each of the 166 the newest valid generation is 2, no generation is damaged, the themes of generation 2 equal those of generation 1 in every key but `flags`, and the flags other than `field_words` are equal; the themes in the newest generations number 1,913 with 525 flagged;
  a second `themes-reflag plan` finds 0 books to change (175 unchanged, 1 left out as `no_themes`).
- **The sample** (assumption 8): seed 12 for each stratum; 954 themes flagged by the old rule and not by the new, 525 flagged by the new; 20 chosen from each, with the ids in the file. Kept outside the repository, mode 600, sha256 `602cc8e476e9c1b8d9f2f98c1e75ae4b264c5324c5a7d6de22d59fde9caa59de`. Order of the population: the book id, then the number of the theme id (`t2` before `t10`).
- **My reading of the sample, marked as mine and not the owner's** (a judgement of whether a flagged word is a word of the book's field, with no ground truth): of the 20 themes that **lost** their flag, about half were ordinary words (`safety`, `negative`, `training`, `communication`, `memory`, `shared`, `sentence`, `inventory`) and about half were real words of the field that the rule dropped because other books hold them too
  (LoRA: `matrices`, `rank`; the Ising model: `phase`, `transition`, `temperature`, `correlations`; Lotka–Volterra: `differential`, `nonlinear`; statistical mechanics: `microscopic`, `macroscopic`; the Attention paper: `dropout`, `optimizer`; the entropy page: `entropy`; the PID page: `oscillations`, `steady`; TRPO: `policy`, `policies`; the finite element page: `mesh`). Of the 20 that **kept** a flag, about 13 held a word specific to the book
  (`surprisal`, `callable`, `determinant`, `disparity`, `rays`, `chaining`, `slots`, `axial`, `separable`, `finetuned`, `vine`, `courier`, `timestamp`, `tumor`, `pulse`) and about 7 an ordinary one (`mental`, `competitor`, `passage`, `possession`, `tactics`, `killing`, `prompts`). So the rule removed most of the ordinary words and also about half of the real field words of the books in the clusters of the library (physics, machine learning), where 5 percent or more of the books share the field's words; a threshold on the share of books cannot tell the words of a field from ordinary words when the library holds several books of that field.
  The flag is "a reason to look", so this is a trade of recall for precision, which is the owner's to judge.
- **The owner's reading:** not given when this was written.
- **Decision (2026-11-12).** On the owner's word ("Go with your recommendation") after the report of the run and of my reading of the sample, **the limit of 5 percent stays for now** and the flag stays a rough reason to look; a different measure, or another limit, is not started. The reasons given were that the flag is not read by anything downstream yet and that the re-flag is cheap to run again if the rule changes.
  The owner has not given a reading of the sample; the file is kept for it. Criteria 1 to 4 are met with the evidence above; criterion 5 (the owner's reading) is open, and criterion 6 is met by this decision.
- **For the owner to decide:** whether 5 percent stays; whether a different measure is wanted (for example a word's share within the books that are alike rather than within the whole library, or a count of how many books of the library hold it against how many of its own cluster), which would be a new plan; the open items of `2026-11-11-run-the-theme-extraction-over-the-library`.
- **Not done.** No push. No security review (not asked). The owner's reading of the sample.
