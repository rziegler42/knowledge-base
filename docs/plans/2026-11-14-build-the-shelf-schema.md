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
A security review was not run for A: the checker reads one file as data and writes nothing. I recommended none for Increments A and D and one for B and C; the owner said "go with your recommendation" (see Increment B).

### Increment B

**Security review of the reader** (the `security-reviewer` agent, which works on a copy in its own scratch folder and may send only to 127.0.0.1; two exchanges). Its experiments used fake servers on this machine; it never contacted a real address.

- **First exchange: no Critical or High finding; two Medium and five Low.** (1) Medium, applied: the 30-second limit of a request held only between reads, so a server that trickled one byte every few seconds, in the body or in the headers, could stretch one request to minutes or months (a trickled
  body of 103 bytes took 10.6 s against a 3 s limit, trickled headers 23.7 s); the reader now runs each request under a wall-clock alarm that interrupts a blocked read, headers included. (2) Medium, applied: a `Content-Length` with a non-ASCII digit crashed with a traceback;
  it is now a refusal. (3) Low, applied: the default trust of TLS follows `SSL_CERT_FILE` and `SSL_CERT_DIR` of the owner's environment (a self-signed certificate was accepted when the variable pointed at it); the reader now refuses to run on https when either is set. (4) Low, applied: text taken from a reply
  reached the terminal unescaped (a clear-screen code in a header); it is now escaped and cut. (5) Low, applied: a folder swapped for a link between the check and the writes sent the files to the link's target; the folder is now opened once, a link is refused, and every file is written through that open handle. (6) Low, applied:
  an interrupt or a full disk left a truncated file that a rerun would refuse; a file is now synced and removed if the write fails. (7) Low, by design: the saved files are checked only for the shape this reader needs, so Increment D must treat them as hostile.
- **Second exchange (the fixes): no Critical or High finding; one Medium and three Low, and it judged the reader fit for its first real run.** Medium, applied: an alarm that lands inside a finalizer raises an error that Python discards, which loses the deadline for that request (shown with a staged finalizer, 3.6 s against 1 s);
  the handler now arms the alarm again before it raises. Low, applied: a link given with a trailing slash was followed (a clear refusal for any link now, and `O_NOFOLLOW` kept as a second line, each with a test); the alarm is now disarmed in its own step so that the old handler is always restored. Low, noted: the deadline needs SIGALRM (macOS and Linux, not Windows) and the main thread, which the reader enforces.
- **The last fixes were not shown to the reviewer again.** The fixes of the second exchange (the alarm armed again, the clear refusal of a link, the order of disarming) were tested (54 tests) and broken on purpose (59 breaks, all caught), and were not rechecked by the security reviewer before the run. It had judged the reader fit for its first run without them and named the re-arm as the first thing to add.
- **Not covered by the review:** the real server and its real certificate chain (the run itself used the default checking and succeeded), a full disk, a signal between the open and the write, and other trust paths such as an OpenSSL configuration file or the keychain (only the two variables are checked).
**The reviewer's reading (step 4 of the increment)**, the `reviewer` agent, one exchange; it read the plan, the reader, the breaks and the checker of Increment A, and not the saved lists. One blocking finding and several others, all about the record or for Increment D; no flaw in the reader.

- **1, blocking, applied.** Criterion 3 asks the Result to record each list's address, retrieval date, size, sha256 and counts, and the version or date of the source; the Result had truncated hashes and no per-list address or size, and a truncated hash cannot feed the snapshot of the schema file. The Result now gives the full hashes, the addresses, the size and count of each list, the
  range of `updated_date` and the exact format of the manifest whose hash Increment D takes as the OpenAlex source.
- **2, applied.** "No irregularity" was too strong: it holds for the counts and the ids, and the name clash, the two empty subfields and the descriptions that are not sentences are irregularities of the data. The Result says so.
- **3, noted.** Every number it could check against the code agreed (51 requests, 52 files, 4,798 records, 282 lowercase descriptions, the times, 54 tests, 59 breaks); the claims that need the saved lists it could not check.
- **4, applied.** The Result did not say what the owner was shown before "run it", or that the reader changed after it. It now says what I described in words and what the `check` mode printed, that the addresses were not pasted to the owner, and that the changes after the "run it" were the security fixes, with the requests unchanged.
- **5, applied.** The facts for Increment D were checked against the checker of Increment A: its identifier rule accepts the real ids, its limit of 500 for a scope sentence would refuse a whole description (290 are longer) but not a first sentence (at most 476 by a plain rule), it has no rule that a subfield needs children, and it allows names with characters outside ASCII (12 names have one). Slug collisions were counted (one, the domain and the field "Social Sciences").
  The reviewer's point that the scope rule of the plan, as approved, needs a decision: the rule is "the first sentence of the description" with the fixed sentence as the fallback, and it works on these data as long as Increment D writes exactly what ends a sentence; **I left the plan's text as approved and the owner reads the result in Increment D** (changing the rule in the plan would need a new approval, which I did not ask for).
