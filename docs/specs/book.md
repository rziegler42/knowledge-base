# Book

Status: Draft

This specifies the book, the unit the library holds. It belongs to the design in `knowledge-base.md`, which gives the intent, the
vocabulary and the other parts. **Nothing here is final.** The spec stays `Draft` until the owner approves it, and any statement
can be reopened. Each statement carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

## Scope

A book is a container for one work. This spec covers what a book is, how it is identified, how it is laid out, its versions, the
items inside it, how sources are converted, the metadata and model output it carries, how it moves through the pipeline, its
lifecycle, and how it is written safely. It does not cover shelves, cards as search entries, the weave, or the library as a whole;
they have their own specs.

## Non-goals

- **[agreed]** Browsing books by hand. The focus is an agent or skill finding relevant material through the reading interface, so
  folder names need not be readable.
- **[agreed]** Editing a primary source. A primary source is never edited.
- **[agreed]** A notes feature. A book may later hold other kinds of item, but none is designed here.
- **[agreed]** Per-claim verification tags.
- **[agreed]** Judging licenses or the law, or restricting a book on license grounds. Permission is assumed unless a source
  specifically says otherwise, and the terms a source states are recorded.

## Assumptions and constraints

- The library is untracked, local data. A tracked document cites a book by source URL, retrieval date and content hash, never by a
  path into the library.
- The workbench's path rules refuse symlinks, and a database misbehaves on a network share, so a book's layout uses no links and
  its manifest files are plain files.
- Files in a book are untrusted data and are never executed.
- **[agreed]** A conversion tool, like any other dependency, needs the owner's explicit approval once per tool and not once per use.
  After approval the pipeline runs the tool on any book without asking. A tool that parses untrusted files is raised for a security
  review once, when it is approved.
- **[agreed]** Capture is by default, because the owner is not worried about the cost of storage or of processing with a local
  model. A pointer-only book is for what cannot sensibly be copied, such as repositories, datasets and large media.

## Behavior

### What a book is

- **[agreed]** A book is a container for one work. It has a stable id independent of its shelf, common details at its root, and one
  or more versions. Each version has one primary source and supporting items derived from it.
- **[agreed]** The kinds of source are an open set: PDFs, web pages, office documents, text and Markdown, papers, repositories,
  datasets and more. A source with no conversion is still filed, with its original, its manifest and a card built from metadata.
- **[proposed]** A book about two works is two books.

### Kinds and their profiles

- **[proposed]** What differs between kinds of source is gathered in one **kind profile** per kind, not spread through this spec.
  A profile names: the identity keys the kind has, how a new version is recognised (a label, a commit, a text comparison, or
  appended content), the capture shape (one file, files with a primary, or a collection of parts), the conversion tools in
  fallback order, the kind of locator its anchors use, how often a steady-mode check looks again and when it stops, and which
  source terms are recorded. Adding a kind of content means adding a profile and a converter, and does not change the book.
- **[proposed]** The first profiles are the arXiv paper and the PDF. A web article follows. A repository, a documentation site, a
  video or podcast and a discussion thread are named so the layout leaves room for them, and are not built first.
- **[proposed]** A book of a kind with no profile is still filed as a plain captured or pointer book (see "Items"), and a profile
  can be added later and applied to it without changing its id.
- **[proposed]** A web page is one of at least four shapes, and its profile says which: a **document** (an article or a page of
  documentation), a **thread** (comments by many authors, each with its own id), a **listing** (an index page of links or headlines,
  which is filed as a pointer and not converted as a document) and a **script-built page** (the visible text is made by scripts,
  so the raw capture is complete and the text is empty or small, and it is filed as partial). In a test of ten pages on
  2026-11-04, six were documents, one a thread, one a listing, one script-built and one a repository page (evidence note 17 in `knowledge-base.md`).
- **[proposed]** The manifest of a web page requires only what every page had: the address asked for, the final address after
  redirects, the retrieval date, the response headers kept, and the hash of the raw bytes. A title was present on every page. An
  author, a published date, a language and a canonical address were present on some, and are optional fields.

### Identity

- **[proposed]** A book's id is unique and time-sortable (a ULID), generated when the book is filed, namespaced by the library id,
  and never reused.
