# Knowledge base

Status: Draft

This is the design of the knowledge base as it stands in a continuing conversation with the owner. **Nothing in it is final.** The
spec stays `Draft` until the owner approves it, and any statement can be reopened as the brainstorming goes on. Each statement
carries one of three marks so that the owner can see how firm it is:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

Ideas that are not yet settled enough to belong here are kept in working notes outside this spec.

This spec is the overview. The detail lives in topic specs, each with its own marks and acceptance criteria:

- `book.md`: the book, its versions, items, conversion, metadata, model output and lifecycle.
- `theme.md`: the theme, the unit of meaning that the weave connects.
- `shelf.md`: shelves, their rules, permission levels, relevance, priority, the crawler and who may see what.
- `card.md`: the card and the catalog an agent searches.
- `library.md`: the host, credentials, network access, backup, integrity, the library report and the doctor.
- `pipeline.md`: the stages, streaming, scheduling, failure handling, completeness and the safety of captured content.
- `models.md`: the model registry, the router, escalation, quotas, the switches and the embedding model.
- `reading.md`: the reading module, its interface, the search and the brainstorm report, the budget and the MCP door.
- `weave.md`: the exploratory layer of threads between themes, revised after the first cross-field experiment.
- `testing.md`: fixtures, the two test layers and the evaluation.


## Scope

**Intent [agreed].** A personal library of outside information on topics the owner cares about. A project that installs this
module gives its agent access to the library during brainstorming, specs, decisions, roadmaps and plans, so the agent can bring in
ideas, patterns and facts that are not obvious, even from a web search, and follow them into new concepts.

**Purpose [agreed].** The library supports research across many, possibly unrelated, fields, to find novel concepts that are not
obvious. It is more than a search engine. Its reader is mostly a research agent working for the owner, and sometimes the owner. The
agent, not the library, decides whether a concept it finds is worth pursuing; the library does not judge novelty. An agent's own
knowledge is common and a deep dive only interpolates between known solutions, so the library aims to help it extrapolate: to see how
ideas from separate fields fit together and to reach a field outside its search parameters that can shape a solution in a new way.
One theme is the unit it offers. It offers distant material the agent did not ask for as well as answering what it asks, most of that
material will be noise, and that is accepted if each item is cheap to skim. The agent sets two things on a call: a weighting from
narrow to wide, as a short named scale (narrow behaves like an ordinary search engine, wide casts a net over many non-obvious topics,
and the default leans wide), and a distance, the number of steps along threads to travel within the bounds the weighting sets. The
decision is `2026-11-11-the-library-equips-a-research-agent-to-extrapolate`, which also lists what is left open.

**Success test [agreed].** A brainstorm is better because the library was consulted. If the agent does not return information that
helps the brainstorm, the owner stops using it. The previous standalone generator failed this test: it produced few novel
findings.

**Guiding principle [agreed].** Where a choice trades cost or simplicity against the chance of finding novel concepts, the design
errs toward finding novel concepts.

**Expected scale [agreed].** Tens to hundreds of shelves and hundreds of thousands of books, grown over years, partly by a slow
crawler.

**Parts and order [agreed].**

1. **Library model.** The shelf, book, version, manifest and catalog-card formats, with identity and duplicate rules
   (`book.md`, `shelf.md`, `card.md`, `theme.md`, `library.md`).
2. **Reading module.** The workbench module declaration, a read-only reading interface, and the skills and policy that make an agent
   search at the planning steps and report back.
3. **Curation tooling.** Commands, each governed by a workbench permission level the owner sets, to set up the library, create
   shelves, find and file books, add versions, reshelve and rebuild the catalog, and later a slow crawler.

They are built in the order 1, 2, 3. Two further pieces are ideas, not parts yet: the weave (themes joined by threads, below) and
an MCP door onto the reading interface.

## Non-goals

- **[agreed]** Storing decisions or conversation. Those belong in `docs/decisions/` and in the owner's memory module.
- **[agreed]** Judging licenses or the law, or restricting content on license grounds. Permission is assumed unless a source
  specifically says otherwise. Terms a source states are recorded, and what to do about them is the owner's to decide.
- **[agreed]** Executing anything the library holds. A repository, script or document in the library is data and is never built or
  run.
- **[agreed]** Per-claim verification tags. A card is a lead to follow, not a claim to rely on.
- **[agreed]** Tracking the library in git. Backup and history are the owner's to arrange.
- **[agreed]** A notes feature. A book may later hold other kinds of item, but none is designed here.
- **[proposed]** Mapping what depends on what in a project's own files. That is the workbench's `graphify` module.

## Assumptions and constraints

