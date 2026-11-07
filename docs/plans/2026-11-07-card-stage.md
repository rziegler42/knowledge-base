# The card of a book

Status: In Progress
Created: 2026-11-07
Candidate: cards#card-stage
Specs: card

## Goal

A converted book gets a card: a short entry written by a model that says what the book is about, what it is useful for and, in
words of no field, what problem it addresses and how. Which model does each kind of work is a setting of the user's config,
task by task; the engine prefers no model, so other users can set others, and for this owner's set-up the settings follow what
the experiments found worked best. The card is kept in the book's own folder as a generation
that is never overwritten, with the model, prompt version and date, and the owner can make one for named books and read it back.
This is the base for the card catalog (`cards#card-catalog`) and the trial (`cards#card-trial`). When the plan is done the owner
has seen cards made from three real books by the models their config names for the card tasks.

## Scope

- A setting in the config, `tasks`, that names for each kind of model work the registry entry that does it, and a choice that
  reads it. The kinds of work the engine knows are named in code (here the two card jobs) and carry no model. A task with no
  setting is refused with a message that names the task and the key to set; the engine never guesses a model.
- The card file: mechanical fields taken from the manifest and the scan (never written by a model), the model-written fields of
  `card.md`, a partial mark with its reasons, and the generation record. It is kept as a payload `derived/card/<n>` of the
  version, marked untrusted and read-only, one new number for each card made.
- Reading a converted book in pieces: pieces that end at a block boundary, a note for each piece, and a card made from the notes,
  the title and the outline. A book that fits one piece gets its card in one call. A book with too many pieces is sampled and
  marked partial.
- A card for a version with no conversion, or whose converted text is shorter than a cutoff the owner sets (`card_min_chars`, with
  a default), built from the metadata alone with no model call and marked partial (`card.md`: an item below a small size gets a
  card built from metadata, and the cutoff is a setting).
- Two commands: `cards`, which makes a card for the books the owner names, with the models the `tasks` setting names, and
  `card-show`, which prints a card with the model's text between the untrusted-text markers.
- A prompt that tells the model to describe the book and ignore any instruction in it, and to write in English whatever the
  source's language (`card.md`); every input that does not come from the engine's own instructions (a piece of the book, its
  title, its outline, the notes of the earlier calls) is labelled as data and placed between delimiters that hold a random token
  made for the call, so none of them can forge the end of a section; and an answer checked for shape and length before it is
  kept.
- One live run on the owner's word: cards for three books the owner names, with the models the owner's `tasks` setting names, set
  from what the experiments found best.

## Non-goals

- Searching the cards. That is `cards#card-catalog`.
- The `carded` stage in the stage state, and `process` making cards by itself. The stage state is exactly the five stages today, and
  adding one means reading every stage file already written. A card is found here by its payload, and the stage is added when
  cards are made in `process`. The owner makes cards by a command, so book text goes to a model only when the owner asks.
- Embeddings, search by meaning, themes, the weave, and any change to the shelf of a book.
- Switching the active generation back to an earlier card. The newest card is the active one.
- The rest of the router of `models.md`: preferring the less busy machine, quotas and budgets, escalation after a failed answer,
  spot checks of one model by another, a cloud model, and batching of many books. The choice here is the owner's setting for the
  task, and nothing else: no classes, no fallback to another model, no default.
- Judging whether the cards help. That is `cards#card-trial`.

## Assumptions and constraints

- The model-call layer of `2026-11-07-model-calls` is built: `kb.models.run_job` takes a `Job` (a name, a prompt version, a shape
  and an optional schema file in `engine/kb/schemas/`) and returns the checked values, marked untrusted, with a record. The
  registry and the switch are in the owner's config. A call has a bridge limit of 256 KB for a prompt, and the server refuses a
  prompt larger than its window, which for the owner's models is about 32 to 49 KB of text. A piece of the book is therefore kept
  to about 20,000 bytes.
