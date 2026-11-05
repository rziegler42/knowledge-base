# Shelf

Status: Draft

This specifies the shelf, the domain or area of interest that groups books, carries the rules under which books are filed
automatically, and decides who may see what. It belongs to the design in `knowledge-base.md` and builds on the book in `book.md`.
**Nothing here is final.** The spec stays `Draft` until the owner approves it, and any statement can be reopened. Each statement
carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

Much of this spec was split out of `knowledge-base.md`, and those statements keep their marks. The rest was added in the
conversation that followed.

## Scope

A shelf is a named area of interest with a scope statement and a set of rules. This spec covers how a shelf is created and
defined, the limits it can carry, its states (new, seeding, steady, paused, removed), how it is seeded and kept growing, how the crawler
behaves, how its books are reshelved, its safeguards, and whether it is shared or private. It does not cover what a book is
(`book.md`), the themes inside books (`theme.md`), the card, the weave, or the library as a whole; they have their own specs.

## Non-goals

- **[agreed]** Roles and fine-grained access control. A shelf is shared or private and nothing finer.
- **[agreed]** Any limit on the size of a shelf, its number of books, or the number of shelves in a library, unless the owner sets
  one for a shelf.
- **[agreed]** Judging licenses. The tooling records the terms a source states and does not decide what is allowed.

## Assumptions and constraints

- A book sits on one home shelf (`knowledge-base.md`, `book.md`). The shelf is metadata of the book, so moving a book to another
  shelf moves no bytes.
- Everything fetched from outside is untrusted data. The crawler is a fixed fetcher with rules and not an agent, so untrusted
  text cannot add a new source domain, and what it can influence (work cited by held books, alternate copies) is bounded by the
  shelf's allowed sources and relevance rules.
- The owner's wishes about rights: the tooling does not know the law where the owner lives, does not want to restrict, and
  assumes permission to use content unless a source specifically says otherwise.
- Every pipeline stage runs on whatever models the owner lists, local or cloud, and the owner has on/off switches for model work, globally and per machine
  (`knowledge-base.md`, Models).

## Behavior

### Creating and defining a shelf

- **[agreed]** The owner can create shelves remotely, without a terminal, and the actions that need the owner use the workbench's
  permission levels (`block`, `ask`, `delegated`, `none`), set per action by the owner. See "Permission levels" below.
- **[agreed]** Creating a shelf has two parts: an agent may propose one, and approving the proposal is the governed action.
- **[proposed]** A shelf is a folder with a name and a one- or two-sentence scope statement, which placement matches against. No
  charter or required question list.
- **[agreed]** Filing is mostly automated. The owner, with the help of an AI, defines a shelf together with its limits, such as
  license, size and fetch speed. Once the owner approves those rules, candidates that meet them are filed without per-book approval.
- **[proposed]** The limits a shelf can carry: the scope statement, allowed sources and file types, an optional license rule (none
  by default), a size limit per item, optional limits on total size and book count (none by default), fetch speed per site, a daily
  budget for fetches and model calls, and a relevance threshold. An AI proposes the rules and defaults, the owner reviews them, and
  the approval action approves the exact rules, bound to a digest of them. A change to a rule needs a new approval, and an agent
  cannot change a rule.
- **[proposed]** Each shelf has its own daily cap on fetches and model calls. Separately, the library's total capacity is divided
  between shelves by their weights (see "Priority between shelves"), so there is no separate library-wide cap unless the owner
  sets one.
- **[agreed]** The owner may edit a shelf's rules file by hand or change it through the AI and commands. Either way the change
  alters the file's digest, so it takes effect only after it is approved again.
- **[proposed]** The rules are a small plain-text file per shelf, kept in the library and not in the repository. The proposal shows
  the owner a plain-English summary: what will be fetched and from where, how fast, what it will not do, the daily budget, and
  whether the shelf is shared. A changed proposal shows what changed.
- **[proposed]** A proposal for a new shelf states its visibility explicitly in the plain-English summary. The default stays
  shared.
- **[agreed]** The owner does not want to limit the size of a shelf, the number of books on it, or the number of shelves in a
  library. There is no such limit unless the owner sets one for a shelf.
