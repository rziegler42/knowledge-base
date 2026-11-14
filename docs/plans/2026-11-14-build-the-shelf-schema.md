# Build the shelf schema

Status: In Progress
Created: 2026-11-14
Candidate: none (the shelves, the fetch engine and the crawler are outside every roadmap, which say so; creating a roadmap for them is the owner's change of direction, and this plan is the first step the owner asked for)
Specs: docs/specs/shelf.md

## Goal

The library has a fixed list of shelves, kept as a tracked file in this project, built from OpenAlex's subfields and topics and from a short, reviewed list of
Library of Congress subclasses for fields OpenAlex does not cover, as the decision
`2026-11-14-the-shelf-schema-is-our-own-list-from-openalex-and-lcc` says. When the plan is done:

1. A checker validates the file, and its tests were seen to fail first and are shown to catch deliberate breaks.
2. The two public lists were read once from the network, and their size, retrieval date and hash are recorded, so the file can be rebuilt and compared.
3. The owner has reviewed the Library of Congress list, and the owner's marks are recorded as given.
4. The file is committed with its provenance, and it can be rebuilt byte for byte from the recorded inputs.

This plan builds data and a checker. It does not match books to shelves, scout or fetch, and it does not change `docs/specs/shelf.md`, which was revised to
match the decision before this plan starts.

## Scope

- A format for the schema file and a checker for it (`engine/kb`, with tests).
- One read of OpenAlex's public lists of fields, subfields and topics, and one read of the Library of Congress classification outline, each saved outside the
  repository and cited by hash.
- A list of Library of Congress subclasses for fields OpenAlex lacks, proposed by the agent and reviewed by the owner.
- A builder that makes the file from those inputs, and the file.

## Non-goals

- The matcher that places a book on a shelf, and the test of it on OpenAlex-labelled papers (a plan of its own).
- The state of a shelf (scout, active, dormant), its priority and its counts: they are the library's data, not the file's.
- Scouting, the fetch engine, drill-down, the exploration share, and any use of Wikipedia's lists.
- Any further change to `docs/specs/shelf.md` (it was revised on 2026-11-14 to match the accepted decision, after two rounds of review), and any change to a
  roadmap, the library, the cards, the themes, the weave or the walk.
- `schema-adopt`, the library's own step that takes a version of the schema file into use (a governed action the spec now defines), and the library's state
  file for shelves.
- The schedules of the Library of Congress: only the names and codes of subclasses are kept.

## Assumptions and constraints

- **The decision is accepted.** `docs/decisions/2026-11-14-the-shelf-schema-is-our-own-list-from-openalex-and-lcc.md` was accepted by the owner on 2026-11-14, and
  `docs/specs/shelf.md` was revised to match it. This plan follows both: the file holds identity only (the spec's "The schema and the standard classifications"),
  every OpenAlex topic is in it, and a shelf has the one scope sentence that placement matches against (the fetch scope belongs to the library's rules, not to the file).
- **The format (a proposal):** one JSON file with a `format` number, a `snapshot` (the OpenAlex lists' retrieval date and hash and the outline's), and a list of shelves,
  each with `slug` (lowercase kebab-case, unique, never changed), `name`, `level` (`domain`, `field`, `subfield`, `topic` or `custom`), `parent` (a slug or null),
  `openalex` (the identifier, or null), `lcc` (a subclass code, or null) and `scope` (one sentence). Nothing about scout or active state, priority or counts.
  Where the file lives is fixed in Increment A, inside `engine/kb/`.
- **The builder's inputs are three, all explicit:** the saved OpenAlex lists (outside the repository, cited by hash), the saved Library of Congress outline (the same), and a
  **tracked, versioned file of custom shelves** written in Increment C from the owner's marks: for each custom shelf its code, name, parent, one scope sentence, the reason and
  its source page (URL and retrieval date). The owner's keep, drop and add decisions are therefore data the builder reads, and not only a narrative in the Result.
- **The scope sentence of a shelf from OpenAlex** is fixed by a rule that Increment D tests and the owner reads: the first sentence of the description OpenAlex gives for the
  topic, subfield, field or domain if the saved list has one (Increment B records which fields the lists carry), and otherwise the fixed sentence "Works on <name>, <level article> of <parent name>."
  The sentence of a custom shelf comes from the tracked file of custom shelves.
- **Network.** Two plain reads of public data (OpenAlex's list endpoints and the Library of Congress's outline pages), from this machine, with no query that carries
  anything of the owner's and nothing sent to the model server. The owner says "run it" before each (Increments B and C). The files read are untrusted data: parsed as
  data, never run, size-limited, and saved with mode 600 outside the repository.
- **Counts the lookup gave (second-hand, to be verified in B):** 4 domains, 26 fields, 252 subfields, 4,516 topics for OpenAlex; "over 225" subclasses for the Library of Congress.
  If the real lists differ, B says how and the plan uses the real lists.
- The Library of Congress terms have not been checked. The file keeps names and codes only, and the owner decides in Increment C whether that is acceptable, with the
  repository's visibility in mind.
- The engine's own code uses the standard library; the checker and the builder need nothing more.

## Completion criteria

1. The plan follows the accepted decision and the revised shelf spec (both of 2026-11-14), and changes neither.
2. `python3 -m kb shelf-schema-check` validates a schema file: format, unique slugs, parents that exist, levels in order (a topic under a subfield, a subfield under a field, a field under a domain, a custom shelf under none or a domain), no cycle, and the counts it
   reports; its tests were seen to fail first, and deliberate breaks of the checker are caught.
3. The two public lists were read, and the Result records each one's URL, retrieval date, size, hash and counts, and how they differ from the second-hand figures.
4. The owner has marked each proposed Library of Congress subclass (keep, drop, or add one), the marks are recorded as given, and a tracked file of custom shelves holds exactly the kept and added ones, each with its scope sentence.
5. The schema file is committed, passes the checker, has the counts the Result records, and the builder reproduces it byte for byte from its three recorded inputs (the saved OpenAlex lists, the saved outline and the tracked file of custom shelves).
6. The owner has read the names of the fields and subfields in the file and the custom shelves.
7. `wb run code-work check` finds no problems, and nothing outside this plan, the checker, the builder, the file and the engine's README changes.

## Increments

### Increment A — The format and the checker

**Outcome:** a checker for the schema file exists, with tests and deliberate breaks, and no data and no network.
**Dependencies:** none (the decision is accepted and the spec revised).
**Affected areas:** `engine/kb/shelfschema.py` (new), `engine/kb/__main__.py` (the command `shelf-schema-check`), `engine/tests/test_shelfschema.py` (new), `engine/README.md` (the command).
**Steps:**
1. Write the tests first from a small fixture of a schema (two domains, a field, two subfields, three topics, a custom shelf), and see them fail: a valid file passes; each rule above is broken in
   turn (duplicate slug, missing parent, a topic under a field, a cycle, a missing field of a shelf, a slug with capitals or spaces, an unknown level, a custom shelf under a topic, an unknown format number).
2. Write the checker to make them pass: it reads the file as data, refuses a file over a size limit, a value of the wrong type and any field it does not know (so that no state, priority or count can be put in the file), and prints the counts by level and the problems found, with the line or shelf of each.
3. Register the command and write its README entry (what it reads, that it writes nothing, that it needs only the standard library).
4. Deliberate breaks: edit the checker to drop each rule in turn, run the tests, expect a failure, and restore the file byte for byte.
5. The `reviewer` agent reads the checker, its tests and the breaks.
**Verification:** `python3 -m unittest engine.tests.test_shelfschema` (and the nearest neighbours that read the command table: `engine.tests.test_package`), the breaks all caught and the file restored by hash, and `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#A`.

### Increment B — The two public lists

**Outcome:** OpenAlex's fields, subfields and topics are saved outside the repository with their size, hash and counts recorded.
**Dependencies:** A, and the owner's word ("run it") after being told what is read.
**Affected areas:** this plan's Result; raw files outside the repository (mode 600).
**Steps:**
1. Tell the owner exactly what is read (the addresses, the fact that it is a plain GET from this machine with nothing of the owner's in it, and the limit on size) and wait for "run it".
2. Read the lists with a small script held outside the repository (cited by hash), one request at a time, with a size limit and a time limit, and save each reply unchanged.
3. Record in the Result, for each file, its URL, the retrieval date, its size and its sha256; the counts by level; the version or date the source gives; how the counts differ from 4, 26, 252 and 4,516; and any topic that has no subfield or any other irregularity.
4. The `reviewer` agent reads the script and the Result (not the raw files, which hold only public data but need no cloud model).
**Verification:** the counts recomputed by a second snippet from the saved files and equal to the recorded ones; each file's hash recorded twice; `wb run code-work check`. No test of the engine is run: nothing tracked but this plan changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#B`.

### Increment C — The Library of Congress list

**Outcome:** the list of Library of Congress subclasses that become custom shelves is fixed by the owner and kept as a tracked file of custom shelves.
**Dependencies:** B (it needs to know which fields OpenAlex's subfields already cover), and the owner's word ("run it") for the read.
**Affected areas:** this plan's Result; the saved outline outside the repository; the tracked file of custom shelves, inside `engine/kb/` beside the schema file (its form is fixed in Increment A).
**Steps:**
1. Tell the owner what is read (the Library of Congress classification outline pages, a plain GET) and wait for "run it". Save each page unchanged with its URL, date, size and hash.
2. Extract the main classes and subclasses with a script held outside the repository, and record the count.
3. Propose, from the subclass names, those that cover fields no OpenAlex subfield covers (crafts and trades, recreation, the military, the arts and the humanities), each with a one-line reason, and show the proposal to
   the owner with the subclasses left out beside it.
4. The owner marks each *keep* or *drop* and may add one, and says whether keeping only names and codes is acceptable; record the marks as the owner gave them.
5. Write the tracked file of custom shelves from the marks: one entry for each kept or added subclass, with its code, its name, its parent (none or a domain), one scope sentence
   (written by the agent and read by the owner), the reason, and the page it came from (URL and retrieval date); a dropped entry is not in the file. The file is checked by the checker of Increment A.
6. The `reviewer` agent reads the proposal, the file and the Result.
**Verification:** the count of subclasses recomputed from the saved pages by a second snippet; every kept entry has its code and its page; the file has one entry for each *keep* and *add* of the owner's marks and none for a *drop*
(compared by a second snippet); the owner has read the scope sentences. `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#C`.

### Increment D — Build and commit the schema

**Outcome:** the schema file is in the repository, passes the checker and can be rebuilt byte for byte from the recorded inputs.
**Dependencies:** A, B and C.
**Affected areas:** `engine/kb/shelfbuild.py` (new), `engine/tests/test_shelfbuild.py` (new), the schema file under `engine/kb/`, `engine/README.md`; it reads the saved outline and the tracked file of custom shelves of Increment C.
**Steps:**
1. Write the builder's tests first on a small fixture of the three inputs (a stable slug for each name, a clash between two names resolved the same way every time, parents set, a custom shelf, the scope rule, the snapshot block with the outline's provenance,
   and a custom entry whose code is not in the outline, which is refused), and see them fail.
2. Write the builder: it reads the saved OpenAlex lists, the saved Library of Congress outline and the tracked file of custom shelves by path (arguments, never hard-coded). It refuses a custom entry whose code and name
   are not in the saved outline, makes the slugs, sets each scope sentence by the rule above, orders the shelves in a fixed order, and writes the file with the snapshot block (each source's URL, date and hash, the outline's
   included, and the hash of the file of custom shelves).
3. Build the file from the real inputs, run the checker, and compare the counts with the Result of B and C; rebuild into a second file and compare the bytes.
4. Show the owner the names of the fields and subfields and the custom shelves (a single page), and record anything the owner changes.
5. Deliberate breaks of the builder (a slug rule, the order, a parent, the scope rule, a custom shelf left out, the check of a custom entry against the outline, the snapshot hash) and their restoring.
6. The `reviewer` agent reads the builder, its tests and the file's counts.
**Verification:** `python3 -m unittest engine.tests.test_shelfschema engine.tests.test_shelfbuild`, the checker on the file, the rebuild equal byte for byte, every topic, subfield, field and domain of the
saved OpenAlex lists present as a shelf (counted by a second snippet), the breaks caught, `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#D`.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end the checker is run once more on the file, the saved inputs' hashes (including the tracked file of custom shelves) are compared with those recorded, and the two test modules are rerun.
The engine's other tests are not rerun: only the command table in `__main__.py` and the README change outside the new modules, and `engine.tests.test_package` reads that table. What could break outside the tested area: the command table (an entry
that clashes with another), which that test covers.

## Risks and sensitive actions

- **Two network reads of public data.** They send nothing of the owner's and nothing to the model server. The owner is told before each and says "run it". The replies are untrusted: parsed as data, size-limited, never run.
  Parsing untrusted JSON and HTML is a place to look for a flaw; the owner is asked once whether to run a security review of the reader.
- **The Library of Congress terms are unchecked.** Only names and codes are kept; the owner decides in Increment C.
- **The public lists may differ from the second-hand figures,** or have irregular entries (a topic without a subfield, duplicate names). B records them; the builder refuses what it cannot place and says so.
- **Slugs are permanent.** A badly chosen slug rule would be hard to change once books are placed. The rule is fixed in D's tests and the owner reads the names before the commit.
- **No push** and no change of the library, the weave, the vectors, the skills, the helper or the spec of shelves.

## Review record

### The plan (before approval)

Reviewed with Codex through the project's review engine, two rounds of three (the files are in `.workbench/workbench/review-engine/plan-488dcf81640cd6e4/`). Round 1: one major finding, applied (the builder
could not reproduce the custom shelves or the scope sentences; a tracked file of custom shelves and a fixed scope rule were added). Round 2: one major finding, applied (the outline was declared an input but the builder
did not read it; it now does, and checks each custom entry against it). The owner approved the plan on 2026-11-14 after both.

### Increment A

The `reviewer` agent (read only), two exchanges of six. First exchange: one blocking finding and four not blocking; it read the plan, the checker, its tests, the command and the README, and ran nothing.

- **1, blocking, applied.** `counts()` looked up a shelf's `level` in a dict, so a hostile file with a list or a dict as a level raised `TypeError`, the command ended in a traceback with exit 1 (the code for "problems found") and named
  no problem. Reproduced first by new tests that failed with the error, then fixed (`type(level) is str` before the lookup). The same tests put 16 hostile values (null, booleans, a 400-digit integer, floats, empty and long strings,
  lists, dicts) in every place of the schema and of the custom file, and found no other crash.
- **2, not blocking, applied.** `load()` checked the path with `os.stat` and then opened it, so a pipe swapped in between could make the open wait. It now opens with `O_NONBLOCK` and reads the kind of file from the open descriptor.
  A symlink to a regular file is read as that file, and the README now says so.
- **3, not blocking, kept.** Every cycle also breaks a level rule, so the cycle check cannot be reached alone; it stays as a second line of defence and its test and break show it works.
- **4, not blocking, applied.** README: the snapshot's `custom` entry holds a sha256 only, `--custom` prints only the number of custom shelves, `Infinity` is refused.
- **5, observation.** The checker also refuses unknown keys inside the snapshot and the custom file, wider than the plan names and in the spirit of "identity only".

Second exchange (the fixes only): both fixes remove their findings, nothing wrong in what they introduced, no blocking finding left. The reviewer ran nothing and did not read the breaks script; the runs are mine, below.
A security review was not asked for: the checker reads one file as data and writes nothing. I recommended none for Increments A and D and one for B and C, and the owner has not yet answered.

## Deferred work

- The matcher that places a book on a shelf, with its test on OpenAlex-labelled papers.
- The state of a shelf, its priority and its counts, and the library's config that holds them.
- The scouting pass (about 3 books for each subfield), the fetch engine's first slice, and the pilot of topic-level scouts.
- A roadmap for shelves and the crawler (a change of direction: the owner's). `docs/specs/shelf.md` was revised to match the decision before this plan.
- `schema-adopt` and the library's shelf state, and the fetch engine's own plan, which will also settle the points the spec review left open: the privacy
  path of demand-derived queries (an earlier agreed position) and whether any per-token cache exists.
- Wikipedia's lists as a map for choosing scouts, as a source of its own decision.

## Result

### Increment A — the format and the checker (built, verified and reviewed; **not committed**)

- **Built:** `engine/kb/shelfschema.py` (372 lines, sha256 `a57fdd0a…895fc`), the command `shelf-schema-check` in `engine/kb/__main__.py` (11 lines: an import, a parser with `--custom`, a dispatch that exits 1 for a problem, 2 for a
  refused file), `engine/tests/test_shelfschema.py` (60 tests, 520 lines, sha256 `95b68b1e…e771`), and a section "The shelf schema" and a test-list entry in `engine/README.md`. No network, no library, no config and no model server are
  used; the checker needs only the standard library and writes nothing.
- **The rules, as the checker has them:** format 1 (an integer, not a boolean or a float); unique slugs of lowercase words joined by single hyphens; a name and a scope sentence of 1 to 200 and 1 to 500 characters with no control, hidden
  or separator character; five levels with a parent rule for each (a domain has none, a field's is a domain, a subfield's a field, a topic's a subfield, a custom shelf's none or a domain); no cycle; one OpenAlex identifier on a shelf
  that is not custom and one subclass code on a custom shelf and neither the other way; no duplicate identifier or code; a snapshot with the three sources and the fields of each; **any field the file does not know is a problem**
  (so a state, a priority or a count cannot be put in), at the file, shelf, snapshot, source and custom levels; the file read as data, refused over 8 MB, not UTF-8 JSON, with a repeated key, `NaN` or `Infinity`, or not a regular
  file (a pipe is refused without waiting); at most 200 problems shown with the count of the rest, each naming its shelf. The file of custom shelves has its own rules (code, name, parent, scope, reason, page, date, source) under `--custom`.
- **Test-first, seen to fail:** the tests were run (1) with no module (an import error), (2) against an empty stub that finds nothing (71 failures and 8 errors counting each subtest), and then (3) against the checker. After the
  review, the hostile-value tests were written first and run against the checker as it was, and failed with the `TypeError` of finding 1 before the fix.
- **Verification as run (2026-11-14, at head `ab3bfcf` plus the uncommitted files):** `python3 -W error::ResourceWarning -m unittest engine.tests.test_shelfschema` 60 tests OK; with the neighbours `engine.tests.test_setup` and
  `engine.tests.test_package` 195 tests OK, **77 skipped** (those of `test_package` need a workbench checkout that is not set here, so the helper tests did not run); `wb run code-work check` found no problems.
- **Deliberate breaks:** `breaks_shelfschema.py` (outside the repository, sha256 `436519e7…454d`), **49** breaks, each dropping or weakening one rule or the command's exit code, each run against the tests and each file restored byte for
  byte (checked by hash: `shelfschema.py` `a57fdd0a…`, `__main__.py` `c7f40d41…`). **All caught, after strengthening tests: the first run missed six** (a duplicate-slug test was caught by the duplicate-identifier rule instead; an lcc code
  on a non-custom shelf the same; the date format was caught by the real-date check; an unknown snapshot source and the custom source's fields had no test; the size limit was caught by a truncated read), and a later run missed one
  (the file-kind check, because a folder or a pipe was refused by another error). A real flaw found while writing the breaks and fixed first: `load()` opened a path before checking its kind, so a pipe would have blocked.
- **By hand:** the command was run from a shell on a good file (exit 0, the counts by level), a bad file (exit 1, two problems named: a `state` field and a missing parent), a custom file (exit 0) and a missing file (exit 2,
  "refused: cannot read … No such file or directory").
- **Not run:** the tests of the engine that need the pinned environment or numpy (nothing they read changed: only the command table and the README changed outside the new modules), the helper tests of `test_package` (skipped),
  any network read, any model. No push.
- **Review:** see the Review record; one blocking finding, reproduced and fixed, none left after the second exchange.
- **For the commit:** the paths are `engine/kb/shelfschema.py`, `engine/kb/__main__.py`, `engine/tests/test_shelfschema.py`, `engine/README.md` and this plan, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#A`; the owner's word is awaited.
