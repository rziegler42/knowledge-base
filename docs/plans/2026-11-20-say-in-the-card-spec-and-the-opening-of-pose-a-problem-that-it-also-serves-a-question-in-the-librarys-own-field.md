# Say in the card spec and in the opening of pose-a-problem that it also serves a question in the library's own field

Status: Proposed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: it finishes the plan `2026-11-20-keep-the-books-of-the-problems-own-field-and-name-the-reference-pages-in-the-search-skills`, whose review found two places that still say the old rule and were outside its Scope)
Specs: docs/specs/card.md

## Goal

Step 5 of the skill `pose-a-problem` now starts from what the owner asked for (commit `3234b76`): for a request of ideas from other fields the books of the problem's own field are set aside, and for a question in a field the library is mainly about they are kept as the answer. Two places still say only the old rule (two todo items of the owner, from the review of that increment):

1. `docs/specs/card.md`, lines 199 to 200, say without a condition that the caller sets aside the books of the problem's own field.
2. The skill's front matter description, its opening paragraph and its step 1 speak of ideas from other fields only, so an agent may not use the skill for a question in the library's own field, which the new step 5 serves.

When this plan is done both say what step 5 says: the caller decides from what the owner asked for.

## Scope

- `docs/specs/card.md`: the one sentence of the "Built in the engine" paragraph on `problem-search` that says the caller sets aside the books of the problem's own field.
- `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`: the `description` of its front matter, the opening paragraph ("Use this when ..."), and the last sentence of step 1.
- `engine/tests/test_package.py`: `SkillTests`.

## Non-goals

- The rest of the skill (step 5 and the other steps stay as committed) and `walk-from-themes`.
- The other words of the same paragraph of `card.md`, in particular the parenthesis "(every shelf is `default`)", which stopped being true on 2026-11-20 when 879 books were moved onto shelves: it is recorded as a todo item and not changed here.
- Any change to the engine, the helper or the approval of the crawl: no file of `engine/kb` changes.

## Assumptions and constraints

- The description must stay between 30 and 300 characters (a test holds it), and the skill's name and the folder name stay.
- The rules of step 1 that are about what is sent out (general terms, no secret) are not touched; only the aim of the restatement is said in one more clause.
- A spec states what is true now; the sentence is rewritten to say what the skill does, and the spec is not otherwise reopened.

## Completion criteria

1. The sentence of `card.md` says that the engine sets nothing aside by field, that the caller decides from what the owner asked for, setting the books of the problem's own field aside for a request of ideas from other fields and keeping them as the answer for a question in a field the library is mainly about, and names step 5 of the skill.
2. The front matter description says the skill finds books that fit "from other fields or from the problem's own field, as the owner asked", within 300 characters.
3. The opening paragraph says the skill is for ideas from other fields or for an answer from a field the library is mainly about.
4. The last sentence of step 1 says that a description that a book from another field could match also finds the books of the problem's own field that say the same thing in other words.
5. The tests of the skill fail on a skill without these sentences and pass with them; each sentence has a deliberate break that a test catches; the rest of the skill and its tests are unchanged and pass.

## Increments

### Increment A — The card spec

**Outcome:** `docs/specs/card.md` no longer says the old rule without a condition.
**Dependencies:** none.
**Affected areas:** `docs/specs/card.md`.
**Steps:**
1. Read lines 194 to 204 of `card.md` and step 5 of the skill; rewrite the one sentence ("the caller sets aside the books of the problem's own field") as in criterion 1, keeping the rest of the paragraph as it is.
**Verification:** `wb run code-work check`; `git diff --check`; a read of the sentence against step 5 of the skill. There is no test of the spec's wording.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-say-in-the-card-spec-and-the-opening-of-pose-a-problem-that-it-also-serves-a-question-in-the-librarys-own-field#A`.

### Increment B — The front matter, the opening paragraph and step 1 of the skill

**Outcome:** the three places of the skill say that it also serves a question in the library's own field.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, `engine/tests/test_package.py` (`SkillTests`).
**Steps:**
1. Read the three places and the tests that hold them (`test_the_skill_is_a_neutral_skill_with_a_name_and_a_description`, `test_it_says_how_to_restate_the_problem_and_what_to_leave_out`).
2. Write the tests first and see them fail: the description holds "from other fields or from the problem's own field" and stays within 300 characters; the opening paragraph holds "or an answer from a field that the library is mainly about"; step 1 holds the sentence of criterion 4.
3. Write the three texts in the plain words of the skill.
4. Break the text on purpose, one change at a time (each of the three sentences removed or inverted), see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-say-in-the-card-spec-and-the-opening-of-pose-a-problem-that-it-also-serves-a-question-in-the-librarys-own-field#B`.

