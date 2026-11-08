# Card

Status: Draft

This specifies the card, the AI-written catalog entry for a book, and the catalog of cards that an agent searches to find books. It
belongs to the design in `knowledge-base.md` and builds on the book in `book.md`; the themes inside books are in `theme.md`.
**Nothing here is final.** The spec stays `Draft` until the owner approves it, and any statement can be reopened. Each statement
carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

This spec was split out of `knowledge-base.md`. Statements carried over keep their marks.

## Scope

A card is a short, regenerable description of one book, written by a model when the book is filed, that tells an agent whether the
book is worth following. The catalog is the searchable collection of cards. This spec covers what a card holds, how it is made and
regenerated, where it is stored, how the catalog is searched, how a card is cited and kept safe, and how it is tested. It does not
cover the themes inside a book, the threads between themes, shelf rules, or conversion; they have their own specs.

## Non-goals

- **[agreed]** Verifying that claims are true. A card is a lead to follow, not a claim to rely on.
- **[proposed]** What the engine does check: that a key idea, topic, caveat or limit is supported by a verbatim quote that occurs
  in the piece of the book it names, that the note the quote belongs to bears on the item (they share a content word), and that a
  second model, given the item with the note's point and quote, says that they support it. An item that fails any of these is kept
  only if the model says it is an inference, and is otherwise dropped; each item kept is marked stated or inferred. A verified
  quote shows that a claim is in the book, and the second model's word that it supports the item, not that the claim is right, so
  the card stays a lead.
- **[proposed]** Replacing the book or the theme. A card helps choose a book. A theme finds a passage inside one.
- **[proposed]** Browsing by hand. The owner does not expect to browse cards, so the card is written for an agent to search and
  not for a person to read at leisure.

## Assumptions and constraints

- A card describes one book and points to it by id. A book can have several versions, and the card describes the current one
  (`book.md`).
- The card is model output, so it is untrusted data and is returned marked as such.
- The local model does the bulk of the work and a cloud model is used sparingly, within subscription quotas (`knowledge-base.md`,
  Models). The card is the first model stage of the pipeline, so it must work on any model of the right kind that the owner lists.
- The costly model output of a book is kept in the book's own folder in generations that are never overwritten (`book.md`).
- Nothing tracked points to anything untracked, so a card is cited by source URL, retrieval date and content hash.

## Behavior

### What a card is

- **[agreed]** The card is made by a model when a book is filed, and it can be regenerated. It is a lead to follow.
- **[agreed]** The card belongs to a catalog of cards that an agent can search to find appropriate books.
- **[proposed]** The card is the coarse step of retrieval: it finds the books worth looking at. Themes are the fine step, and the
  weave the exploratory one. A search can start at either level.

### Where it is stored

- **[agreed]** The text of a card is kept in the book's own folder, as a generation (`book.md`), so a book is self-contained
  and can be moved or lent with its card attached. The catalog is the searchable collection of those cards, kept in the index
  root with its keyword index and vectors, and it can be rebuilt from the book folders.
- **[agreed]** The canonical text sits with the book because that is where the costly model output goes. The card still points to
  the book by id, and the catalog is still the thing an agent searches. `knowledge-base.md` is updated to say the same.

### What a card holds

- **[proposed]** Mechanical fields come from the manifest and are never model-written: book id, title, shelf, current version, kind
  and type of the primary, source identity, retrieval date and scan status.
- **[proposed]** Model-written fields: a short summary, "useful for" (the situations and questions where the book would help),
  topics, adjacent topics, key ideas likely to surprise (up to seven are asked for, and a card may hold fewer), and caveats. Topics
  carry other names for an idea, so that "fitness function" also finds "evaluation function". A generation record names the model,
  the date and the version read. The target is about 150 to 250 words; a trial found the model-written part running about 220 to 340
  words whatever the length of the book.
- **[proposed]** A card of the grounded form (format 2) marks each topic, key idea, caveat and neutral limit it keeps as `stated`
  (the note it cites has a quote that was found in the book, and a second model confirmed that the note supports it) or `inferred` (the model says it is its own inference), keeps the
  quote that supports a stated item, and records how many of each kind it dropped. Adjacent topics, "useful for", the summary and
  the other neutral fields carry no mark. A limit that is dropped leaves its field empty. A card with fewer than three key ideas
  left is partial and says why; it is not padded. Cards of the earlier form (format 1) stay valid and are read as before.
