# Let an agent walk from themes along the links

Status: Proposed
Created: 2026-11-13
Candidate: theme-weave#theme-walk
Specs: docs/specs/theme-walk.md, docs/specs/weave.md

## Goal

A research agent can ask the library for themes it did not ask for. One command, `python3 -m kb theme-walk`, takes the agent's question (or several), finds the themes an ordinary search would return, follows the
links of the weave of same mechanism from the best of them on a short narrow-to-wide scale, and offers leads in two lanes (follow-through and exploration), each with its route, its reason and whether an ordinary
search of the same question would also have returned it. The agent iterates by passing back what it has seen, what it follows and what it drops; the command keeps no state. When the plan is done the walk exists
as the spec `docs/specs/theme-walk.md` says, a skill tells an agent how to use it, and the owner has read its output on the real library at each level. The agent trial, which measures the share of offered leads that
an ordinary search already returned at each level and step distance, is the roadmap's separate candidate `theme-weave#extrapolation-trial` and gets a plan of its own once this one is done.

## Scope

- A new module `engine/kb/walk.py` with the selection (routes, levels, the best route of a theme, the two lanes, the limits, `--seen`, `--drop`, `reached_by`) as pure functions of the weave's links, the starting
  themes, the ordinary set and a visible set; and the glue that gets the starting themes and the ordinary set from the search by meaning (`themevectors.search`) and shapes the output.
- The command `python3 -m kb theme-walk` in `engine/kb/__main__.py`, its output (one JSON object, text between the untrusted-text markers, bounded), its refusals, and its entry in `engine/README.md` and `README.md`.
- A skill that tells an agent how to use the walk, in the package beside `pose-a-problem` (`package/kb/harness/neutral/skills/`), declared the way that one is, with the package test.
- A read-only smoke check on the owner's real library, with the owner reading the output at each level (Increment E).
- A "Built" line in the spec that records what is built. The spec's status and the tuning of its open questions are not changed here: they are the owner's, decided after the trial of the separate candidate.

## Non-goals

- Judging whether a lead is novel or useful; the agent decides (the owner, `docs/specs/weave.md`).
- Any state kept between calls, any file written, any call to a model other than the embedding of the questions.
- The other kinds of weave, a judge's label on a link, and the building of combinations from leads (all named in the spec's non-goals).
- Guests, tokens and shelves (`shelf.md`): the engine has none. The selection takes a visible set as an input so that they can be added; the plan builds none of them.
- Changing the weave, the search, the cleaning of text or the markers.
- The agent trial, its written result and the share of offered leads an ordinary search already returned at each level and distance: the roadmap's candidate `extrapolation-trial` (dependency: this plan), planned
  separately.

## Assumptions and constraints

- The weave of same mechanism exists over the owner's library (generation 1, 1,805 themes, 7,966 links) and `theme-links status` says nothing is due; the walk reads it as `weave.read` does and refuses one that is
  missing or not the engine's. (`docs/specs/weave.md`; Result of `2026-11-13-link-themes-that-work-the-same-way`.)
- The search by meaning (`themevectors.search`) exists with a per-book limit, a reply that says which model answered, and a refusal for a file made for another model, dimension or prefix. The walk uses it as it is
  and does not change it.
- The design decisions are the drafter's calls recorded in `docs/specs/theme-walk.md` (reviewed by Codex for two rounds, six findings applied); the owner said the design was better and asked for the plan. The numbers
  (levels, the threshold 0.66, the lane shares, 5 starting themes, an ordinary set of 30, the caps) are guesses to tune on the trial.
- Tests that import the weave run with `engine/.venv/bin/python`; the walk itself needs no numpy, and its tests also run with plain `python3` unless they read a weave file (which needs no numpy either, `read` being
  lazy about it).
