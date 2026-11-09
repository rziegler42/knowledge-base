# Search the neutral descriptions by meaning

Status: Proposed
Created: 2026-11-09
Candidate: cross-field-discovery#meaning-search
Specs: docs/specs/card.md, docs/specs/models.md

## Goal

An agent can search the library by meaning. Three of the five neutral fields of each card (problem, approach and provides; the
owner decided on 2026-11-09, on the figures of Increment A, to leave out needs and limits) are
turned into vectors by an embedding model that the owner lists in the config, and `card-search` with a new `--meaning` option returns
books ranked by how close one of those fields of their card is to the query. A result has the same citation, the same facts about how complete
the source is, the same marks of the grounding and the same untrusted-text markers as a keyword result. The vectors can be rebuilt
from the cards alone, each is marked with the model that made it and with the hash of the text it was made from, and a vector that
is stale or from another model is refused, never used.

The plan is done when the owner has the measurement of how accurate the neutral descriptions are (the owner decided on 2026-11-09
that this comes before search by meaning is built on them), the engine has the embedding call, the store and the search, a live build
over the library has been made, and the owner has seen what a few searches return and decided what to do next.

## Scope

- A blind sample of the neutral sentences of the current cards of the library, labelled as supported, inference or unsupported, with
  a calibration subset for the owner, reported by field and by book, and a stop for the owner's decision before anything is built.
- An embedding entry in the registry of the config (a `kind` of `embedding`), a kind of work for it, and a call in the engine to the
  bridge's existing `embed` command (`wb run ask-ollama embed`), with batches that stay inside the bridge's limits.
- A store of vectors in its own file in the index root (`vectors.sqlite`), built from the cards, marked with the model and the
  dimension, one vector for each of the three searched fields (problem, approach, provides) of each card, kept when the text it
  came from has not changed.
- A command that builds the store, and the search by meaning in `card-search`: the query is embedded by the same model, the closeness
  is a cosine, a card is ranked by its closest field, and the result says which field matched.
- A live build over the library with the owner's embedding model and a few searches whose results are shown to the owner.
- The spec text (`docs/specs/card.md`, "Searching the catalog"; `docs/specs/models.md`, "The embedding model") and `engine/README.md`.

## Non-goals

- Themes, search over the full text by meaning, a cloud embedding service, and ranking by anything but closeness (all named out of
  scope by the candidate).
- Embedding the summary side of a card (the summary, uses, topics, key ideas), and embedding the neutral fields `needs` and
  `limits`: the sample of Increment A found 14% and 7% of their sentences supported by the book. Only problem, approach and provides
  are embedded. Adding the other two later is a change of one constant and a rebuild.
- Choosing an embedding model by measurement. The owner lists the models; the plan does not decide which is best. Increment E may be
  repeated for each embedding model the owner has listed, and then shows, for the same eight searches, what each returns, so that the
  owner can see the differences before choosing; it measures no accuracy and ranks no model. The trial of the candidate
  `cross-field-discovery#cross-field-trial` is where search is compared against problems with known answers.
- A vector index (approximate nearest neighbour) or a new dependency. The library has about eighty books and three searched fields each, so the
  closeness is computed in plain Python over every vector.
- Posing a problem as sub-problems and setting aside results from the problem's own field (`cross-field-discovery#problem-search`).
- Any change to a card, to how it is made, or to the keyword search. Editing the owner's config file (the owner does that).
- Shelves and the guest rule of `card.md`: the library has one shelf today.

## Assumptions and constraints

- The bridge `ask-ollama` already has `embed` (contract 1): one JSON object `{"texts": [...]}` on standard input, and a reply
  `{"ok": true, "model", "dimension", "vectors", "usage"}` or a failure object. `wb run ask-ollama check` lists two embedding models
  on the owner's server, `nomic-embed-text` (context 2048) and `bge-m3` (context 8192, multilingual). The engine calls the bridge as
  `models.py` calls `ask`: as a separate program, with an argument list and no shell. Increment B reads the bridge's limits
  (`MAX_TEXTS`, `MAX_TEXT`, `MAX_INPUT`) from the helper and stays inside them.
- Text sent to the embedding model (the three searched fields of cards, and the query) goes to the owner's server over plain HTTP on the
  owner's network, in the clear, as every card call does today. Nothing leaves the owner's network.
- The 79 cards of the catalog are of two forms. A neutral field of a card made in the grounded-sentence form (generation 3, nine
  books) is a few sentences; in the earlier form it is a short text. Both are plain text in the card's model part, as
  `catalog._fields` reads them. A card with no model part (a card from the metadata) has no neutral field and no vector.
- The candidate's prerequisite, `cross-field-discovery#neutral-cards-for-the-library`, is complete: the plan
  `2026-11-08-cards-for-the-library-one-model-at-a-time` is `Completed` and its Result records 79 cards in 80 books. The sentence
  of the roadmap that says twelve books have a card is out of date and is not what this plan relies on. The plan does not make
  cards.
- A vector is a list of finite numbers with a positive norm (a vector of zeros has no direction, and its cosine is undefined). The
  store keeps it as 32-bit floats; a vector with a non-finite number, a zero norm, a wrong length or a length that differs from the
  dimension in the config entry and in the store's meta is refused, whether it came from the bridge or from the store.
- A model that differs by name or by dimension from the one in the store's meta makes the store foreign. The plan treats a change
  of model as a rebuild, not as a mix: vectors of two models are never compared, as `models.md` says.
- Tests use a fake bridge (a script that answers like `embed`), as the tests of `ask` do. The live build and searches use the
  owner's server and the owner's word.
- Increment A sends passages of books to cloud models (Claude subagents that label), as the earlier samples did; the owner has said
  any shelf's books may go to a cloud model (`models.md`, "Privacy of what is sent"). It starts only on the owner's word.
- The owner edits the config (the entry and the kind of work). The engine and the agent never write the config file.
- This plan is narrower than the candidate's outcome in one place: the candidate says "the neutral descriptions"; the plan embeds
  each of three fields (problem, approach, provides) as its own vector (as `card.md` and `theme.md` say, "each is embedded
  separately") and ranks a book by its closest field. Whether one vector for the fields together would do better is not tested here.

## Completion criteria

1. The owner has the labelled sample of the neutral sentences, reported by field, by generation and by book, with the calibration
   agreement, and has decided
   (recorded in the Result) to go on.
2. `models.embed` calls the bridge's `embed`, checks the reply (a count equal to the texts, one dimension, finite numbers, a model
   named) and refuses anything else; the config refuses an embedding entry with a key that only a chat entry holds.
3. `card-vectors` builds the store from the cards alone, twice with the same result, and a card whose neutral text changed is
   embedded again while the others are kept.
4. `card-search QUERY --meaning` returns results in the shape of a keyword result, with the closeness as the score and the field that
   matched, and refuses a store made by another model, a store of another format, and a query that is empty; a vector whose text no
   longer matches its card is not used and is counted in the reply.
5. A live build over the library made a vector for each searched field (problem, approach, provides) of each card that has one, with
   each embedding model the owner chose to try; the owner has seen the results of the same eight searches for each, and recorded a
   decision, including which model the library keeps.
6. `wb run code-work check` finds no problems, and the specs and the README state what is built.
7. The findings F1, F2 and F5 of the security review of commit `4e93147` (the end of Increment D) are fixed, each with a regression
   test that failed before the fix, and a second look has found them fixed; the other findings (F3, F4, F6) are stated in the README
   as known limits.

## Increments

### Increment A — Measure the accuracy of the neutral descriptions of the library

