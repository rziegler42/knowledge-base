# Review of docs/plans/2026-11-14-measure-the-shelf-matcher.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 3
- Closed: no

## Rounds

- Round 1, 2026-11-14T19:13:49Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 2, 2026-11-14T19:16:27Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-14T19:14:24Z: The bar and the figures meant different things. The plan now ranks only the home shelves, defines top-1, top-5, the rolled-up hit and the candidate recall, keeps the level rankings as information, ...
- R1-F2: applied on 2026-11-14T19:14:25Z: Increment D now delimits the work text as untrusted quoted data, tells the model to ignore instructions in it, accepts only one strict answer form, and tests the reader with a fake model and a chec...
- R2-F1: applied on 2026-11-14T19:16:38Z: A steered answer can have the valid form, so the form check proved nothing about steering. The plan now says the reader is no defence, and measures steering with five paired works, a plain control ...