- **6, noted, not changed.** Remaining code limits, all in the Result: only the reader's own refusals are caught in `main`, a link higher up the path is followed, and the breaks script rewrites the reader in place (it restores it by hash).

## Deferred work

- The matcher that places a book on a shelf, with its test on OpenAlex-labelled papers.
- The state of a shelf, its priority and its counts, and the library's config that holds them.
- The scouting pass (about 3 books for each subfield), the fetch engine's first slice, and the pilot of topic-level scouts.
- A roadmap for shelves and the crawler (a change of direction: the owner's). `docs/specs/shelf.md` was revised to match the decision before this plan.
- `schema-adopt` and the library's shelf state, and the fetch engine's own plan, which will also settle the points the spec review left open: the privacy
  path of demand-derived queries (an earlier agreed position) and whether any per-token cache exists.
- Wikipedia's lists as a map for choosing scouts, as a source of its own decision.

## Result

### Increment A — the format and the checker (built, verified and reviewed; committed as `a3fd46c` on the owner's word)

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
- **For the commit:** the paths are `engine/kb/shelfschema.py`, `engine/kb/__main__.py`, `engine/tests/test_shelfschema.py`, `engine/README.md` and this plan, with the trailer `Plan: 2026-11-14-build-the-shelf-schema#A`; the owner said "commit a" and it was committed.

### Increment B — the two public lists (read on the owner's "run it" of 2026-11-14; reviewed twice over (the security review, then the reviewer); **not committed**)

- **What was read.** One run of the reader (held outside the repository, with its tests and its breaks) on 2026-11-14, 17:19:36 to 17:20:03 UTC: **51 plain HTTPS GET requests to `https://api.openalex.org`, one at a time, 0.3 seconds apart**, for the domains, fields, subfields and topics lists, 100 results a page, with
  `select` of `id, display_name, description, ids, updated_date` and the parent level or levels of each (so that the keyword lists and the sibling lists were not asked for), with a fixed User-Agent and **nothing of the owner's** (no key, no email, no cookie; the owner's address was not used). Nothing was sent to the model server. All 51 answered 200 with no redirect, no retry and no failure; the longest request took 0.3 seconds
  and all 51 together 10.7 seconds; the largest reply was 96,602 bytes and the replies together 4,415,996 bytes. The replies are saved unchanged, one file each, with a report, in a folder of the owner's alone (mode 700) outside the repository (52 files, all mode 600).
- **The owner's word and the order:** the owner said "go with your recommendation" to a security review of the reader before the read, and "run it" while that review was still running; I held the run until the review had reported and its fixes were made and rechecked, and ran it then.
- **Counts, as the lists gave them:** domains **4**, fields **26**, subfields **252**, topics **4,516**; each as the plan expected from the second-hand figures, with no irregularity in the counts or the ids (every count equals what was received; all ids are unique; no result lacks an id; the irregularities of the data itself are under "What the data looks like"). The topics took 46 pages, the subfields 3, the others 1.
- **Recomputed by a second snippet** (not the reader's code) from the saved files: all 51 hashes and sizes equal those in the report (0 mismatches); the counts and unique ids above; **the hierarchy is complete and consistent** (every field names a domain that is in the list, every subfield a field and a domain, every topic a subfield, a field and a domain, and each topic's field and domain
  are those of its subfield: 0 problems); every record at every level has a name and a description. The report names the reader by hash and it equals the reader's file.
- **What the data looks like (for Increment D):** the ids are `https://openalex.org/domains/N`, `/fields/N`, `/subfields/N` and `https://openalex.org/TN` for a topic; the parent of a record is an object that carries its `id`; there are 4 domains (Life Sciences, Social Sciences, Physical Sciences, Health Sciences). **Two things the builder must handle:**
  the name "Social Sciences" is both a domain and a field (the only name that occurs at two levels, so the slugs of two shelves would clash), and two subfields have no topic (Bioengineering and Radiological and Ultrasound Technology, which would be shelves with no children); topics per subfield run from 1 to 197. **The scope sentence:** all 4,798 records have a description, but the first-sentence
  rule of the plan needs a decision in Increment D: topic descriptions are 192 to 828 characters (median 378) and begin like "This cluster of papers covers…", and 282 of the descriptions (those of the higher levels, such as "academic disciplines concerned with…") begin with a lowercase letter and are not full sentences.