**Outcome:** the owner knows, from a blind labelled sample, how much of what the neutral fields say is supported by the book, and
decides whether to build search on them. Nothing is built.
**Dependencies:** none. The owner's word to send passages to cloud labellers.
**Affected areas:** `engine/kb/cardsample.py` and its tests only if the tool cannot draw from the neutral fields alone (step 1); the
sample files outside the repository; this plan's Result.
**Steps:**
1. Read `card-sample` and `card-accuracy`. If the sample cannot be limited to the five neutral fields, add an option that does it (a
   small change with a test written first); otherwise draw a sample large enough that the neutral sentences in it are at least 120.
2. Draw a blind sample over every current card with `card-sample` (a seed recorded in the key), with a calibration subset of 15.
3. On the owner's word, label the sample with cloud subagents in batches that do not know which generation an item is from, with the
   rubric of the earlier samples (supported, inference, unsupported, skip). The labeller sees the top passages of the book only.
4. Report by field, by generation and by book: the shares supported, inference and unsupported, the share of cards that have at least one
   unsupported neutral sentence, and the number of items skipped. The calibration subset goes to the owner; the agreement
   (`card-agreement`) is reported when the owner has labelled it, and until then the report says the labels are a model's alone.
5. Record the figures in the Result and stop. Recommend, without a threshold the plan sets, whether to go on, to go on with the
   unsupported sentences named, or to stop. The decision is the owner's.
**Verification:** the numbers in the report are recomputed from the labelled file with `card-accuracy`; if step 1 changed code, the
tests of `cardsample` pass (`python3 -W error::ResourceWarning -m unittest engine.tests.test_cardsample`) and a deliberate break of the
new option is caught; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#A`, holding this
plan's Result (and the tool change, if any), and the owner's decision.

### Increment B — Call the embedding model from the engine

**Outcome:** the engine can turn a list of texts into vectors through the owner's embedding model, and refuses a reply that is not
exactly what was asked for.
**Dependencies:** A, with the owner's decision to go on.
**Affected areas:** `engine/kb/models.py`, `engine/tests/test_models.py`, `docs/specs/models.md` ("The embedding model"),
`engine/README.md` (the registry section).
**Steps:**
1. Write the tests first, with a fake bridge: an embedding entry is accepted (`kind` of `embedding`, a bridge, a server, a model, a
   `dimension` that is a whole number from 1 to the bridge's largest, an optional timeout) and refuses a missing or wrong
   `dimension`, `max_output` and `thinking`; a chat entry is unchanged and refuses `dimension`; the kind of work `card-embed` is optional
   and must name an embedding entry; a chat entry named for it, and an embedding entry named for a chat task, are refused.
2. Add `kind` to the keys of an entry, with `chat` the default, and the task `card-embed` to `OPTIONAL_TASKS`.
3. Add `embed(cfg, name, texts, launcher=None, root=None)`: it builds the argument list `wb run ask-ollama embed --server S --model M`
   (and `--timeout` when set), sends `{"texts": [...]}` and reads the reply object as `call` does. It checks that `ok` is true, that
   the count of vectors equals the count of texts, that all have one length that equals both the reply's `dimension` and the
   entry's `dimension`, that every number is finite and not a boolean, that no vector has a zero norm, and that the model is named;
   it returns the model, the dimension and the vectors. A failure object is raised as a
   refusal with the bridge's failure kind. Texts are split into batches within the bridge's limits, in order, and the batches are
   joined; a text that alone is over a limit is refused with its index, not cut.
4. Update the text of `models.md` ("The embedding model" and "Ways a model is called": the bridge command exists and the engine calls
   it) and the README's registry section.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_models` (and `engine.tests.test_setup` if the README
or the config check is touched); deliberate breaks, each from a green baseline: a reply with one vector too few, a vector with a
different length, a length that differs from the entry's `dimension`, a non-finite number, a zero vector, a boolean, a missing model
name, `ok` false, and a batch split that drops or repeats a text are all caught; `wb run code-work check`. No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#B`.

### Increment C — Store the vectors of the searched fields

**Outcome:** `python3 -m kb card-vectors` builds a file of vectors from the cards, marked with the model, and builds it again
cheaply when nothing changed.
**Dependencies:** B.
**Affected areas:** a new `engine/kb/vectors.py`, `engine/tests/test_vectors.py`, `engine/kb/__main__.py` (the command),
`docs/specs/card.md` ("Where it is stored"), `engine/README.md`.
**Steps:**
1. Write the tests first, with the fake bridge: the store is built from the cards of a fixture library; building twice makes the same
   rows; a card whose text of a searched field changed gets a new vector and the others keep theirs (the fake bridge counts the
   texts it was sent); a card with no model part, an empty searched field, and the fields `needs` and `limits` (never embedded),
   make no row; a store of another format number, a store with a
   table or trigger the engine did not put there, and a store whose model or dimension differs from the configured one, are refused
   as the catalog's checks refuse them; a half-built store is never left in place.
2. The file `vectors.sqlite` in the index root holds a `meta` table (format, the model as the bridge named it, the dimension, the
   date of the build) and a `vectors` table: the book, the version, the generation, the field (one of the three searched), the SHA-256 of the
   field's text, and the vector as 32-bit floats. It is built beside the old file and renamed into place under the writers' lock, as
   the catalog is, and it has mode 600. It reads the cards through `card.read`, so a card that fails its checks is left out and
   counted.
3. `card-vectors` reads the cards, keeps a row whose text hash and model match, sends the other texts through `models.embed` in
   batches, and prints the counts: cards, vectors kept, vectors made, cards left out, and texts sent. `--again` makes every vector
   again. It refuses when `card-embed` is not set or model work is off. Nothing but the text of the three searched fields is sent.
4. Update `card.md` ("Where it is stored": the vectors are a second derived file that can be thrown away and rebuilt) and the README.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_models`;
deliberate breaks, each from a green baseline: a vector stored for the wrong field, a text hash not checked, a foreign model accepted,
a half-built file left in place, a non-finite number stored, a kept row not reused (the fake bridge's count of texts shows it);
`wb run code-work check`. No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#C`.

### Increment D — Search by meaning

**Outcome:** `python3 -m kb card-search QUERY --meaning` ranks books by the closeness of the query to a searched field (problem, approach or provides) of their card
and returns what a keyword result returns.
**Dependencies:** C.
**Affected areas:** `engine/kb/vectors.py`, `engine/kb/catalog.py` (the building of one result, shared with the keyword search),
`engine/kb/__main__.py`, their tests, `docs/specs/card.md` ("Searching the catalog"), `engine/README.md`.
**Steps:**
1. Write the tests first, with the fake bridge giving vectors chosen by hand so that the expected order is known: a query closest
   to one card's field ranks that card first and names the field; a card is ranked by its closest field, once; the limit is kept;
   the score is the cosine; an empty query, a limit out of range, a store missing (the reply says to run `card-vectors`), a store
   of another model than the configured one, a query vector of another dimension, and a query vector of zeros are refused; a stored
   vector of zeros or of another length is left out and counted with the stale ones; a vector whose text hash differs from the
   card's field text now, and a card that has no vector, are left out of the ranking and counted in the reply (`stale` and
   `without_vector`), never used; a result has every key of a keyword result and the same markers; the result for the same card
   is the same as the keyword search's apart from the score and the matched field.
2. Move the building of one result (the checks against the stored card, the rendering between the markers) out of `catalog.search`
   into a function that both searches call, without changing the keyword search's output (its existing tests pass unchanged).
3. Add the search by meaning: embed the query through `models.embed`, read the vectors and the cards of the catalog in one read-only
   connection each, compute the cosine in plain Python, rank, and build the results. `--meaning` searches the three embedded fields only and
   refuses `--in`. The excerpt is the text of the field that matched.
4. Update `card.md` ("Searching the catalog": the search by meaning is built; the marks and the citation are those of a keyword
   result; the neutral side only) and the README.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_card engine.tests.test_models`;
deliberate breaks, each from a green baseline: ranking by the wrong sign, a stale vector used, a foreign model accepted, a zero vector ranked, a result
missing its markers or its citation, a limit not applied, a card returned twice; `wb run code-work check`. No call to the owner's
server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#D`.

