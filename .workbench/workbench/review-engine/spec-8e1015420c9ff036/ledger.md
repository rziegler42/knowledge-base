# Review of docs/specs/theme-walk.md

This file is a rendering of state.json for people. It is never read back.

- Kind: spec
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 6
- Closed: no

## Rounds

- Round 1, 2026-11-14T00:10:07Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-luna
- Round 2, 2026-11-14T00:12:54Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-luna

## Decisions

- R1-F1: applied on 2026-11-14T00:10:47Z: A REF names a theme and not a route, so the spec now says the agent passes back the themes of the route it has seen in --seen, the command only guarantees that a route never visits a theme twice an...
- R1-F2: applied on 2026-11-14T00:10:47Z: The engine has no guests or tokens yet, but the weave spec requires counts and links over the visible subset; the walk spec now takes the visible set as an input to the selection, computes every co...
- R1-F3: applied on 2026-11-14T00:10:47Z: The roadmap finish line for the trial is the share of offered themes an ordinary search already returned at each setting and distance; the trial criterion now requires that figure for every level a...
- R1-F4: applied on 2026-11-14T00:10:47Z: The best route of a theme now has a final tie-break, the smallest sequence of the theme REFs compared as text, so the choice does not depend on the order in which routes are found.
- R2-F1: applied on 2026-11-14T00:13:14Z: The embedding configuration is now a deterministic input: criterion 3 names the model and query prefix, the command refuses a vectors file or a reply from another model before any lead is made as t...
- R2-F2: applied on 2026-11-14T00:13:14Z: The limit is now a whole number from 1 to 20 and a value outside it is refused, so the lane shares and the held-back counts describe the real result and the format cap is not a hidden second limit.
