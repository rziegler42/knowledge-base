# Models

Status: Draft

This specifies how the knowledge base uses language and embedding models: the registry of models, how a model is chosen for a task,
how work escalates from a cheaper model to a stronger one, how quotas and switches limit use, and how the choice of embedding
model is pinned. It belongs to the design in `knowledge-base.md` and serves the pipeline (`pipeline.md`), the card (`card.md`), the
theme (`theme.md`) and the shelf rules (`shelf.md`). **Nothing here is final.** The spec stays `Draft` until the owner approves it,
and any statement can be reopened. Each statement carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

Much of this spec was split out of `knowledge-base.md`, and those statements keep their marks. The rest was added in the
conversation that followed.

## Scope

The library does its model work through a registry of models that the owner controls. This spec covers what the registry holds, the
paths by which a model is called, the router that picks a model for a job, escalation, quotas and budgets, the on/off switches and
draining, the embedding model, privacy of what is sent, what is recorded about each call, and how the quality of a model is checked.
It does not cover what a stage does with a model's output (the specs of the pipeline, card and theme), or the workbench's own bridge
rules, which this spec depends on.

## Non-goals

- **[proposed]** Training or fine-tuning models. The library uses models as they are.
- **[proposed]** Running a model runtime for the owner. A model server is the owner's to install and keep, and the registry only
  records how to reach it.
- **[proposed]** Judging a vendor's terms. The owner reads each vendor's terms on automated use before a subscription is used for it.
- **[proposed]** Choosing the best model in general. The router picks the best enabled model that fits a job, and the evaluation
  (`testing.md`) is how quality is compared.

## Assumptions and constraints

- Model calls go through the workbench's vendor bridges (decision `2026-10-22-model-calls-go-through-vendor-bridges`; spec
  `model-bridge`). A bridge is one thin module per vendor. It takes one prompt of up to 256 KB on standard input and returns one
  JSON reply of up to 256 KB, and it does not choose the model, retry or fall back. Installing a bridge is the owner's consent to
  send content to that vendor.
- Only `ask-codex` is built. A vendor program a bridge wraps can read files itself, so a bridge is not blind even when read-only
  (`model-bridge`, "What the vendor program can read"). The property "no tools, no network" holds for local endpoints and not for
  vendor bridges. A probe found that the working directory of the one built bridge does not confine what its program reads, so
  captured text may be sent through a cloud bridge only with its tool features disabled, through the `--confine` option that is requested below (`pipeline.md`, "Safety of captured content"). Each bridge call also carries a large fixed overhead: a one-word prompt used about 15,800 input tokens, and a call
  that used a tool about 31,000, so many small items are batched into one call.
- The existing bridges offer no plain completion with no file access, and none offers embeddings. A bridge for a local model server and a command for embeddings are requests to the workbench (see "Ways a model is called").
- The registry, the endpoints and the tokens are owner-only config, for the reasons of the workbench decision
  `2026-10-20-fixed-store-location`. They are never in a tracked file and never an argument.
- Reading about 10 billion tokens once would take roughly five to six weeks on one machine with a 12 GB GPU, and a long backlog is
  acceptable (`pipeline.md`). Speed and quality figures are in the evidence notes of `knowledge-base.md`.

## Behavior

### What the owner wants

- **[agreed]** The owner wants a modular system that lists models from several vendors and picks one for the work being done. A
  owner decides which models run which work, local or cloud, in the registry, and not every owner has a local model. The
  owner's own set-up is a small local model for bulk work and cloud models where more quality is needed, as an example and not a
  rule.
- **[agreed]** The owner prefers to stay on subscriptions if possible. A model served locally, for example by Ollama on another
  machine on the owner's network, is an example of a local model, not a requirement.
- **[agreed]** The owner is comfortable with the books of any shelf, shared or private, going to a cloud model. Cloud use is limited
  by quotas and by the owner's configuration, not by privacy.
- **[agreed]** Models may run on the host or on another machine, and the design does not prohibit either (`library.md`). A model on
  the host is called the same way as one elsewhere, so no stage depends on where a model runs.
- **[agreed]** Whether a stage runs on a local model, a cloud model or either is the owner's configuration in the registry. Not
  every owner has a local model, so no stage may require one, and none may require a cloud subscription: the library works with
  whichever models the owner lists. Every stage is able to run on any listed model of the right kind, and the router uses the
  owner's order of preference.

### The registry

