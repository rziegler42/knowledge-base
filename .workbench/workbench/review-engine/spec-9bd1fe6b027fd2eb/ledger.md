# Review of docs/specs/population.md

This file is a rendering of state.json for people. It is never read back.

- Kind: spec
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-16T16:54:52Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-luna

## Decisions

- R1-F1: applied on 2026-11-16T16:55:53Z: The existing capture code already connects to the address it validated and the threat review tested that, but the spec did not require it of the new shared client. I wrote it in: resolve once, chec...
- R1-F2: applied on 2026-11-16T16:55:53Z: Correct: I had left a choice open. The spec now fixes a resident-memory limit with a kill by the watchdog, a smaller PDF size than arXiv allows, a size limit on converted text, process-count and de...
- R1-F3: applied on 2026-11-16T16:55:53Z: Right about the shipped default: sources with unresolved or restrictive terms are now off in the default plan and the owner preview names each one that is on and says its terms are the owner to hav...
- R1-F4: applied on 2026-11-16T16:55:54Z: Right, and it matters for two unattended weeks: a later pull, merge or model change could alter behaviour under an old sign-off. The spec now binds the sign-off to a fingerprint of the engine modul...
