# Theme weave

Status: Active
Updated: 2026-11-12

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

The library holds 176 books, 175 of them with a card and 174 with vectors. A card holds a short description of the book, key ideas
(each marked as stated by the book or inferred by a model, with a verbatim quote that was checked), and a description of the book's
problem, approach, what it needs, what it provides and where it would not work, in words of no field. A search by keyword and a search
by meaning rank books, and `problem-search` merges the books found for up to five sub-problems. The vectors cover three of those
descriptions, which are single strings on the book. Themes, as `docs/specs/theme.md` designs them, are built and made for the library:
1,913 themes in 175 of the books (made on 2026-11-11 and 2026-11-12 by the extraction and the check of `engine/kb/themeextract.py` and
`themecheck.py`). Each has a title, a type, a summary, a description of five parts in words of no field, an anchor into the book, a
confidence, a mark of stated or inferred on each part, and flags. They have no vectors and no links between them yet. The flag for a
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

### theme-links: Link themes from different fields

- ID: theme-links
- Outcome: links between themes exist from sources that cost no model call per pair, such as closeness across fields, citations from
  one book to another, and what one theme provides against what another needs. Weak and cross-field links are kept, and each link
  records its kind and its reason.
- Dependencies: theme-vectors.
- Boundary: in, the kinds of link, how they are chosen so that the strongest are not the only ones kept, and how they are stored. Out,
  judging pairs by a model, stored judgments of pairs, and the walk.
- Trigger: theme-vectors is done and the owner asks for a plan.

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

- Which stage of the weave to build, stored threads or threads made at the time of the query: open until a measure of extrapolation
  exists (`docs/specs/weave.md`).
- Judging pairs by a model: not part of this scope until the trial says it would add anything.
- The variety of fields in the library: a limit that no setting removes. Adding sources is the owner's, and the crawler and the
  classification of sources are a different scope.
- Visibility to a guest and the security work that goes with it.

## Decisions

- [The library equips a research agent to find non-obvious ideas across fields](../decisions/2026-11-11-the-library-equips-a-research-agent-to-extrapolate.md)
- [The knowledge base is a standalone package](../decisions/2026-11-04-knowledge-base-is-a-standalone-package.md)
