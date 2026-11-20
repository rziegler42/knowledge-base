# Make the locators of the helper safe to copy into a single-quoted command

Status: Proposed
Created: 2026-11-20
Candidate: none (a correction that follows from a finding: the first live test of the skills in `kb-scratch` on 2026-11-20 showed that the fix of the plan `2026-11-20-close-the-findings-of-the-security-review-of-the-find-a-passage-and-suggest-topics-skills` does not work)
Specs: docs/specs/knowledge-base.md ("Reading module": the helper and the skills)

## Goal

An agent that reads a passage copies a locator out of a reply of the helper into a command: `wb run kb read ... '<locator-json>'`. A locator holds the headings and words of a crawled page, so it can hold an apostrophe, and in a single-quoted argument an apostrophe ends the quotes and the rest runs as a command. This is the Medium finding of the security review of 2026-11-20.

The plan `2026-11-20-close-the-findings-of-the-security-review-of-the-find-a-passage-and-suggest-topics-skills` tried to close it by having the helper write each apostrophe of a reply as the JSON escape of an apostrophe (a backslash, then u0027) and by telling the agent to type that escape. **It does not work.** In the first live test (a question about Dijkstra's algorithm, in `kb-scratch`) the agent's command held a raw apostrophe in `["Dijkstra's algorithm"]` and the shell stopped with an unmatched quote. Tested here with a harmless command: this harness turns a typed backslash-u escape into the character it stands for before the command runs (`printf '%s' 'A<escape>B'` fails with "unmatched '"), while a doubled backslash, `%27` and a double quote arrive exactly as typed. So an agent cannot send the escape, the risk of a heading such as `x'; touch y; '` is still open, and the Result of both earlier plans that says "closed" is wrong.

When this plan is done an agent copies a locator that holds **no apostrophe, no double quote, no backslash and no `%` that is not a code**: the helper writes those four characters, inside the locator objects of its replies, as `%27`, `%22`, `%5C` and `%25`, and `read` turns them back before the engine sees the locator. The agent types nothing and decodes nothing. The three skills that pass a locator say so, a real shell shows that a hostile heading stays one argument, the owner's live check (the Dijkstra question) reads the page, and the records of the two earlier plans are corrected.

## Scope

- `package/kb/helper/kb`: remove `no_apostrophe` (the escape of every apostrophe of the engine's text); read the engine's JSON, encode the four characters in the string values of every object found under a key `locator` or `next`, write the reply again as JSON in which no locator holds a backslash (non-ASCII characters of the reply are written as themselves); `read` decodes the four codes in the string values of the locator it is given.
- `engine/tests/test_package.py`: the class `ApostropheTests` is replaced by tests of the new behaviour; the tests of the three skills are changed to the new sentences.
- `package/kb/harness/neutral/skills/find-a-passage/SKILL.md`, `pose-a-problem/SKILL.md` and `walk-from-themes/SKILL.md`: the sentences on the locator.
- `docs/specs/knowledge-base.md` ("Reading module"): one sentence on the form of a locator in a reply of the helper (the four codes), added once it is built. The spec holds no statement on it today and none on an apostrophe escape, so nothing in it is contradicted.
- The Result of the two earlier plans (`2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package` and `2026-11-20-close-the-findings-of-the-security-review-of-the-find-a-passage-and-suggest-topics-skills`): a correction of what they say is closed. Their Result may change without a new approval.

## Non-goals

- Any file of `engine/kb`, any command, the module declaration, or the crawl's approval: none changes. The helper is `package/kb/helper/kb`, outside the engine's fingerprint.
- Encoding anything outside the locators. A title, an excerpt, a citation and a caveat keep their apostrophes: no skill copies them into a command (the words of a search are plain words, the rule of the older plans), and an excerpt that reads `it%27s` would be worse for the agent.
- Making the agent's shell call safe in another way (a helper that takes the locator on standard input, or from a file): a larger change of the helper's calls, not asked for.
- The owner's copy of the package in `kb-scratch` (the approval, the upgrade and the re-render are the owner's, in a terminal) and the owner's todo items.
- Changing how the harness treats a typed escape.

## Assumptions and constraints

- **What the harness does (tested 2026-11-20, with a harmless `printf`).** A backslash-u followed by four hexadecimal digits, typed in a command, reaches the shell as the character; a doubled backslash, `%27` and a double quote are not changed. Whether other escapes (a backslash and a letter, a backslash and a quote) are changed is not known; so the plan leaves **no backslash and no double quote inside a string of a locator**, and so no backslash-u sequence in a locator, whatever the harness does with them. The rest of a reply may hold the escapes that JSON needs (a title or an excerpt can hold the text backslash-u, which JSON writes with a doubled backslash): no skill copies that text into a command.
- **The engine's replies are JSON** (`search`, `read`, `problem-search`, `theme-walk` print `json.dumps(..., indent=1)`, which writes non-ASCII characters as backslash-u escapes and leaves an apostrophe as it is). Where the locators are in a reply is read from the engine in Increment A: `locator` in a result of a search and in a read reply (also the replacement locator of a `found_by_text` reply), `next` in a read reply; the results of `problem-search` and `theme-walk` are checked.
- The code is a percent code of one byte: `%27` for the apostrophe, `%22` for the double quote, `%5C` for the backslash, `%25` for the percent sign. Decoding is one pass over the four codes and nothing else, so a heading that holds the text `%27` comes out as `%2527` and goes back to `%27`: the round trip loses nothing. A `%` that is not one of the four codes is left as it is.
- **A string of a locator holds no newline and no tab** if the engine cleans headings as it seems to (`locator.shown` and `textutil.clean`); Increment A, step 1 checks it with real locators of the library and with the engine's code. The helper keeps newline and tab in other text, and JSON writes them with a backslash. If a locator can hold one, the plan stops at that step and the codes are extended (`%0A`, `%09`) with the owner's word, because that changes this plan's approved criteria.
- The helper's bound of 2000 bytes for a locator (`MAX_LOCATOR`) is the engine's bound for a locator; it is measured on the decoded locator (the encoded one may be longer, by 2 bytes for each of the four characters), so a locator that the engine gave is never refused for its codes.
- A reply that is not JSON (a failure with plain text, a reply the helper could not read) holds no locator and is treated as before: cleaned, cut and framed. A reply cut at the helper's bound is encoded before it is cut.
- The engine's own bound on a locator and the strict reader of the helper (`jsonstrict`) stay as they are.
- A tracked skill is text and a test shows its words; a real shell and the helper's own code show that a locator is one argument. What the harness does to a typed command is shown by the owner's live check in `kb-scratch`, by hand.

## Completion criteria

1. In the reply of each of the four commands, every string value inside an object under a key `locator` or `next`, at any depth, has its backslash, double quote, apostrophe and percent sign written as `%5C`, `%22`, `%27` and `%25`, and no other string of the reply is changed in meaning; the JSON text of each locator holds no backslash at all (non-ASCII characters are written as themselves, control characters are removed, as the helper already removes them from all text), so it holds no backslash-u sequence; the rest of the reply may hold the escapes JSON needs; a reply that is not JSON is as before; the paths of this machine that the helper knows are hidden in locators too, **including a path that holds an apostrophe, a double quote, a backslash or a percent sign** (the paths are hidden in the raw text of the reply first, as now, and the locators are encoded after, so that the encoded spelling is never one the redaction would have to know).
2. A locator copied from a reply, with its codes, passed to `read`, reaches the engine as the same locator the engine gave, for headings that hold an apostrophe, a double quote, a backslash, a percent sign and the text `%27`; the locator that the engine gets equals, exactly, the one the engine gave, including a heading that holds the text `%27` or `%25` as its own characters.
3. A test with a real shell (`sh -c` over a command that prints its one argument) shows that the locator copied from a reply of a hostile heading `x'; touch y; '` is one argument of a single-quoted command and that nothing else ran (a marker file is not made).
4. `read` refuses a locator over the bound after decoding and accepts one at the bound that holds codes.
5. `no_apostrophe` is gone and no apostrophe of the engine's text outside a locator is changed.
6. `find-a-passage`, `pose-a-problem` and `walk-from-themes` say: copy the locator exactly as given; a `%27`, `%22`, `%5C` or `%25` in it stands for a character and is never decoded or typed by the agent; if a locator you hold has an apostrophe or a backslash in it (an old helper), do not run the read and mark the book unread; none of the three says to write an escape of an apostrophe.
7. Each new rule has a deliberate break that a test catches (the helper: no encoding, one of the four codes missing, `next` not encoded, a key at depth not reached, decoding in two passes, `%` not encoded, encoding after the cut, a reply written with backslash-u again; the skills: each sentence), and each file is restored byte for byte.
8. The tests of the package pass with and without the workbench checkout, `wb run code-work check` reports no problem, and the Result of both earlier plans is corrected.
9. The owner's live check, once the package is approved and installed in `kb-scratch`: the question about how Dijkstra's algorithm picks the next node reads the page (the `read` runs and returns a passage), and is recorded in this plan's Result.

## Increments

### Increment A — The helper encodes the four characters in the locators of its replies and decodes them in `read`

**Outcome:** criteria 1 to 5.
**Dependencies:** none.
**Affected areas:** `package/kb/helper/kb`, `engine/tests/test_package.py` (`ApostropheTests` is replaced).
**Steps:**
1. Read what each of the four commands prints and where a locator sits in it (`kb/search.py`, `kb/read.py`, `kb/problem.py`, `kb/walk.py` and what they reuse), the helper's `cleaned`, `wrap`, `query_engine`, `read` and `no_apostrophe`, the fake engine of `HelperCase`, and the tests of `ApostropheTests`. Take a locator of the owner's library as an example (read only, from a search reply) to see what a real one holds.
2. Write the tests first and see them fail: for each command the fake engine prints a JSON object with locators (`locator` in a result, `locator` and `next` in a read reply, a locator at depth) whose headings hold an apostrophe, a double quote, a backslash, a percent sign, the text `%27` and a non-ASCII letter: each string of each locator holds the codes and none of the four characters, the rest of the reply is the same as the engine printed (parsed and compared, including a title that holds the text backslash-u), the JSON text of each locator holds no backslash, and a reply that is not JSON is as before; the whole round (a reply, the locator taken from it, `read`) gives the fake engine the same locator; a real `sh -c` with the locator in single quotes prints it as one argument and a hostile heading makes no file; the bound is measured after decoding; a known path that holds each of the four characters, placed inside a locator of the reply, is hidden and no part of it is left (the test that would fail if the paths were hidden after the encoding); the standard error and the text of a failed run are cleaned as before.
3. Make the change: one function that encodes the four characters in the strings of a locator, one that walks a parsed reply and applies it to every object under `locator` and `next`, one that decodes; `cleaned` cleans the text and **hides the paths first, in the raw text as it does now**, then reads the JSON, applies the functions, writes the reply again with `indent=1` and without ASCII escapes, and cuts; remove `no_apostrophe`.
4. Break it on purpose, one change at a time, see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`, with `KB_WORKBENCH_CHECKOUT` set and unset; `wb run code-work check`; `git diff --check`. No engine file changes, so no wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command#A`, after an independent review of the helper's change by the `reviewer` agent.

### Increment B — The three skills say to copy the locator as given, and what to do when it holds an apostrophe

**Outcome:** criterion 6, and criterion 7 for the skills.
**Dependencies:** Increment A (the skills say what the helper does).
**Affected areas:** `package/kb/harness/neutral/skills/find-a-passage/SKILL.md`, `pose-a-problem/SKILL.md`, `walk-from-themes/SKILL.md`, `engine/tests/test_package.py` (`FindPassageSkillTests`, `SkillTests`, `WalkSkillTests`).
**Steps:**
1. Read step 4 and 5 of `find-a-passage` and step 6 of the other two, and their tests.
2. Write the tests first and see them fail (the new sentences; the old sentence that tells the agent to write the escape is gone; a test that no skill holds a backslash-u sequence). Change the three skills in the plain words they have. Break the text on purpose, one change at a time, and restore each file byte for byte.
**Verification:** the three test classes and the whole of `engine/tests/test_package.py`, with and without `KB_WORKBENCH_CHECKOUT`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: ...#B`, after an independent review by the `reviewer` agent.

### Increment C — The records of the two earlier plans are corrected

**Outcome:** criterion 8 (the records).
**Dependencies:** Increments A and B.
**Affected areas:** the Result of `docs/plans/2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package.md` and of `docs/plans/2026-11-20-close-the-findings-of-the-security-review-of-the-find-a-passage-and-suggest-topics-skills.md`; the Result of this plan; `docs/specs/knowledge-base.md` ("Reading module").
**Steps:**
0. Read the "Reading module" section of `docs/specs/knowledge-base.md` and "Failure and safety" of `docs/specs/reading.md`, and add to the first one sentence that says what is true once Increment A is built: the locators of a reply carry an apostrophe, a double quote, a backslash and a percent sign as `%27`, `%22`, `%5C` and `%25`, and `read` takes them back. This states what is built; it changes no direction.
1. In each of the two Results add a dated correction: the Medium finding was not closed by the escape (why, with the test), and is closed by this plan; the sentences that say "closed" stay as they were written and are marked as corrected, not rewritten.
2. Run the whole of the package tests and the check once more.
**Verification:** `wb run code-work check`; `git diff --check`; the whole of `engine/tests/test_package.py` with and without `KB_WORKBENCH_CHECKOUT`.
**Evidence:** the one local commit, with the trailer `Plan: ...#C`, and this plan marked completed once the owner's live check (criterion 9) is recorded.

## Verification for the plan as a whole

Each increment's recorded verification stands. After C, `engine/tests/test_package.py` is run once as a whole, with and without the workbench checkout, and `wb run code-work check`. No engine file changes, so no wider run is named. **The live check is the test that the first plan lacked:** after the owner approves and installs the package in `kb-scratch` (approve, upgrade, re-render), the question "where does the library's material say how Dijkstra's algorithm picks the next node?" is asked there, and the `read` of the page with the apostrophe in its heading must run and return a passage. The commands of that session are read (they show the locator the agent sent). The Result says what was seen.

## Risks and sensitive actions

- **A hostile heading is the case this plan exists for.** Until the new helper is installed in a project, that project's agent can be made to run a command by a crawled heading with an apostrophe. In `kb-scratch` and any other project with the package the owner can keep it away from untrusted headings until then. The records of the earlier plans said it was closed; this plan corrects them.
- **The helper writes the reply again.** It reads the engine's JSON and prints it; a mistake would change what an agent sees. The tests compare the parsed reply with what the engine printed except for the locator strings; a reply that cannot be read is left as it was. Non-ASCII characters appear as themselves instead of backslash-u escapes: an improvement for readers, a change for every skill.
- **A locator the agent shows or quotes holds codes** (`%27` for an apostrophe). The skills say it stands for a character and is not to be decoded; a heading the agent writes in its answer is read from the title, not from the locator.
- **The harness may treat other typed escapes in ways not yet known.** The plan leaves no backslash and no double quote in a locator string, so what the harness does with them does not matter; the live check is the proof.
- **A security review of the changed helper** runs only if the owner asks. The first review could not run an experiment (its write hook refused the probe scripts); the owner may want one with a scratch directory its hook accepts, with this finding as its first question.
- The helper is module-owned: another project keeps the old helper until the owner approves and installs the package there.
- No outside request, no secret and no crawl approval is touched.

## Review record

Peer review through the review engine (plan `plan-04c83d0bae39de82`), 3 rounds of a bound of 3, the bridge `ask-codex` (the models `gpt-5.6-terra` in rounds 1 and 2 and `gpt-6.1-sol` in round 3). The last round still had findings, so the review ended at its bound without a round of no findings; all 4 findings are applied and none was rejected. The plan has not been read again by the reviewer since the last two edits.

- **R1-F1 (blocker), applied:** the rule that a reply holds no backslash-u sequence cannot hold for a title or an excerpt that holds that text, which JSON writes with a doubled backslash. The guarantee now covers the locators only (goal, scope, assumptions, criterion 1, the tests), the rest of the reply may hold the escapes JSON needs, and the plan adds a check that a locator holds no newline or tab (Assumptions, Increment A step 1).
- **R2-F1 (blocker), applied in part:** the reviewer said the spec requires the old escape of every apostrophe. It does not: `docs/specs/knowledge-base.md` and `docs/specs/reading.md` say nothing about it. But they say nothing about the form of a locator either, so one sentence in the Reading module is added to the scope and as step 0 of Increment C.
- **R3-F1 (major), applied:** encoding the locators before hiding the paths would let a known path with one of the four characters escape the redaction. The order is now: hide the paths in the raw text first (as now), then read the JSON and encode; a criterion and a test cover a path inside a locator.
- **R3-F2 (minor), applied:** criterion 2 now says that the locator the engine gets equals the one it gave, including a heading that holds the text `%27`, and not that it holds none of the codes.
- **Left for the owner:** a fourth round (`extend`, the owner's level) if a round of no findings is wanted before approval; the independent read of each increment by the `reviewer` agent is in the plan anyway. The review's files in `.workbench/workbench/review-engine/plan-04c83d0bae39de82/` are committed with the plan.

## Deferred work

- A reader of the topics file that refuses an invisible or control character in a line (the engine's, which voids the crawl's approval): from the earlier plans.
- Taking the locator from standard input or from a file, so that no locator is copied into a command at all.
- The engine writing locators in a form that needs no codes (a change of the engine, which voids the crawl's approval).

## Result

Empty until work starts.
