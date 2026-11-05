# Plans

A plan describes one bounded piece of work as ordered increments. It is how a roadmap
candidate becomes a verified, reviewed, committed result.

## Names and location

- A plan is one file, `docs/plans/YYYY-MM-DD-<topic>.md`. The date is the creation date and
  the topic is lowercase kebab-case. The file is never renamed or moved; archiving changes
  its status only.
- Several plans may be active at once. There is no fixed single-plan file and no
  hand-maintained index. Active plans are found by listing plans by `Status:`.
- Planning tools and skills may supply a method or content structure, but they do not
  override this location. Do not create a tool-owned or parallel plan directory.

## Content

A plan has, in order:

1. A title, a `Status:` line and a `Created:` date, which is the date in the file name.
2. `Candidate: <roadmap>#<id>`, or `Candidate: none` with a one-line reason. Exactly one.
3. `Specs:` naming zero or more specs the plan implements or changes.
4. Goal, scope, non-goals, and assumptions and constraints.
5. Completion criteria for the whole plan.
6. Increments.
7. Verification for the plan as a whole.
8. Risks and sensitive actions, or "None identified".
9. Review record.
10. Deferred work.
11. Result.

Status is `Proposed`, `Approved`, `In Progress`, `Completed` or `Superseded`. The header
lines come before the first `##` heading.

## Increments

- An increment is the smallest unit that can be verified and reviewed on its own, and it
  produces exactly one local commit.
- Labels run `A` to `Z`, then `AA`, `AB` and so on, in execution order. Labels are unique
  within a plan. More than 15 increments suggests two plans, and more than 26 is not allowed.
- After approval, labels are not renumbered. An increment needed between `B` and `C` is
  `B-A`, then `B-B`, and nests the same way (`B-A-A`).
- The heading is `### Increment <label> — <title>`, under a `## Increments` heading. Each
  increment states its outcome, dependencies, affected areas, numbered steps, verification,
  and the evidence that completes it.
- An increment is cited as `<plan stem>#<label>`.

## Committing an increment

- Commit an increment with `wb run safe-git commit`, naming the commit HEAD is expected to be
  and the exact paths. The helper stages only those paths, refuses a commit when anything else
  is staged, and prints the new commit.
- The message describes the change only. It carries no attribution of any tool unless the
  project allows it in `.workbench/safe-git.json`.
- A commit that completes an increment ends with the trailer `Plan: <plan stem>#<label>`.
- On a branch with no commit yet, the expected commit is `none`.

## Approval and revision

Write a complete plan with `Status: Proposed`, then obtain the owner's explicit approval
before changing it to `Approved` or beginning implementation. Use `In Progress` while
implementation is underway. Editing anything other than the status line, the review record
and the result after approval needs a new approval.

Approval is a record, not a status. The owner makes it with `wb approve-plan <plan>`, which
shows the hash of the plan's hashed region and records it when the owner types the start of it
back; `wb plan-status <plan>` reads it and prints `approved`, `changed since approval` or
`not approved`. The record names the approver by their git identity, `Name <email>`, and says how
the run was authorized (at a terminal, at a prompt, delegated or with no gate). Do not begin an
increment of a plan that is not `approved`. The `Status:` line is informational and never an approval.

The hashed region is the whole plan except the `Status:` line, the `## Review record` section
(or `## Second opinion`) and the `## Result` section. Write those headings exactly so, once
each: only the exact heading starts a left-out section, and any other heading ends it. A plan
with a repeated one, with no `Status:` line before its first heading, or with a code fence or
comment that is never closed has no region and cannot be approved.

Classify new findings before editing the plan: add a step when the outcome is unchanged; add
an increment for a separately reviewable outcome or prerequisite; update assumptions or risks
when no work is added; record out-of-scope work as deferred or in a roadmap.

## Checkpoints and caps

A checkpoint is a point where the work stops for the owner: approving a plan, pushing to a shared
branch, submitting a remote job, fetching its output, changing a spec's or roadmap's direction,
accepting a decision, and acknowledging changes made by someone else (two tiers). Every checkpoint
stops by default. `wb settings` prints the level of each, and a level the owner has set to something
other than `block` lets the agent go on in the way that level says.

Three caps bound a run: review rounds (default 3, at most 5), retries of the same failure
(default 1, at most 2) and exchanges with a reviewer (default 6, at most 12). A second identical
failure stops and diagnoses instead of retrying, and reaching a cap stops the run with a report.
The owner may lower a cap in the personal settings, never raise it above its most. `wb settings`
prints each checkpoint and the value of each cap that applies in this project.

## Completion

A plan is `Completed` only when its completion criteria are met with recorded evidence. A
plan that names a roadmap candidate and is `Completed` is what makes that candidate
complete; the roadmap file is not edited.
