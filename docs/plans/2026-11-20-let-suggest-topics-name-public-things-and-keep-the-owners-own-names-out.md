# Let suggest-topics name public things and keep the owner's own names out

Status: Completed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: one sentence of a skill, found by its first live use in `kb-scratch` on 2026-11-20; the owner asked for it)
Specs: docs/specs/knowledge-base.md ("Reading side": the skills)

## Goal

Step 2 of the skill `suggest-topics` says that a topic holds "no secret, no credential, no private text from the project, and no name of a project, product, company or person". Its purpose is that the crawl sends every topic to outside search services and to the owner's model server, so a topic must not leak who the owner is or what the project is. Read literally the rule is wider than that and also forbids a topic about a public thing: "Dijkstra's algorithm" names a person, "Cochrane risk-of-bias tools" names an organisation, "CONSORT reporting guidance" a standard. In the first live use of the skill (a question about bias in clinical-trial randomisation) the agent proposed a topic with "Cochrane RoB 2 and CONSORT" and then said that its topics held "no project, product or personal names", which was not true of the words and was harmless in fact. A rule that an agent states and breaks in the same answer is a rule to fix.

When this plan is done the skill says what the rule is for: a topic may name a **public thing when the topic is about that thing itself** (a method, a standard, a published work or tool, a public organisation, the person whose name a method carries), and it holds **no name that points at the owner**: not the owner's own project, product or company, and not a person that the conversation was about. The part about secrets, credentials and private text is unchanged.

## Scope

- `package/kb/harness/neutral/skills/suggest-topics/SKILL.md`: the sentence of step 2 that holds the rule.
- `engine/tests/test_package.py`: `SuggestTopicsSkillTests`, the phrase test of step 2.

## Non-goals

- The other rules of the skill (the form of the file, the comments, the repeats, the approval), the helper, the engine and the crawl: unchanged.
- A check in the engine that refuses a name (the crawl's reader cannot know which names are private). The skill is the only guard, as before.
- The owner's copy of the package in `kb-scratch` (the owner's approval, upgrade and re-render).

## Assumptions and constraints

