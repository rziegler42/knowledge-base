# Review of docs/plans/2026-11-16-show-the-state-and-the-report-of-the-unattended-crawl.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 2 of 3 rounds (ceiling 5)
- Rounds in all: 2
- Decisions recorded: 4
- Closed: no

## Rounds

- Round 1, 2026-11-16T21:26:08Z: the reviewer said changes_needed, the engine read changes_needed, 3 findings, model gpt-5.6-terra
- Round 2, 2026-11-16T21:40:25Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra

## Decisions

- R1-F1: applied on 2026-11-16T21:27:56Z: The plan did contradict itself on printed credentials. Added a named redaction rule before cleaning, tests that plant each case, and a plain statement that it is a safeguard and not a guarantee.
- R1-F2: applied on 2026-11-16T21:27:57Z: Checked the URLhaus module on main: its state is a separate file the list reader would miss. Added it to the status contract, its fixtures and tests, reading counts and times only and never a URL o...
- R1-F3: applied on 2026-11-16T21:27:57Z: The read-only promise and the accepted side files conflicted. Narrowed the criterion to name exactly the two SQLite side files, added a first measuring step on this machine, and ruled out the immut...
- R2-F1: applied on 2026-11-16T21:40:48Z: The plan gave two opposite orders for redaction and cleaning, which let a header split by a hidden character through. Fixed to normalise, redact, then cut, with tests for split names, a cut inside ...