### Increment D-A — Fix the findings of the security review of Increments B to D

**Outcome:** three findings of the security review of commit `4e93147` are fixed, each with a regression test that failed before the
fix: (F2) the file of vectors is built in a private temporary folder and not through a fixed name that a link could take the place
of; (F1) a damaged file of vectors is refused with the command to run and never ends in a raw SQLite error; (F5) text from the error
object of the bridge cannot carry the words of an untrusted-text marker into a refusal. The other findings are stated as known limits.
**Dependencies:** D.
**Affected areas:** `engine/kb/vectors.py`, `engine/kb/models.py` (`_why_failed`), `engine/tests/test_vectors.py`,
`engine/tests/test_models.py`, `engine/README.md`, this plan's Result.
**Steps:**
1. Write the tests first and see each fail for the right reason: (a) a link planted at the old fixed name `vectors.sqlite.new`, and at
   `vectors.sqlite.new-journal`, before and during a build (a test makes the timing certain by planting it after the leftover files
   are removed) is not followed: the file it leads to, an empty one made world-writable and a foreign SQLite file with a table of its
   own, is unchanged in content, mode and tables; the file of vectors is built and put in place; (b) the file is private from the
   moment it exists, and a folder or file left by a build that was killed is removed by the next build, under the lock, and nothing
   but such a leftover is removed; (c) a damaged file of vectors (the page that holds the `meta` table zeroed, a connection that raises
   a SQLite error on that table) is refused by `check_entry`, by `search` and by the command with a message that names `card-vectors`,
   and a build replaces it; (d) the error text of a bridge reply that holds the words of a marker is withheld in the refusal of
   `models.embed` and of `models.call`.