- **[idea]** Grouping shelves into sections, if hundreds of shelves make flat placement slow and noisy.

### Permission levels

The levels work as the workbench defines them (`command-permissions.md` in the workbench): `block` means the owner at a terminal,
`ask` means the agent runs the action and the owner confirms a prompt on their channel, including a remote one, with the command
carrying the digest of its preview, `delegated` means a gate the action declares has passed, and `none` means nothing is needed.
The owner sets a level per action in their personal settings, and the workbench default for an owner-run action is `block`.

- **[agreed]** These shelf actions are governed, each with its own key. The key names are provisional. Every one defaults to
  `block`, as the workbench does, and the owner opts in per action with `ask`.
  - `shelf-approve`: approve a shelf's rules, which also creates the shelf and starts seeding. It is the action that matters most.
    A change of scope, name, priority or any other rule goes through it too.
  - `shelf-visibility`: change a shelf from shared to private or the reverse.
  - `reshelve-approve`: approve a reshelving list, which shows any change of visibility. Emptying, merging, splitting and moving
    books to a new shelf are all reshelving lists.
  - `shelf-resume`: resume a paused shelf.
  - `shelf-reseed`: run seeding again.
  - `book-weed`: remove books, one or a whole shelf's worth, which deletes data.
  - `shelf-remove`: remove a shelf that has no active books.
- **[proposed]** These are agent-safe and need no level: *propose a shelf* or a rule change (it writes only a pending proposal, which
  has no effect), *preview a proposal* (prints the summary and its digest), and every read.
- **[proposed]** Each governed action has a preview that prints the digest, as the workbench requires of a command that offers
  `ask`. A pause by the circuit breaker needs no level, because
  stopping is always safe.
- **[agreed]** Every governed action offers all four levels, `block`, `ask`, `delegated` and `none`, and ships at `block`. The
  owner chooses per action. Today the workbench offers `delegated` only for plan approval, where the gate is a converged, sealed
  review, so `delegated` for a shelf action needs a gate that the action declares, and that gate is an open question
  (`library.md`). Until it is defined, `delegated` reads as `block`, as the workbench reads it for an action without a gate.
- **[idea]** A later gate for shelf rules might be a review of the proposal by a second model plus a check that the rules stay
  inside bounds the owner set, but this needs a change in the workbench.
- **[agreed]** The host decides. A governed action runs as the host's own helper, which computes the digest of the exact rules
  itself. The host also has a ceiling in the owner-only config, such as "approval only at a terminal on the host", and the stricter
  of the client's level and the host's ceiling wins. The client's `ask` prompt is only the confirmation channel. As in the
  workbench, anything with a shell as the owner on a trusted machine is treated as the owner.
- **[agreed]** The host cannot verify a client's `ask` prompt, so what it accepts as proof of approval is the client's workbench
  level for that action within the host's ceiling, plus the digest it computes itself. There is no separate approval credential. A
  stricter option for chosen actions may be added later without redoing this design.
- **[agreed]** Credentials stay out of this. A machine token, a project token and a guest token are not created or shown through an
  `ask` prompt, and an agent never holds a machine token or the power to enrol a machine or create a guest token. An agent reads
  through a project token. Creating tokens stays `block`.
- **[proposed]** At `ask` the confirmation proves the owner saw the command and a digest, not that they read every rule. The
  summary is therefore short, and the digest is bound to the exact rules file, so rules changed after the preview do not match.
  The workbench accepts that a script an agent writes could get around an `ask` prompt, and shelf approval inherits that limit.
- **[proposed]** The default host ceiling is "governed actions only at a terminal on the host", so a level of `ask`, `delegated` or
  `none` takes effect only after the owner loosens the ceiling, for example to allow approval with `ask` from enrolled machines.
- **[proposed]** The host helper, not the proposer, renders the plain-English summary of the rules, deterministically from the rules
  file. Any text of untrusted origin in it (a scope statement written by an AI, a wanted-topic description) is shown as quoted
  data.

### Relevance

