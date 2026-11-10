# A query prefix for embedding models

Status: Completed
Created: 2026-11-09
Candidate: none (an improvement that follows from Increment E of the completed plan 2026-11-09-search-the-neutral-descriptions-by-meaning, whose Result found that the models the owner chose from are made to take an instruction before a query and the engine sends none)
Specs: docs/specs/models.md, docs/specs/card.md

## Goal

An embedding entry of the owner's config can say what text goes in front of a query, and what text goes in front of a stored text, when
the engine turns them into vectors. Some embedding models are made to take such text: `qwen3-embedding` is trained for
`Instruct: <a task>` and a line `Query: <the query>` before a query and for a plain document; others use a short prefix for each side.
The engine sends none today, so the model the library keeps, `qwen3-embedding:4b`, runs without its best form.

The plan is done when the config can hold a `query_prefix` and a `document_prefix` for an embedding entry; the engine puts the right
one in front of the right kind of text and records the document prefix with the vectors it makes, so that vectors made one way are
never searched with the other; and the owner has seen what the same eight searches of Increment E return for `qwen3-embedding:4b`
with an instruction before the query, next to what they returned without one, and has decided what the config keeps.

## Scope

- Two optional keys of an embedding entry, `query_prefix` and `document_prefix`: text of at most 400 characters, printable
  characters and line breaks only, refused on a chat entry.
- `models.embed` takes the kind of text it is given (a query or a document) and puts the entry's prefix for that kind in front of every
  text before it is checked for size and sent. With no prefix set, what is sent is what is sent today.
- The file of vectors records a hash of the document prefix it was made with (a new format of the file); a build does not reuse
  vectors made with another prefix, and a search refuses a file made with another one.
- `card-vectors` makes documents and `card-search --meaning` makes a query; the reply of a search says whether a query prefix was used.
- A live comparison for `qwen3-embedding:4b` of the eight searches of Increment E with an instruction before the query against the
  ranks recorded without one, with at most two wordings, and the owner's decision about what the config keeps.
- The specs and the README.

## Non-goals

- Trying `bge-m3`, `mxbai-embed-large` or `nomic-embed-text` with their own prefixes. The keys are general, and the live comparison is
  for the model the library keeps.
- A prefix for a chat entry, a different prefix for each kind of search, and a prefix chosen by the engine or by a model: the owner
  writes it in the config.
- Choosing the best wording by measurement. The comparison shows what two wordings return for eight searches; it measures no accuracy.
  The trial of the candidate `cross-field-discovery#cross-field-trial` is where search is compared on problems with known answers.
- Embedding the other two neutral fields, a second model for ranking, and any change to a card.
- Editing the owner's config file (the owner does that).

## Assumptions and constraints

- The format that `qwen3-embedding` is trained on is an instruction line and a query line: `Instruct: <task>` then a line break and
  `Query: <the query>`, with documents embedded without an instruction. This was read in summaries of the model's card in a web search
  on 2026-11-09 and was not checked at the source or against the card itself; the live comparison is what shows whether it helps, so a
  wrong assumption costs a comparison and not the library. A short prefix for `mxbai-embed-large` that the same search suggested is not
  used by this plan.
- A prefix is text from the owner's own config. It is sent to the owner's server on standard input as part of the text, as every text
  is, and it never reaches the command line.
- The longest stored text is 500 characters and a query is at most 2000, so a prefix of at most 400 characters keeps every text well
  inside the 32768 bytes the bridge takes and the 8192 tokens of `qwen3-embedding:4b`. The size is checked on the text with its
  prefix.
- The vectors of the library today are in the format 1 file, made without a prefix. The new format means the file is replaced the
  first time `card-vectors` is run after Increment B: 230 texts to the owner's server, about half a minute for `qwen3-embedding:4b`.
  Until then a search is refused with the command to run.
- A document prefix changes the vectors of the stored texts, so it is recorded; a query prefix changes only the query, so it needs no
  rebuild and is not recorded in the file.
