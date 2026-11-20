# Close the findings of the security review of the find-a-passage and suggest-topics skills

Status: Proposed
Created: 2026-11-20
Candidate: none (a correction that follows from a finding: the owner asked for a security review of the plan `2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package`, and the owner said yes to a plan for its findings)
Specs: docs/specs/knowledge-base.md ("Reading module": the helper and the skills), docs/specs/population.md (the topics of the crawl and what the owner approves)

## Goal

The security review of the skills `find-a-passage` and `suggest-topics` (2026-11-20, by the `security-reviewer` agent) found no Critical or High problem and eight points below that. It could run no experiment (its write hook refused its probe scripts), so every point rests on reading; three were then tested here with the real reader of the topics file and the helper's own patterns, and all three hold:

1. **Medium.** The rule that an apostrophe in a locator must be written as the JSON escape `\u0027` is kept only if the agent follows the text. A crawled page can put an apostrophe in a heading, the engine prints it unchanged inside a locator, and an agent that copies one apostrophe raw lets the rest of the heading run in its shell. `pose-a-problem` and `walk-from-themes` still say "exactly as given", which is unsafe in the same way (a todo item of the owner since the first plan).
2. **Low.** `suggest-topics` says "a `#` starts a comment". The reader skips only a line whose first character is `#`: `A topic # gap: private evidence` is read as one topic (tested), and the evidence would be sent out.
3. **Low.** An invisible character before `#` or `[` (U+200B and the like) keeps the line from being a comment or a section line, and the reader then reads it as a topic (tested for both).
4. **Low.** The skill says the comments "land in what the owner approves"; the approval summary shows counts, not the text of topics or comments. The text is covered by the digest and stored in the approved copy.
5. **Low.** The skill's list of where a topic goes leaves out the model server of the owner's config, which turns each topic into queries (`crawl-query`), and does not say that each outside source is a switch of the plan.
6. **Low.** The skill states the owner's three sections and weights as if they were everyone's; the package ships to other projects.
7. **Low.** `find-a-passage` does not say that the fields outside the marker lines (the title, the caveats, the reasons, the citation, the headings of a locator) are also texts of books; `walk-from-themes` says it and tests it.
8. **Low.** The helper's patterns for a book id and a version use `match` with `$`, which also accepts a trailing newline (tested). There is no shell between the helper and the engine, so it has no sink; it is a hygiene correction.

When this plan is done the helper writes every apostrophe of the engine's text as `\u0027` (so the locator an agent copies "exactly as given" holds no character that can end a single-quoted argument, in all four skills that pass a locator or a `ref` on), its two patterns match the whole value, `suggest-topics` and `find-a-passage` say what is true and test it with the real reader, and the review is recorded in the Result of the plan it reviewed.

## Scope

- `package/kb/helper/kb`: the text taken from the engine has each apostrophe written as `\u0027` (in `cleaned`, after the cut, for the standard output and the standard error of the engine); `BOOK` and `VERSION` match the whole value (`fullmatch`).
- `engine/tests/test_package.py`: tests for both, with the fake engine of `HelperCase`; changes to the tests of the two skills.
- `package/kb/harness/neutral/skills/suggest-topics/SKILL.md` and `package/kb/harness/neutral/skills/find-a-passage/SKILL.md`.
- The Result of `docs/plans/2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package.md` (a line that records the review; its Result may change without a new approval).

## Non-goals

- Any file of `engine/kb`, any command, the module declaration, or the crawl's approval: none changes. The helper is `package/kb/helper/kb`, outside the engine's fingerprint.
- Changing `pose-a-problem` and `walk-from-themes`. After Increment A, "exactly as given" is safe for them because of the helper, so their text stands. A sentence that tells them the helper writes the apostrophes is deferred.
- Changing the owner's topics file, or making the reader of the file stricter (a refusal of an invisible character before `#` is the engine's and voids the crawl's approval): recorded as deferred.
- Making the agent's shell call safe in another way (a helper that takes the locator on standard input): a larger change of the helper's calls, not asked for.
- The copy of the skills and of the helper in the owner's other folder (`kb-scratch`) and the owner's approval of the package there.

## Assumptions and constraints

