# Review of docs/plans/2026-11-11-stop-the-launcher-when-the-engine-is-killed.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-11T13:06:23Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 2, 2026-11-11T13:08:36Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 3, 2026-11-11T13:09:38Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-11T13:06:43Z: Real gap: the launcher runs before the watchdog is ready, as with the converter. Narrowed the guarantee to start at the ready word, started the watchdog right after the launcher, and listed the win...
- R2-F1: applied on 2026-11-11T13:08:47Z: Fair: the start failure and the missing ready word are two code paths. Split into two tests, and criterion 3 now names both.
- R2-F2: applied on 2026-11-11T13:08:47Z: Fair: a short call limit would let the call stop first. The hand check now sets the call limit above the helper time and confirms the helper timed out before looking.
- R3-F1: applied on 2026-11-11T13:10:03Z: Correct: the launcher is reaped before done is sent, in the converter and here, so the ordering claim was false. The plan now records the remaining race as a risk, sends done first in the cleanup, ...