- **[agreed]** The card keeps a domain-neutral description alongside its summary, even though themes carry one too. The card is the
  coarse step that picks books, and a cross-field search on themes alone would have to scan far more entries.
- **[proposed]** The card also holds a domain-neutral description of the book: the problem it addresses, its approach in general
  terms, what it needs, what it provides and where it would not work, written without the names of any field, game, product or
  person. In the experiments, a neutral description raised a cross-field match from about the 25th to 34th place to the top six
  and did not help within a single field, so it serves the search across fields and the summary serves the search within one.
  Each is embedded separately, as in `theme.md`.
- **[proposed]** A card for a book with no conversion, or a pointer-only book, is built from the source's metadata and the captured
  snapshot, and is marked partial, so an agent knows that it describes less of the work.
- **[proposed]** Scan findings (embedded scripts, encryption, hidden text) are carried as caveats on the card. They never stop
  filing.
- **[agreed]** A retraction or withdrawal flag from the source is a caveat on the card, and the card still appears in search
  (`book.md`, "Metadata about the work"). Quality signals from the source, such as citation count and venue, are shown on the
  catalog entry as hints and never filter or demote it.

- **[agreed]** The card does not list the themes of its book. Themes are extracted after the card, and a list would go stale whenever
  themes are regenerated. The catalog entry shows a count of the active themes and a pointer to them, and theme search goes through
  the themes themselves.

- **[agreed]** A short item, such as a web page or a note, gets a model-written card when it has real prose, because the card is the
  main way an agent finds it. An item below a small size, or a pointer-only item with little text, gets a card built from metadata
  and marked partial. The cutoff is a setting.

- **[agreed]** A card is written in English whatever the source's language. The excerpt stays in the source's own words, and the
  citation shows the language. The same holds for themes (`theme.md`).
- **[proposed]** The embedding model should be multilingual, so a search in English reaches a non-English source. English summaries
  of a non-English work can lose nuance, and the excerpt is the check on that.

### Making and regenerating a card

