# Limit the themes of one book in a theme search

Status: Proposed
Created: 2026-11-13
Candidate: theme-weave#theme-per-book
Specs: docs/specs/theme.md

## Goal

A search of the themes by meaning (`python3 -m kb theme-search`) can limit how many themes of one book a page holds, so that a page shows more books. After this plan the limit is on by default at 2 themes of one book, an option sets another number or switches the limit off, and with it off the search returns exactly what it returned before. This follows the owner's reading of the eight searches (the Result of `2026-11-12-search-the-themes-by-meaning`, "The owner's reading of the eight searches"), in which one book often filled most of a page, and the owner's choice of a limit for each book (option A).

## Scope

- `engine/kb/themevectors.py`: `search` takes `per_book` (a whole number from 0 to the maximum limit; 0 switches the limit off; default 2). The ranking is unchanged. The limit is applied to the ranked list: a theme is kept if fewer than `per_book` themes of its book (`book_id`) are already kept, in the order of the ranking, until `limit` results are kept. The reply gains two keys: `per_book` (the number used, 0 when off) and `held_back` (how many of the themes searched are over the limit of their book: each theme, over the whole ranking and whatever `limit` is, that comes after `per_book` themes of its book; it is 0 when the limit is off, and a page can be shorter than `limit` because of it).
- `engine/kb/__main__.py`: the option `--per-book N` of `theme-search`, with the default of 2 and `0` to switch the limit off.
- Tests in `engine/tests/test_themevectors.py`, the paragraph of `theme-search` in `engine/README.md`, and one clause in `docs/specs/theme.md` (line 163 onwards).

## Non-goals

- A separate view of the best theme of each book, links between themes and the walk (the candidates `theme-links` and `theme-walk`).
- A limit in the keyword search, the card search or the search of the cards by meaning.
- Any change to the vectors, the file, the scores, the ranking, the counts (`themes_searched`, `stale`, `without_vector`) or what a result holds.
- Dropping any of the seven texts of a theme.
- Counting a book by anything but its `book_id` (a book with two versions counts once).

## Assumptions and constraints

- The default of 2 is the agent's suggestion in the owner's reading of the eight searches; the owner approves it by approving this plan. A default that hides themes changes what a call with no option returns, so the reply says what was held back.
- The only callers of `themevectors.search` are the command line and `engine/tests/test_themevectors.py` (checked with `grep` on 2026-11-13). No other command reads its results.
- The stored query vectors and the 50 results of each of the eight searches of `2026-11-12-search-the-themes-by-meaning` (Increment B-A, the baseline kept outside the repository, cited there by sha256) allow a check against the real file with no call to any model, as Increment B-A did.
- Nothing is sent to any model by this plan; the live check is not repeated, and the file of the vectors is only read.

## Completion criteria

1. With `per_book` 0 the search returns exactly what it returned before the change, in the tests and against the stored baseline of the eight searches on the real file (same themes, same order, same scores, same counts), and the reply holds `per_book` 0 and `held_back` 0.
2. With a number N, no book has more than N results, the results that remain are in the same order as the ranking, and the page is filled up to `limit` from further down the ranking when themes were held back.
3. `held_back` and `per_book` are in the reply and are correct (`held_back` over the whole ranking, as the Scope says); the other counts do not change.
4. A `per_book` that is not a whole number (a float, a string, a boolean, `None`) or is out of range is refused before the query is sent, as a bad `limit` is; the option of the command line passes the number and the default is 2.
5. The README and the spec say what the option does, in the form the other options are described.

## Increments

### Increment A — The limit for each book in the theme search

