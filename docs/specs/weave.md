# Weave

Status: Draft

This specifies the weave, the exploratory layer that connects themes across the library so that an agent can find a combination of
ideas from unrelated fields that solves a problem none of them was written for. It belongs to the design in `knowledge-base.md` and
builds on the theme (`theme.md`), the card (`card.md`), the shelf (`shelf.md`) and the reading module (`reading.md`). **All of it is
exploratory, and nothing here is final.** The spec stays `Draft` until the owner approves it, and any statement can be reopened.
Each statement carries one of three marks:

- **[agreed]** The owner said it. It is the working position and it can still change.
- **[proposed]** The assistant's suggestion. The owner has not decided it.
- **[idea]** Exploratory. It is recorded so it is not lost, and it is not a requirement.

**This spec was revised after the first cross-field transfer experiment** (see "Evidence"). The experiment measured how far search over neutral descriptions gets on its own, before any weave exists. It does not decide how much of this spec is needed, and every statement below that is not marked [agreed] is still a hypothesis.

## Purpose

**[agreed]** Set by the decision `2026-11-11-the-library-equips-a-research-agent-to-extrapolate`; the points below are the owner's.

- The weave helps a research agent find novel, non-obvious concepts across fields. The agent, not the library, decides whether a find
  is worth pursuing, and the weave judges nothing for it.
- The aim is to extrapolate and not to interpolate. The agent's own knowledge is common, and the larger gap is seeing how ideas from
  separate fields fit together, and that a field outside its search parameters can shape a solution.
- The unit is one theme and a thread joins two themes. The owner's word *idea* means the same unit. The key ideas that cards hold
  today are the early, coarse form of themes (`knowledge-base.md`, "Vocabulary").
- The weave carries the agent from a theme a search found to distant themes it did not ask for. Its links must not be limited to
  strongly paired themes, or it becomes a search engine again. Weak and cross-field links are the point.
- The agent sets a weighting (narrow, medium, wide or similar, a short named scale; the default leans wide) and a distance (steps
  along threads, within the bounds the weighting sets). Noise is expected and accepted if each item is cheap to skim. The names and
  behaviour of the levels, how a level bounds the distance and what a step counts are open.

## Scope

A thread connects two themes, possibly from different shelves. The weave is the set of threads, with the ledger of pairs judged.
This spec covers the problem the weave is for, what a thread is, how candidate pairs are found and judged, how the graph is kept
sparse without losing novelty, where it is stored, how it is used at query time, how it is kept private and safe, and how it is
tested. It does not cover how themes are made or how the agent searches, which have their own specs.

## Non-goals

- **[agreed]** Verifying claims. A thread is a lead to follow, and a combination built from threads is a hypothesis.
- **[proposed]** A knowledge graph of facts. A thread says two ideas relate in a stated way, and carries a reason and a confidence.
  It does not assert that either idea is true.
- **[proposed]** Judging every pair. The space of pairs is far too large, so only candidates are judged.
- **[proposed]** Changing a book or a theme. The weave is derived and rebuildable.

## Assumptions and constraints

- Themes have a domain-neutral description with five parts: the problem it solves, the method in general terms, what it needs, what
  it provides, and where it would not work (`theme.md`).
- At the expected scale there may be millions of themes. On rough assumptions of 200,000 books, 2 MB each and 30 themes each, that is
  about 6 million themes, and an unconstrained graph would have tens to hundreds of millions of threads. A real disk-based vector
  index would be needed, and relevance scoring and duplicate detection would decide whether the result is useful. These figures are
  the assistant's assumptions, and the first extraction test suggests 30 themes per book may be high for short papers and low for
  long books.
- Judging a pair uses a model. The local model does the bulk, and the stronger class is used where it earns its cost (`models.md`).
- Threads and the ledger connect many books, so they live in the index root and are backed up with it (`library.md`).
- A thread with a private theme at either end is invisible to a guest (`shelf.md`).

