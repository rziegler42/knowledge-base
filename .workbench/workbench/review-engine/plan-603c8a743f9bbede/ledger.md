# Review of docs/plans/2026-11-19-load-pdf-files-from-a-folder-into-the-library.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 5
- Closed: no

## Rounds

- Round 1, 2026-11-19T17:25:01Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-5.6-terra
- Round 2, 2026-11-19T17:27:29Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-5.6-terra
- Round 3, 2026-11-19T17:29:01Z: the reviewer said changes_needed, the engine read changes_needed, 2 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-19T17:25:35Z: The index already claims a key atomically  first register wins , so the plan now claims the hash before the book, takes over a stale entry, finishes an unfinished book, and holds a lock for the run...
- R2-F1: applied on 2026-11-19T17:28:26Z: The lock cannot cover the crawl capture, so the book is now made live before the hash is claimed and the crawl capture answers held for it; the small remaining window is stated, with a todo, and an...
- R2-F2: applied on 2026-11-19T17:28:26Z: One cleaned, length-bounded form of the file name is used for the title, the stored source and every printed line; the raw name is stored nowhere; tests for control, bidi, zero-width, newline and l...
- R3-F1: applied on 2026-11-19T17:29:25Z: Checked: the helper only asks whether a book exists, so a weeded holder would pass as live. The plan now treats only an active book as a holder, takes over any other, and tests a failure followed b...
- R3-F2: applied on 2026-11-19T17:29:25Z: The residue against a crawl capture already in flight is real and cannot be removed without changing the crawl capture; the plan now states it in full, asks for the load to run with the stop file i...
