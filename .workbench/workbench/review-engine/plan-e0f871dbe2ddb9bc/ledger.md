# Review of docs/plans/2026-11-08-cards-for-the-library-one-model-at-a-time.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 3
- Closed: no

## Rounds

- Round 1, 2026-11-08T20:25:30Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-08T20:26:16Z: Correct: running another model does not prove the tested one was unloaded. The measurement now unloads the model on purpose, uses the room, waits, and judges the cold state by the times, leaving ou...
- R1-F2: applied on 2026-11-08T20:26:16Z: A registry entry is used by every command, so the option would have changed ordinary cards calls. Keep-alive is now an argument of one call and a config setting that only queue runs read, with a te...
- R1-F3: applied on 2026-11-08T20:26:16Z: Two entries may name the same server and model and share one loaded model. The queue now groups by the physical pair and keeps each call own entry options, with tests for both cases.
