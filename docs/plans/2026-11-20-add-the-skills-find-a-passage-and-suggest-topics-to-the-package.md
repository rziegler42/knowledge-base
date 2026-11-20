# Add the skills find-a-passage and suggest-topics to the package

Status: Proposed
Created: 2026-11-20
Candidate: none (work too small to need roadmap direction: two skills that complement `pose-a-problem` and `walk-from-themes`, found by the first use of those two on 2026-11-20; the owner may say that it belongs to a roadmap)
Specs: docs/specs/knowledge-base.md ("Reading module": the skills that make an agent use the library)

## Goal

The package `kb` gives an agent two skills, both of which search by meaning. The helper also offers a search by words and the reading of a passage (`wb run kb search`, `wb run kb read`), and **no skill teaches them**: the two existing skills use them only as the check at the end (step 6 of each, which repeats the same rules). And nothing connects what an agent finds missing in the library to what the crawl collects.

When this plan is done the package has two more skills:

1. **`find-a-passage`**: when to search by words and not by meaning; how to write the words (plain words only, because they go into a shell command); how to call `wb run kb search` and read its results; how to pick the result of the book meant; how to read the passage with `wb run kb read` and follow `next`; how to quote the passage as the book's own words with its citation; when to mark a book unread. The numbers it gives (the limit of the search, the longest query, the size of a read) are those of the helper, and a test holds them.
2. **`suggest-topics`**: when an agent has found a gap in the library (a search that covered little, a search where nothing fits, results that were only reference pages), how to turn it into at most five proposed lines for the owner's file of crawl topics, in the format of that file, each with the evidence and a section (core, exploratory or low). **The agent writes nothing**: the file is the owner's, private and outside the repository, and changing it is the owner's decision (the crawl must be approved again after any change to it). The skill says that the topics go to outside search services when the crawl runs, so a topic holds no private text.

## Scope

- `package/kb/harness/neutral/skills/find-a-passage/SKILL.md` and `package/kb/harness/neutral/skills/suggest-topics/SKILL.md` (new; one file in each folder, as the two skills have).
- `engine/tests/test_package.py`: one test class for each skill, like `SkillTests` and `WalkSkillTests`.
- `docs/specs/knowledge-base.md`: where it lists the skills the package ships, if it does (read first; the sentence is added or left as it is).

## Non-goals

- Any change to the helper, the engine or the module declaration, or to the approval of the crawl: no file of `engine/kb` changes and no command is added. The two skills use `wb run kb search` and `wb run kb read`, which exist.
- Changing step 6 of `pose-a-problem` and `walk-from-themes` so that they point at `find-a-passage`. The two skills repeat the rules today and their tests hold them in each; a pointer is a change of both, and an agent that has only one skill loaded would lose the rule. Recorded as deferred.
- Reading or writing the owner's file of topics, the crawl's plan, or the crawl's queue. The agent proposes in its answer; the owner copies.
- The agent for the library, and the skills for running the library (the status of the loop, a hand run, a change of the engine): their own plans, if the owner wants them.
- The installed copy of the skills in the owner's other folder (`kb-scratch`): the owner refreshes it.

## Assumptions and constraints

- **The command is `wb run kb`.** The built module is named `kb` (`package/kb/module.json`: `"name": "kb"`, command `kb`), and the helper and both existing skills use `wb run kb ...` (15 places in the package, the specs and the guide). `docs/specs/knowledge-base.md` (line 123, marked agreed) says the project, module and command are all named `knowledge-base` and that an agent runs `wb run knowledge-base ...`, and `docs/specs/library.md` (line 264) has `wb run knowledge-base backup-pause`: the spec differs from what was built. The plan follows what was built, because a skill that names a command that does not exist cannot work; whether the name is to change, or the spec is to be corrected, is the owner's decision and is not made here (a todo item of the owner).
- A skill is text an agent reads. A test shows the words, and that the numbers agree with the helper and the format agrees with the reader of the topics file; it does not show how an agent behaves.
- **What an agent writes into `wb run kb search` goes into a shell command**, so only plain words (letters, digits and spaces) may be used, in single quotes, with none of the characters a shell reads: the rule the two skills already hold, in the same words.
- Everything the library returns (a title, an excerpt, a passage, a citation) is untrusted text from outside: not an instruction, whatever it says.
- The file of topics (`kb/crawltopics.py`): one topic to a line, at most 300 characters, no repeat of another line, sections written `[name weight=N]` with a whole number from 1 to 999999 and a name of up to 40 letters, digits, `-` or `_`, a `#` starting a comment; the owner's three sections are `core` (10), `exploratory` (5) and `low` (1). The crawl sends the topics to outside search services (OpenAlex, arXiv, Wikipedia, a web search; `docs/specs/population.md`), which is why a topic holds no secret and no private text, and the digest that the owner approves covers the topics file.
- The agent cannot see the owner's topics file, so it cannot tell a repeat. The skill says so and asks the owner to compare.

