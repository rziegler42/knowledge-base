# Review of docs/plans/2026-11-19-fetch-arxiv-papers-in-the-unattended-crawl.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 5
- Closed: no

## Rounds

- Round 1, 2026-11-19T14:52:05Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 2, 2026-11-19T14:54:21Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 3, 2026-11-19T14:55:24Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-19T14:52:34Z: Only a book of the owner blocks a fetch before the request; the crawl own books go to the capture. The assumption, criterion 4 and the test list now say so, with the abstract page and the orphan ca...
- R1-F2: applied on 2026-11-19T14:52:34Z: The id is read as everything after the abs or pdf segment so legacy ids with a slash work; step 3 and the tests now list legacy and versioned forms and the refusals.
- R2-F1: applied on 2026-11-19T14:54:58Z: The id is now read with the existing webaddr identity key function, which knows the three arXiv hosts, legacy ids, versions and a final pdf, so no second parser is written; the tests cover each host.
- R2-F2: applied on 2026-11-19T14:54:58Z: Chose the narrow rule: only a candidate of the arxiv source without a paper address is rejected; another source at a non-paper arXiv address stays with the page capture. Step 4 and test h say so.
- R3-F1: applied on 2026-11-19T14:55:41Z: Checked on the real function: identity key drops the version. The plan now says the crawl always takes the latest version, test c expects the id without the version, and keeping a named version is ...
