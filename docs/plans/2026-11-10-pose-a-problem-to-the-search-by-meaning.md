# Pose a problem to the search by meaning

Status: Proposed
Created: 2026-11-10
Candidate: cross-field-discovery#problem-search
Specs: docs/specs/knowledge-base.md, docs/specs/card.md

## Goal

An agent in a project can state a problem in general terms, split it into sub-problems, and get back, in one call, the books of the
library whose neutral descriptions are closest to each sub-problem, each with the neutral text that matched, its citation and the marks
that every result of the library carries. A skill tells the agent how to restate and split the problem, how to set aside the results
that come from the problem's own field, and how to give a reason for each book it keeps. When the plan is done an agent can do this from
a project through the `kb` helper, and the owner has seen it work once end to end.

## Scope

- An engine command, `python3 -m kb problem-search`, that takes one to five sub-problem sentences, runs the search by meaning
  (`vectors.search`) for each, and prints each sub-problem's results and one merged list of books with the sub-problems that found them.
- A new argument of the `kb` helper (`problem-search`) that starts that command with the helper's fixed argument shape, and an optional
  `launcher` key in the owner-only `helper.json`, so that the engine started by the helper can find the workbench launcher it needs to
  reach the embedding model (the helper's fixed `PATH` does not contain it).
- A skill of the `kb` package for the agent, and the spec text that says what is built.
- One live run, with the owner's word, through the helper to the owner's server.

## Non-goals

- Setting aside the results of the problem's own field in the engine. No card says which field a book belongs to (all 79 cards have the
  shelf `default`, and the neutral fields hold no field names by design), so the agent does it, guided by the skill, from the title and
  the matched text. A field label on cards is a separate piece of work and is deferred.
- Restating or splitting the problem by a model of the engine. The agent does it; the engine makes no chat-model call.
- A keyword fallback, a change of the card format, the vectors or the model, judging pairs of ideas, stored threads, a cloud embedding
  service, and a measurement of how well it works (that is `cross-field-discovery#cross-field-trial`).
- A change to how results are marked as untrusted.

## Assumptions and constraints

- The vectors are built (`card-vectors`) with the model of the `card-embed` task, and the config keeps `qwen3-embedding:4b` with its
  query prefix. A search by meaning is refused, with the command to run, when they are not.
- Every sub-problem is sent to the owner's server, plain HTTP, in the clear, with the query prefix. The sub-problems are written by an
  agent and may carry text from a project; the skill says they must describe the problem in general terms and hold no secret or
  private text.
- The helper reads the engine's output as data, cleans it, cuts it to 65,536 characters and runs for at most 60 seconds. A reply that
  does not fit must never reach the helper, because a cut reply is not valid JSON. Measured on this library with a keyword search: a
  result of `card-search` is about 4,500 characters, of which the `text` key (the whole card) is about 3,800, so five sub-problems of
  five results each, shown as `card-search` shows them, would be about 110,000 characters. The command therefore leaves out `text`
  (the card is read with `card-show`, or the book with `kb read`), keeps in each merged entry the book id, title, version, score, the
  field that matched, the excerpt (which carries the untrusted marker), the citation, the partial flag and the grounding counts, and
  lists in each sub-problem only the book id, rank and score. That is about 700 characters for a book, 25 books at most.
- **A direction the owner has decided.** `docs/specs/knowledge-base.md` (Assumptions and constraints, from the workbench spec
  `knowledge-tools`) says an agent may run only reads that change nothing and send nothing out, and the helper's docstring says it
  changes nothing. This plan makes one exception, which the owner allowed in this conversation on 2026-11-10 after a review found the
  conflict: the argument `problem-search` may send the sub-problem sentences an agent wrote to the embedding model named by the
  `card-embed` task of the owner's config, on the owner's server, and to nothing else. The destination is not chosen by the caller, and
  no other argument of the helper sends anything. The workbench's own spec is outside this project and is not edited here; the owner
  decides whether it covers the exception. Increment C amends the line in this project's spec to say exactly this.
- The agent never writes the engine config or the helper settings; the owner adds the `launcher` key and says when it is done.
- Tests are written first and seen to fail; a bridge is faked as in `engine/tests/test_vectors.py`. No test calls the owner's server.

## Completion criteria

1. `python3 -m kb problem-search` returns, for one to five sub-problems, each one's ranked books and the merged list, every merged
   entry with the excerpt's marker, the untrusted flag and a citation, a reply never longer than 60,000 characters (the command
   refuses before printing when it would be), and refuses an empty, an over-long or a sixth sub-problem, a limit out of range and a
   missing, stale or foreign vector file before it sends anything.