- **[proposed]** Identity keys are separate from the id: a DOI, an arXiv id, a canonical URL, a repository URL, the text
  fingerprint, and the raw hashes of the files. They are kept in the book's root file and indexed in the index root for fast
  duplicate checks.
- **[agreed]** The tooling does not download a source the library already holds. Duplicate checks run on identity before any
  download and on content hash after a fetch.
- **[idea]** The identity keys also include an ISBN and an edition for a book, and a plain **owner-supplied origin** note (what it
  is, where the owner got it, the date) with its hash for a source that has no URL or DOI. A tracked document cites such a book by
  title, hash and retrieval date, since there is no source URL to give. Whether a new edition is a new version or a new book is
  decided per kind profile, and a translation is a separate book with a "same work" note.
- **[proposed]** Near-duplicates, such as one paper from two sites, are found by comparing text fingerprints and cards.
- **[agreed]** A preprint and the published paper are one book with two versions when the tooling can link them, for example by an
  explicit link in the metadata such as arXiv's published-version DOI, or by a very close match of title and authors. Otherwise
  they are two books with a "same work" note, which the owner can merge.
- **[proposed]** A "same work" note shown in a card or a result is redacted for a token that cannot see the other book: the link,
  and the fact that it exists, are left out.

### Layout

- **[agreed]** At the root of a book are the details common to all of its versions. Each version has its own folder, holding the
  original work and its conversions.
- **[proposed]** The manifest of a book is its root file together with its version files. "Manifest" always means that pair, and
  "root file" or "version file" means one of them.
- **[agreed]** Books are stored flat and sharded by id, and a book's shelf is metadata, not a folder. A reshelve is therefore a small
  edit and never moves bytes.
- **[proposed]** A version folder holds `version` details, an `original/` folder (one or more files, one marked primary) and a
  `derived/` folder with conversions grouped by the tool that made them. For a pointer-only version it holds the pointer and a small
  captured snapshot in place of `original/`.
- **[proposed]** Which version is current is a field in the root file, not a link.
- **[proposed]** Nothing stored in the library holds an absolute path to a root. Everything inside a book, and everything that
  refers to it, uses its id and paths relative to a root, so moving a root needs only a change of config.

### Root details

- **[proposed]** The root file holds the book id and library id, the title, authors, year, kind (for example preprint, thesis, web
  page), language, identity keys, the home shelf, the date added, whether it was auto-filed, a state (active, weeded, removed, or duplicate for a candidate that turned out to be another book),
  the current version, and any "same work" links.

### Versions

- **[agreed]** When the same source changes upstream, the new content is a new version of the same book, the new primary becomes
  current, and earlier versions are kept unchanged.
- **[agreed]** Only a meaningful change in the text makes a new version. A change in bytes alone does not.
- **[proposed]** Two cases. A source that labels its own versions (arXiv v1 and v2, a git commit, a DOI version) makes a new version
  whenever the label is new. A source with no versions, mainly a web page, has its text extracted and normalised (menus, page
  numbers, headers and footers, dates and whitespace removed) and compared with the current version: below a similarity threshold
  it is a sighting, and above it a new version. The threshold is a shelf setting with a sensible default.
- **[proposed]** A sighting adds a line to the book's event log (seen again on this date, bytes differ, same text) and records the
  new file's hash as an alternate hash of the existing version, so a project that cited the other file by hash still resolves to
  the right version. The new bytes are not kept.
- **[proposed]** A pointer re-pins only on request or when a shelf's steady-mode check runs, so a repository that changes daily does
  not produce a version a day.
- **[proposed]** New upstream versions of a source are looked for by steady-mode crawling of the shelf, and also when the owner
  or an agent asks for a check of one book.
- **[proposed]** A version can record alternate sources of the same content, for example a preprint and a publisher copy.
- **[idea]** Search covers only the current version by default, with older versions available on request.
- **[idea]** A **growing source**, such as a discussion thread, a feed or a changelog, only adds content. Appended text is not a
  replacement, so a similarity threshold would either lose new replies as sightings or make a version for each reply. For such a
  kind a version is a dated snapshot, a re-check adds the new parts to the current snapshot or starts a new one by the profile's
  rule, and the book gains a state (open, stable or closed) so the steady-mode check stops looking at a thread that has gone quiet.
