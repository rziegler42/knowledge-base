# Theme

Status: Draft

This specifies the theme, the unit of meaning that the weave connects and that theme-level search finds. It belongs to the design in
`knowledge-base.md` and builds on the book in `book.md`. **Nothing here is final.** The spec stays `Draft` until the owner approves
it, and any statement can be reopened. Each statement carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

The size of a theme (idea-level) is agreed; the kinds of theme are still open, so both come first.

## Scope

A theme is a derived chunk of meaning inside a book that points back to an excerpt, for citing. This spec covers what a theme is,
what it holds, how it is extracted from a converted book, how it stays stable across reconversions and versions, where it is stored,
how it is searched and cited, and how it is tested. It does not cover the threads between themes (the weave), the card of a book,
or conversion; they have their own specs.

## Non-goals

- **[agreed]** Verifying claims. A theme is a lead to follow, not a claim to rely on.
- **[proposed]** Threads, weights and the choice of weaves. A theme is useful without a weave, because searching at the theme level
  can find a passage that a card or a whole-book description would bury.
- **[proposed]** Changing a book. Themes are derived and never touch the book's primary source.

## Assumptions and constraints

- Themes are built from the converted text of a book version, using the anchors and the structure-quality label that `book.md`
  specifies. In this spec an **anchor** is the typed locator of `book.md` (a page, section, line range at a commit, time range or
  comment id) together with the part of the version it lies in. A paper has one part, and the examples here, which speak of
  sections and paragraphs, are the paper case.
- Every theme is model output, so it is untrusted data and is returned marked as such. The excerpt it points to is the source's own
  words.
- The costly model output of a book is kept in the book's own folder in generations that are never overwritten (`book.md`).
- The local model does the bulk of the work and a cloud model is used sparingly, within subscription quotas (`knowledge-base.md`).
  An experiment found a modest edge for a cloud model on domain-neutral descriptions, and none within a single field.
- Nothing tracked points to anything untracked, so a theme is cited by source URL, retrieval date and content hash, plus its anchor.

## Behavior

### What a theme is

- **[agreed]** The word is *theme*: a derived chunk of meaning inside a book that points back to an excerpt, for citing. It was
  chosen over unit, passage, idea and concept.
- **[proposed]** A theme belongs to one version of one book and to one generation of model output. A new version gets its own themes,
  and the themes of earlier versions are kept and marked historical.

### Size and kind

- **[idea]** Three granularities were considered, meaning what one theme holds. Section-level themes are cheap and stable but blur
  ideas together. Idea-level themes hold one technique, finding or concept each, anchored to a stretch of text. Claim-level themes
  are precise but expensive, noisy and hard to keep stable. The leaning is idea-level.
- **[agreed]** Themes are idea-level: one technique, finding, problem or concept each. A theme is the right size if its neutral
  description makes sense without the rest of the book; if it does not, it is too small and is merged into its parent idea, and if
  it needs "and also", it is too big and is split. A theme has one contiguous anchor range, themes may overlap, and the anchor also
  records the section path so a reader can step up to the section. The type is a hint for the weave and never a filter, and a theme
  without a clear type is kept. The extraction test on real papers passed its acceptance test (see the evidence note), and a second
  check on a more varied corpus is still wanted before relying on it for cross-field finds. The criterion that was passed: the two
  questions that card-level search missed were found at rank 1 to 6 by theme-level search in the first test. The corpus and the
  limits of that test are in the evidence note.
- **[agreed]** The number of themes in a book is not targeted or fixed. Book content and size lead to vastly different counts that are
  known only when a book is processed, and a fixed number would add noise to small books and drop information from large ones.
- **[proposed]** Quality is kept by checks and not by a count: near-duplicate themes within a book are merged; the share of a book's
  text that lies under some theme (coverage) and the number of themes per thousand tokens (density) are recorded for each shelf
  and model, so that a model that produces too few or too many shows up; a generous safety cap per book breaks only runaway output
  and is never a target; and a weak theme is kept and weighted down by its confidence.
- **[agreed]** There is an upper bound on the number of themes per book, one never expected to be reached and small enough to catch
  a runaway.
- **[proposed]** The bound scales with the book: the larger of a floor and a generous number of themes per thousand tokens, with an
  absolute ceiling above both, all settings. The defaults are chosen after the first real runs, at several times the highest normal
  density observed. Reaching the bound does not truncate: the stage is marked failed with the reason "runaway", the output is kept
  aside for inspection, and repeated hits pause the shelf through its circuit breaker.