## Behavior

### The problem

- **[idea]** Three unrelated shelves A, B and C, and a problem D with little relation to any of them, where a part from each,
  combined, gives a novel solution that would be very hard to find otherwise. The weave is meant to find that.
- **[proposed]** A sharper form of the same problem: a target problem stated in its own field's words, and a theme from a distant
  field that solved a structurally similar problem. Famous cases are simulated annealing from statistical physics, bandit methods
  into game search, and sequential testing from quality control into engine testing.
- **[proposed]** The previous standalone generator found little that was new, probably because it searched one domain at a time, its
  entries were answers and not leads, it was consulted only on request, and its library was thin. This is a guess, and it is why
  the weave looks across shelves.

### What a thread is

- **[idea]** A thread connects two themes. It holds: the two theme ids and the generation of each, a kind, a weight, a one-line
  reason that cites both themes' excerpts, a confidence, and a record of the model, prompt version and date that judged it.
- **[agreed]** A link made without a model judging the pair holds (the owner, 2026-11-13): its kind, the two themes, the structural
  closeness and the wording distance as numbers, which texts of the two themes matched and in which direction, and what lets the
  agent check it (the stated or inferred mark, the book's own words and the citation of each theme). It holds no model, prompt or date
  of judging, because none judged it. The library never drops a link because it looks weak or noisy to a reader, because what looks
  like noise to one search may be a find for another; the agent decides what is worth pursuing. The one rule that leaves a link out
  for its closeness is the floor of strength under "Keeping the graph sparse", which is the weave's own measure and no judgment of
  use.
- **[agreed]** The weaves are separate (the owner, 2026-11-13): each is a set of links of one kind, with a score that means one
  thing, rebuilt on its own. The kinds are *alike*, *same mechanism*, *same problem*, *fit together* and *builds on* (positive), and
  *incompatible* and *disagrees* (negative). *Same problem* is the owner's addition to the first six: the problem is close across
  fields and the method differs, so it shows how other fields solved the same problem, the mirror of *same mechanism*. The order of
  building, agreed with the owner's reading of the agent's table: *same mechanism*, *fit together*, *same problem*, then *alike*,
  which is kept as a reference for when the agent is in its home field and is not walked by default; *builds on* waits for reference
  data, and *incompatible* and *disagrees* wait for a model to judge each pair. Which of these the first plan builds is not decided.
  Whether weights are needed at all is open.
- **[idea]** What each kind is for. *Alike* (similar subject) maps the neighbourhood. *Same mechanism* (works the same way
  underneath, from a different field) is probably the main source of surprise. *Fit together* (one theme supplies what the other
  needs) is for combinations. *Builds on* (cites, extends or replaces) is the cheapest, because the citations come from the
  sources. *Incompatible* (assumptions clash) stops combinations that cannot work. *Disagrees* (contradicts) surfaces a tension as a
  lead and filters nothing out. *Same problem* (the problem is the same, the method differs) shows how else the problem has been
  solved.
- **[idea]** Combinations are never precomputed, because there are too many. Only themes and threads are prepared ahead, and a
  combination is composed at query time and cites every theme behind it.
- **[proposed]** *Fit together* and *builds on* are directional: the first theme provides what the second needs, or the second extends
  the first. The other kinds are symmetric.
- **[idea]** Novelty tends to sit on weaker, cross-shelf threads, so a search needs a setting for how far from the obvious to go.
- **[idea]** How the weaves might combine: look for themes far in topic but close in mechanism or fit, then drop the incompatible
  ones. Roughly the same-mechanism and fit-together scores, minus the alike score, minus incompatible. The hard weaves are same
  mechanism, fit together and incompatible, because they need the domain-neutral descriptions and recorded assumptions. A start, as
  the owner agreed on 2026-11-13: same mechanism, fit together and same problem, with alike as a reference, adding the rest once
  those produce something worth filtering.

### Staged build

- **[proposed]** The weave is built in stages, and each stage is built only if the evidence says the one before it is not enough.
  This holds for the stages in which a model judges pairs. It does not hold for stored links that no model judges, which are built
  as the next bullet says.
- **[agreed]** Links that no model judges are precomputed and stored (the owner, 2026-11-13), and are not made at the time of a
  search. A link depends on the two themes and not on any question. What depends on the agent's question, such as whether an
  ordinary search of it would have returned a theme, which links to follow, and the closeness of a theme to the question, is worked
  out at query time on top of the stored links. Stored links need no model call per pair, and a weave records the generation of
  each theme it processed, those left with no link included, so that it is rebuilt when the themes change and a theme the floor left
  with no link is not taken for one that is waiting.
- **[proposed]** *Stage 0, no weave.* The agent restates the problem abstractly, splits it into sub-problems, and searches the
  neutral descriptions of themes across all shelves for each (`reading.md`). The cross-field experiment measures how far this goes,
  including the composite problem where a theme from each of three shelves is needed.
- **[proposed]** *Stage 1, threads made at query time.* The agent or a model judges candidate pairs among the themes a search just
  retrieved, and uses the answers for the brainstorm report. Nothing is stored except an optional cache in the ledger. This tests whether
  judging pairs adds anything, without paying for a graph.
- **[proposed]** *Stage 2, stored threads that a model judged.* Threads are precomputed for the pairs most likely to matter and
  kept, with the ledger, so a search can follow them without judging again. It is built only if Stage 1 shows value and is too slow
  or too costly to run at query time. It is not the stored links of the agreed bullet above, which no model judges.
- **[proposed]** The decision between the stages is made on measures (see "Testing"), not on enthusiasm. This spec stays at the
  level of hypothesis until then.
- **[proposed]** The measures so far do not fit the purpose above. The cross-field experiments and the trial of cross-field search
  measured the retrieval of known transfers, the rank of a book the owner expected, and the rating of pairs by fit. None measured
  whether an agent extrapolates, so they do not show that Stage 0 is enough or that a stage above it is needed. Which stage to build
  is open until a measure for that exists, and a gate of the form "build the next stage only if search alone fails on retrieval" no
  longer stands.

### Finding candidate pairs

- **[proposed]** *Free threads first.* Some relations cost no model call. A resolved reference from one book to another gives a
  *builds on* thread. Shared authors, shared subject codes and "same work" notes give weak links (`book.md`). These are objective
  and are recorded as such.
- **[proposed]** *Neighbours in neutral space.* Candidates are the nearest neighbours of a theme in the embedding space of the
  neutral descriptions, taken across shelves and fields, and not only within the theme's own.
- **[idea]** *Provides and needs.* For *fit together*, the *provides* part of one theme is matched against the *needs* part of
  another, which needs those parts embedded separately. This is cheap and fits the five-part structure.
- **[agreed]** *Distance in field* is a wording distance and nothing stronger (the owner, 2026-11-13): the closeness of the summary
  vectors of the two themes, which are their own words, taken at the level of the theme and not of the book, so that a book on
  several topics does not blur them. It is carried on each link as a number and never as a pass or fail. It stands in for field and
  does not measure it, and it fails when a transfer borrowed the vocabulary of its home field. Where Wikipedia or arXiv categories
  exist they are shown beside it as evidence. The shelves' buckets are not used: every book is on the default shelf today.
- **[proposed]** Near-duplicates and themes of books marked as the same work are marked, so they do not create strong, useless *alike*
  threads (`theme.md`).

### Judging

- **[proposed]** A model is given two neutral descriptions and their excerpts, and returns a kind, a weight, a one-line reason that
  cites both excerpts, and a confidence. A reason that does not refer to both excerpts is rejected.
- **[proposed]** Judging is staged by cost. The local model does the first pass over candidates, and the stronger class judges the
  survivors, if the cross-field experiment shows that class earns its cost.
- **[proposed]** Judging is a pipeline stage like any other: queued, resumable, idempotent, and subject to the shelf budgets and the
  model quotas (`pipeline.md`, `models.md`). It runs at low priority, after cards and themes.
- **[proposed]** Priority goes to pairs with a large field distance, high-confidence themes, and themes from shelves the owner has
  given weight.

### Keeping the graph sparse without losing novelty

- **[idea]** Two protections for novelty. Sparsifying the graph must not keep only each theme's most similar neighbours, which are
  the obvious ones: each theme keeps a quota of neighbours from other shelves and fields as well, and low-weight threads are kept
  and not pruned.
- **[agreed]** The reachability rule (the owner, 2026-11-13). In this rule a *link* is the line between two themes (this spec's
  *thread*) and a *weave* is a set of links of one kind. **Cap, for every weave:** no theme keeps more than a set number of links
  in all; when a theme is full, the themes that wanted it choose their next candidate, so that the cap holds back the generic
  themes that a choice made for variety of distance piles links onto. A link is turned away because its theme is full and not
  because it is weak (the floor of strength below is a separate rule). **Floor on incoming links, for a directional weave only** (*fit together*, and *builds on* when it exists): a theme with fewer
  than a few incoming links is given some, chosen from the themes whose *provides* is closest to its *needs*. A symmetric weave
  needs no such floor, because its links can be followed both ways and a theme is reached by its own links. For a symmetric weave
  the cap is the slot rule below, which holds a theme to 12 links; the cap near 60 that the first measurement under "Evidence"
  suggested, for a choice made without slots, is not needed. The numbers for a directional weave are set in the plan.
- **[agreed]** The slot rule, which links a theme keeps (the owner, 2026-11-13). The links of a symmetric weave are two-way. Every
  pair of themes of different books falls in one of four bands of wording distance, the quarters of the summary closeness over all
  such pairs, and the edges of the bands are stored with the weave. Each theme has 3 slots in each band, so at most 12 links. A link
  takes one slot at each end, a theme links to at most one theme of one book in a band, and links are accepted from the strongest
  closeness of the weave's kind down (method closeness for *same mechanism*). When a theme's slots are full, the themes that wanted
  it take their next candidate. Slots for a directional weave are not decided.
- **[agreed]** A bound on the candidates (the owner, 2026-11-13, on the agent's recommendation): each theme puts forward only its closest 300 partners in each band,
  so that memory grows with the number of themes and not with its square. A theme whose candidates in a band are all taken, or all of books it already links to in
  that band, gets no further link there even if other partners are free. How often this changes a result is measured on the owner's library by building with and
  without the cut, and the rule without it (rounds of further candidates for themes with free slots) is brought to the owner only if the measurement shows real
  differences.
- **[proposed]** A pair whose wording closeness is exactly on an edge is in the band above it.
- **[proposed]** Built: `engine/.venv/bin/python -m kb theme-links build` makes the weave of *same mechanism* from the file of the theme vectors (read only; nothing is
  sent to any model) and puts `weave-same-mechanism.sqlite` in the index root, in a folder of its own under a lock, keeping the generation before; the file records every
  theme it processed with its number of links, those left with none included, and what it was made from. The closeness is an integer in billionths and the median and
  the edges are exact (`engine/kb/weave.py`; `engine/README.md`). Looking at the links of a theme, the repair of a weave and the batching are not built yet.
- **[agreed]** The floor of strength (the owner, 2026-11-13). A link is kept only if its closeness for the weave's kind is above the
  median closeness of all pairs of themes of different books, worked out for each weave. A pair no closer than a typical pair is not
  a link of that kind, so it is not stored, and a theme may keep fewer than 12 links, most of all in the wording-farthest band. It
  is the weave's own measure and not a judgment of whether a link is useful. The farthest band is to be checked for sparseness when
  a weave is built.
- **[idea]** The ledger records pairs judged unrelated as well as threads, so a pair is not paid for twice and can be judged again
  when the model or prompt improves.
- **[proposed]** There is a bound on the threads per theme, large and never expected to be reached, to catch a runaway. Reaching it
  marks the stage failed, as for themes. It is a different bound from the cap of the reachability rule above, which hub themes are
  expected to reach and which fails nothing.
- **[proposed]** A thread records the generation of each theme it judged. When a theme is regenerated, the thread is re-anchored by
  the excerpt hash and kept if the excerpt is found, and flagged if not (`theme.md`).

### Storage

- **[proposed]** The weave is derived and rebuildable, and the books are never touched. Threads and the ledger live in the index
  root and are backed up with it. They cannot be rebuilt from the book folders without paying for the judging again, so the staging
  copy of the index matters most for them (`library.md`, "Backup").
- **[proposed]** Threads are kept per generation of the weave, so a better prompt or model adds a generation and the old one can be
  compared and restored.
- **[agreed]** Adding books (the owner, 2026-11-13). A full rebuild and every old generation kept at each new book would cost too
  much over years of slow growth. New books wait in a list, and the weaves are repaired for the whole batch when the first of these
  happens: the new themes reach about 5 percent of the themes already linked, or 30 days have passed since the oldest unlinked book
  arrived, or the owner asks. A repair offers the candidate links of the new themes strongest first; a link takes a free slot, or
  replaces the weakest link of a full slot if it is stronger, and a theme that lost a link is refilled from its candidates. Each batch
  makes one generation, and one previous generation is kept. A book whose themes changed, or that was taken out, is treated as
  removed and added again (the owner, 2026-11-13): the links of its old themes are dropped, the themes that lost a link are refilled,
  and its new themes are added as new. A full rebuild is for a change of embedding model, dimension or prefix, for a change of more
  than about 5 percent of the themes in the weave at once (which is what a new theme generation of the whole library is), or on the
  owner's word. The walk says how many themes are not yet linked. The numbers are guesses to tune in the plan.

### Using the weave at query time

- **[idea]** For a problem like D the agent restates it abstractly, splits it into sub-problems, retrieves candidate themes from
  any shelf, follows threads from them, and proposes combinations that cite every theme used, marked as hypotheses. This may become a
  fourth section of the brainstorm report (`reading.md`).
- **[proposed]** An *incompatible* thread is used to warn: a combination that joins two themes with one carries that as a caveat.
  A *disagrees* thread is used the other way, to surface the tension as a lead, and it filters nothing out.
- **[idea]** An example from the original notes: an Othello evaluator might meet a scoring rule from another field, once both are
  described in domain-neutral terms.
- **[proposed]** A search has a setting for how far from the obvious to go, which raises the weight given to distant, weaker
  threads. The default is left to the builder and tuned on real use.
- **[agreed]** Whether a theme offered is one that an ordinary search of the agent's own question would also have returned is worked
  out when the agent asks, from its question, and is shown with each theme. It belongs to the walk and is not stored in a link, which
  is made before any question is known.
- **[proposed]** Every combination states which themes it uses, why they fit, what it assumes, and that it is a hypothesis for the
  owner to test. The agent never presents a combination as a finding.

### A digest of connections

- **[idea]** A digest would surface a few items with no question attached: a pair of themes from distant fields that look related, or
  new arrivals near what a project has worked on. The aim is to reach the owner without a prompt, since the previous generator was
  consulted only on request.
- **[idea]** It is not built unless the weave's pairs are shown to be useful. The condition is a trial in which the owner finds a
  clear share of proposed pairs interesting. Without that, a digest is random novelty and is likely to be ignored.
- **[idea]** The better-aimed version is the "what is new near my work" idea in `reading.md`, which uses cited sources and recent
  arrivals, could use the usage log, and needs no weave.

### Privacy and safety

- **[proposed]** A thread with a private theme at either end is invisible to a guest, and so are counts and hints derived from it
  (`shelf.md`).
- **[proposed]** Threads and cross-book links are computed and returned over the visible subset of the token, so a token never
  sees a thread, a count or a link that depends on a book it cannot see.
- **[proposed]** The judging model reads untrusted theme text. Its prompt tells it to judge the relation and to ignore instructions,
  it has no tools, and its output is validated for shape and length (`pipeline.md`, "Safety of captured content").
- **[proposed]** A thread is a lead. Its reason and confidence are the model's, and the excerpts are the source's own words, so the
  owner can check the relation against them.

## Testing

- **[proposed]** The measures that decide the stages: the rank of the source-domain theme for a target problem stated in its own
  words, at Stage 0 and at Stage 1; the share of judged pairs the owner finds useful; and, for the composite problem, whether
  sub-question searches surface a theme from each of the contributing shelves, with and without threads.
- **[proposed]** The standard test is the one in `testing.md`: a hand-made library with shelves A, B and C and a problem D whose
  combined solution is known. The cross-field transfer set, with documented transfers as ground truth, is the larger evaluation.
- **[proposed]** Used notes (`reading.md`) are evidence for the weave: a combination that a project used and cited is shown to the
  owner as evidence that it was relied on, not as a validated thread, and it does not rank threads automatically. The share of
  proposed combinations that get used is a measure of the weave's value that needs no model.
- **[proposed]** The owner's own judgment of whether a combination is novel is the final measure, and no automated measure replaces
  it.

## Evidence

- **[proposed]** A cross-field transfer experiment on 2026-11-01 (evidence note 10 in `knowledge-base.md`) tested Stage 0, search over
  neutral descriptions with no weave. Across 8 documented transfers on 124 papers and two embedding models, neutral descriptions
  found the source field better than summaries or raw text, and the card-level neutral description did as well as the theme-level
  one for choosing the paper. Three of 8 transfers were found at rank 1; two were weak in every variant.
- **[proposed]** The composite problem gives the most useful reading. The sequential-testing and bandit sub-questions reached their
  source shelves in every variant, so searching sub-questions separately works for them. The annealing sub-question reached the
  physics shelf in only 1 of 10 runs, because the target shelf already held the idea in its own words and outranked the source.
  Setting the target shelves aside brought the physics shelf to rank 1 to 11. So the main failure of Stage 0 is not that the
  source is absent, but that the home field's version hides it.
- **[proposed]** Two cheap fixes were tried in a follow-up on the saved embeddings, and neither gave a clear gain by the rule set in advance: a hub correction (it cut hub papers from 11 to 3 but did not raise ranking in the best variants) and a list of the best paper from each of the top five shelves (better than the plain top five in 3 to 5 of 10 cells, and worse for the neutral-description variants). A second follow-up tested the hypothesis that restating the problem in neutral language matches the neutral descriptions better than the raw query does. It did not: a restatement by a small local model ranked the source papers lower in all four neutral-description cells, and the raw query joined to the restatement did no better than the raw query alone (`knowledge-base.md`, Evidence note 12). A stronger model restating may do better, and that is untested.
- **[proposed]** A judging experiment on 2026-11-04 (evidence note 15 in `knowledge-base.md`) tested the two things Stage 1 needs.
  Candidates reach the judge: the best true source theme was in the top 100 for all 8 transfers using the best of four query
  forms, and in the top 30 for 4 of 8 using the whole problem alone. A local model can judge a pair: with only neutral
  descriptions, `gemma4:12b` (mean AUC 0.84) and `gpt-oss:20b` (0.90) scored true source themes well above lookalikes, and both
  passed the rules set in advance. The judges scored many other themes 8 or more, so one score is a coarse signal. The immune
  transfer was missed by `gemma4:12b` and found by `gpt-oss:20b`, so the model class matters.
- **[proposed]** What is still untested: whether judged pairs found on an unlabelled library are new or useful to the owner (model
  raters found few, and the owner has not rated the pairs alone), whether stored threads (Stage 2) beat searching and judging at query time,
  and how many transfers a library with far more variety would hide. The experiments so far do not justify building stored
  threads, and they do not show that the weave is unnecessary.
- **[proposed]** Blind discovery on the thin library (evidence note 16 in `knowledge-base.md`, 2026-11-04) did not show novelty.
  Two model raters (GPT-6.1 Sol with owner review, and Claude Opus blind) agreed on 39 of 40 pairs. Of the judge's 30 best
  pairs, 1 was rated useful and new, 25 to 26 known and 3 to 4 junk, and a control group of low-scored pairs did as well (1 of
  10 useful and new). By the rule set in advance this is a fail. The deviation is that the rule named the owner as the rater and
  models rated, so it is not the owner's verdict. The judge ranks by fit, which favours standard ideas. One of the two useful
  pairs (a security detector tested for observational identifiability, from an astronomy idea) was scored low by the judge. The
  result does not justify building stored threads, and it does not show that the weave cannot work. It was a thin library with no
  baseline of a model asked for cross-field ideas unaided. A retest needs a broader library, that baseline, and, if wanted, the
  owner's own rating.
- **[proposed]** The previous generator found little that was new; this experiment gives no evidence of novelty. A source paper at
  rank 1 shows retrieval, and only the owner can say that a connection is new or useful.
- **[idea]** Earlier throwaway experiments showed that neutral descriptions raised two foraging papers from 25th–34th by card to the
  top six on a whole problem, with no benefit within a single field.
- **[proposed]** How links fall on the themes, measured on 2026-11-13 (read only, no call to any model; Python 3.15.0, numpy 2.5.4;
  repository at `ff99750`) on the owner's local library, which is not in this repository: 1,805 themes with a summary and a method
  vector, in 173 books, for links of method closeness between themes of different books. Keeping each theme's 6 nearest left 228
  themes with no incoming link and 405 with one or two, and the top 5 percent of themes held 21 percent of the links (the
  most-linked theme had 67). Keeping 3 for each quarter of wording distance, at most one theme of a book in a quarter, left 186
  with none and 329 with one or two, and the top 5 percent held 35 percent (the most-linked theme had 328, and 50 themes had more
  than 60). Conclusion: a choice made for variety of distance piles links onto generic themes, so a cap is needed, and a floor
  matters where links are directional. One library and one weave: it is a measurement, not a limit.
- **[proposed]** Wording distance as a stand-in for field, tested on 2026-11-13 (read only, no call to any model; Python 3.15.0;
  repository at `ff99750`) on the owner's local library, which is not in this repository. The library held 176 books: 40 arXiv
  preprints (34 of them computer science) and 136 web pages, 128 of them English Wikipedia pages; every book was on the default
  shelf, and no book recorded a language. 127 of 128 stored Wikipedia pages still held their own list of categories (a median of
  12, some of them maintenance labels). On 12 pairs of books that the assistant judged to be in the same field and 12 in different
  fields (its own judgment, not the owner's), the closeness of the average summary vectors of the two books separated them perfectly
  (AUC 1.000, against 0.979 for the field-free description, 0.938 for the method and 0.931 for the provides). At the level of the
  theme, over every pair of themes of the two books, the summary separated them at 0.824 (the method at 0.675), and by the median of
  a pair of books at 0.986; the cosines are on a lower scale than between books, so no threshold carries over. One far pair,
  *Genetic algorithm* and *Natural selection*, came out as close as the near pairs because the book on the first is written in the
  second field's words. Conclusion: the summary closeness is a usable stand-in for how far apart two themes are in wording, not a measure of field,
  and it needs the number and the texts beside it.
- **[proposed]** The slot rule, the floor and adding books, measured on 2026-11-13 (read only, no call to any model; Python 3.15.0,
  numpy 2.5.4; repository at `b6ffb09`) on the owner's local library, which is not in this repository, for a same-mechanism weave
  over 1,805 themes with a summary and a method vector, in 173 books. The edges of the four bands were 0.316, 0.378 and 0.447.
  With 3 slots in each band and every candidate considered, there were 9,264 links, no theme was left with none and 4 with one to
  three, no theme had more than 12, and 391 themes (22 percent) had no link in the wording-farthest band. The median method
  closeness of all pairs of themes of different books was 0.490, and 1,298 of the 9,264 links (14 percent) were no closer than that,
  461 of 1,881 (25 percent) in the wording-farthest band. A full rebuild took about 1.0 second and a repair about 0.7 second. Taking
  17 of the 173 books out and putting them back, 70 percent of the old links were in the full rebuild and 77 percent in the repair,
  72 percent of the repair's links were in the rebuild, and the mean method closeness of a link was 0.618 for the repair against 0.624
  for the rebuild. Adding books together replaced these shares of the old links: 1 book 2.6 percent (227 links), 3 books 6.6
  percent, 9 books 13.7 percent, 17 books 22.8 percent, 35 books 37.6 percent (the average of 3 random samples), so a book costs
  227 replaced links alone and 74 in a batch of 35. Not tested: the drift over many repairs in a row, a directional weave, and
  whether links just above the median are useful.

## Acceptance criteria

All of these are provisional until the spec is approved and the experiment has reported.

- On a hand-made library with shelves A, B and C and a problem D whose combined solution is known, stored or query-time threads
  improve on the Stage 0 result for the composite problem: a theme from each shelf in fewer searches or at a better rank, or a
  combination that Stage 0 did not produce, with the passages cited.
- A combination is returned as a hypothesis that cites every theme used, and never as a finding.
- A thread's reason refers to both excerpts, and a thread with a private theme at either end is invisible to a guest.
- Stored threads record the generation of each theme and survive a reconversion by re-anchoring on the excerpt hash.
- Sparsifying keeps cross-shelf neighbours and low-weight threads, and does not keep only the most similar ones.
- A pair judged unrelated is recorded in the ledger and not judged again until the model or prompt changes.
- A runaway of threads for one theme marks the stage failed and keeps the output aside.
- The weave is rebuildable from the themes, and the books are untouched.

## Open questions

- The names and behaviour of the levels of the narrow-to-wide scale, which level is the default, how a level bounds the distance, and
  what a step is counted in (which kinds of thread).
- How to get themes: build them as `theme.md` designs them (an anchor and a neutral description each), or promote the key ideas of
  the cards, which today are plain text of at most 300 characters in the book's own terms with no neutral description of their own.
  Today the field-free fields are single strings on the book.
- How to tell whether the weave helps an agent extrapolate, since no measure of that exists yet.

- Which stage of the weave is needed at all, which the cross-field experiment decides.
- What a thread is, whether weights or several weaves are needed, and how the kinds combine.
- How much a stronger model improves judging and neutral descriptions, which the Haiku comparison in the experiment measures.
- The cost and the model class of pair judging, if the cross-field experiment shows the local model is not enough: a stronger
  class for every candidate, a stronger class for survivors only, or fewer candidates judged.
- The quota of cross-shelf neighbours, the bound on threads per theme, and the daily judging budget.
- Whether *provides* and *needs* should be embedded separately, and how well that finds fits.
- How the "how far from the obvious" setting is expressed to the agent and to the owner.
- How a combination is validated, if at all, beyond the owner's judgment.
- The scale of the real graph, since the figures above are assumptions.

## Governing decisions and references

- Decisions: none recorded in this repository yet.
- References: none.
- The design this belongs to is `knowledge-base.md`. The related specs are `theme.md`, `card.md`, `shelf.md`, `reading.md`,
  `pipeline.md`, `models.md`, `library.md`, `book.md` and `testing.md`.
