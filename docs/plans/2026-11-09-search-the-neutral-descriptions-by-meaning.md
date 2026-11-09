# Search the neutral descriptions by meaning

Status: Proposed
Created: 2026-11-09
Candidate: cross-field-discovery#meaning-search
Specs: docs/specs/card.md, docs/specs/models.md

## Goal

An agent can search the library by meaning. The five neutral fields of each card (problem, approach, needs, provides, limits) are
turned into vectors by an embedding model that the owner lists in the config, and `card-search` with a new `--meaning` option returns
books ranked by how close a field of their card is to the query. A result has the same citation, the same facts about how complete
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
  dimension, one vector for each neutral field of each card, kept when the text it came from has not changed.
- A command that builds the store, and the search by meaning in `card-search`: the query is embedded by the same model, the closeness
  is a cosine, a card is ranked by its closest field, and the result says which field matched.
- A live build over the library with the owner's embedding model and a few searches whose results are shown to the owner.
- The spec text (`docs/specs/card.md`, "Searching the catalog"; `docs/specs/models.md`, "The embedding model") and `engine/README.md`.

## Non-goals

- Themes, search over the full text by meaning, a cloud embedding service, and ranking by anything but closeness (all named out of
  scope by the candidate).
- Embedding the summary side of a card (the summary, uses, topics, key ideas). Only the five neutral fields are embedded.
- Comparing embedding models, and choosing one by measurement. The owner lists the model; the plan does not decide which is best. The
  trial of the candidate `cross-field-discovery#cross-field-trial` is where search is compared.
- A vector index (approximate nearest neighbour) or a new dependency. The library has about eighty books and five fields each, so the
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
- Text sent to the embedding model (the neutral fields of cards, and the query) goes to the owner's server over plain HTTP on the
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
  each of the five fields as its own vector (as `card.md` and `theme.md` say, "each is embedded separately") and ranks a book by its
  closest field. Whether one vector for all five fields would do better is not tested here.

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
5. A live build over the library made a vector for each neutral field of each card that has one, and the owner has seen the results
   of the searches of Increment E and recorded a decision.
6. `wb run code-work check` finds no problems, and the specs and the README state what is built.

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

### Increment C — Store the vectors of the neutral fields

**Outcome:** `python3 -m kb card-vectors` builds a file of vectors from the cards, marked with the model, and builds it again
cheaply when nothing changed.
**Dependencies:** B.
**Affected areas:** a new `engine/kb/vectors.py`, `engine/tests/test_vectors.py`, `engine/kb/__main__.py` (the command),
`docs/specs/card.md` ("Where it is stored"), `engine/README.md`.
**Steps:**
1. Write the tests first, with the fake bridge: the store is built from the cards of a fixture library; building twice makes the same
   rows; a card whose neutral field text changed gets a new vector and the others keep theirs (the fake bridge counts the texts it
   was sent); a card with no model part, and an empty neutral field, make no row; a store of another format number, a store with a
   table or trigger the engine did not put there, and a store whose model or dimension differs from the configured one, are refused
   as the catalog's checks refuse them; a half-built store is never left in place.
2. The file `vectors.sqlite` in the index root holds a `meta` table (format, the model as the bridge named it, the dimension, the
   date of the build) and a `vectors` table: the book, the version, the generation, the field (one of the five), the SHA-256 of the
   field's text, and the vector as 32-bit floats. It is built beside the old file and renamed into place under the writers' lock, as
   the catalog is, and it has mode 600. It reads the cards through `card.read`, so a card that fails its checks is left out and
   counted.
3. `card-vectors` reads the cards, keeps a row whose text hash and model match, sends the other texts through `models.embed` in
   batches, and prints the counts: cards, vectors kept, vectors made, cards left out, and texts sent. `--again` makes every vector
   again. It refuses when `card-embed` is not set or model work is off. Nothing but the neutral fields is sent.
4. Update `card.md` ("Where it is stored": the vectors are a second derived file that can be thrown away and rebuilt) and the README.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_models`;
deliberate breaks, each from a green baseline: a vector stored for the wrong field, a text hash not checked, a foreign model accepted,
a half-built file left in place, a non-finite number stored, a kept row not reused (the fake bridge's count of texts shows it);
`wb run code-work check`. No call to the owner's server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#C`.

### Increment D — Search by meaning

**Outcome:** `python3 -m kb card-search QUERY --meaning` ranks books by the closeness of the query to a neutral field of their card
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
   connection each, compute the cosine in plain Python, rank, and build the results. `--meaning` takes the neutral fields only and
   refuses `--in`. The excerpt is the text of the field that matched.
4. Update `card.md` ("Searching the catalog": the search by meaning is built; the marks and the citation are those of a keyword
   result; the neutral side only) and the README.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_vectors engine.tests.test_catalog engine.tests.test_card engine.tests.test_models`;
deliberate breaks, each from a green baseline: ranking by the wrong sign, a stale vector used, a foreign model accepted, a zero vector ranked, a result
missing its markers or its citation, a limit not applied, a card returned twice; `wb run code-work check`. No call to the owner's
server is made in this increment.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-09-search-the-neutral-descriptions-by-meaning#D`.

### Increment E — Build over the library and look at what it returns

**Outcome:** the library has vectors for its neutral fields, and the owner has seen what a few searches by meaning return next to
what a keyword search returns, and decides what to do.
**Dependencies:** D, the owner's setting of the embedding entry and of `card-embed` in the config, and the owner's word to run.
**Affected areas:** the index root (`vectors.sqlite`); this plan's Result. No tracked code.
**Steps:**
1. Run `wb run ask-ollama check` to see that the embedding model is listed, and `python3 -m kb card-vectors` over the library. The
   texts sent are the neutral fields of the current cards (about 400), to the owner's server; say so before the run.
2. Run the build again: it makes no new vector.
3. Run a set of searches by meaning, and the same words as a keyword search on the neutral side. The owner gives the queries, or
   agrees to a set of eight that I propose: four written as a problem of one field and four as a plain description of a mechanism.
   Record for each the first five books of each search with the field that matched.
4. Record the counts of the build, its time, any text refused, and a plain reading of the searches: which books surfaced that the
   keyword search did not, which keyword results were lost, and which results are from the same field as the query. No claim of how
   often search finds a transfer is made: that is the trial (`cross-field-discovery#cross-field-trial`).
5. Recommend, and record the owner's decision.
**Verification:** the second build makes no new vector; every search's results have a citation and the markers; the counts of the
build agree with the number of neutral fields in the catalog; `wb run code-work check`.
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
  the owner, started on the owner's word). In E, the neutral fields and the queries go in the clear to the owner's server on the
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
  root. The owner is asked once whether to run a security review with the installed module before Increment B is committed; it runs
  only if the owner asks.

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
- **Left for the owner:** a second round was not asked for; the roadmap's out-of-date "Current state" is not changed.

## Deferred work

- Embedding the summary side of a card, and the choice between one vector for all five neutral fields and one for each.
- Comparing the two embedding models on a held-out set of queries (`models.md` says the evaluation decides).
- A vector index, if the library grows far beyond a few hundred books.
- Prefixes that a model may want for a query and for a document: a model that needs them is not supported by this plan.
- Marked inferences or "not stated" for empty neutral parts, and the other open items of `cards`.

## Result

Empty until work starts.
