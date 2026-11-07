# Reading

Status: Draft

This specifies the reading module, the part of the knowledge base that a workbench project installs so that its agent can search
the library while it brainstorms and drafts. It covers the reading interface, how the agent searches and reports, the budget, the
project setting that names shelves, feedback, and the later MCP door. It belongs to the design in `knowledge-base.md` and reads
what the other specs produce: the catalog of cards (`card.md`), the themes (`theme.md`) and, if built, the weave. **Nothing here is
final.** The spec stays `Draft` until the owner approves it, and any statement can be reopened. Each statement carries one of
three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

Much of this spec was split out of `knowledge-base.md`, and those statements keep their marks. The rest was added in the
conversation that followed.

## Scope

The reading module gives an agent a small, read-only way to ask the library for leads. This spec covers when the agent searches, how
it forms its queries, the operations the interface offers, what a result holds, the brainstorm report the agent returns, the budget, the project
setting, how a guest differs from the owner, feedback, failure when the host is unreachable, the safety rules for what is returned,
and the MCP door for tools outside the workbench. It does not cover how the library is built or filled, which the other specs
cover, or the module declaration's exact form, which is designed in the module's plan.

## Non-goals

- **[agreed]** Verifying claims. A result is a lead to follow, and a claim in it is verified before it is relied on.
- **[proposed]** Writing to the library. The reading interface changes no book, card, theme or shelf. It has read operations and two
  small note operations, record-feedback and record-used, and a search itself leaves one usage log entry. All of these are kept on
  the host and none is in the library's books. "The interface and notes" below lists every state change the helper can cause.
- **[proposed]** Replacing the project's own files, the owner's memory module or the code graph. The routing rule below says which
  question goes where.
- **[proposed]** Browsing by hand. The owner does not expect to browse the library; the interface is for an agent or a skill.

## Assumptions and constraints

- The workbench's `knowledge-tools` spec fixes the boundaries. Library content is reference data and untrusted as instruction. A
  tracked document cites it by source URL, retrieval date and content hash and never by path. An agent may run only reads that change
  nothing stored and send nothing out of the machine.
- The reading interface sends the query to the library host, which is another machine on the owner's network unless the host is
  the same machine. That sends text out of the machine and writes a usage log entry on the host, which is more than the workbench
  rule allows for an agent-safe read. This is an exception that this module's spec records, as the workbench did for `mempalace`
  (`knowledge-tools`, "What `mempalace` showed"). The owner has accepted it (see "Failure and safety").
- The module's interface is a pinned helper command, since the workbench has no MCP layer and one was deferred (decision
  `2026-10-21-module-code-lives-in-modules`). The host's address and the client's tokens are owner-only config and are never
  arguments (`library.md`).
- Search runs on the host and needs the pinned embedding model to embed a query (`models.md`).
- A result is returned as text marked as data, bounded in size and time, and is never passed to a shell.

## Behavior

### When the agent searches

- **[agreed]** In a project with the module installed, the agent searches the library on its own when it brainstorms or drafts a
  spec, decision, roadmap or plan, across the whole library.
- **[proposed]** The "whole library" above holds unless the project's setting or its project token narrows it (see "The project
  setting" and "Guests and narrowed tokens").
- **[proposed]** The module's policy block carries the routing rule in the same words as the other knowledge modules: a question
  about what is known outside the project in a domain goes to the knowledge base, a question about what was decided or tried goes to
  the memory module, a question about what a change touches goes to the code graph, and a question the current files answer is
  answered from the files and none of the three is consulted.
- **[proposed]** The planning skills (brainstorm and the drafting skills for specs, decisions, roadmaps and plans) call a search
  step. The step runs early, when the problem is being framed, and not at the end, when a lead can no longer change the design.
- **[proposed]** The agent does not search for a trivial or fully local task, and it says when it skipped the search and why. A
  search must never be a gate: if it fails or times out, the work goes on.
- **[proposed]** A project without the module is unaffected.

### Forming queries

- **[proposed]** The agent does not search once with the topic's own words. It restates the problem abstractly, splits it into
  sub-questions, and searches several variants: the topic's own words, the abstract description with the field's words removed, and
  each sub-question alone. The interface lets a search ask for the summary variant, the neutral-description variant or both. A test
  of a small local model's restatement (`knowledge-base.md`, Evidence note 12) found that it ranked the source papers worse than the
  raw query did, so the raw query is always searched too, and the restatement is an added variant and not a replacement.
