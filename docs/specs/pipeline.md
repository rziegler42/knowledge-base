# Pipeline

Status: Draft

This specifies the pipeline, the chain of stages that takes a candidate source from "found" to "searchable", and the safety rules for
the captured content that moves through it. It belongs to the design in `knowledge-base.md` and builds on the book (`book.md`), the
shelf (`shelf.md`), the card (`card.md`) and the theme (`theme.md`). **Nothing here is final.** The spec stays `Draft` until the
owner approves it, and any statement can be reopened. Each statement carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

Much of this spec was split out of `knowledge-base.md`, and those statements keep their marks. The rest was added in the
conversation that followed.

## Scope

The pipeline moves each book through its stages, schedules the work across shelves and machines, survives restarts and failures,
tells a searcher how complete its source was, and treats everything it captures as untrusted. This spec covers the stages, the
streaming and the queues, scheduling and priority, resumability, failure handling, the interaction with pauses and switches,
findability and completeness, observability, reprocessing, and the safety of captured content. It does not cover what a stage
produces (the specs of the book, card and theme), the rules of a shelf, which models are used and how they are picked (the models
spec), or how an agent reads the result (the reading spec).

## Non-goals

- **[agreed]** A quarantine. The old one was annoying and hard to maintain.
- **[proposed]** A daemon for the crawler. The owner schedules crawler runs with cron or launchd, and the crawler works in small
  bounded batches (`shelf.md`). The host itself is a resident service that runs the pipeline and answers the reading interface.
- **[proposed]** Exactly-once delivery. Stages are idempotent, so a job that runs twice changes nothing, and that is the guarantee.
- **[agreed]** Real-time latency. A new source may take hours or days to reach every stage, and the backlog is allowed to be long.

## Assumptions and constraints

- Everything captured is untrusted data. The crawler is a fixed fetcher with rules, not an agent (`shelf.md`).
- Every stage runs on whatever models the owner lists, local or cloud (`knowledge-base.md`, Models), within quotas.
- The payload of a book is immutable once filed and is written through an incoming area (`book.md`), and the pipeline state of
  each version is recorded in the book's manifest, which is mutable metadata.
- The host schedules and the workers stay simple: a machine runs only its model server and the host calls it. Where a stage runs
  is not part of its contract (`library.md`).
- Expected scale is hundreds of thousands of books grown over years. Reading 200,000 books of about 50,000 tokens each is
  roughly 10 billion tokens, so the first pass alone may take weeks to months of local compute.

## Behavior

### The stages

- **[agreed]** The stages are find, fetch, convert, card, index, and later themes. Each book moves through them as soon as it is
  ready for the next one.
- **[proposed]** Scan is a stage of its own, before convert: the objective checks (embedded scripts, encryption, hidden text) run on
  the captured file, and their findings become caveats (see "Safety of captured content"). The stages are therefore, in order:
  *found* (a candidate and its identity), *fetched* (the original in the incoming area), *scanned* (the objective checks),
  *converted* (text, structure and caveats), *carded* (the first model stage), *indexed*, *themed* (extraction and neutral
  descriptions, then their indexes) and, if the weave is built, *threaded*. Keyword indexing happens right after converted, so the
  book is searchable by keyword; vector indexing happens after carded, so it is searchable by meaning.
- **[proposed]** A stage of a version is pending, done, failed or skipped, the words of `book.md`. A stage that has failed after
  its bounded retries and is set aside with its reason is parked, and the word means only that.
- **[proposed]** Each stage has a named input, a named output and a version of its own code and prompt. A change to a stage's
  version marks earlier output as out of date and never rewrites it (generations, `book.md`).
- **[proposed]** The model stages are card, themes and, later, threads. Fetch, convert and index need no model beyond an embedding
  model for the vectors.
- **[proposed]** A stage reads from the book folder or the incoming area and writes through the incoming area, so a stage that
  stops half way leaves no half-written output (`book.md`, "Safe writing").

### Streaming and queues

- **[agreed]** The pipeline is streaming. Each book moves through the stages as soon as it is ready, and a stage never waits for a
  whole batch of earlier work to finish. Fetching hundreds of sources does not hold up the processing of the first ones.
- **[proposed]** Small bounded queues join the stages, so a fast stage cannot flood a slow one. When a queue is full the stage
  before it stops taking new work, and the pressure travels back to find and fetch.
- **[proposed]** Each book's manifest records the stages it has finished (`book.md`), so a restart resumes where it stopped.
- **[proposed]** The stages can run on different machines at once: fetching and conversion on the host, model work on the model
  machines. Writes to the catalog are serialised, and how is left to the builder.
- **[proposed]** A worker claims a job with a short lease and renews it while working. A job whose lease runs out, because the
  worker died or the machine is off, returns to the queue, and its half-finished output is discarded.

### Scheduling and priority

