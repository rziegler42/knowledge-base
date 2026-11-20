# Review of docs/plans/2026-11-20-make-the-locators-of-the-helper-safe-to-copy-into-a-single-quoted-command.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-20T18:00:02Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 2, 2026-11-20T18:02:11Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 3, 2026-11-20T18:03:09Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-20T18:00:37Z: Right: a title or excerpt may hold the text backslash-u, which JSON writes with a doubled backslash, so a rule for the whole reply cannot hold. The guarantee now covers the locators only, where tex...
- R2-F1: applied on 2026-11-20T18:02:36Z: Partly right. I read both specs: neither says anything about escaping apostrophes, so nothing in them contradicts the plan. But they also say nothing about the form of a locator, which will be true...
- R3-F1: applied on 2026-11-20T18:03:28Z: Right: the plan encoded the locators before hiding paths, so a known path with an apostrophe or a percent sign would no longer match the redaction and could leak. The order is now: hide paths in th...
- R3-F2: applied on 2026-11-20T18:03:28Z: Right: a heading that holds the text percent-27 must come back as exactly that after decoding, so the criterion now says the locator the engine gets equals the one it gave, with no claim that it ha...
