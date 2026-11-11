# The library equips a research agent to find non-obvious ideas across fields

Status: Accepted by Robert Ziegler <25854477+rziegler42@users.noreply.github.com> on 2026-11-11

## Context

The knowledge base is a personal library that agents read. Its overview (`docs/specs/knowledge-base.md`) states the intent as bringing
in "ideas, patterns and facts that are not obvious" and following them into new concepts, and it says the design errs toward finding
novel concepts. In the work since, the finish lines and measures narrowed to retrieval: the roadmap `cross-field-discovery` set as its
finish line sources from other fields that suit a problem, compared with keyword search; the trial of cross-field search measured the
rank of books the owner expected; and the pair-judging stage and the weave were made to depend on that trial showing that search alone
is not enough. A conversation with the owner on 2026-11-11 found that this is not the goal, and that the work had lost sight of it.
What the owner said in that conversation is the basis of this record.

## Decision

1. **The purpose.** The library supports research across many, possibly unrelated, fields, in order to find novel concepts that are not
   obvious. It is more than a search engine.
2. **The reader.** The reader is mostly a research agent working for the owner, and sometimes the owner. The agent, not the library or
   its builders, decides whether a concept it finds is worth pursuing. The library does not judge novelty.
3. **The gap it fills.** The agent's own knowledge is common, and a deep dive into a topic only interpolates between known solutions.
   The owner's judgment is that the larger gap is not missing knowledge but not seeing how ideas from separate fields fit together, and
   not realising that a field outside its search parameters can shape a solution in a new way. The aim is to extrapolate, not to
   interpolate.
4. **The unit.** The unit offered to the agent is one theme, as `docs/specs/theme.md` defines it: idea-level, with an anchor to an
   excerpt and a neutral description of its own. The key ideas already taken from the books and kept on the cards are the early,
   coarse form of themes. A thread of the weave joins themes.
5. **Distant material is offered.** The library offers distant material the agent did not ask for, as well as answering what it asks.
6. **Two settings, chosen by the agent.** A weighting from narrow to wide, given as a short named scale (not a number): narrow behaves
   like an ordinary search engine, wide casts a net over a large range of non-obvious topics, and with no weighting given the default
   leans wide because that is the purpose and narrow search is already provided by other tools. And a distance: how many steps to
   travel along threads from the themes a search found, within the bounds the weighting sets.
   **Left open, not decided here:** the names of the levels and how many there are, what each level does in observable terms, how a
   level bounds the distance, which level the default is, and what a distance counts (steps along which kinds of thread). They are
   settled in the weave spec and in the plan that builds the walk, and a plan that builds it needs them written down first.
7. **Noise is expected.** Most of what is offered will be irrelevant and that is accepted, provided each item is cheap for the agent to
   skim. The aim is needles in a haystack. A novel concept would not be novel if it were obvious.
8. **The weave serves this.** The weave is meant to help the agent reach distant themes. Links must not be limited to strongly paired
   themes, or the library becomes a search engine again.

## Alternatives considered

- **Keep the retrieval aim** (return sources that fit the problem, measured by the rank of known books). Rejected: it finds what the
  agent could already ask for, and the home field's own version of an idea tends to hide the one from another field.
- **The library judges which finds are novel or worth pursuing.** Rejected by the owner: that is the research agent's decision.
- **A fixed minimum share of offered themes from outside the problem's field.** Put forward by the assistant and set aside by the owner in
  favour of the weighting in point 6. It is not part of this decision.
- **A numeric weighting.** Not chosen; a short named scale is enough, and what each level means can be tuned later.
- **Strongly paired links only.** Rejected by the owner as the way back to a simple search engine.

## Consequences

- Specs and roadmaps that state the purpose as retrieval, or that gate the weave on a retrieval measure, no longer match. The overview,
  the weave, the reading and the testing specs, and the roadmap `cross-field-discovery` (archived) are affected, and so is the word list
  in the overview that avoids the word *idea* (the owner's *idea* means a theme). Changing a spec's direction or a roadmap is the owner's act and is not done by this
  record.
- Success cannot be measured by finding a known transfer. How to measure whether the library helps an agent extrapolate is open. One
  idea, not decided: the share of offered themes that a plain search of the agent's own question would already have returned.
- Much of the built work stays as foundation (capture, scan, conversion, cards with marks of what a book states and what a model
  infers, the model calls). What is missing for this purpose includes a field-free description for each theme (today the field-free
  fields are single strings on the book), vectors for themes, and links between themes.
- Nothing in the library is verified by this record. A find is a lead for the agent to follow, as before.
- The library's variety of fields remains a limit that no setting removes.

## Evidence

- The owner's statements in a conversation with the assistant on 2026-11-11, summarised above.
- What was read, at commit `0bc4acd`: `docs/specs/knowledge-base.md` (intent, success test, guiding principle, vocabulary),
  `docs/specs/weave.md`, `docs/specs/reading.md`, `docs/roadmaps/cross-field-discovery.md`, the Result of
  `docs/plans/2026-11-10-trial-of-cross-field-search.md` (search alone found the expected book at 5 or better in 9 of 10 problems; the
  blind agents named the answer in several; novelty was not measured), and `engine/kb/card.py` and `engine/kb/vectors.py` (the
  field-free fields are strings on the book, key ideas are plain text of at most 300 characters, and the embedded fields are the
  neutral problem, approach and provides).
- **Provenance of the reading.** Done on 2026-11-11 at commit `0bc4acd` of this repository, by reading the files named above with the
  file-read and text-search tools of the agent session, and by looking in `engine/kb/card.py` and `engine/kb/vectors.py` for the card
  and embedded field names. No program of this project and no model was run, so no tool version applies beyond the commit. Conclusion:
  the written intent already named the aim in point 1, and the finish lines, the trial and the gate on the weave were stated in terms of
  retrieval of fitting books (a mismatch of the records, not a finding about the code); and the field-free description is held once for
  a book and not for each key idea, which a walk between themes would need.
- No experiment was run for this record. It states a purpose, and the evidence for or against the design that follows from it is not
  yet gathered.

## Note, 2026-11-11

Made the same day, on the owner's word and before any work was built on this record: the unit is called the **theme**, not the
*idea*. The owner said *idea* and meant the same unit as a theme, and chose one unit under one name. Points 4, 6 and 8 and the
consequences were reworded in place for that, and nothing else in the decision changed. The reasons for the name are in
`docs/specs/knowledge-base.md`, "Vocabulary". The text was changed after it was accepted; the text accepted had the hash
`7f3a7e762a7a2d02e016229861783dd4f78a50e28a793f0489dffd112ec7cd59`, and the text with this note has another.