- Any call that sends a question to a model (the embedding of the question, on the owner's machine) happens only with the owner's word and after being told what is sent. The tests use a stand-in for the search.
- Nothing tracked points to anything untracked: the trial's report is kept outside the repository and cited by its sha256.

## Completion criteria

1. The selection returns, for a question's starting themes, leads each with a route of at most the level's steps over links of the weave, every theme of a route of a different book from its predecessor, no route
   visiting a theme twice, and no lead a starting, `--seen` or `--drop` theme; `narrow`, `medium` and `wide` bound the steps and the links followed as the spec's table says, and `--steps` never exceeds the level's.
2. The leads are in two lanes by the closeness of the weakest link of the route (threshold 0.66), each lane with its share of the limit, never blended; within a lane the leads not in the ordinary set come first;
   at most two leads from a book and three from a starting theme in a lane; one lead per theme with its best route (the highest weakest link, then the fewest steps, then the smallest REF sequence).
3. The same arguments, weave, vectors and embedding configuration give the same output in the same order; the command writes nothing and keeps no state; a file of vectors or a reply from another model is refused
   before any lead is made.
4. `--from`, `--seen` and `--drop` work as the spec's criterion 4 says; a REF is validated as an identifier only and an unknown one is counted and ignored.
5. Every lead carries the ordinary-search flag with its rank and the book flag; the header says what was skipped, held back and why, what widening would add, and says so when little or nothing is found.
6. The selection and every count are computed over a visible set given as an input, and a test with hidden themes shows no route, lead, count, flag or rank depends on one.
7. Every text of a book or a card in the output is cleaned and withheld whole if it holds the words of an untrusted-text marker, and a hostile title, text, question or REF does not change the structure of the output;
   every lead carries the `stated` or `inferred` mark of each neutral field it shows and the theme's citation (as a search result carries them), taken from the file and never from text;
   the output is bounded (at most 20 leads, about 1,500 bytes a lead, about 40 KB); `--limit` is 1 to 20.
8. A skill in the package tells an agent how to use the walk (the loop of ask, read, follow, drop, ask again; the two lanes; what the flags mean; that a lead is a lead and not a finding), and the package test passes.
9. On the owner's real library the command has been run read only for the owner's questions, the weave and the file of vectors are unchanged by it (their sha256), and the owner has read the output at each level
   (a smoke check; the trial that measures the share an ordinary search already returned is the separate candidate).

## Increments

Five increments, each one verified, reviewed local commit; the agent trial is not one of them.

### Increment A — The selection, as pure functions

**Outcome:** `engine/kb/walk.py` holds the selection of the spec, over plain data, with no search, no file and no model: it is tested by hand and against a slow reference.
**Dependencies:** none (the weave exists and `weave.read` gives its rows).
**Affected areas:** `engine/kb/walk.py` (new), `engine/tests/test_walk.py` (new).
**Steps:**
1. Write the tests first and see them fail. Hand-built graphs of a few themes with known links, closeness and bands: the levels (`narrow` follows only bands 2 and 3 for one step; `medium` two steps; `wide` three, taking
   the farthest bands first at the later steps, at most 12, 3 and 2 links of a theme as the table says); a route never visits a theme twice and never returns to a `--from` theme; a link to the same book is never
   met (the weave has none, and the test builds one to show the walk does not rely on it); the best route of a theme (highest weakest link, fewest steps, smallest REF sequence, with ties made on purpose and the
   routes given in every order); the two lanes by the threshold (a link exactly at 0.66 is in the follow-through lane), their shares of the limit (two thirds rounded up), a short lane giving its places to the other,
   leads not in the ordinary set first, at most two from a book and three from a starting theme, the held-back counts by reason; `--seen` themes never offered and not walked through unless in `--from`; `--drop`
   removing a theme and what is reached only through it; `reached_by` counting the different routes (by hand on a diamond and on a graph with two and with three routes); the visible set (a hidden theme and a
   link to it change nothing visible: the same output as a graph without them); a start with no links, and everything reached known, give the reasons the header needs; the same input in any order gives the same
   output.
2. Write the reference: a plain, slow enumeration of every simple route of the level's length (`reference_walk` in the tests) that shares none of the code's structure, and a test that the code and the reference
   give the same leads, lanes and counts on a few hundred random graphs (themes of several books, links in four bands, seeded).
3. Write the least code that passes.
4. Deliberate breaks, each restored byte for byte and each caught: the level bounds off by one step; a route that revisits a theme; the lane threshold with `>` for `>=`; the lanes blended; a lane's places not given
   to the other; the order within a lane not putting the ordinary-set themes last; no book cap or no starting-theme cap; the best route taken by the strongest link and not the weakest, or the longest; no final tie-break;
   `--seen` themes walked through; `--drop` not removing what is reached only through it; `reached_by` counted by the first route only; a count or a lead computed over all themes and not the visible set.
5. The `reviewer` agent, for a second look.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_walk` and the breaks of step 4. No wider run: nothing else imports `walk.py` yet.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-let-an-agent-walk-from-themes-along-the-links#A`.

### Increment B — The starting themes and the ordinary set

**Outcome:** the glue that, for the agent's questions, gets from the search by meaning the starting themes (the first 5 that have a link, per question), the ordinary set (the first 30 results of all the questions) and
the book flag, over a visible set, and reports the embedding model, the use of a query prefix and the build time of the vectors.
**Dependencies:** A.
**Affected areas:** `engine/kb/walk.py`, `engine/tests/test_walk.py`.
**Steps:**
1. Write the tests first and see them fail, with a stand-in for `themevectors.search` that returns results of the shape the real one returns (a ranked page, `held_back`, the model, the prefix, `built`): the starting
   themes are the first 5 results with at least one link in the weave, skipping those with none and saying how many were skipped; several questions merge their results by the best rank and the ordinary set is
   the first 30 of the merge; a question that finds nothing is reported as finding nothing and the others go on; the book flag is true when any theme of the book is in the ordinary set; the per-book limit of the
   search is used and not overridden; a theme outside the visible set is dropped from the search results before the starting themes and the set are made; a search that refuses (a file for another model, a reply from
   another model) makes the walk refuse before any lead is made, with the search's message; the search is asked for at most the number of results the search allows and the walk says when fewer starting themes
   were found than wanted.
2. Write the least code that passes.
3. Deliberate breaks, each restored byte for byte and each caught: a starting theme with no link taken; the ordinary set taken from the starting themes and not the first 30 results; the merge by the first question
   and not the best rank; a hidden theme left in the ordinary set; a refusal of the search swallowed; the book flag taken from the starting themes only.
4. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_walk` and the breaks of step 3. No call to the real search: the stand-in is the search's shape, taken from its docstring and the tests of
`themevectors`, which are run once because the walk depends on that shape (`engine.tests.test_themevectors`).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-let-an-agent-walk-from-themes-along-the-links#B`.

### Increment C — The command and its output

**Outcome:** `python3 -m kb theme-walk --question "…" [--question …] [--from REF …] [--seen REF …] [--drop REF …] [--level …] [--steps N] [--limit M]` prints the one JSON object of the spec and refuses what the spec
says it refuses.
**Dependencies:** A and B.
**Affected areas:** `engine/kb/__main__.py`, `engine/kb/walk.py` (the shaping of a lead and of the header), `engine/tests/test_walk.py`, `engine/README.md`, `README.md`, `docs/specs/theme-walk.md` (the "Built" line).
**Steps:**
1. Write the tests first and see them fail, with a small weave file and a small file of vectors made as the tests of the weave make theirs, and a stand-in for the embedding: the output holds, for each lead, the
   fields of the spec (`ref`, the title, type and book title, the neutral `problem`, `method`, `needs` and `provides` each with its mark (`stated` or `inferred`) and the summary, the citation of the theme, the lane, the route with the closeness to two decimals and the band's
   name, `why`, `explain`, `novelty`, `reached_by`, `weak_link`) and a header with the fields of the spec; a mark is one of the two fixed words and is never text of a theme, a citation is the file's and equals the one
   a search result carries for the same theme; every text of a book is cleaned and between the markers; a text that holds the words of a marker is withheld whole; a
   hostile title, summary, method, question and REF (newlines, the words of the markers, a line that imitates a field, a very long text) do not change the structure; the size bounds hold with a theme of the
   largest allowed size; a REF that is not an identifier is refused, an unknown one is counted and ignored; `--limit` outside 1 to 20, `--steps` over the level's, an unknown level, no question, a question that is not
   text, are refused; more than 200 REFs are refused; a weave that is missing, not the engine's, or out of date is refused or said to be as `theme-links show` does; the command writes nothing (the weave and the
   file of vectors are unchanged by it, by sha256, and no file appears in the index root); the same arguments give the same bytes; the command line runs with numpy made unavailable.