- The workbench's `knowledge-tools` spec reserves this module, proposes the capability name `knowledge-base`, and fixes its
  boundaries: library content is reference data and untrusted as instruction, a tracked document cites it by source URL, retrieval
  date and content hash and never by path, and an agent may run only reads that change nothing and send nothing out. **Two
  exceptions, allowed by the owner** (the first on 2026-11-10, plan `2026-11-10-pose-a-problem-to-the-search-by-meaning`, which cites this line; the second on 2026-11-14,
  plan `2026-11-13-let-an-agent-walk-from-themes-along-the-links`, Increment E-A, where the owner answered "Yes, allow it" to the question whether `theme-walk` may send an
  agent's questions out through the helper): the helper arguments `problem-search` and `theme-walk` send the sub-problems or questions an agent wrote to the embedding
  model that the owner's config names for the `card-embed` task, on the owner's server (on the owner's network, over plain HTTP: in the clear), and to nothing else; the
  destination is not chosen by the caller, and `search` and `read` still send nothing out. The workbench's own `knowledge-tools` spec is outside this project and is not changed here: it is the
  owner's to reconcile with this exception.
- The workbench decision `2026-10-20-fixed-store-location` explains why a store's location must not be changeable by an option, an
  environment variable or a committed file. The same reasoning is applied below to addresses, tokens and the model registry.
- Model calls go through the workbench's vendor bridges (decision `2026-10-22-model-calls-go-through-vendor-bridges`; spec
  `model-bridge`). A bridge is one thin module per vendor, takes one prompt and returns one JSON reply of up to 256 KB, and does not
  choose the model, retry or fall back. Installing a bridge is the owner's consent to send content to that vendor. Only
  `ask-codex` is built, and the vendor programs it wraps can read files themselves.
- The workbench has no MCP layer; one was deferred (decision `2026-10-21-module-code-lives-in-modules`). A module's interface is a
  pinned helper command, and permission rules match commands.
- Parsing converted documents, running a subprocess, fetching from the network and calling a model over a network each touch this
  project's security policy. The owner is asked about a security review when the curation plan is drafted.
- Adding a dependency, such as a vector index or a local model runtime, needs the owner's explicit approval.
- The module declares itself to the workbench in the form its module contract requires. That is designed in the reading module's
  plan, not here.

## Behavior

### Vocabulary

- **[agreed]** The **library** is the whole collection. A **shelf** is one domain. A **book** is a container for one work. A
  **theme** is a derived chunk of meaning inside a book, pointing back to an excerpt for citing. The **catalog** is the searchable
  set of **cards**, each describing one book. The **weave** is the exploratory layer connecting themes across shelves, and a
  **thread** is one connection between two themes.
- **[agreed]** One unit, one name. The unit that the library offers an agent and that a thread joins is the **theme**, as `theme.md`
  defines it (idea-level, with an anchor to an excerpt and a neutral description of its own). The owner may say *idea* or *key idea*
  and means the same unit. The key ideas that a card holds today are the early, coarse form of themes: plain text of at most 300
  characters with a quote and a mark, and no neutral description or anchor of their own. The decision
  `2026-11-11-the-library-equips-a-research-agent-to-extrapolate` says *idea* where this spec says *theme*.
- **[proposed]** A **hop** is one step of the agent's walk. Before threads exist a step goes from a card to its book to adjacent cards
  and needs no weave; once threads exist a step follows a thread. **[agreed]** The agent's distance setting counts steps along
  threads.
- **[proposed]** The **library report** is the state-of-the-library output, and the **integrity check** is the check that the
  library's files match what it records. Both are specified in `library.md`.
- **[agreed]** The project, the capability, the module and its command are all named `knowledge-base`, so an agent runs
  `wb run knowledge-base ...`. "Library" is the word for the collection, in the documents and in conversation. The assistant first
  suggested `library` for the module and command and withdrew it: in a software project "search the library" can be read as code
  libraries, and the workbench's routing text for this module says "knowledge base".
- **[proposed]** Words avoided, because they are overloaded here or in the workbench: for a theme, *unit*, *passage*, *idea* and
  *concept* (*idea* also collides with the mark `[idea]`; the owner's *idea* means a theme, above); and generally *module*, *reference*, *topic*, *entry*, *note* and *chunk*.
- **[proposed]** An item in a book is **captured** (a copy of content lives in the book) or a **pointer** (an address plus the exact
  version meant). "Reference" is avoided because the workbench uses it for `docs/references/`.

### Where things live

The library is specified in `library.md`: where its data lives, the host and its clients, credentials and their rotation, setup,
moving the library, the unmounted-drive guard, backup, format versions and integrity, and the library report. This section keeps
only the summary.

- **[agreed]** The library is untracked, local data, outside the clone of this project and outside every project that reads it.
  Only the engine (code, specs and documents) is ever committed, and data never is. Test libraries are generated by the tooling or
  built from small synthetic fixtures.
- **[agreed]** Config lives at `~/.config/knowledge-base/`. The library has two roots, chosen by the owner once at setup: a bulk
  root for books and an index root for databases and other small, fast data. Their defaults are under
  `~/.local/share/knowledge-base/`. The owner's own choice of location is personal and is never a default of the project.
- **[agreed]** One library host serves all the owner's machines on the local network, as part of the workbench. Models may run on
  the host or elsewhere. More than one library on a machine is deferred.
- **[agreed]** An owner who moves things can point the project at the new root locations.
- **[proposed]** Nothing stored inside the library holds an absolute path to a root.
- **[agreed]** Backup is the owner's to arrange, and the library offers a way to pause writes during a backup and to resume after
  it, with no storage type assumed.
- **[agreed]** Each user of the library has a current and a next token so that tokens rotate with no downtime, and rotation on the
  client is automatic. A machine is enrolled once and each project on it gets its own tokens.

### Shelves

The shelf is specified in `shelf.md`: creation and rules, permission levels, relevance, placement, scope changes, renaming,
emptying and removing, classifications, licenses, candidates and filing, states and seeding, the crawler, reshelving, safeguards,
and shared and private. This section keeps only the summary.

- **[agreed]** A shelf is an owner-defined area of interest with a scope statement and rules. The owner, with the help of an AI,
  defines it and approves its rules, after which filing is automatic. The owner can do this remotely, without a terminal, through the
  workbench's permission levels.
- **[agreed]** A shelf is shared by default and can be made private. A guest sees nothing of a private shelf.
- **[agreed]** There is no limit on the size of a shelf, its number of books, or the number of shelves, unless the owner sets one.
- **[agreed]** Licenses never restrict by default; permission is assumed unless a source specifically says otherwise.
- **[agreed]** The owner can give priority to some shelves, and no shelf is starved by it. The library may suggest splitting or
  combining shelves, and emptying a shelf moves its books to other shelves and deletes nothing.

### Books

The book is specified in `book.md`: identity, layout, versions, items, conversion, metadata, model output, pipeline state,
lifecycle and safe writing. This section keeps only what ties books to shelves and to the curation pipeline.

- **[agreed]** A book sits on one home shelf and is found from any shelf through the catalog. The catalog's topics and the weave
  do the cross-linking, so a book never needs a second shelf. A book that straddles two fields goes on its best-fitting shelf.
- **[proposed]** A new version is added under the shelf's approved rules. Removal is a governed owner action and lists what it will delete.
  Nothing is pruned automatically. Steady-mode crawling checks for new
  upstream versions, and the owner can also ask for a check.
- **[proposed]** A size cap per item, set generously by the owner, guards against runaway downloads and is not a storage limit.
- **[proposed]** Capture and processing are separate dials, and processing is not a gate. A backlog is acceptable
  (`pipeline.md`).
- **[proposed]** A "seen" list records candidates the crawler considered and rejected (identity, decision, reason), so they are not
  fetched again. It is not a book. Weeding removes the original of a low-value book to reclaim space and keeps its card, pointer
  and recorded hash.

### Safety of captured content

The safety rules for captured content are in `pipeline.md`. This section keeps only the summary.

- **[agreed]** The old quarantine was annoying and hard to maintain, so there is none. All captured content is untrusted: it is
  converted with limits and no network, carries an untrusted banner, and is returned to an agent marked as data. Objective scan
  findings become caveats and never stop filing.

### The catalog and cards

The card and the catalog are specified in `card.md`. This section keeps only the summary.

- **[agreed]** A card belongs to the catalog, the collection an agent searches, and points to its book by id. Its canonical text is
  kept in the book's own folder. A model generates it when a book is filed and it can be regenerated. It is a lead to follow.
- **[agreed]** The card keeps a domain-neutral description alongside its summary, and is written in English whatever the source's
  language.
- **[proposed]** Model output is kept in generations and never overwritten, with the model, prompt version and date recorded
  (`book.md`). The index root holds a fast local working copy (vectors and keyword indexes) so searching and following hops never
  touch the bulk drive. **[agreed]** The catalog, vectors and keyword indexes can always be rebuilt from the book folders. The seen
  list, the work queue, the logs and, if built, the threads and ledger exist only in the index root and cannot be rebuilt from the
  books, so the index root is backed up like the books (`library.md`).

### Reading side

The reading module is specified in `reading.md`: when the agent searches, how it forms queries, the interface, what a result holds,
the three-tier brainstorm report, the budget, the project setting, feedback, failure and safety, and the MCP door. This section keeps only the
summary.

- **[agreed]** In a project with the module installed, the agent searches the library on its own when it brainstorms or drafts a
  spec, decision, roadmap or plan, across the whole library unless the project's setting or its token narrows it. It follows hops
  from a card to its book to adjacent cards within a fixed budget, then reports what it found and recommends when and where to
  continue. It does not go past the budget unasked.
- **[agreed]** The brainstorm report is sorted into three tiers: **on topic**, **adjacent** and **improves on the idea**. Where
  nothing useful was found it says so.
- **[agreed]** The workbench agent is the first and most frequent user, through a governed workbench command. An MCP server is a
  later door onto the same interface, for tools outside the workbench.

### Curation side

- **[agreed]** Curation tooling creates shelves and finds and loads sources. The owner can say "find information on game theory",
  and an agent searches the web for matching sources.
- **[proposed]** Every curation action that fetches from the network, writes the library or sends content to a model is governed by
  a workbench permission level that the owner sets (`shelf.md`, "Permission levels"). The network interface offers reads and
  proposals, and a proposal has no effect until the governed approval is given.
- **[agreed]** Candidates, filing, seeding, the crawler, reshelving and the safeguards are specified in `shelf.md`.
- **[agreed]** The pipeline is streaming, each book moving through the stages as soon as it is ready, and a shelf is searchable
  as soon as it has anything in it. The stages, queues, scheduling, resumability, failure handling and completeness statements
  are specified in `pipeline.md`.

### Models

The models are specified in `models.md`: the registry, the ways a model is called, the router, escalation, quotas, the switches
and draining, the embedding model, privacy of what is sent, and quality checks. This section keeps only the summary.

- **[agreed]** The owner wants a modular system that lists models from several vendors and picks one for the work being done. A
  owner decides which models run which work, local or cloud, in the registry, and not every owner has a local model. The
  owner's own set-up is a small local model for bulk work and cloud models where more quality is needed, as an example and not a
  rule. The owner prefers to stay on subscriptions, and is comfortable with any shelf's books going to a cloud model.
- **[agreed]** Models may run on the host or on another machine. The owner can turn local processing on and off, globally and per
  machine, and more model machines may be added later.
- **[agreed]** Every model call goes through a workbench bridge, local or cloud, and an Ollama bridge is written for local models.
- **[agreed]** Local or cloud use is the owner's configuration, because not every owner has a local model. No stage requires a
  local model or a cloud subscription. **[agreed]** The registry and the endpoints are owner-only config.

### The weave

The weave is specified in `weave.md`, and all of it is exploratory. This section keeps only the summary.

- **[idea]** The problem: three unrelated shelves A, B and C, and a problem D with little relation to any of them, where a part
  from each, combined, gives a novel solution that would be very hard to find otherwise. The weave is meant to find that.
- **[agreed]** A thread connects two themes, possibly across shelves, and the weave is meant to carry the agent from a theme it found
  to distant themes it did not ask for. Links must not be limited to strongly paired themes, or the library becomes a search engine again.
- **[idea]** The weave is built in stages, only as far as the evidence says is needed. A first cross-field experiment (evidence note
  10) showed that search over neutral descriptions finds the source field for some transfers without any weave, and that the home
  field's own version of an idea often hides it. That experiment, and the trial that followed it, measured the retrieval of known
  transfers, not whether an agent can extrapolate, so they do not settle which stage is needed (`weave.md`).

### Beyond one library

The ideas about other people using the library, loans between libraries and hybrid weaves are kept in `library.md`, under "More than
one library". They are ideas, not parts.

## Acceptance criteria

All of these are provisional until the spec is approved. The topic specs hold the detailed criteria for their parts.

- **The model.** A hand-made library written to the formats above passes a check, a reshelve leaves every book's id and manifest
  intact, and a version added to a book leaves earlier versions byte-for-byte unchanged. Deleting the catalog and rebuilding it
  gives the same mechanical fields.
- **The reading module.** In a project with the module installed, a brainstorm request runs a bounded search through the host,
  returns a three-tier brainstorm report with cite-ready provenance, marks it as data, and stays within its budget. A project without the
  module is unaffected, and an unreachable host does not stop the brainstorm.
- **The measure that matters.** On a small hand-made game-AI library, the prompt "brainstorm fitness functions for an Othello AI's
  board-strength evaluation" returns on-topic books on evaluation functions, adjacent books on other approaches to Othello, and
  books on improving on hand-built evaluation, including ones that use "evaluation function" and not "fitness function". The owner
  judges the result useful. It is run before the curation tooling is built, and again with two or three prompts from other
  domains. **[proposed]** A set of real questions from the owner's own projects, kept outside the repository
  (`testing.md`), is the first test set. It includes two generic known misses of card-level search, finding the paper with an
  opening-book framework and finding the sequential-test papers for stopping a matchup early, which theme-level search is to find
  or the spec records why not.
- **The curation tooling.** A topic request produces proposals and files nothing until approved. A candidate already in the library
  is not downloaded again. A candidate that fits a different shelf is proposed for that shelf. A changed upstream source is offered
  as a new version.
- **The weave, if built.** On a hand-made library with shelves A, B and C and a problem D whose combined solution is known, the
  search surfaces the part from each shelf, with the passages cited.
- **Failure the design guards against.** A library crowded with unwanted or duplicate books, cards that are stale or wrong with
  nothing to show it, an agent that fills its context with unhelpful cards, search that returns only the obvious, and setup effort
  high enough that the library is never fed.

## Open questions

- Whether cards and themes alone are enough or book text must be searched too, and the matching mechanism and budget defaults.
  An early experiment found papers in the text that card search missed.
- What a thread is in the weave, and whether weights or several weaves are needed.
- The names and behaviour of the levels of the narrow-to-wide scale, how a level bounds the distance, which level is the default, and
  what a step is counted in (the decision lists these as left open). How to tell whether the library helps an agent extrapolate.
- How the workbench would treat a local model, a plain-completion bridge and an MCP layer, which are workbench questions.
## Governing decisions and references

- Decisions: `2026-11-04-knowledge-base-is-a-standalone-package` and
  `2026-11-11-the-library-equips-a-research-agent-to-extrapolate`. The rules above come from the workbench decisions and specs named in
  "Assumptions and constraints" (`knowledge-tools`, `model-bridge`, `2026-10-20-fixed-store-location`,
  `2026-10-22-model-calls-go-through-vendor-bridges`, `2026-10-21-module-code-lives-in-modules`), which this project adopts and
  will restate in a decision of its own when the owner accepts them.
- References: none.

### Evidence notes

These summarise throwaway experiments run on 2026-10-31 (the theme extraction experiment is summarised in `theme.md`) against a local model server with a 12 GB GPU (server version not
recorded; the repository had no commits). The scripts were not kept. Each result is from one run and is a rough guide only.

1. **Speed.** A prompt of about 4,800 tokens was read at about 2,980 tokens a second by `gemma4:12b` (8.4 GB) and about 3,410 by
   `gpt-oss:20b` (14.1 GB, partly in system memory). Generation was about 68 and 74 tokens a second, and loading took 22 to 33
   seconds. Reading about 10 billion tokens once would therefore take roughly five to six weeks on one such machine. Quality was
   not measured.
2. **Embeddings.** `nomic-embed-text` (768 dimensions) and `bge-m3` (1,024) were both used. In a four-sentence test, "evaluation
   function for Othello" was closer to a generic position heuristic than to a genetic-algorithm fitness function, and both were
   well above an unrelated sentence. Scores from different embedding models are not comparable.
3. **One domain, cards and text.** Cards were made for 30 papers from an earlier game-AI collection (14 chosen by their mentions of
   Othello and evaluation functions, 16 at random with a fixed seed), and the cards and 2,373 text chunks were searched with
   three queries for one prompt. The on-topic papers ranked first in every variant. The adjacent and improves-on queries returned
   nearly the same papers as the on-topic one, so tiers need queries without the topic words or the removal of results already
   shown. Searching text chunks found papers the card searches missed. The two card writers gave similar rankings.
4. **Neutral descriptions within one domain.** With four queries containing no game words, the right answers (chosen by the
   assistant, and incomplete) found in the top five were 3 and 4 of 10 for domain-neutral descriptions, 3 and 5 for the original
   cards, and 2 and 2 for raw text, with the two embedding models in that order. The descriptions still used game words, and a
   hub paper surfaced for unrelated queries. No benefit from the rewrite was shown.
5. **Across fields.** Twenty-one open-access arXiv papers (8 on foraging, 8 on optimal stopping and sequential tests, 5 on the
   value of information; each recorded with its source URL, retrieval date and SHA-256) were added to the 30 game-AI papers, making
   51 books. For a time-budget problem searched whole, 5 or 6 of the top 6 were game-AI papers. Abstract sub-questions pulled in
   the other shelves. The two most on-point foraging papers ranked 25th to 34th by card and 1st to 6th by neutral description on
   the whole problem, and unevenly on the sub-questions. Descriptions written by Claude Haiku at low effort leaked fewer field
   words than `gemma4:12b`'s (63 against 110) and gave a lower rank sum for the two papers (65 against 81, lower being better),
   using about 620,000 tokens for 51 descriptions: a modest edge, not a clear win.
6. **Real questions.** Cards for the rest of the earlier collection gave 216 books (195 game-AI and 21 from the other fields), and
   seven real open questions from two of the owner's game-engine projects (a board game and a card game) were searched against
   cards and raw text. Four returned useful leads, and the card-game hits largely repeated sources the projects already used.
   Two were misses, on opening books and on stopping a matchup early, because the question's vocabulary did not match the
   papers'; the papers were in the library. The card-game results show a content gap: the library has no source on the card
   game itself. The owner's judgment is that the library has too little variety to tell how much a weave would help.
7. **What a vendor bridge's program can reach.** On 2026-11-01 the one built bridge (`ask-codex`, version not recorded; the repository
   had no commits) was called seven times from a new empty directory inside the project, each time with a harmless prompt and a
   canary file. The vendor program read a canary in its working directory, read a canary one directory above it, read a canary
   outside the project by absolute path, listed the parent directory, and ran a shell command. Its attempt to create a file was
   refused, and a network request failed to resolve a host. A one-word prompt used about 15,800 input tokens, and calls that used a
   tool about 31,000. Conclusion: the bridge's working directory does not confine what the program reads, reads can reach any file
   the owner's user can read, and the reply is the only route out, so captured text should reach such a bridge only if the program
   runs sandboxed. Each call was one run, so the figures are a rough guide.
8. **Overhead and protection options of the vendor program.** On 2026-11-01, `codex-cli` 0.163.0 was run directly with the same
   safety options as the bridge (read-only sandbox, ephemeral session, no user config or rules, working directory a new empty
   folder), once per variant with harmless prompts. A one-word prompt used 15,836 input tokens, of which 12,288 were reported as
   cached, in 4.6 seconds, which matches the bridge. Disabling twelve tool-adding features (apps, browser, computer use, image
   generation, multi-agent, plugins, hooks and similar) gave 13,669 input tokens, and also disabling the shell tool gave 13,029, so
   the program's own base instructions are most of the overhead and tool definitions are about 18 percent of it. Cached counts
   varied between 0 and 12,288 from run to run, so caching cannot be relied on. With the tool features and the shell tool
   disabled, four canary probes (a file in the working directory, one above it, one outside the project, and a shell command) all
   failed because no tool was available, whereas with the defaults the first three were read. This is a statement that the model
   had no tool to call, and it depends on the program's version and feature list, so it is not an operating-system boundary. A
   single call with 100 short items used 14,050 input tokens and returned a correct JSON array in 6.4 seconds, and one with 400 items
   used 17,050 and was correct in 15 seconds, so each added item cost about 10 input tokens and about 3 output tokens. The items
   were trivial (the second word of a sentence), so a task with long items gains much less from batching: a 10,000-token piece of
   text already outweighs the fixed overhead. Each figure is one run.
9. **What remains when the vendor program's tool features are disabled.** The same day, with the twelve tool features and the shell
   tool disabled, the program was asked to list the tools it could call. It listed, among others, an exec function, a patch tool, an
   image viewer, MCP resource readers, agent-spawning functions and a web tool, so the earlier result that four reads failed does
   not mean that no tools remain. The exec function reported that it has no filesystem access and a request to read a canary file
   through it failed. The web tool still worked: it fetched a harmless public page and returned its title, so a confined program
   can reach the internet even though a shell request failed to resolve a host. Setting the program's `web_search` option to
   `disabled` removed the web tool, and a repeat of the fetch failed. A setting to remove the image viewer (`tools.view_image=false`)
   did not remove it. The lists are the model's own report of its tools, so they are a tripwire and not proof. Conclusion: a
   confinement option should also disable the web tool, and its acceptance test should include a tool-list check and a web probe
   as well as the file and shell canaries. A name that is not a feature stopped the program with an error, but a misspelt config key was only warned about and ignored (the web tool stayed on) unless strict configuration checking was on, so a confinement should always use it. With the thirteen feature flags disabled, the web setting disabled and strict checking on, six probes (two relative reads, one absolute read, a shell command, a read through the exec function, and the web tool) all failed, where the default options read both files. Each figure is one run.
10. **A cross-field transfer test.** On 2026-11-01 a throwaway experiment used 124 open-access arXiv papers on 17 shelves (8 source
   fields, 6 target fields, 3 unrelated), a local 12-billion-parameter model for cards and themes, and two embedding models
   (bge-m3 and nomic-embed-text). The 8 transfers were annealing from statistical physics, bandits into game-tree search, sequential
   testing into engine matches, foraging into search stopping, epidemic spreading into information spread, immune systems into
   anomaly detection, ant trails into routing, and visual cortex into image recognition. The source papers, the measures and the
   queries (written by a separate agent) were fixed in advance, and each problem was stated in the target field's own words, in four
   forms. Mean reciprocal rank of the first source paper: card neutral description 0.47 and 0.45 (the two models), theme neutral
   description 0.43 and 0.48, card summary 0.36 and 0.23, theme summary 0.27 and 0.35, raw text chunks 0.22 and 0.29. In all four
   comparisons the neutral description beat the summary of the same item. Theme level did not beat card level once the card had a
   neutral description. Sequential testing, foraging and epidemic spreading were found at rank 1 by theme neutral descriptions;
   immune and annealing were weak in every variant. The home field's own version of the idea usually outranked the source field.
   A large survey on tree search reached the top 10 for more than half of all queries under theme variants. For the composite
   problem (a test that stops early, allocates trials, and avoids a poor setting), the sequential-testing and bandit sub-questions
   reached their source shelves in every variant, and the annealing one in 1 of 10 runs. With paragraph pointers and code finding the
   exact span, 98.6 percent of themes had a valid anchor. Haiku at low effort improved the median rank of 24 source themes from 207
   to 37 and of 16 control themes from 534 to 120 (among 1,677), so the gain was not specific to the right themes. Limits: 8
   transfers, 4 to 8 papers per shelf, famous transfers the models may know, a corpus chosen by the assistant, queries that describe
   each mechanism fairly directly, a metric that counts only a source paper as a hit, and no measure of novelty. Each figure is
   from one run.
11. **A follow-up on the saved embeddings.** The same day, a pre-registered follow-up (the 37 queries re-embedded with the same two
   models, nothing else recomputed) tested a hub correction, the mean of a paper's three best items, and a list of the best paper
   from each of the top five shelves. The baseline reproduced the original tables exactly. The hub correction raised mean
   reciprocal rank in 5 of 10 variant-and-model cells (the rule set in advance asked for 6) and cut hub papers from 11 to 3. It
   helped the weaker variants and lowered the neutral-description variants slightly (for example 0.468 to 0.420 for card neutral
   with one model). The mean of three items raised it in 2 of 10 cells and made hubs worse (17). The per-shelf list beat the plain
   top five in 3 of 10 cells (5 of 10 with the hub correction) and lost hits for card neutral descriptions (22 to 16 with one
   model). The physics shelf for the annealing sub-question stayed between ranks 3 and 13. Conclusion: no clear gain from either
   fix, hubs can be reduced, and the open problem is the home field's version outranking the source field. Limits: 32 queries per
   cell, one run, and a correction that uses the 37 queries themselves.
12. **A second follow-up: restated queries and the standard hub correction.** A second pre-registered follow-up on the same saved
   embeddings (restatement written by gemma4:12b with thinking off, temperature 0; the baseline again reproduced the original
   tables exactly). The restatement alone (Q1) lowered mean reciprocal rank in all 4 neutral-description cells (for example 0.468 to
   0.389 and 0.477 to 0.320) and cut the total found in the top 10 from 102 to 74; the raw query joined to the restatement (Q2)
   raised it in 1 of 4 cells and found 93. With the 3 flagged restatements (naming a field or method) removed the result was the
   same. The restatements worsened the weak annealing transfer (first source paper near rank 50 to 80 where the raw query gave 4 to
   40) and improved the immune transfer for one model only. The standard hub correction (item-neighbour, k = 10) raised ranking in 0
   of 10 cells and increased hub papers from 11 to 18, so the query-based correction of the first follow-up is the better of the two.
   Conclusion: no clear gain from either, and the restating step is not a replacement for the raw query. Limits: one restating model
   that was small and local, 32 queries per cell, one run. Tested again with a stronger model, the result may differ.
13. **A bake-off of three language models on the owner's model server.** A pre-registered run (rules and hash set before any model
   ran) gave the card prompt of the first experiment to gemma4:12b (the baseline from that experiment), phi4 and gpt-oss:20b on the 25
   source papers of the eight transfers, and the theme prompt on piece 1 of 13 of them. All three returned valid cards (25 of 25).
   With each model's own neutral descriptions put in the saved card index, mean reciprocal rank for the 32 transfer queries was 0.468
   (bge-m3) and 0.449 (nomic-embed-text) for gemma4:12b, 0.164 and 0.246 for phi4, and 0.571 and 0.653 for gpt-oss:20b, which found
   31 of 32 source papers in the top 10 against 25 and 28. phi4 wrote shorter, more field-bound descriptions (24 of 25 leaked field
   words). gpt-oss:20b matched the baseline on leaks (14 against 13 of 25) and took about the same time per card (17 s against 15 s,
   the baseline measured in the earlier run). Themes were the other way: gpt-oss:20b made more themes per piece (8.6 against 6.2),
   14 of its 112 paragraph ranges were invalid (the other two models: none), and 79 of 112 neutral theme descriptions leaked field
   words against 17 of 81 for the baseline. By the rules set in advance, gpt-oss:20b fits a stronger class for cards and gemma4:12b
   fits the bulk class for cards and themes, and phi4 fits neither. Limits: 25 papers, one run, temperature 0.2; gpt-oss:20b wrote
   neutral descriptions about twice as long as the others (253 words against 130 and 109), which alone may raise retrieval, so a
   length-matched control is needed before treating the gain as quality; the leak check is a word list; the baseline's times and
   first-attempt counts come from the earlier run; gpt-oss:20b is larger than the model server's 12 GB graphics memory and runs
   partly in system memory.
