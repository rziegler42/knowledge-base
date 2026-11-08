# Cross-field discovery

Status: Active
Updated: 2026-11-08

## Purpose

Find, for a problem posed in one field, ideas from other fields that fit it. The roadmap covers the search over what books are about
in plain, field-free terms, the way an agent poses a problem to that search, and the trial that shows whether it works. It does not
cover loading sources, the accuracy of cards (`cards.md`), shelves or the crawler.

The finish line is that an agent given a problem from one field gets back, from the library, sources from other fields that suit it,
and a trial on problems the owner chooses shows how often it does, compared with keyword search. The owner can then call the roadmap
finished, or pause it, without that deciding anything about shelves, the crawler or the classification of sources.

It is a roadmap of its own and not part of `cards.md` because that roadmap's finish line is keyword search of cards, and it names
search by meaning and themes as out of scope.

## Current state

The library holds about eighty books on game theory, game players, learning models, algorithms, high performance computing, CAD and
3D printing. A keyword search finds them and a read returns a passage with its citation, from the command line and, through the `kb`
workbench package, from a project. Twelve books have a grounded card with a domain-neutral description; the rest have none. Models
on the owner's server write cards and judge, and an embedding model is available there. Search by meaning is not built.

Earlier experiments (`docs/specs/knowledge-base.md`, evidence notes 10 and 15, and `docs/specs/weave.md`, "Evidence") found that a
search over neutral descriptions finds the source field better than one over summaries or raw text, that the home field's own
version of an idea can hide the source, and that a local model can judge whether a pair of ideas relate. They were run on
another set of papers, and the first trial of the cards used easy questions, so what a search by meaning finds in this library is
not yet known.

## Candidates

### neutral-cards-for-the-library: Give every book a grounded card with a neutral description

- ID: neutral-cards-for-the-library
- Outcome: every book of the library that has a conversion has a grounded card with a domain-neutral description, made by the
  models of the owner's config, as a new generation that never overwrites an earlier one. The run can be left to run on its own and
  reports what failed.
- Dependencies: `cards#card-grounding`. A format fix for failed replies (`cards#card-format-resilience`) helps and is not required.
- Boundary: in, a run over the library with a report, the order and grouping of books so that a model is loaded as few times as
  possible, and the rebuilding of the catalog. Out, a change to what a card holds, themes, and cards for sources that have no
  conversion.
- Trigger: the owner asks for a plan.

### meaning-search: Search the neutral descriptions by meaning

- ID: meaning-search
- Outcome: the neutral descriptions of the cards are turned into vectors by an embedding model of the owner's config, and a search
  by meaning returns books ranked by closeness, with the same citation, completeness and untrusted marks as a keyword search. The
  vectors can be rebuilt from the cards alone and are marked with the model that made them.
- Dependencies: neutral-cards-for-the-library.
- Boundary: in, the vectors and their store, the search command, and a check that a stale or foreign vector is refused. Out, themes,
  search over the full text by meaning, a cloud embedding service and ranking by anything but closeness.
- Trigger: cards with neutral descriptions exist for most of the library and the owner asks for a plan.

### problem-search: Let an agent pose a problem and search across fields

- ID: problem-search
- Outcome: an agent can restate a problem in general terms, split it into sub-problems, search each by meaning across all fields and
  set aside results from the problem's own field, and gets books with a short reason for each. It is a command and a skill of the
  `kb` package.
- Dependencies: meaning-search.
- Boundary: in, the command, the skill and the way results from the problem's field are set aside. Out, judging pairs, stored
  threads, and any change to how a result is marked untrusted.
- Trigger: the owner asks for a plan.

### cross-field-trial: Try it on problems the owner chooses

- ID: cross-field-trial
- Outcome: the owner knows whether it works. For a set of problems the owner chooses, with the transfers they expect, the trial
  compares what a keyword search, a search by meaning and the problem search return, and reports how often a source from another
  field is found and at what rank. It ends with the owner's decision on whether to go on to judging pairs.
- Dependencies: problem-search.
- Boundary: in, the trial, a written result and the owner's decision. Out, building what the decision chooses.
- Trigger: problem-search is done and the owner asks for a plan.

### pair-judging: Judge pairs of ideas that a search returned

- ID: pair-judging
- Outcome: a model judges candidate pairs among the books or passages that a problem search returned, states in what way each pair
  relates, and the answers feed the agent's brainstorm. Nothing is stored beyond an optional cache of judgments.
- Dependencies: cross-field-trial, and only if its result shows that search alone is not enough.
- Boundary: in, the judging call, its prompt and its check, and the use of the answers by the agent. Out, stored threads and the
  weave as a graph, which `docs/specs/weave.md` builds only if this stage shows value and is too slow or too costly to run at the
  time of the query.
- Trigger: the trial's result says so and the owner asks for a plan.

## Deferred work

- Themes and the stored weave: built only if the trial and the judging of pairs show that the earlier stages are not enough
  (`docs/specs/theme.md`, `docs/specs/weave.md`).
- Shelves, filing by card, the crawler and the classification of sources: a different scope with its own finish line.
- A queue per model, so that a model is loaded once for many books: it speeds up `neutral-cards-for-the-library` and is not needed to
  start it.
- Choosing between models, escalation to a cloud model, quotas and budgets.
- Visibility to a guest and the security work that goes with it.

## Decisions

- [The knowledge base is a standalone package](../decisions/2026-11-04-knowledge-base-is-a-standalone-package.md)