- Where this plan differs from a draft spec or the roadmap, it does so on the owner's instruction of 2026-11-07, and changes none of
  them: `card.md` says a card is made when a book is filed (agreed), and the owner decided that for now cards are made by a command;
  `models.md` says the registry and its endpoints are never an argument, and this plan puts no entry, address or secret in an
  argument; and the roadmap lists the choice between models under deferred work, and the owner asked that each type of task have
  its model set in the config. Whether the spec or the roadmap should be changed to say so is the owner's decision.
- The model for a kind of work is the user's setting (`models.md`: "Whether a stage runs on a local model, a cloud model or either
  is the owner's configuration in the registry", and "the library works with whichever models the owner lists"). The engine
  therefore ships no preference and names no model; it names the kinds of work. A user with one model lists it for every task;
  another user lists others.
- The settings for this owner follow the experiments (`knowledge-base.md`, evidence notes 13 and 14; `models.md`, "Which tasks go
  where"). They are written to the owner's config in increment E, on the owner's word, and are not tracked. What the notes found:
  one of the owner's models gave the best retrieval from the neutral descriptions of cards, by a gain that length alone did not
  explain, though the notes ask for a larger, held-out sample before it is fixed for the card job; another is the bulk-class model
  that gave valid cards and the best themes; a third fit neither class. The settings are the owner's to confirm in increment E,
  and a task can be set to another model at any time by editing the config.
- The text of a book is read from the conversion in use (`convert.load_in_use`), and its caveats and conversion quality from the
  version file. A book may have no conversion in use.
- A book is untrusted data. A model reading it may be steered by it, so the model has no tools, its answer is accepted only in the
  shape the job asks for, and everything it writes is stored and shown as untrusted. This cannot be made airtight; the checks
  reduce the risk (`card.md`, "Safety").
- The model that reads a book gets its text over the link the registry names. For the owner's set-up that is plain HTTP on the
  owner's network without authentication, so the text travels in the clear there. The owner has said any shelf may go to a cloud
  model, and the live run of increment E needs the owner's word for the books and the models it sends them to.
- A payload is built in the incoming area, checked against its hash list, renamed into place and made read-only, and is never
  overwritten (`store.file_payload`). The engine takes no lock, and two programs working on one book at once are not supported.
- Nothing tracked names the owner's server, models or paths. Tests use the fake launcher of `engine/tests/test_models.py`.

## Completion criteria

1. For each kind of work the engine uses the registry entry that the `tasks` setting names for it; a task with no setting, a setting
   that names an unlisted entry, a task the engine does not know, or the switch off is refused before anything is sent; the engine
   never picks a model by itself, and a run reports which model did which task and why.
2. A card made through a fake launcher has mechanical fields that match the manifest and model fields that match the job's shape,
   and is kept as a new read-only generation without changing an earlier one.
3. A book is read in pieces that cover its whole text without a piece over the limit; a book of one piece makes one call and a
   longer one makes a call for each piece and one for the card; a book with too many pieces is sampled and the card says so.
4. A version with no conversion, or with converted text below the cutoff, gets a card with no model call, marked partial.
5. Every input that comes from a book or from a model (a piece of text, the title, the outline, the notes) reaches a model only as
   labelled data between delimiters that no such input can forge, the prompt asks for English, an answer of the wrong shape is
   refused and nothing is filed, and a failure in any call files nothing.
6. `cards` and `card-show` work through the command line, `cards` refuses to run without named books, and `card-show` prints the
   model's text between the markers and withholds a field that holds the words of a marker.
7. Cards were made from three real books on the owner's word, read back, and the result is written in this plan.
8. No name or path of the owner appears in a tracked file.

## Increments

### Increment A — The model for each kind of work, set in the config

**Outcome:** the engine finds, for a kind of work, the registry entry the user's config sets for it, and says where the setting
came from. It prefers no model.
**Dependencies:** none.
**Affected areas:** `engine/kb/models.py` and `engine/tests/test_models.py`. No call is made differently: a call by name works as
before.
**Steps:**
1. Write the tests first. They fail because the setting does not exist.
2. Name the kinds of work the engine knows (the two card jobs, `card-notes` and `card`) in one place in `models.py`, with no model
   attached to any of them.
3. Read a `tasks` object of the config: each key is a known kind of work and each value the name of an entry of `models`. Check it
   like the rest of the registry: an unknown kind of work, a value that is not a name, or a name that is not listed refuses the
   whole registry, so a typo is found at once and not on the first call.
4. Add the choice for a task: it needs the switch on, and returns the entry the config sets and a reason in words (`set for card in
   the config`). A task with no setting is refused with a message that names the task and the key to set.
5. Show the settings in the `models` listing, by task and entry name only.
6. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_models`. It is the only test file of the module that changes, and its
command tests cover the listing.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-stage#A`.

### Increment B — The card file and its storage

**Outcome:** a card can be built from a version's manifest, filed as a new generation and read back, with no model involved.
**Dependencies:** none.
**Affected areas:** a new module `engine/kb/card.py` and its tests `engine/tests/test_card.py`. The store and the conversion
code are read, not changed.
**Steps:**
1. Read the code that lists or reads the payloads of a version (`store`, `convert`, `scan`, `index`) to confirm that a second kind
   of derived payload next to the conversions and the scan breaks none of it. Write down what was read in the Result.
2. Write the tests first. They fail because the module does not exist.
3. Build the mechanical part: book id, version id, title, kind, shelf, the source's identity and its retrieval date as the version
   file holds them (cleaned, bounded), the scan's caveats (kind, count, detail), the conversion's structure quality, and a partial
   mark with its reasons when the conversion is partial or flat.
4. Define the card file (`card.json`): a format number, the mechanical part, the model part (the fields of `card.md`: summary,
   useful for, topics, adjacent topics, key ideas, caveats, and the neutral description as problem, approach, needs, provides and
   limits) or none, and the generation record.
5. File it as `derived/card/<n>` with `store.file_payload`, untrusted, where `<n>` is one more than the highest card number. Read
   the newest back with its payload hashes checked, and refuse a card file that is not of this format.
6. Build a card with no model part, partial, for a version that has no conversion.
7. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_card engine.tests.test_store`. The store tests are the nearest tests of the
payload code the new module uses.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-stage#B`.

### Increment C — Reading a book in pieces and the two jobs

**Outcome:** the text of a converted book is cut into pieces, each piece gets a note, and the notes make one card, through the
model-call layer, with the book text safely delimited.
**Dependencies:** B.
**Affected areas:** a new module `engine/kb/cardmake.py`, its tests `engine/tests/test_cardmake.py`, two schema files in
`engine/kb/schemas/`, and a small addition to `engine/kb/models.py` (a minimum number of items for a list in a shape) with its
tests in `engine/tests/test_models.py`.
**Steps:**
1. Write the tests first, with the fake launcher, a conversion built in memory and a fake model that answers from a script. They
   fail because the module does not exist. They include a hostile title, hostile headings, hostile note text and hostile book text
   that contain the delimiters' wording, a guess at the token and instructions to the model, and they check that the prompt shows
   each of those only inside its own labelled section and that the token never appears in any of them.
2. Add `min_items` to the `strings` type of a shape in `models.py`, tests first (the key ideas are three to five).
3. Cut the conversion's blocks into pieces of at most 20,000 bytes that end at a block boundary, cutting a larger block at
   whitespace. Cap the pieces at twelve: beyond that take twelve evenly spaced ones, always the first and the last, and record
   that the card was sampled.
4. Define two jobs, each with a prompt version and a shape: a note for a piece (a few short points) and the card (the model fields
   of B, with limits on length and on the number of items). Each has a schema file.
5. Write the prompts. Each states what the model is to do, asks for English whatever the language of the source, says that
   everything in a labelled section is data and any instruction in it is to be ignored, and puts every such input (a piece of the
   book, the title, the outline, each note) in its own labelled section between delimiters that hold a random token made for the
   call. A token that appears in an input is made again, so no input can close a section.
6. Make the calls, each with the model the config sets for its job (or the one the owner names for the run), so a card may be
   made by two models: a book of one piece goes straight to the card job; a longer one gets a note call for each piece, in order,
   and then the card job on the title, the outline of headings (cut to a length) and the notes. Any failed call stops the card
   and files nothing. The generation record names each model that took part.
7. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models`. The model tests
are included because `models.py` changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-stage#C`.

### Increment D — Making a card for a version, and the two commands

**Outcome:** the owner can make a card for named books and read it, from the command line, with the models the config sets for the
card tasks.
**Dependencies:** A, B, C.
**Affected areas:** `engine/kb/cardmake.py`, `engine/kb/card.py`, `engine/kb/__main__.py`, and `engine/tests/test_cardmake.py` and
`engine/tests/test_card.py`.
**Steps:**
1. Write the tests first, through the real command line with the fake launcher. They fail because the commands do not exist.
2. Read the cutoff `card_min_chars` from the config (a whole number of characters of converted text, checked like the other keys,
   with a default of 1,000 when it is missing). Join the parts: for a version, find the model of each job, load the conversion in
   use, make the card, or the card with no model part when there is no conversion or its text is below the cutoff, and file it. Refuse a version with an unfinished conversion step and say why; skip a book that already has a card unless
   `--again` is given, which adds a new generation.
3. Add `cards --book ID`, with the book option repeated for more books and required, so no run covers the library by default. The
   models are the ones the `tasks` setting names, and no model, entry or address is an argument. It prints one line of JSON for
   each book: the book, the version, `carded`, `skipped` or `failed`, the generation, whether the card is partial, the pieces, the
   calls, the model used for each job and why, and the reason. It prints no card text. It exits 1 if a book failed.
4. Add `card-show BOOK_ID` (with optional version and generation). It prints the mechanical fields, then the model's fields as one
   text between the markers of `search.MARKER` and `read.END_MARKER`, and withholds any field that holds the words of a marker.
5. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_setup`. The setup
tests are included because `__main__.py` changes.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-stage#D`.

### Increment E — Cards for three real books, and the documents

**Outcome:** the owner has cards made from three real books by the models their config sets for the card tasks, has read them, and
the documents say how.
**Dependencies:** D.
**Affected areas:** the owner's config (not tracked), `engine/README.md` and the status section of `README.md`.
**Steps:**
1. Propose to the owner the `tasks` settings that follow the experiments (evidence notes 13 and 14), naming the model for each of
   the two card tasks and the entries that are missing from the registry, and ask which three books to use (one short page, one
   paper, one long book). On the owner's word I back up the config and write the settings and the entries, with thinking off for
   the models that write cards.
2. Stop and ask the owner for the word to send the text of those three books to those models, over the link the registry names.
3. Make a card for each book with `cards`, with no model named, so each task uses the model the config sets. Note the pieces, the
   calls, the models, the time and the tokens for each. If the owner wants a different model for a task, the owner edits the
   `tasks` setting and the card is made again as a new generation.
4. Read each card with `card-show` and note, without judging the cards (that is the trial): whether the model fields are present,
   whether the neutral description leaks the book's field, and whether the output stayed within its limits.
5. Document the `tasks` setting (the kinds of work the engine knows and how another user sets their own models), the two commands
   and the card file in `engine/README.md`, and add one sentence to `README.md`.
6. Record the run in this plan's Result.
**Verification:** `python3 -m unittest engine.tests.test_card engine.tests.test_cardmake engine.tests.test_models` once more, and
the live run of steps 3 and 4, run as written and read.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-card-stage#E`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After E, rerun the three test
files for cards and the model tests once. Increments A and C change `models.py`, and D changes `__main__.py`, so
`engine.tests.test_models`, `engine.tests.test_store` and `engine.tests.test_setup` are rerun too. The wider engine suite is not
named: the plan adds modules and two commands, and changes no stage, no index and no conversion. A wider run is the owner's to ask for.

## Risks and sensitive actions

- **Book text goes to a model.** Increment E sends the text of three books over a link that, in the owner's set-up, is plain HTTP
  on their network. It needs the owner's word for the books and the models. No other step sends book text.
- **A wrong setting sends work to the wrong model.** The model for a task is the user's setting. A typo is refused when the
  registry is read, a missing setting is refused and never guessed, the run reports the model it used for each job and why, and the
  card records the models.
- **A book steers the model.** The text may carry instructions. The model has no tools, the delimiters hold a random token, the
  prompt names the text as data, the answer is accepted only in its shape and length, it is stored and shown as untrusted, and a
  field with the words of a marker is withheld when shown. A model can still write misleading words, and a card is a lead to
  follow, not a claim to rely on.
- **Cost and time.** A long book makes up to thirteen calls. The pieces are capped at twelve, each call has the time limit of the
  registry, and a run covers only the books the owner names.
- **A second kind of derived payload.** Step 1 of increment B reads the code that touches the payloads before anything is filed.
- **Edit of the owner's config.** New registry entries and task settings are written only on the owner's word, after a backup, and are not
  committed.
- **Cards that look authoritative.** A card is model output about a book and may be wrong. It is marked untrusted and partial where
  the source was incomplete.
- **A larger plan than its candidate.** The roadmap lists the choice between models as deferred work. This plan takes a bounded part
  of it, a model set in the config for each kind of work, because the owner asked for that. Escalation, the less busy machine,
  quotas and spot checks stay deferred.

## Review record

Reviewer: Codex through the review engine (model gpt-5.6-terra). Round 1 of 3: changes needed, five findings. Four applied, one
rejected on the owner's instruction and left for the owner.

- R1-F3, applied: the delimiter safeguard covered only a piece of the book. The title, the outline and the notes also reach the
  card job and are source-derived or model-derived, so every such input now gets its own labelled section with a per-call random
  token (made again if an input holds it), and the tests include hostile titles, headings, notes and text.
- R1-F4, applied: the card spec's agreed behaviors of English whatever the source's language, and a metadata-only partial card for
  an item below a size cutoff that is a setting, were missing. The prompt now asks for English and a `card_min_chars` setting
  (default 1,000 characters of converted text) sends a small item to the card with no model call.
- R1-F5, applied: `--model NAME` on `cards` made a registry entry an argument, against `models.md`, and it also bypassed the task
  settings. It is removed; the owner changes a model by editing the `tasks` setting.
- R1-F2, applied as a record: the agreed behavior that a card is made when a book is filed is not built, because the owner decided
  that for now cards are made by a command. The plan now says so and lists the filing step as deferred. The spec is not edited;
  whether it should be is the owner's decision.
- R1-F1, rejected for now: the review says the candidate leaves the choice between models out. The roadmap lists that choice under
  deferred work and the boundary of `cards#model-calls` excludes it; the boundary of `cards#card-stage` does not. The owner asked
  on 2026-11-07 that each type of task have its model set in the config, and the owner's instruction comes first. The plan records
  the difference in its assumptions and risks. Left for the owner: whether to add a roadmap candidate for it, which is a change of
  direction that waits for the owner's word.

## Deferred work

- The `carded` stage in the stage state, and `process` making a card when a book is filed (the agreed behavior of `card.md`), once
  the owner has seen what a card costs and is.
- Searching the cards (`cards#card-catalog`) and the trial of whether they help (`cards#card-trial`).
- Escalation after a failed answer, the choice of the less busy machine, quotas and budgets, spot checks, a cloud model and
  batching; and the names of kinds of work that do not exist yet, such as themes and judging.
- Revising the owner's settings by evaluation: the notes ask for a held-out sample before the stronger model is fixed for cards.
- Switching the active generation back to an earlier card, and making cards again for a whole shelf.
- Embeddings and search by meaning.
- Checking a card for leaked field words by code. The live run only looks at it.

## Result

### Increment A — The model for each kind of work, set in the config (2026-11-07)

Added to `engine/kb/models.py`: `TASKS` (the kinds of work the engine knows, `card-notes` and `card`, with no model attached to
either), `_settings` (checks the `tasks` object of the config: an unknown kind of work, a value that is not a name, or a name that
is not listed is refused), `choose` (the entry the setting names and a reason, `set for <task> in the config`; the switch must be
on; a task with no setting is refused with the task and the key to set, even when only one model is listed) and a `tasks` entry
of the listing (kind of work and entry name only). `registry` now checks the setting too, so a wrong setting refuses the whole
registry, and a call by name as well. The engine never picks a model on its own.

Verification run: `python3 -m unittest engine.tests.test_models engine.tests.test_setup` gave 124 tests, OK (94 in
`test_models`, 15 of them new: 13 in `TaskTest` and 2 command tests). Tests were written first and failed because the setting did not
exist. Seven deliberate breaks of the new code were each caught (the engine guessing the only listed model; a bad setting not
refusing the registry; an unknown kind of work accepted; a setting naming an unlisted entry; `choose` ignoring the switch; the
reason not saying where the setting came from; the listing leaving the settings out). Not run: any other test file, and any live
call, which this increment does not make.

Review: the `reviewer` agent, one exchange, no blocking findings. Applied: the module docstring said nothing here chooses between
models, which `choose` made untrue; it now says what the module does. Noted, not changed: `choose` reports a wrong setting before
it reports the switch off, which follows from refusing the whole registry. The owner's config was not touched; the `tasks`
settings for the owner's models are written in increment E, on the owner's word.

### Increment B — The card file and its storage (2026-11-07)

Step 1, the read of the payload code: the version file's payload list is read in one place outside the store (`convert` reads
`payloads["original"]`); `set_version_conversions` writes only the conversion records; the conversion and the scan list only
`derived/<their own tool>`; nothing walks all of `derived/`; `stages.reconcile` and `store.adopt_payload` act only on a name the
caller passes; the payload name rule already allows `derived/card/<n>`. A second kind of derived payload breaks none of it. A latent
point: the store's tool-name rule would accept a conversion tool named `card`, and nothing can produce one today (the tools are a
fixed list).

