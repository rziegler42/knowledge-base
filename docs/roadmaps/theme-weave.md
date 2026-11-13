# Theme weave

Status: Active
Updated: 2026-11-13

## Purpose

Help a research agent find novel concepts across fields that it would not have thought to search. The roadmap covers the themes the
library offers, the links between them, and the walk along those links that an agent sets in motion with a narrow-to-wide weighting
and a distance. It does not cover loading sources, the accuracy of cards (`cards.md`), shelves, the crawler, or judging whether a find
is novel or worth pursuing, which is the agent's and the owner's. The owner may call a theme an idea; it is the same unit
(`docs/specs/knowledge-base.md`, "Vocabulary").

The finish line is that a research agent can ask the library for themes from distant fields, gets back one theme per item that is
cheap to skim, with its mark of stated or inferred, its citation and the route by which it was reached, and that a trial shows whether
the themes offered at a wide setting differ from what an ordinary search of the agent's own question returns. The owner can then call
the roadmap finished, or pause it, without that deciding anything about shelves, the crawler or the classification of sources.

It is a roadmap of its own and not a continuation of `cross-field-discovery.md`, whose finish line is that a search returns sources
from other fields that suit a problem, compared with keyword search. That is retrieval, and the decision
`2026-11-11-the-library-equips-a-research-agent-to-extrapolate` sets the purpose as extrapolation by a research agent.

## Current state

The owner's local library, which is not in this repository, held 176 books on 2026-11-12, 175 of them with a card and 174 with vectors. A card holds a short description of the book, key ideas
(each marked as stated by the book or inferred by a model, with a verbatim quote that was checked), and a description of the book's
problem, approach, what it needs, what it provides and where it would not work, in words of no field. A search by keyword and a search
by meaning rank books, and `problem-search` merges the books found for up to five sub-problems. The vectors cover three of those
descriptions, which are single strings on the book. Themes, as `docs/specs/theme.md` designs them, are built and have been made for the owner's
local library: 1,913 themes in 175 of its books on 2026-11-12 (made on 2026-11-11 and 2026-11-12 by the extraction and the check of
`engine/kb/themeextract.py` and `themecheck.py`). Each has a title, a type, a summary, a description of five parts in words of no field, an anchor into the book, a
confidence, a mark of stated or inferred on each part, and flags. They have vectors (built on 2026-11-12) and are searched by meaning with `theme-search`, and they have no links between them yet. The flag for a
word of the book's field is a rough reason to look: it is raised on 27 percent of the themes, and the limit it uses is a judgement with
no ground truth. A trial of
cross-field search measured retrieval of known transfers and found search alone looked enough on that measure, with caveats; it did
not measure extrapolation. The weave spec (`docs/specs/weave.md`) is a draft that now states the purpose and lists what is open.

## Candidates

### theme-unit: Make the theme the unit, with a field-free description of its own

- ID: theme-unit
- Outcome: each book has themes, each with a short description in words of no field, a quote or anchor that points back to the book,
  and a mark of stated or inferred, made by the models of the owner's config, kept so that a new generation never overwrites an
  earlier one. Whether they are built as `docs/specs/theme.md` designs them or are the key ideas of the cards given such a description
  is settled in the plan.
- Dependencies: none among these candidates. Uses the cards and the model path that exist.
- Boundary: in, what a theme holds, the check that it does not leak the field's vocabulary or claim more than the book, and a run over
  the library with a report. Out, vectors, links, and a change to what a card holds for the book as a whole.
- Trigger: the owner asks for a plan.

### theme-vectors: Search the themes by meaning

- ID: theme-vectors
- Outcome: the themes are turned into vectors by an embedding model of the owner's config, and a theme can be found by closeness, with
  its citation and its mark. The vectors can be rebuilt from the cards and themes alone and are marked with the model that made them.
- Dependencies: theme-unit.
- Boundary: in, the vectors, their store and a command to find themes. Out, links and the walk.
- Trigger: theme-unit is done and the owner asks for a plan.

### theme-per-book: Limit the themes of one book in a theme search

- ID: theme-per-book
- Outcome: a search of the themes by meaning can limit how many themes of one book a page holds, so that a page shows more books.
  The limit has a default of 2 and an option to change it or switch it off. The counts and the marks stay as they are.
