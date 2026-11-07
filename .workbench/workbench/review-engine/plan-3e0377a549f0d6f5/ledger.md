# Review of docs/plans/2026-11-07-card-trial.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 3
- Closed: no

## Rounds

- Round 1, 2026-11-07T21:50:52Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-07T21:51:43Z: A missing card would have been counted as a card search that missed, so uncovered right books are now listed and left out of the card measures, and every right book must be carded before the run.
- R1-F2: applied on 2026-11-07T21:51:43Z: The measures were undefined for a question with several queries, so the plan now fixes the union, the best place, the pair as the unit and every formula, and the tests use a hand-worked corpus.
- R1-F3: applied on 2026-11-07T21:51:44Z: The report did not say which cards and which catalog gave the result, so it now holds an input manifest with hashes and the command refuses a catalog that is not the one the cards make.