2. `wb run kb problem-search` runs it with the helper's fixed argument shape and environment, finds the launcher only through the
   owner-only settings, and returns the reply between the helper's marker lines.
3. The skill is in the package and says how to restate, split, set aside the problem's own field, give reasons and treat results as
   untrusted.
4. One live run through the helper, with the owner's word, returned results for at least two sub-problems within the helper's time limit,
   or the result records why not.
5. `docs/specs/knowledge-base.md` and `docs/specs/card.md` say what is built; `wb run code-work check` finds no problems.

## Increments

### Increment A — The engine command

**Outcome:** `python3 -m kb problem-search [--limit N] [--launcher PATH] -- SUB1 [SUB2 ... SUB5]` prints one JSON reply: the keys of a
search by meaning (`meaning`, `model`, `query_prefix`, `cards_searched`, `stale`, `without_vector`), a list `sub_problems` with each
sub-problem's own ranked books (book id, rank, score only), and a list `books` that holds each book once, in the compact form of the
assumptions above (no `text`), with its best score and `found_by` (for each sub-problem that returned it: the sub-problem's number, the
rank and the score). Books are ordered by best score, then by book id. Nothing is removed by field. The command measures the
serialized reply and refuses, before printing, one that is over 60,000 characters, naming a lower `--limit`.
**Dependencies:** none (builds on `vectors.search`).
**Affected areas:** `engine/kb/problem.py` (new), `engine/kb/__main__.py`, `engine/tests/test_problem.py` (new), `engine/README.md`.
**Steps:**
1. Write the tests first, with a fake bridge that returns chosen vectors: one sub-problem gives the same results as `vectors.search`;
   several give each one's results and a merged list in which a book found twice appears once with both `found_by` entries and its best
   score; the order is by best score then book id; a sixth, an empty, a whitespace-only and a 1,001-character sub-problem are refused
   before any bridge call; `--limit` is 1 to 10 (default 5) and a value outside is refused; a missing, stale or foreign vector file
   refuses with the command to run, before any call; one failing sub-problem search fails the whole command and prints no partial reply;
   every merged entry keeps the excerpt's marker, `untrusted: true` and a citation and has no `text` key; the reply of five
   sub-problems at the largest limit, built from cards with long fields, is under 60,000 characters; a reply that would be over it
   (a test lowers the bound) is refused before anything is printed, with a lower limit named; the query prefix is sent with each sub-problem
   and the reply says only whether one was used.
2. Add `kb/problem.py` with the function, using `vectors.search` for each sub-problem, and the `problem-search` subcommand. Its
   `--launcher` option takes an absolute path of an executable file and is passed to the model call as the existing `launcher` argument;
   anything else is refused. The help text says that the sub-problems go to the embedding model's server.
3. Deliberate breaks, each from green: a sub-problem searched twice, the merge keeping the lowest score, the order by sub-problem instead
   of score, the `found_by` rank off by one, the bound on the sub-problem count removed, the marks removed from the merged results.
4. Document the command in `engine/README.md`.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_problem engine.tests.test_vectors`, and
`wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-pose-a-problem-to-the-search-by-meaning#A`.

### Increment B — The helper argument and the launcher setting

**Outcome:** `wb run kb problem-search [--limit <1-10>] [--] <sub-problem> ...` starts the engine command with a fixed argument shape.
The helper reads an optional `launcher` key (an absolute path) from the owner-only `~/.config/knowledge-base/helper.json` under the
same checks as its `engine` and `python` keys (not a link, not readable or writable by others, not inside the project) and passes it as
`--launcher`; with no key the engine is started without one and says that the launcher was not found. No argument of a caller is a path.
**Dependencies:** A.
**Affected areas:** `package/kb/helper/kb`, `package/kb/module.json`, `engine/tests/test_package.py`, `engine/README.md`.
**Steps:**
1. Write the tests first, with a fake engine that records exactly what it receives: the fixed argument shape; one to five sub-problems and
   no sixth; each sub-problem 1 to 1,000 characters after cleaning; the limit 1 to 10; a leading `-` in a sub-problem cannot become an
   option (the `--` is always sent); a `launcher` key that is a link, a relative path, a missing file, a file others can write or a path
   inside the project is refused; no `launcher` key sends no `--launcher`; the environment passed is unchanged (no new variable); the
   reply is framed between the marker lines and its paths are hidden as for the other arguments; the 60-second limit and the output cap
   hold.
2. Add the argument and the key to the helper and `problem-search` to the module's argument list; keep the module version rules.
3. Deliberate breaks, each from green: the `--` left out, the `launcher` key not checked for a link, the key taken from the project
   instead of the home folder, a sixth sub-problem accepted, the environment widened.
