# Review of docs/plans/2026-11-18-fix-arxiv-queries-and-use-an-openalex-key.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-18T14:36:08Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra
- Round 2, 2026-11-18T14:38:30Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-18T14:37:02Z: The listed deliberate changes were meant as mutations to check the tests, but the wording read as behaviour. Reworded step 3 to say they make the forbidden behaviour on purpose and that the table i...
- R1-F2: applied on 2026-11-18T14:37:02Z: Named every reason value from the errors page and gave each its duration, with a fixture for each row. Kept one departure from the suggestion: a 429 that is a valid object with no reason is a refil...
- R1-F3: applied on 2026-11-18T14:37:02Z: Fetched the authentication and errors pages again, recorded their addresses, the date and the hash of the bytes, and tied the reason table to a text search of them. Stated that no real API answer e...
- R2-F1: applied on 2026-11-18T14:38:55Z: Agreed: the project asks the owner before a security review and runs it only on request. Reworded the key increment to name the exposure, ask, and record either the review or the owner decision, an...