## Verification for the plan as a whole

Each increment's verification stands. After B, `engine/tests/test_package.py` is run once more as a whole with `code-work check`. No engine code changes, so no wider run is named and the crawl's approval is not touched.

## Risks and sensitive actions

None identified: text of a spec and of a skill, no code, no network, no approval of the crawl. The one risk is wording that makes an agent use the skill where it should not; the description keeps its first words and its purpose, and step 5 is where the agent decides what to do with own-field books.

## Review record

No review by the review engine (Codex): the owner chose to commit, approve and implement at once. Independent review of both increments by the `reviewer` agent (read only, 1 exchange of a cap of 6): no blocking findings. It found the spec sentence true of the engine (`problem-search` sets nothing aside) and of step 5 of the skill, the three new places of the skill in agreement with steps 5 and 7, the description a fair summary of about 235 characters within the limit of 300, and no way for the new text to make an agent use the skill where it should not or forget the cross-field aim.

- Applied: the spec sentence names "the caller" in both clauses, so that "it" cannot be read as the engine, which the sentence's own opening says sets nothing aside.
- Noted, not changed: (a) the spec sentence does not give step 5's third case (cannot tell: keep both groups and say so), which is acceptable for one sentence of a spec; (b) "(every shelf is `default`)" stays in the same sentence and is stale, as the plan says (a todo item); (c) "a field that the library is mainly about" is not defined and the agent judges it, which step 5's third case covers; (d) the "it" of step 1's added clause and of the opening's last clause are loose but unambiguous; none of these changes behaviour.
- Could not be checked by the reviewer: any run result; the diff against `HEAD` (it read the current files); whether another file of the repository states the old unconditional rule (not searched by it). I searched `docs/`, `package/` and `engine/README.md` for it myself after the review (my first search failed on a shell glob and was repeated) and found three more places outside this plan's Scope: `engine/README.md` lines 885 and 903 (the guide's description of `problem-search` and of the skill), and the roadmap `docs/roadmaps/cross-field-discovery.md` line 65, which describes the intended command and skill in the roadmap's own words (a roadmap is direction, and a change to it is the owner's).

## Deferred work

- The parenthesis "(every shelf is `default`)" in the same paragraph of `card.md` (a todo item of the owner).
- The two sentences of `engine/README.md` (lines 885 and 903) that still say the caller sets aside the books of the problem's own field without a condition (a todo item of the owner), and the line of the roadmap `cross-field-discovery.md` that says the same, which the owner may leave as the roadmap's own words.

## Result

**Increment A** (in `main` directly: a spec, no engine code, so the approval of the crawl is not touched). The sentence of `docs/specs/card.md` that said the caller sets aside the books of the problem's own field without a condition now says the caller decides from what the owner asked for (step 5 of `pose-a-problem`): for a request of ideas from other fields the caller sets them aside, and for a question in a field the library is mainly about the caller keeps them as the answer. Verification: `wb run code-work check`, 77 plans, no problems; `git diff --check`, clean; the sentence read against step 5. There is no test of the spec's wording. Departures from the plan: none.

**Increment B** (in `main` directly, for the same reason). The `description` of the front matter of `pose-a-problem` says it finds books "from other fields or from the problem's own field, as the owner asked" (about 235 characters); the opening paragraph says it is for ideas from other fields "or an answer from a field that the library is mainly about"; the last sentence of step 1 says the description also finds the books of the problem's own field that say the same thing in other words. One new test in `SkillTests`, written first and seen failing (1 failure), then passing. Verification: `python3 -B -m unittest engine.tests.test_package`, 111 tests, OK, 77 skipped (as before), Python 3.15.0; `wb run code-work check`, no problems; `git diff --check`, clean. Breaks (7 single changes: the description back to other fields only, "as the owner asked" removed, the description over 300 characters, the opening's own-field answer removed, the opening's cross-field use removed, the step 1 sentence removed, and inverted), each caught by the new test, the file restored byte for byte. Departures from the plan: none.