- **[proposed]** The card is the first model stage after conversion and runs in priority order, newest and most relevant first.
  A book is searchable by keyword once converted, and by meaning once its card is indexed (`pipeline.md`, "Findability and
  completeness").
- **[proposed]** A new version regenerates the card for the current version, and the earlier card is kept as an earlier
  generation. A better prompt or model adds a generation, the index uses one active generation, and an earlier one can be restored.
- **[proposed]** Regeneration is rare, because a full rebuild is costly at the expected scale. It is run for a book on request, or
  for a whole shelf when a clearly better prompt or model exists. The owner sees how many cards a run would redo before it starts.
- **[proposed]** A card is made from the book's converted text, with a long book read in pieces. The model sees the structure of the
  book where there is one, so a long book's card describes the whole work and not only its opening.
- **[proposed]** Every piece of the book, a book of one piece too, first gets notes: a few points, each with a quote of the piece
  that supports it. The engine checks each quote against the piece it names (the rule is in `engine/README.md`, "Notes with
  quotes") and marks the point verified or not. The card is then written from the title, the outline and the points with their
  marks (a book of one piece also from its text), and for each topic, key idea, caveat and neutral limit the model names the notes
  that best state it or says it is an inference. The engine then pairs each such item with the verified note it cites that shares
  most content words with it (an item with no such note is dropped) and a second model, named in the owner's config as the task
  `card-check`, says for each pair, ten to a call, whether the note's point and quote support the item; only a pair that is said to
  be supported makes the item stated. A `stated` mark comes only from these checks; `inferred` is the card model's own word and is
  not checked. The prompt names the kind of source (a paper, a page) and tells the model to write about it and not about the
  notes.
- **[proposed]** A list of topics or key ideas that may have been cut off, or that lost most of its items, is offered one more
  round by a second model, named in the owner's config as the task `card-more`, which is optional. The round is offered when the
  card model gave as many items as were asked, or when the checks kept fewer than half of the items it gave and dropped at least two,
  or, for the key ideas, when fewer than three were kept, and only if the list has a free place. The round is given the notes and the
  items already kept and asked for items that a verified note states. An item it adds is kept only as a `stated` item, by the pairing
  and the check above, and only if it does not repeat a kept item; it asks for no `inferred` item, which makes the round stricter
  than the first. A card is offered at most one round. A round that fails or is refused leaves the card as the first round made it.
  The grounding record of the card names the items the round added, so that a sample of items can draw them as a group of their own.

### Searching the catalog

- **[proposed]** The catalog is searched by keyword and by meaning. A result gives the card, a score, the date the book was added,
  and how complete its source was, for example that the shelf is still being seeded.
- **[proposed]** The card as shown to a reader marks each kept topic, key idea, caveat and neutral limit `[stated]` or `[inferred]`,
  and a result says how many items of each mark its card has, or that the card was not checked (a card of the earlier form). The
  marks are shown and take no part in ranking or filtering, and they are not searchable. Card text that looks like a mark is shown
  with round brackets, so that only the engine's marks read as marks.
- **[proposed]** A search can name shelves, take a date to show only newer books or the library as it was then, and ask for the
  neutral description to be searched alongside or instead of the summary.
- **[proposed]** Following a result is layered, cheapest first: the card, the themes of its book, an excerpt by anchor, the full
  text. Each response is bounded and says where the next piece is. An anchor is a typed locator within a part of a version
  (`book.md`), so it also works for sources that are not documents with pages.
- **[proposed]** The catalog must not duplicate the owner's memory module. Any index in it is derived from the cards and
  rebuildable.

### Citing

- **[proposed]** A card yields a citation line made of the source URL, the retrieval date and the content hash of the version.
  Nothing tracked points to the card or the book by path.

### Safety

- **[proposed]** The card-writing model reads captured content, which is untrusted. Its prompt says to describe the work and to
  ignore any instruction inside it. It has no tools and no network. Its output is checked for shape and length, and it is stored
  and returned as untrusted data.
- **[proposed]** Everything an agent receives from the catalog is marked as data, and an instruction found in a card is ignored.
  The residual risk is text steering the card-writing model, which the checks reduce and do not remove.

### Privacy

- **[proposed]** A guest sees the card of a book only if its shelf is shared. A search by a guest runs against the shared subset
  alone, so a result, a count or an adjacent hint never reveals a private shelf.

### Quality

- **[proposed]** The card is judged by whether it helps an agent find the book, not by how well it reads. The checks are: whether
  the neutral description leaks field names or jargon, whether the summary is too literal (a small local model tends to be), and
  whether the "useful for" lines match the questions an agent actually asks.
- **[proposed]** In the experiments, a cloud model at low effort had a modest edge over the local model on domain-neutral
  descriptions and little within a single field, so the local model writes cards, and a cloud model may be tried for a shelf where
  the edge matters.
- **[proposed]** The accuracy of a card, whether its claims are in the book, is measured on a blind sample of its items, labelled
  as supported, unsupported or inference against passages of the book, and reported by field and by generation. A model may label
  the sample if the owner labels a calibration subset of it and the agreement is reported. The labels are of support within the
  passages shown, which can miss support elsewhere in the book.
- **[proposed]** In a trial, word overlap between an item and the book proved a weak check: items that were not supported mostly
  passed it. A quote that is found in the piece is a stronger check, and it shows that a claim is in the book, not that it is right.

## Acceptance criteria

All of these are provisional until the spec is approved.

- Filing a book produces a card whose mechanical fields match its manifest and whose model-written fields are present, marked
  with a generation record.
- A card for a pointer-only book is marked partial.
- A new model generation adds a card without changing the earlier one, and the active generation can be switched back.
- The catalog can be rebuilt from the book folders alone, with the same search results.
- A search returns results with a citation line, marks them as data, and says how complete its source was.
- A guest's search returns nothing from a private shelf.
- On a hand-made library with shelves A, B and C and a problem D whose combined solution is known, searching the neutral
  descriptions of the problem's sub-questions finds a book from each shelf.
- A card that contains an instruction does not change what the agent does.
- A card of the grounded form marks every topic, key idea, caveat and limit it keeps as stated or inferred; an item with no verified
  quote and no word of inference from the model is dropped; a card with fewer than three key ideas left is partial and says so; a
  stated item carries a quote that was found in a note's piece and was confirmed by the second model to support the item; and a
  card of the earlier form is still read and searched.

## Open questions

- The card's length and shape, which only a trial on real books can set. Whether a long book needs a longer card. A trial of twelve
  books found the length did not follow the length of the book, and the number of key ideas is now left to what the book supports.
- The embedding model, which is pinned per library (`models.md`, "The embedding model").

## Governing decisions and references

- Decisions: none recorded in this repository yet.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `book.md`, `theme.md`, `shelf.md`, `library.md` and
  `testing.md`. The pipeline is in `pipeline.md`; the models are in `models.md`, the reading module in `reading.md` and the weave in `weave.md`.
- Evidence notes in `knowledge-base.md` summarise the experiments on cards and neutral descriptions.