- **[agreed]** The relevance threshold errs loose. Noise is bad, but losing something that could lead to a novel concept is worse, in
  line with the guiding principle in `knowledge-base.md`.
- **[proposed]** Relevance is scored in two steps. A cheap embedding similarity to the scope statement is a first filter, set low.
  Candidates that pass get a short local-model judgment with a one-line reason.
- **[agreed]** Approving a shelf's rules starts seeding at once, with no preview before it goes live. **[proposed]** The threshold
  is therefore tuned from what the first batch actually filed: the shelf's status shows sample accepts and rejects near the
  threshold, and the owner moves the threshold, which is a rules change that goes through approval. Because relevance errs loose,
  the first batch may hold some noise, and weeding it is the owner's governed action. A shelf's scope can be widened later, and widening runs seeding again.
- **[proposed]** A candidate rejected near the threshold is not discarded without a trace. It goes on the seen list with its score
  and reason, so the owner or an agent can pull it back. Clear rejects are recorded with a reason too, so they are not fetched again.
- **[proposed]** A source whose topic is adjacent to the scope but outside it can be filed on the shelf nearest to it, flagged
  with the near-scope flag, and not rejected. The shelf's own rules still apply.
- **[agreed]** The near-scope flag is a label. It is returned in results so an agent can weigh it, and it does not demote the book
  in ranking, because losing a lead is worse than noise.

### Shelves and standard classifications

- **[agreed]** Shelves stay owner-defined and flat. They are not a library classification such as Dewey: a shelf is an interest
  area with a scope statement and rules, may span several classes, and a fixed field-based tree would reinforce the boundaries the
  library is meant to find ideas across.
- **[agreed]** A standard classification is optional book metadata (`book.md`), recorded when a source provides it. The weave uses it
  as a cheap, model-independent measure of how far apart two fields are, and placement may use it as a hint.
- **[agreed]** The owner wants to borrow the buckets of a library classification such as Dewey, not its call numbers, so that the
  tooling does not invent its own scheme.
- **[proposed]** A shelf may carry an optional *bucket*: a broad category from a named scheme, stored in its rules file with the
  scheme's name. It is a label for grouping and not a rule, and a shelf that spans several buckets lists them.
- **[proposed]** Buckets are used in four ways. When a shelf is proposed, the AI suggests its bucket or buckets and shows the
  neighbouring shelves. A library report shows which buckets have shelves and which have none, so the library grows in breadth, as
  the brainstorm report's tiers intend. Sections, if hundreds of shelves need them, follow the buckets. The weave reads the distance between
  the buckets of two themes' shelves as a cheap measure of how far apart the fields are.
- **[agreed]** The default scheme for buckets is OpenAlex's domains and fields, because most of the library will be papers and
  papers arrive tagged by OpenAlex or arXiv, so the bucket comes from the source and is not guessed. The Library of Congress
  Classification is the supported alternate, suited to book-heavy and humanities shelves and to subjects such as games, and Dewey
  is used only if someone maps it in.
- **[agreed]** The tooling bundles no classification schedule. Buckets come from the source's own tags or from a mapping the owner
  supplies, so the rights of any schedule are not the tooling's concern.
- **[agreed]** When a topic fits the default scheme badly, such as games and recreation in OpenAlex, the owner can add a custom
  bucket with their own name, marked as custom. It is not used for field distance, which is unknown for that shelf.
- **[proposed]** A library has one default scheme. A shelf may carry extra labels from other schemes, each stored with its scheme's
  name, and the tooling never compares codes across schemes. The weave's field distance uses the default scheme only.
- **[proposed]** The vocabulary of buckets is a setting, with a mapping so that another scheme can be used. A bucket is broad, two
  levels at most, so that an owner's own interests are never forced into a fine category.
- **[idea]** A shelf proposal could suggest a scope by listing the categories that most of its seed candidates fall in, as
  information for the owner and not as a rule.

### Priority between shelves

- **[agreed]** The owner can give priority to the shelves they are more interested in, and no shelf is starved by it.
- **[agreed]** A shelf has a priority weight, a small whole number with a default that is the same for every shelf. It is part of
  the shelf's rules file, so a change goes through the same approval as any other change of rules.
