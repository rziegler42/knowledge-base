# Model calls from the engine

Status: Proposed
Created: 2026-11-07
Candidate: cards#model-calls
Specs: models

## Goal

The engine can send one prompt to a model that the owner has listed, through the installed Ollama bridge, and take back one
checked reply together with a record of which model, prompt version and date made it. This is the base that the card stage
(`cards#card-stage`) builds on. When the plan is done the owner can see a call work against their own server, with a fixed short
prompt that holds no book text.

## Scope

- A small registry of models in the owner's config: a name, the bridge, the server name, the model identifier and the limits of
  a call.
- One function that makes a call through the bridge, and the refusals around it: a prompt too large, a model that is not listed,
  the owner's switch off, the bridge not found, a call that runs too long, a reply that is not valid.
- A check of the reply's shape and length, and the generation record (the model the server reported, the prompt version, the
  date, and the tokens used where the server reports them).
- An optional schema for a job, passed to the bridge so that the server shapes its reply.
- Two commands: one that lists the registry and the switch without any connection, and one that makes a single call.
- One live call to the owner's server, on the owner's word, with a fixed prompt that holds no book text.

## Non-goals

- Choosing between models, escalation to a stronger model, quotas, budgets, retries and batching. A call uses the model that the
  caller names.
- Embeddings and the pinned embedding model.
- Cloud bridges and the `--confine` option. The Ollama bridge makes one request to its server and reads at most one bounded
  schema file inside the project, so the property of having no tools holds by construction (`models.md`, "Ways a model is
  called").
- Any change to the bridge, which belongs to the workbench.
- A command to edit the registry or to flip the switch. Both are governed owner actions in the spec; here the owner edits the
  config file by hand.
- Writing a card, or sending any book text to a model.

## Assumptions and constraints

- The bridge takes one prompt of up to 256 KB on standard input and prints one JSON object. On success it holds `contract` (the
  integer 2), `ok` (true), `vendor` (`ollama`), `model`, `reply` and `usage`; on failure it holds `contract`, `ok` (false),
  `vendor` and an `error`. The engine accepts only `contract` equal to 2 and `ok` a real boolean. It is called as
  `wb run ask-ollama ask` with a named server and model, and it finds the project from its working directory, so the engine runs
  it with the project's root as the working directory.
- The bridge reads no file except one: when a call names `--schema`, it reads that single file, which must be a regular file of
  at most 64 KB, with no link in its path, inside the project, and holding one JSON object. The `models.md` sentence that the
  bridge "reads no files" does not mention this option. The plan uses the option only with a schema file that is tracked in the
  engine, and does not edit the spec. Its level in `wb settings` is `none`. This was read in the installed helper on 2026-11-07 and is
  confirmed again by the live call of increment C.
- The server's address is in the workbench's owner-only endpoint file and never in this project. The registry holds only a server
  name. No address, server name or model name of the owner appears in a tracked file, in a test or in this plan.
- The registry and the switch live in the owner's config (`~/.config/knowledge-base/`, mode 600), beside the approved tools, and
  are never tracked. A registry value goes into the command line, so each value is checked against a strict pattern before it is
  used, and none may start with a dash.
- The engine uses only the standard library. The bridge is started as a separate program with an argument list and no shell, and
  its prompt goes in by standard input and never as an argument.
- A reply is model output and is untrusted data, whoever the server is. It is cleaned and marked as untrusted wherever it is shown.
- The server in the owner's set-up is plain HTTP on the owner's network without authentication; the bridge itself warns of this.
  The first live call therefore carries no book text, and whether book text may go that way is the owner's decision at the card
  stage.
- Tests use a fake launcher that records exactly what it receives, so no test touches a network or a real server.

## Completion criteria

1. A call through a fake launcher sends the expected argument list and the prompt by standard input only, and returns the reply and
   a generation record.
2. Each refusal listed in the scope is raised before anything is sent, or ends the call with a clear reason, and none leaves a
   process running.
3. A reply that is not a JSON object of the expected shape, or is too long, is refused and never returned as valid.
4. The two commands work, and the listing makes no connection.
5. One live call to the owner's server returned a reply and a record, and the result is written in this plan.
6. No path or name of the owner appears in a tracked file.

## Increments

### Increment A — The registry and one call

**Outcome:** the engine reads the registry from the owner's config and makes one call through the bridge, with the refusals
around it.
**Dependencies:** none.
**Affected areas:** a new module `engine/kb/models.py` and its tests `engine/tests/test_models.py`. The config loader is not
changed; the module reads the two new keys of the loaded config.
**Steps:**
1. Write the tests first, against a fake launcher program that records its argument list and standard input and prints a chosen
   reply, a chosen exit code or nothing. They fail because the module does not exist.
2. Read the registry: a `models` object of named entries (`bridge`, `server`, `model`, and optionally `max_output`, `thinking`
   and `timeout`) and a `models_on` switch. Check every field against a strict pattern, refuse an unknown key and a value that
   starts with a dash, and treat a missing switch as off.
3. Make the call: build the argument list for `wb run ask-ollama ask` with no shell, run it with the project's root as the
   working directory, send the prompt on standard input, cap the time and the size of what is read back, and kill the process at
   the limit.
4. Refuse before sending: a prompt over 256 KB, an unlisted model, the switch off, a launcher that is not found.
5. Parse what comes back: a failed exit, `ok` false, a contract version other than 2, text that is not JSON, and a missing or
   mistyped field each end the call with a reason cleaned of control characters and cut to a length.
6. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_models` and the config tests `engine.tests.test_setup`, which share the
config module. They are the nearest tests of the new code and of the file it reads.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-model-calls#A`.

### Increment B — The checked reply and the generation record

**Outcome:** a reply is returned only after its shape and length are checked, with a record of how it was made, and a job can pass
a schema to the bridge.
**Dependencies:** A.
**Affected areas:** `engine/kb/models.py`, `engine/tests/test_models.py` and a new folder `engine/kb/schemas/` with one small
schema.
**Steps:**
1. Write the tests first: a schema path that is absolute, holds `..`, is a link, is not a file or is over 64 KB is refused before
   the bridge is started; a reply that is not a JSON object, one with a missing key, a key of the wrong type, an unlisted key or
   a value over its length is refused; a good reply passes; the record holds the model the server reported, the prompt version,
   the date and the token counts where present.
2. Add the shape check. A job states the keys it expects, each with a type and a length limit. Text in a reply is cleaned of
   hidden and control characters, and the result is marked as untrusted.
3. Add the optional schema. A schema is a tracked JSON file in `engine/kb/schemas/`, named by a job. The engine passes the
   bridge its path relative to the project root, after checking that it is a regular file of at most 64 KB with no link in its
   path and that it holds one JSON object. No schema is written at run time, so no temporary file exists. One small schema, for
   the `model-try` command of increment C, is added here.
4. Add the generation record as a plain object that the card stage can store as it is.
5. Run the tests and see them pass.
**Verification:** `python3 -m unittest engine.tests.test_models`. No wider run: the increment touches only the new module.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-model-calls#B`.

### Increment C — The two commands, the live call and the documents

**Outcome:** the owner can list the registry offline and make one real call, and the documents say how.
**Dependencies:** B.
**Affected areas:** `engine/kb/__main__.py`, `engine/tests/test_models.py`, `engine/README.md` and the status section of
`README.md`.
**Steps:**
1. Write the tests first: the listing prints the registry names, the switch and whether the launcher is found, makes no call and
   prints no server name or address; the call command takes a model name and reads the prompt from standard input.
2. Add the commands (`models`, which lists, and `model-try`, which makes one call and prints the reply with its record and the
   untrusted mark).
3. Stop and ask the owner to add one entry and the switch to the config. On the owner's word I make that edit, after a backup of
   the config, as in earlier plans.
4. On the owner's word, make one live call with a fixed prompt that holds no book text, and read the result. Compare it with the
   contract that increment A assumed. Note how long the call took and whether starting the bridge for each call costs enough to
   matter (`models.md`, open questions).
5. Document the registry keys, the switch and the two commands in `engine/README.md`, and add one sentence to `README.md`.
6. Record the live call in this plan's Result.
**Verification:** `python3 -m unittest engine.tests.test_models` and the live call of step 4, run as written and read.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-07-model-calls#C`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. After C, rerun
`python3 -m unittest engine.tests.test_models` once. The wider engine suite is not named: the plan adds a module and two
commands and changes no existing code path. The one existing file it edits is `engine/kb/__main__.py`, so the existing tests that
start the command line (`engine.tests.test_setup`) are rerun too. A wider run is the owner's to ask for.

## Risks and sensitive actions

- **A subprocess built from config values.** A registry value reaches a command line. Mitigation: strict patterns, no dash at the
  start, an argument list with no shell, and tests that pass hostile values through a fake launcher.
- **A network call.** The live call sends a short fixed prompt to the owner's server over plain HTTP on their network. It carries
  no book text and needs the owner's word. Sending book text is the card stage's decision.
- **Untrusted output.** A reply is cleaned, checked and marked as untrusted before it is returned.
- **Edit of the owner's config.** Adding the registry entry is a write to a file outside the project. It is made only on the
  owner's word, after a backup, and is not committed.
- **A process left running.** A call that hangs is killed at its time limit; a test shows that no process is left.

## Review record

Reviewer: Codex through the review engine (model gpt-5.6-terra). Round 1 of 3: changes needed, two findings, both applied.

- R1-F1, applied: the plan named a contract version to check but not the field. The bridge's success reply carries `contract`
  (2), `ok`, `vendor`, `model`, `reply` and `usage`, read in the installed helper; the assumptions now say so.
- R1-F2, applied: the plan said the bridge reads no files and then wrote a schema file for it to read. The bridge does read one
  bounded schema file, and only from inside the project, so a temporary folder would have been refused. The schema is now a
  tracked file in the engine, and the assumptions state the exception.

Left for the owner: the sentence in `models.md` that the Ollama bridge "reads no files" does not mention the schema option. The
plan does not edit the spec.

## Deferred work

- Choosing between models, escalation, quotas and budgets (`models.md`).
- Embeddings and the pinned embedding model, which belong to a later candidate for search by meaning.
- A command to edit the registry and to switch model work on and off, as governed owner actions.
- A doctor warning that a server is reached over plain HTTP without authentication.
- Retries, batching of many short items, and cloud bridges with `--confine`.
- Showing each model's health in a report.

## Result

Empty until work starts.