- **[proposed]** Work is taken from the queue in priority order. Within a shelf the order is newest and most relevant first
  (`shelf.md`, "Priority between shelves"). Across shelves, the shelf weights divide the capacity in proportion, with a guaranteed minimum share and
  aging so that no shelf is starved (`shelf.md`, "Priority between shelves").
- **[proposed]** The shares apply to the scarce resources: the daily fetch budget and the crawler's visits, and the order in
  which model work from different shelves is taken. They do not apply to a stage that has spare capacity, so an idle machine
  takes work whatever the shares say.
- **[proposed]** Finishing is preferred to starting. When capacity is short, work that moves an already fetched book toward
  searchable (card, then index) goes before fetching a new one, so books become findable early and the backlog of half-processed
  books does not grow without limit.
- **[proposed]** Reprocessing (a new prompt or model over books already done) runs at the lowest priority, so it never delays new
  books, and a better generation replaces an older one only when it is complete for that book.
- **[proposed]** Backlog is acceptable. Capture and processing are separate dials. Processing is not a gate: every captured book
  is processed eventually on the local model, in priority order, and the queue length is visible to the owner. Quality, not cost,
  is the limit, because a small local model may write descriptions that are too literal.

### Resumability and idempotence

- **[proposed]** A stage's result is written atomically and keyed by book version, task, prompt version and model, so a job that runs twice
  changes nothing. This makes a restart, a duplicate claim and a late result safe (`library.md`, "Backup").
- **[proposed]** A stage that finds a valid result for its key skips the work. A result that fails validation is treated as no
  result and is redone.
- **[proposed]** Model output is validated for shape and length before it is stored, and a malformed or oversize output counts as
  a failure of that attempt.

### Failure handling

- **[proposed]** A failed job is retried a bounded number of times, with growing delays. Its stage is then failed and parked: the
  stage stays failed, is set aside with its reason, and records the stage, the error and the attempts, and it does not block the
  others. The stage states are those of `book.md`: pending, done, failed and skipped.
- **[proposed]** Failures are classified so they are not all treated alike. A transient failure (a busy or unreachable machine, a
  timeout) is retried. A permanent failure (a corrupt file, an encrypted file, an unsupported format) is failed and parked with a
  clear reason at once, and the book is kept with what it has, for example a card built from metadata and marked partial
  (`card.md`). A stage that does not apply to a book, such as themes for a flat pointer, is skipped.
- **[proposed]** The circuit breaker of a shelf (`shelf.md`, "Safeguards") counts failures, scan findings, low relevance and stages
  that hit their runaway bound, and pauses the shelf when too many occur. The pipeline reports to it and does not decide on its
  own to stop a shelf.
- **[proposed]** A theme stage that reaches the runaway bound is marked failed with the reason "runaway", its output is kept
  aside, and repeated hits pause the shelf (`theme.md`).
- **[proposed]** A model that is switched off, unreachable or over its quota is not a failure of the job. The job waits or goes to
  another enabled model that fits, and the library report shows what is waiting and why.

### Pauses, switches and draining

- **[agreed]** The owner can turn local processing on and off, to use or update the model machines, globally and per machine
  (`knowledge-base.md`, Models). Off means drain: the host starts no new jobs, lets in-flight ones finish up to a timeout, and
  requeues the rest.
- **[proposed]** A library pause for a backup (`library.md`, "Backup") stops new work, lets work in flight finish for a short
  time, drops what has not finished, and leaves the queue intact. On resume the stages carry on from the queue. A late model
  result during the pause is dropped and redone.
- **[proposed]** A paused shelf stops its own find and fetch work and keeps what it already holds searchable. Work already past
  fetch for that shelf continues unless the owner pauses all processing.
- **[proposed]** The pipeline checks the state of the library, the shelf and the machine before it starts a job and again before it
  writes, so a pause that arrives mid-job is honoured at the write.

### Findability and completeness

- **[agreed]** A shelf is searchable as soon as it has anything in it, including while it is still being seeded.
- **[proposed]** A book becomes findable stage by stage: by keyword once converted, by meaning once its card is indexed, and by
  theme later. A search result says how complete its source was, for example "this shelf is being seeded: 120 of about 250
  filed, 80 with cards", so that a missing result is not mistaken for missing knowledge.
- **[proposed]** Each result carries the date its book was added, and a search can take a date to show only newer books or the
  library as it was then. Books are only added and never changed in place, so a date is enough and no revision id is needed.
  Regenerated cards and weeding make an old search only approximately reproducible.

### Observability

- **[proposed]** The pipeline keeps counters for every stage: queue length, jobs in flight, completed, retried and parked, the age
  of the oldest waiting job, and throughput over recent hours. It records which machine ran a job and which model.
- **[proposed]** These feed the library report (`library.md`) and the doctor: which stage is behind, which shelf is not receiving
  its share, and which jobs are parked and why. A parked job is visible and not silent.
- **[proposed]** Logs are structured and bounded in size, and carry no captured content beyond what is needed to identify the
  book.

### Reprocessing

