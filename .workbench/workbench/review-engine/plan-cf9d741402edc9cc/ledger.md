# Review of docs/plans/2026-11-07-card-catalog.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 2
- Closed: no

## Rounds

- Round 1, 2026-11-07T20:20:09Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-07T20:20:56Z: Checked the read and card code: a read adds the PDF address of an arXiv paper and a card keeps none, so the contract now allows exactly that difference and is tested for a web page and for an arXiv...
- R1-F2: applied on 2026-11-07T20:20:57Z: The roadmap outcome is that a result gives the card, so the catalog stores the whole card and each result carries its rendered text between the markers, checked on use, with a test against what car...