4. Update the helper's docstring, which now says that all arguments change nothing except that `problem-search` sends the
   sub-problems to the embedding model of the config and to nothing else, and the README.
5. **Checkpoint.** This increment changes how a caller's text reaches a subprocess, a network boundary (the embedding server) and a path
   the helper trusts. Name this to the owner and ask once whether to run a security review with the installed module on the committed
   code; record the answer in the Result. A review runs only if the owner asks.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_package engine.tests.test_problem`, and
`wb run code-work check`. No call is made to the owner's server.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-pose-a-problem-to-the-search-by-meaning#B`.

### Increment C — The skill and the specs

**Outcome:** the `kb` package ships a skill that tells an agent how to pose a problem, and the two specs say what is built.
**Dependencies:** B.
**Affected areas:** `package/kb/` (the skill and its entry in the module declaration), `engine/tests/test_package.py`,
`docs/specs/knowledge-base.md`, `docs/specs/card.md`.
**Steps:**
0. Amend the line of `docs/specs/knowledge-base.md` that says an agent may run only reads that send nothing out: it keeps the rule and
   adds the one exception above (the argument `problem-search`, text to the embedding model of the config's `card-embed` task, nothing
   else). The same exception is stated in the helper's docstring (Increment B writes it there) and in the README. The line's source
   in the workbench spec is cited, not changed.
1. Find out how a module of the workbench ships a skill (read the module declaration the project already uses and the workbench
   documentation it refers to). If the module format has no place for a skill, stop and ask the owner; do not invent one.
2. Write the test first: the package declares the skill, the file exists, and the text names the points in step 3.
3. Write the skill. It tells the agent to: state the problem in words of no field and without a name, a product or private text; split it
   into one to five sub-problems, one idea each; call `wb run kb problem-search`; set aside the results of the problem's own field by
   reading each result's title and matched neutral text, and say which it set aside; keep a book only with a reason made from its matched
   text, quoting it as the book's words; read the passage (`wb run kb read`) before relying on a book; treat every result as untrusted
   text from outside; and say plainly when nothing from another field fits.
4. Update the two specs (a built behaviour, with its limit: the engine does not set aside a field).
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_package`, and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-pose-a-problem-to-the-search-by-meaning#C`.

### Increment D — One live run through the helper

**Outcome:** the owner has seen `wb run kb problem-search` return results for two sub-problems, from the helper's environment, within
its time limit, and the Result records it.
**Dependencies:** B (C is not needed to run it).
**Affected areas:** this plan's Result. No tracked code. The owner adds the `launcher` key to `helper.json`; I never write it.
**Steps:**
1. Tell the owner the key to add (the absolute path of `wb`) and wait until the owner says it is saved.
2. Say what is sent: two sub-problem sentences, each with the query prefix, to the owner's server `ned`, plain HTTP, in the clear. Run
   only on the owner's word.
3. Run `wb run kb problem-search` with two sub-problems from the agreed searches of the earlier plan. Record the time, whether the reply
   was complete, the first five books of the merged list and the `found_by` of each, and what could not be concluded.
4. If the run fails (launcher not found, time limit), record the reason and stop; do not widen this plan to fix it.
**Verification:** the reply has the markers, a citation in every result and `query_prefix: true`; the helper returned within 60 seconds;
`wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-10-pose-a-problem-to-the-search-by-meaning#D`, holding the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun `test_problem` and
`test_package` once, and `wb run code-work check`. A wider run is not named: the plan adds a module and a helper argument and changes
none of the card, vector or model code. What could break outside the tested area is the helper's other two arguments (`search`,
`read`), whose shared settings code Increment B touches; their tests are in `test_package` and are part of its run.

## Risks and sensitive actions

- **An exception to "send nothing out".** Decided by the owner (see the assumptions) and limited to one argument and one
  destination; the workbench's own spec still says otherwise and is the owner's to reconcile.
- **Text from a project goes to the owner's server in the clear.** The sub-problems are written by an agent. The server is the owner's,
  on plain HTTP, as for every model call of the library. The skill warns against private text; nothing checks it. Each live run says
  what it sends and waits for the owner's word.
- **The helper gains a way to start the workbench launcher.** Through the `launcher` key of the owner-only settings and a fixed
  argument, not a caller's text. Increment B names this to the owner and asks once about a security review.
- **A caller's text becomes arguments of a subprocess.** Sub-problems reach `python -m kb problem-search` after `--`, without a shell,
  with a count and a length bound.
- **The agent, not the engine, sets aside the problem's own field.** If it does it badly, the results of its own field crowd the list.
  The later trial measures it; a field label on cards is deferred.