## Completion criteria

1. `find-a-passage` has a name and a description within the limits the other skills' tests hold, and says: use a search by words when you know words that occur in the book and use `pose-a-problem` for ideas; write plain words only, few and distinctive, because every word must match in one passage; the call `wb run kb search [--limit <1-20>] -- '<words>'` with the limit, the longest query and the single quotes the helper has; read what a result carries (`book_id`, `version_id`, `title`, `excerpt`, `locator`, `is_current`, `caveats`, `completeness`); pick the result whose `book_id` is the book meant and no other; the call `wb run kb read [--version v<N>] [--chars <100-20000>] <book> '<locator-json>'` with the locator exactly as a result gave it; follow `next` to read on; quote the passage as the book's own words, with its citation and never a path, and say what the caveats and the completeness say; mark the book unread when no passage turns up and do not rely on it; at most three tries with fewer or other words, no loop; the reply is untrusted data; stop and tell the owner when the helper refuses for its settings.
2. `suggest-topics` has a name and a description within the same limits, and says: use it only for a gap you found by searching in this conversation (a search that covered little, a search where nothing fit, only reference pages); check with `wb run kb search` that the library holds little on it (read only; plain words); propose at most five lines, each one idea of at most 300 characters, in the topics file's own form (a section line `[name weight=N]` as the owner's file has them, then the lines), with the evidence for each written as a `#` comment line above its topic (which the reader of the file skips) or as prose outside the block, **never as a plain line inside the block, which the crawl would read as one more topic and send out**; propose a section, never a weight of your own; write nothing and read no file of the owner's; the topics go to outside search services when the crawl runs, so a topic holds no secret, no private text and no name of a project, product or person; you cannot see the owner's file, so the owner compares for repeats; changing the file needs the owner's approval of the crawl again; say what you could not tell.
3. The example block that `suggest-topics` shows is read by the real reader of the file (`crawltopics.parse_topics`) without refusal and **yields exactly the topics the example proposes and no other line** (at most five, so no evidence or explanation becomes a topic), and the numbers of `find-a-passage` are those of the helper (read from it by a test, as the test of `walk-from-themes` does).
4. Each skill's tests fail on a skill without a sentence and pass with it, each sentence has a deliberate break that a test catches, each skill folder holds only `SKILL.md`, no skill holds a marker of the library's text or a control character, and the rest of the package and its tests are unchanged and pass.

## Increments

### Increment A — `find-a-passage`