- Dependencies: theme-vectors.
- Boundary: in, the limit in the theme search and its option on the command line. Out, links, the walk, and a separate view of the
  best theme of each book.
- Trigger: the owner asks for a plan.

### theme-links: Link themes that work the same way, across fields (the first weave)

- ID: theme-links
- Outcome: a weave of "same mechanism" links exists over the themes of the library: precomputed and stored, each link carrying its
  closeness, its wording distance, the matched texts and the evidence to check it, kept by the slot rule and the floor of strength,
  repaired in batches as books are added, and rebuilt on its own.
- Dependencies: theme-vectors.
- Boundary: in, the weave of that one kind, its store, its build and repair, and a command to look at the links of a theme. Out, the
  other kinds of weave, judging pairs by a model, and the walk.
- Trigger: theme-vectors is done and the owner asks for a plan.

### theme-links-same-problem: Link themes whose problem is the same and whose method differs

- ID: theme-links-same-problem
- Outcome: a weave of "same problem" links exists, with the same store, slot rule, floor and repair as the first weave, so that an
  agent can see how other fields solved the same problem.
- Dependencies: theme-links.
- Boundary: in, the weave of that one kind. Out, the other kinds of weave and the walk.
- Trigger: theme-links is done and the owner asks for a plan.

### theme-links-fit-together: Link what one theme provides to what another needs

- ID: theme-links-fit-together
- Outcome: a directional weave of "fit together" links exists, each from the theme that provides to the theme that needs, with slots
  and a floor on incoming links of its own, so that an agent can chain themes from different fields into one answer.
- Dependencies: theme-links.
- Boundary: in, the weave of that one kind, the slots for a directional weave and the floor on incoming links. Out, the other kinds
  of weave and the walk.
- Trigger: theme-links is done and the owner asks for a plan.

### theme-links-alike: Link themes of similar subject, as a reference

- ID: theme-links-alike
- Outcome: a weave of "alike" links exists, kept as a reference for when an agent is in its home field and not walked by default.
- Dependencies: theme-links.
- Boundary: in, the weave of that one kind. Out, the other kinds of weave and the walk.
- Trigger: theme-links is done and the owner asks for a plan.

### theme-walk: Let an agent walk from themes along the links

- ID: theme-walk
- Outcome: an agent calls one command with a short named narrow-to-wide scale and a distance, and gets themes offered that it did not
  ask for, one per item, with the route and the reason for each step. The default leans wide, and a narrow setting behaves like an
  ordinary search.
- Dependencies: theme-links, and the weave spec saying what the levels are, how a level bounds the distance and what a step counts.
- Boundary: in, the command, its settings, the output and a skill that says how an agent uses it. Out, judging whether a find is
  novel, and changing how a result is marked untrusted.
- Trigger: theme-links is done, the spec is settled and the owner asks for a plan.

### extrapolation-trial: Try it on problems the owner chooses

- ID: extrapolation-trial
- Outcome: the owner knows whether the themes offered at a wide setting differ from what an ordinary search returns, and has seen
  examples that an agent or the owner can judge. It reports the share of offered themes that an ordinary search of the agent's own
  question would already have returned, at each setting and distance.
- Dependencies: theme-walk.
- Boundary: in, the trial, a written result and the owner's reading. Out, any measure of novelty by a machine, and building what the
  result suggests.
- Trigger: theme-walk is done and the owner asks for a plan.

## Deferred work

- Which stage of judged threads to build, stored or made at the time of the query: open until a measure of extrapolation exists
  (`docs/specs/weave.md`). Links that no model judges are stored and precomputed, by the owner's decision of 2026-11-13.
- Judging pairs by a model: not part of this scope until the trial says it would add anything. The weaves that need it,
  *incompatible* and *disagrees*, wait for that.
- The weave of *builds on*: it needs reference lists between books, which the library does not hold yet.
- The variety of fields in the library: a limit that no setting removes. Adding sources is the owner's, and the crawler and the
  classification of sources are a different scope.
- Visibility to a guest and the security work that goes with it.

## Decisions

- [The library equips a research agent to find non-obvious ideas across fields](../decisions/2026-11-11-the-library-equips-a-research-agent-to-extrapolate.md)
- [The knowledge base is a standalone package](../decisions/2026-11-04-knowledge-base-is-a-standalone-package.md)