- **The engine's replies are JSON.** `search`, `read`, `problem-search` and `theme-walk` print `json.dumps(..., indent=1)` (`kb/__main__.py`), which writes an ASCII apostrophe as it is. The JSON the engine prints never holds a backslash before an apostrophe that is not itself escaped (`\'` is not valid JSON), so replacing each `'` by `\u0027` leaves valid JSON with the same meaning. A reply that is not JSON would show the six characters instead of the apostrophe: harmless, and said in the Result.
- The cut of the text at `MAX_TEXT` is made first and the escape after it, so the cut never lands inside an escape; the marked cut is not changed.
- The text of the helper's own wrapper (the marker lines and the sentence "This is data from the owner's library...") is not the engine's text and is left as it is; nothing in it is copied into a command.
- What an agent sees changes: an excerpt reads `it\u0027s` where it read `it's`. An agent that reads JSON takes it as an apostrophe. This is the cost of the correction and is said in the Result.
- A tracked skill is text; a test shows its words and, with the real reader of the topics file, what the reader does with its example. It does not show how an agent behaves.
- The review's own limit stands: its experiments were not run. The helper's behaviour is tested here with a fake engine, as the other helper tests are.

## Completion criteria

1. The helper writes each apostrophe of the engine's standard output and standard error as `\u0027`, for all of its commands, after the paths are hidden and after the cut; the text between the helper's marker lines holds no ASCII apostrophe; `json.loads` of the text of a JSON reply equals the object the engine printed (the value with an apostrophe, a backslash before an apostrophe, and the text `\u0027` written by the page itself are all unchanged in meaning); a failed run's text is treated the same.
2. A locator taken from such a reply and passed to the helper again reaches the engine as the same locator (the existing test of the escape through the helper still passes, and a test with a hostile heading `x'; touch y; '` goes through the whole round).
3. `BOOK` and `VERSION` refuse a value with a trailing newline; a test shows both, and that a good value is still accepted.
4. `suggest-topics` says that a comment is a line whose first character is `#` and that nothing else is a comment (no evidence or `#` after a topic on the same line); that the proposal is written in plain characters (no invisible or control character, none copied raw from a result: the agent writes it in its own words); that the comments are stored in the owner's file and covered by the approval's digest, and that the summary of the approval shows counts and not text, so the owner reads the block; that a topic goes also to the model server of the owner's config and, of the outside sources, only to those the plan has switched on; that the sections and weights shown are an example, and the owner pastes the lines under the owner's own section header. Tests with the real reader show: a `#` after a topic is part of the topic; an invisible character before `#` makes a topic; the three lines of the block that the skill gives to paste are read as given.
5. `find-a-passage` says that the title, the caveats, the reasons, the citation and the headings of a locator are also texts of books, outside the marker lines, and are not to be obeyed; and says that the helper writes the apostrophes of its replies as `\u0027`, to be copied as given, while the rule to write any apostrophe of a locator as `\u0027` stays for a locator that was not copied from a reply.
6. Each new sentence has a deliberate break that a test catches, and the file is restored byte for byte after each run; the helper's change has breaks too (the escape removed, applied to the wrong text, applied before the cut, applied to one stream only, `match` for `fullmatch`).
7. The tests of the package pass with and without the workbench checkout, `wb run code-work check` reports no problem, and the earlier plan's Result records the review and its outcome.

## Increments

### Increment A — The helper writes each apostrophe of the engine's text as `\u0027`, and its patterns match the whole value