- **[idea]** Each theme has a type, such as *problem*, *method*, *finding* or *concept*, because the weave's "fit together" idea needs
  to match a method that provides something with a problem that needs it. The set of types is open.

### What a theme holds

- **[proposed]** A theme holds: its id; the book id, version and conversion it came from (tool and version); its part and its anchor
  (the locator kind and a start and an end), and a hash of its excerpt; a short title; a type; a summary in the source's own vocabulary; a domain-neutral
  description; a confidence; and a generation record (model, prompt version, date).
- **[proposed]** The domain-neutral description has five parts, as used in the experiments: the problem it solves, the method in
  general terms, what it needs, what it provides, and where it would not work. It avoids the names of any field, game, product or
  person, and it avoids the field's jargon.
- **[proposed]** The two descriptions serve different searches. The summary in the source's vocabulary serves search within a field and
  citing. The domain-neutral description serves matching across fields. Each is embedded separately, and a search can use either or
  both. In the experiments, neutral descriptions helped for a problem written in one shelf's own vocabulary and did not help within a
  single field.
- **[agreed]** Keep both descriptions and embed both. The owner errs toward whatever helps find novel concepts, so an embedding is
  dropped only if a test shows that doing so loses nothing for finding novel concepts. The texts are the costly part and are always
  kept; which are embedded can be changed later because embeddings are cheap to rebuild.

### Extraction

- **[proposed]** Themes are extracted after the card, as a later pipeline stage in priority order, section by section within the
  model's context budget (pieces of about 8,000 to 16,000 tokens). The model proposes themes, each with an anchor.
- **[proposed]** Every anchor is checked against the text: the excerpt must exist at the anchor, and its hash is recorded. A theme
  whose anchor does not hold is rejected, so a theme cannot cite text that is not there.
- **[proposed]** The model does not quote its own start and end. It names the section or paragraph a theme comes from (or, for another kind of source, the equivalent that its profile gives: a line
  range, a time range or a comment), and code finds the exact span and records the excerpt hash. In the extraction test, asking a 12-billion-parameter local model for start
  and end quotes failed to anchor 44 percent of its themes, mostly because the end quote was missing or did not match.
- **[proposed]** The prompt tells the model to skip proofs, lemmas and a paper's own local definitions. In the test these appeared
  as themes with full confidence, so a confidence floor does not remove them.
- **[proposed]** A flat conversion falls back to windows of text with page markers, and its themes count for less. A pointer-only book
  gets themes from its captured snapshot only, marked partial.
- **[proposed]** Near-identical themes within one book are merged, and themes of books marked as the same work or as duplicates are
  marked so that they do not create strong, useless "alike" threads.
- **[idea]** When a new version leaves a section unchanged, as shown by the excerpt hash, its themes are reused and not re-extracted.

### A run over the library

What is built now, from the plan `2026-11-11-run-the-theme-extraction-over-the-library` (the commands are in the engine README).

- **[proposed]** A run is planned, then run. The plan makes no model call: it lists the books to make themes for (active, with a card that can be read and a
  conversion in use) and the others with a reason, counts the pieces, and estimates the time. The run makes, checks and files a new generation of themes for
  each book as soon as it is made, one book at a time, and saves a record after every book. Its records are derived and can be deleted without losing a theme.
- **[proposed]** A book is skipped when the newest valid generation of its current version was made with the prompt version and the model now set for the extraction. The
  model and prompt version of the check are not in a generation, so the skip rule cannot see them; the record of each book names them, and the plan lists the skipped
  books whose check is another or not known, so that the owner can ask for them again.
- **[proposed]** A book that fails does not end the run, and is tried once more after the last book. Three books in a row failing for a reason that is not a refused answer
  stop the run (a server that is down would fail every book), and the books not reached stay waiting. A book that is no longer active, or whose conversion changed since
  the plan, is dropped and reported. A run stopped at any point and run again makes no book twice whose record was saved.
- **[proposed]** The theme run and the card queue share one lock, so they never run together against one index root. The lock does not guard a second index root
  or another machine that uses the same model server.

- **[agreed]** A theme is described in English whatever the source's language. The excerpt stays in the source's own words, and the
  citation shows the language. The embedding model should be multilingual (`card.md`).

### Stability

- **[proposed]** A reconversion can shift anchors. A theme is re-anchored by its excerpt hash and is kept if the excerpt is found, and
  flagged if not.