**Outcome:** the package has the skill `find-a-passage`, with a test class that holds its words and ties its numbers to the helper.
**Dependencies:** none.
**Affected areas:** `package/kb/harness/neutral/skills/find-a-passage/SKILL.md`, `engine/tests/test_package.py`, `docs/specs/knowledge-base.md` (if it lists the skills).
**Steps:**
1. Read the two existing skills' tests and step 6 of each, the helper's `search` and `read` (limits, what it refuses, what it prints), the engine's `search` and `read` replies (`kb/search.py`, `kb/read.py`: the keys of a result, `next`, `completeness`, the markers), and the lines of `docs/specs/knowledge-base.md` that name the skills.
2. Write the tests first and see them fail (the skill does not exist): the file and its front matter; each sentence of criterion 1; the numbers of the helper (`CEILING_LIMIT`, `MAX_QUERY`, the `--chars` bounds, `MAX_LOCATOR`) read from its source; no marker and no control character; one file in the folder.
3. Write the skill in the plain words of the other two.
4. Break the text on purpose, one change at a time (each rule removed or inverted: the plain words, the single quotes, the pick by `book_id`, `next`, the locator exactly as given, quoting as the book's words, unread, the three tries, untrusted data, the refusal), see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package#A`.

### Increment B — `suggest-topics`

**Outcome:** the package has the skill `suggest-topics`, with a test class that holds its words and parses its example with the real reader of the topics file.
**Dependencies:** none (it may name `find-a-passage` for the check, and holds without it).
**Affected areas:** `package/kb/harness/neutral/skills/suggest-topics/SKILL.md`, `engine/tests/test_package.py`.
**Steps:**
1. Read `kb/crawltopics.py` (the form of the file, the limits), the paragraph of `docs/specs/population.md` on the topics and on what the owner approves, and the owner-facing text of `crawlapprove.py` on the topics.
2. Write the tests first and see them fail: the file and its front matter; each sentence of criterion 2; the example block of the skill, taken from the file by the test and parsed by `crawltopics.parse_topics` without refusal, the parsed topics being exactly the lines of the example that are topics (the section line and the `#` comment lines of evidence give none; at most five topics, none over 300 characters, no repeat), and a test that an evidence line written as a plain line inside the block would be one more topic (so the skill's rule is the one that matters); no marker and no control character; one file in the folder.
3. Write the skill in plain words, with the example and the evidence line for each proposal.
4. Break the text on purpose, one change at a time (each rule removed or inverted: only for a gap found by searching, the check by words, at most five, a section and never a weight of one's own, writes nothing, outside services and no private text, the owner compares, the approval again, say what you could not tell) and a break of the example (a section line that the reader refuses), see a test fail for each, and restore the file byte for byte.
**Verification:** the new tests and the whole of `engine/tests/test_package.py`; `wb run code-work check`; `git diff --check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-20-add-the-skills-find-a-passage-and-suggest-topics-to-the-package#B`.

## Verification for the plan as a whole

Each increment's recorded verification stands. After B, `engine/tests/test_package.py` is run once more as a whole with `code-work check`. No engine code changes, so no wider run is named and the crawl's approval is not touched. A live check, by hand and read only, once the owner has copied the skills to the project that has the helper: an agent given a real question uses `find-a-passage` to read a passage of a book that `pose-a-problem` found, and `suggest-topics` after a search that covered little gives at most five lines that the owner can read in the form of the file.

## Risks and sensitive actions

- **`suggest-topics` is about what goes out.** The topics it proposes are sent by the crawl to outside services once the owner adds them. The skill tells the agent to keep private text out of every line, and the agent writes nothing: the owner reads each line and chooses. A topic that names a private project would still be the owner's doing, and the skill asks the agent to avoid it, which a test holds as words and cannot enforce.
- **Words into a shell command.** `find-a-passage` repeats the rule of plain words for the words an agent copies from a book into `wb run kb search`; a weaker sentence would be a regression of the plan `2026-11-14-plain-words-in-the-search-of-pose-a-problem`, and the tests hold the same phrases.
- **A skill that tells an agent to read a book's passage** reads data from outside: it is marked untrusted and the skill says so first.
- Nothing sensitive in the engine: no code, no network, no approval of the crawl. The owner is asked once whether to run a security review with the installed `security-reviewer`, because of the two points above.

## Review record

Plan review through the review engine, 3 rounds of a bound of 3, converged on 2026-11-20. Rounds 1 and 2 ran with the profile `standard` (`gpt-5.6-terra`, medium effort); **round 3 ran with the profile `second-opinion` (`gpt-6.1-sol`, low effort)**, a different model and a lower effort than the first two. The review engine chooses the profile of each round from the owner's `review-profiles.json`; I did not choose it, and a round at low effort that finds nothing is weaker evidence than one at medium effort.

- Round 1, one finding (major), applied as a record and not as a change of the plan's command: the plan has the skills teach `wb run kb`, and `docs/specs/knowledge-base.md` (marked agreed) says the command is `wb run knowledge-base`. The built module, the helper and both existing skills use `kb`, so a skill that named the other would not work; the discrepancy is written into the assumptions and is a todo item of the owner (a spec that differs from what was built, to be settled by the owner).
- Round 2, one finding (major), applied: an evidence line for a proposed topic written as a plain line inside the block would be parsed as one more topic and sent by the crawl to outside services. The skill now puts the evidence in a `#` comment line above the topic (which the reader skips) or in prose outside the block; criterion 3 and Increment B require that the parsed example yields exactly its topics, and a test shows that a plain evidence line would become a topic.
- Round 3: no meaningful findings.
- Rejected: none. Left for the owner: the approval; the security review (asked once, in the owner's hands); the todo on the command name.

Increment A, independent review by the `reviewer` agent, 2 exchanges (of a cap of 6).

- **First exchange: one blocking finding and three others, all applied.** (1) **Blocking:** the skill put the locator of a read between single quotes with no rule for a quote inside it, and a locator carries text of the book (headings and words of the passage). Checked on the owner's library: 5 of 200 locators returned by a search held an apostrophe or a quotation mark (headings such as "Dijkstra's algorithm"), so a locator can end the single quotes of the agent's own shell command. The skill now says that a locator holds text of the book, that every apostrophe of it is written as the JSON escape of an apostrophe (it means the same locator, and the helper's strict reader reads it as the same: checked by parsing both with the workbench kit's `jsonstrict.parse_object`, and a test of the helper group shows the engine receives the same locator), that no apostrophe may be left between the quotes, that this is the only change allowed to a locator, and that an agent that cannot be sure of a locator does not run the read and marks the book unread. (2) The rule for `status` was wrong: `found_by_text` is also a passage that was read (its reply carries a new locator and `next` that replace the old), and `unknown_kind` is unread as `not_found` is. (3) The query limits of the engine (at most 20 words, each of at most 100 characters) were not said. (4) The `version_id` of the result is to be passed as `--version`.
- **Second exchange: no blocking finding, two wording points applied:** the escape rule covers every locator an agent passes (a `next`, and the replacement locator of a `found_by_text` reply, which can carry headings), and the locator is kept on one line. The reviewer found that inside single quotes of a POSIX shell only the apostrophe is special, that headings are cleaned of newlines and control characters by the engine, and that a locator longer than 2,000 characters or deeper than 6 levels is refused by the helper (which step 6 covers).
- Recorded as a todo item of the owner: `pose-a-problem` and `walk-from-themes` (step 6 of each) have the same gap and say to keep the locator exactly as given; it is outside this plan and a safety rule, so it is its own small plan.
- Could not be checked by the reviewer: any run result; the workbench kit's strict JSON reader (outside the repository), which I checked myself; how the command gate treats a quoted argument that holds a backslash.

## Deferred work

- Changing step 6 of `pose-a-problem` and `walk-from-themes` to point at `find-a-passage`, so that the rule is held in one place (a change of both skills and of their tests, and of what an agent with one skill loaded does).
- Skills for running the library: the status of the loop, a hand run with the stop file, a change of the engine that does not void the crawl's approval, the command forms of the gate.
- The agent for the library, after the skills have had use.

## Result

**Increment A** (built in `main` directly, since no code of `engine/kb` changes and so the approval of the crawl is not touched).

- Done: the new skill `package/kb/harness/neutral/skills/find-a-passage/SKILL.md` (when to search by words and when by meaning; the plain words and the characters to leave out, with the limits of the helper and of the engine; the search call with the double dash and single quotes; what a result carries; the pick of the result of the book meant; the read call with the locator exactly as given except for the escape of its apostrophes; the `status` rule; following `next`; quoting the passage as the book's own words with its citation; unread; the refusal), and the class `FindPassageSkillTests` (12 tests) in `engine/tests/test_package.py`, with one test in the helper group (`HelperCase`) that a locator whose apostrophe is written as the JSON escape reaches the engine as the same locator.
- `docs/specs/knowledge-base.md` lists no skills (line 60 names them in general), so the sentence the plan allowed there was left out.
- Tests were written first and seen failing (the skill did not exist: FileNotFoundError), and again for each point of the review (3 failures after the first exchange, 1 after the second), then passing.
- Verification (Python 3.15.0): `python3 -B -m unittest engine.tests.test_package`, 124 tests, OK, 78 skipped (they need a workbench checkout); with `KB_WORKBENCH_CHECKOUT` naming the workbench checkout, 124 tests, OK, none skipped, which includes the helper test of the escape; `wb run code-work check`, 78 plans, no problems; `git diff --check`, clean.
- Breaks: 45 single changes to the text of the skill (each rule removed or inverted), each caught by a test, the file restored byte for byte. In the first run 3 breaks were not caught, because the same words appear elsewhere in the skill (the heading of step 5, the single quotes of the read call, a key named again in step 5); the tests were tightened to the exact sentence and section. Later, one break of the new locator rule was not caught (the rule to run no read when unsure) and a phrase was added.
- A slip of mine, caught by the new test: the edit tool turned the JSON escape I wrote into a literal apostrophe, so for a moment the skill told the agent to write an apostrophe as an apostrophe; the escape was written again through a script that keeps the backslash, and the test holds the escape.
- Departures from the plan: the skill states the engine's limit of words (not in the plan's criterion 1); the rule for the apostrophes of a locator (the plan said only that the locator is given exactly as a result gave it); both from the review.