Added `engine/kb/card.py`. `mechanical` builds the part that no model writes: the book, version, title (under the title rule,
and cleaned of the library folders twice), kind, shelf, the type of the primary file, the source record, the scan status and
caveats, and the conversion's structure with the reasons the card is partial (no conversion, a partial conversion with its
reasons, a flat one). The source record keeps only six named keys, each under its own rule: an address only if it is a web
address with no user name (the rule `read._address` already uses), an arXiv id, a label and a hash only in their forms, and a
retrieval date only as a date. `make` adds the model part (checked and cleaned by the model-call layer against the fields of
`card.md`), the records of how it was made, the counts and further reasons, and refuses a card that is not valid; with no model
part the card is built from the metadata and marked partial. `file` files the next `derived/card/<n>` through `store.file_payload`,
untrusted and read-only; `read` returns the newest or a named generation after the hash check, with exactly the card file in the
payload, the size checked first, and the card belonging to the book and version asked for. `validate` is the gate for both: exact
keys and types, text from a book or its source already in its clean form (the title also under the rule that blanks the words of
an untrusted-text marker), and a partial card with its reasons.

Verification run: `python3 -m unittest engine.tests.test_card engine.tests.test_store` gave 80 tests, OK (45 new in
`test_card`, 35 in `test_store`). Tests were written first and failed because the module did not exist. Twenty-one deliberate breaks
were checked; twenty were caught. Two breaks survived on the first pass and were fixed: my test of an extra file in the payload
refused for the wrong reason (a card for another book), and nothing tested that the library folders are taken out of the scan
text. One break still survives and is equivalent: the key allowlist is enforced both where the source is read and in the shape
check, so removing either changes nothing. Not run: any test file besides these two, and any live call (no model is involved).