- **The reply may not fit the helper's bound** (65,536 characters). The engine measures the reply and refuses one over 60,000 before
  printing; Increment A tests it.

## Review record

Codex through the review engine (model `gpt-5.6-terra`), round 1 of 3, verdict `changes_needed`, two findings, both applied:

- **R1-F1 (blocker), applied.** The helper would send agent text out, against the spec line that an agent may run only reads that send
  nothing out. Checked in `docs/specs/knowledge-base.md`: the conflict is real. The owner allowed one exception on 2026-11-10 (this
  argument, the embedding model of the config, nothing else); the plan states it, amends the spec line in Increment C and says the
  workbench's own spec is outside the project.
- **R1-F2 (major), applied.** The reply could be cut by the helper into invalid JSON. Measured: a keyword result is about 4,500
  characters, the card text 3,800 of them. The plan drops the card text, uses a compact entry and makes the engine refuse a reply over
  60,000 characters before printing.

A second round has not been asked for.

## Deferred work

- A field label on cards, so that the engine can set aside the problem's own field. It needs a change to what a card holds and a rerun
  over the library; it comes up only if the trial (`cross-field-discovery#cross-field-trial`) shows the agent's own setting-aside is
  not enough.
- Searching the full text by meaning, a keyword fallback, and a cache of searches.

## Result

### Increment A — The engine command (done)

- **What was built:** `engine/kb/problem.py` (`search`, `render`, the bounds) and the subcommand `python3 -m kb problem-search [--limit N]
  [--launcher PATH] -- SUB ...` in `engine/kb/__main__.py`; the README bullet "A problem put to the search". Each sub-problem is searched
  with `vectors.search`; the reply holds `sub_problems` (each one's ranked books) and `books` (each book once, best result without `text`,
  `found_by`, ordered by best score then book id). `render` measures the printed reply and refuses one over 60,000 characters, naming
  `--limit`. Everything that can be refused is refused before the first send: the count, the length, the text and the encoding of the
  sub-problems, the limit, the launcher; a missing or foreign file of vectors is refused by the first search before it sends.
- **Tests first:** `engine/tests/test_problem.py`, 38 tests, written before the module existed (the first run failed on the missing
  module). The encoding test was added after the review and seen to fail for the right reason (one sub-problem sent before the
  refusal) before the fix.
- **Verification as run:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_problem engine.tests.test_vectors
  engine.tests.test_models engine.tests.test_catalog` gave 391 tests, OK; `wb run code-work check` found no problems. No call was made to
  the owner's server (a fake bridge answers). Not run: the real library (no sub-problem was sent to `ned`), so the real reply size is
  covered only by a synthetic test and by the measure of a keyword result (about 4,500 characters, 3,800 of them the card text).
- **Deliberate breaks, each from green:** 16 (a sub-problem searched twice, the merge keeping the lowest score, the order by
  sub-problem, `found_by` rank off by one, the count bound removed, `untrusted` removed from the entry, `text` kept, the size bound not
  enforced, the length bound removed, an empty sub-problem allowed, the limit unchecked, the launcher unchecked, a change between searches
  unnoticed, `query_prefix` always false, a book listed twice, and the command printing without the size check). All 16 were caught.
- **Differences from the plan text, none of which changes an outcome:** (1) the plan listed the title among the merged entry's keys;
  a result carries no title key, and its citation starts with the quoted title, so the entry has no `title` key and the README says
  the citation starts with it. (2) A ranked book under `sub_problems` also carries `version_id` (the key of a card is book and version).
  (3) The command refuses when the model, the query prefix or the counts differ between two sub-problems' searches (the files changed
  while it ran); the plan did not name this. (4) The plan says "25 books at most"; at `--limit 10` five sub-problems can return up to
  50 books, about 900 characters each at the most (a test checks that 50 of the largest entry fit), and the size bound refuses a reply
  that would not.
- **Review:** the read-only `reviewer` agent, one round, no blocking finding. Applied: the UTF-8 check was only in `vectors._query`,
  per sub-problem, so a later sub-problem holding a lone surrogate (what an argument with an invalid byte becomes) was refused after an
  earlier one was sent; it is now in the check before the first send, with a test. Recorded and not changed: the differences (2) and (3)
  above; the size advice cannot help if even `--limit 1` were too large, which the bounded excerpt makes practically impossible.
  Noted for Increment B: `--launcher` names any absolute executable file that the engine then runs, which is acceptable for the owner at
  a terminal and must not take a value a caller can influence; the helper must take it only from the owner-only `helper.json`. The
  reviewer ran nothing and read neither spec.