- **[agreed]** The weight divides the library's limited capacity in proportion: the daily fetch budget, the crawler's visits, and
  the order in which model work from different shelves is taken from the queue. Within one shelf the order stays as it is
  (newest and most relevant first).
- **[agreed]** Priority is a share and not a strict order. Every shelf with work waiting gets at least a guaranteed minimum share,
  a setting, so that a shelf of low weight still advances. The owner may set the minimum to a higher value, and cannot set a
  shelf's share to nothing without pausing the shelf explicitly.
- **[agreed]** Waiting work also ages: the longer an item has waited, the more its priority rises, so no item waits for ever
  because other shelves keep arriving.
- **[agreed]** Priority affects only how fast a shelf grows and is processed. It does not affect what a search returns or how
  results are ranked, so a low-priority shelf is searched on equal terms.
- **[proposed]** The library report shows, for each shelf, its weight, the share of capacity it actually received, and the age of
  its oldest waiting item, so the owner can see whether a shelf is being starved.
- **[idea]** How the shares are scheduled is defined in `pipeline.md` ("Scheduling and priority"). The weights here are only the
  input.

### Demand from searches

- **[agreed]** Searches that find little are a signal for growing the library where it is needed. The owner likes this because it
  helps flesh out the library in a deterministic way. Searches must not be the only driver, but they help prioritise and direct the
  crawler.
- **[proposed]** A *gap* is a search whose best results are weak by fixed score rules (no result above a score floor), not by a model's opinion, so the same searches give the same gaps. The
  rules are settings, and the searches come from the usage log (`reading.md`). The feedback "not useful" is kept and shown with the
  topic, but it is not a trigger for a gap.
- **[proposed]** Gaps are grouped by the similarity of their queries, using the pinned embedding model and a fixed method. Each group
  becomes a *wanted topic*: a short description taken from a representative query, its evidence (how many separate searches, from
  how many projects, over what dates), and the nearest shelf or none.
- **[agreed]** A wanted topic counts distinct projects and tokens, not raw searches, so one agent repeating a search does not
  make demand.
- **[agreed]** A wanted topic needs repetition before it affects the crawler: at least a set number of separate gap searches, or
  searches from more than one project, over more than one day. One odd query steers nothing.
- **[agreed]** The owner does not review wanted-topic text before it is used. Once a wanted topic meets the repetition rule, a model
  derives the queries for external sources from it, after a filter has removed anything that looks like a project name, a path, a
  codename or another identifier. The text of every external query is logged and shown in the library report with its wanted
  topic, so the owner can see what was sent and dismiss a topic.
- **[proposed]** The filter lowers the chance of a private detail reaching a search engine and cannot remove it, because a query
  written from a private project may carry it in ordinary words. The derived query describes the subject in general terms and not
  the project's wording, and the owner can turn external queries off for a shelf or for the library, which stops this step and
  nothing else.
- **[agreed]** A wanted topic that falls inside a shelf's scope becomes an extra seed query for that shelf's crawler. It is
  searched across the sources the shelf already allows, under the shelf's approved rules, so it needs no new approval. A candidate
  it finds goes through the normal relevance filter and filing.
- **[agreed]** A wanted topic that falls outside every shelf's scope becomes a proposal for a new shelf or for widening a
  scope. It is never applied on its own. Approval is the usual governed action (`shelf-approve`).
- **[agreed]** Demand is one input among several and has a cap. A setting limits the share of the crawler's capacity that demand
  may take, so the rest still goes to the shelf's own scope and to following the citations of books already held. The owner's shelf
  weights stay primary (`shelf.md`, "Priority between shelves"): demand adjusts emphasis inside a shelf and proposes new shelves, and
  does not override the weights.
- **[proposed]** Within a shelf, relevance to an open wanted topic is one more factor in the order of work, after the existing
  "newest and most relevant first", and it is bounded by the same cap.