Review: the `reviewer` agent, one exchange, no blocking findings, and it agreed with the step 1 reading. Applied: a source address
now follows the citation rule (finding 1), the title is cleaned of the library folders after cleaning as well as before (finding
2; the store already cleans a title when it is written, so this guards a title written some other way), and `validate` now
requires the text of a card to be clean, so a card read back cannot carry control characters or marker words that a card made
would have lost (finding 3); the tests for the three branches the reviewer found untested were added (format on reading, a link
for a generation folder, a card over the size limit, a hostile title). I also found, by tracing the clean-text rule, that a
conversion reason of 500 characters plus its prefix would have made a valid card fail its own check; it is cut, with a test.
Noted for later increments: the shape of the key ideas has no minimum yet, which increment C adds (`min_items`); `card-show` in
increment D must still wrap the mechanical text in the markers, because a hash list sits in the same folder as the card and the
words of a marker are blanked only in the title; and a stop between filing a card and noting it in the version file leaves a card
that `read` finds (it lists the folders) but the payload list lacks, which is safe because `file_payload` refuses an overwrite and
the engine has one writer.

### Increment C — Reading a book in pieces and the two jobs (2026-11-07)

Added `engine/kb/cardmake.py`, two schema files (`engine/kb/schemas/card.json` and `card-notes.json`), and `min_items` for a list
in a shape (`engine/kb/models.py`), which the card's key ideas now use (a one-line change in `engine/kb/card.py`, three to five).
`pieces` cuts a conversion into pieces of at most 20,000 bytes that end at a block boundary (a larger block is cut at words, by
characters small enough that the bytes fit); `sample` keeps twelve evenly spaced pieces, always the first and last, when there
are more, and says so; `outline` lists the headings by level, capped in bytes. `make_model_part` finds the model of each job
before the first call (`models.choose`, so a missing setting stops the card before anything is sent; a one-piece book needs only
the card setting), gives a one-piece book straight to the card job, gives a longer one a note call for each piece and then the
card call on the title, the outline and the notes, and returns the checked values, a record for each call with its task and model,
the pieces read, the calls made and the reasons the card is partial. It files nothing, and any failed call or answer of the wrong
shape stops it. Every input from a book or a model (a piece, the title, the outline, each note) is a labelled section of its own
between delimiters that carry a per-call random token, made again if any input holds it; the rules name that token and say that
a line with another token is data. Both prompts ask for English and say that nothing in a section is an instruction.