- **[proposed]** Themes are kept in generations. A better prompt or model adds a generation, the index uses one active generation, and
  an earlier one can be restored. Threads record which generation of themes they judged.

### Storage

- **[proposed]** A book's themes are kept in its own folder, per generation, with the model, prompt version and date. The embeddings
  and keyword indexes are kept in the index root, so searching never touches the bulk drive, and they can be rebuilt from the book
  folders.

### Search and reading

- **[proposed]** Theme-level search is a reading operation. A result gives the theme id, the book, the excerpt's anchor, the summary,
  and a citation line, and it says how complete its source was (for example that the shelf is still being seeded).
- **[proposed]** Reading is layered, cheapest first: the card, a theme, the excerpt or section by anchor, the full text. Each response
  is bounded and says where the next piece is.
- **[proposed]** Everything returned is marked as untrusted data, and an instruction found in a theme or an excerpt is ignored.

### Citing

- **[proposed]** A theme yields a citation line made of the source URL, the retrieval date and the content hash of the version, plus the
  anchor and the excerpt hash.

### Privacy

- **[proposed]** A theme is visible to a guest only if its book's shelf is shared.

### Confidence

- **[proposed]** A theme carries a confidence that reflects the structure quality of its conversion, whether its anchor verified, and
  how the model rated it. Low-confidence themes are kept and weighted down, not dropped.

## Acceptance criteria

All of these are provisional until the spec is approved.

- Extracting themes from a converted book gives themes whose excerpts exist at their anchors, and a theme with a false anchor is
  rejected.
- A reconversion that shifts anchors leaves the themes re-anchorable by their excerpt hash.
- A new model generation adds themes without changing the earlier generation, and the active generation can be switched back.
- Theme-level search returns results with a citation line, marks them as data, and says how complete its source was.
- Two questions that card-level search missed in an earlier experiment, finding the paper with an opening-book framework and finding
  the sequential-test papers for stopping a matchup early, are found by theme-level search, or the spec records why they were not.
- On a hand-made library with shelves A, B and C and a problem D whose combined solution is known, searching the neutral descriptions
  of the problem's sub-questions surfaces a theme from each shelf, with the excerpts cited.

## Open questions

- The kinds of theme, and whether the type set (problem, method, finding, concept, other) is right once themes from a more varied
  corpus exist.
- Whether one model pass over a whole section, or a pass per candidate theme, extracts themes better. The first test used one
  pass per piece of about 10,000 tokens, and anchors are now found by code from a section or paragraph pointer.
- Which embedding model is pinned. Both descriptions are embedded (agreed above).
- Whether theme extraction needs a stronger model than the local one, which only an experiment on real books can show.

## Governing decisions and references

- Decisions: none recorded in this repository yet.
- References: none.
- Evidence (a throwaway experiment, 2026-10-31, scripts and data not kept): idea-level extraction by a 12-billion-parameter local
  model over 48 papers, mostly game AI, in 102 pieces of about 10,000 tokens, took 39 minutes. 593 themes were proposed and 331
  survived the anchor check. The median was 0.42 themes per 1,000 tokens, two pieces returned invalid output, none hit a
  runaway cap, and 4 of 331 had a near-duplicate in the same paper. Theme-level search put the paper with an opening-book
  framework at rank 1 or 2 among the 48, against 9 to 18 for card-level search, and put at least two of four sequential-test papers
  in the top six for most variants, against 17 to 31 for card-level search apart from one at 2. The other five questions were
  mixed. Limits: a small corpus that is mostly one field, the right papers chosen by text search, the stands-alone check made by the
  model that wrote the themes, and no section-level or claim-level variant tried.
- Evidence (a second throwaway experiment, 2026-11-01; evidence note 10 in `knowledge-base.md`): with paragraph pointers and code finding the exact span, 98.6 percent of 1,677 themes had a valid anchor, against 56 percent for quoted anchors, and the median was 10 themes per paper. On 8 documented cross-field transfers, theme-level search with neutral descriptions did not beat card-level search with neutral descriptions at ranking the source paper (mean reciprocal rank 0.43 and 0.48 against 0.47 and 0.45), and a paper with many themes was favoured. Themes add the pointer to the passage and a finer match, not a better paper ranking.
- The design this belongs to is `knowledge-base.md`, and the book it builds on is `book.md`. The related specs are `shelf.md`,
  `card.md`, `library.md` and `testing.md`. The pipeline is in `pipeline.md`; the models are in `models.md`, the reading module in `reading.md` and the weave in `weave.md`.
