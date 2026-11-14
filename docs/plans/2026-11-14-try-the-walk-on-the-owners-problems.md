# Try the walk on the owner's problems

Status: In Progress
Created: 2026-11-14
Candidate: theme-weave#extrapolation-trial
Specs: docs/specs/theme-walk.md

## Goal

The owner knows whether the themes that `theme-walk` offers at a wide setting differ from what an ordinary search of the same questions returns, and whether the difference is worth following. When the plan is done:

1. Five problems (the owner's questions of 2026-11-14: card-game search with learning, simulated annealing with modern AI, minimax with a learning algorithm; and, added by the owner, improving the 3D print quality of CAD models with organic shapes and large open voids, and
   optimizing large matrix multiplication across several cores for AI networks on small slow hardware) have been run through the walk at every level and every distance, and a table gives, for each,
   **the share of offered leads that an ordinary search of the agent's own questions would already have returned** (the roadmap's finish line for this candidate).
2. An agent has used the walk for several rounds on each problem as the skill `walk-from-themes` says, passing back `--seen`, `--from` and `--drop`, and what it followed and why is written down.
3. The owner has read, blind, a mixed sheet of 40 themes (from the walk's two lanes, from the next page of the ordinary search and from the library at random) and marked which they would follow; the Result gives the counts and reads them against a rule written
   before any call.

The share alone cannot answer the owner's question. In the owner's own run (`2026-11-13-let-an-agent-walk-from-themes-along-the-links`, Increment E) all 12 leads at `wide` were outside the ordinary set for each question: the walk offers the leads that are outside the ordinary set first, so a
low share is partly its ordering, and any random theme would also be "different". That is why the plan adds the owner's blind reading, with two comparators, and reports the share as a count and not as a finding.

## Scope

- The five problems (the owner's own words, below) and the questions in general terms that the agent writes for them, fixed and hashed before any call, with the reading rule below.
- One script outside the repository (as Increment E's `run_walk_e.py` was) that runs the calls, tallies the shares, draws the sheet and unseals its key; held outside the repository and cited by hash.
- The sweep: each problem at six settings (narrow with 1 step; medium with 1 and 2; wide with 1, 2 and 3), 30 calls, limit 20, and the ordinary search's first 50 themes for each problem.
- The rounds: for each problem, up to three calls at the wide default, chosen by the agent following the skill (at most 15 calls).
- The blind sheet of 40 themes, the owner's marks, and the written result with the reading.

## Non-goals

- Any change of the walk, its levels or numbers (0.66, the lanes, 5 and 30, the caps), of the weave, the vectors, the skill or the helper. The trial reports; a change that the result suggests is a recommendation and a plan of its own. (The spec says the trial "tunes" the numbers; this plan does not tune them.)
- Any machine measure of novelty, and any judging of pairs or themes by a model.
- Building what the result suggests (down-ranking generic themes, a links-per-theme count, a tracked trial command).
- Problems from other fields or a larger library; the library is as it is (the owner decided on 2026-11-14 to keep to the roadmap).

## Assumptions and constraints

- **The agent is this session's agent standing in for a research agent** (`theme-walk.md`, criterion 11). It is not blind: it built the walk and has seen the library's titles in earlier runs. The questions are therefore written once, shown to the owner and fixed before any call,
  and the agent's rounds are recorded with its reasons so that the owner can see where its knowledge decided a choice.
- **The problems are the owner's own questions of 2026-11-14,** in the owner's words: (1) how to apply AI to computer players of nondeterministic card games that would normally use a Monte Carlo search tree; (2) how to improve on traditional simulated annealing with modern AI
  techniques; (3) how to optimize a minimax search with a learning algorithm; (4) "how can I automatically improve the 3d print quality of cad models that contain organic shapes with large open voids"; (5) "How can I optimize large matrix multiplication across multiple cores to improve ai
  network performance on smaller slow hardware". Increment E ran the first three once at three levels (9 calls). Problems 1 to 3 come from one neighbourhood of the library (search, games, optimisation, learning); 4 and 5 were added so that the walk also starts from CAD and 3D printing and from
  numerical computing on hardware. Five problems are more than the spec's "two or three" (criterion 11); the owner chose them, and the spec paragraph of Increment E says so. Problem 5 may draw generic themes, which Increment E saw for other questions; the result says what it sees.
- **Sends.** Every call of the walk, and the ordinary search, sends the agent's questions (at most three for a problem, each short) to `qwen3-embedding:4b` on the server `ned`: on the owner's network, over plain unauthenticated HTTP, in the clear, and not on this machine
  (`wb run ask-ollama check` says so). At most 150 sentences in all: the sweep 30 calls × at most 3 questions, and 5 ordinary searches × at most 3 questions (105), then at most 15 calls of rounds × at most 3 questions (45). Nothing else is sent. The owner is told before each of Increments B and C
  and says "run it". The owner allowed the walk to send an agent's questions on 2026-11-14 ("Yes, allow it"); that is for an agent in another project, and this plan asks again before each send.
- The walk is read only: it writes no file and keeps no state. The weave and the file of theme vectors are hashed before and after each run, as in Increment E (weave `ebbba8f4…8fe3`, vectors `59fe6474…9229` at the last run).
- The ordinary set is the walk's own: the first 30 themes of the merge of the questions by best rank, two themes at most from one book. Its page is 50 (`search.MAX_LIMIT`), so the ordinary search can give ranks 31 to 50 and no more.
- **The sheet's sources** (each theme shown with the same fields: its title, its book's title, its summary and its four neutral parts; no score, no lane, no mark of stated or inferred, no route):
  - **S1**, the next page of an ordinary search: ranks 31 and 32 of the merge (the fair alternative at the same effort: asking the search for more).
  - **S2**, wide follow-through: the first two leads of the follow-through lane in the output of the wide call with 3 steps and limit 20.
  - **S3**, wide exploration: the first two leads of the exploration lane of the same call. A lane that holds fewer than two gives what it holds, and the Result says so.
  - **S4**, random: two themes drawn with a seed (the first eight hex characters of the sha256 of the questions file) from the themes of the library that are in neither the ordinary list (ranks 1 to 50) nor the walk's leads; the noise floor.
  - A theme drawn for S2 or S3 is never drawn for S1 (the next rank is taken) or S4. 2 themes × 4 sources × 5 problems = 40 themes (10 a source), shuffled by a seed, with the key (which theme is which source) written to a file, hashed before the owner marks anything and opened only after.
- **The marks:** for each theme the owner says *would follow*, *might follow* or *would not follow*, reading it as a lead for the problem. The owner's words are recorded as given. Forty themes is one sitting of reading; the owner may ask for more (3 a source and problem is 60) or fewer.
- The reviewer agent can read files outside the repository, and a review of the tallies would have it read theme texts of books of the owner's library (web pages and preprints, in a cloud model). The owner is told before a reviewer is given the raw outputs; without the owner's word the reviewer is given the script, the fixture and the printed tallies only.

## The reading, written before any call (a proposal; the owner may change it when approving the plan, and the numbers are guesses)

Counts are small (10 themes a source, 5 problems), so nothing is tested for significance: this is a look at one reader's marks, and the Result says so.

1. **Does the walk offer what an ordinary search would not?** For each problem, the share of the leads of the wide call (3 steps, limit 20) that are among the first 30 themes of the ordinary set, by theme and by book. **Differs** if at most 25 percent for every problem; **mostly the same** if 60 percent or more for any;
   **mixed** otherwise. The same share is reported for each of the six settings, and with it the number of themes the call reached and the size of the ordinary set (the header's own numbers), so that the effect of the walk's ordering (leads outside the ordinary set first) can be read.
2. **Is the difference worth following?** The owner's rate of *would follow* among the 20 themes of S2 and S3, against S1 (10) and S4 (10).
   **Wide adds** if S2 and S3 together reach 25 percent *would follow* or more, at least twice the rate of S4, and a rate not lower than S1's. **Wide differs, and paging the ordinary search does as well** if the first two hold and S1's rate is higher. **Noise** if the rate of S2 and S3 is less than
   twice that of S4. Anything else is **unclear**, and the Result says what would settle it.
3. **Descriptive, no rule:** the rates of S2 against S3 (whether the follow-through lane does better than the exploration lane, which is a first look at the 0.66 threshold), the *might follow* counts, which problems the marks come from, and which themes the agent followed in its rounds that the owner marks would not follow.

## Completion criteria

1. The questions, the script and the reading rule are fixed and hashed, and the owner has read the questions, before any call is made.
2. The sweep ran: 30 calls and 5 ordinary searches, each exiting normally, with the table of shares for the six settings and five problems, the header counts, and the weave and the file of vectors shown unchanged.
3. The rounds are recorded for each problem: the calls, the leads followed, `--seen`, `--from` and `--drop` passed back, the reason for each, and how many leads were new to the agent.
4. The sheet of 40 themes was made by the rules above, its key was hashed before the owner marked it, and the owner's marks are recorded as given.
5. The Result gives the counts, the reading against the rule, what cannot be concluded, a recommendation and the owner's decision; no number, code, weave or skill is changed.
6. `wb run code-work check` finds no problems.

## Increments

### Increment A — The questions, the script and the rule, fixed before any call

**Outcome:** the questions for the five problems, the script and the reading rule are fixed and hashed, the script gives the right answers on a hand-made case, and the owner has read the questions. Nothing is sent.
**Dependencies:** none.
**Affected areas:** this plan's Result; files outside the repository (the questions, the script).
**Steps:**
1. Write the questions in general terms for each problem as step 1 of the skill `walk-from-themes` says (one to three, each one idea, no name of a field, a product or a person), as a file outside the repository; record its sha256.
2. Write the script outside the repository: it runs `python3 -m kb theme-walk` and `theme-search` as Increment E's script did, with the options of the sweep; reads the weave and the vectors hashes before and after; tallies the shares by theme and by book from the walk's `novelty` fields; draws the sheet by the rules above with the seed; writes the key; and tallies the marks.
   Nothing in it sends text except the questions of the file.
3. Test it on a hand-made output of three problems, each with a known share and a known sheet, without any send; then deliberate breaks, each caught: the boundary (rank 31 counted as in the ordinary set); the share taken over all reached themes instead of the offered leads; the share by book taken by theme; an S1 theme that
   is also an S2 theme kept; the random draw unseeded; a source label left on a sheet item; the key written after the marks. Record its sha256.
4. Show the owner the questions (and the reading rule above), and record what the owner says. The `reviewer` agent reads the script, the fixture and the plan, and not the library.
**Verification:** the script on its fixture gives the hand-worked numbers, the breaks of step 3 are each caught, and `wb run code-work check`. No call to any model.
**Evidence:** the one local commit (the plan's Result with the hashes), with the trailer `Plan: 2026-11-14-try-the-walk-on-the-owners-problems#A`.

### Increment B — The sweep and the ordinary lists

**Outcome:** the walk has been run for each problem at each of the six settings and the first 50 themes of the ordinary search have been taken, and the table of shares exists.
**Dependencies:** A, and the owner's word ("run it") after being told what is sent (the questions of the fixed file, to `ned` in the clear: at most 105 sentences in this increment).
**Affected areas:** this plan's Result; raw outputs outside the repository (mode 600, hashed).
**Steps:**
1. Say what is sent and to which server, show the hashes of the weave and of the vectors, and wait for the owner's word.
2. Run the script: 30 calls (5 problems × narrow/1, medium/1, medium/2, wide/1, wide/2, wide/3, limit 20) and 5 ordinary searches of the problem's questions with the limit of 50, one at a time. Record each call's time and exit status; a call that fails stops the run and is reported (it is not repeated in a loop).
3. Cross-check that the ordinary lists are the walk's: every lead of every call that carries an `ordinary_rank` is at that rank in the first 30 of the list the script built, and no lead without one is among them.
4. Hash the weave and the vectors again, and list the index root before and after.
5. Write the tables into the Result: for each problem and setting, the leads offered, the share in the ordinary set by theme and by book, the themes reached, the size of the ordinary set, and the lanes' counts.
6. The `reviewer` agent, with the owner's word before it reads raw outputs (see the assumptions).
**Verification:** the cross-check of step 3, the hashes and the listing of step 4, the table recomputed once by hand for one problem and one setting, and `wb run code-work check`. No test of the engine is run: nothing tracked changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-try-the-walk-on-the-owners-problems#B`.

### Increment C — The agent's rounds

**Outcome:** for each problem the agent has walked for up to three calls at the wide default as the skill says, and what it followed and why is written down.
**Dependencies:** B, and the owner's word ("run it") after being told what is sent (at most 45 sentences).
**Affected areas:** this plan's Result; raw outputs outside the repository.
**Steps:**
1. For each problem, call the wide default with the problem's questions; read the leads as data; choose the ones to follow, each with a reason made from its text; pass back `--seen` (every lead read and the themes of its route), `--from` (the chosen) and `--drop` (a dead end), as the skill says; call again, at most three calls for the problem.
   Nothing is followed on a hunch about the library that the lead's own text does not support, and a choice that rests on the agent's own knowledge of the library is marked as such.
2. Write the rounds into the Result: per call, the leads offered, which were new to the agent (not in the ordinary set of its questions and not seen before), which it followed and why, and what it dropped.
3. Hash the weave and the vectors again, and list the index root again.
**Verification:** the hashes and the listing of step 3, the counts of "new to the agent" recomputed by script and by hand for one call, and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-try-the-walk-on-the-owners-problems#C`.

### Increment D — The blind sheet and the owner's marks

**Outcome:** the owner has marked the 40 themes of the sheet without knowing their sources, and the marks are recorded as given.
**Dependencies:** B (the sheet draws from the sweep; C is not needed). Nothing is sent.
**Affected areas:** this plan's Result; the sheet and its key outside the repository.
**Steps:**
1. Run the script to draw the sheet by the rules above; hash the key file and write the hash into the Result before the sheet is shown.
2. Show the owner the sheet (40 themes, shuffled, each with its title, its book and its four neutral parts, and nothing else). The owner marks each *would follow*, *might follow* or *would not follow*, and may say more in words; the agent records each answer as the owner gave it and rewords none.
3. Only then open the key and tally the marks per source, per lane and per problem.
**Verification:** the key's hash taken before the marking equals its hash at the opening; the sheet holds 40 distinct themes and no theme in two sources; the tally is recomputed by hand for one source; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-try-the-walk-on-the-owners-problems#D`.

### Increment E — The written result and the owner's decision

**Outcome:** the Result holds the counts, the reading against the rule, what cannot be concluded, a recommendation and the owner's decision, and the spec records that its criterion 11 was run.
**Dependencies:** B, C and D.
**Affected areas:** this plan's Result; `docs/specs/theme-walk.md` (the "Built" section: the trial was run, with the result and its limits; the numbers, the status and the open questions are not changed).
**Steps:**
1. Write the Result: the share table of B, the rounds of C, the marks of D by source, the reading of each of the three questions above, and what cannot be concluded (five problems, three of them from one neighbourhood, one reader, one stand-in agent that is not blind, small counts, the effect of the walk's ordering on the share, the 0.66 and the lane shares untuned).
2. Give the owner a recommendation that follows the reading, and write the owner's decision. A change of the walk's numbers, a count of links per theme or a down-ranking of generic themes is named as a possible plan and is not made; adding it to a roadmap is the owner's (`change-direction`).
3. Record the evidence in `docs/specs/theme-walk.md` under "Built" in a short paragraph that cites the plan and the hashes, and says that five problems were used where criterion 11 says two or three (the owner chose them); the criterion's own wording is left as it is.
4. The `reviewer` agent reads the Result and the spec paragraph against the recorded tallies.
**Verification:** each number of the Result equals the recorded tally (checked by the reviewer and once more by hand for the share of one problem); `wb run code-work check`. No code is changed.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-try-the-walk-on-the-owners-problems#E`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs; the raw outputs and the script are not changed after B, C and D, so their hashes are checked once at the end. Nothing tracked but this plan and one paragraph of `docs/specs/theme-walk.md` changes, so no test of the engine, the helper or the skills is rerun;
the last run of those (235 tests, then 105 of the package) was at commits that precede this plan. What could break outside the tested area: nothing in the repository reads this plan or that paragraph except the check of documents, which Increment E runs. The weave and the vectors are checked unchanged after every run.

## Risks and sensitive actions

- **Sentences go out in the clear.** At most 150 short questions go to the embedding model on `ned` over plain unauthenticated HTTP. They are the owner's own problems in general terms; the owner is told before each send and says "run it".
- **The stand-in agent is not blind, and the library's variety is limited.** Three problems share a neighbourhood and two reach into CAD and hardware computing, but five problems are still a small look. The result can show only what this agent, this reader and this part of the library show. The Result says so and draws no conclusion for other fields.
- **The share is shaped by the walk's ordering,** which puts leads outside the ordinary set first, and a random theme is also "different". The plan reports the share as a count with the header's numbers beside it, and puts the weight on the owner's blind marks with a random comparator.
- **One reader and 10 themes a source:** nothing is tested for significance, and a close result is read as unclear.
- **The script is not tracked.** It is cited by hash, as Increment E's was; a fixture and breaks show it computes what the plan says before any real call. A tracked trial command is deferred.
- **A reviewer reading raw outputs reads texts of books of the owner's library** (web pages and preprints) in a cloud model; the owner is asked first.
- **A security review is not asked for.** The plan adds no input, no boundary and no permission: it uses the walk's existing read-only command and the send path the owner allowed on 2026-11-14. The owner may ask for one.
- No push and no change of the library, the weave, the vectors, the skills or the helper.

## Review record

### Increment A

The `reviewer` agent (read only; it read the plan, the four files outside the repository, `engine/kb/walk.py`, `themevectors.py` and `__main__.py`), round 1 of 3. **No blocking finding.** It found no concrete security risk. It could not run the tests, the breaks or `--check`, and could not check the hashes
(they are checked in the Result). It found six things, all not blocking:

- **1, applied.** The sheet's seed was the whole 64-character hash of the questions file; the plan says its first eight hex characters. The script now uses the first eight (`build_sheet`), with a test that pins it and a break.
- **2, applied.** `call` asked for 20 leads by default, the sweep's number; a round is "at the wide default" and the walk's default is 12. `ROUND_LIMIT` is 12, tested against `walk.DEFAULT_LIMIT`, and a break.
- **3, applied (the most useful one).** `sweep` and `call` wrote their report only after all the sends, with an exclusive create: a path that already existed lost a finished report after 105 sentences had been sent. Both now refuse, before any send, a path (or its `.partial`) that exists or whose folder does not
  (`ensure_free`); tested with the configuration, the search and the walk replaced by fakes that fail if used, and three breaks. The same check is in `sheet`, which is not tested offline because it reads the library.
- **4, applied in part.** Added: a mocked run of `sweep` that counts every sentence it would send (105, the number `--check` prints, from 15 searches and 30 calls), a failed call that stops the run and writes a `.partial` report, a walk that disagrees with the merge that stops it, a round's arguments and report,
  `PAGE`, `ORDINARY` and `ROUND_LIMIT` against the walk's own constants, and `build_sheet` with the narrow call first (so taking the first call as the wide one, or taking the leads from the wide call only, is caught). **Not applied:** the plan's break "the key written after the marks" has no break of that
  name; the script enforces the order by a hash check in `tally_marks` (the key is hashed and written with the sheet, and the marks are refused against any other hash), and the break of that check is the corresponding one. `make_sheet` itself (it reads the library) and `main` for `sheet` and `marks`
  have no offline test; Increment D runs them first on the real sheet with the owner's word.
- **5, rejected.** `snapshot` hashes every file at the top of the index root and not only the weave and the vectors. It is read only, it is what Increment E did ("every other file of the index root also unchanged"), and it shows more than the plan asks. Recorded here.
- **6, applied.** `sheet` now prints the count of each source and warns when the sheet holds fewer than 40 items. A marks file that does not name every item is still refused: if the owner asks for fewer items, the sheet is drawn again with fewer.

The fixes were not sent for a second round: they are small, and each has a test and a break. Reviewer exchanges used: 1 of 6.

## Deferred work

- A count of links per theme in the weave, to test the guess that a few generic themes turn up for unrelated questions, and a down-ranking of such themes if the count supports it: not on any roadmap (the owner's decision, `change-direction`).
- A tracked command that runs a trial of the walk, if the owner wants the trial repeatable after books are added.
- The same trial on problems from other fields, with a second reader, and with a blind stand-in agent that is given only the skill and a problem.
- Tuning the levels and the 0.66 threshold, if the result supports it: a plan of its own.
- Judged labels of links (the weave spec's open question) wait until the owner has read the walk's output on this trial.

## Result

### Increment A (the questions, the script and the rule, fixed before any call; committed on the owner's word)

- **Done.** Nothing was sent, and no file of the library was read. Four files outside the repository, in `~/.local/share/knowledge-base/trial/walk-trial/` (mode 600; untracked, so cited by hash):

  | file | sha256 |
  |---|---|
  | `walk-trial-questions.json` | `ee84c13c24d071222e27c84251195e1ffe3931aa5532771eae9231886f860a76` |
  | `trial_walk.py` | `12d8cba2cc6f6a80eb107b9a121d84c3161ec05eafd825533f516e3f1d782061` |
  | `test_trial_walk.py` | `5c2d3d063ad8f68d2afe1e9c10f5529a3d6da08ecd680c40df10c2210bfef796` |
  | `breaks_trial.py` | `330f1c0d88101f0b051a48dc85ccbb042e39fe9e96a10e5547a10a13ae218377` |

- **The questions.** Three for each of the five problems (15 in all, so one pass sends 15 sentences and the sweep 7 passes, 105), in general terms: no field, product or person, no apostrophe or quotation mark, plain words only (letters, digits, spaces and `, . ? -`). The owner's own words are kept in the file for the reader and are never sent.
  The agent that wrote them (this session's) is not blind, as the plan says.
- **The script** (`trial_walk.py`, 22,897 bytes). Pure parts: reading the questions, the arguments of a walk call, the merge that makes the ordinary set, the shares and a cross-check against the walk's flags, the sheet draw, the key, the tally of the marks. Parts that send (`sweep`, `call`) or read the library
  (`sheet`) are separate, and `sweep --check` prints what would be sent and sends nothing.
- **Readings made where the approved plan was silent** (the plan is not changed): (1) the ordinary set is the first 30 *places* of the merge of the questions' pages by `(best rank, question, key)`, not "rank at most 30" (two questions can each give a rank of 1); S1 is places 31 and 32; the walk's own `ordinary_rank` is its best
  rank, so the cross-check of Increment B compares a lead's `(ordinary_rank, key)` with the script's merge, and not a position. (2) S4 leaves out every theme on any page of the problem's questions (up to 150) and every lead of its six calls, and a theme drawn for an earlier problem or an earlier source is passed over for the next
  in line, so that the sheet holds 40 distinct themes. (3) Each problem has its own seed, `<first eight hex characters of the hash of the questions file>:<problem>`; the order of the sheet is a hash order. (4) Every item of the sheet is rendered from the library's row in one way (title, book, summary and the four parts, each cut at 600
  characters, no mark, no score, no lane, no route) and never from the walk's own text, which is cut at 140 characters and carries marks and would show which source an item came from. (5) "The key written after the marks" is enforced by the hash check in `tally_marks`, not by a separate break.
- **Tests, and what was not seen first.** `test_trial_walk.py`: **38 tests, OK** (`python -W error::ResourceWarning -m unittest test_trial_walk` from the folder, with the engine's venv python). They start no process and send nothing, replace the configuration, the search and the walk by fakes in the one mocked run of `sweep`, and
  compare the script's merge with `kb.walk.starting_themes` on three pages with tied ranks. **I wrote the script before its tests**, so the tests were not seen to fail first; the breaks are the evidence that they can fail.
- **Deliberate breaks:** `breaks_trial.py`, **51**, each editing the script, running the tests and restoring the file, **all caught**. One was missed in the first run (the random draw not leaving out the pages of the questions: a pool large enough hid it), a test was added; and after the review two breaks were corrected (one anchor that no longer applied, one that stopped the run by accident).
  The script was restored byte for byte after every run (hash `12d8cba2…782061`, as above). They include the boundary (place 31 counted in), rank confused with place (twice), the merge's tie-break and the worse place, the share over the themes reached and over the book, a theme drawn twice, an unseeded draw, a source label or a mark on the sheet, an S2 or S3 item
  rendered from the walk's text, the key not checked, a report that overwrites or is readable by others, and `--check` going on to send.
- **`--check` on the real questions:** "would send 105 sentences (15 questions, in 7 passes: 6 walk calls and one ordinary page each) and write nothing". The mocked sweep sends exactly 105 (15 searches and 30 walk calls of 3 questions each) and checks the report paths first.
- **Review:** the `reviewer` agent, one round, no blocking finding; see the Review record. `wb run code-work check` was run on the plan before approval; it is run again before the commit.
- **Step 4, the owner's reading of the questions (2026-11-14):** the owner said "Questions are good." and, in the same message, "Commi[t] a, start b". The questions stand unchanged (sha256 `ee84c13c…1a76`). Increment B's send still waits for the owner's "run it" after the exact send is shown.
- **Not run:** any send, any read of the library, `sheet` and `marks` on real data, the install of anything. No push.