- **[agreed]** The owner can see the wanted topics with their evidence in the library report, and can dismiss one (it is then
  suppressed), pin one, or add one by hand. A topic added by hand is a deterministic want list and counts as demand with no
  repetition needed. These owner actions are governed actions with the default `block`, and an agent cannot perform them at `block`
  or `ask` without the owner.
- **[proposed]** The loop closes. After books are added, the stored gap queries are run again, which is cheap because it uses
  embeddings and no model. A wanted topic whose queries now find results above the floor is marked answered, and the next search
  from an affected project is told that the library has since added something on its earlier unmet need. The check is computed over
  the visible subset of each project's or guest's own token, so it never reveals a hit on a shelf the reader cannot see.
- **[proposed]** Demand is untrusted data. A query is written by an agent that may have read untrusted content, so a query can
  never name a URL to fetch. Only the shelf's allowed sources are searched. Demand needs repetition, is capped, and is visible to
  the owner, which limits how far an injected query can steer the crawler.
- **[proposed]** A wanted topic that matches a private shelf stays private: it is invisible to a guest, as the shelf is.

### Suggesting splits and merges

- **[agreed]** The library may suggest splitting or combining shelves.
- **[proposed]** A suggestion is information and never acts on its own. It appears in the library report with its evidence, and
  if the owner accepts it, it becomes an ordinary reshelving proposal, listed and approved as a list, with any change of
  visibility shown.
- **[proposed]** The signals are measurable and use the card embeddings the library already holds, with no model call. A shelf
  whose cards fall into distinct, far-apart groups may be two shelves. Two shelves that overlap heavily, or that keep producing
  near-tie placements, may be one. A shelf that stays very small after seeding is a candidate to fold into a neighbour.
- **[proposed]** A suggestion shows the groups it found, with sample books from each, so the owner can judge whether a cluster is
  meaningful. A cluster is not always a topic, and the owner decides.
- **[proposed]** A suggestion that was declined is remembered, so it is not repeated unless the evidence has changed.

### Renaming a shelf

- **[proposed]** A shelf has a stable id, like a book's, and a name. Books, the seen list, the event log and the catalog refer to the
  shelf by its id, so renaming changes no bytes and breaks no reference.
- **[proposed]** The previous names are kept as aliases, so a command, a skill or a note that uses an old name still finds the
  shelf, and the result says the name has changed. An old or removed shelf name asked for by a token that cannot see the shelf gets
  the same answer as a name that never existed ("no such shelf"). Aliases created while a shelf was private are dropped when it is
  made shared.
- **[proposed]** The name is part of the rules file, so a rename is a rules change and needs a new approval like any other. This
  keeps one rule: an agent cannot change a shelf's rules.
- **[proposed]** On a shared shelf, a guest sees the new name at once. A private shelf stays invisible whatever its name.
- **[proposed]** Merging two shelves and splitting one are reshelving operations and not renames: a proposal moves books, shows any
  change of visibility, and is approved as a list.

### Emptying and removing a shelf

- **[agreed]** Emptying a shelf moves its books to other shelves and deletes nothing. The move is listed before it runs, with a reason
  for each book and any change of visibility, and approved as a list.
- **[agreed]** A book that fits no other shelf goes to a holding shelf, one per library, and not into deletion. It is searchable
  by the owner, and it is a candidate for any shelf created later. The holding shelf is private, because hiding a book from a guest
  can be undone and exposing one cannot, and the proposal shows the change of visibility.
- **[agreed]** The holding shelf is named `holding`. Only books moved from other shelves go onto it. The crawler and relevance
  scoring never file onto it directly.
- **[proposed]** Weeding every book on a shelf is a different action, not a form of emptying. It is the governed weeding action
  (`book-weed`), run on the whole shelf, and it is listed and approved as a list.
- **[proposed]** An emptied shelf is paused, because its scope would otherwise let the crawler refill it at the next steady-mode run.
  The owner resumes it, or changes its scope, when they want it to grow again.
- **[proposed]** A shelf may be removed when it has no active books ("empty" means no active books). Weeded and removed books keep
  their records with the shelf's id. The shelf's rules file, id and aliases are kept as a record, marked removed, so references to
  it still resolve to a clear "this shelf was removed" for a token that can see it, and not to nothing.