- Tests use the fake bridge, which records the texts it is sent. The live comparison uses the owner's server and the owner's word.

## Completion criteria

1. An embedding entry accepts `query_prefix` and `document_prefix` as text of 1 to 400 printable characters (line breaks allowed) and
   refuses anything else, and a chat entry refuses both.
2. `models.embed` puts the prefix for the kind of text in front of every text it sends, checks the size of the text with its prefix,
   and sends exactly what it sent before when the entry has no prefix.
3. The file of vectors records a hash of the document prefix; `card-vectors` makes documents with the document prefix and keeps a
   vector only if it was made with the same one; a search sends its query with the query prefix and refuses a file made with another
   document prefix; a file of the earlier format is refused by a search and replaced by a build.
4. The owner has seen the ranks of the books expected for the eight searches for `qwen3-embedding:4b` with an instruction before the
   query, next to the ranks recorded without one, and has decided what the config keeps; the file of vectors on disk was made with the
   prefix settings the config keeps.
5. `wb run code-work check` finds no problems, and the specs and the README state what is built.

## Increments

### Increment A — Prefixes for the texts the engine embeds

**Outcome:** an embedding entry can carry a `query_prefix` and a `document_prefix`, and `models.embed` puts the right one in front of
each text it sends.
**Dependencies:** none.
**Affected areas:** `engine/kb/models.py`, `engine/tests/test_models.py`, `docs/specs/models.md` ("The embedding model"),
`engine/README.md` ("Calling a model").
**Steps:**
1. Write the tests first, with the fake bridge recording the texts it is sent: an embedding entry accepts each prefix alone and both;
   text of 400 characters, with line breaks and non-ASCII letters, is accepted; an empty text, text of 401 characters, a character
   that is not printable (a control character other than a line break, a lone surrogate, a hidden or look-alike control such as a
   zero-width character or a right-to-left mark) and a value that is not text are refused; a chat entry with either key is refused;
   `embed` with the kind `query` sends the query prefix followed by the text, with the kind `document` sends the document prefix, and
   with no prefix set sends the text unchanged; the kind defaults to `document`; a kind that is neither is refused before anything is
   sent; the size limit applies to the text with its prefix (a text that fits alone and not with the prefix is refused by its place);
   the prefix is never an argument of the bridge command; the vectors returned are those the fake bridge makes from the prefixed text.
2. Add the two keys to the accepted keys of an entry, with their checks, for the kind `embedding` only. Add the argument `kind` to
   `models.embed` (`"document"` by default, or `"query"`), and put the prefix in front of each text after the text itself is checked
   and before the size of the text is.
3. Update `models.md` and the README: what the keys are, that the prefix is for the owner to write, the format
   `Instruct: ...` + line break + `Query: ...` that one model is trained for (as an example, marked as not checked at its source), and
   that a document prefix needs the vectors to be made again.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_models engine.tests.test_setup`; deliberate breaks,
each from a green baseline: the query prefix put on a document, the document prefix put on a query, both prefixes put on both, the
prefix put on after the size is checked, a chat entry accepting a prefix, a control character or a zero-width character accepted,
a prefix of 401 characters accepted, an empty prefix accepted, a kind that is neither accepted, the prefix passed on the command
line; `wb run code-work check`. No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-query-prefix-for-embedding-models#A`.

### Increment B — Record the document prefix with the vectors and use the prefixes in the build and the search

