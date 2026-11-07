# Cards

Status: Active
Updated: 2026-11-07

## Purpose

Make the books of the library findable by what they are about and what they are useful for, and not only by the words in their
text. A card is a short, model-written entry for a book (`docs/specs/card.md`). The finish line is that an agent can search the
cards by keyword and find books that a keyword search of the full text misses, and a trial on the books the library holds shows
whether it does. The first step uses keyword search only; search by meaning is deferred. Themes are not part of this roadmap.

## Current state

The engine captures, scans, converts and indexes books, searches their text by keyword and reads a passage back by locator. It
makes no model call, writes no card and holds no catalog. The card spec is a `Draft`, and most of its statements are marked
proposed. A bridge to local models (`ask-ollama`) is installed in the workbench, and the engine does not use it yet.

## Candidates

### model-calls: Call a local model from the engine

- ID: model-calls
- Outcome: the engine can send one prompt to a local model through the Ollama bridge and take back one checked reply, with the
  model, prompt version and date recorded for every output. The models and their addresses are held in the owner's config and in
  no tracked file.
- Dependencies: none. It first reads what the installed bridge does and does not offer, such as structured output and an
  owner-only address setting.
- Boundary: in, a registry of one or a few local models, a call, a check of the reply's shape, the generation record, and the
  owner's on/off switch. Out, choosing between models, escalation to a cloud model, quotas, budgets, embeddings and any change to
  the bridge itself, which belongs to the workbench.
- Trigger: the owner accepts this roadmap and asks for a plan.

### card-stage: Write a card for each converted book

- ID: card-stage
- Outcome: a converted book gets a card, written by the model, kept in the book's own folder as a generation that is never
  overwritten, with the mechanical fields taken from the manifest and the model-written fields marked as untrusted. Both the
  summary and the domain-neutral description are written, so that a later search by meaning needs no rewrite.
- Dependencies: model-calls.
- Boundary: in, a long book read in pieces, a partial card for a book that has no conversion, scan findings carried as caveats,
  and a prompt that tells the model to ignore any instruction in the book. Out, themes, regenerating cards in bulk, switching
  generations, and search.
- Trigger: model-calls is done and the owner asks for a plan.

### card-catalog: Search the cards by keyword

- ID: card-catalog
- Outcome: the cards are searchable by keyword in the library's index, and a result gives the card, a citation line, a mark that
  it is untrusted data, and how complete its source was. The index can be rebuilt from the book folders alone.
- Dependencies: card-stage.
- Boundary: in, keyword search over both descriptions and the other fields of a card, and a search that names a book. Out, search
  by meaning, vectors, search by shelf, and guest visibility.
- Trigger: cards exist for some books and the owner asks for a plan.

### card-trial: Try the cards on the books the library holds

- ID: card-trial
- Outcome: the owner knows whether the cards help. For a set of questions the owner chooses, the trial compares what a search of
  the cards finds with what a search of the full text finds, and reports the card length and shape that worked, whether the
  neutral description leaks field names, and whether the summaries are too literal.
- Dependencies: card-catalog.
- Boundary: in, a trial on the books the library holds, a written result, and the owner's decision on whether to go on to search
  by meaning or to themes. Out, building either of them.
- Trigger: card-catalog is done and the owner asks for a plan.

### card-grounding: Make every item on a card traceable to the book

- ID: card-grounding
- Outcome: the owner knows how accurate the cards are, and the cards are more accurate. A card's key ideas and topics grow or
  shrink with what the book holds. Each claim taken from the book carries a short verbatim quote, and a check confirms that the
  quote occurs in the piece it names; an item with no verified quote is dropped or marked as inferred, and a card with fewer
  than the minimum is marked thin, not padded. Each item is marked stated, inferred or unverified, and a search result shows
  the mark. The accuracy of the current cards and of the new ones is measured on a sample of items that the owner labels as
  supported, unsupported or inference. Time and calls are spent on accuracy.
- Dependencies: card-trial (its result says what the cards get wrong), card-stage.
- Boundary: in, higher ceilings in the merge call, a quote per claim and a mechanical check of it, the three marks, the owner's
  labelled sample and the accuracy measure, a fix to the prompt's wording (the right word for the kind of source, no mention of
  the pipeline's notes), and a second trial on harder questions and more books. Also in, if the labelled sample shows it pays: a
  second model, named in the owner's config, that checks one more round when a list is full or an item's support is weak
  (tested against the owner's labels before it is trusted), agreement across two runs of the note stage, and a test of whether
  covering every piece of a long book improves accuracy before the sample cap is raised. Out, search by meaning, themes, cloud
  models, and rewriting existing cards (a new card is a new generation).
- Trigger: the trial's result is recorded and the owner asks for a plan.

## Deferred work

- Search by meaning and the embedding model: cards are stored so that vectors can be added later without rewriting any card.
- Themes, the weave and theme-level search: the card spec puts them after the card, and the trial decides whether they are worth
  their cost.
- Shelf filing and reshelving by card: they score a book against a shelf's scope using its card, so they follow this roadmap.
- Choosing between models, escalation to a cloud model, quotas and per-shelf budgets.
- Visibility of cards to a guest, and the security work that goes with it, until the owner knows the system works.
- The workbench package that lets an agent in another project search the library: a different scope with its own finish line.

## Decisions

- [The knowledge base is a standalone package](../decisions/2026-11-04-knowledge-base-is-a-standalone-package.md)
