# Review of docs/plans/2026-11-19-lengthen-the-idle-window-once-the-days-fetches-are-used-up.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 3
- Closed: no

## Rounds

- Round 1, 2026-11-19T23:56:17Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 2, 2026-11-19T23:57:53Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 3, 2026-11-19T23:58:33Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-19T23:56:34Z: The start of the next run belongs to the loop or the scheduler. The plan now promises only that the window ends at the day end, says so in the goal and the non-goals, and the acceptance reads the l...
- R2-F1: applied on 2026-11-19T23:58:04Z: Checked: a closed sqlite connection raises ProgrammingError, not KbError. The boundary is now KbError or sqlite3.Error for the short window and anything else propagates, with tests for a closed, a ...
- R3-F1: applied on 2026-11-19T23:58:46Z: The end of the day is a cooperative deadline like the others of the window: no new call starts after it and a call in flight may finish. The goal, criteria 4 and 6 and the acceptance say so, and a ...
