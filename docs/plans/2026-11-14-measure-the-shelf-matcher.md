# Measure the shelf matcher

Status: Proposed
Created: 2026-11-14
Candidate: none (the shelves, the fetch engine and the crawler are outside every roadmap, which say so; creating a roadmap for them is the owner's change of direction, and this plan is the next step the owner asked for after the shelf schema)
Specs: docs/specs/shelf.md

## Goal

The library has a shelf schema (4,816 shelves, committed in `engine/kb/data/shelf-schema.json`) and a spec that says a work is placed on one home shelf by a matcher: the nearest shelf descriptions by embedding, then
a model's choice among them (`docs/specs/shelf.md`, "Placement when more than one shelf fits", and its Acceptance criteria and Open questions). Nobody knows yet how accurate that is, and the spec leaves it open on purpose ("Only a run can tell"). When this plan is done:

- there is a measurement, on real OpenAlex works whose label is hidden from the matcher, of how often the embedding step puts the right topic, subfield, field and domain among the nearest shelves, for each of a few
  embedding models, and how long it takes;
- there is the same measurement for the model's choice among the nearest shelves, on a smaller sample, if the first result makes it worth running;
- the owner has read the result against a bar the owner set before any run, and decides whether the matcher is good enough to build on, needs a different method, or needs more evidence;
- the pure part of the matcher (ranking shelves by closeness, scoring a placement at each level) is code with tests in `engine/kb/`, ready for the library to use.

## Scope

- A module `engine/kb/shelfmatch.py` with the pure functions: rank shelves by cosine closeness to a vector, the hit of a placement at each level (topic, subfield, field, domain) given the schema, and the summary of a run;
  stdlib only, no network, no model.
- One read of a sample of OpenAlex works (title, abstract, primary topic) of two designs, saved outside the repository and cited by hash, by a reader of the same hardened kind as the readers of the shelf-schema plan.
- Embedding the shelf names and scope sentences and the sample's texts with two or three of the embedding models of the owner's model server, and the measurement of the embedding step on the sample.
- If the owner agrees after reading that result: the model's choice among the five nearest shelves with one or two chat models, on a subsample, and its measurement.

## Non-goals

- Placing the library's own books, the library's state of a shelf, scouting, the fetch engine, drill-down, `schema-adopt`, the audit of sampled placements, the margin that counts as a tie and the second labels (the spec's other parts of placement); a command for the library to call. They come after this
  result.
- Any change to `docs/specs/shelf.md`, the schema file or its builder, or any roadmap.
- Training or tuning a model, a threshold or a prompt on the sample beyond the one prompt version the plan names (a tuned result would need a second, fresh sample).
- Measuring books. OpenAlex works are the only labelled texts available; books are the matcher's real use and are not measured here (see Risks).

## Assumptions and constraints

- **The ground truth is OpenAlex's own label.** A work's `primary_topic` is the output of OpenAlex's classifier, not a human's judgment, and it was made from a work's title, abstract and other data. Agreement with it measures how like OpenAlex's classifier the matcher is, which is the matcher's
  definition for papers in the spec (a paper takes its home shelf from OpenAlex's primary topic) and a proxy for any other text. The result is read with that in mind.
- **The label is hidden:** the matcher is given the text (title and abstract) and the shelves, never the topic, the subfield, the field, the domain or any other OpenAlex field of the work. The saved sample keeps the label beside the text for the measurement only.
- **The sample (a proposal; the owner may change it):** two designs, both with a fixed seed. **R:** a random sample of 1,000 works that have an abstract and a primary topic (ten requests of 100 with seeds 1 to 10, duplicates removed, for
  an overall figure that follows the real mix of fields). **F:** 20 such works for each of the 26 fields (520 works, 26 requests, to see the fields that R barely reaches). Texts are the title and the abstract rebuilt from OpenAlex's inverted index, cut to 1,500 characters
  so that every model's context fits; a work whose primary topic is not in the schema file is counted and left out. The sample reader makes about 40 requests with no key (OpenAlex allows basic use without a key at 10 requests a second, and the metadata is CC0).
- **What the OpenAlex documentation says, second hand** (read by a helper on 2026-11-14 at `help.openalex.org`, pages `api/authentication`, `data/works/attributes`, `api/selecting-fields`, `how-to/api-recipes` and `access/overview`; no content hash was taken, so these are to be
  confirmed by the first reply of the reader): `sample` has a maximum of 10,000; a `seed` gives a reproducible sample (shown only in a recipe); the abstract is `abstract_inverted_index`, an object from word to positions; `primary_topic` and `topics` carry the topic with its subfield, field and domain; `select`
  takes top-level fields only; the data are CC0. **Not found:** whether paging works with `sample` (the plan therefore uses ten seeds of 100 and no paging), the exact filter names for "has an abstract" (`has_abstract:true` appears in a recipe) and for the primary topic's field, and the topic entry's `id`.
  The first request is made alone, its reply read and the rest of the design adjusted before the others are sent.
- **The embedding models** are those of the owner's model server (`wb run ask-ollama check` on 2026-11-14 lists `bge-m3`, `qwen3-embedding:4b`, `nomic-embed-text` and `mxbai-embed-large` as embedding models, and `phi4`, `gemma4:12b`, `gpt-oss:20b` and `qwen3:14b` as chat models).
  The plan starts with `bge-m3` and `qwen3-embedding:4b` (a long context for each); the owner may add or drop one. The engine calls a model only through an entry of the owner's config; the owner adds the embedding entries by hand (the engine never writes the config) and says when.
- **What is sent to the model server** is public text only: the schema's shelf names and scope sentences, and the titles and abstracts of public OpenAlex works. It goes by plain `http` to the server on the owner's network, unauthenticated, in the clear (the bridge warns of it); nothing of the owner's library, notes or questions is sent.
  The owner says "run it" before each send.
- **The shelf's text for the embedding** is its name, a full stop and its scope sentence (the topic sentences of OpenAlex do not name the topic); the same text for every model. A model's document and query prefix come from its config entry, if any.
- **What is ranked and what is scored (fixed here so that every figure has one meaning).** A placement is at a *home shelf*, which is a topic shelf or a custom shelf, and counts roll up from it to its subfield, field and domain (the spec). So the matcher ranks the **4,534 home shelves** (4,516 topics and 18 custom) by cosine
  closeness to the work's vector, ties broken by the order of the file. From that one ranking: **top-1** is the nearest home shelf and **top-5** the five nearest; a *home hit* is the true topic (for a work whose true shelf is a topic); the *rolled-up hit* of the nearest home shelf is that its subfield, its field or its domain is the true one;
  the **candidate recall** at the subfield or field is that at least one of the five nearest home shelves lies in the true subfield or field (it is what the model's choice step in Increment D would be offered). As information, not part of the bar, the module also gives the **level rankings**: the subfield shelves alone (252), the field shelves alone (26) and the domain shelves alone (4), each ranked
  by their own text, with top-1 and top-5 (top-3 for fields); these say whether matching at a coarser level would do better than rolling up.
- **The bar (my guess; the owner's to set before approving this plan):** the embedding step is good enough to build on if, on sample R with the better model, the **candidate recall at the subfield is at least 80 percent**, the **rolled-up field of the nearest home shelf is the true field for at least 85 percent**, and **no field in sample F has a subfield candidate recall below
  50 percent**; the model's choice step is worth its cost if it raises the home-hit top-one rate by at least 10 points on the same works. Below the bar the result is "misses"; within five points of a figure's bar it is "close" and is reported as such; the plan reports the numbers whichever way they fall. These figures are guesses, not measurements: nothing in the project says what the library needs.
- **Speed.** The engine's Python has no numpy (`import numpy` fails; `weave.py` imports it only where present), and the stdlib is the rule. Ranking one work against 4,816 vectors of 1,024 numbers is about five million multiplications; for 1,520 works that is about 7.5 billion, which pure Python does in
  minutes with `sum(map(operator.mul, a, b))` and in much longer with `math.fsum`. Increment A measures it on random vectors before anything is sent; if it is too slow the plan narrows the search through the levels (domain, then field, then subfield, then topic) and reports both ways, or the owner decides.
- The engine's own code uses the standard library; a reader and a run script outside the repository may too.

## Completion criteria

1. `engine/kb/shelfmatch.py` has tests that were seen to fail first, and deliberate breaks of it are caught.
2. The sample of works was read, and the Result records each request's URL, the retrieval date, the sizes, the hashes, the counts (works asked for, kept, left out and why), and how the real replies differ from the second-hand facts above.
3. The shelves and the sample were embedded with each model the plan runs, and the Result records the model, the dimension, the number of texts, the time, and the hash of each file of vectors.
4. The embedding step's measurement is in the Result for each model, with the exact figures the plan defines and no others standing in for them: on R and on F, and per field in F, the home-hit top-1 and top-5, the rolled-up hit of the nearest home shelf at the subfield, the field and the domain, the candidate recall at the subfield and the field, and, as information, the level rankings' top-1 and top-5 (top-3 for fields); the floor (what always answering the most common
   shelf would score); the run time per work; and 20 misses (the work's title, its true topic, the matcher's nearest three) for the owner to read.
5. The owner has read the result against the bar and said what to do next: the choice step, a different method, more evidence, or build on it.
6. If the choice step was run (the owner's word after criterion 5), its measurement is in the Result with the model, the prompt version, the time per work and the same figures on the subsample.
7. `wb run code-work check` finds no problems, and nothing outside this plan, `engine/kb/shelfmatch.py`, its tests and the engine's README changes in the repository.

## Increments

### Increment A — The pure core of the matcher

**Outcome:** `engine/kb/shelfmatch.py` ranks shelves by closeness to a vector and scores placements at each level, with tests; the speed of the ranking at the real size is known.
**Dependencies:** none (it reads the schema file `engine/kb/data/shelf-schema.json` as data through the checker's loader).
**Affected areas:** `engine/kb/shelfmatch.py` (new), `engine/tests/test_shelfmatch.py` (new), `engine/README.md` (a short section).
**Steps:**
1. Write the tests first on a small schema fixture and small vectors, and see them fail: ranking of the home shelves (topics and custom shelves) by cosine, ties broken by the shelf's order in the file so a run is repeatable; the level rankings (the subfield shelves alone, the field shelves alone, the domain shelves alone); the nearest K; a vector of zeros or of the wrong length refused; the ancestors of a shelf from
   the schema (a topic's subfield, field and domain; a custom shelf has none); each figure of the plan's list, one test for each, on cases where the figures differ (a topic that outranks every other topic of its field while the field-level ranking puts another field first; a candidate recall that is met by the fifth shelf and not the fourth; a custom shelf as the true shelf, which has no subfield, field or domain
   and is counted apart); the summary of many placements (counts, shares, per-field shares, the floor of always answering the most common shelf); and the refusal of a placement whose true shelf is not in the schema.
2. Write the module: the vectors are lists of floats, normalised once; cosine by `sum(map(operator.mul, a, b))`; nothing is read except through arguments; no network, no model, no config.
3. Measure the speed on 4,816 random vectors of 1,024 and 2,560 numbers against 200 random queries, once, with the time recorded; and the same with the search narrowed through the levels.
4. Deliberate breaks (the order of ties, the level of an ancestor, a hit at the wrong level, the floor, the refusal of a bad vector, the normalisation) and their restoring.
5. The `reviewer` agent reads the module, its tests and the speed figures.
**Verification:** `python3 -m unittest engine.tests.test_shelfmatch`, the breaks caught, `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-measure-the-shelf-matcher#A`.

### Increment B — The sample of works

**Outcome:** the sample of OpenAlex works is read once, saved outside the repository with its hashes, and counted.
**Dependencies:** none (it may run before A; the order is A first so that the commit of A is not held by a network read).
**Affected areas:** outside the repository only: a reader, its tests and breaks, and the saved replies in a private folder (mode 700, files mode 600) next to the earlier reads; the plan's Result.
**Steps:**
1. Write the reader on the pattern of the earlier two (fixed address `api.openalex.org`, https only, no redirect, proxy or retry, a size limit and a deadline for each reply, the folder opened once and written through its descriptor, one new file for each reply, a report with the URL, the
   size, the hash and the counts of each, the manifest of the files), with the tests first and deliberate breaks; the query is built from the owner's seed list and field list only and carries nothing else; it selects `id`, `display_name`, `abstract_inverted_index`, `primary_topic` and `topics`.
2. Recommend to the owner a security review of the reader (it reads the network; ask once); run it if the owner says so, and apply its findings.
3. Tell the owner the exact addresses and the number of requests, and wait for "run it". Make the first request alone, read the reply, and adjust the filters and the design in the Result if a name is wrong (nothing sent beyond the design's seeds and fields).
4. Make the rest of the requests (about 40) with a pause between them; save the replies; rebuild each abstract from its inverted index; keep a work only if it has an abstract of at least 200 characters and a primary topic that is a shelf of the schema; count what is left out and why; write the texts and their labels to a results file
   outside the repository (title and abstract cut to 1,500 characters, the label beside it); recount by a second snippet.
5. The Result records the requests, the retrieval date, the hashes, the counts and any difference from the second-hand facts.
6. The `reviewer` agent reads the reader's report of the run and the Result (not the saved replies).
**Verification:** the reader's tests, its breaks, the report of the run read, the counts recounted, `wb run code-work check`.
**Evidence:** the one local commit, which holds the plan's Result and Review record for B, with the trailer `Plan: 2026-11-14-measure-the-shelf-matcher#B`; the reader, the replies and the sample are outside the repository and cited by hash.

### Increment C — The embedding step, measured

**Outcome:** the shelves and the sample are embedded with each model of the plan, the embedding step is measured on R and F, and the Result gives the figures of criterion 4.
**Dependencies:** A and B.
**Affected areas:** outside the repository: a run script and the files of vectors; the owner's config (the owner's hand: the embedding entries); the plan's Result; `engine/README.md` (the speed figures, if A's section says so).
**Steps:**
1. Ask the owner to add the embedding entries to the config (the plan names the models; `python3 -m kb models` lists them; the dimension is read from a trial reply of the model-try command, never guessed), and say what the owner's reading of the bar is, if changed.
2. Embed the 4,816 shelf texts and the sample's texts with the first model through `kb.models.embed`, in calls the engine sizes; save the vectors (mode 600, outside the repository) with the model, the dimension, the prefix hash and the hash of the texts; time it. The owner says "run it" before each model (what is sent: the 4,816 shelf names and sentences and the sample's public titles and
   abstracts, over plain `http` on the owner's network).
3. Rank every work of the sample against the shelves with the module of A; give the figures of criterion 4; list the 20 misses (every fifth miss in the file order, so that they are not chosen).
4. Repeat for the second model. If the owner names a third, the same.
5. The `reviewer` agent reads the run script, the figures and the Result (not the vectors).
6. Report against the bar: "meets", "close" or "misses", with the numbers, and wait.
**Verification:** the run script's own checks (the vectors have the dimension and the count; every work was ranked once; the figures recounted by a second snippet from the saved rankings), `wb run code-work check`.
**Evidence:** the one local commit, which holds the plan's Result and Review record for C, with the trailer `Plan: 2026-11-14-measure-the-shelf-matcher#C`; the vectors and the run script are outside the repository and cited by hash.

### Increment D — The model's choice among the nearest shelves (only on the owner's word)

**Outcome:** the second step of the spec's matcher is measured on a subsample, or the owner decides not to run it.
**Dependencies:** C and the owner's word after reading its result.
**Affected areas:** outside the repository: a prompt, a run script and the saved answers; the plan's Result.
**Steps:**
1. Write the prompt (version `place-1`) and test it first: the work's title and abstract come as **untrusted quoted data** between fixed delimiter lines (a delimiter that occurs inside the text is replaced before it is sent), and the instruction above them says that the quoted text is data to be placed, that any instruction in it is to be ignored, and that the only valid answer is one of the five numbered shelves or the word `none`
   with a one-line reason; the five nearest home shelves of the better embedding model come with their names and scope sentences in a fixed order that does not follow their closeness; the model sees no label. The answer is parsed by a strict reader that accepts exactly one number from 1 to 5 or `none` and a reason of at most 200 characters and refuses everything else (a refusal is counted as a malformed answer, not guessed at). Tests, with a fake model, show the reader refusing an
   answer that names a shelf outside the five, two answers, a number outside 1 to 5, an over-long reason, and showing that a delimiter inside the text is replaced before it is sent. **The reader cannot tell a manipulated answer from a legitimate one** (an injected "choose 2" gives a valid answer), so the strict form is not a defence against steering and the plan does not claim it is.
   What the plan does instead is a **paired behavioural check on the real model**, reported and not tuned on: five invented works, each with an obvious true shelf among the five offered; each is sent twice, once plain (the control) and once with an instruction added to its abstract that tells the model to choose a particular *wrong* shelf of the five; the Result records, for each work, the answer to the control, the answer to the injected text, and whether the injected one chose the target, and the count over the five. This says how easily
   this model is steered by text it is given as data; it is not a proof of resistance. The works placed in the measurement are public OpenAlex abstracts that no one wrote to steer a model, so the risk to the measurement itself is low; the check is for the later use of the matcher on texts from the open web (a crawler), which is not built here.
2. Take a subsample of 300 works (the first 150 of R and 150 of F in the file order) and measure the model's time per work on five works before the rest; tell the owner the estimate and wait for "run it".
3. Run one chat model (the owner picks from `phi4`, `gemma4:12b`, `gpt-oss:20b` and `qwen3:14b`; the plan suggests `gemma4:12b`), save the answers, and measure: the share whose chosen shelf is the true topic, against the embedding step's top-one on the same works; the share whose subfield and field are right; the number of answers refused as malformed; the time.
4. A second model only if the owner asks.
5. The `reviewer` agent reads the prompt, the run script, the figures and the Result.
**Verification:** the run script's checks, the figures recounted by a second snippet, `wb run code-work check`.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-14-measure-the-shelf-matcher#D`; the prompt text is in the Result.

## Verification for the plan as a whole

Each increment's recorded verification stands unless a later one changed its inputs. At the end: the tests of `engine.tests.test_shelfmatch` and `engine.tests.test_shelfschema` are rerun, the hashes of the saved sample and of each file of vectors are compared with those recorded, and `wb run code-work check` is run. The engine's other tests are not rerun: only the README and
the new module change in the repository. What could break outside the tested area: nothing that another module reads (the new module is imported by no command).

## Risks and sensitive actions

- **Texts leave for the model server in the clear.** Only public text goes: shelf names and sentences, and public abstracts; nothing of the owner's. The server is on the owner's network and the bridge warns that the connection is unauthenticated `http`. The owner says "run it" before each send, and is told what and how much.
- **A network read of public data** (about 40 requests to `api.openalex.org`). It sends no query that carries anything of the owner's. The replies are untrusted: parsed as data, size-limited, never run. Parsing untrusted JSON is a place to look for a flaw; the owner is asked once whether to run a security review of the reader (Increment B).
- **The label is a classifier's output, and the classifier saw the same text.** A high figure may only show that embedding the abstract agrees with a model that read the abstract; it does not show that the matcher places a *book* well, and a library book's text (a summary or a card) is not an abstract. The result is evidence about papers; whether it carries to books is open and is
  not measured here (a hand check by the owner of the placement of some of the library's books would be the next evidence, and is deferred).
- **Sampling bias.** R follows the mix of OpenAlex (heavy in medicine and the social sciences); F is flat across fields; neither follows the shape of the owner's library or the wider audience. Both are reported separately and the per-field figures are given.
- **The bar is a guess.** It is the owner's to set before approving the plan; a result near it is reported as "close", not rounded.
- **Pure Python is slow;** A measures it first and the plan changes its search before sending anything if it is too slow.
- **No change** of the library, the cards, the vectors of the cards, the shelf schema, the spec or a roadmap, and **no push** without the owner's word.

## Review record

### The plan (before approval)

Reviewed with Codex through the project's review engine, two rounds of three (the files are in `.workbench/workbench/review-engine/plan-8adec48366d5a48f/`). Round 1: two major findings, both applied (the bar, the figures and the ranker did not mean the same thing, so the plan now ranks only the home shelves and defines each figure, with a test for each;
the chat prompt put untrusted work text beside the instruction, so it is now delimited as data with a strict answer reader). Round 2: one major finding, applied (a steered answer can have the valid form, so the form check did not test steering; the plan now says the reader is no defence and measures susceptibility with five paired works, a control and an injected version).
The repository is public, which the Result of the shelf-schema plan had left unknown; nothing in this plan puts a secret in it.

## Deferred work

- Placing the library's own books and the owner's hand check of those placements; measuring the matcher on books.
- The audit of sampled placements, the margin that counts as a tie and the secondary labels.
- A command of the library that places a work (after the result), the state of a shelf, `schema-adopt`, scouting and the fetch engine.
- A keyword or lexical baseline, if the embedding result is close to the bar and the owner wants to know whether embeddings add anything beyond word overlap.

## Result

Empty until work starts.