2. Write the least code that passes.
3. Write the README text: the command and its options, what each field means, the two lanes, the loop for an agent, the limits, what it reads and that it writes nothing; and the "Built" line of the spec, which
   records only what is built (the spec stays a `Draft`, and its open questions stay the owner's).
4. Deliberate breaks, each restored byte for byte and each caught: a text not cleaned; a withheld text shown; a marker left out of the output; a REF used as a path; the limit not checked; the output not bounded; a
   file written; the size cap off; a field of a lead missing; a mark or a citation left out or taken from a text; the explanation pointing at the wrong link.
5. The `reviewer` agent. The security review is recommended to the owner before the walk is used on the real library, because the command takes an agent's text (questions and REFs) as input and shows text of
   books, a boundary like `theme-links show`; it runs only if the owner asks.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_walk engine.tests.test_themevectors`, the breaks of step 4 and `wb run code-work check`. No wider run: the search, the read, the cards and the
conversion are not touched.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-let-an-agent-walk-from-themes-along-the-links#C`.

### Increment D — The skill for an agent

**Outcome:** an agent that installs the package has a skill that says how to use the walk.
**Dependencies:** C.
**Affected areas:** `package/kb/harness/neutral/skills/` (a new skill, beside `pose-a-problem`), the module declaration of the package where that skill is declared, `engine/tests/test_package.py`.
**Steps:**
1. Read `pose-a-problem`'s skill, its declaration and its package test, and write the new skill the same way (name, description, steps); the test first (the skill is found, its front matter has the name and a
   description, it names the command and every option, it says that a lead is a lead and not a finding, and it holds no instruction that could be read as coming from a book).
