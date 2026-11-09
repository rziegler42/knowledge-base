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
- Comparing embedding models, and choosing one by measurement. The owner lists the model; the plan does not decide which is best. The
  trial of the candidate `cross-field-discovery#cross-field-trial` is where search is compared.
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
5. A live build over the library made a vector for each searched field (problem, approach, provides) of each card that has one, and the owner has seen the results
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

### Increment E — Build over the library and look at what it returns

**Outcome:** the library has vectors for its searched fields, and the owner has seen what a few searches by meaning return next to
what a keyword search returns, and decides what to do.
**Dependencies:** D, the owner's setting of the embedding entry and of `card-embed` in the config, and the owner's word to run.
**Affected areas:** the index root (`vectors.sqlite`); this plan's Result. No tracked code.
**Steps:**
1. Run `wb run ask-ollama check` to see that the embedding model is listed, and `python3 -m kb card-vectors` over the library. The
   texts sent are the three searched fields of the current cards (about 240), to the owner's server; say so before the run.
2. Run the build again: it makes no new vector.
3. Run a set of searches by meaning, and the same words as a keyword search on the neutral side. The owner gives the queries, or
   agrees to a set of eight that I propose: four written as a problem of one field and four as a plain description of a mechanism.
   Record for each the first five books of each search with the field that matched.
4. Record the counts of the build, its time, any text refused, and a plain reading of the searches: which books surfaced that the
   keyword search did not, which keyword results were lost, and which results are from the same field as the query. No claim of how
   often search finds a transfer is made: that is the trial (`cross-field-discovery#cross-field-trial`).
5. Recommend, and record the owner's decision.
**Verification:** the second build makes no new vector; every search's results have a citation and the markers; the counts of the
build agree with the number of non-empty searched fields in the catalog; `wb run code-work check`.
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
  the owner, started on the owner's word). In E, the three searched fields and the queries go in the clear to the owner's server on the
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
- **After the review:** the plan was amended once, on the figures of Increment A (three searched fields instead of five). The
  amendment was not reviewed by the second model.
- **Left for the owner:** a second round was not asked for; the roadmap's out-of-date "Current state" is not changed.

## Deferred work

- Embedding the summary side of a card, and the choice between one vector for the searched fields together and one for each.
- Embedding `needs` and `limits`, if a later measurement (a better card form or a person's labels) shows them to be reliable.
- Comparing the two embedding models on a held-out set of queries (`models.md` says the evaluation decides).
- A vector index, if the library grows far beyond a few hundred books.
- Prefixes that a model may want for a query and for a document: a model that needs them is not supported by this plan.
- Marked inferences or "not stated" for empty neutral parts, and the other open items of `cards`.

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
  runs only if the owner asks.