- **[idea]** A correction to an article can be too small to cross the similarity threshold. The profile for web pages can name
  words that mark an update (for example "updated" or "correction") so that a change near them is not discarded as a sighting.

### Items

- **[agreed]** The primary source is either captured (a copy lives in the book) or a pointer (an address plus the exact version
  meant). "Reference" is avoided as a word for a pointer because the workbench uses it for `docs/references/`.
- **[agreed]** Pointers are allowed for things too large or live to copy.
- **[proposed]** A pointer records the address, the exact pin (a commit, date or etag), the kind, and when it was last checked and
  what it returned. A small captured snapshot, such as a README, sits beside it so the book can be searched.
- **[proposed]** Promoting a pointer to a captured copy makes a new version whose primary is the snapshot, and the pointer version
  stays. The book's id does not change.
- **[proposed]** Derived items are never the only copy of anything. Each records the tool and version that made it, and it can be
  deleted and rebuilt.
- **[proposed]** A version's content is a list of **parts**. A paper has one part, which is its primary. A source with several
  files has a primary and supporting parts. A collection with no single primary, such as a repository, a documentation site or a
  discussion thread, has many parts and no primary. Each part records its own path, hash, locator kind and size, so a part can be
  named, read, re-checked and cited alone. A part is not a book: the book stays one work with one card.
- **[idea]** A rule that keeps the derived-items rule honest for media: a transcript made from a source's own captions is a
  captured item of the source, and a transcript made by the library from captured audio is derived from that audio. A transcript
  made from audio that was not captured would be the only copy, so the audio is captured unless the book is pointer-only.
- **[idea]** For a web page the capture holds the raw response, the readable text that was extracted from it, how it was rendered
  (plain fetch or a rendered page), and optionally the address of an archived copy. A page that only renders with scripts is
  recorded as such, and is not retried every time as if it had failed.

### Conversion and structure

- **[agreed]** Conversion aims at better over simple: where the format allows, an outline (headings with anchors) and sections
  with stable anchors such as page numbers and section headings, so an excerpt can be cited precisely.
- **[proposed]** An anchor is a **typed locator**, not only a page or a heading. The locator kinds are a page, a section, a line
  range at a commit, a time range in media, and a comment or post id. Each part names its locator kind in its kind profile, and a
  stored anchor records the kind with the value, so a reading, a theme or a citation can say where it came from in any kind of
  source. A reader that meets a locator kind it does not know shows the raw value and does not guess.
- **[proposed]** Structure is best-effort and labelled. Each conversion records its structure quality as full (outline and
  sections), partial (some headings, pages kept) or flat (text with page markers only). A search or an excerpt always works.
- **[proposed]** An approval names the tool and its exact version, and a new version of the tool needs a new approval, so an update
  cannot quietly change what parses the owner's files. The approved tools, the formats each handles and their fallback order are
  owner-only config, changed only by a governed owner action at `block`; an agent cannot change them. Approved tools run within the existing
  limits: a time limit, a size limit, no network, and untrusted output.
- **[proposed]** A conversion tool can be approved only if it runs confined: as a separate low-privilege user or in an equivalent
  sandbox, with a filesystem allowlist limited to its input and output folders, and with no network. A tool that cannot be
  confined this way cannot be approved.
- **[proposed]** An archive is unpacked within limits: a maximum total size, a maximum nesting depth, a maximum decompression
  ratio, and no entry that resolves outside the output folder (no path traversal, no absolute paths, no links). An archive that
  exceeds a limit fails the conversion stage with the reason, and nothing is written outside the output folder.
- **[proposed]** Several conversions of a version may exist, grouped by tool, and one is marked as the one to use. A second tool runs
  when the first gives a flat result.
- **[proposed]** A locator names the conversion it was made against, as the tool, its version and the generation, because the same
  page converted by two tools gives different blocks. In a test, a locator made as a heading path, a paragraph
  number and an excerpt hash was found again by the same tool on the same raw capture on all ten pages, and by a second tool on none
  of the four pages tried. A locator is therefore only valid against its conversion, and after a change of conversion the excerpt
  hash is what finds the passage again, by text.
- **[proposed]** For a web page no single extractor is right, so two run and their sizes are compared. When the article extractor
  returns far less text than the plain extractor (in the test, 1.5k against 2.6k characters for a repository page and 3.7k against
  28k for a thread), the book is marked partial and the owner can see both. The threshold is not settled and rests on ten pages.
  A page with no paragraph or heading tags is one flat block, and its only locator is an offset in the converted text.
