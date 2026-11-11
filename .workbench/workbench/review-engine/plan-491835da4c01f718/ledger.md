# Review of docs/plans/2026-11-11-make-the-theme-the-unit-of-the-weave.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 8
- Closed: no

## Rounds

- Round 1, 2026-11-11T15:05:14Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-terra
- Round 2, 2026-11-11T15:08:22Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-11T15:06:08Z: Fair: the plan left the schema to a draft spec. Added a table of fields with types, limits and the five type values, and Increment A now tests every row.
- R1-F2: applied on 2026-11-11T15:06:08Z: Fair: no source of field vocabulary was named. It is now derived from the title, the card topics and the words frequent in the book and rare in the library, flagged and kept, and read in the trial.
- R1-F3: applied on 2026-11-11T15:06:08Z: Correct: theme.md says themes follow the card. A current card is now required for extraction and for the run, and cardless books are listed with that reason.
- R1-F4: applied on 2026-11-11T15:06:09Z: Fair: the active generation was undefined. It is the newest valid one, as for cards, readable by number, and the run resumes on prompt version and models. Restoring an earlier one is deferred and t...
- R2-F1: applied on 2026-11-11T15:09:23Z: Fair: the anchor lacked an end and a hash of the whole excerpt. The table now holds start and end locators, the heading path and the full excerpt hash with a size bound, and Increment B tests re-an...
- R2-F2: applied on 2026-11-11T15:09:24Z: Fair: the vocabulary rule was left to the implementation. The plan now defines tokenization, the corpus, the common-word rule, the thresholds and the sources, with a four-book fixture asserting the...
- R2-F3: applied on 2026-11-11T15:09:24Z: Partly: the engine has no pointer-only books and no code to make them, so there is nothing to extract from. The plan states that limit, lists books without a conversion in the run report with that ...
- R2-F4: applied on 2026-11-11T15:09:24Z: Fair: the failed-check outcome contradicted the schema. A part that is not fully supported is kept and marked inferred, and a theme whose check gives no valid answer is dropped with the reason unch...