- **[proposed]** The adjacent and improves-on tiers need queries that omit the topic words, or the removal of results already shown.
  An early experiment found that otherwise they return nearly the same papers as the on-topic tier (`knowledge-base.md`, Evidence
  notes).
- **[proposed]** The agent searches beyond the topic at hand for adjacent ideas and analogies from other fields, and matches by
  meaning and not only keyword.
- **[proposed]** The agent writes down the queries it ran, so the brainstorm report can say what was asked and a reader can repeat it.

### The interface

- **[proposed]** The reading interface is small and fixed: search, get a card, get a theme, follow hops, follow threads (if the
  weave exists), get an excerpt, get a citation line, and report the remaining budget. These are read operations. Two small note
  operations are added, record-feedback and record-used. Each is allowed for a project token and a machine token (owner scope) and
  not for a guest token.
- **[proposed]** The interface and notes. The helper can cause only these state changes: usage log entries (one per search),
  feedback notes, used notes, token issuance and rotation (`library.md`), and the host's request, refusal and re-issue logs. It
  changes no book, card, theme, shelf or weave.
- **[proposed]** A search takes a query and optional limits: the shelves to search, a date (only books added after it, or the library
  as it was then), the level (cards, themes or both) and the variant (summary, neutral description or both). It returns a bounded list.
- **[proposed]** Reading is layered, cheapest first: the card, a theme, the excerpt or section by anchor, the full text. Each
  response is bounded and says where the next piece is. Full text and originals need an owner-scope token (`library.md`).
- **[proposed]** The library report is a read operation too, for an agent that holds a project token, computed over the visible
  subset of that token. It tells the agent whether the library is healthy and how complete a shelf is. The doctor is for a machine
  token only (`library.md`), because it reports host details, and it returns health results without addresses or ranges.
- **[idea]** An operation that answers "is anything new relevant to what I already cited", taking the sources a project already
  cited (by URL and hash) and returning recent arrivals whose cards or themes sit close to them. See "Knowing what is new".

### What a result holds