**Outcome:** a theme search holds at most `per_book` themes of one book on a page (2 by default), says what it held back, and with 0 returns exactly what it returned before.
**Dependencies:** none. The search and the file exist (`2026-11-12-search-the-themes-by-meaning`, committed).
**Affected areas:** `engine/kb/themevectors.py` (`search` and its docstring), `engine/kb/__main__.py` (the `theme-search` option and its call), `engine/tests/test_themevectors.py`, `engine/README.md` (the paragraph of `theme-search`), `docs/specs/theme.md` (one clause).
**Steps:**
1. Write the tests first and see them fail: with `per_book` 0 the same themes, order, scores and counts as before (the existing expectations, called with 0); with 1 and 2 over a fixture of several books with several themes each, no book above the limit and the order of the ranking kept; the page filled from further down the ranking when themes are held back, and `limit` still the most results; a book with two versions counted once; `held_back` correct over the whole ranking, including when the ranking ends before `limit` is reached (three themes of one book, `per_book` 2, `limit` 10: two results shown and `held_back` 1), when themes after the last result shown are over the limit, when nothing is held back, and 0 when the limit is off; `per_book` and the other counts in the reply; a `per_book` that is a float, a string, a boolean, `None`, negative or above the maximum limit refused before any query is sent (the embedding call not made); the command line option read, with the default 2 and 0 passed through.
2. Add `per_book` to `search` and the walk over the ranked list; refuse a bad value with the same message form as the limit, before the query is sent; add the two keys to the reply; add the option to `theme-search`. Existing tests that rely on more than 2 themes of one book on a page pass `per_book=0`, and each such change is listed in the Result.
3. Deliberate breaks, each restored byte for byte, each caught by the tests: the limit not applied; applied with the wrong comparison (one too many, one too few); applied before the ranking; the page not filled from further down; the limit counted by `theme_id` or by `version_id` and not by `book_id`; `held_back` not counted, or counted only up to the last result shown, or counted when the limit is off; `per_book` not checked, or a boolean accepted; the check made after the query is sent; the default not 2; 0 not switching the limit off; the option of the command line not passed; the new keys missing.
4. With no call to any model: against the real file (read only, the sha256 of the file before and after), with the stored query vector of each of the eight searches in place of the embedding call, check that `per_book` 0 returns the stored 50 results with the same order, scores and counts, and show, for each search, how many books the first 10 results hold with 0 and with 2 and what `held_back` is. Where fewer than 10 results can be formed from the stored 50 when the limit is on, say so and do not claim a comparison.
5. Update the paragraph of `theme-search` in `engine/README.md` (the option, the default, `0`, the two keys) and add one clause to the spec; run the document check of the project.
6. Ask for the `reviewer` agent (mandatory), judge its findings with `evaluate-findings`, and record the outcome in the Result.
**Verification:** `python3 -m unittest engine.tests.test_themevectors` (the nearest tests and the tests of the module it changes), and the module that reads the command line options if the tests of the command line are in another module (`grep` shows only `test_themevectors.py` calls `theme-search` today); the deliberate breaks of step 3 each caught; the real-file check of step 4 with the file unchanged. No wider run: nothing outside `themevectors.py` and the option of `theme-search` changes, and no other command calls the search.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-limit-the-themes-of-one-book-in-a-theme-search#A`, and the numbers of steps 3 and 4 in the Result.

## Verification for the plan as a whole

With one increment, the verification of Increment A is the verification of the plan. The tests of the search by meaning that Increment B-A and B-B recorded still stand unless a test of them had to change in step 2 of Increment A; each such change is listed in the Result and the tests of that module are run as a whole. Nothing wider is run: the file of the vectors, the build and the keyword search are not touched.

## Risks and sensitive actions

- **The default changes what a call with no option returns.** A call that used to return 10 themes of one book now returns at most 2 of that book and fills the page from further down. This is the point of the plan; `held_back` says it, and `--per-book 0` gives the old results. No stored result or command reads the old form.
- **A book counts by `book_id`.** A book whose `book_id` is shared by different books would be limited together; the file's `book_id` is the library's id of one book, so this is not expected, and the test over a fixture shows it.
- **No new input reaches a privileged use.** The option is a whole number checked before the query is sent, the `book_id` is a value of the file that the search already checks and uses as a key, and no text is added to the output. A security review is not recommended for this plan and runs only if the owner asks.
- No call to any model, no write outside the repository files named, no push.

## Review record

- **Reviewer:** the Codex review engine (`wb run review-engine review-plan`; model `gpt-5.6-terra`), asked for by the owner on 2026-11-13. Only the plan file was sent, with what the reviewer read of the project from it.
- **Rounds:** 2 of 3 (ceiling 5). Converged at round 2 with no meaningful finding.
- **Applied (1):** R1-F1 (major): `held_back` counted only up to the last result shown, so with three themes of one book, `per_book` 2 and `limit` 10 it said 0 while one theme was hidden. It is now defined over the whole ranking, whatever `limit` is; the Scope, the tests of step 1, the breaks of step 3 and completion criterion 3 say so.
- **Rejected:** none.
- **Left for the owner:** whether to approve the plan; whether to ask for a security review (not recommended in the risks; not asked).

## Deferred work

- A separate view of the best theme of each book: left to the plan for links and the walk, if the walk needs it.
- Whether the default of 2 suits an agent that searches across fields: the owner's decision after use; a different default is a one-line change.
- The same limit in the card search by meaning, if the owner wants it there.

## Result

Empty until work starts.