- The crawl sends each topic to OpenAlex, arXiv, Wikipedia and a web search (each when the owner's plan has it on) and to the model server of the owner's config. A public name in a topic is as public as the page it will find; a private name is what must not go out.
- The skill cannot see the owner's project, so "points at the owner" is judged by the agent from the conversation; the sentence says what to look at (the project, its product, its company, the people the conversation was about) and keeps the existing escape: if the subject cannot be put in general words, do not propose it and tell the owner why.
- A tracked skill is text; a test shows its words and that the old sentence is gone. It does not show how an agent behaves.

## Completion criteria

1. Step 2 of `suggest-topics` says that a topic holds no name that points at the owner (the owner's own project, product or company, and a person that the conversation was about), and that a topic may name a public thing when it is about that thing itself (a method, a standard, a published work or tool, a public organisation); the old words "no name of a project, product, company or person" are gone; the sentences on secrets, credentials and private text, on general words, and on the comments are unchanged; a test holds each of these.
2. Each new phrase has a deliberate break that a test catches, and the file is restored byte for byte; the other tests of the skill pass unchanged.
3. The tests of the package pass with and without the workbench checkout, and `wb run code-work check` reports no problem.

## Increments

### Increment A — The sentence of step 2

**Outcome:** criteria 1 to 3.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/suggest-topics/SKILL.md`, `engine/tests/test_package.py`.
**Steps:**
1. Read step 2 of the skill and the phrase test of step 2 in `SuggestTopicsSkillTests`.
2. Write the test first and see it fail: the two new phrases, and that the old phrase "no name of a project, product, company or person" is not in the skill.
3. Change the sentence in the plain words of the skill; break each new phrase on purpose, one change at a time, and restore the file byte for byte.
**Verification:** `engine.tests.test_package.SuggestTopicsSkillTests` and the whole of `engine/tests/test_package.py`, with `KB_WORKBENCH_CHECKOUT` set and unset; `wb run code-work check`; `git diff --check`. No engine file changes, so no wider run.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-let-suggest-topics-name-public-things-and-keep-the-owners-own-names-out#A`, after an independent review by the `reviewer` agent.

## Verification for the plan as a whole

Increment A's recorded verification is the whole of it. The live use of the owner's copy in `kb-scratch` needs the owner to approve, upgrade and re-render the package; it is not a condition of this plan.

## Risks and sensitive actions

- **A looser rule lets a private name through.** The change keeps the guard where it matters (a name that points at the owner) and gives the agent a test it can apply (is the topic about the public thing itself?). The remaining risk is the agent's judgement, as before; the owner reads the block before anything is copied, and the crawl runs only under an approval that covers the file.
- The skill is package text: other projects keep the old text until the owner approves and installs the package there.
- No outside request, no secret, no crawl approval and no engine file is touched.

## Review record

Increment A, independent review by the `reviewer` agent, 1 exchange (of a cap of 6): no blocking findings; it ran nothing and did not read the crawl code or the population spec.

- **Found true (read only):** nothing else in the skill (the comments of evidence, the example block, step 4) conflicts with the new sentence; the secrets, credentials and private-text clauses and the general-words escape are intact; the test phrases match the text once white space is normalised and the scoping to step 2 is sound.
- **Applied:** (1) the new rule excluded fewer kinds of names than the old one, so an agent could call a client "a public organisation" or an internal tool "a tool": the sentence now also excludes the owner's team, an employer, a client, a colleague, an unpublished or internal tool and a private repository, defines "public" as "anyone can find it without this project or this conversation", and says to leave a name out when not sure that it is public; (2) "not a person that the conversation was about" collided with the eponym case that the plan's Goal allows ("Dijkstra's algorithm"): the sentence now allows "a person only as the name of a method or work"; (3) the escape "and tell the owner why" is now pinned by the test.
- **Noted, not changed:** the assertion that the old wording is gone is a literal check, so a reworded version of the old rule would pass it; a colleague who appears only in the project text and not in the conversation is covered by "a colleague" and by "no private text from the project", and the rest is the agent's judgement, as before.
- **Could not be checked by the reviewer:** any run result and the breaks; the exact old sentence (it could not run git); how an agent reads the rule in practice.

## Deferred work

- The earlier small matters of `suggest-topics`, if the owner wants them: that the agent says how many results each search returned from what it saw and does not report them loosely (the live use gave 3 in one answer and 4 in the next for the same search), and a search by meaning as well as by words before the agent calls a gap.

## Result

**Increment A** (in `main` directly, as the earlier plans' increments were).

- Done: step 2 of `package/kb/harness/neutral/skills/suggest-topics/SKILL.md` now says that a topic holds no secret, no credential, no private text from the project, and **no name that points at the owner**: not the owner's own project, product, company or team, not an employer, a client or a colleague, not an unpublished or internal tool or a private repository, and not a person that the conversation was about; that a topic **may name a public thing when it is about that thing itself** (a method, a standard, a published work or tool, a public organisation, or a person only as the name of a method or work); that **public means that anyone can find it without this project or this conversation**, and that a name of which the agent is not sure is left out; and, unchanged, that a subject that cannot be put in general words is not proposed and the owner is told why. The test of step 2 holds each of these and that the old words "no name of a project, product, company or person" are gone.
- The test was written first and seen failing, and again for the review's points (1 failure each time), then passing.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package` with `KB_WORKBENCH_CHECKOUT` set, 164 tests, OK; unset, 164 tests, OK, 100 skipped; `wb run code-work check`, 82 plans, no problems; `git diff --check`, clean; no `.pyc` or `__pycache__` in `package/`. No engine file changed, so no wider run.
- Breaks: 65 single changes to the text of `suggest-topics` (the 59 before, with the entries for the old names rule replaced by 12 for the new sentence: each exclusion, the allowance for a public thing and its kinds, the person as the name of a method, the definition of public, "leave it out when not sure", and "tell the owner why"), each caught by a test, the file restored byte for byte.
- Departures from the plan: the sentence is longer than the plan's criterion 1 says (it adds the employer, client, colleague, internal tool and private repository, the definition of public, the person as the name of a method, and "when not sure leave it out"), from the review; both requirements of criterion 1 are met (a name that points at the owner is excluded, a public thing may be named) in wider words than the criterion's, and the old wording is gone.
- Not done: the owner's approval, upgrade and re-render of the package in `kb-scratch`, where a new use of the skill would show the rule at work; the two small matters in Deferred work.