- **[proposed]** Emptying is a reshelving list (`reshelve-approve`) and removing is its own action (`shelf-remove`). A book that is
  private stays private whichever way it leaves a shelf.

### Placement when more than one shelf fits

- **[agreed]** A candidate that fits two shelves about equally well goes on the shelf with the higher score. If the shelves differ
  in visibility, a tie goes to the private one, because hiding a book from a guest by mistake can be undone and exposing one cannot.
- **[proposed]** What counts as "about equally well" is a small margin between the scores, set as a rule. A book placed by a tie is
  marked so that reshelving proposals can show it first.

### Changing a shelf's scope

- **[agreed]** Widening a scope runs seeding again for the new part of the scope only, and never removes a book already held. It
  also offers a reshelving proposal for books on other shelves that now fit better.
- **[agreed]** Narrowing a scope removes nothing. It flags the books that no longer fit, so the owner can weed them if they choose.
- **[proposed]** Weeding is a supported, owner-governed action (it has its own permission level), and it is unlikely to be common for
  this owner. It stays supported because other owners of this tooling may use it often, and nothing in the design should assume
  that books are kept forever. The flag on a book that no longer fits is information and is not a removal.
- **[proposed]** A scope change is a rules change, so it needs a new approval like any other.

### Licenses and permission

- **[agreed]** Licenses never restrict by default. The tooling does not know the law where the owner lives and does not want to
  restrict, so it always assumes permission to use content unless a source says something specific to the contrary. An unknown
  license is accepted. Any terms a source states are recorded in the manifest for the owner's information. A shelf has a license
  rule only if the owner writes one, and the tooling then applies the owner's wording without judging it.
- **[proposed]** What counts as "specific to the contrary" is limited to a technical refusal by the source: a login, a paywall, a
  CAPTCHA or an HTTP refusal. The tooling skips such a source and never bypasses an access control. It does not read a license and
  decide for itself that use is forbidden.

### Candidates and filing

- **[proposed]** Candidates are proposed with a reason and a proposed shelf, and a new shelf is proposed when none fits. Candidates
  are proposed in the same three tiers as the brainstorm report, so the library grows in breadth. Candidates that meet the shelf's approved
  rules are filed automatically; a source the owner gives directly is filed on the owner's say-so, and is still subject to the shelf's allowed sources and to the
  crawler's address rules below; and a candidate that fits no shelf's rules waits for the owner.
- **[agreed]** A slow crawler brings in books continuously, under each shelf's approved rules. The owner reviews samples and
  summaries, not individual books.

### States, seeding and steady growth

- **[agreed]** A shelf has a fast mode to seed it, followed by a slow mode that keeps looking for more books.
- **[proposed]** A shelf's state is new, seeding, steady, paused or removed. Seeding runs a bounded burst: an AI turns the scope into
  queries across several sources, and the burst stops when its target is met,
  its candidates run out, or its time limit passes. It can be run again, for example after the scope is widened. Fast means
  breadth, with many sites fetched in parallel and one request at a time to any one site; the per-site speed is a setting, and
  raising it makes a block more likely. Steady mode uses a low daily budget and the human-like pace, and looks for work cited by
  books already held, newly published work in the shelf's areas, and new versions of held books. Seeding creates a large backlog
  of model work, which the priority queue absorbs.
- **[agreed]** The seed limit is set when a shelf is created, with a default of about 250 books.
- **[proposed]** When steady mode checks for new versions of held books, it also re-reads each source's retraction or withdrawal flag
  and its quality signals, and updates the caveat and the hints (`book.md`). A newly flagged book is listed in the library report.
- **[agreed]** A shelf is searchable as soon as it has anything in it, including while it is still being seeded. How the pipeline
  streams and how a result states its completeness is specified in `pipeline.md`.

### The crawler

- **[proposed]** The owner schedules the crawler with cron or launchd in small batches, and no daemon ships. It is a fixed fetcher
  with rules and not an agent, so untrusted text cannot add a new source domain, and what it can influence (work cited by held books, alternate copies) is
  bounded by the shelf's allowed sources and relevance rules. It needs a security review, rate limits and
  human-like pacing. Rights remain the owner's.