14. **A length-matched control for the card result.** A second pre-registered run tested whether gpt-oss:20b's higher retrieval
   (evidence note 13) came from its longer neutral descriptions. Variant A cut its existing descriptions to gemma4:12b's length for
   each paper, and variant B asked it again for at most 26 words per field. Mean reciprocal rank for the 32 transfer queries, with
   the baseline 0.468 (bge-m3) and 0.449 (nomic-embed-text): full length 0.571 and 0.653, A 0.554 and 0.586, B 0.576 and 0.495. By
   the rule set in advance the gain is not explained by length (A and B were at least the baseline for both embedding models), and
   leaks stayed level (10 and 12 of 25 against 13). The result is firm for bge-m3 and modest for nomic-embed-text with variant B,
   where the gain over the baseline (0.046) is within noise and 27 source papers were found in the top 10 against 28. Limits: 25
   papers, one run each, a cut can drop the end of a field, and instructing the model changes the whole card. A larger and held-out
   sample is needed before gpt-oss:20b is chosen for the card job.
15. **Judged pairs and candidate reach for the weave.** On 2026-11-04 a pre-registered run (rules and hash set before any judge
   call) reused the saved theme data of evidence note 10 (1,677 themes with neutral descriptions, 8 documented transfers). Test 2
   embedded the four query forms with bge-m3 and ranked all themes by their neutral descriptions: the best of three chosen source
   themes was in the top 100 for all 8 transfers using the best of the four forms, and in the top 30 for 4 of 8 using the whole
   problem alone (epidemic spreading was weakest: 35th at best, 239th on the whole form). Test 1 gave each judge the problem in
   the target field's words and one candidate's neutral description, with 3 true themes and 12 negatives per transfer (other
   transfers' themes, same-field themes that are not the idea, and the three nearest lookalikes), 144 pairs, and asked for a score
   from 0 to 10. `gemma4:12b` (thinking off) gave a mean AUC of 0.844, won 6 of 8 transfers and scored true themes 3.8 above
   lookalikes; `gpt-oss:20b` gave 0.903, 6 of 8 and 4.3. Both passed the rules set in advance (0.80, 5 of 8, 2.0). Both missed
   epidemic and immune by the strict rule, and gemma4:12b scored all three true immune themes 3 where gpt-oss:20b scored them 8.
   Only 2 of 24 true themes contained the source field's words. Read afterwards, 27 negatives scored 8 or more, and many look like
   real matches that were labelled wrong (regret minimization for bandits, link percolation for epidemic spread, sequential testing
   for a foraging stop rule), so the AUC is probably understated, and the judges give high scores freely, so a single score is a
   coarse signal. Limits: 8 famous transfers, I chose the true themes after seeing the earlier results, one run per judge,
   curated negatives and not a blind search, a retry on retryable bridge errors was added to the runner after one cold-load 500, no
   Haiku run (the rules called for it only if the local judges disagreed on the verdict), and nothing about whether a connection is
   new or useful. Tools: ask-ollama bridge, Ollama 0.35.1, `--temperature 0`; the repository has no commits. Pre-registration
   sha256 e85132489b9c0590c7e5a8136cf413a4a0b9cec29dbfb3b2fa16c92a827e4157.
16. **Blind discovery on the thin library, rated by models (Test 3).** On 2026-11-04 a pre-registered run (rules and hash set before
   any pair was judged; `prereg3.md` sha256 d7a21b7c406ef36ebe688d55cafaf339fb80a591b7aaa327e3207b62cf61e116) searched the saved
   library of note 10 (124 papers, 1,677 themes, mostly game AI plus eight source fields) with no known answer. For 120 problem
   themes (20 from each of six shelves) it took the five nearest themes on other shelves by bge-m3 on the neutral descriptions
   (580 pairs after removing the known transfers), scored all pairs with `gemma4:12b`, and rescored the top 80 with
   `gpt-oss:20b`. A sheet of 40 unlabelled pairs was made: the 30 top pairs (at most 2 per problem theme and per candidate theme)
   and 10 controls drawn from stage 1 scores of 2 or less, shuffled with seed 20261104. **Deviation from the pre-registration:** the
   rule named the owner as the only rater. The ratings are the work of GPT-6.1 Sol at medium effort, reviewed by the owner (how
   much the owner changed is not recorded), and of a second, blind rater, Claude Opus, given a blank copy of the sheet. Opus found 1
   of the 30 top pairs useful and new (U), 26 known (K) and 3 junk (J); the controls were 1 U and 9 J. GPT gave the same two U pairs
   and the same split except 25 K and 4 J in the top group, and the two raters agreed on 39 of 40 pairs. By the rule set in
   advance, at most 1 of the 30 top pairs useful and new fails, and the control group (1 of 10) did better than the top group
   (1 of 30), so the rule is met on both conditions for both raters. The one top U was pair 4, Action Reduction (gameai) with
   CoFineUCB (bandits): choose an action group before the action. The one control U was pair 29, System Call Analysis (security)
   with The Dark Degeneracy (astro): test whether benign and harmful runs look identical to the detector. The judge scored pair
   29 at 2 or less. The top group's final scores were 12 of 10 and 18 of 9, so stage 2 gave little spread, and 8 of the 30 were
   security with image. What it shows: the judge ranks pairs by fit, most of its best pairs (25 to 26 of 30) were standard ideas
   that restate the problem, and fit is not novelty. This is novelty against what a model already knows, which is the consumer's
   use, and it is not novelty to the owner. Limits: both raters are language models and may share a blind spot, the Opus run was
   brief, the library is thin and skewed, 40 pairs is a small sample, one run each, and there was no baseline of a model asked for
   cross-field ideas with no library. The owner has not rated the pairs alone. Sheet sha256 (with GPT ratings and notes)
   abac3e0efc1dbece595534a53616018e3cb1155f9af96dcca0add60d062a843b; Opus ratings sha256
   a09fc39a46a4231d108e529fdae5fd2b40c253ae6e7c6fab1512b1b0a612615b. Tools: ask-ollama bridge, Ollama 0.35.1, `--temperature 0`;
   the repository has no commits.
17. **Capture and conversion of ten web pages.** On 2026-11-04 ten pages were fetched once each with a plain GET and an honest
   user agent, 3 seconds apart, all returning status 200: an essay, Python documentation, two Wikipedia pages (one a large table
   page), a Fowler article, a Hacker News thread, an arXiv HTML paper, a GitHub repository page, a news index page, and a page
   built by scripts (a scraping practice site). Raw bytes, headers, final address and sha256 were kept (`fetch.json` sha256
   3240a36f637cedba8f7b3af734e957f7fe5f666f1befe3c38f826e7e0bc2513c). Each was converted by the Python standard library with a
   tag skip list and by trafilatura 2.3.1 (with beautifulsoup4 4.15.0 and lxml 6.1.3, in a scratch venv; `extract.py` sha256
   320b5a0591a99d2e3f01831048cb567d9aab2bdc2112a557775784cb2be248fd). Six pages gave clean text with both tools. The thread lost
   all 71 comments under trafilatura's defaults and returned them with comments on (25,600 characters); the repository page lost
   its README body under trafilatura and kept it, mixed with the file list, under the standard library; the script-built page
   gave 22 and 29 characters although its data is in a script tag; the news page is a list of 83 headlines; the essay has 599 line
   breaks and no paragraph or heading tags, so it is one block. A locator of heading path, paragraph number and excerpt hash was
   found again by the same tool on the same capture on all ten pages and by the other tool on none of four tried. A title was on
   every page, and an author, a published date, a language or a canonical address on some only. Limits: ten pages, one fetch each
   (change between fetches is untested), no robots or terms check, no script rendering, no PDFs, the extractors' defaults and one
   of my settings (comments off) affected the thread, and the locator test shows repeatability, not stability. The repository has
   no commits.
