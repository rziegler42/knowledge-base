# Review of docs/plans/2026-11-13-link-themes-that-work-the-same-way.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 4 of 4 rounds (ceiling 5)
- Rounds in all: 4
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-13T15:20:24Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 2, 2026-11-13T15:26:05Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 3, 2026-11-13T15:27:04Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol
- Round 4, 2026-11-13T15:32:02Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-13T15:20:58Z: Repair is now only for themes added to an otherwise unchanged set: status says a full build is needed and repair refuses, even when told to go on, if a linked theme changed or went or the vectors m...
- R2-F1: applied on 2026-11-13T15:26:23Z: The median and the three band edges are now exact order statistics found in bounded memory by two passes, not a histogram estimate; a pair exactly at the median is not linked; the tests compare wit...
- R3-F1: applied on 2026-11-13T15:27:29Z: The exact selection no longer collects the values of a bin: the closeness is an integer in billionths and a radix selection over the blocks pins the rank in at most two passes with memory fixed by ...
- R4-F1: applied on 2026-11-13T15:32:30Z: The weave now records every theme it processed, with its generation and hashes and its number of links, those with none included; unlinked means not processed, themes with no link are counted separ...
