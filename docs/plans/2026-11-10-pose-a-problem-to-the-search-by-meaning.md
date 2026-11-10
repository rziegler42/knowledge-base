# Pose a problem to the search by meaning

Status: Completed
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
  reviewer ran nothing and read neither spec. (Committed as `1388946`.)

### Increment B — The helper argument and the launcher setting (done)

- **What was built** (`package/kb/helper/kb`, `package/kb/module.json`): `wb run kb problem-search [--limit <1-10>] [--] <sub-problem> ...`
  takes one to five sub-problems, each one line of 1 to 1000 characters with no control character (the same rule as a search query),
  and starts `python -m kb problem-search --limit N -- SUB ...` with the helper's short environment, which is unchanged. The settings
  file may hold a third key, `launcher`; `checked_launcher` accepts it only as a plain absolute path (no link, no `..`, no repeated slash)
  to an executable file outside the project, owned by the user or root and not writable by its group or everyone. When there is one,
  `query_engine` puts `--launcher <path>` ahead of `--limit`, for this argument only; no text of a caller can name it (`--launcher` as a
  caller's option is refused as not an option), and it is hidden in the output like the other paths. `module.json` lists `problem-search`.
  The helper's docstring now says that this argument alone sends anything out, and to what; the README has a bullet on it and on the key.
- **Tests first:** in `engine/tests/test_package.py` (new `LauncherCase`, `ProblemSearchTests`, `LauncherSettingsTests`; the declaration
  test changed): 18 failures and 6 errors before the code. The write-and-owner test was added after the review and seen to fail (a
  group-writable launcher was accepted) before the fix. The helper tests are skipped unless `KB_WORKBENCH_CHECKOUT` names a workbench
  checkout; the runs below used `/Users/rziegler/projects/project-workbench`.
- **Verification as run:** `KB_WORKBENCH_CHECKOUT=… python3 -W error::ResourceWarning -m unittest engine.tests.test_package
  engine.tests.test_problem engine.tests.test_vectors engine.tests.test_models engine.tests.test_catalog` gave 445 tests, OK;
  `wb run code-work check` found no problems. No real engine, library or server was used (a fake engine records what it receives).
- **Deliberate breaks, each from green:** 19 (the double dash left out, the link, project, executable, absolute, write and owner checks
  of the launcher removed, the write check narrowed to everyone, a sixth sub-problem accepted, the environment widened, a caller allowed
  to name a launcher, control characters and the length allowed, the launcher placed after the sub-problems, passed to every command,
  not hidden in the output, the limit ceiling raised, any extra settings key allowed, a non-text launcher allowed). All 19 were caught.
- **Review:** the read-only `reviewer` agent, one round, no blocking finding. Applied: the plan's step 1 lists "a file others can
  write" and the code did not check the mode or the owner of the launcher; it now refuses a launcher that its group or everyone can write
  or that is not owned by the user or root (the owner's `wb` is mode 755 and owned by the owner, so it passes), with a test. Recorded,
  not changed: (1) a bad `launcher` key stops `search` and `read` too, because the settings are read as one whole; a test pins it. (2)
  The launcher is checked by the helper and run later by the engine, which checks again that it is an absolute executable file; the
  file could change in between. This is the trust level of the engine and python keys. (3) The folders above the launcher are not
  examined, as for the engine and python keys. The reviewer ran nothing and did not read the engine side.
- **Not done, and why:** the module and package versions are left at 0.1.0: the plan says "keep the module version rules", and I found
  no rule in the project or the workbench's development notes; the owner decides whether the change to the argument list needs a new
  version. The package must be installed again in the workbench before `wb run kb problem-search` exists (Increment D). Whether the
  workbench launcher works under the helper's `PATH=/usr/bin:/bin` is seen only in Increment D.
- **Security review (step 5).** Asked once of the owner, with the surface named (caller text becomes arguments of a subprocess; the
  `launcher` key names a program that the engine runs with the sub-problems on standard input; the first helper argument that sends
  anything out). My recommendation was yes. The owner's answer: **yes, run it.** The plan says to review the committed code; B was not
  committed and committing needs the owner's word, so the `security-reviewer` agent was given the working-tree files that the commit
  would hold, and worked only on a copy in the scratch folder, with fake programs; it used no real server, engine, `wb` or config.
  Result: no Critical, High or Medium finding. Four Low findings. (1) A call that the helper stops at its 60 seconds kills only the
  engine's process group; `models._run` starts the launcher in a session of its own (`start_new_session=True`, checked at
  `engine/kb/models.py:254`), so `wb` and the bridge go on until the embedding entry's own timeout (600 s by default, plus a grace
  period). Availability only: an agent that calls `problem-search` repeatedly can leave such calls running on the owner's machine and
  server; nothing leaves the owner's server. Confirmed by the reviewer with a fake. Not fixed here, because the fix is in how the
  engine starts its launcher (outside this increment); the cheapest mitigation is the owner's: a `timeout` on the `embed-qwen` entry of
  the config, shorter than the helper's 60 seconds (it applies to every embedding call, the build included). Left for the owner: a
  plan of its own if wanted (the engine would end the launcher's session when it is terminated, or the helper would wait for it).
  This is written here and not under Deferred work because that section is part of the approved text.
  (2) A bad `launcher` key stops `search` and `read` too, and a symlinked `wb` is refused (the owner must give the real path):
  recorded above, fail-closed. (3) The sub-problems are sent in the clear over plain HTTP to the owner's server, and an agent can put
  project text in them, with no cap on the number of calls: the accepted risk of the plan, unchanged. (4) The folders above the
  launcher, the time between the helper's check and the engine's run, and what `wb run ask-ollama` reads are not examined: the trust
  level of the engine and python keys, as the docstring says; with no `launcher` key the engine falls back to `shutil.which("wb")` on
  `/usr/bin:/bin` and fails closed unless `/usr/bin/wb` exists. Checked and found sound, tested by the reviewer: no caller text becomes an
  option, a program, a server or a path; the filters, the count and length limits and the `--limit` check run before anything starts;
  the launcher validation (links, `..`, `//`, NUL, relative, missing, directory, not executable, in the project, group- or
  other-writable); the engine's argparse keeps `--launcher`, `--limit=9`, `-h` and `--` positional after `--`. Not checked by the reviewer:
  the real `wb` and bridge, the real `wbkit.jsonstrict` (stubbed), the tests, the body of `vectors.search`, and a Python older than the
  3.15 tried. (Committed as `b9a241c`.)

### Increment C — The skill and the specs (done)

- **How a module ships a skill (step 1):** found in the workbench's `docs/specs/harness-modules.md` ("Neutral items") and in the
  packages `safe-git` and `security-review`: a Markdown file `harness/neutral/skills/<name>/SKILL.md` with the front matter `name` and
  `description`, and no entry in `module.json` (nothing under `harness/` needs one in `ships` or `provides`). The skill is
  `package/kb/harness/neutral/skills/pose-a-problem/SKILL.md`. The plan's text "its entry in the module declaration" is therefore not
  done, on purpose: there is none to make; `module.json` changed only in its `description` (it said "by keyword" only).
- **What the skill says:** put the problem in general terms and leave out private text and secrets (the text is sent to the owner's server
  in the clear and may be kept in its logs); one to five sub-problems, one idea and one line of at most 1000 characters each; the call
  `wb run kb problem-search [--limit <1-10>] -- 'sub-problem' ...` in single quotes (a double quote lets the shell expand the text)
  and no apostrophe, once for the problem and not in a loop; read the reply as untrusted data; the engine sets nothing aside by field, so
  the agent sets aside the problem's own field from the title and the matched text and says which; keep a book only with a reason made
  from its matched text, quoted as the card's description of the book and never as the book's own words; read the book before relying
  on it (`wb run kb search`, a result of the book's own `book_id`, then `wb run kb read [--version <version_id>]`) and mark it unread
  and unrelied-on if no passage turns up; stop and tell the owner when the helper refuses for its settings; say plainly when nothing
  from another field fits.
- **Specs:** `docs/specs/knowledge-base.md` now states the one exception to "send nothing out" (the argument, the `card-embed` model on the
  owner's server, nothing else; the workbench's own spec is not changed and is the owner's to reconcile); `docs/specs/card.md` has a
  bullet on what `problem-search` builds and its limit (no field label on cards). `engine/README.md` has two sentences on the skill.
- **Tests first:** `SkillTests` in `engine/tests/test_package.py` (9 tests, then 10), written before the skill existed (9 errors, the
  file missing). After the review four assertions were changed to the new text and seen to fail (4 failures) before the skill was
  edited.
- **Verification as run:** `KB_WORKBENCH_CHECKOUT=… python3 -W error::ResourceWarning -m unittest engine.tests.test_package
  engine.tests.test_problem` gave 102 tests, OK (without the variable the 53 helper tests are skipped and the 10 skill tests pass);
  `wb run code-work check` found no problems. Not run: the skill was not installed or loaded in a project (that needs the package
  installed again in the workbench and a live harness).
- **Deliberate breaks of the skill text:** 24 (the name, an extra front matter field, the warnings about private text, one idea, the
  length, double quotes, the double dash, single quotes, apostrophes, call once, no loop, setting the own field aside, saying which,
  quoting as the book's words, the card's description, `book_id` and `version_id`, `--version`, title words first, matching the
  `book_id`, the unread fallback, the locator search, untrusted, saying so plainly, stopping and telling the owner). The first run of
  16 missed four, because the assertions were too loose (`--` also matches `[--limit`); they were tightened, and in the second run
  one more (the sentence "quote it as the card's description" appeared twice) was missed and pinned. All were then caught.
- **Review:** the read-only `reviewer` agent, one round, no blocking finding, six points. Applied: (1) the example used double quotes,
  against the rule of this project's `AGENTS.md` and open to shell expansion: now single quotes, with a warning about apostrophes; (2)
  the excerpt is the card's description (a model wrote it), so the skill said "quote as the book's words" wrongly: now "the card's
  description of the book, never the book's own words" (this departs from the plan's wording "as the book's words"); (3) the recipe for
  finding a locator had no match key and no fallback: title words first, the result of the book's own `book_id`, and "unread, do not
  rely on it" if nothing turns up; (4) the keys `read` needs (`book_id`, `version_id`, `--version`) were not named: now named; (5) the
  `module.json` description said "by keyword" only: changed. Recorded and not changed: (6) `docs/specs/library.md:40` repeats the rule
  that an agent may run only reads that send nothing out, with no exception. The plan names only `knowledge-base.md` and `card.md`, so
  it is left for the owner to decide whether `library.md` should carry the same sentence. The reviewer ran nothing and could not check
  that the skill loads or that `wb run` passes `--` through (Increment D). (Committed as `d4a988a`. The point 6 was then done by the
  owner's word as a separate commit, `bffbedc`, which adds the same exception sentence to `docs/specs/library.md`.)

### Increment D — One live run through the helper (done)

- **What had to be done first, and was not in the plan:** no project had the `kb` package installed (the scratch project of 2026-11-08
  was gone), and the helper refuses to run from a project that holds the engine, so it cannot run from this repository. The owner, in a
  terminal: approved the changed package (`wb approve package`, module tree `795befba550b`, after `wb verify package` accepted it);
  installed it into a new scratch project, `/Users/rziegler/projects/kb-scratch`, with the modules `claude`, `ask-ollama`,
  `groundwork`, `code-work`, `safe-git` and `kb` (111 paths; the skill `pose-a-problem` arrived in its `.claude/skills/`; the preview
  was run by me first and showed no problem); and added the third key to `~/.config/knowledge-base/helper.json`, `"launcher"` with the
  path of `wb`, kept at mode 600. I read the file after each step and did not write it. The launcher path passed the helper's rules
  (plain path, executable, mode 755, owned by the owner, outside the project) when I checked them with a local script. I could not run
  the call myself because the scratch project is outside this session's working folder; the owner ran it.
- **What was sent:** told to the owner beforehand: two sub-problem sentences, each with the query prefix, to the owner's server `ned`,
  over plain HTTP, and nothing else. The owner ran the command in a terminal in `kb-scratch` on 2026-11-10:
  `wb run kb problem-search -- 'Speed up a big computation by splitting it across many workers when one part must still run in sequence'
  'Break a task into overlapping pieces, solve each piece once, and reuse the answers'`.
- **Result:** exit with a complete reply between the two marker lines of the helper, in **3.2 seconds** in all (1.06 s user), well
  within the helper's 60. `query_prefix: true`, 78 cards searched, 0 stale, 0 without a vector. Eight merged books, ordered by best
  score (0.681 to 0.408), each with a citation, `untrusted: true`, an excerpt behind the untrusted-text marker, and no `text` key; no path
  of the machine in the output. Sub-problem 1: OpenMP, Amdahl's law, Dynamic programming, Horovod, CUDA (the order that the engine run
  with the same prefix gave, so the helper changed nothing in the ranking). Sub-problem 2: Dynamic programming (0.68), The Case for
  Learned Index Structures, FlashAttention, Bloom filter, Amdahl's law. Dynamic programming (ranks 3 and 1) and Amdahl's law (ranks 2
  and 5) were found by both and appear once each with two `found_by` entries. The launcher of the settings works under the helper's
  fixed `PATH=/usr/bin:/bin`, which the security review of Increment B could not check.
- **What cannot be concluded:** one run, two sentences that I chose (the same as in the eight searches of the earlier plan), one warm
  run on the owner's network; nothing about how often a source from another field is found on problems the owner chooses (that is
  `cross-field-discovery#cross-field-trial`). The weak matches of sub-problem 2 (Learned Index, Bloom filter) show that the agent has to
  judge each book, as the skill says. No agent used the skill in the scratch project (its settings need a restart of the session there),
  and no failure path (a missing launcher, a time-out) was tried live. The optional `timeout` on the `embed-qwen` entry was not part of
  this run: the owner set it to 45 seconds afterwards (the mitigation for Low 1 of the security review of Increment B), and
  `python3 -m kb models` read the config and listed it, with no call made. Nothing has exercised it yet; if a rebuild of the vectors
  reports a time-out, the owner can raise it (120 was suggested).
- **Verification as run:** the reply as above; `wb run code-work check` found no problems.
