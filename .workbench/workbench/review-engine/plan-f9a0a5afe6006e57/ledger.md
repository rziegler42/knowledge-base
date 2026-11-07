# Review of docs/plans/2026-11-07-card-grounding.md

This file is a rendering of state.json for people. It is never read back.

- Kind: plan
- Rounds in this window: 3 of 3 rounds (ceiling 5)
- Rounds in all: 3
- Decisions recorded: 10
- Closed: no

## Rounds

- Round 1, 2026-11-07T23:26:40Z: the reviewer said changes_needed, the engine read changes_needed, 5 findings, model gpt-5.6-terra
- Round 2, 2026-11-07T23:30:46Z: the reviewer said changes_needed, the engine read changes_needed, 4 findings, model gpt-5.6-terra
- Round 3, 2026-11-07T23:34:19Z: the reviewer said changes_needed, the engine read changes_needed, 1 findings, model gpt-6.1-sol

## Decisions

- R1-F1: applied on 2026-11-07T23:28:55Z: The roadmap candidate now allows a cloud model to label the sample and keeps it out as a card writer or checker; the plan non-goals say the same.
- R1-F2: applied on 2026-11-07T23:28:56Z: With the owner word, the candidate outcome and boundary now say a strong model labels the sample and the owner labels a calibration subset, matching the plan.
- R1-F3: applied on 2026-11-07T23:28:56Z: The second trial needs new questions and more books, so it moved out of the candidate boundary into the roadmap deferred work, and the plan non-goals point to it.
- R1-F4: applied on 2026-11-07T23:28:56Z: The candidate title and outcome now name the four marked fields; the summary and other neutral fields are in the measured sample and grounded later only if it shows a need.
- R1-F5: applied on 2026-11-07T23:28:57Z: With the owner word the spec non-goal now covers verifying that claims are true, and a new statement says what the engine checks; the plan spec step no longer needs to change that non-goal.
- R2-F1: applied on 2026-11-07T23:32:09Z: The agreement command now compares over the ids of the smaller file, which must be a subset of the larger, so the model labels of the full file can be checked against the owner labels of the calibr...
- R2-F2: applied on 2026-11-07T23:32:09Z: The plan now fixes one rubric for the three labels and skip, written by the sample command, quoted in the readme and given to every labeller, including how to treat support outside the passages and...
- R2-F3: applied on 2026-11-07T23:32:10Z: Every unverified topic and key idea is now dropped, and a card with fewer than three key ideas left is marked thin and not padded back to three.
- R2-F4: applied on 2026-11-07T23:33:57Z: With the owner word, the roadmap and the spec now say an item without a verified quote is kept only if the model calls it an inference and is otherwise dropped, and the plan drops unsupported cavea...
- R3-F1: applied on 2026-11-07T23:34:46Z: The shared passages cannot measure retrieval misses, so the rubric no longer claims that; the agreement is stated as support within the passages shown, and a second look at the full text of the ite...