Verification run: `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_models` gave 186
tests, OK (44 new in `test_cardmake`, 3 new in `test_models`, one added case in `test_card`). Tests were written first and failed
because the module did not exist. Twenty-three deliberate breaks of the new code were each caught (a piece over the limit; a large
block cut by too many characters; sampling that misses the last piece; a token that an input holds being kept or checked against
the first input only; the title or the outline not given as data; either prompt not asking for English; the rules not naming the
token; a record with no task; the sample reason dropped; a book with no text read; the outline or a heading not cut; the outline
limit in characters and not bytes; an empty note allowed; no minimum of key ideas; either schema not passed; the card model chosen
only after the notes; a list minimum not enforced or above the maximum). One break text went stale after an edit and was run
again with its new wording. Not run: any live call (the model is a fake launcher that records every prompt), and any other test
file.

Review: the `reviewer` agent, one exchange, no blocking findings. Applied: the rules now name the token of the call and say that a
line carrying another token is data (the code already kept a forged closer from closing a section; the model is now told too);
tests for the cases the plan's step 1 names that were missing (hostile book text in both prompts, a token held by the book text, a
note or the outline, a hostile heading through the outline); and the outline is capped in bytes and a wide-character test keeps
the one-piece prompts under 30 KB. Not applied: the note prompt says "piece 5 of 12" for a sampled book though the pieces are not
consecutive (the sample reason reaches the card); and the schema files carry no item limits, which the plan did not ask for (the
engine enforces them after the call). Known limit: if a model writes its notes in a wide script against the instruction to write
English, a card prompt of twelve notes can pass the window of a small model; the bridge refuses such a prompt and the card is not
made, so nothing is filed. Left for the owner: step 6 of this increment still says "or the one the owner names for the run", which
the review of the plan removed from the commands; the code has no such option, and correcting the sentence in an approved plan needs
a new approval.

