# Review of docs/plans/2026-11-07-card-live-run-fixes.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 3
- Closed: no

## Rounds

- Round 1, 2026-11-07T19:25:27Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-07T19:26:06Z: Checked the runner: it builds a new failed report from the exception text, so a typed refusal that carries the file name and a report field are now required and tested.
- R1-F2: applied on 2026-11-07T19:26:06Z: A repeated name would lose the new answer under an exclusive create, so the name gets a random suffix, a clash is met with a new one, and a test forces the clash.
- R1-F3: applied on 2026-11-07T19:26:07Z: The plan promised no link is followed but only checked the folder before creating by path, so the write now uses descriptors with no-follow opens, a directory check and an exclusive create relative...
