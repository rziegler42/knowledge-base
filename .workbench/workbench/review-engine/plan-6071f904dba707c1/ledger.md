# Review of docs/plans/2026-11-07-card-stage.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 1 of 3 rounds (ceiling 5)
- Rounds in all: 1
- Decisions recorded: 5
- Closed: no

## Rounds

- Round 1, 2026-11-07T16:47:41Z: the reviewer said changes_needed, the engine read changes_needed, 5 findings, model gpt-5.6-terra

## Decisions

- R1-F1: rejected on 2026-11-07T16:48:53Z: The owner asked on the same day that each type of task have its model set in the config, and the roadmap lists the choice as deferred work, not as barred; the plan records the difference and leaves...
- R1-F2: applied on 2026-11-07T16:48:53Z: The owner chose cards by command for now; the plan now states the difference from the spec, lists filing-time cards as deferred, and leaves any spec change to the owner.
- R1-F3: applied on 2026-11-07T16:48:53Z: The title, outline and notes are also untrusted inputs to the card job, so each now gets a labelled section with a per-call token, and the tests use hostile versions of each.
- R1-F4: applied on 2026-11-07T16:48:54Z: Checked the card spec: English output and a size cutoff set by a setting are agreed behaviors, so the prompt asks for English and a cutoff setting sends small items to a card with no model call.
- R1-F5: applied on 2026-11-07T16:48:54Z: A command line option naming a registry entry goes against the spec and against the per task settings, so it is removed and the owner edits the task setting instead.