**Outcome:** `card-vectors` makes documents with the document prefix and records it, and `card-search --meaning` sends its query with the
query prefix; vectors made one way are never used with the other.
**Dependencies:** A.
**Affected areas:** `engine/kb/vectors.py`, `engine/tests/test_vectors.py`, `docs/specs/card.md` ("Where it is stored" and "Searching
the catalog"), `engine/README.md` ("Searching the cards").
**Steps:**
1. Write the tests first, with the fake bridge: a build sends each text with the document prefix, and a search sends its query with the
   query prefix, never the other way; the file records the hash of the document prefix (that of an empty text when there is none) in
   its meta table; a build keeps a vector only if the file was made with the same document prefix, and replaces the file otherwise
   (counted as `replaced`, nothing reused); a search refuses a file made with another document prefix, and says which command to run;
   a change of the query prefix alone needs no rebuild and changes only the query that is sent; with no prefix set, a build and a
   search send what they sent before; a file of the earlier format is refused by a search and replaced by a build; the stored text
   hash still covers the text without any prefix, so a text that changed is still found stale; the reply of a search says whether a
   query prefix was used (`query_prefix`, true or false) and never holds the prefix; a meta table with a document-prefix hash that is
   not a hash is refused.
2. Raise the format of the file to 2 and add the document-prefix hash to its meta table; have `build` call `models.embed` with the
   kind `document` and `search` with the kind `query`; compare the hash in `check_entry`, in the reuse of old vectors and in the
   checks of a search.
3. Update the card spec and the README: the new format and what it means (the first `card-vectors` after this change replaces the file),
   what the prefixes do, and that the reply of a search says whether a query prefix was used.
4. Before the increment is committed, name to the owner what the change exposes (text from the config reaching the bridge on standard
   input as part of every text, and a new field in the file of vectors that a search compares), ask once whether to run a security
   review of it with the installed module, and record the owner's answer in the Result. If the owner asks for one, it runs on the
   committed code and its findings are handled as the earlier plan's were.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_models engine.tests.test_catalog`;
deliberate breaks, each from a green baseline: the document prefix not applied in a build, the query prefix applied in a build, the
document prefix applied to a query, the hash not recorded, the hash not compared in a build, the hash not compared in a search, an
old vector kept for a new prefix, the stored text hash made over the prefixed text, the format not raised, the prefix itself shown in the
reply; the owner's answer about a security review is recorded in the Result; `wb run code-work check`. No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-query-prefix-for-embedding-models#B`.

### Increment C — Try an instruction before the query for the model the library keeps

**Outcome:** the owner has seen what the eight searches of Increment E return for `qwen3-embedding:4b` with an instruction before the
query, next to the ranks recorded without one, and has decided what the config keeps.
**Dependencies:** B, the owner's edit of the config, and the owner's word to run.
**Affected areas:** the index root (`vectors.sqlite`); this plan's Result. No tracked code. The owner edits the config; I never do.
**Steps:**
1. Propose the wording and agree it with the owner: `qwen3-embedding` takes `Instruct: ` and a task, a line break, and `Query: ` before
   the query. A task for these searches: `Given a description of a problem or of how something works, find descriptions of methods or
   ideas that solve the same problem or work the same way, in any field`. The owner adds it as `query_prefix` of `embed-qwen` (the
   value ends after `Query: `, and a line break is written `\n` in the config) and tells me; I check that the config loads
   (`python3 -m kb models` makes no call).
2. Run `python3 -m kb card-vectors`. The file on disk is of the earlier format and is replaced: 230 texts go to the owner's server, in
   the clear, and nothing is reused; say so before the run. Run it again: it sends nothing.
3. Run the eight searches of Increment E (the same sentences and the same script), which sends the eight query sentences, each with
   the prefix, to the owner's server; say so before the run. Record the first five books of each and the rank of the books I expected,
   next to the ranks recorded for `qwen3-embedding:4b` without a prefix in Increment E of the earlier plan, and say plainly what could not
   be concluded (eight searches, my own idea of the right books).
4. If the owner wants, try a second wording: the owner edits `query_prefix`, and I run the eight searches again. This needs no rebuild.
   At most two wordings are tried.
5. Recommend, and record the owner's decision on what the config keeps (a wording, or none). If it is none, the config has no prefix,
   and the file of vectors on disk, made without a document prefix, still matches it. No accuracy is claimed.
**Verification:** the file of vectors on disk names `qwen3-embedding:4b` and the hash of the document prefix the config has; the second
build sends no text; every result of a search has the markers and a citation (the script asserts it); a search of the prefixed model
reports that a query prefix was used; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-query-prefix-for-embedding-models#C`, holding the Result and the
owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the tests of the modules
that changed (`test_models`, `test_vectors`, `test_catalog`) once, and `wb run code-work check`. A wider run is not named: no increment
changes a module outside the model and vector paths. What could break outside the tested area is any caller of `models.embed`, whose
new argument has a default that keeps today's behaviour, and the owner's existing file of vectors, which Increment B makes unusable
until `card-vectors` is run once; the plan says so before it happens.

## Risks and sensitive actions

- **The existing file of vectors stops working.** The new format of the file means a search is refused until `card-vectors` is run
  once (230 texts to the owner's server, about half a minute for `qwen3-embedding:4b`). The refusal names the command.
- **A prefix can make search worse.** A wrong or badly worded instruction may rank books lower. The comparison of Increment C shows it
  against the ranks recorded without one, and the prefix is optional: with none, behaviour is today's.
- **Text leaves the machine in C.** The 230 texts and the eight queries, with the prefix on the queries, go in the clear to the owner's
  server on the owner's network, as every card call does, and the owner is told before each run.
- **The prefix is config text.** It is the owner's own, it goes on standard input as part of the text and never to the command line,
  and it is limited in length and in the characters it may hold, so it cannot hide text or break a line of the bridge's input.
- **Security review.** The change adds a new input to a surface the security review of the earlier plan covered (a subprocess, the
  parsing of a model's reply, and a file in the index root): text from the owner's config now reaches the bridge, on standard input,
  and the file gains a field that is checked as before. Increment B ends with a checkpoint at which the owner is asked once whether to
  run a security review of this config-to-bridge text and of the changed file, and the answer is recorded. A review runs only if the
  owner asks.

## Review record

- **Reviewer:** the second model of the review engine (`gpt-5.6-terra`), asked by the owner. Round 1 of 3; verdict `changes_needed`;
  one finding, decided.
- **Applied:** R1-F1 (major): the change adds a new input (config text to the bridge, and a field in the file of vectors) to a surface
  that the earlier security review covered, so the plan now has an explicit checkpoint at the end of Increment B that asks the owner
  once whether to run a security review and records the answer.
- **Rejected:** none.
- **Left for the owner:** a second round was not asked for.

## Deferred work

- Trying the prefixes of `mxbai-embed-large`, `nomic-embed-text` and `bge-m3` (which takes none), if the library ever uses one of them.
- A separate prefix for different kinds of search, once there is a second kind (`problem-search` in the roadmap would be one).
- A comparison of wordings on problems with known answers (the cross-field trial).
- The other items left over from the earlier plan: the fixed-name gap in `catalog.rebuild`, caps on reading the files, embedding
  `needs` and `limits`, the roadmap's out-of-date "Current state", and the owner's unlabelled calibration items of Increment A.

## Result

### Increment A — Prefixes for the texts the engine embeds (done)

- **What was built** (`engine/kb/models.py`): an embedding entry may have `query_prefix` and `document_prefix`, each text of 1 to 400
  characters that are printable or a line break (`_prefix_ok`: `str.isprintable` plus `\n`); a chat entry refuses both, and the listing
  does not show them. `models.embed` has a new last argument `kind` (`"document"` by default, or `"query"`; anything else is refused
  before anything is sent). It puts the entry's prefix for the kind in front of each text after the raw text is checked (text, not
  blank) and before the size is checked, so the size limit applies to the prefixed text and the vector is made from it; an entry with
  no prefix for the kind sends the text as before. The prefix goes in the JSON on standard input and never in the command. The models
  spec and the README say what is built.
- **Tests first**, and seen to fail (21 errors and a failure before any code; two refusal tests passed at first only because the keys
  were unknown and were shown to bite by the breaks). Then `python3 -W error::ResourceWarning -m unittest engine.tests.test_models
  engine.tests.test_setup engine.tests.test_vectors` gave 282 tests, OK; `wb run code-work check` found no problems. The plan names the
  first two; `test_vectors` was added because the build and the search call `embed`. No call was made to the owner's server (a fake
  bridge answers and records the texts it is sent).
- **Deliberate breaks**, each from green: 16 (the query prefix put on a document, the document prefix put on a query, both on both,
  the prefix put on after the size is checked, the prefix not sent, a chat entry accepting a prefix, a control character, a
  zero-width character, a prefix of 401 characters, an empty prefix, a value that is not text, a kind that is neither, the kind not
  checked first, the default kind a query, the prefix passed on the command line, a prefix shown in the listing) were each caught.
- **Review.** The read-only `reviewer` agent, no blocking finding. Applied: (1) the README said "nothing in the engine uses these keys
  yet", which was false, because `build` and `search` call `embed` with the default kind, so a `document_prefix` in the config would
  be put in front of a search's query too and the file of vectors does not record it; the README and the spec now say "do not set
  either prefix yet" until Increment B; (2) "nothing hidden" claimed more than `isprintable` checks (it still allows combining marks,
  variation selectors, fillers such as U+3164 and the braille blank, and look-alike letters), so the docstring, the README and the spec
  now say what is refused and that the check does not make the text sure to be what it looks like. The plan's Risks section says a
  prefix "cannot hide text", which overstates this; the approved text is not changed, and the limit is stated here and in the docs.
  Not applied: refusing combining marks and the fillers (combining marks are in text of many languages, and the prefix is the owner's
  own text sent to the owner's server). Noted for Increment B: the document-prefix hash must cover the exact string, since no
  normalization is applied, and a `str` subclass with its own methods could make `embed` raise a different error, which a JSON config
  value cannot be. The reviewer ran nothing and read no bridge source.
- **Not asked yet:** the question about a security review comes at the end of Increment B, as the plan says. (Committed as `6204014`.)

### Increment B — Record the document prefix with the vectors and use the prefixes in the build and the search (done)

- **What was built** (`engine/kb/vectors.py`): the file of vectors is of format 2 and its meta table has a new key,
  `document_prefix_sha256`, the SHA-256 of the entry's document prefix exactly as written (no normalization), that of an empty text
  if it has none (`prefix_hash`). `_meta` requires it to be 64 lowercase hex digits; `check_entry` refuses a file whose hash differs
  from the entry's, with the command to run, so a search is refused before anything is sent, and `build` (through `_old_rows`) does not
  reuse any vector of such a file and replaces it (`replaced`). `build` embeds each stored text with `kind="document"` and `search`
  embeds its query with `kind="query"`. The stored text hash still covers the text alone, so a changed text is found stale as before.
  The reply of a search has a new key, `query_prefix`, true if the entry has a query prefix (which was put in front of the query) and
  never the prefix itself. A change of the query prefix alone needs no rebuild. A file of the earlier format is refused by a search
  (the command to run is named) and replaced by the first build, which sends every text again. The card spec, the models spec and the
  README say what is built, and the earlier README sentence "do not set either prefix yet" is gone.
- **Tests first** (24 failures and 2 errors against the code of Increment A, among them the query sent with the document prefix, no hash
  in the meta table and the old format accepted), then `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors
  engine.tests.test_models engine.tests.test_catalog` gave 353 tests, OK; `wb run code-work check` found no problems. Two existing
  tests were changed for the new format number. No call was made to the owner's server (a fake bridge with chosen vectors answers).
- **Deliberate breaks**, each from green: 10 (the build using the query kind, the search using the document kind, the hash not
  recorded, the hash not compared, the stored text hash made over the prefixed text, the format not raised, the prefix shown in the
  reply, the flag always true, the prefix hash normalised, the stored hash not checked to be a hash). Nine were caught. The last is not
  caught and is redundant: a stored value that is not a hash can never equal the entry's hash, so the comparison refuses it first.
  A test was added for the format number (the older-format tests would have passed even if it were not raised).
- **Review.** The read-only `reviewer` agent, no blocking finding: it found no path in which a vector made with one document prefix is
  kept, searched or ranked with another, and none in which a query gets the document prefix or a stored text the query prefix. Applied
  (all wording): the module docstring, the `build` docstring and the first sentence of the README's vectors bullet did not mention the
  document prefix; the README's list of what a search refuses left it out; a test was named as a refusal but tests that a long text
  fits (renamed); and the known limits did not say that someone who can write the file can set the hash of the document prefix to
  the config's value. Not applied: the reason a file was replaced is not printed (the counts say `replaced`, and the README says what
  makes a file unusable). The reviewer ran nothing and did not read the fake-bridge helpers.