- **[proposed]** A title in a result or a citation line is text from outside and is made by the one title rule of `book.md` where it is shown
  as well as where it is stored, and has no library folder in it (a search result has none once the index is rebuilt: search has
  no access to the library's folders, so a folder in a title indexed before the rule stays until the next `index`).
- **[proposed]** A result holds: the title, the shelf (only if the token may see it), a short summary, why it matched (which query,
  which variant and level, and the score), the date its book was added, whether it is flagged near-scope or partial, its caveats
  (including a retraction or withdrawal flag), the source's quality hints (citation count, venue, peer review) with the date they were
  read, a statement of how complete its source was, and a citation line made of the title, the source URL, the retrieval date and the content
  hash. The title is shown between quotation marks that it cannot close (a quotation mark in it becomes an apostrophe), so the fields
  after it are always the engine's own and a title cannot imitate them; a quotation mark or a space in the address is written as `%22` or
  `%20` for the same reason.
- **[proposed]** A result also says which pipeline stages its book has finished (for example, a card but no themes yet), so the agent
  and the owner can tell a thin result from a book that is still being processed (`pipeline.md`, "Real-time latency").
- **[agreed]** Quality hints and a retraction flag are shown to the agent and never remove a result. By default they do not change
  its rank.
- **[proposed]** A theme result also holds the anchor of its excerpt and the excerpt's hash, so the agent can read the passage and a
  document can cite it. The anchor is a typed locator within a part of a version (`book.md`). A reader that meets a locator kind it
  does not know shows the raw value and does not guess, and a result for a book with several parts names the part.
- **[proposed]** A search says how complete its source was, for example "this shelf is being seeded: 120 of about 250 filed, 80
  with cards", so that a missing result is not mistaken for missing knowledge (`pipeline.md`).
- **[proposed]** Results from one book are grouped, and a book that matches for many unrelated queries (a hub) is shown with its
  score reduced, because the early experiments found a hub paper crowding out better answers. How much reduction is a setting tuned on real shelves. A hub is partly an effect of ranking a book by its best item. In a follow-up on the experiment's saved embeddings, reducing an item's score by how near it is to many queries (a correction that needs only the log of recent queries) cut the number of hub papers from 11 to 3 across the ten test cells, but its effect on ranking was mixed: it helped the weaker variants and slightly lowered the neutral-description variants, which were the best. Scoring a book by the mean of its three best items did not help and produced more hubs. A hub correction is therefore a setting to test on real shelves and not a default.
- **[idea]** Diversifying the adjacent and improves-on tiers across shelves or buckets, by showing the best paper of each of the top five shelves, did not beat the plain top five in the follow-up (better in 3 of 10 cells, and worse for the neutral-description variants), so it is not recommended as a default. In the experiment the home field's own version of an idea usually outranked the source field's, and that problem is still open.

### The brainstorm report

- **[agreed]** The agent follows hops from a card to its book to adjacent cards within a fixed budget, then reports what it
  found and recommends when and where to continue. It does not go past the budget unasked.
- **[agreed]** The brainstorm report is sorted into three tiers: **on topic**, **adjacent** and **improves on the idea**. Where nothing useful
  was found it says so.
- **[proposed]** The brainstorm report carries cite-ready provenance for each item (source URL, retrieval date, content hash) and
  marks everything as untrusted data. An instruction found in a card or a book is ignored.
- **[proposed]** The brainstorm report lists the queries it ran and the shelves it searched, and says which parts of the library
  were still being filled.
- **[idea]** If the weave exists, the brainstorm report may gain a fourth section of hypotheses: combinations of themes from different
  shelves, each citing every theme used and marked as a hypothesis, not a finding.

### The budget

- **[proposed]** The budget is set by the owner. The default is generous, because a stingy budget stops the agent short of the non-obvious finds that are the point of the library
  **[agreed]**; the number is left to the builder and tuned from the usage log. It is a limit on the number of calls, on the
  amount returned into the agent's context, and on time, and the agent can ask the interface how much remains.
- **[proposed]** The budget protects the agent's context. A search that fills the context with unhelpful cards is a failure the
  design guards against, so results are bounded and ranked, and the agent reads a few and stops.
- **[proposed]** At the end of the budget the brainstorm report says what was left unexplored and recommends where to continue, so the owner
  can allow more.

### The project setting

- **[proposed]** A project setting names which shelves it searches, so a hardware project does not search a cooking shelf. The
  setting is a tracked file and names shelves, never library paths.
- **[proposed]** The project's own list is a hint that the agent applies. A real limit is one the owner sets on the host for that
  project's token (`library.md`, "Credentials"), because a project's tracked files are untrusted.
- **[proposed]** A relevant book whose home shelf a project excludes would be missed, so the setting excludes shelves from a
  search by default and the agent may widen it for an adjacent query, within what the token allows.

### Guests and the owner

- **[proposed]** A guest's token sees only shared shelves, and gets cards, themes, short excerpts and citation lines. Full text and
  originals need an owner-scope token. A guest's search runs against the shared subset alone, so a count, a hint or a "where to
  continue" never reveals a private shelf (`shelf.md`).
- **[proposed]** The project token's narrowing, set by the owner on the host, limits what a project can read whatever its setting
  says (`library.md`).

### Guests and narrowed tokens

- **[proposed]** A result's size and the excerpts a token may read are capped: a size cap per request and a cumulative cap per book
  per token. Sections by anchor are not readable with a guest token.
- **[proposed]** Hub scores and duplicate grouping are computed over the visible subset of the token, so they reveal nothing about a
  book the token cannot see.
- **[proposed]** Links in a card or a result to a book the token cannot see (resolved citations, same-work notes) are redacted.
- **[proposed]** The "answered" notice (see "Usage log and demand") is computed over the token's visible subset.
- **[proposed]** The privacy rules apply to every token, including a project narrowed on the host, and not to guests alone.

### Feedback

- **[proposed]** The owner may record one line on whether a search helped: useful, partly, or not. This is a *feedback note*. It is
  kept on the host with the search it refers to, and never in a tracked file.
- **[agreed]** Feedback feeds the evaluation (`testing.md`) and the choice of defaults. It is not used to change a result's rank
  automatically, because a library that learns what the owner already likes would drift toward the obvious.
- **[proposed]** The host's usage log of searches is described in "Usage log and demand". The owner can see it and clear it, and it
  is not shared with a guest.
- **[proposed]** The retention defaults of the usage log, the feedback notes and the used notes are in `library.md`.

### Used notes

- **[agreed]** The library keeps a record of where its items have been used. When an agent cites a library item in a project's
  document, it records a *used note* on the host.
- **[proposed]** A used note holds: the item (book, and theme if any), the project, the kind of document (spec, decision, roadmap or
  plan), and the date. It holds no excerpt and no library path. It points from the library's untracked data to a project, so it
  breaks no rule about tracked files pointing at untracked ones.
- **[proposed]** The project field of a used note comes from the token that recorded it and not from the agent's claim.
- **[proposed]** Used notes serve three purposes. They measure the success test, whether brainstorms improved, by counting items
  used per search and per shelf. They protect books from being weeded unknowingly, because a weeding list shows where each book was
  used (`book.md`). And, if the weave exists, a combination that was used is shown to the owner as evidence that it was relied on
  (`weave.md`).
- **[proposed]** Used notes are shown to the owner as evidence and as warnings, for example on a weeding list. They are not used to
  rank results or to weave threads automatically.
- **[proposed]** A used note is a claim by an agent, and it is data. It changes nothing in the library except a warning and a count,
  and it is kept on the host, bounded, visible to the owner and clearable. The exception for the owner's host covers it, with the
  query, the usage log entry and the feedback note.

### Reference stubs

- **[agreed]** A result can be turned into a ready-made reference record. A skill step writes it into the project's
  `docs/references/` in the form the workbench's reference rules require, from the result's citation line: the source URL, the
  retrieval date, the content hash, the title and a one-line note on why it matters.
- **[proposed]** The stub is the agent's ordinary edit of a tracked project document, so it follows the project's own rules for
  documents. It holds no library path and no copy of the source beyond a short quotation, so nothing tracked points at anything
  untracked.
- **[proposed]** The stub is data, written from the library's metadata. An instruction found in a result is ignored, and the
  owner reviews the record like any other document.
- **[proposed]** The title, the note and the quotation in a stub come from untrusted metadata. A stub is written with fixed fields
  only, with markup stripped, marked as untrusted data, with a short quotation, and the owner reviews it before it is committed.
- **[proposed]** Writing a stub also writes a used note, so the library knows the item was relied on.

### Usage log and demand

- **[agreed]** Searches leave a signal that helps the library grow where it is needed (`shelf.md`, "Demand from searches"). It helps
  prioritise and direct the crawler, and it is not the only driver.
- **[proposed]** Every search writes one *usage log entry* on the host: the time, the project that asked, the query and its
  variants, the number of results above the score floor, the top score, and whether the source was still being filled. An entry is
  a record of what happened and carries no model judgment. Wanted topics are computed from the usage log.
- **[proposed]** A search is a gap only by fixed rules, set as settings: no result above the score floor, or a top score below a
  second floor. Feedback of "not useful" is kept and shown with the entry but is not a trigger. A search of a shelf that was still
  being seeded is marked, because a miss there may only mean the shelf is not finished.
- **[proposed]** A guest's searches are not recorded for demand unless the owner allows it. The owner's and projects' searches are.
- **[proposed]** The usage log is kept on the host, bounded in size and age, visible to the owner, and can be cleared. It is never
  in a tracked file.
- **[proposed]** When a stored gap is answered by later additions, the next search from that project says so in the brainstorm
  report.

### Failure and safety

- **[agreed]** The owner's own library host is treated as inside the machine boundary of the workbench rule on agent-safe reads. A
  search sends its query only to that host, which is the owner's and is on the owner's network, and leaves a usage log entry there.
  The reading helper may send a query only to the host named in the owner-only config.
- **[proposed]** The owner's host is not the end of the path, and the exception states what else the query can reach. The host
  embeds the query with the pinned embedding model, which may run on another machine of the owner's or in a vendor cloud, so the
  query can reach the embedding endpoint. Wanted topics derived from queries can later become queries to external sources, made by
  the crawler under the shelf's rules (`shelf.md`).
- **[proposed]** The exception covers the helper sending a query to the configured host and the host's notes (the usage log entry,
  the feedback note and the used note), and nothing else the helper does. It does not cover any operation that changes the library,
  which is not in the reading interface at all.

