# Close the findings of the security review of the find-a-passage and suggest-topics skills

Status: Completed
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

Increment A, independent review by the `reviewer` agent, 1 exchange (of a cap of 6): no blocking findings. Its recommendation: no blocking findings. It ran nothing and read the code and the tests.

- Found sound (read only): every route from the engine's bytes to the helper's output goes through `cleaned` (the success text, the standard error notes, the text of a failed run); the helper's own refusal and failure messages hold no engine text; `search`, `read`, `theme-walk` and `problem-search` all print `json.dumps(..., indent=1)` on success; the replacement leaves valid JSON with the same meaning (a backslash before an apostrophe, a page's own `\u0027`, keys and lists); the cut is made before the escape, so it cannot land inside one; the path hiding runs first, so a path that holds an apostrophe is still found; `plain` runs before the escape and cannot add an apostrophe; the new tests match criteria 1 to 3.
- Applied: (1) a test gap: no test put an apostrophe in a hidden path, so an escape moved ahead of the hiding would have leaked such a path. Added `test_a_path_that_holds_an_apostrophe_is_still_hidden_because_the_escape_comes_after_the_hiding` and the break "escape before the paths are hidden" (caught by it); (2) the module docstring of the helper now says that the engine's text is written with every apostrophe as the JSON escape.
- Noted, not changed: (3) the bound `MAX_TEXT` (and `MAX_STDERR`) counts characters before the escape, so a reply made of apostrophes can be up to six times the stated bound (about 393000 characters instead of 65536); the marker still says "cut at 65536", which is true of the engine's text, and the engine's own output stays capped at 1 MiB by `MAX_OUTPUT`; (4) Increment A, step 2 of this plan says the text "holds no `\u0027`" where it means no ASCII apostrophe (a slip of mine when I corrected the escapes in this plan; criterion 1 says it right and the code and tests follow criterion 1); the plan is approved, so the wording stands and is recorded here; (5) the skill's step 4 still tells an agent to write the apostrophes of a locator as the escape: correct, and Increment C is the planned place to update it.
- Could not be checked by the reviewer: any run result; that the fake engine passes its output byte for byte (the tests show it); real replies of the engine with apostrophes (the live check of the plan).
- No security review of the changed helper was run; it runs only if the owner asks.

Increment B, independent review by the `reviewer` agent, 1 exchange (2 in all of a cap of 6): no blocking findings. Its recommendation: no blocking findings. It ran nothing and read the code and the tests.