- **Security review (step 4).** Asked once of the owner, with the surface named: text from the config reaching the bridge on stdin as
  part of every text, and a new field in the vector file that a search compares. My recommendation was no (the new input is the
  owner's own config text, sent only to the owner's server, and checked as before). The owner's answer: **no**. No security review was
  run for this surface. (Committed as `0864bc8`.)

### Increment C — Try an instruction before the query for the model the library keeps (done)

- **Wording** (agreed with the owner, who added it to the config; I did not write the config): `query_prefix` of `embed-qwen` is
  `Instruct: Given a description of a problem or of how something works, find descriptions of methods or ideas that solve the same
  problem or work the same way, in any field`, a line break, and `Query: ` (value ends after `Query: `, 177 characters). No
  `document_prefix`. `python3 -m kb models` loaded the config and made no call. Only this one wording was tried.
- **Build** (the owner said yes after being told that 230 texts go to the server `ned`, in the clear): `python3 -m kb card-vectors`
  gave `made 230, kept 0, texts_sent 230, replaced true` (the file was of format 1); run again, `kept 230, made 0, texts_sent 0,
  replaced false`. The file's meta table, read after the build: format 2, model `qwen3-embedding:4b`, dimension 2560,
  `document_prefix_sha256` e3b0c442…b855 (the SHA-256 of an empty text, as the config has no document prefix).