- **[proposed]** If the host is unreachable, the reading side says so and the brainstorm continues. A call has a time limit, and a
  slow search is cut off and reported as incomplete.
- **[proposed]** Everything returned is marked as data. An instruction found in a card, a theme or an excerpt is ignored, and a
  result never grants approval, never overrides an accepted decision, a spec or the current code (`AGENTS.md`, "Source of truth").
- **[proposed]** The helper runs no shell on a result, bounds each response, and treats the host's reply as untrusted text.
- **[proposed]** A finding that should shape the project is recorded in a spec, a decision or a reference, citing the source by URL,
  retrieval date and hash. The library holds no decisions or conversation (`knowledge-base.md`).

### Knowing what is new

- **[idea]** Knowing whether anything new bears on the work, with no changelog and no marker kept anywhere. From simplest: a
  brainstorm report says how many of its results arrived recently; a search takes a date, either "added after" or "as of"; the project passes the
  sources it already cited (by URL and hash) and the host returns recent arrivals whose cards or themes sit close to them; and, if
  a weave exists, a digest for the owner of new themes that attach strongly to themes already relied on, or of new threads between
  shelves that were not linked before. A separate list of new items was considered and set aside as more effort than it is worth.

### The MCP door

- **[agreed]** The workbench agent is the first and most frequent user, through a governed workbench command. An MCP server is a
  later door onto the same interface, for tools outside the workbench.