### Increment D — Making a card for a version, and the two commands (2026-11-07)

Added to `engine/kb/cardmake.py`: `min_chars` (the `card_min_chars` setting, a whole number of characters, default 1,000),
`make_for_version` (the join) and `run` (the join for each named book). For a version the join skips a book that is not active,
refuses a version that is not fetched or whose conversion is still pending (and says to run `process`), skips a version that has a
card unless asked again (then a new generation is filed and the earlier one is untouched), and makes the card: from the metadata
alone, with no model call, when there is no conversion or its text is below the cutoff, and otherwise through `make_model_part`
with the models the `tasks` setting names. `run` refuses an unknown book before any work, and a book that fails (any exception, as
`process` treats a version) is reported as failed with its version and reason while the others go on. Added to `engine/kb/card.py`:
`render`, the text of a card for a reader, in which every piece of text from a book, its source or a model goes through one rule: it
is cleaned, and withheld if its letters hold the words of an untrusted-text marker (a list is withheld item by item, and as a whole
if the words are split across its items); and a record date must now be an ISO date. Added to `engine/kb/__main__.py`: `cards --book
ID` (repeatable and required, so no run covers the library by itself; `--again`; no model, server or class is an argument; model work
and the card setting are checked before any book is touched; one line of JSON for each book with no card text; exit 1 if a book
failed) and `card-show BOOK_ID` (`--version`, `--generation`; the facts that cannot hold free text outside, the rendered text of the
card between the markers of `search.MARKER` and `read.END_MARKER` inside).

