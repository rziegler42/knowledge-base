# Fix the bound of a locator, the control characters and the output of the helper

Status: Proposed
Created: 2026-11-20
Candidate: none (a correction that follows from a finding: the second security review of 2026-11-20, of the helper's locator codes, and experiments that I ran by hand because the reviewer's hook allowed none)
Specs: docs/specs/knowledge-base.md ("Reading side": the helper and the locators)

## Goal

The plan `2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command` made the locators of the helper's replies safe to copy into a single-quoted command, and its live check in `kb-scratch` passed. A second security review of the final helper (the `security-reviewer` agent, 2026-11-20) found no Critical, High or Medium problem, but **it could run no experiment** (its hook refused every command: "the command matches none of the agent's pinned commands"), so its findings are reasoning. I then ran experiments on the helper as the tests load it. They show that the coding itself is sound and found one regression of mine and two small gaps:

- **Sound (tested):** 200,000 random and adversarial strings (the four characters, the codes, `%2527`, a lower-case `%5c`, control characters, NUL, U+2028, a lone surrogate, non-ASCII, an emoji, look-alikes of the apostrophe) satisfy `read_codes(write_codes(s)) == s`, and the coded form never holds an apostrophe, a double quote or a backslash; twelve hostile headings (among them `x'; touch y; '`, quotes, a backslash, `%27` as text, accented and CJK letters, an emoji, a heading of 3,000 characters), taken out of a helper reply as an agent copies them and put between single quotes in a real `sh -c`, are always one argument and run nothing.
- **L5, a regression of mine (tested).** The helper now measures the bound of 2000 on the string it sends to the engine, which is written with ASCII escapes, so a non-ASCII character counts six characters. A locator with a heading of 480 CJK characters is 1,670 bytes in UTF-8, would have passed before the codes (the bound was on the bytes the agent gave), and is now refused with "longer than 2000 characters once its codes are taken back". A page with long non-English headings cannot be read. This breaks the statement of the plan that a locator the engine gave is never refused for its codes.
- **L1, a gap (tested).** If a control character (newline, tab, CR, NUL, ESC) were in a string of a locator, JSON would write it with a backslash, which is what the harness rewrites. The engine cleans its headings (`textutil.title`, `locator.shown`), so this cannot happen today; it would if a future path skipped that cleaning.
- **L2, a gap (tested).** Replies that hold a locator are written with non-ASCII characters as themselves, so a stream that cannot encode them (a non-UTF-8 output) ends the helper with a `UnicodeEncodeError` traceback. The live check printed non-ASCII characters without error, so this needs an unusual setting.
- **L4, read only.** `pose-a-problem` and `walk-from-themes` lack two clauses that `find-a-passage` has: "if you cannot be sure of a locator, do not run the read" and "keep the locator on one line".

When this plan is done a locator at the helper's old bound is accepted whatever its characters, a control character can never put a backslash into a locator, a stream that cannot carry a reply gets a clear failure and no traceback, and the three skills that pass a locator say the same things.

## Scope

- `package/kb/helper/kb`: the bound of a locator in `read` is measured as before the codes (the UTF-8 bytes of the compact JSON of the decoded locator, written as the agent gave it), while the engine still gets the ASCII form; the strings of a locator pass through `plain` before they are coded; `main` turns a `UnicodeError` of the output into a failure with a message.
- `engine/tests/test_package.py`: tests for each, with the fake engine of `HelperCase`.
- `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md` and `walk-from-themes/SKILL.md`: the two clauses; and their tests.
- The Result of `docs/plans/2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command.md` (a paragraph that records the second review, what was tested and where each finding is closed; its Result may change without a new approval).

## Non-goals

- Any file of `engine/kb`, any command, the module declaration, or the crawl's approval. The helper is outside the engine's fingerprint.
- Quoting `<book>`, `<version_id>` and `REF` in the skills' call templates (the review's L3). They are written by the engine and checked by the helper (`fullmatch`) after the shell has read them; the risk needs the index database to hold an id the engine did not write; the change touches every call template and test of four skills. Recorded as deferred.
- Coding the `raw` field of an `unknown_kind` reply (it echoes the locator the agent passed, after decoding, and is not an argument of `read`), writing locators on one line in the replies, taking a locator from standard input, and the gate reading heading text (L6, an availability matter outside the helper). Recorded as deferred.
- The owner's copy of the package in `kb-scratch` and its approval, upgrade and re-render (the owner's, in a terminal).