- **[proposed]** A registry lists each model. An entry holds: a name, the kind (language model or embedding model), the way it is
  called (a vendor bridge, or an endpoint), the model identifier, a rough strength class, the context size, the largest output, how
  many calls it can take at once, a location class (this machine, the owner's network, vendor cloud), whether it can return
  structured output, whether its endpoint is authenticated, a quota (below), and an enabled flag. For an embedding model it also
  records the dimension.
- **[agreed]** The registry and the endpoints are owner-only, held in the config and never in a tracked file or an argument.
  Addresses stay out of every document.
- **[proposed]** A new machine or model is one more registry entry. The host calls it, and a worker stays simple: a machine runs
  only its model server.
- **[proposed]** The registry shows each entry's recent health, taken from the bridge's diagnostic command: reachable or not, the time of its last success, and its recent
  speed. An entry that is unreachable is treated as off.
- **[proposed]** Editing the registry is a governed owner action at `block`, because it changes where content is sent
  (`library.md`, "Credentials" and "Network access" give the same treatment to addresses and tokens). The registry-edit action
  and the switch actions are listed in the actions table of `library.md`.

### Ways a model is called

- **[agreed]** Every model call goes through a workbench bridge, local or cloud. A bridge is the common method of model access,
  and the library calls no vendor and no model server itself.
- **[agreed]** An Ollama bridge is written for local models. It follows the bridge contract (one prompt in, one JSON reply out),
  makes an HTTP request and reads no files, so for a local model the property of having no tools and no file access holds by
  construction. It uses the server's structured output for the `--schema` option, and the address of the server is in the bridge's
  owner-only config and never an argument.
- **[proposed]** Embeddings need their own command, because they return arrays of vectors and not a reply. It takes a batch of
  texts and returns a batch of vectors, since a server accepts a batch in one request, and it must keep a batch within the
  contract's output limit. Whether this is an extension of the contract or a separate capability is for the workbench to decide.
- **[agreed]** The cloud bridges get a `--confine` option that starts the vendor program with its tool features and its shell tool
  disabled, and its web tool turned off. In the measurement this removed all file and shell access in five probes, but the program still listed other tools (an image viewer, a patch tool, MCP resource readers) and its web tool still worked until the web setting was disabled, so the acceptance test also checks the list of tools and a web probe. The program is also started with strict configuration checking, because a misspelt setting is otherwise only warned about and ignored, which would leave a tool on, while an unknown feature name already stops it with an error. A bridge release is accepted for
  untrusted text only if the canary tests pass for it, because the protection depends on the program's version and feature list.
  Until the option exists, captured text is not sent through a file-capable bridge. A separate low-privilege user stays an optional
  extra layer, and the bridge's `--root` option is not a confinement (`pipeline.md`).
- **[proposed]** Batching is done by the library's engine and not by a bridge feature. It packs many short items into one call
  within the contract's limit of 256 KB, and validates that the reply is an array of the right length. In the measurement a call
  with 400 short items cost about 17,000 input tokens against about 13,000 for one item. A task with long items gains little,
  because a long piece of text already outweighs the fixed overhead.
- **[proposed]** Requests to the workbench, which owns the bridges: an Ollama bridge with structured output and an owner-only
  endpoint setting; an embedding command with batches; the `--confine` option, which also turns off the web tool, with canary tests, a check of the program's tool list and a web probe for each release; usage figures that report cached tokens separately (as part of the input tokens, not in addition); and a read-only diagnostic command on each bridge. The diagnostic command reports whether the vendor or server is reachable, which models are available and their version or digest, and whether an embedding model is installed, so that the doctor and the registry can check health and notice a model that changed without notice. These are the library's requirements, and the workbench decides how to meet them.
- **[proposed]** A server may have no embedding model installed, in which case one has to be pulled before embeddings work. The
  doctor reports it (`library.md`).
- **[proposed]** A local model server may serve plain HTTP with no authentication. The registry records this, and the doctor warns
  that library content is being sent in the clear over a network. The owner decides whether that is acceptable on their own
  network, and the address lists of `library.md` do not protect a server that the library only calls.

### Choosing a model

- **[proposed]** Each job states what it needs: the strength class, the context size, whether it needs structured output, and for an
  embedding job which embedding model. The router picks an enabled model that fits.
- **[proposed]** Among the models that fit, the router prefers the cheapest class that meets the job's need, and among those the
  one that is less busy, so the bulk goes to the cheapest models the owner lists (in the owner's own set-up, the small local ones)
  and the stronger ones are kept for the few jobs that need them.
- **[proposed]** The router respects the quota and the switches below. A job with no model that fits and is enabled waits, and the
  library report says what it is waiting for.
- **[proposed]** The engine in this project owns the choice and the escalation, because a bridge may not retry or fall back.
- **[proposed]** A job's prompt has a version, and the prompt version, the model identifier and the date are recorded with every
  output as its generation record (`book.md`).

### Which tasks go where

- **[idea]** Local model: triage against a shelf's scope, near-duplicate checks, first-pass cards, tags and theme splitting.
  Embeddings come from a separate small embedding model.
- **[idea]** Stronger model: domain-neutral theme descriptions (the weave depends on them), judging same mechanism, fit together
  and incompatible, regenerating the cards of books that earned it, and spot-checking the local model.
- **[proposed]** This split is a hypothesis to be set by evaluation. An early experiment found a modest edge for a stronger model
  at writing domain-neutral descriptions, with fewer leaks of field words, and none clearly within a single field
  (`knowledge-base.md`, Evidence notes). A later comparison on 40 themes found that a stronger model's descriptions improved the rank of the source themes (median 207 to 37) but also that of control themes from the same shelves (534 to 120), so the edge is not shown to be specific to the right themes. It is not worth paying for yet, and a held-out set of queries would settle it.
- **[proposed]** A task is assigned to a strength class by its record in the engine and not by the model's own claim, and the assignment is
  changed by evaluation, not by guesswork.

### Escalation

- **[proposed]** A job starts on the cheapest class that fits. It escalates to a stronger model when the output fails validation
  after a bounded number of attempts, or when a policy says that this kind of job needs a stronger model.
- **[proposed]** Escalation is bounded by the quota. At the cap the job waits or stays local, and it is never silently dropped or
  given a worse result without a record.
- **[proposed]** A sample of the local model's output is re-run on a stronger model from time to time as a spot check. The
  difference is reported, which shows whether the local model's cards and themes are good enough, and feeds the evaluation.

### Quotas and budgets

- **[proposed]** Each model entry has a quota: a cap on calls or tokens per day, and optionally per month. A subscription has a daily
  call cap, and at the cap the work waits or stays local.
- **[proposed]** The shelf rules carry a daily budget for model calls (`shelf.md`). The router spends within both the shelf's budget
  and the model's quota, and the weights between shelves decide who gets the capacity when it is short (`shelf.md`, "Priority
  between shelves").
- **[proposed]** Every call records its model, the job, the shelf, the input and output tokens where reported, and the time it took.
  The library report shows consumption by model and by shelf, so the owner can see where the quota goes.
- **[idea]** API keys with a spending cap are the route if the cloud class must grow beyond subscriptions. The owner prefers
  subscriptions, so this is not planned.

### Switches and draining

- **[agreed]** The owner can turn local processing on and off, to use or update the model machines. More model machines may be
  added later.
- **[proposed]** There is a global switch and one per machine. Off means drain: the host starts no new jobs, lets in-flight ones
  finish up to a timeout, and requeues the rest. An unreachable machine is treated as off. The library report shows queue length,
  which machines are on and recent throughput.
- **[proposed]** Both switches are governed owner actions at the workbench levels, with `block` as the default and the owner free to
  choose another level. A switch is a low-risk, reversible action, so an owner who wants a script to turn a machine off for an
  update may choose `none`.
- **[proposed]** Model passes are queued and resumable, because a machine can reboot or be busy (`pipeline.md`). A result is written
  atomically, keyed by book version, task, prompt version and model, so a job that runs twice changes nothing.

### The embedding model

- **[proposed]** One embedding model is pinned per library, because vectors from different models cannot be compared. Each vector
  records the model that made it, and a machine without that model takes no embedding jobs.
- **[proposed]** Changing the pinned model is a governed owner action that re-embeds every card, theme and description as a
  pipeline run in the background, keeping the old vectors until the new ones are complete. Search uses one model at a time and
  never mixes them.
- **[proposed]** The embedding model should be multilingual (`card.md`). The choice is made by the evaluation, and two models were
  used in the early experiments. Both descriptions of a card and a theme are embedded (`theme.md`).
- **[proposed]** An embedding job needs no stronger class. It is cheap next to a language model pass, so a change of model is
  affordable, and the texts, which are the costly part, are kept.
- **[proposed]** Built in the engine (`kb.models.embed`): an entry of the owner's config with `kind` `embedding` and the
  `dimension` of its vectors, and the kind of work `card-embed` that names it. The engine calls the bridge's `embed` command as a
  separate program, batches the texts within the bridge's limits and the size of a reply it can read, checks every reply (the model
  the bridge reported, the number of vectors, the dimension of the entry, finite numbers, no vector of zeros) and refuses the whole
  call if one is wrong. The pinning of one model per library, the record of the model on each vector and the rebuild on a change
  of model are not built yet (`docs/plans/2026-11-09-search-the-neutral-descriptions-by-meaning.md`, Increment C).

### Privacy of what is sent

- **[agreed]** There is no per-shelf or per-book flag that keeps content off the cloud. The owner has said any shelf's books may go
  to a cloud model, and which models are listed and enabled, globally and per machine, is the owner's control. An owner who wants
  nothing to leave the machine lists no cloud model. Visibility (shared or private, `shelf.md`) is separate from where content is
  sent, and a private shelf may still go to a cloud model.
- **[agreed]** Only the text a job needs is sent: the piece of the book being read or the card being judged, and not the library's
  structure, tokens or other books.
- **[proposed]** Model output is untrusted. The prompt tells the model to describe the content and to ignore any instruction inside
  it, and the output is validated for shape and length (`pipeline.md`, "Safety of captured content"). The model has no tools and
  no network only for a local endpoint. A vendor program behind a bridge may read files itself, so captured text sent through a
  bridge needs the confinement that `pipeline.md` requires.

### Checking quality

- **[proposed]** The evaluation (`testing.md`) compares models and prompts on the same inputs: anchors that hold, themes per 1,000
  tokens, leaks of field vocabulary into neutral descriptions, and the rank of the right book or theme for a set of questions.
- **[proposed]** A change of model or prompt is justified by a measure and is made as a new generation, so the old output can be
  compared and restored.
- **[proposed]** A model that gets worse after an update shows as a change in the spot checks, and the registry can pin a model
  version so that an update by a server is not applied silently.

## Acceptance criteria

All of these are provisional until the spec is approved.

- With only a local model enabled and no cloud bridge installed, every stage runs to completion on a fixture library.
- A job states its needs and the router picks an enabled model that fits, preferring the cheapest class that meets the need and the
  less busy machine.
- A model that is switched off, unreachable or over its quota is skipped, and the job waits or moves to another model, and the
  library report says why.
- Draining a machine lets in-flight jobs finish up to the timeout and requeues the rest, and a result that arrives twice changes
  nothing.
- A job that fails validation twice escalates to a stronger model within its quota, and at the quota it waits or stays local and
  records that it did.
- Every output records its model, prompt version and date, and the library report shows consumption by model and by shelf.
- Changing the pinned embedding model re-embeds in the background, never mixes vectors from two models in one search, and keeps the
  old vectors until the new ones are complete.
- A registry edit and a switch change are governed actions, and an endpoint address appears in no tracked file.
- A spot check re-runs a sample on a stronger model and reports the difference.

## Open questions

- How the host, a resident service, calls a bridge through the workbench launcher, which was designed for agents and the harness,
  and whether a process per call is fast enough for many embedding batches.
- Which tasks genuinely need a stronger model, which waits for the cross-field experiment and later for real shelves.
- The quota defaults, and how a subscription's real limits are read, given that a vendor program may hide them.
- The default strength classes, the escalation limits and the sample rate of spot checks.
- Whether an endpoint without authentication is acceptable, or an authenticated proxy should be recommended.
- The embedding model, which the evaluation decides.
- Whether a middle class on a machine with a large unified memory is needed, which depends on further experiments.
- How the router learns each machine's speed, and how it handles a model that loads slowly the first time.

## Governing decisions and references

- Decisions: none recorded in this repository yet. The rules come from the workbench decisions and specs named in
  `knowledge-base.md` (`model-bridge`, `2026-10-22-model-calls-go-through-vendor-bridges`, `2026-10-20-fixed-store-location`), which
  this project adopts and will restate when the owner accepts them.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `book.md`, `shelf.md`, `card.md`, `theme.md`,
  `library.md`, `pipeline.md`, `reading.md`, `weave.md` and `testing.md`.
- The speed and quality figures rest on the evidence notes in `knowledge-base.md` and `theme.md`.
