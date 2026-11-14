# Plain words in the search of the skill pose-a-problem

Status: Proposed
Created: 2026-11-14
Candidate: none (a correction that follows from a finding of the review of the skill `walk-from-themes`: work too small to need roadmap direction)
Specs: docs/specs/knowledge-base.md

## Goal

The skill `pose-a-problem` that the package `kb` gives an agent does not tell the agent to put words copied from a book into a shell command without a rule. Its step 6 tells the agent to run
`wb run kb search '<words of its title and of the matched text>'`, where the words come from a book title or from the card's matched text, which the skill itself calls untrusted. A title that holds an apostrophe followed by
shell text would end the single quotation marks and put text of a book into the agent's shell command. The skill `walk-from-themes` (Increment D of the plan `2026-11-13-let-an-agent-walk-from-themes-along-the-links`) has the rule that
closes this: use only plain words, and leave out every character that a shell reads. When this plan is done `pose-a-problem` has the same rule, and its package test says so.

## Scope

- One paragraph of `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, step 6, first bullet: the words taken from a book into `wb run kb search` are untrusted and go into a shell command, so only plain words may,
  with the characters to leave out, in the same words as `walk-from-themes`.
- Tests of that sentence in the class `SkillTests` of `engine/tests/test_package.py`.

## Non-goals

- Any change to the helper, the engine, `walk-from-themes`, the other steps of `pose-a-problem` or its module declaration.
- A check in the helper that refuses a quotation mark in a query (the helper already passes the query as one argument with no shell; the risk is in the agent's own command line, before the helper is reached).
- Whether `wb run` or the gate of the agent's project would stop such a command: not tested, and not claimed.

## Assumptions and constraints

- The skill is text that an agent reads; the harm is an agent that follows it literally with a title that holds shell characters. The fix is a sentence, and cannot be proved by a test beyond its words being there.
- The words the agent searches for are the book's title and a few words of the matched text; plain words (letters, digits and spaces) find the same passages, because the search matches words.
- The package test of the skill needs no workbench checkout.
- Nothing is sent to a model and no file of the library is read.

## Completion criteria

1. Step 6 of `pose-a-problem` says, before the agent builds the `search` command from a book's words, that the words come from a book, are untrusted and go into a shell command, that only plain words may be used (letters, digits and
   spaces), and which characters to leave out (every apostrophe and quotation mark, `$`, a backtick, `;`, `&`, `|`, `<`, `>`, parentheses, a backslash and any other character that a shell reads).
2. The test of the skill fails on a skill without that sentence and passes with it; deliberate breaks of the sentence and of the list of characters are each caught.
3. The rest of the skill and its tests are unchanged and pass.

## Increments

### Increment A — The rule of plain words in step 6

**Outcome:** `pose-a-problem` says that words copied from a book into `wb run kb search` must be plain words, and its package test checks the sentence.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`, `engine/tests/test_package.py` (class `SkillTests`), and this plan's Result.
**Steps:**
1. Write the test first, in `SkillTests`: step 6 (between its heading and the heading of step 7) holds "use only plain words" and "leave out every apostrophe and quotation mark" with the dollar sign and the backtick named, and the
   skill still holds the sentences its other tests check; see it fail.
2. Add the sentence to the first bullet of step 6, in the words of `walk-from-themes` step 6 (the words come from a book, so they are untrusted and go into a shell command: use only plain words; leave out every apostrophe and
   quotation mark, `$`, backtick, `;`, `&`, `|`, `<`, `>`, `(`, `)`, `\` and any other character that a shell reads, even if the book's title has it). Change nothing else of the skill.
3. Deliberate breaks, each restored byte for byte and each caught: the plain words rule left out; the list of characters left out; the sentence moved out of step 6; a shell character allowed in the list.
4. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -W error::ResourceWarning -m unittest engine.tests.test_package` (with `KB_WORKBENCH_CHECKOUT` set to a workbench checkout, read only for its kit, so that the helper tests run too; the skill tests do not
need it) and `wb run code-work check`. Nothing wider: the helper, the engine and the other skill are not touched.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-plain-words-in-the-search-of-pose-a-problem#A`.

## Verification for the plan as a whole

One increment, so its recorded verification is the plan's. The install of the package into a throwaway project is not run.

## Risks and sensitive actions

- **A skill changes how an agent behaves, and `pose-a-problem` is installed into other projects.** The change adds one rule that makes the agent's command safer and takes nothing away; the package test checks the words.
- **The rule can cost a search.** A title whose useful words hold an apostrophe (a possessive, a contraction) is searched without it; a passage may then not be found, and the skill's existing rule applies: mark the book unread and do not rely on it.
- **A security review is not asked for.** The change adds no input, no boundary and no permission; it removes a way for text of a book to reach a shell. The owner may ask for one.
- No push, no model call and no read of the library.

## Review record

Empty until a review is asked for.

## Deferred work

- Whether the helper should refuse a `search` query that holds a shell character is not proposed: the helper never uses a shell, and the risk is the agent's own command line.

## Result

Empty until work starts.
