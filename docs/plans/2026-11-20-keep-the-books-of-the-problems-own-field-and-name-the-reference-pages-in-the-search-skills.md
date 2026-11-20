# Keep the books of the problem's own field when it is what was asked for, and name the reference pages, in the search skills

Status: Proposed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: a correction that follows from the first use of the two skills on a real question, 2026-11-20)
Specs: docs/specs/knowledge-base.md

## Goal

The skill `pose-a-problem` of the package `kb` tells the agent, in its step 5, to **set aside** each book that is from the problem's own field, "because that is not what you were asked to find". That is right when the owner asked for ideas from other fields. It is wrong when the owner asks a question in a field that the library is mainly about.

Measured on 2026-11-20, by running the skill as an agent would on the owner's question "For a card game with incomplete information, how can I combine a learning AI with Monte Carlo tree search so that game play will improve as the AI learns" (restated in general terms, three sub-problems, `python3 -m kb problem-search --limit 6` at commit `294315c` of `main`, Python 3.15.0): the search covered all 925 cards and returned 17 books; the best matches were in the library's own field, game-playing AI (the paper on planning in the observation space for trick-taking card games, which answers the question directly and whose passage was read and found to match its card, the MuZero papers, Silver's thesis, the regularized-policy-optimization paper); a literal agent would have set every one of them aside. Seven of the 17 books were encyclopedia pages (Thompson sampling, Reinforcement learning, Hidden Markov model, Bayesian inference, Kalman filter, Ant colony optimization, Entropy), which give the name of a concept and are not an idea of another field; the skill does not say to tell them from papers. The walk (`walk-from-themes`, 12 leads) had the same kind of page among its leads (Minimax and Game theory in the follow-through lane, PageRank in the exploration lane).

When this plan is done:

1. `pose-a-problem` step 5 starts from what the owner asked for. For a request of ideas from other fields it is as it was (set aside the books of the problem's own field, and say which and why). For a question in a field the library is mainly about, the books of that field are the answer: they are kept under the same rules of step 6, listed first under the heading "From the problem's own field", and the books of other fields come after under "From other fields". When the agent cannot tell which the owner wants, it keeps both groups, names them, and says that it could not tell.
2. Both skills tell the agent to say which kept books or leads are encyclopedia or reference pages, and not to rest a claim that something works on such a page alone.

## Scope

- `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`: step 5 (and the one sentence of step 7 that says what to report when nothing fits, so that it agrees), and one paragraph in step 6.
- `package/kb/harness/neutral/skills/walk-from-themes/SKILL.md`: one paragraph in step 6.
- `engine/tests/test_package.py`: the tests of both skills (`SkillTests`, `WalkSkillTests`).

## Non-goals

- Any change to the engine, the helper, a search or a score, or to the approval of the crawl (no file of `engine/kb` changes).
- A filter of the search by the kind of a book or by its shelf (`wb run todo list` holds it as a todo item for the owner: a change of the helper and the engine, and its own plan).
- The agent for the library: the owner decided to look at it after the skills have been used.
- The installed copy of the skills in the owner's other folder (`kb-scratch`): the owner refreshes it.
- A rule for what counts as the library's field. The agent judges from the titles of the best matches and from the question, as step 5 already asks it to judge the field of a book, and says what it judged.

## Assumptions and constraints

- The skills are text that an agent reads; a test can show the words and cannot show how an agent behaves. The measurement above is one question; the plan does not claim more.
- Whether the owner wants the books of the problem's own field kept for a question in that field is the owner's decision about what the skill is for. Approving the plan is that decision; the first sentence of the goal says what it is.
- The rules that exist stay as they are: plain words in the search, untrusted data, single quotes, no loops, one call, a book read before it is relied on, the card's description quoted as the card's and not as the book's.
- A reference page is told by what the citation says (it names the site, which for an encyclopedia is plain); the skill does not name sites, so that no list goes stale.

## Completion criteria

1. Step 5 of `pose-a-problem` says: read what the owner asked for; for ideas from other fields set aside the books of the problem's own field and say which and why; for a question in a field the library is mainly about keep them, under "From the problem's own field", before the books "From other fields"; when you cannot tell, keep both groups and say so.
2. Step 7 of `pose-a-problem` agrees: "nothing from another field fit" is said only for a request of ideas from other fields, and a question in the library's own field is not answered with it while books of that field were kept.
3. Step 6 of both skills says: say which kept books or leads are encyclopedia or reference pages (the citation names the site); they give a concept or the name of a method; a paper or a book that matches as well comes before them; a claim that something works is not supported by such a page alone.
4. The tests of both skills fail on a skill without these sentences and pass with them, each sentence has a deliberate break that a test catches, and the rest of both skills and their tests are unchanged and pass.

## Increments

### Increment A — `pose-a-problem`: the problem's own field, and the reference pages

**Outcome:** step 5 and step 7 of `pose-a-problem` say what to do for each kind of request, and step 6 names the reference pages.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, `engine/tests/test_package.py` (`SkillTests`).
**Steps:**
1. Read steps 5 to 7 of the skill and the tests of it (`SkillTests`), including `test_it_says_the_engine_does_not_set_the_own_field_aside_and_the_agent_does_from_title_and_matched_text`, which holds "the engine sets nothing aside: you do", "set aside", "say which" and "own field", so that those phrases stay.
2. Write the tests first and see them fail: step 5 tells the agent to read what the owner asked for, to set the own-field books aside for a request of ideas from other fields, to keep them under "From the problem's own field" before "From other fields" for a question in the library's field, and to keep both and say so when it cannot tell; step 7 does not tell the agent to say "nothing from another field fit" for a question in the library's own field while books of that field were kept; step 6 names the reference pages and says what they are and are not.
3. Write the paragraphs, in the existing sections and in the plain words of the skill.
4. Break the text on purpose, one change at a time (each of the sentences removed or inverted), see a test fail for each, and restore the files byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-keep-the-books-of-the-problems-own-field-and-name-the-reference-pages-in-the-search-skills#A`.

### Increment B — `walk-from-themes`: the reference pages

**Outcome:** step 6 of `walk-from-themes` names the reference pages in the same words.
**Dependencies:** Increment A (the same words).
**Affected areas:** `package/kb/harness/neutral/skills/walk-from-themes/SKILL.md`, `engine/tests/test_package.py` (`WalkSkillTests`).
**Steps:**
1. Write the test first and see it fail; write the paragraph; break it on purpose and restore.
**Verification:** the new test and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-keep-the-books-of-the-problems-own-field-and-name-the-reference-pages-in-the-search-skills#B`.

## Verification for the plan as a whole

Each increment's recorded verification stands. After B, `engine/tests/test_package.py` is run once more as a whole with `code-work check`. A live check, read only and by hand, on the same question as the measurement: the owner reads what an agent that follows the new text reports, and says whether it keeps the card-game paper and names the encyclopedia pages. No engine code changes, so no wider run is named and the crawl's approval is not touched.

## Risks and sensitive actions

- **A change in what an agent is told to report.** The new step 5 lets an agent present books of the problem's own field as the answer. The two named headings and the rules of step 6 (a reason made from the matched text, the card quoted as the card's, the book read before it is relied on) stay, so such a book is held to the same standard as any other.
- **A wrong reading of the request.** An agent may take a question for one of the two kinds wrongly. The rule for "cannot tell" is to keep both groups and say so, which costs a longer answer and no lost book.
- Nothing sensitive: no engine code, no network, no approval of the crawl; a security review is not asked for.

## Review record

Plan review through the review engine (`gpt-5.6-terra`), 1 round of a bound of 3, converged on 2026-11-20: no meaningful findings; the reviewer found the plan actionable, consistent with its named spec, and its scoped changes covering the stated behaviour. Applied: none. Rejected: none. Before the review I corrected one detail of the plan myself (PageRank was a lead of the exploration lane, not of the follow-through lane). Left for the owner: the approval, which is also the decision about what `pose-a-problem` is for (the first sentence of the goal).

## Deferred work

- The filter by kind or shelf (a todo item of the owner).
- The agent for the library, after the skills have had use.
- The skills for running the library (the status of the loop, a hand run with the stop file, a change of the engine, the command forms of the gate), which the project does not have.

## Result

Empty until work starts.