2. The skill says: put the problem in general terms, and the sub-problems, as questions; read the follow-through lane first and sample the exploration lane; pass back what was read in `--seen`, what is worth
   following in `--from`, dead ends in `--drop`; read `novelty` and `reached_by` and the weak link as numbers and decide; widen with a level or a question when the header says little was found; stop when a round
   gives nothing new; never present a combination of leads as a finding.
3. Deliberate breaks of the package test (the skill missing, the option named wrongly, the front matter without a name), each caught.
4. The `reviewer` agent.
**Verification:** `engine/.venv/bin/python -m unittest engine.tests.test_package` and `wb run code-work check`. The install of the package into a throwaway project is not run (a preview of it is, if the test
for `pose-a-problem` did so; the Result says which).
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-13-let-an-agent-walk-from-themes-along-the-links#D`.

### Increment E — A read-only run on the owner's library

**Outcome:** the owner has read the walk's output on the real library for questions the owner chooses, at each level, and the weave and the file of vectors are shown unchanged.
**Dependencies:** C and D, and the owner's word ("run it") after being told what is sent: the owner's questions, to the embedding model of the config on this machine (a local model; nothing leaves it); nothing else.
**Affected areas:** nothing in the repository but this plan's Result.
**Steps:**
1. Say what will be sent and to which model, and the questions the owner gives; record the sha256 of the weave and of the file of vectors; wait for "run it".
2. Run the command for each question at `narrow`, `medium` and `wide`, with the defaults of the spec; show the owner the header and the leads of each, and the time.
3. Record the sha256 of the two files again and that no file appeared in the index root.
4. Write down what the owner says: whether `wide` offers leads that `narrow` and an ordinary search did not, whether the lanes help, what is noise, and what is missing. Any change to the spec's numbers that
   the owner asks for becomes a correction to the spec, with the owner's word.