- **[proposed]** The tool is chosen by format: a tool built for scientific papers for PDFs of papers (recovering sections, authors
  and references), the native headings for office files and Markdown, an article extractor for web pages. The local model may
  repair or fill in an outline, with its output marked as model-made.
- **[proposed]** The reference list (bibliography) of a work is a derived item. Each entry is marked resolved to a held book,
  unresolved or ambiguous, and resolution is re-run as books arrive. Unresolved entries are the "cited but missing" seeds for the
  crawler. Resolved entries are hard links between books. A resolved citation shown in a card or a result is redacted for a token that
  cannot see the cited book: the entry then shows as unresolved, with no id, title or shelf of the target.
- **[idea]** Figures and tables are items of their own, with captions and a short text description so they can be found without
  reading around them. Images could later get descriptions from a model with vision.
- **[proposed]** The untrusted marker is part of every converted text, so an excerpt carries it whoever returns it.
- **[proposed]** Reading is layered, cheapest first, and each response is bounded and says where the next piece is: the card, an
  outline, a section by anchor, the full text.

### Metadata about the work

- **[proposed]** Title, authors, year, venue and kind come from the source's own records first (arXiv, DOI metadata, HTML or PDF
  metadata). A model fills only gaps, and marks what it filled.
- **[proposed]** Where the source gives them, the metadata also holds subject classifications (for example arXiv categories) and
  author identifiers (for example ORCID). Subject codes are a cheap measure of how far apart two fields are, and shared authors are
  a cheap link.
- **[agreed]** The library flags a work that has been retracted or withdrawn, as a caveat. The flag comes from the source's own
  record (for example an arXiv withdrawal or the retraction flag in OpenAlex or Crossref), not from a model's judgment. A flagged work
  stays in the library and stays findable, because it is still a possible lead, but its card and every result carry the caveat. The
  status is checked again when the steady-mode crawler checks for new versions.
- **[agreed]** Quality signals are hints and never filters. Where the source provides them, the metadata also holds the citation count,
  the venue and whether the work is peer reviewed, with the date they were read. They are shown with a result so the agent can weigh
  it. They never exclude a work, and by default they do not change its rank, because an obscure, little-cited work may hold the
  novel idea.
- **[agreed]** The tooling records whatever classification a source provides and invents none. Open schemes are preferred over
  proprietary ones: for example arXiv categories, MSC codes, OpenAlex topics and the Library of Congress Classification over
  Dewey, whose schedules may carry rights the owner does not want to depend on. Each code is stored with the name of its scheme, so
  codes from different schemes are never compared as if they were one.

### Model output

- **[proposed]** The costly model output of a book (its cards, neutral descriptions and themes) is kept in the book's own folder,
  with the model, prompt version and date, so a book is self-contained and can be moved or lent with its card attached.
- **[proposed]** Model output is kept in generations and never overwritten. A better prompt or model adds a generation; the index
  uses one active generation; an earlier generation can be restored.
- **[proposed]** A theme records the book, the version, the part, the conversion it came from, its typed locator and a hash of its
  excerpt, so it can be re-anchored if a reconversion shifts anchors. A theme from a flat conversion counts for less.
- **[proposed]** Duplicate and "same work" marks are available to whatever reads the book, so that near-copies do not produce
  strong, useless "alike" threads.
### Pipeline state

- **[proposed]** A version records the stages it has passed: found, fetched, scanned, converted, carded, indexed, themed and
  threaded. Scanned is a stage of its own, between fetched and converted. Each stage is pending, done, failed with a reason, or
  skipped, with a timestamp, and is written atomically in the version file. Keyword indexing follows converted, and vector indexing
  follows carded (`pipeline.md`). One writer at a time handles a book.
- **[proposed]** A failed stage is retried with backoff a set number of times. After that it is parked: it stays failed, is set
  aside with its reason, and shows in the library report. "Parked" means only that. A restart resumes from the recorded stages.
- **[proposed]** Objective scan findings (embedded scripts, encryption, hidden text) become caveats and never stop filing.

### Lifecycle

