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

Empty until a review is asked for.

## Deferred work

- The parenthesis "(every shelf is `default`)" in the same paragraph of `card.md` (a todo item of the owner).

## Result

Empty until work starts.