2. (F2) Build the file in a folder made by `tempfile.mkdtemp` inside the index root (mode 0700, a random name), under the lock; make the
   file private by its path inside that folder; put it in place with `os.replace`; remove the folder whatever happens. Before it
   makes a new folder the build removes, under the lock, the folders and files that an earlier killed build left (names of the
   pattern the build uses, real folders and files only, never a link's target).
3. (F1) Make `_meta` (and any other read of the file of vectors that is not already inside the checks of `connect`) turn a SQLite
   error into a refusal that names the command to run.
4. (F5) Make `_why_failed` pass the error and the detail of the bridge through `textutil.title`, and show a fixed text when the
   words of a marker are found.
5. State in the README the known limits: a person who can write the private file of vectors can put any vector under a correct
   text hash, and `card-vectors --again` makes every vector again from the cards (F4); a file of vectors or a catalog is read whole
   into memory, so its size is the bound (F3); the time limit of a build is for each batch and not for the whole build (F6).
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_models engine.tests.test_catalog`;
deliberate breaks, each from a green baseline: the old fixed name used, the file private only after it holds data, a leftover not
removed, a leftover removed that is not one, the folder left behind after a failure, a SQLite error left to escape from `_meta`, the
words of a marker shown from the bridge's error text; a second look by the read-only `reviewer` agent on the fix (it is given the
paths and the findings, and asked to try the planted-link case by reading and to say what it could not check); `wb run code-work check`.
No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#D-A`.

### Increment E — Build over the library and look at what it returns

**Outcome:** the library has vectors for its searched fields, and the owner has seen what a few searches by meaning return next to
what a keyword search returns, and decides what to do.
**Dependencies:** D-A, the owner's setting of one or more embedding entries and of `card-embed` in the config, and the owner's word to
run (and to switch to the next model).
**Affected areas:** the index root (`vectors.sqlite`); this plan's Result. No tracked code. The owner edits the config; I never do.
**Steps:**
1. Agree with the owner, once, the models to try (each an embedding entry of the config, with its section in the endpoint record) and a
   set of eight searches that is used for every model: the owner gives the queries, or agrees to eight that I propose, four written as
   a problem of one field and four as a plain description of a mechanism.
2. For each model in turn, with `card-embed` set by the owner to its entry: run `wb run ask-ollama check` to see that the model is
   listed, and `python3 -m kb card-vectors` over the library. The texts sent are the three searched fields of the current cards
   (about 240), to the owner's server; say so before each run. A change of model replaces the file of vectors and mixes nothing.
3. Run the build again: it makes no new vector.
4. Run the eight searches by meaning, and the same words as a keyword search on the neutral side. Record for each the first five
   books of each search with the field that matched.
5. Record for each model the counts of the build, its time, its dimension, any text refused, and a plain reading of the searches:
   which books surfaced that the keyword search did not, which keyword results were lost, and which results are from the same field
   as the query. After the last model, set side by side what each returned (which books every model returned, which only one) and say
   what could not be concluded. Two models listed by the owner are made to take an instruction before the query (`qwen3-embedding`)
   or a short prefix (`mxbai-embed-large`), and the engine sends none (see Deferred work), so they may do worse here than they
   could; this is said in the Result. No claim of how often search finds a transfer, and no ranking of the models, is made: that is
   the trial (`cross-field-discovery#cross-field-trial`).
6. Recommend, and record the owner's decision, including which model the library keeps. If the last model built is not the one the
   owner keeps, the owner sets `card-embed` to it and the library is built again with it, so that the file of vectors on disk is the
   chosen model's.
**Verification:** for each model, the second build makes no new vector; every search's results have a citation and the markers; the
counts of the build agree with the number of non-empty searched fields in the catalog; at the end, the file of vectors on disk
names the model the owner chose; `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#E`, holding the
Result and the owner's decision.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later increment changed its inputs. At the end, rerun the tests of the modules
that a later increment changed (`test_models`, `test_catalog`, `test_vectors`, `test_card`) once, and `wb run code-work check`. A wider
run (the whole suite) is not named: no increment changes a module outside the card and model paths. The one thing that could break
outside the tested area is `catalog.search`, because Increment D moves the building of a result; the keyword search's own tests run
unchanged in D and again at the end.

## Risks and sensitive actions

- **Text leaves the machine in A and E.** In A, passages of books and sentences of cards go to cloud labelling subagents (allowed by
  the owner, started on the owner's word). In E, for each model tried, the three searched fields and the queries go in the clear to the owner's server on the
  owner's network, as every card call does.
- **A vector that does not match its card.** A stale or foreign vector would rank a book by text it no longer has. The text hash,
  the model and the dimension are checked at every search, and a failure is a refusal or a counted omission.
- **The input of the store.** The reply of the embedding model is untrusted data: the engine checks its shape, its length, and that
  every number is finite, before it is stored, and a card's text reaches the model only as the text of a neutral field.
- **A query reaches the model.** An agent's query is sent to the embedding model; it is limited in length and is not run or
  believed.
- **Misleading ranking.** Closeness says nothing of accuracy: a neutral sentence that Increment A finds unsupported ranks like any
  other. The result says how many of a card's items were checked (the grounding counts), as a keyword result does.
- **Security review.** The change touches a subprocess (the bridge call), a parsing of untrusted model output and a file in the index
  root. The owner asked for a security review at the end of Increment D (commit `4e93147`); its findings are in the Result, and
  Increment D-A fixes the three worth a change now. A fix is new attack surface, so D-A has its own regression tests and a second look.

## Review record

- **Reviewer:** the second model of the review engine (`gpt-5.6-terra`), asked by the owner. Round 1 of 3; verdict `changes_needed`;
  four findings, all decided.
- **Applied:**
  - R1-F1 (major): the candidate's prerequisite is met, so no dependency was added; the plan now states that
    `neutral-cards-for-the-library` is complete and that the roadmap sentence about twelve books is out of date.
  - R1-F2 (major): an embedding entry now has a validated `dimension`, and every reply is checked against it, with tests.
  - R1-F3 (major): zero-norm vectors are refused from the bridge, the store and the query, with tests and a deliberate break.
  - R1-F4 (minor): Increment A and the first completion criterion report by book as well.
- **Rejected:** none.
- **After the review:** the plan was amended once, on the figures of Increment A (three searched fields instead of five). The
  amendment was not reviewed by the second model.
- **Left for the owner:** a second round was not asked for; the roadmap's out-of-date "Current state" is not changed.

## Deferred work

- Embedding the summary side of a card, and the choice between one vector for the searched fields together and one for each.
- Embedding `needs` and `limits`, if a later measurement (a better card form or a person's labels) shows them to be reliable.
- Comparing the embedding models on a held-out set of queries with known right answers (`models.md` says the evaluation decides);
  Increment E only shows what each returns for eight searches. A prefix or instruction for a query, which `qwen3-embedding` and
  `mxbai-embed-large` are made for, is the item below.
- A vector index, if the library grows far beyond a few hundred books.
- Prefixes that a model may want for a query and for a document: a model that needs them is not supported by this plan.
- Marked inferences or "not stated" for empty neutral parts, and the other open items of `cards`.
- `catalog.rebuild` builds its file through a fixed name `cards.sqlite.new` in the same way that Increment D-A stops doing for the
  vectors (the security review of `4e93147` found the gap and noted that it predates this plan). It is a change to code that this
  plan does not otherwise touch, so it is for the owner to decide whether to fix it, in a plan of its own or with an amendment.
- A size cap, a row cap and a time limit for reading a file of vectors or the catalog (F3), a time limit for a whole build (F6), and
  a signature that would bind a vector to its text (F4): not done, because the files are the owner's own, private to the owner and
  small (about 80 cards); the limits are stated in the README.

## Result

### Increment A — The accuracy of the neutral descriptions (run; not committed)

- **Tool change** (step 1): `card-sample` could not be limited to the neutral fields (they are about a fifth of a card's items), so
  it gained `--field` (repeat for several; `fields=` in `cardsample.sample`), which also limits the items a second round added.
  Tests written first and seen to fail (`engine.tests.test_cardsample.FieldsTest` and one test in `AddedTest`; 12 errors and a
  failure before). `python3 -W error::ResourceWarning -m unittest engine.tests.test_cardsample` gave 64 tests, OK. Deliberate breaks,
  each from green: no filter in the draw, added items not filtered, the fields not passed to the draw, a repeated field accepted, a
  field name not checked and a string accepted for the list were all caught; accepting an empty list is not caught by a test because
  it still ends in a refusal (an empty pool). The README describes the option.
- **The sample** (step 2): `card-sample ... --items 180 --calibration 15 --seed 20261109` with the five neutral fields, over the
  newest card of every version: 180 items from 78 cards, 2 or 3 per card; by generation 132 of generation 1, 14 of 2, 24 of 3, 8 of 4
  and 2 of 6 (the cards are of several generations because books were carded again at different times; the sample is of the newest
  card of each book, not of one form). Files are held outside the repository.
- **The labels** (step 3, on the owner's word to start the increment): six cloud subagents (Claude Opus), one for each batch of 30,
  blind to the generation of an item, with the rubric of the earlier samples; each saw only the top five passages of the book shown
  with each item. One labeller cut a passage short when writing its file (item i007); the original passages were restored and its
  label kept. **The labels are a model's alone: the calibration subset of 15 has not been labelled by the owner, so the agreement
  with a person is not known.**
- **The figures** (step 4; `card-accuracy` for generation and field, a script in the scratchpad for book and card). 179 items judged,
  1 skipped. Supported 66 (37%), inference 22 (12%), unsupported 91 (51%).

  | field | items | supported | inference | unsupported |
  |---|---|---|---|---|
  | problem | 41 | 59% | 22% | 20% |
  | approach | 37 | 54% | 16% | 30% |
  | provides | 37 | 41% | 3% | 57% |
  | needs | 36 | 14% | 17% | 69% |
  | limits | 28 | 7% | 0% | 93% |

  By generation: 1: 34% supported, 51% unsupported (131 items); 2: 43% and 57% (14); 3: 50% and 38% (24); 4: 38% and 63% (8); 6: 0%
  and 100% (2). The groups after generation 1 are small. By book: 78 books with 2 or 3 items each; 61 of 78 cards have at least one
  unsupported sampled sentence, and in 21 books every sampled sentence is unsupported. Per-book figures rest on 2 or 3 items each and
  are only indications.
- **Limits.** The labels are those of one model and are of support within five passages, which can miss support elsewhere in the book.
  `needs` and `limits` are written to say what an idea requires and where it fails, which a book often does not state, so a low
  share there is partly the nature of those fields and not only error; the same rubric was used in the earlier samples.
- **Reading and recommendation.** The neutral description is least reliable exactly where it would mislead a search by meaning least
  often, and most reliable in `problem` and `approach`, which say what the book is about. Search by meaning on `problem`, `approach`
  and `provides` is worth building; embedding `needs` and `limits` (14% and 7% supported) would put sentences that mostly are not
  in the book into the vectors, and a match on them would look as good as any other. I recommend going on, and changing the plan's
  scope so that the vectors are made for `problem`, `approach` and `provides` only, with `needs` and `limits` left out and
  recorded as deferred. That is a change of the approved text of the plan (its scope, steps and completion criteria) and needs the
  owner's new approval. The alternative is to go on as written with all five fields and to rely on the result showing the field that
  matched. The decision is the owner's, and so is the labelling of the calibration subset, which would show whether these labels
  agree with a person.
- **The owner's decision** (2026-11-09, on my recommendation): go on, with the vectors made for `problem`, `approach` and `provides`
  only. The plan was amended accordingly (Goal, Scope, Non-goals, Assumptions, completion criterion 5, Increments C, D and E,
  Risks, Deferred work; Increment A's text is unchanged because it measured all five fields) and waits for the owner's new
  approval before Increment B. The calibration subset is still the owner's to label.
- Provenance: sample drawn and labelled on 2026-11-09 at commit `aa58cc8` plus the change to `engine/kb/cardsample.py`,
  `engine/kb/__main__.py`, `engine/tests/test_cardsample.py` and `engine/README.md` (committed as `7fbd91b`); the labelling model was
  Claude Opus through subagents; the sample files are `trial/sampleF` in the owner's data folder (untracked).

### Increment B — Call the embedding model from the engine (done; not committed)

- **What was built** (`engine/kb/models.py`): an entry may have `kind` (`chat`, the default, or `embedding`); an embedding entry
  has a `dimension` from 1 to 8192 and no `max_output` or `thinking`, and a chat entry has no `dimension`. The kind of work
  `card-embed` names an embedding entry, and a card task cannot name one; `call` refuses an embedding entry. `embed(cfg, name, texts)`
  sends the texts to `wb run ask-ollama embed` as one JSON object on standard input, in batches (`_batches`: at most 100 texts, about
  200 KB, and fewer as the dimension grows so that a reply of at most 1.5 MB can be read back), checks each reply (embedding contract
  1, `ok`, vendor, a valid model that is the same in every batch, the dimension of the reply and of the entry, as many vectors as
  texts, every number a finite non-boolean of size between `1e-30` (for the largest) and `1e6`, no vector of zeros) and refuses the
  whole call if one reply is wrong. A text must be non-blank text of at most 32768 bytes, and a call is refused before anything is
  sent if a text is wrong, if there are over 100,000 texts, or if texts times the dimension is over 10 million numbers. The spec
  (`docs/specs/models.md`, "The embedding model") and the README ("Calling a model") say what is built.
- **A deviation from the steps as approved.** Step 2 says to add `card-embed` to `OPTIONAL_TASKS`. I made a separate `EMBED_TASKS`
  instead, so `models.TASKS` stays the card kinds (a test in `test_cardmake` equates it with the card jobs), `optional()` stays
  for the card tasks, and `choose(cfg, "card-embed")` is refused with the key to set when it is unset, which is what Increment C needs.
  The outcome is the one the step names.
- **Tests first, seen to fail** (54 errors and a failure before any code); then `python3 -W error::ResourceWarning -m unittest
  engine.tests.test_models engine.tests.test_setup engine.tests.test_cardmake engine.tests.test_cardqueue engine.tests.test_cardstate`
  gave 478 tests, OK. The plan names `test_models` and `test_setup`; I also ran `test_cardmake`, `test_cardqueue` and `test_cardstate`
  because the registry now returns a `kind` for every entry and checks the kind of the entry a task names, which those tests use. No
  call was made to the owner's server (a fake bridge answers).
- **Deliberate breaks**, each from green: 27 of the checks above (the kind, the dimension, the kind of an entry for a task and for a
  call, each limit of a batch, the count of vectors, the dimension of the entry and of a vector, zeros, tiny and huge numbers,
  booleans, whole numbers kept as numbers, the model name and a change of model between batches, the contract, `ok`, the size of a
  text, blank texts, the memory bound) were each broken and each caught.
- **Review.** The read-only `reviewer` agent, one exchange of six: no blocking finding. Applied: (a) the memory held by one call was
  not bounded, so a call is refused when texts times the dimension is over 10 million; (b) a vector of tiny numbers passed the
  check for zeros but its squares would vanish in a cosine, so a vector whose largest number is under `1e-30` is refused; (c) the
  count of bytes a printed number takes was 24 and is 26, which changes a batch at dimension 1024 from 61 to 56 texts. Noted, not
  changed: the deviation above (recorded here); the model the bridge reports is not compared with the entry's name, because a server
  may report `name:latest`, and the store of Increment C records the name the bridge reported; the time limit applies to each batch
  and not to a whole call (a stalled server costs one limit before the call is refused, a large call is many batches). The reviewer
  did not read the tests, the README or the spec; it could not check the bridge's real behaviour or the real size of a reply at
  dimension 8192, which Increment E shows.
- **Not done / for the owner.** A security review has not been run: this increment starts a subprocess and parses output from a model
  server, so it is a place to look; the reviewer named no concrete exposure. It runs only if the owner asks. (Committed as `13deae4`.)

### Increment C — Store the vectors of the searched fields (done; not committed)

- **What was built.** `engine/kb/vectors.py` and the command `python3 -m kb card-vectors [--again]`. `vectors.sqlite` in the index
  root has a `meta` table (format, the model the bridge reported, the name the config gave the model, the dimension, the date) and a
  `vectors` table (book, version, generation, field, SHA-256 of the text, the vector as little-endian 32-bit floats; one row for each
  of `neutral_problem`, `neutral_approach` and `neutral_provides` of the newest card of each version of each active book; never
  `neutral_needs` or `neutral_limits`). A build reads the cards through `card.read`, keeps the vector of a row whose text hash and
  model are unchanged (and takes the generation from the card), sends the other texts through `models.embed` in chunks that fit in
  memory, and writes a new file beside the old one, made private before it holds anything, renamed into place under the catalog's
  lock (taken only to write, not during the model calls). Old files of another format, with other tables, a trigger, a view, an
  odd meta table, a link, or for another model name or dimension are not reused and are replaced (`replaced` in the counts); a
  damaged vector is made again; a bridge that reports another model than the one that made the kept vectors refuses the build and
  asks for `--again`. `connect`, `check_entry` and `read_rows` are the checks a search will use in Increment D. The counts are true:
  cards, no model part, left out, vectors, kept, made, texts sent, model, dimension, replaced. The card spec ("Where it is stored")
  and the README ("Searching the cards") say what is built.
- **Tests first** (the module did not exist: the new test file failed to import), then `python3 -W error::ResourceWarning -m
  unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_models engine.tests.test_card engine.tests.test_setup
  engine.tests.test_cardmake engine.tests.test_cardqueue` gave 674 tests, OK; `wb run code-work check` found no problems. The plan names
  the first three; the others were run because the registry and the cards are read through the same code. No call was made to the
  owner's server (a fake bridge answers). The library of the owner and its index root were not touched.
- **Deliberate breaks**, each from green: 38 changes (the six the plan names, a vector stored for the wrong field, the text hash not
  checked, a foreign model or dimension accepted, a half-built file left, a non-finite or zero vector stored, the length not
  checked, a kept row not reused, `needs` embedded, no lock, a file not private (also if made private only after the insert), a
  model change not refused, stale journal files kept, a row's field not checked when read, no chunking, a link followed, a trigger,
  view or extra table allowed, the format not checked, `replaced` never said, `--again` keeping old rows, inactive books included,
  the library not guarded at the start or before the swap, unreadable cards not counted, blank text embedded, the generation not
  taken from the card, odd meta values, an unsendable text kept) were each caught. One is not caught and is redundant: the range of
  the dimension in the meta table, because a dimension outside 1 to 8192 can never equal the entry's, which is checked as well.
- **Review.** The read-only `reviewer` agent, a second exchange of six: no blocking finding. Applied: (a) the meta table of the file
  is not trusted (a value that is not text, a dimension that is not ASCII digits, a model name that is not a valid name or a date that
  is too long made `build` raise a `ValueError` or crash on bytes; now they are an unusable file, replaced by a build and refused by
  `check_entry`); (b) the new file is made private as soon as it exists and not after the insert; (c) a text that cannot be encoded
  (a lone surrogate) leaves its card out and counts it, though a card made by the engine has none (its cleaning drops it, which I
  tried) and an edited card fails its payload hash; (d) the docstring says that the cards and the old file are read before the model
  calls and the lock is taken only to write, so a card made meanwhile, or a second build, gives a file that is valid for the cards that
  were read, and a search treats a vector whose text no longer matches as stale. Not applied: the reviewer suggested removing the old
  file's journal, WAL and SHM files after the replace; they are removed before it on purpose, so that a hot journal of the old
  file can never be replayed into the new one (the catalog does the same); the edge it names (the replace failing after they are
  removed) leaves the old file readable and complete.
- **Not done / for the owner.** No security review was run; I recommend one after Increment D, which is the first increment in which
  an agent's query and the stored vectors meet. The reviewer did not read the tests, README or spec text, and could not run anything.
  (Committed as `24c1a8e`.)

### Increment D — Search by meaning (done; not committed)

- **What was built.** `python3 -m kb card-search QUERY --meaning [--limit N]` (`vectors.search`). The query is any text of up to 2000
  characters. It is refused before anything is sent if it is not text or is blank, if the limit is not 1 to 50, if there is no file of
  vectors or no catalog, if the file of vectors is of another format, has a trigger, a view or an odd meta table, or was made for
  another model name or dimension than the one set, or has a row that is not what the engine writes. The query is then turned into a
  vector by the embedding model of the config (`models.embed`); a reply from another model than the one that made the vectors is
  refused. Each vector is used only if its card is in the catalog, the field's text there is non-empty and hashes to the stored hash,
  and the vector is of the entry's dimension, finite and not all zero; any other is left out and counted in `stale` (stored vectors,
  not cards), and a card with no vector that can be used is counted in `without_vector`. The vectors are scaled to length one and a
  card is ranked by the cosine to the closest of its three vectors (ties: problem, approach, provides; between cards: book and
  version), the score rounded to 12 places, larger being closer. The reply is `{"meaning", "model", "cards_searched", "stale",
  "without_vector", "results"}`. A result is built by the same function as a keyword result (`catalog.result_of`, moved out of
  `catalog.search` without a change of its output: the 81 catalog tests pass unchanged), so it has the same keys, the same checks of
  the row against its card, the same markers and the same citation; its `score` is the cosine, `matched` and `excerpt_field` name the
  field, and the excerpt is the start of that field's text. `--meaning` takes no `--in` and no `--book`. The card spec ("Searching the
  catalog") and the README ("Searching the cards") say what is built, and that a larger score is closer.
- **Tests first** (the search tests failed with 59 errors because `vectors.search` did not exist), then `python3 -W
  error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_card engine.tests.test_models
  engine.tests.test_setup engine.tests.test_cardmake engine.tests.test_cardqueue engine.tests.test_trial` gave 752 tests, OK;
  `wb run code-work check` found no problems. The plan names the first four; the others were run because the refactor of
  `catalog.search` and the `--in` default of the command are read by them. No call was made to the owner's server (a fake bridge
  answers with vectors chosen by hand, so the order a query must give is known).
- **Deliberate breaks**, each from green: 22 (the wrong sign of the ranking, a stale vector used in two ways, a foreign model accepted
  for the query and a foreign store accepted, a limit not applied or not checked, a card returned twice, the query's length not
  checked, stale vectors or cards without a vector not counted, a tie going to the later field, the wrong catalog name for a field, a
  score that is not the cosine, vectors not scaled, a result without its marker, a damaged vector refusing the search instead of
  being counted, a row of the catalog not checked against its card) were each caught. Three are not caught and are equivalent in
  effect: a blank query is also refused inside `models.embed` before anything is sent; and a vector of zeros cannot reach the scaling,
  because it is left out as damaged when the rows are read and a zero query vector is refused by `models.embed`.
- **Review.** The read-only `reviewer` agent, a third exchange of six: no blocking finding. Applied: the command read the config
  twice and now reads it once; the README says `stale` counts stored vectors (not cards), `cards_searched` counts cards with at least
  one vector that can be used, and that, as in the keyword search, a card is checked against its row only when it is in the results.
  Noted, not changed: the stored hash binds a vector to its text and not the other way, so a person who can write the private file
  could put any vector under a correct hash and change the ranking (card text is only ever taken from the validated catalog row);
  the search has no time cap like the keyword search's ten seconds, which the size of this library does not need (about 80 cards),
  and a card larger than a card may be is refused when the catalog is built. The reviewer could not run anything, had no diff of
  `catalog.py`, and did not read the tests, README or spec text.
- **Not done / for the owner.** No security review was run. This is the increment in which an agent's query goes to a model server, its
  reply is parsed, and a file in the index root that may have been altered is read, so I recommend one now, before Increment E. It
  runs only if the owner asks. (Committed as `4e93147`.)

### Security review of Increments B to D (run on the owner's word, on commit `4e93147`)

- **What was run.** The `security-reviewer` agent (a read-only agent that runs experiments on a copy), on a copy made with `git
  archive 4e93147`, with fake bridges and no network. It traced the inputs an attacker controls (a query, card text, the bridge's reply,
  the files in the index root, the config names) to their privileged uses and ran about forty probes. The test files
  `test_vectors` and `test_models` passed in its copy (223 tests; it ignored resource warnings). The tree under review was unchanged
  (`git status` empty, HEAD `4e93147`, no stash). It disclosed that its first run executed an older script that was already in the
  shared scratch folder and touched only an old scratch folder, not the repository. It could not check by experiment: what `main`
  prints for a SQLite error (it did not call `main`, which reads the real config), a grandchild process that keeps the pipe open, and
  whether the `wb` launcher itself reads `--server`, `--model` or `--timeout`.
- **Findings.** No Critical or High. **Medium F2:** `build` removes the fixed name `vectors.sqlite.new`, creates it through SQLite and
  then makes it private, so someone who can write in the index root and recreates a link in that gap makes SQLite write the vectors
  schema into a file outside the index root and sets it to 0600 (shown with an empty file and with a foreign SQLite file, which gained
  two tables and kept its own); `catalog.rebuild` has the same pattern and predates this plan. **Low F1:** a file of vectors whose
  `meta` page is damaged makes `search` raise a raw SQLite error (a traceback at the command). **Low F5:** text from the error object
  of the bridge reaches a refusal without the guard against marker words (the older chat call has the same pattern). **Low F3:** a
  file of vectors or the catalog is read whole into memory (150 MB for a 150 MB cell) with no cap and no time limit. **Low F4:** the
  text hash does not bind a vector to its text, so a person who can write the file can put any vector under a correct hash and it
  survives a rebuild until `--again`. **Low F6:** the time limit of a build is for each batch, not for the whole build.
- **Found sound** (tested): the arguments of the bridge command (names restricted, no shell, texts only on standard input); the strict
  checks of the bridge's reply (duplicate keys, NaN, 1e999, a 5000-digit integer, a boolean as a number, wrong types, odd model names,
  a flood of output, a hang, bad UTF-8, exit codes that lie); the lock file and its link check; read-only opening; stale journals; marker
  words in card text (withheld, one genuine end marker in a result); the text-hash staleness; links and directories at the file of
  vectors; odd cells in the meta and vector tables. Read only: no code from a SQLite file is reachable from its data; the batching
  limits fit the bridge's.
- **My evaluation.** F1 and F2 confirmed against the code (`vectors.py:112` has no guard for a SQLite error; `vectors.py:274-278`
  removes, creates and then makes private). The index root belongs to the owner, so F2 and F3 need a writer there who is the owner or
  runs as the owner; in practice they are Low, and the fix for F2 is small and standard. F4 is inherent to the design.
- **The owner's decision** (2026-11-09, on my recommendation): fix F1, F2 and F5 in a new Increment D-A, which needs the owner's new
  approval of the plan; state F3, F4 and F6 as known limits in the README; note the same gap in `catalog.rebuild` as deferred. The
  plan was amended (Completion criteria, Increment D-A, the dependency of Increment E, Risks, Deferred work); it was committed as
  `6ce5e53` and approved again.

### Increment D-A — Fix the findings of the security review of Increments B to D (done; not committed)

- **F2 (the file built through a fixed name).** `vectors.build` now makes a folder with `tempfile.mkdtemp` inside the index folder
  (mode 0700, a random name beginning `.vectors-build-`), under the catalog's lock, builds the file there, makes it private, and
  renames it into place; the folder is removed whatever happens. `_clean_leftovers` removes, under the lock, every folder, file or
  link whose name begins with the prefix (a link as a link, never its target) and the two fixed names an earlier version used
  (`vectors.sqlite.new` and its journal), and nothing else. `_identity` checks that the folder is a real folder owned by this user
  when it is made and again before the file is put in place, which was added after the second look (below).
- **F1 (a raw SQLite error).** `_meta` turns a SQLite error into a refusal that names `card-vectors`; the other reads of the file were
  already covered (`connect`, `read_rows`, `_old_rows`). A file with its `meta` page zeroed or filled with 0xff is refused by
  `check_entry` and by `search`, and a build replaces it.
- **F5 (marker words in the bridge's text).** `models._shown` cleans and cuts text from a bridge and shows a fixed `[text withheld]`
  in place of text that holds the words of a marker; it is used for the `error` and `detail` of a failure and, after the second look,
  for the stderr text in a refusal. It covers the chat call and `embed`.
- **README.** The build folder, what a build removes, that the race is narrowed and not closed, and the known limits F3, F4 and F6
  (with `card-vectors --again` as the recovery for F4).
- **Tests first** and seen to fail: the new tests for F1, the leftovers and the planted link failed against the code of `4e93147`,
  for the reasons the review gave (a raw `sqlite3.DatabaseError`; the build written through a planted link, shown by the file put in
  place being the link). Then `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_models
  engine.tests.test_catalog engine.tests.test_card engine.tests.test_setup engine.tests.test_cardmake engine.tests.test_cardqueue`
  gave 723 tests, OK; `wb run code-work check` found no problems. The plan names the first three; the others were run because the
  registry and the cards are read through the same code. No call was made to the owner's server.
- **Deliberate breaks**, each from green: 16 (the old fixed name used; the file private only after it holds data; the folder not
  private; a leftover not removed; a leftover removed that is not one; a link followed when a leftover is removed; the old fixed
  names not removed; the folder left behind after a failure; a name that can be guessed; a SQLite error left to escape from `_meta`;
  the words of a marker shown from the error text and from stderr; a withheld reason shown as empty; the identity of the folder not
  checked when it is made, before the file is put in place, or for a link) were each caught. Not tested: the owner check of the
  folder (`st_uid`), because a test cannot make a folder owned by another user.
- **Second look** (the read-only `reviewer` agent, a fourth exchange of six): no bypass of F1, F5 fixed for the two fields it covered,
  no blocking finding. Applied: (1) a narrow race remained for F2, since the file is made by SQLite through the folder's name and
  someone who can write in the index folder could rename the folder and put a link at its name in the moments between; the
  identity check above narrows it, and the README and this Result say it is narrowed and not closed (SQLite cannot be given a
  folder's descriptor); (4) the README now says a build removes every name that begins with the prefix; (6) the stderr text of the
  bridge, which F5 had not covered, is guarded in the same way. Not applied: (3) an `OSError` from `mkdtemp`, `chmod` or `replace`
  was said to escape `build` as a traceback, but the command catches `OSError` and prints `failed:` with exit 1
  (`__main__.py`, the `except OSError` after the `except KbError`); (5) the old file's journal, WAL and SHM files are still removed
  before the rename, on purpose, so that a hot journal can never be replayed into the new file; if the rename then fails the old file
  is complete, as the catalog's build also does. Noted: `catalog.rebuild` has the same fixed-name gap (already deferred). The
  reviewer could not run anything and did not read the Result or all of the README.
- **Not done / for the owner.** F3, F4 and F6 are known limits, stated in the README. The `catalog.rebuild` gap is deferred for the
  owner to decide. (Committed as `ab32df3` and pushed.)

### Before Increment E: the models to try, and an amendment of E (2026-11-09)

- **The models.** The owner pulled `qwen3-embedding:4b` and `mxbai-embed-large` onto `ned`, besides `bge-m3`, and added a section for
  each to the endpoint record (`wb run ask-ollama check` lists them with `kind=embedding`, `context=8192` and `512`). The config holds
  three embedding entries, `embed-bge`, `embed-qwen` and `embed-mxbai`, and `card-embed` names `embed-bge` (`python3 -m kb models`
  loads it). A probe that sent the word "test" to each model (three calls, on the owner's word) found the dimensions 1024, 2560 and
  1024; each reply was finite, of length one, with its largest number under 0.34 and its smallest above 1e-6, so all three are
  inside the limits of `models.embed`.
- **Why these models.** A search of recent write-ups (blogs repeating MTEB scores, not primary benchmarks) put Qwen3-Embedding first
  for quality, `bge-m3` as the multilingual workhorse, and `mxbai-embed-large` as a good English model; none of that was checked on
  this library. The cards' fields are short English text (at most 500 characters), so the languages and the long window of `bge-m3`
  count for little here. Qwen3-Embedding is trained for an instruction before the query (`Instruct: …` then `Query: …`) and
  `mxbai-embed-large` for a short prefix; the engine sends neither, so both start at a disadvantage against `bge-m3`.
- **A correction.** I told the owner that comparing the models "fits inside Increment E". It did not: the plan listed comparing
  embedding models as a non-goal. The owner chose to amend the plan (the non-goal, completion criterion 5, Increment E, Risks and
  Deferred work), so E now repeats its build and the same eight searches for each model the owner has listed, shows what each
  returns, and records the owner's choice of the model the library keeps. It still measures no accuracy and ranks no model. The plan
  was committed and approved again before E. (Committed as `a283ccb`.)

### Increment E — Build over the library and look at what it returns (done; no tracked code besides this plan)

- **The eight searches** (agreed by the owner, the same for every model): (1) test whether an item belongs to a huge set with very
  little memory, when a small chance of a wrong "yes" is acceptable; (2) act when the other side's information is hidden and it may
  bluff; (3) find a good design in an enormous space when every trial is expensive; (4) speed up a big computation by splitting it
  across workers when one part must run in sequence; (5) allow random jumps at first and make them rarer so the search settles; (6)
  play many random games to the end, note which first moves win most often, and spend more trials on those; (7) replace a table lookup
  with a model that predicts where the item sits; (8) break a task into overlapping pieces, solve each once and reuse the answers.
  Each is paired with two plain words for the keyword side (`membership memory`, `hidden information`, `expensive evaluation`, `split
  workers`, `random jumps`, `random trials`, `predict lookup`, `reuse pieces`), since a keyword search needs every word in one card.
  The books I expected to see for each are my own judgment and are not a measured truth.
- **Round 1: `bge-m3:latest` (`embed-bge`, dimension 1024), on the owner's word.** `card-vectors` read 79 cards (one with no model
  part, none left out) and made 230 vectors from 230 texts in 6.3 s, in one pass; a second run kept all 230 and sent no text. The 230
  equal the number of non-empty searched fields in the catalog. A search covered 78 cards with 0 stale and 0 without a vector. The
  results of a live search carry the untrusted-text markers and a citation. Sent to `ned`, in the clear: the 230 texts, then the eight
  query sentences (twice, because I ran the searches again to record the rank of the expected books, and one of them a third time to
  check the markers).
- **What came back** (the first five by meaning; "kw" is the keyword search on the neutral side). (1) Bloom filter first (0.78), then
  four unrelated books; kw: Bloom filter. (2) Mechanism design, Minimax, Mastering Atari/Go/Chess/Shogi by planning, Dota 2, Genetic
  algorithm; DeepStack at rank 11 and the imperfect-information paper at 14; kw: Mastering Atari/Go/Chess/Shogi. (3) LoRA, Simulated
  annealing, Computer-aided design, 3D modeling, Genetic algorithm; DeepCAD at 47; kw: none. (4) OpenMP first, Asynchronous Methods
  for deep RL, ZeRO, a FreeCAD scripting page, Computer-aided manufacturing; Amdahl's law at 12, Horovod 13, Megatron 9, Message
  Passing Interface beyond 50; kw: none. (5) Alpha-beta pruning, A*, Dijkstra, Simulated annealing (4th), PPO; kw: none. (6) Mechanism
  design, Evolutionary game theory, Dijkstra, Mastering Chess and Shogi by self-play, Dynamic programming; Monte Carlo tree search at
  21; kw: none. (7) five books about language and vision models and game agents; The Case for Learned Index Structures beyond 50;
  kw: none. (8) Dynamic programming first (0.69), OpenMP, DeepStack, GPT-3, ResNet; FlashAttention at 17, Fast Fourier transform
  beyond 50; kw: none.
- **A plain reading.** `bge-m3` puts the book that states the idea first when the card says it plainly (Bloom filter, Dynamic
  programming, OpenMP), and finds Simulated annealing and Genetic algorithm in the top five for the search problem. It misses
  books a person would expect for the others (Monte Carlo tree search, the learned index, Amdahl's law, DeepStack), and the top five
  often hold books of a similar kind of text (Wikipedia pages on algorithms, or deep-learning papers) that have little to do with
  the query. The keyword search found something for two of the eight. The result cannot say whether the misses come from the model,
  from the neutral descriptions (the sample of Increment A found them partly unsupported), or from the query wording.
- **Round 2: `qwen3-embedding:4b` (`embed-qwen`, dimension 2560), on the owner's word.** `card-vectors` made 230 vectors from 230
  texts in 27.6 s (`replaced: true`: the `bge-m3` file was replaced, nothing mixed); a second run kept all 230 and sent no text. A
  search covered 78 cards with 0 stale and 0 without a vector, and the live results carry the markers and a citation (the script
  asserts this on every result of a search; for this round one search was also checked by hand). Sent to `ned`, in the clear: 230
  texts, the eight query sentences, and the first query a second time for the check. No instruction was put before a query: the
  model is made to take one, so it ran without its best form.
- **Where the books I expected ranked, `bge-m3` then `qwen3-embedding:4b`** (my own expectations; rank among 78; lower is better):
  1 Bloom filter 1 → 1 (closeness 0.78 → 0.86); 2 DeepStack 11 → 3, the imperfect-information paper 14 → 5; 3 Simulated annealing
  2 → 1, Genetic algorithm 5 → 5, DeepCAD 47 → 19; 4 OpenMP 1 → 1, Horovod 13 → 3, Amdahl's law 12 → 5, ZeRO 3 → 11, Megatron 9 → 10,
  Message Passing Interface beyond 50 → 23; 5 Simulated annealing 4 → 1; 6 Monte Carlo tree search 21 → 9; 7 The Case for Learned
  Index Structures beyond 50 → 25; 8 Dynamic programming 1 → 1, Fast Fourier transform beyond 50 → 13, FlashAttention 17 → 16.
  `qwen3-embedding:4b` put the expected book higher in 12 of the 18 comparisons, the same in 4 and lower in 2 (ZeRO and Megatron
  in search 4). The top five of its search 1 held The Case for Learned Index Structures second, which `bge-m3` did not.
- **A plain reading.** On these eight searches `qwen3-embedding:4b`, with no instruction, found more of the books I expected, and
  higher, than `bge-m3`; both missed Monte Carlo tree search and the learned index in the top five, and neither is a measurement of
  accuracy. The keyword results are the same as in round 1.
- **Round 3: `mxbai-embed-large:latest` (`embed-mxbai`, dimension 1024), on the owner's word.** `card-vectors` made 230 vectors from
  230 texts in 5.6 s (`replaced: true`; no text was refused for its length); a second run kept all 230 and sent no text. A search
  covered 78 cards with 0 stale and 0 without a vector, and the script asserted the markers and a citation on every result. Sent to
  `ned`, in the clear: 230 texts and the eight query sentences. No prefix was put before a query, though the model is made to take one.
- **Where the books I expected ranked, in all three rounds** (my own expectations; rank among 78; `bge-m3` / `qwen3-embedding:4b` /
  `mxbai-embed-large`): 1 Bloom filter 1 / 1 / 1; 2 DeepStack 11 / 3 / 3, imperfect-information paper 14 / 5 / 12; 3 Simulated
  annealing 2 / 1 / 1, Genetic algorithm 5 / 5 / 3, DeepCAD 47 / 19 / 12; 4 OpenMP 1 / 1 / 1, Amdahl's law 12 / 5 / 6, Horovod 13 / 3 /
  21, ZeRO 3 / 11 / 4, Megatron 9 / 10 / 5, Message Passing Interface beyond 50 / 23 / 31; 5 Simulated annealing 4 / 1 / 1; 6 Monte Carlo
  tree search 21 / 9 / 2; 7 The Case for Learned Index Structures beyond 50 / 25 / 25; 8 Dynamic programming 1 / 1 / 1, Fast Fourier
  transform beyond 50 / 13 / 15, FlashAttention 17 / 16 / 32. Over the 18 comparisons (a rank beyond 50 counted as 51) the mean rank was
  17.4 / 8.4 / 9.8, and the expected book was in the top five 7 / 10 / 10 times. These are descriptive figures on eight searches and
  my own expectations; they are not a ranking of the models.
- **Side by side.** Only a few books were returned in the top five by all three models for the same search: Bloom filter (1);
  Mechanism design and Minimax (2); Simulated annealing and Genetic algorithm (3); OpenMP (4); A* and Simulated annealing (5);
  Evolutionary game theory (6); two papers on vision-language and game-playing agents (7); Dynamic programming (8). The rest of each
  top five differed between the models. `qwen3-embedding:4b` alone found Amdahl's law, CUDA and Horovod for search 4; `mxbai-embed-large`
  alone found Monte Carlo tree search for searches 5 and 6 (second in 6, where `bge-m3` had it 21st and `qwen3` 9th) and Megatron-LM
  for 4. Each model also returned a few books that seem unrelated to the search (for example the Hello world page from `bge-m3` in
  search 1 and from `mxbai-embed-large` in search 8, and the SQLite page from `qwen3-embedding:4b` in searches 1 and 7); I did not
  count them. All three
  missed The Case for Learned Index Structures in the top five of search 7 (25th for both newer models), and all three put an
  unrelated book or two in most top fives.
- **What could not be concluded.** Eight searches and my own idea of the right books cannot show how often search finds a transfer or
  which model is better in general; the differences between `qwen3-embedding:4b` and `mxbai-embed-large` are small and go both ways.
  The misses may come from the neutral descriptions (Increment A found them partly unsupported) as well as from the models. Both
  newer models are made to take an instruction or a prefix before the query, which the engine does not send, so they may do better
  than shown. That, and a trial on problems with known answers, is where the models should be compared; it is the candidate
  `cross-field-discovery#cross-field-trial`.
- **Cost and size** (one build of 230 texts, on `ned`): `bge-m3` 6.3 s, 1024 numbers a vector; `qwen3-embedding:4b` 27.6 s, 2560 numbers
  (the vectors are about 2.5 times larger); `mxbai-embed-large` 5.6 s, 1024 numbers, and a limit of 512 tokens a text (the cards' fields
  are at most 500 characters, so none was refused, but a longer field would be).
- **Recommendation (for the owner's decision).** Keep `qwen3-embedding:4b` as the library's model. On these searches it did as well
  as `mxbai-embed-large` and better than `bge-m3`, it has far more room in its window, and it has an upside once the engine can send
  the instruction it is made for. Its costs are a longer build (27.6 s for the library) and larger vectors, which are small at this
  size. `mxbai-embed-large` is a reasonable second choice if a short build or a small file matters more. The file of vectors on disk
  now holds `mxbai-embed-large`: if the owner keeps `qwen3-embedding:4b`, the owner sets `card-embed` back to `embed-qwen` and the
  library is built again with it (230 texts to `ned`, about half a minute).
- **The owner's decision** (2026-11-09, on my recommendation): the library keeps `qwen3-embedding:4b`. The owner set `card-embed` to
  `embed-qwen`, and I built the library again with it: 230 vectors from 230 texts in 27.7 s (`replaced: true`, the `mxbai-embed-large`
  file replaced, nothing mixed). The file of vectors on disk now says `model` and `configured` `qwen3-embedding:4b`, dimension 2560,
  230 rows; a further build kept all 230 and sent no text. The config keeps the three embedding entries (`embed-bge`, `embed-qwen`,
  `embed-mxbai`), so another model can be tried by changing the one word of `card-embed` and building again.
- **Verification of the plan as a whole** (run once after the last increment): `python3 -W error::ResourceWarning -m unittest
  engine.tests.test_models engine.tests.test_catalog engine.tests.test_vectors engine.tests.test_card engine.tests.test_cardsample`
  gave 478 tests, OK. No code changed in this increment, so the recorded verification of A to D-A stands. `wb run code-work check`
  finds no problems. Sent to `ned` during E, in the clear: four builds of 230 texts (`bge-m3`, `qwen3-embedding:4b`,
  `mxbai-embed-large`, and `qwen3-embedding:4b` again), about 38 query sentences (the eight searches for each model, the eight again
  for `bge-m3` to record ranks, and two single searches to check the markers), and the three one-word probes of the dimensions.
- **What is left, for the owner.** The cross-field trial (`cross-field-discovery#cross-field-trial`) is where the models and the
  search are compared on problems with known answers, and `problem-search` is the candidate that would use this search. Not done and
  recorded as deferred: a prefix or instruction before a query (which `qwen3-embedding` is made for); the fixed-name gap of
  `catalog.rebuild`; caps on reading the files; embedding `needs` and `limits`; the roadmap's out-of-date "Current state"; the
  calibration subset of Increment A, still unlabelled by the owner.