- **[proposed]** A book is active, then weeded (the original is dropped, and the card, pointer and recorded hashes are kept), then
  removed (a tombstone only). Weeding and removal are a governed owner action (`book-weed`, `shelf.md`) and list what they will delete, with a note on any book that has been used in a project (`reading.md`, "Used notes"). Nothing is weeded or removed
  automatically.
- **[proposed]** The tombstone, and the seen list for candidates never filed, keep the crawler from fetching the same source again.
- **[proposed]** Reshelving edits the home shelf and logs the change. A move never changes a book's id.
- **[proposed]** Each book has an append-only event log (filed, version added, sighting, reshelved, card made, weeded). It shows how
  an auto-filed book arrived.

### Safe writing

- **[proposed]** A book is built in an incoming area on the same volume, its hashes are verified, and it is renamed into place, so
  there is never a half-filed book. Manifest files are written to a temporary file and renamed.
- **[proposed]** A filed book has an immutable payload and small mutable metadata. The payload is the originals, the converted
  text, the other hashed files and the written generations of model output. It is marked read-only after filing and is never
  changed in place, except by weeding or removal. The metadata is the root file, the version files, the stage state, the event
  log, the alternate hashes and the current-version field, and it changes only by an atomic rewrite.
- **[proposed]** The integrity check (`library.md`) verifies the hash of every payload file against the manifest. The metadata is
  not hash-frozen; the integrity check verifies its format and its consistency (the format number, that every file the manifest
  names exists, and that the current version names a version that exists).
- **[proposed]** Every file carries a format number. Older formats are read, and migration is a governed owner action with a preview (`library.md`), never silent.

## Acceptance criteria

All of these are provisional until the spec is approved.

- Filing a source produces a book with a root file, a version folder, an original with its hash, a conversion with a structure
  quality, and a card, and the book is searchable.
- A source the library already holds is not downloaded again. The same text with different bytes is recorded as a sighting and
  adds an alternate hash, and a meaningful text change or a new source version label makes a new version while the earlier
  version stays byte-for-byte unchanged.
- A preprint and its published paper become one book when linkable, and two books with a "same work" note when not.
- Interrupting filing at any point leaves no half-filed book, and a restart resumes from the recorded stages.
- Altering a payload file in a book makes the integrity check report it, while a legitimate change of the metadata (a stage state,
  an event, the current version) does not, and a malformed or inconsistent metadata file is reported as such.
- A resolved citation or "same work" note in a card or result is redacted for a token that cannot see its target.
- A conversion tool that cannot run confined (separate low-privilege user or sandbox, input and output folders only, no network)
  is refused approval, and an archive over a size, nesting or ratio limit, or with a path-traversal entry, fails the stage and
  writes nothing outside the output folder.
- Moving a root and changing the config leaves every book and the index working. A reshelve moves no bytes.
- A pointer is recorded with its pin, and promoting it adds a captured version without changing the id.
- A weeded book keeps its card, pointer and hashes, and a removed book is not fetched again.
- A reconversion that shifts anchors leaves the book's themes re-anchorable by their excerpt hash.
- A reader that meets an older format number reads it, and nothing is migrated without the owner's command.

## Open questions

- The similarity threshold and normalisation rules for sources without version labels.
- Which conversion tools to use, and the exact schema of the root and version files, which the builder fixes.
- The locking mechanism for one writer per book, and how long event logs are kept.
- How a figure or table description is made, if at all.
- How "same work" links across different DOIs are proposed to the owner for merging.
- **Granularity of a large collection.** One book has one card, which is too coarse for a repository or a documentation site. Part
  level cards may be needed, and whether they are is open until a collection kind is built.
- **What the search sees of a pointer-only book.** A repository book has a README snapshot, so its code and pages cannot be
  searched. Whether to capture a bounded text snapshot of selected paths at the pin is open.
- **Whether a kind profile is data or code.** A profile could be a declared table that tools read, or a small program per kind.
  The first two kinds will show which.

## Governing decisions and references

- Decisions: none recorded in this repository yet. This spec follows the workbench's rules cited in `knowledge-base.md`.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `shelf.md`, `card.md`, `theme.md`, `library.md` and
  `testing.md`. The pipeline is in `pipeline.md`; the models are in `models.md`, the reading module in `reading.md` and the weave in `weave.md`.