- **Eight searches** (the owner said yes after being told that the eight query sentences go to `ned`, each with the prefix): the same
  sentences and script as Increment E of the earlier plan. The script asserted the markers and a citation on every result; the reply
  said `query_prefix: true`, 0 stale, 0 without a vector, 78 cards searched. Rank of the books I expected, without a prefix (from the
  earlier run, same 230 texts and model) and with this prefix:
  1 Bloom filter 1 → 1; 2 DeepStack 3 → 2, Imperfect-Information 5 → 4; 3 Simulated annealing 1 → 1, Genetic algorithm 5 → 2, DeepCAD
  19 → 15; 4 Amdahl 5 → 2, Message Passing 23 → 10, OpenMP 1 → 1, Horovod 3 → 4, ZeRO 11 → 6, Megatron 10 → 8; 5 Simulated annealing
  1 → 1; 6 Monte Carlo tree search 9 → 4; 7 Learned Index 25 → 5; 8 Dynamic programming 1 → 1, Fast Fourier 13 → 11, FlashAttention
  16 → 3. Of 18 books, 12 ranked higher, 5 the same and 1 lower (Horovod, 3 → 4).
- **What cannot be concluded:** eight searches, books chosen by me, all within the library's 78 cards, several searches with more than
  one right book. This is not a measure of accuracy and says nothing about other searches; scores are not compared, only ranks. In
  search 7 the top five are still mostly unrelated books (Learned Index is fifth).
- **Owner's decision:** the owner took my recommendation: the config keeps this wording as the query prefix of `embed-qwen`. No
  second wording was tried. Verified as run: the file names `qwen3-embedding:4b` and the hash of the document prefix the config has;
  the second build sent no text; every result had the markers and a citation; the search reported that a query prefix was used.