**Verification:** the two hashes before and after, the listing of the index root before and after, and the outputs shown. No other check.
**Evidence:** the one local commit (the Result of this plan), with the trailer `Plan: 2026-11-13-let-an-agent-walk-from-themes-along-the-links#E`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. Increment C changes `engine/README.md` and `README.md`, which later increments do not touch; Increment D changes the package, and
its test is run after C. The tests of `themevectors` and of the weave are run in B and C because the walk depends on them; they are not run again unless a later increment changes `themevectors.py` or `weave.py`.
Increment E rests on A to D and is taken after all of them. Nothing wider is run: the cards, the conversion and the extractor are not touched.

## Risks and sensitive actions

- **The command takes an agent's text (questions and REFs) as input and shows text of books.** The questions go only to the local embedding model; the REF is an identifier and never a path; the text shown is
  cleaned, marked and withheld whole if it holds a marker's words, as `theme-links show` does. Increment C recommends a security review to the owner; it runs only if the owner asks.
- **The owner's questions in Increment E are sent to the embedding model of the config.** It is a local model on this machine; the owner is told before each run and says "run it".
- **The visible set is built for guests and tokens that the engine does not have.** If the spec's rule is wrong when they arrive, the walk's input is the only thing to change; the plan builds no part of them.
- **The numbers are guesses (levels, the 0.66 threshold, the lane shares, 5 and 30, the caps)** and rest on an exploratory cut of 30 themes. The trial of the separate candidate tunes them; the plan does not claim they are right.
- **The walk offers leads that may be noise.** The spec accepts noise if each lead is cheap to skim; the owner reads the output in Increment E, and the trial of the separate candidate reports the share an ordinary
  search already returned, with no machine measure of novelty.
- **A skill changes how an agent behaves** and is installed into other projects. It is written to say how to use the command and to carry no instruction from a book; its package test checks it.
- **No write to the owner's library and no push** in any increment but with the owner's word.

## Review record

- **Reviewer:** the Codex review engine (`wb run review-engine review-plan`; model `gpt-5.6-terra`), asked for by the owner on 2026-11-13. Only the plan file was sent, with what the reviewer read of the
  project from it. The spec it implements (`docs/specs/theme-walk.md`) was reviewed in two rounds before (model recorded `gpt-5.6-luna`; six findings, all applied).
- **Rounds:** 1 of a bound of 3. The owner chose to commit and approve after the fixes and not to ask for a second round.
- **Applied (3):**
  - R1-F1 (major): the agent trial is the roadmap's separate candidate `extrapolation-trial`, so the plan no longer holds it (Increment F is removed; it is in the deferred work as a plan of its own).
  - R1-F2 (major): every lead carries the `stated` or `inferred` mark of each neutral field and the theme's citation, taken from the file; the criteria, Increment C and the spec say so.
  - R1-F3 (minor): one transition point for the spec: Increment C records only what is built; the spec's status and open questions stay the owner's, decided after the trial.
- **Rejected:** none.
- **Not reviewed after the last change:** the text of the three fixes was not seen by a reviewer; the `reviewer` agent looks at every increment.
- **Left for the owner:** nothing from the review.

## Deferred work

- The other kinds of weave and a judge's label on a link, when the trial says they would add something.
- Guests, tokens and shelves, which the visible-set input prepares for.
- Whether `reached_by` should weigh in the order, a threshold learned from more than 30 themes, and a walk that follows several kinds of link.
- **The agent trial** (`theme-weave#extrapolation-trial`; trigger: this plan done and the owner asks for a plan): two or three problems the owner chooses, this session's agent running the walk over several rounds
  with the skill and passing back what it has seen, the written share of offered leads that an ordinary search already returned at each level and step distance, the counts of leads new to the agent and of leads
  the owner would have followed, and the spec's evidence item; the spec's status and open questions are decided there.
- A larger or second-rater trial, and a measure of novelty that is not a person's reading.

## Result

Empty until work starts.