- **The record of the lists (criterion 3), in full, since the files are outside the repository:** retrieved **2026-11-14**; the address of each list is `https://api.openalex.org/<level>` (`domains`, `fields`, `subfields`, `topics`), asked for with `per_page=100&page=N&select=<fields>` as in the reader's `SELECT`; the version or date the source gives is the `updated_date` of its records, from **2026-10-05T15:26:57 to 2026-11-14T03:01:33** (no separate version number is given).
  By list: domains 4 records, 1 file, 2,458 bytes; fields 26, 1 file, 13,216 bytes; subfields 252, 3 files, 145,997 bytes; topics 4,516, 46 files, 4,254,325 bytes; all 51 files 4,415,996 bytes. **The report** (`openalex-read-report.json`, which holds the URL, status, size, sha256, count and seconds of every file) has sha256 `d8eac2eb8186881d736cf8b8125073a23202638be3dd74c25ab7114427da5685`.
  **The manifest**, which Increment D takes as the sha256 of the OpenAlex source in the snapshot: the text of 51 lines `<file name> <sha256 of that file>` (one space between; the names `domains-001.json`, `fields-001.json`, `subfields-001.json` to `subfields-003.json` and `topics-001.json` to `topics-046.json`), sorted by file name, each line ending in one newline, encoded as UTF-8; its sha256 is
  `e3da2475a126452d8e8605ddcc8adda092a12f18c23160b27ef7365710a61614` (recomputed by a second snippet from the report, which holds the 51 file hashes; the report and the files are the two records of each hash). **The reader that ran:** `d504b7eaccb63f827d56e9134223af89276b4986b8b92df9cedc293f05b6be36`; its tests `4bb260df9241ae5c0da036acca216f15d9c75dd02c01451fa0f5c5b0858cabef`; its breaks `df72e0c661aed26dd7128db23647089e38feb11e6ca22456e8683bb7527c9202`.
  The retrieval date to record in the snapshot is 2026-11-14.
- **Counted for Increment D (the reviewer asked for it):** of 4,798 records, **12 names have a character outside ASCII** (a curly apostrophe, a dash or a Greek letter, e.g. "TGF-β signaling in diseases"), **none holds a control, format or separator character**, the longest name has 83 characters (the checker allows 200), no name repeats within a level, and the slugs by a plain rule (fold to ASCII, lowercase, runs of other characters to one hyphen) are all non-empty and at most 120 characters,
  with **one collision, "social-sciences" (the domain and the field)**. No description holds a control, format or separator character. **290 descriptions are longer than 500 characters** (the longest is under 829), so a whole description would not pass the checker's limit of 500 for a scope sentence; the **first sentence by a plain rule** (up to the first full stop followed by a space and a capital) is at most 476 characters (median 198), so the plan's first-sentence rule fits the limit on these data. The rule still has to be written exactly in Increment D (what ends a sentence; what to do for a higher-level description that is a lowercase phrase; the fallback of the fixed sentence if no sentence fits 500 characters or the text holds an odd character),
  and the owner reads the result there. The checker accepts real ids (`https://openalex.org/subfields/3106` is 35 characters of the allowed set) and has no rule that a subfield must have children, so the two empty subfields pass; D only records them.
- **What the owner was told before the run.** In the message before "run it" I described the read in words (the host, about 51 plain GETs one at a time, a fixed header with no key, email or cookie, the limits, replies saved unchanged in a private folder), and the reader's `check` mode printed the four first-page addresses and the limits (I ran it before the security review and again just before the read); I did not paste those addresses into a message to the owner. **The reader was then changed after the owner's "run it"** (the security fixes, in a message to the owner that listed each fix and said the read was held until the second check of them); the addresses, the `select` fields, the headers and the pace did not change, and the code that ran is the reader whose hash is above, which is also the hash in the report.
- **Tests and breaks:** 54 tests of the reader against a fake server on 127.0.0.1 (a good server and a hostile one: redirects, error statuses, wrong or compressed or oversized replies, a reply with no length that never ends, slow, trickled and silent servers, bad JSON and wrong shapes, a count that lies or changes, an interrupt, a changed trust store, a folder swapped for a link, a half-written file),
  and **59 deliberate breaks, all caught** on a clean baseline, the reader restored byte for byte each time. **I wrote the reader before its tests**, so the tests were not seen to fail first; the breaks are the evidence that they can fail. **My first run of the breaks was partly invalid:** the break that let a reply choose the file name wrote a stray file into the temporary folder of the machine, which made one test fail on every later break, so
  those counted as caught for the wrong reason. I found it from a break that was missed on the rerun, removed the stray file, made the test use a folder of its own, and reran all of them; the counts above are from the clean run. The second run found one real gap (no test for a folder of another owner), now covered.
- **Review (step 4):** the `reviewer` agent read the script and this Result, not the saved lists; see the Review record. **Known limits left as they are**, because the read is done and a change would change the reader's recorded hash: `main` catches only the reader's own refusals, so a full disk during a run would end in a traceback after the partial report is written (nothing is overwritten and a half-written file is removed, but a rerun needs a new folder); a link higher up the folder path is followed (the path is the owner's own);
  only two variables of the trust store are checked; the reader was never run against a misbehaving real server, only fake ones; and the real certificate chain was accepted by the default checking and not examined. `wb run code-work check` is to be run before the commit. No push.
- **For the commit:** this plan only (the reader, its tests and its breaks and the saved files are outside the repository and are cited by hash), with the trailer `Plan: 2026-11-14-build-the-shelf-schema#B`; the owner's word is awaited.