## Assumptions and constraints

- The coding stays as it is: the four characters become `%25`, `%27`, `%22` and `%5C` in the strings of the objects under `locator`, `next` and `anchor`, and `read` takes them back in one pass. Nothing in this plan changes a code.
- **The bound.** Before the codes the helper checked the bytes of the locator as the agent gave it against `MAX_LOCATOR` (2000), after the parse. The plan keeps that meaning: the bound is the UTF-8 length of `json.dumps(decoded, separators=(",", ":"), sort_keys=True, ensure_ascii=False)`, which does not count the codes and counts a non-ASCII character as its bytes. The string sent to the engine stays the ASCII form (`ensure_ascii` true, as now), which is at most 12 times the bound and far below the engine's own bound of 100000 characters. The parse limit of 3 times the bound stays (the codes make the text at most three times as long).
- `plain(s)` with nothing to keep removes control, format, unassigned and line-separator characters, as the helper does to all engine text. A locator string that the engine cleaned holds none of them, so for a real reply nothing changes; a heading that did hold one no longer matches the page by its path and is found by the words of its excerpt (the engine's own fallback).
- The helper's entry point passes `sys.stdout` as it is. `main` already refuses or fails with a message for an `OSError`; a `UnicodeError` of `out.write` happens before anything is written, because the stream encodes the whole text first.
- The reviewer's hook refused every command; the experiments of this plan are my own, on the helper loaded as the tests load it. They are repeated as tests here. What the harness does with other typed text is shown only by the live check of the earlier plan.

## Completion criteria

1. `read` accepts a locator whose decoded compact form is at most 2000 bytes in UTF-8, whatever its characters: tests with 480 CJK characters (about 1,670 bytes), with a locator of exactly 2000 bytes that holds apostrophes, and with one of 2000 bytes made of non-ASCII characters; it refuses one byte more, with a message that names the bound in bytes; the engine gets the ASCII form and the same locator as the agent gave.
2. The strings of a locator in a reply never hold a control character, a line separator or a character that `plain` removes, so the text of a locator holds no backslash even when the engine's reply held such a character in a locator string (tests with newline, tab, CR, NUL, ESC, DEL, U+2028, a lone surrogate, and a bidirectional mark, for `locator`, `next` and an `anchor` with `start` and `end`); the other strings of the reply are as before.
3. When the output stream cannot encode the reply, `main` returns 1 with a message on the error stream that says what to set (a UTF-8 locale), writes nothing to the output, and raises no traceback; with a UTF-8 stream nothing changes (a test with a stream of ASCII encoding, and the whole existing set).
4. `pose-a-problem` and `walk-from-themes` say what `find-a-passage` says: if you cannot be sure of a locator, do not run the read and mark the book (the lead) unread; keep the locator on one line; with tests that hold the sentences.
5. Each new rule has a deliberate break that a test catches (the bound measured on the ASCII form again, measured on the characters instead of the bytes, never enforced; the plain removed; the plain applied to the keys; the failure on `UnicodeError` removed; the skills' sentences), and each file is restored byte for byte.
6. The tests of the package pass with and without the workbench checkout, `wb run code-work check` reports no problem, and the Result of the earlier plan records the second review.

## Increments

### Increment A — The helper: the bound in bytes of the locator as given, control characters out of locator strings, and a clear failure for a stream that cannot carry the reply

**Outcome:** criteria 1, 2, 3 and the helper's part of 5.
**Dependencies:** none.
**Affected areas:** `package/kb/helper/kb`, `engine/tests/test_package.py` (`LocatorCodeTests` gets the tests; `ReadTests` keeps its bound tests).
**Steps:**
1. Read `read`, `code_locators`, `in_strings`, `main` and `plain` in the helper, the tests of the bound in `LocatorCodeTests` and `ReadTests`, and what `jsonstrict.parse_object` limits (bytes of the input, strict).
2. Write the tests first and see them fail: the CJK locator of 480 characters and the ones at the bound (criterion 1), the locators with control characters (criterion 2), the stream of ASCII encoding (criterion 3).
3. Make the change: the bound measured as the plan says and the message in bytes; `plain` applied to each string of a locator before `write_codes`; in `main`, `out.write(text)` inside a `try` that turns `UnicodeError` into a failure with the message and a return of 1.
4. Break it on purpose, one change at a time, see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`, with `KB_WORKBENCH_CHECKOUT` set and unset; `wb run code-work check`; `git diff --check`. No engine file changes, so no wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-fix-the-bound-of-a-locator-and-the-control-characters-and-output-of-the-helper#A`, after an independent review by the `reviewer` agent.

### Increment B — The two skills say the two clauses, and the second review is recorded

**Outcome:** criterion 4, the skills' part of 5, and criterion 6 (the record).
**Dependencies:** none (it may be done before A).
**Affected areas:** `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, `walk-from-themes/SKILL.md`, `engine/tests/test_package.py` (`SkillTests`, `WalkSkillTests`), the Result of `docs/plans/2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command.md`.
**Steps:**
1. Read the read bullet of the two skills and step 4 of `find-a-passage`.
2. Write the tests first and see them fail; add the two clauses in the plain words of `find-a-passage`; break them on purpose, one change at a time, and restore each file byte for byte.
3. Add to the Result of the earlier plan one paragraph: the second review, that the reviewer could run nothing and what it found; the experiments I ran and their results (the fuzz, the twelve headings in a real shell, the three findings); and where each finding is closed (this plan) or deferred.
4. Run the whole of the package tests and the check.
**Verification:** the two skill test classes and the whole of `engine/tests/test_package.py`, with and without `KB_WORKBENCH_CHECKOUT`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: ...#B`, after an independent review by the `reviewer` agent.

## Verification for the plan as a whole

Each increment's recorded verification stands. After B, `engine/tests/test_package.py` is run once as a whole, with and without the workbench checkout, and `wb run code-work check`. No engine file changes, so no wider run is named. A live check is not needed for the plan's rules (they are tested with a fake engine and a real shell), but the owner's installation in `kb-scratch` of the new helper and skills is the owner's, and a read of a page with a long non-English heading, if the library holds one, would show the bound there.

## Risks and sensitive actions

- **The bound changes meaning back to what it was.** A locator the agent gives is measured in bytes as the agent wrote it, as before the codes. It cannot admit a locator that the engine would refuse: the engine's bound is 100000 characters and the ASCII form of 2000 bytes is at most 12000.
- **`plain` on locator strings** removes characters from a heading that the engine's cleaning also removes; for a real reply it changes nothing. If a heading did hold such a character, the locator would no longer match by its path and the engine would look for the passage by its words (`found_by_text`); the skills already say what to do with that reply.
- **The output failure** turns a traceback into a message; a stream that cannot encode the reply gets no reply at all, which is safe and says how to change the setting.
- The helper is module-owned: `kb-scratch` and any other project keep the old helper until the owner approves and installs the package there.
- No outside request, no secret and no crawl approval is touched. A third security review is the owner's to ask for; a reviewer whose hook allows probe scripts would test what this plan tests by hand.

## Review record

Increment A, independent review by the `reviewer` agent, 1 exchange (of a cap of 6): no blocking findings; it ran nothing and read the helper in full, the tests, `jsonstrict` and the engine's bound.

- **Found true (read only):** the new bound cannot admit a locator that the engine cannot take (the engine's bound is 100000 characters; the ASCII form of 2000 UTF-8 bytes is at most about 12000), lone surrogates are refused by the strict reader so the encoding in the check cannot raise, and the old direction is also right (the bytes as given are what the bound counted before the codes); `emit` writes nothing before it fails, because a `TextIOWrapper` encodes the whole text first; the message names bytes and the order of `plain` and `write_codes` matches the plan; the one break that no test catches ("plain applied after the codes") gives identical output.
- **Applied:** (1) no test showed that the engine still gets the ASCII form, so a `sent` written with raw non-ASCII would have passed: the CJK test now asserts `argv[4].isascii()` and a break covers it; (2) the control-character test put a control character only in the `start` of an anchor: the `end` has one too.
- **Noted, not changed:** the keys of a locator are not cleaned or coded (the engine's keys are fixed words, and this predates the plan); the `plain` that the plan adds matters only below U+0020, because the `plain` that `with_coded_locators` already ran on the whole reply removes the other characters (so the Unicode-version difference between the helper's interpreter and the engine's was already in force); the parse limit of 3 times the bound can refuse a locator of almost only codes that is typed with much white space (a refusal that says "larger than 6000 bytes"); a stream with the error handler `replace` or `backslashreplace` never raises, so `emit` would write a reply with replacement characters (outside the plan: it assumes the entry point passes `sys.stdout` as it is); an `OSError` from `emit` in the `Failed` branch ends as a traceback and in the success branch is reported as "could not be started" (both predate this plan).
- **Could not be checked by the reviewer:** any run result and the breaks; the behaviour of the real `sys.stdout` under a non-UTF-8 locale; what changed relative to HEAD.

## Deferred work

- Quoting `<book>`, `<version_id>` and `REF` in the call templates of the skills (L3 of the second review).
- Coding the `raw` field of an `unknown_kind` reply.
- Writing a locator on one line in the replies, so that an agent need not join the lines of the copied object ("keep the locator on one line" asks it to).
- The helper taking a locator from standard input or from a file.
- The command gate reading heading text in a copied locator (an availability matter, outside the helper).
- A reader of the topics file that refuses invisible or control characters (the engine's, which voids the crawl's approval).

## Result

**Increment A** (in `main` directly, as the earlier plans' increments were).

- Done: in `package/kb/helper/kb`, `read` measures the bound of 2000 as the UTF-8 bytes of the compact JSON of the decoded locator written as the agent gave it (`ensure_ascii` false) and says "bytes" in its refusal, while the string passed to the engine stays the ASCII form; `code_locators` passes each string of a locator through `plain` before `write_codes`; a new `emit` writes the reply to the output and turns a `UnicodeError` into `failed: ... set a UTF-8 locale ...` with a return of 1 and nothing written, for the text of a success and for the text of a failed run. `LocatorCodeTests` has 7 more tests: the CJK locator of 480 characters and the ASCII form it sends; the exact bound in bytes and one byte more; control characters in a locator, a next and an anchor's start and end (newline, tab, CR, NUL, ESC, DEL, U+2028, a bidirectional mark, a lone surrogate); a stream of ASCII encoding for a success and for a failed run.
- Tests were written first and seen failing for the right reasons (7 failures and 1 error: the CJK locator and the exact bound refused, a backslash in a locator for newline, tab, CR, NUL and ESC, and a `UnicodeEncodeError` from the helper; the cases DEL, U+2028, the bidirectional mark and the lone surrogate already passed, because the `plain` over the whole reply removes them, and stay as guards), then passing.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package` with `KB_WORKBENCH_CHECKOUT` set, 162 tests, OK; unset, 162 tests, OK, 98 skipped; `wb run code-work check`, 81 plans, no problems; `git diff --check`, clean; no `.pyc` or `__pycache__` in `package/`. No engine file changed, so no wider run.
- Breaks: 14 single changes to the helper, 13 caught by a test, the file restored byte for byte: the bound on the ASCII form again, on characters, never enforced, one byte too wide; the message without "bytes"; the string sent to the engine no longer ASCII; `plain` removed, or keeping newline and tab; `UnicodeError` not caught; a stream that cannot carry the reply reported as a success; the message without what to set; the text of a failed run and of a success written without the check. Not caught, and it cannot be: "plain applied after the codes instead of before" gives identical output, because the codes are ASCII.
- Departures from the plan: none beyond the review's two test additions.
- Not done: Increment B; the owner's installation of the new helper in `kb-scratch`.
