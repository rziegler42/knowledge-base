# Let suggest-topics name public things and keep the owner's own names out

Status: Proposed
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

Empty until a review is asked for.

## Deferred work

- The earlier small matters of `suggest-topics`, if the owner wants them: that the agent says how many results each search returned from what it saw and does not report them loosely (the live use gave 3 in one answer and 4 in the next for the same search), and a search by meaning as well as by words before the agent calls a gap.

## Result

Empty until work starts.