- **[agreed]** Good content matters more than being polite to sites. The crawler behaves like a human using a known browser: it
  sends a current, common browser's user-agent and ordinary request headers, and fetches slowly with irregular gaps and no parallel
  hammering of one site. Honouring `robots.txt` is a per-shelf setting, off by default at the owner's wish; the owner decides
  whether that is acceptable where they live.
- **[agreed]** The crawler errs toward getting information and does not assume restrictions on the owner's behalf. Being ethical and
  lawful in what is collected and how it is used is the owner's responsibility, and the crawler passes no judgment on copyright,
  license or terms (the owner's settings above decide those). This rule is only about access.
- **[agreed]** The crawler never defeats a site's access controls: it does not get past a login, a paywall or a CAPTCHA, and it
  does not rotate proxies or addresses to avoid a block or rate limit. On a refusal (a login wall, a CAPTCHA, an HTTP 403 or 429)
  it backs off, records the refusal, and looks for another openly available copy of the same work (a preprint, an institutional
  repository, an archive, or the author's own page). The work's identity (a DOI, an arXiv id, or title and authors) is what is
  matched, and the manifest records which source the copy came from. If no other copy is found, that is recorded in the seen list
  and the crawler moves on.
- **[proposed]** The crawler refuses private, loopback and link-local destinations and revalidates every redirect hop, whatever
  text supplied the URL (a citation, a DOI, an alternate copy, a direct submission).

### Reshelving

- **[agreed]** When a new shelf is created, the tooling looks at the books on the other shelves, including the holding shelf, to see
  whether any belong on the new one, and proposes those moves.
- **[proposed]** This pass runs before the new shelf is seeded, using the same relevance scoring as filing, on each book's card
  and not on its text, so it is cheap. A book is proposed for the new shelf only when it fits clearly better than its current
  shelf, by more than the tie margin. A book that fits both about equally stays where it is. Seeding then skips anything already
  held, so nothing is fetched twice.
- **[proposed]** After a shelf is added or its scope changes, the tooling proposes moves with a reason for each. The owner approves
  the list and the books move. A move never changes a book's id. Because the shelf is metadata, a move changes no bytes.
- **[proposed]** A proposal shows any change of visibility (shared to private or the reverse) before approval.

### The seen list

- **[agreed]** The seen list lives in the index root, once per library, keyed by the work's identity. Each entry records the shelf
  it was considered for, its score and its reason. A removed shelf's entries stay, so the crawler does not fetch those works again.

### Safeguards

- **[proposed]** Safeguards for automatic filing: a log of what was
  filed or rejected and why, a circuit breaker that pauses a shelf when too many items fail conversion, trip scan findings, score
  low on relevance or hit a runaway bound in a stage (themes or threads), and the existing on/off switches.
- **[proposed]** One safety floor: filing pauses everywhere when free space on the library's drive falls below a threshold the owner
  sets, so that an unattended crawl cannot fill the disk. It is not a limit on shelf size.

### Shared and private

- **[agreed]** A shelf can be marked shared or private. There are no roles or fine-grained access control. The owner said "public
  or private" and left the word to the assistant; "shared" is used because on a home network it means readable with a guest token
  and does not suggest exposure to the internet. "Public" stays available for a wider audience later. Private does not mean
  sensitive: a private shelf may hold public sources that the owner simply does not want shared with others. So a guest sees
  nothing of a private shelf, including its name, its scope statement and its book counts.
- **[agreed]** A shelf is shared by default; the owner can make it private.
- **[proposed]** Three kinds of token: a machine token and a project token (owner scope) see everything unless a project is narrowed
  on the host, and a guest token sees only shared shelves. A guest gets cards, themes, short excerpts and citation lines; full text
  and originals need an owner-scope token, and a guest never gets them. Auto-filed books are marked as such.
- **[proposed]** The non-leak rules apply to every token through its visible subset alone, not only to guests, so a project narrowed
  on the host is held to the same rule. A query runs against the token's visible subset alone, so counts, hints, "where to
  continue" advice, threads, errors, the answered notice, the library report and aliases never reveal a shelf the token cannot see;
  a thread with an invisible theme at either end is invisible to that token.

## Acceptance criteria

All of these are provisional until the spec is approved.

- Creating a shelf with a scope statement and rules, then approving the rules, lets candidates that meet them be filed without
  per-book approval, and a changed rule is not applied until it is approved again.
- With the approval action at `ask`, a shelf can be approved from a remote channel without a terminal, and the confirmation is
  refused if the rules file differs from the digest that was previewed.
- At `block`, approval is refused without a terminal; at `none`, it runs without one and is logged.
- An agent can propose a shelf, and a proposal has no effect until approved. At `block` and `ask` an agent cannot apply a rule on
  its own; at `none` the owner has chosen to let an agent approve.
- Seeding stops at the seed limit, when candidates run out, or at its time limit, and the shelf's status shows sample accepts and
  rejects near the threshold.
- A shelf can be searched while it is being seeded, and the result says how far seeding has got.
- The circuit breaker pauses a shelf on repeated conversion failures, scan findings or low relevance, and the pause is logged.
- Filing pauses everywhere when free space falls below the owner's floor, and resumes when it recovers.
- A source behind a login, paywall or CAPTCHA is skipped and recorded, and another openly available copy of the same work is tried;
  no access control is bypassed.
- A guest's query returns nothing from a private shelf: its name, scope, counts, and threads touching it are absent.
- The same holds for every token through its visible subset: a project narrowed on the host sees no count, hint, thread, error,
  answered notice, library report line or alias that reveals a shelf it cannot see, and a guest never receives full text or originals.
- The crawler refuses a private, loopback or link-local destination, including after a redirect, whatever text supplied the URL.
- Repeating one search from one project and token does not make a wanted topic, "not useful" feedback alone does not make a gap, and
  the answered check never reveals a hit on a shelf the reader cannot see.
- A name of a removed or renamed shelf, asked for by a token that cannot see it, gets the same answer as a name that never existed.
- Reshelving moves a book without changing its id or moving bytes, and the proposal shows any change of visibility.
- With one shelf at a high weight and another at the lowest, the high one receives the larger share of capacity and the low one
  still advances at no less than its minimum share. The oldest waiting item of the low shelf is eventually served, and a search
  ranks books from both on equal terms.
- A single gap search changes nothing in the crawler. The same gap repeated across separate searches and days becomes a wanted topic
  and adds a seed query, and the share of crawler capacity taken by demand never exceeds its cap.
- A wanted topic outside every shelf's scope produces a proposal and no fetch until the owner approves it. A query that contains a
  URL causes no fetch of that URL.
- A dismissed wanted topic is suppressed, a topic added by hand is acted on without repetition, and a topic whose stored queries now
  find results is marked answered.
- A shelf with two clearly separate groups of cards is reported as a split candidate, with sample books from each group. Two
  heavily overlapping shelves are reported as a merge candidate. Nothing moves until the owner approves a reshelving list.

## Open questions

These need a trial on a real shelf or real scale, so they are left open on purpose.

- The embedding model and the starting threshold for the first filter. The first batch's sample accepts and rejects tune the threshold.
- The size of the margin that counts as a tie. It is a setting, tuned on real shelves.
- The default fetch speed, daily budgets and the free-space floor. Start conservative, with the floor at 10 percent of the drive
  unless the owner sets another number.
- How sections of shelves would work if there are hundreds. Not worth designing before about fifty shelves.
- The thresholds for demand: the score floors that make a search a gap, how many separate searches and days make a wanted topic,
  and the default cap on the crawler's capacity that demand may take. These need real searches to tune.
- How a wanted topic is turned into queries for a shelf's sources, and how its representative description is chosen.

## Governing decisions and references

- Decisions: none recorded in this repository yet.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `book.md`, `theme.md`, `card.md`, `library.md` and
  `testing.md`. The pipeline is in `pipeline.md`; the models are in `models.md`, the reading module in `reading.md` and the weave in `weave.md`.