- **[proposed]** A new prompt version or model adds a generation and does not overwrite the old one. The index keeps using the
  active generation until the owner switches (`card.md`, `theme.md`).
- **[proposed]** A reprocessing run shows, before it starts, how many books and tokens it would cover and on which models, so the
  owner can see the cost. It can be limited to a shelf, and it runs in the background at the lowest priority.
- **[proposed]** The index can be rebuilt from the book folders, and a rebuild is a pipeline run like any other.

### Safety of captured content

- **[agreed]** The old quarantine was annoying and hard to maintain.
- **[proposed]** No quarantine, release step or blocking. All captured content is untrusted. Conversion runs with a time limit, a
  size limit and no network. Converted text carries an untrusted banner, and everything returned to an agent is marked as data.
  Objective scan findings (embedded scripts, encryption, hidden text) become caveats on the book and its card and never stop
  filing. There is no phrase list. A hostile file can still be filed, inert; the residual risk is text steering an agent or the
  card-writing model.
- **[proposed]** Model stages read untrusted text. Their prompts tell the model to describe the content and ignore any
  instruction inside it. Its output is validated for shape and length, and it is stored and returned as untrusted data. For a
  local model endpoint the model has no tools and no network. For a vendor bridge that does not hold, because the vendor program
  may read files itself (`models.md`).
- **[proposed]** Captured text is not sent through a vendor bridge whose program can read files, unless the bridge runs it with its tool features disabled (the `--confine` option requested from the workbench in `models.md`) and the canary test passes for that release. A separate low-privilege user is an optional extra layer. A bridge with no file access is used for untrusted text when one exists. A bridge's
  `--root` option is not a confinement. A probe on 2026-11-01 found that the one built bridge read a file one directory above its
  working directory, read a file outside the project by absolute path, listed the parent directory and ran a shell command, while
  its file writes were refused and a network request failed to resolve a host (see the evidence notes in `knowledge-base.md`).
- **[proposed]** Nothing the pipeline captures is executed, built or run, and a converter runs only if the owner has approved
  that exact tool and version (`book.md`).
- **[proposed]** Parsing documents, running a converter subprocess, fetching from the network and calling a model each touch the
  security policy, so the owner is asked about a security review when the plan for the pipeline is drafted.

## Acceptance criteria

All of these are provisional until the spec is approved.

- A book fetched while others are still being fetched moves on to conversion and its card without waiting for the batch, and is
  searchable by keyword once converted and by meaning once its card is indexed.
- Killing the host in the middle of each stage leaves no half-written output, and a restart resumes every book from its recorded
  stage with no duplicate work.
- A job run twice for the same book version, task, prompt version and model changes nothing.
- A full queue makes the stage before it stop taking work, and the pressure reaches fetch.
- With one shelf at a high weight and another at the lowest, the high one receives the larger share of scarce capacity, the low one
  still advances at no less than its minimum share, and an idle machine takes any work regardless of shares.
- When capacity is short, a fetched book's card is made before a new book is fetched.
- A transient failure is retried and a permanent one is parked with its reason and the book is kept, marked partial.
- A model switched off or over quota makes jobs wait or move to another model, and the library report says why.
- Draining a machine lets in-flight jobs finish up to the timeout and requeues the rest, and a library pause drops late results
  and resumes from the queue.
- A search during seeding says how many books are filed and carded, and a search with a date returns only books added after it.
- The library report shows the oldest waiting job per stage and the parked jobs with reasons.
- A hostile fixture is filed inert with a caveat, conversion respects its limits, and an instruction inside content does not change
  what a model stage does.
- The stage list of a version is found, fetched, scanned, converted, carded, indexed, themed and threaded, each pending, done,
  failed or skipped, and a stage failed after its retries is shown as parked with its reason.
- Captured text goes through a file-capable vendor bridge only when the bridge runs it with `--confine`, and a test with a canary file in the library, the config and the project shows that the confined program cannot read any of them.

## Open questions

- The queue lives in the index root (`library.md`). Only the mechanism (a database or files) and how workers claim jobs are left to
  the builder.
- The default retry counts and delays, the lease length, and the queue sizes.
- The fair-share algorithm, which only a run with real shelves can tune.
- How a very large book is split across jobs, and whether it is processed as pieces that can run on different machines.
- Which scan tools are used and which findings count as caveats.
- Whether the card and the first indexing happen on the host so a book is findable quickly, or wait for a model machine.
- The batch size and frequency of scheduled crawler runs.
- The stage versioning scheme, and how out-of-date output is shown.

## Governing decisions and references

- Decisions: none recorded in this repository yet.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `book.md`, `shelf.md`, `card.md`, `theme.md`,
  `library.md` and `testing.md`. The models are in `models.md`, the reading module in `reading.md` and the weave in `weave.md`.
- The evidence notes in `knowledge-base.md` and `theme.md` record the speed and extraction experiments that the scale and cost
  figures rest on.