- **[proposed]** The MCP server returns cards, themes and short excerpts by default and full text on request, marks everything as
  data, and has a cards-only mode for the least trusted clients. It offers a prompt carrying the brainstorming method and the
  three-tier brainstorm report. Clients that only run local servers may need a small local shim that forwards to the host.
- **[agreed]** An MCP server is a network listener and so uses the same address lists as the host interface (`library.md`, "Network
  access"). It authenticates with tokens like any other client.

## Acceptance criteria

All of these are provisional until the spec is approved.

- In a project with the module installed, a brainstorm request runs a bounded search through the host, returns a three-tier
  brainstorm report with cite-ready provenance, marks it as data, and stays within its budget.
- A project without the module is unaffected, and an unreachable host does not stop the brainstorm.
- The brainstorm report lists the queries it ran and the shelves it searched, and says how complete the sources were.
- Where nothing useful is found, the brainstorm report says so.
- On a small hand-made game-AI library, the prompt "brainstorm fitness functions for an Othello AI's board-strength evaluation"
  returns on-topic books on evaluation functions, adjacent books on other approaches to Othello, and books on improving on
  hand-built evaluation, including ones that use "evaluation function" and not "fitness function". The owner judges the result
  useful.
- The first test set is seven real questions from two of the owner's game-engine projects (`knowledge-base.md`). The opening-book and
  early-stopping questions, known misses of card-level search, are found, or the spec records why they were not.
- The interface changes no book, card, theme or shelf. Its only state changes are the listed ones (usage log entries, feedback and
  used notes, token issuance and rotation, the host's logs), and a result never carries an instruction that the agent obeys.
- The helper sends a query only to the host named in the owner-only config. The spec names the embedding endpoint and the
  crawler's later queries as the other places a query's content can reach.
- A guest's search returns nothing from a private shelf, and a project narrowed on the host cannot read outside its shelves
  whatever its setting says.
- Hub scores, duplicate grouping, redacted links and the "answered" notice are computed over the token's visible subset, and a
  guest token cannot read sections by anchor.
- A hub book that matches many unrelated queries is shown with a reduced score.
- A retracted or withdrawn work still appears in results, carries the caveat, and is not removed or re-ranked by it. Quality hints
  are shown and do not exclude a work.
- Citing a library item in a project document records a used note with the project and kind of document and no excerpt, and a
  weeding list shows where each book was used.
- A result turned into a reference stub holds the source URL, retrieval date, content hash and title, and no library path.
- The usage log, the feedback notes and the used notes are kept on the host and are not in any tracked file.
- The MCP server, if built, refuses the same addresses as the host interface.

## Open questions

- How the exception for the host is worded in the module's own spec and policy block, and whether the workbench's
  `knowledge-tools` spec should name it, since it was written before a remote store existed.
- Whether cards and themes alone are enough, or book text must be searched too, and the matching mechanism. An early experiment
  found papers in the text that card search missed.
- The budget defaults, and the default size of a result list.
- How the planning skills call the search step so it helps and does not annoy, and how the agent decides a task is trivial.
- How much a hub's score is reduced, and how a hub is detected without a model call.
- Whether feedback is stored with the query text or only a hash of it.
- The exact form of the module declaration and the command's arguments, which are designed in the module's plan.
- How a used note is triggered reliably when an agent cites an item, since it depends on the agent following the skill, and the
  form of the workbench's reference record that a stub must match.
- Whether quality hints should ever be allowed a mild weight in rank, set by the owner, given the default of none.

## Governing decisions and references

- Decisions: none recorded in this repository yet. The rules come from the workbench's `knowledge-tools` spec and the decisions named
  in `knowledge-base.md`, which this project adopts and will restate when the owner accepts them.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `card.md`, `theme.md`, `shelf.md`, `library.md`,
  `pipeline.md`, `models.md`, `book.md`, `weave.md` and `testing.md`.
- Evidence notes in `knowledge-base.md` and `theme.md` summarise the experiments on tiers, hubs and vocabulary mismatch.
