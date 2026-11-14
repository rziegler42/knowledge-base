# Review of docs/decisions/2026-11-14-the-shelf-schema-is-our-own-list-from-openalex-and-lcc.md

This file is a rendering of state.json for people. It is never read back.

- Kind: adr
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-14T16:21:25Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 2, 2026-11-14T16:24:07Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 3, 2026-11-14T16:25:30Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-14T16:22:03Z: Real contradiction. The record now says every OpenAlex topic is in the file from the start, so drill-down activates an existing shelf and adds nothing to the file; only a topic OpenAlex lacks, a cu...
- R1-F2: applied on 2026-11-14T16:22:03Z: Fair. Keeping state and priority in library data is my refinement of the owner decision that every shelf has a flag and a priority. The record now says so, names the library data as the authoritati...
- R2-F1: applied on 2026-11-14T16:24:22Z: Correct. The record now takes the home shelf from the topic OpenAlex names as primary, makes the other recorded topics the secondary labels in OpenAlex order, sends a work with no primary topic or ...
- R3-F1: applied on 2026-11-14T16:26:00Z: Correct, and it was my own overstatement. The trial gave thin leads for one problem and an unclear result, and did not establish whether coverage or method was the cause. The Context and the Eviden...