- Found true against the code (read only): the four outside sources are each a switch of the plan (`discover.py`); the topic reaches the model server in the prompt of `crawl-query`; the approval summary prints counts and section names and weights, no text of a topic or a comment; the digest covers the plan, the topics, the allow file and the fingerprint, and the approved copy keeps the comments; a `#` after a topic stays in the topic; an invisible character before `#` or `[` makes a topic; the 300 characters are counted after cleaning; the example passes the real reader.
- Applied: (1) a repeat inside the proposal (two topics alike in case, spacing or hidden characters) makes the reader refuse the owner's file, and the skill did not say so: it now says that no two topics are alike, even in case or spacing, and why; (2) a topic wrapped over two lines would give a second, fragment topic that is sent out: the skill now says to write each topic on one line and never wrap it, and why; (3) the sections are only a guess of the agent, which it cannot check: it now says so in its sentence outside the block. A new test shows both effects with the real reader.
- Noted, not changed: a comment line that starts with white space is also a comment to the reader (the skill's rule, to start with `#`, is the safe direction); "is sent out with it" for a `#` after a topic is true of the prompt and of the fallback queries and may overstate for the model's own queries (safe direction); three of the four sources are on by default and the skill says only "each only if the owner's plan has it on"; the test of an invisible character in the example is indirect (a raw invisible character makes the raw plain lines differ from the cleaned topics).
- Could not be checked by the reviewer: any run result; whether the characters the skill calls invisible are all of those the reader drops; how an agent behaves with the new wording.

Increment C, independent review by the `reviewer` agent, 1 exchange (3 in all of a cap of 6): no blocking findings. Its recommendation: no blocking findings. It ran nothing and read the code, the tests and both plans.

- Found true against the code (read only): which fields a search reply and a read reply carry; that only the excerpt (search) and the text (read) are enclosed by the engine's untrusted-text marks, so the title, the caveats, the reasons for the completeness, the citation (read only) and the headings of a locator sit outside them; the helper escapes the engine's text in every reply; the escape means the same locator and the helper reads the escaped locator as the same (it parses it strictly and writes it again); each case of the new apostrophe paragraph (a copy made exactly, a `next`, the replacement locator of a `found_by_text` reply, a retyped locator) leads to the right action; the new tests match the skill's text.
- Applied: (1) the skill did not say what to do when a copied locator still holds an apostrophe, which happens with a helper that is an old one: it now says to write it as the escape or not to run the read; (2) the skill did not tell the agent to write the apostrophe when it quotes a passage or a title, which the Result of Increment A says it must: step 5 now says so; (3) the citation is a field of a read reply and not of a search reply, so the sentence of step 2 now says "and the citation of a read reply".
- Noted, not changed: the helper's own sentence between the marker lines holds an apostrophe ("owner's"), which is the wrapper and not engine text (no locator comes from it; the plan's Assumptions say so); "do not write, change or complete a locator yourself, with the one exception below" sits beside the rule for a retyped locator, which is a defensive rule and leads to no raw apostrophe; the paragraph added to the earlier plan's Result says "closed" and is committed with this increment, not before.
- Could not be checked by the reviewer: any run result; how an agent behaves with the wording; live replies of the engine with apostrophes (the live check of the plan); the standard error and failed-run routes of the helper past what Increment A's review covered.

## Deferred work

- A sentence in `pose-a-problem` and `walk-from-themes` that says the helper writes the apostrophes of its replies as `\u0027`. After A their rule is safe as it stands.
- A reader of the topics file that refuses an invisible or control character in a line (the engine's, which voids the crawl's approval): the skill is the only guard until then.
- The excerpt may not hold the matched word, because the index matches whole words and ignores accents and the excerpt is found by substring: the skill's "shows the words that matched" is nearly true (a note of the review).
- A title with a double quote is rewritten as an apostrophe in a citation, so a citation copied into another single-quoted command carries one; A makes it `\u0027` in the reply, and no skill copies a citation into a command.

## Result

**Read the Correction at the end of this Result first: this plan did not close the Medium finding, and its "closed" statements, its Goal and its Status above are what was believed when it was written.**

**Increment A** (in `main` directly, as the earlier plan's increments were).

- Done: `package/kb/helper/kb` has the function `no_apostrophe`, which writes each ASCII apostrophe as `\u0027`, called at the end of `cleaned` (after the paths are hidden and after the cut) for all engine text: the standard output of the four commands, the standard error notes and the text of a failed run; the helper's own sentences are not changed; `BOOK` and `VERSION` are checked with `fullmatch`; the module docstring says it. `engine/tests/test_package.py` has the class `ApostropheTests` (7 tests).
- Tests were written first and seen failing for the right reasons (9 failures: raw apostrophes in all four commands, in the standard error and in a failed run, an unchanged cut, and a trailing newline accepted for a book and a version), then passing. One of them takes the locator out of a reply as an agent copies it, shows with `shlex` that a single-quoted command holding it is one argument, and shows that the engine receives the same locator through `read`.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package` with `KB_WORKBENCH_CHECKOUT` set, 141 tests, OK; unset, 141 tests, OK, 85 skipped; `wb run code-work check`, 79 plans, no problems; `git diff --check`, clean; no `.pyc` or `__pycache__` in `package/`. No engine file changed, so no wider run.
- Breaks: 12 single changes to the helper, 11 caught by a test, the file restored byte for byte after each run: the escape removed; written as the Python escape (which is only an apostrophe); only the first apostrophe; another escape (hex); applied before the cut; the standard error not escaped; a failed run not escaped; the wrapper escaped too; applied before the paths are hidden; `match` for `fullmatch` on the book and on the version. Not caught, and it cannot be: "the cut marker goes through the escape too" gives identical output, because the marker holds no apostrophe.
- Slips of mine, found by the checks: the writing tool turned every escape of this plan into a plain apostrophe, so the first approved text was wrong; the commit preview showed it, a script wrote the escapes back, and the owner approved the corrected plan (region 430a1385) before the plan was committed (95691c8). My first script for the helper wrote a real Python escape into its source, which is an apostrophe, so the replacement did nothing; the new tests failed and showed it, and the doubled backslash fixed it.
- What an agent sees now: an apostrophe in a title, a heading or an excerpt reads `\u0027` in every reply of the helper, in all four skills. An agent that reads JSON takes it as an apostrophe; a passage quoted for the owner has to be written with the apostrophe.
- Not done: the live check by hand (a real `read` of a passage whose heading holds an apostrophe); the owner's copy of the package in the other folder, and the pin and approval there.

**Increment B** (in `main` directly).

- Done: `package/kb/harness/neutral/skills/suggest-topics/SKILL.md` says: a topic also goes to the model server of the owner's config, which writes the queries, and each outside source only if the owner's plan has it on; the comments of evidence are kept in the owner's file and covered by the digest of the approval, while the summary of the approval shows counts and not text, so the owner reads the block; a comment is a line whose first character is `#`, and a `#` after a topic stays in the topic and goes out with it; the proposal is in plain characters (an invisible or control character before `#` or `[` makes the line a topic) and in the agent's own words, with no text copied raw from a result; each topic is on one line, never wrapped, and no two are alike even in case or spacing; the three sections and weights are the owner's as an example and the owner pastes the lines under the owner's own header; the sections are the agent's guess and it says so. The old sentence "a `#` starts a comment" and the old sentence "in what the owner approves" are gone, and a test holds that.
- Tests were written first and seen failing (2 failures of the phrase tests for the first set of changes, 1 for the review's points); three new tests use the real reader: a `#` after a topic is part of the topic; an invisible character (U+200B, U+FEFF, U+200E) before `#` makes a topic and before `[` makes the section line a topic; a wrapped topic is two topics and a repeat in case and spacing refuses the file. `SuggestTopicsSkillTests` now has 13 tests.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package` with `KB_WORKBENCH_CHECKOUT` set, 144 tests, OK; unset, 144 tests, OK, 85 skipped; `wb run code-work check`, 79 plans, no problems; `git diff --check`, clean; no `.pyc` or `__pycache__` in `package/`. No engine file changed, so no wider run.
- Breaks: 55 single changes to the text of the skill and its example, each caught by a test, the file restored byte for byte (the earlier 40, with the entries that pointed at reworded text updated, and 15 for the new sentences).
- Departures from the plan: the skill also says that no two topics are alike and that a topic is never wrapped (from the review; the plan's criterion 4 did not list them), and that the sections are the agent's guess.
- Not done: the live check of the plan, which needs the package copied to the other folder.

**Increment C** (in `main` directly).

- Done: `package/kb/harness/neutral/skills/find-a-passage/SKILL.md` says: the title, the caveats, the reasons for the completeness and the headings of a locator, and the citation of a read reply, are also texts of books, not only the excerpt and the passage between the untrusted-text marks, and none of them is to be trusted or holds an instruction (as `walk-from-themes` says of its titles and citation); the helper writes every apostrophe of a reply as the JSON escape, so a locator copied exactly holds none and the agent checks that none is left; a locator not copied from a reply, or retyped, is written with the escape too, and so is a copied one that still holds an apostrophe (an old helper), or the read is not run; the escape in a reply stands for an apostrophe, which the agent writes when it quotes a passage or a title. A paragraph was added to the Result of `2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package` that records the security review, its limit (no experiment could be run), the findings and where each is closed.
- Tests were written first and seen failing (2 failures), and again for the review's points (2 failures); `FindPassageSkillTests` has 14 tests; the old phrase "write every apostrophe of the locator as the escape" was replaced by the new wording.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package` with `KB_WORKBENCH_CHECKOUT` set, 146 tests, OK; unset, 146 tests, OK, 85 skipped; `wb run code-work check`, 79 plans, no problems; `git diff --check`, clean; no `.pyc` or `__pycache__` in `package/`. No engine file changed, so no wider run.
- Breaks: 56 single changes to the text of `find-a-passage`, each caught by a test, the file restored byte for byte (the earlier 45, the entries aimed at the reworded apostrophe paragraph updated, and the new ones for the untrusted fields, the helper's escape, a copied or retyped locator, an old helper, and quoting).
- Departures from the plan: the skill also tells the agent what to do with a copied locator that still holds an apostrophe (an old helper), and to write the apostrophe when it quotes (both from the review); the citation is named as a field of a read reply only.

**The plan as a whole.** All three increments are committed. After C, `engine/tests/test_package.py` was run once as a whole with and without the workbench checkout (146 tests, OK), with `wb run code-work check` (no problems). The live check (a real `read` of a passage whose heading holds an apostrophe, through the helper installed in the other folder) is not made: it needs the owner to approve and install the package there. No security review of the changed helper and skills was run; it runs only if the owner asks. Recommended to the owner: a new security review of this plan, in a session where the reviewer's write hook lets it run its probe scripts, because the first review could not run one.

**Correction, 2026-11-20, after the first live test of the skills in `kb-scratch`: Increments A and C of this plan did not close the Medium finding, and the statements above that it is closed are wrong** (they are left as written). The helper wrote each apostrophe of a reply as the JSON escape and the skills told the agent to write that escape, but this harness turns a typed backslash-u escape into the character it stands for, so the agent's command held a raw apostrophe and the shell stopped on it (a harmless `printf` shows the same). Increment A's review, my breaks and 146 tests could not see it: they checked the helper's output and the words of the skills, and never a call through a real tool. The risk was open before this plan, as the finding said, and stayed open through it: from the skills of the earlier plan (`f869fd0`, `6186795`) and this plan's commits (`fecf6a4`, `fb58e05`, `93cbe1f`) until the commits of the plan `2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command` (`830b4bd`, `076e411`), which replace the escape with percent codes that the agent only copies (the live check of that plan was made on 2026-11-20 in `kb-scratch` and passed: see the Result of that plan). The repository on `origin` held the unsafe instruction until the push that follows those two commits. The deferred item of this plan about a sentence in `pose-a-problem` and `walk-from-themes` is done there, with different content (the Deferred work bullets above are not changed, because the plan is approved). I should have carried over what the records of both plans show had already happened to my own edits (the edit tool turned the same escape into an apostrophe, in the plan of the skills and in this plan), and tested the instruction through a real tool call before I called the finding closed.