Verification run: `python3 -m unittest engine.tests.test_cardmake engine.tests.test_card engine.tests.test_setup` gave 154 tests,
OK. Tests were written first and failed because the commands and functions did not exist; they run the commands through the real
command line against a real temporary library with converted books, and a fake launcher in place of the model. Twenty-six deliberate
breaks were each caught (the date rule, the withholding, what is rendered, the cutoff, the skip and `--again` rules, the refusal of
a book not fetched, not converted, not active or unknown, a failure stopping the other books, a boolean as a cutoff, the current
version, the early check of the card setting, the `--again` option, the markers of `card-show`, its generation, the exit code, the
split-words rule, the catch of any exception, the version in a failed report). Three broke at first through gaps in my tests (the
partial reasons not asserted, the not-fetched refusal passing through the not-converted one) and were fixed; one break text of mine
was meaningless and is not counted. Not run: any live call (the next increment makes it), and any other test file.

Review: the `reviewer` agent, one exchange, no blocking findings. Applied: words of a marker split across the items of a list are
now withheld as a line; `run` catches any exception for a book, as `process` does, and a failed report names the version; a test
for a generation of 0 or -1. The reading of the plan's "refuse a version with an unfinished conversion step" that the owner may
want to change: a version whose conversion is pending or whose book is not fetched is refused, and one whose conversion failed or
was skipped gets a card from its metadata, as `card.md` says for a book with no conversion. The cost is that such a card counts as
"has a card", so a later `cards` run skips the book until `--again` is given, which is what to use after a failed conversion is
made good. Not changed: the early check of the card setting refuses a run whose books would all get metadata-only cards; this is
safe and consistent with the plan's first criterion.
