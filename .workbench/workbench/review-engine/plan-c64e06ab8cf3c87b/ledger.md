# Review of docs/plans/2026-11-08-card-lists-that-follow-the-book.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 8
- Closed: no

## Rounds

- Round 1, 2026-11-08T17:48:44Z: the reviewer said changes_needed, the engine read changes_needed, 5 findings, model gpt-5.6-terra
- Round 2, 2026-11-08T17:51:49Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-08T17:49:43Z: The goal promised help for any list that lost most items but only key ideas had such a trigger. The triggers now cover topics and key ideas alike, with a measurable loss rule and a test for each.
- R1-F2: applied on 2026-11-08T17:49:44Z: The round now says it adds stated items only and asks for no inferred one. That is a deliberate choice, given the weak record of inferred items, and the card spec update in increment A states it. T...
- R1-F3: applied on 2026-11-08T17:49:44Z: The comparison now uses matched generations that each change one thing: baseline, round, coverage and both, plus a repeat of the baseline for the size of an ordinary difference. Each recommendation...
- R1-F4: applied on 2026-11-08T17:49:44Z: Correct: card-level counts cannot recover which items the round added. The generation record now names them, in a format 2 card only, and the sampling tool and its tests are in increment A. The non...
- R1-F5: applied on 2026-11-08T17:49:45Z: The comparison now tests reading every piece of long books against the current cap, and the default cap stays twelve in this plan. Raising the default waits for the recorded result and the owner de...
- R2-F1: applied on 2026-11-08T17:52:08Z: One repeat on one book could not set the margin for the other books. The baseline is now made twice for every book and each decision uses the margin of the matched books.
- R2-F2: applied on 2026-11-08T17:52:09Z: The roadmap candidate asks for the strong-model labels to be checked against a subset the owner labels. The plan now requires at least ten owner-labelled items and their agreement before the cloud ...
- R2-F3: applied on 2026-11-08T17:52:09Z: The third trigger is for key ideas only. The test obligation now says so and adds a test that it starts no round for topics.
