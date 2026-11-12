# Review of docs/plans/2026-11-12-search-the-themes-by-meaning.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 5
- Closed: no

## Rounds

- Round 1, 2026-11-12T15:16:52Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-terra
- Round 2, 2026-11-12T15:19:03Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 3, 2026-11-12T15:19:56Z: the reviewer said no_meaningful_changes, the engine read no_meaningful_changes, 0 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-12T15:18:03Z: The plan now embeds the summary, the whole neutral description and all five parts, since the agreed rule is to drop an embedding only on a test, and Increment C looks at what dropping the needs, li...
- R1-F2: applied on 2026-11-12T15:18:03Z: The citation now carries a language line, which says not recorded because neither a card nor a theme records the language today; recording it in the card is listed as deferred and the gap is to be ...
- R1-F3: applied on 2026-11-12T15:18:04Z: The build now reads only the list of active books and, for each, its card and its themes, with a test that no other file of a book is opened, and says how a missing card or theme is counted
- R1-F4: applied on 2026-11-12T15:18:04Z: The plan now separates the two behaviours: a build makes every vector and replaces an unusable or mismatched file only when whole, and a search refuses such a file
- R2-F1: applied on 2026-11-12T15:19:38Z: The file now stores the theme id, the book and version and the whole anchor with its excerpt hash, the search returns them, and the tests include a row whose anchor is malformed