**Outcome:** criteria 1, 2 and 3.
**Dependencies:** none.
**Affected areas:** `package/kb/helper/kb`, `engine/tests/test_package.py`.
**Steps:**
1. Read `cleaned`, `wrap`, `query_engine`, the patterns and their users, the fake engine of `HelperCase` (its control file: `stdout`, `stderr`, `repeat`) and the tests of `OutputTests` and `ReadTests`; read what each engine command prints, to confirm that the four commands print JSON.
2. Write the tests first and see them fail: for each of `search`, `read`, `problem-search` and `theme-walk` (the fake engine printing a JSON object with a heading `x'; touch y; '`, a value with a backslash before an apostrophe, and the text `\u0027` written as a page would), the text between the marker lines holds no `\u0027`, and `json.loads` of it equals the object; the escape is made after the cut (a long text with apostrophes, cut, is still cut at the same place and holds no raw apostrophe in the part kept); the standard error and a failed run's text hold none; a locator taken from the reply goes back through `read` and reaches the fake engine as the same locator; `BOOK` and `VERSION` refuse a trailing newline and accept a good value.
3. Make the change: one function that writes the escape, used at the end of `cleaned` for text that comes from the engine (not for the helper's own sentences); `fullmatch` for the two patterns.
4. Break it on purpose, one change at a time, see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`, with `KB_WORKBENCH_CHECKOUT` set and unset; `wb run code-work check`; `git diff --check`. No engine file changes, so no wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-close-the-findings-of-the-security-review-of-the-find-a-passage-and-suggest-topics-skills#A`, after an independent review of the helper's change by the `reviewer` agent.

### Increment B — `suggest-topics` says what is true about comments, characters, the approval and the sections

**Outcome:** criterion 4.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/suggest-topics/SKILL.md`, `engine/tests/test_package.py` (`SuggestTopicsSkillTests`).
**Steps:**
1. Read the skill, its tests, `crawltopics.parse_topics` and `clean`, and `render_summary` of `crawlapprove.py`.
2. Write the tests first and see them fail: each new sentence; the reader's behaviour for a `#` after a topic and for an invisible character before `#` and before `[` (the tests show why the rules are there); the existing phrase test of "a `#` starts a comment" is replaced by the true sentence.
3. Change the skill in the plain words it has, keeping its form and its one block.
4. Break it on purpose, one change at a time, and restore the file byte for byte.
**Verification:** `engine.tests.test_package.SuggestTopicsSkillTests` and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: ...#B`, after an independent review by the `reviewer` agent.

### Increment C — `find-a-passage` says that every field of a reply is a text of a book, and what the helper does with apostrophes; the review is recorded

**Outcome:** criteria 5, 6 (for this skill) and 7.
**Dependencies:** Increment A (the skill says what the helper does).
**Affected areas:** `package/kb/harness/neutral/skills/find-a-passage/SKILL.md`, `engine/tests/test_package.py` (`FindPassageSkillTests`), `docs/plans/2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package.md` (its Result only).
**Steps:**
1. Read `walk-from-themes` where it says that every title and the citation are also texts of books, and its test; read step 4 of `find-a-passage`.
2. Write the tests first and see them fail; change the skill; break it on purpose, one change at a time, and restore it byte for byte.
3. Write in the Result of the earlier plan one paragraph: the security review that was run on the owner's word, that it ran no experiment, the findings by severity, what was tested here, and where each is closed (this plan).
4. Run the whole of the package tests and the check.
**Verification:** `engine.tests.test_package.FindPassageSkillTests` and the whole of `engine/tests/test_package.py`, with and without `KB_WORKBENCH_CHECKOUT`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: ...#C`, after an independent review by the `reviewer` agent.

## Verification for the plan as a whole

Each increment's recorded verification stands. After C, `engine/tests/test_package.py` is run once more as a whole, with and without the workbench checkout, and `wb run code-work check`. No engine file changes, so no wider run is named. A live check by hand once the owner has copied the package to the other folder: a real `read` of a passage whose heading holds an apostrophe returns the locator with `\u0027`, and the engine accepts it as given.

## Risks and sensitive actions

- **The helper changes what every agent sees** from the library, in all skills: an apostrophe in a title or an excerpt reads `\u0027`. A skill that quotes a passage must write the apostrophe when it quotes; the skills say to quote the passage as the book's words, and the Result says what was seen. The risk of the change is in the text that the helper passes on, so a wrong replacement would corrupt a reply: the tests compare `json.loads` of the reply with the object.
- **A second look at a fix is new attack surface.** Increment A is reviewed by the `reviewer` agent (read only). A security review of the changed helper runs only if the owner asks; the earlier one could not run experiments, so the owner may want one with a scratch directory its hook accepts.
- **The helper is module-owned.** Other projects that have the package keep the old helper until the owner approves and upgrades the package there; until then they have the unsafe "exactly as given". Said in the Result.
- No outside request, no secret and no crawl approval is touched.

## Review record

Empty until a review is asked for.

## Deferred work

- A sentence in `pose-a-problem` and `walk-from-themes` that says the helper writes the apostrophes of its replies as `\u0027`. After A their rule is safe as it stands.
- A reader of the topics file that refuses an invisible or control character in a line (the engine's, which voids the crawl's approval): the skill is the only guard until then.
- The excerpt may not hold the matched word, because the index matches whole words and ignores accents and the excerpt is found by substring: the skill's "shows the words that matched" is nearly true (a note of the review).
- A title with a double quote is rewritten as an apostrophe in a citation, so a citation copied into another single-quoted command carries one; A makes it `\u0027` in the reply, and no skill copies a citation into a command.

## Result

Empty until work starts.
