# Search the themes by meaning

Status: Proposed
Created: 2026-11-12
Candidate: theme-weave#theme-vectors
Specs: theme, models

## Goal

Make the themes findable. The library holds themes for its books (1,913 in 175 books on the owner's local library on 2026-11-12, which is not in this repository), each with a summary in the book's own words and a description of five parts in words of no field, and nothing yet lets an agent ask for them: `theme-weave#theme-unit` made them, and this
candidate is the next on the roadmap. When this plan is done, the texts of the themes are turned into vectors by the embedding model the owner's config already names for the cards, kept in a file of their own in the index root that can be rebuilt from the book folders alone, and `python3 -m kb theme-search` takes a sentence or two about a problem and returns themes ranked by how
close one of their texts is, each with its citation, its mark of stated or inferred, its flags and the untrusted-text markers; and the owner has built the vectors over the library, seen what eight searches return, and decided what comes next.

## Scope

- A file of the themes' vectors and of what a result shows (`theme-vectors.sqlite` in the index root), built by `python3 -m kb theme-vectors` from the newest valid card and the newest valid generation of themes of each active book that has both; the vectors of unchanged texts are kept, and a build of a changed library makes only the vectors that changed.
- A search by meaning over that file, `python3 -m kb theme-search`, which reads the file and sends only the query to the embedding model.
- The statements in the theme and models specs, and the engine README.
- A live build over the library and eight searches, run on the owner's word, with the results shown to the owner.

## Non-goals

- Links between themes, the walk, a judgement of novelty, and a trial against an ordinary search (the roadmap's `theme-links`, `theme-walk` and `extrapolation-trial`).
- A keyword search of themes, a change to what a theme holds, to the themes made or to their flags, or to the config (the agent does not write the owner's config).
- A change to the card vectors (`vectors.py`) or to `card-search`.
- Search across cards and themes in one list, and an interface for the workbench package.

## Assumptions and constraints

- **My calls, not yet the owner's.** (The owner said to skip the questions and draft on the defaults; these are the defaults.)
  1. **What is embedded: everything, and a test decides what to drop.** `docs/specs/theme.md` agrees that both descriptions are embedded and that an embedding is dropped only if a test shows that doing so loses nothing for finding novel concepts. So for each theme: its summary (the source's own vocabulary), its whole neutral description as one text (the parts that have text, in the order problem, method, needs, provides, limits, each led by its name),
     and each of the five parts as a text of its own: up to seven texts and seven vectors for a theme. A part with no text has no text of its own, and a theme with no part has no whole description. A part marked `inferred` is embedded and keeps its mark. (For the cards the needs and the limits were left out because a sample found most of their sentences not in the book; that has not been measured for themes, so they are embedded here, and Increment C looks at whether the searches change without them.)
  2. **One result for each theme.** A theme is ranked by the cosine between the query and the closest of its vectors, larger being closer. The result says which text matched (the summary, the whole description or a part), shows that text as its excerpt, and gives the mark of that part (`stated` or `inferred`; the summary and the whole description have none).
  3. **The embedding model is the one the config names for `card-embed`**, used for the themes too. That keeps the owner's config as it is. A separate kind of work for themes would need the owner to set it and is left for later if wanted. The vectors are marked with the model the bridge reported and with the hash of the document prefix. **A build and a search treat a file that is not usable differently, as for cards:** a build does not reuse a file that this engine did not make, that is damaged or of another format, or that was made for another model, dimension or document prefix: it makes every vector, and puts the new file in place of the old one only when it has been made whole (the count says the old file was `replaced`);
     a search refuses such a file, and says to run the build.
  4. **One file, in the index root, made from the cards and the themes alone.** The build lists the active books from the store's book records (their ids, versions and state, and nothing else of the store), and for each reads its newest valid card (`card.read`) and its newest valid generation of themes (`theme.read`); no book text, conversion or manifest is read. A book with no card that can be read, or with no themes, is left out and counted. `theme-vectors.sqlite` holds a row for each theme
     with what a result shows: the theme's id, the book id and version, the card's title for the book, the theme's title, type, summary, the five parts with their marks, confidence, flags, **the whole anchor** (its `start` and `end` locators, its `path` and its `excerpt_sha256`, kept as the theme holds it and checked against the form of an anchor when the file is read), the citation line, the generation of the themes and of the card,
     and the hash of each embedded text; and a row for each vector. A result returns the theme id, the book, the whole anchor, the summary and the citation line, as `docs/specs/theme.md` ("Search and reading") says. A search reads only this file and the model, so it does not touch the bulk drive. It is derived, can be thrown away, and is written beside the old file and renamed into place under a lock, as the card files are.
  5. **The file shows the themes as of its build.** A generation of themes filed later (a remade book, a re-flag) is not seen by a search until `theme-vectors` is run again, as the catalog of cards is not updated as cards are made. A result carries the generation it was built from, and the file says when it was built.
  6. **The build is rebuildable and cheap.** Up to seven texts for each of 1,913 themes is up to 13,000 texts; the card vectors took 6.3 seconds for 230, so a full build is under ten minutes. A text whose hash, model and prefix are unchanged keeps its vector. The build is `again`-able (every vector made again).
  7. **The citation line is built as the card catalog builds it** (`catalog.citation_of`, the form a read gives, from the source facts the card holds), with the theme's anchor path added, at build time, and is stored. **It also shows the language, as the theme spec agrees** ("the citation shows the language"): `language: not recorded`, because neither a card nor a theme records the language of its source today (an HTTP capture keeps a `Content-Language` header, but a card keeps no such field).
     That is a known gap, said in the result and in the spec, and recording the language in the card is deferred. Everything a result shows is untrusted text from a book or a model: it is cleaned, shown between the untrusted-text markers and marked untrusted, as a card search does.
  8. **Dependency.** `theme-unit` is built: the plans `2026-11-11-make-the-theme-the-unit-of-the-weave`, `2026-11-11-run-the-theme-extraction-over-the-library` and the ones after it are committed, though their Status lines still say `Proposed` (that line is informational, and changing it is the owner's). The roadmap's trigger for `theme-vectors` is that the owner asks for a plan, which the owner has.
- Embedding texts go in the clear to the server the config names for `card-embed`, as for cards: the texts of the themes (descriptions model-written about the owner's books) in a build, and the query in a search.
- A defect found in the live run stops it; the plan is not widened to get past it.

## Completion criteria

1. The build makes the file from the newest valid card and the newest valid generation of themes of every active book that has both, and from nothing else of the books: the right rows and vectors (up to seven texts for a theme, none for a part with no text), vectors kept for unchanged texts and made for changed ones, a book with no card or no themes, and a theme or a card that cannot be read, left out and counted; a file that is not this engine's, is damaged, or is for another model, dimension or prefix, is not reused and is replaced only by a file made whole. Tests show each, with a fake embedding bridge.
2. The search ranks themes by the closest vector, one result for each theme, with the theme id, the book, the whole anchor, the summary, the matched text, its mark, the citation (which shows the language, or that it is not recorded), the flags, the generation and the untrusted-text markers; it refuses a missing or foreign file, a query that is not text, a limit out of range and a reply from another model than the one that made the vectors; it reads the file read-only, sends only the query, and writes nothing. Tests show each.
3. The commands `theme-vectors` and `theme-search` exist, take no model, server or address, and print what the tests say. The theme and models specs and the engine README say what is built.
4. The vectors have been built over the library on the owner's word, and eight searches have been run and shown to the owner with the top results and the counts (texts sent, vectors, stale, without vector, time); the report is outside the repository with its sha256 and the Result holds the numbers.
5. The owner has the Result and has decided what comes next.

## Increments

### Increment A — The file of the vectors of the themes and its build

**Outcome:** `themevectors.build` makes `theme-vectors.sqlite` from the themes of the library with a fake or a real embedding bridge.
**Dependencies:** none.
**Affected areas:** a new `engine/kb/themevectors.py` (reusing `vectors.pack`, `unpack`, `sha256`, `prefix_hash`, `connect`-style checks where they fit, and `models.embed`); `engine/tests/test_themevectors.py`; reads `theme.py`, `card.py` and `catalog.py` (`citation_of`), and the store only for the list of active books.
**Steps:**
1. Write the tests first and see them fail, with a fake `models.embed` and a store of books with cards and themes (as the tests of `themerun` build them): seven texts for a theme with every part, and none for a part with no text (the whole description is left out too when no part has text); `needs` and `limits` are embedded; the newest valid generation of themes of a book is the one built (an older or a damaged one is not);
   a book that is not active, has no card that can be read or has no themes is left out and counted, and so is a theme or a card that cannot be read; no file of the book other than its card and its themes is opened (shown by a store whose book text and manifest raise if opened); the rows hold the theme's id, the book id and version, the card's title, the theme's title, type, summary, the five parts with their marks, confidence, flags, the whole anchor (start, end, path and excerpt hash), the citation line with the language line, and the generations; a row whose anchor is not in the form of an anchor is refused when the file is read;
   a second build keeps every vector and sends no text; a changed text, a changed model, dimension or prefix, and `again` make the vectors again; a build over a file that another program made, that is damaged, of another format, or for another model, dimension or prefix makes every vector and replaces it only when whole (and says `replaced`), while a build that fails leaves the old file as it was; the file is written beside the old one and renamed under a lock; a vector that is not the right length, not finite or all zeros is refused;
   only the texts of the embedded fields are sent (no title, no book text); the file is private to the user.
2. Write `themevectors.build`; run the tests; break the code on purpose, one break at a time, and restore each.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themevectors engine.tests.test_vectors engine.tests.test_theme` and `wb run code-work check`. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-search-the-themes-by-meaning#A`.

### Increment B — The search and the commands

**Outcome:** `python3 -m kb theme-vectors` builds and `python3 -m kb theme-search` searches, with the results in the form of criterion 2.
**Dependencies:** A.
**Affected areas:** `engine/kb/themevectors.py` (`search`, `coverage`); `engine/kb/__main__.py` (the two commands); `engine/tests/test_themevectors.py`; `docs/specs/theme.md`, `docs/specs/models.md`; the engine README.
**Steps:**
1. Write the tests first and see them fail: the ranking by the closest of a theme's vectors, one result for each theme, the theme id, the book and the whole anchor in the result, the matched text and its mark, the order on a tie, the limit and its range, the query cleaned and bounded as the card search does; the result's fields and the untrusted markers; a missing file, a foreign file, a file for another model or dimension, a row that is not what the engine writes, a reply for the query from another model, a query that is not text: each refused before or after the query is sent as the card search refuses them;
   the search reads the file read-only and writes nothing; only the query is sent; the parser of the two commands takes no model, server or address; `theme-vectors` prints the counts (themes read, left out, vectors kept and made, texts sent); the exit codes.
2. Write the search and the commands; update the specs and the README (what is embedded, what a result shows, the file, that it shows the themes as of the build, and what is sent); run the tests; break the code on purpose, one break at a time, and restore each. Run `python3 -m kb --help` and the help of the two commands.
**Verification:** `python3 -W error::ResourceWarning -m unittest engine.tests.test_themevectors engine.tests.test_vectors engine.tests.test_theme engine.tests.test_catalog` and `wb run code-work check`, and the module that tests the command line, found by search. No live call.
**Evidence:** the one local commit, with the trailer `Plan: 2026-11-12-search-the-themes-by-meaning#B`.

### Increment C — Build over the library and look at what it returns

**Outcome:** the vectors of the library's themes exist and the owner has seen what eight searches return.
**Dependencies:** B. The owner's word for the live build, given after the plan of the build is shown.
**Affected areas:** the index root (the file of vectors); nothing tracked except this plan's Result; the report is outside the repository.
**Steps:**
1. Show the owner the plan of the build: the themes and books it will read, the number of texts, the model the config names for `card-embed`, the estimate, and what is sent (the texts of the themes' summaries, whole descriptions and parts, in the clear to the embedding server) and that the book folders are not written. Wait for the owner's "run it".
2. Run `theme-vectors`; read its counts; run it again to show that it keeps every vector and sends nothing.
3. Run eight searches, the same eight sentences the card search was looked at with (the Result of `2026-11-09-search-the-neutral-descriptions-by-meaning`), and keep each query, its top five results (book, theme title, score, matched text and its mark) and the counts; write the report outside the repository, mode 600, with its sha256.
4. Write the Result: the numbers, the results shown, a comparison of the books that the theme search puts first with those that the card search put first (from that plan's Result), whether the searches change when the needs, the limits and the whole description are left out (worked out from the same vectors, with no further call), my reading marked as mine, and what I would do next. The owner's reading is asked for and recorded.
**Verification:** the counts of the build, the second build, the eight searches and the report.
**Evidence:** the Result of this plan, committed with the trailer `Plan: 2026-11-12-search-the-themes-by-meaning#C`.

## Verification for the plan as a whole

Each increment's recorded verification still stands unless a later increment changed its inputs. Increment B changes only the new module and the command line, so the tests of the card vectors are run in A and B to show that the shared functions behave as they did. The live work is Increment C.

## Risks and sensitive actions

- **A live build** (Increment C) sends up to 13,000 short texts (model-written descriptions of the owner's books) in the clear to the embedding server the config names for `card-embed`, and the eight queries. The owner's word is asked after the plan of the build is shown.
- **The file holds model-written text about the books** (summaries and descriptions) and untrusted text from a book (titles, anchors' paths); it is private to the user, derived, and shown only between the untrusted-text markers.
- **Untrusted input and a new store.** The file is written and read by a new module that parses model vectors and reads SQLite. The plan reuses the card vectors' checks (a foreign or damaged file is refused, a vector is checked when made and when read). **Security review checkpoint:** this touches the filesystem, untrusted input, parsing and a network boundary (the embedding bridge), so I ask the owner once, before Increment A, whether to run `security-review` on it; the card vectors had one (their Increment D-A) and it found things. A review runs only if the owner asks.
- **The result ranking is a measure of closeness of text, not of novelty or of use.** Nothing here says a found theme is worth pursuing; that is the agent's and the owner's.
- **The file shows the themes as of its build** (assumption 5), so a theme remade later is not found until the build is run again.

## Review record

- **Reviewer:** the review engine (`plan-d2ce329be287dd8e`), models `gpt-5.6-terra` (rounds 1 and 2) and `gpt-6.1-sol` (round 3). Rounds used: 3 of a bound of 3; the third converged with no meaningful finding.
- **Applied (5):** everything is embedded (the summary, the whole neutral description and all five parts), because the agreed rule is to drop an embedding only on a test, and Increment C looks at what dropping some would change (R1-F1); the citation carries a language line that says `not recorded`, because neither a card nor a theme records the language, with recording it deferred (R1-F2);
  the build reads only the list of active books and each book's card and themes, with a test that nothing else of a book is opened (R1-F3); a build and a search treat an unusable or mismatched file differently, stated and tested (R1-F4); the file keeps the theme id, the book and version and the whole anchor with its excerpt hash, and a result returns them (R2-F1).
- **Rejected:** none.
- **Left for the owner:** whether to ask for a security review (recommended in the risks; not yet asked), and whether to approve the plan. The live build (Increment C) waits for the owner's word after the plan of the build is shown.

## Deferred work

- Links between themes, the walk, a keyword search of themes, and one list across cards and themes (the other candidates of the roadmap).
- A separate embedding model or kind of work for themes (`theme-embed`), if the owner wants one.
- Dropping the embeddings of the needs and limits, or of the whole description, if the searches of Increment C and a test show that doing so loses nothing (the owner's agreed rule).
- Recording the language of a source in the card, so that the citation of a theme can show it.
- A way to notice a newer generation of themes without a build, and the workbench package's use of the search.
- The other open items of the earlier plans: the check model's leniency, the prompt's sentence about a span being thrown away, and making the PDFs of the library again.

## Result

### Increment A (the file of the vectors of the themes and its build; committed)

- **Done.** New `engine/kb/themevectors.py`: `build(store, cfg, again=False)` makes `theme-vectors.sqlite` in the index root from the list of active books (their state and current version), and for each book its newest card (`card.read`) and its newest valid generation of themes (`theme.read`); no book text, conversion or manifest is opened. For each theme up to seven texts are embedded:
  its summary, its whole description (the parts that have text, in order, each led by its name) and each of the five parts (needs and limits included, as the plan decided). A vector is kept by the sha256 of its text under the same model, dimension and document prefix; a text held by several themes is sent once. The file holds a row for each theme with what a result shows (the theme as filed, whole anchor included, the card's title,
  the citation line, both generations, the hash of each text) and a row for each vector. The citation is the card's line, then `Section [headings]` and `Language: not recorded` (no card or theme records a language; recording it is deferred). A heading is cleaned, cut, and has `"`, `[`, `]`, `>` and `\` taken out. A build does not reuse an unusable or mismatched file, makes every vector, and puts the new file in place only when whole (`replaced`); a failure, an `OSError` included, leaves the old file and no folder of the build.
  It reads a row back only if it is what the engine writes: the theme checked as a theme is (anchor included), its id and its hashes equal to those of the theme it holds, valid ids and versions, and vectors of the right length, finite and not all zero. `read_themes`, `read_vectors`, `connect`, `check_entry`, `lock` and `citation_line` are there for the search of Increment B. The counts: `books` (each counted once), `inactive`, `no_card`, `no_themes`, `unreadable`, `built` (so `books` is their sum), `themes`, `vectors`, `kept`, `made`, `texts_sent`, `model`, `dimension`, `replaced`.
- **Verification as run.** Tests first: the module did not exist. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themevectors engine.tests.test_vectors engine.tests.test_theme` printed `Ran 242 tests ... OK` (47 of them new); `wb run code-work check` clean. The card vectors' tests are in the run to show that the functions the module reuses (`vectors.pack`, `sha256`, `prefix_hash`, `_identity`, `_remove`) behave as they did.
  Deliberate breaks: 37 one-line breaks of `themevectors.py` (each text left out or added, the dedupe, `again`, `replaced`, the language, the section cleaning and its cut, the lock, the mode of the file, the leftover of a killed build, each check of the file and of the model, a theme read without its checks, a hash or an id not compared, a vector of zeros, an inactive book built, each count, the shape of the file, a link, a trigger or a view, the card generation,
  the model check when nothing is kept): all caught after tests were added for the ones that were missed at first (the id of the row, a vector of zeros, the model of kept vectors, an unknown field, the card generation); file restored identical (sha256 prefix `dbdb18d71209`).
- **Review.** The independent `reviewer` agent (read-only), one round, no blocking finding. Applied: "newest valid card" corrected to "newest card" (a damaged newest card is `no_card`, as in the catalog) and tested; a book with no version counts as `no_card`; the hashes of a row are compared with the texts of the theme; the book id of a vector is checked; `>` is dropped from a heading; an `OSError` while writing is a `KbError`; the check of the model that made the kept vectors applies only when a vector is kept;
  the branch for a text that cannot be encoded was dead (a theme with a lone surrogate does not pass `theme.read`) and was removed with its count; the counts add up and are tested; a failure after the folder of the build exists, the lock held across the replace and a second writer refused, and the files a build opens are tested. Not changed, noted: a kept vector is trusted by the hash stored with it (as the card vectors trust theirs; the file is local and the owner's);
  the `server` of the embedding entry is not recorded in the file, so another server behind the same model name keeps its vectors; two builds at once each write a whole file and the last rename wins; `themes-run` and `themes-reflag` take no lock on this file.
- **Not run.** The search and the commands (Increment B); any live call; no vectors were made over the library. No security review (not asked).
- **Not done.** Increments B and C.

### Increment B (the search and the commands; committed)

- **Done.** In `engine/kb/themevectors.py`: `search(index_root, cfg, query, limit, ...)`, `result_of`, `render` and `_shown`. The query is turned into a vector with the model the config names for `card-embed` (with the entry's query prefix, if it has one); each theme is ranked by the cosine between it and the closest of its vectors, one result for each theme, at most 50 (10 by default), ties to the first text (summary, description, problem, method, needs, provides, limits) and then to the first theme.
  A result gives the theme id and its place, the book's title, the theme's title, type, summary and confidence, the whole anchor, the text that matched as the excerpt with the mark of that part (`stated`, `inferred`, or none for the summary and the whole description), the flags, the citation, and the theme as text between the untrusted-text markers. Every printed text of the file is cleaned and withheld whole if it holds the words of a marker (`card._shown`, as a card is shown); `[stated]` and `[inferred]` in a text become `(stated)` and `(inferred)`.
  A vector is used only if its hash is the one its theme row holds for that text and it is a finite vector of the right dimension that is not all zeros; the others are counted in `stale`, and a theme with none left in `without_vector`. The search reads the file read-only, sends only the query, and is refused before it is sent for a bad limit or query, a missing, linked or foreign file, a file for another model, dimension or prefix, or a row that is not what the engine writes; and after it for a reply from another model.
  The commands in `engine/kb/__main__.py`: `theme-vectors [--again]` (opens the store to write; exit 1 if a book could not be read) and `theme-search QUERY [--limit N]` (opens no store); neither has an option for a model, a server, an address or a launcher. `docs/specs/theme.md` ("Search and reading"), `docs/specs/models.md` and the engine README say what is embedded, sent, shown and not shown.
- **Verification as run.** Tests first: the search and the commands did not exist. `python3 -W error::ResourceWarning -m unittest engine.tests.test_themevectors engine.tests.test_vectors engine.tests.test_theme engine.tests.test_catalog` printed `Ran 370 tests ... OK` (80 in `test_themevectors`, 33 of them new in this increment); `wb run code-work check` clean; `python3 -m kb --help` and the help of the two commands show them.
  Deliberate breaks: about 35 one-line breaks of the search, the result, the render, `_shown`, the clean checks, the citation line and the two commands (the limit and its range, the query check, the model of the reply, a query vector with no length, the order of ties and of the ranking, the hash of a vector, each count, each mark, the markers, the anchor, the prefix flag, the kind of the query, the exit code, the store opened by the search, the parameters of the commands, the cleaning of each printed text,
  the withholding of headings that hold a marker together, each of the two cleanings of the citation, the id pattern): all caught, after tests were added for the ones missed at first (a query vector with no length reached by bypassing the embedding call, a flag detail that holds marker words, the cleaning of a heading). Breaking only one of the two cleanings of the citation is not caught by itself because the other still makes the line clean; breaking both is (6 tests). Files restored identical.
- **Review.** The independent `reviewer` agent (read-only), three rounds. **Round 1 returned a blocking finding that was real:** `read_themes` required the whole citation to pass `textutil.title`, which returns nothing for a line whose letters hold the words `untrusted text`, so a source address such as `.../untrusted-text-handling`, or two headings `Untrusted` and `Text`, made a build that succeeded and a search that refused the file ("run `theme-vectors`") whatever was rebuilt.
  Round 2 found the same kind of fault again: dropping `>`, `[`, `]`, `"` and `\` from a heading left two spaces that the read check collapses, so `Input > Output` made the file unsearchable. Round 3: closed. Fixed: the citation is checked for clean text only (as the catalog's citation is) and not for marker words; headings that hold a marker together are withheld whole; each heading and then the whole line are cleaned, so the line the build writes equals its own cleaned form;
  a test builds and searches with headings and an address that triggered each fault; `flags[].kind` passes through `_shown`; the ids a theme may have are those of `theme._ID` (a latent mismatch with `t1`-style ids, noted by the reviewer, is closed and tested); the withholding is tested on the summary, a part, the excerpt and a flag detail; a test renamed for what it shows; the README mentions the cut of the excerpt.
  Accepted, noted: the `anchor` is printed as the theme holds it, its path included (a reader needs it whole to find the passage; it is data in the object and not text between the markers, and a heading in it may hold the words of a marker); the citation line is printed outside the markers, as a card's is; the card's own fields are assumed clean, and the line is cleaned again as a whole; a vector is kept or used by its stored hash, as for cards; the server of the embedding entry is not recorded in the file.
- **Not run.** Any live call (the build over the library and the eight searches are Increment C); no vectors exist over the library yet. No security review (not asked; this touches a file, untrusted text, parsing and a network boundary, and the reviewer found two real faults in how the file is written and read, both fixed and tested).
- **Not done.** Increment C.
