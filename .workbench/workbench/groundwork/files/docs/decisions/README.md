# Decisions

A decision record states why a choice was made and what was rejected. It is durable
history, and it outranks the current code.

## Naming

One record per decision, named `YYYY-MM-DD-<topic>.md` with the creation date and a
lowercase kebab-case topic, for example `2026-01-15-use-spi-flash.md`. A record is never
renamed. Its file name without the extension is its ID.

## Status

One status line, `Status: <value>`, comes before the first `##` heading. The values are
`Proposed`, `Accepted`, `Rejected` and `Superseded`. A superseded record names its successor
with a line `Superseded by <name>` beside the status line.

Accepting a decision is the owner's act, unless the owner has set the level of `accept-decision`
to let the agent accept (the `draft-decision` skill says how); otherwise an agent writes a
record as `Proposed` and asks. At `block`, and at any other reading, the agent stops at `Proposed` and asks the owner.
At `ask` the agent runs `wb run groundwork preview <record>`, shows the owner what it prints, then runs
`wb run groundwork accept <record> --digest <digest>` with the digest that preview printed, and the owner confirms that command.
At `none` the agent runs `wb run groundwork accept <record>`. `delegated` reads `block`. Once accepted, a record is not
rewritten: a correction or a change of mind is a new record that supersedes it.

A status line that says who accepted a record names that person by their git identity, as
`Status: Accepted by Name <email> on YYYY-MM-DD`. An older record keeps the form it was written in.

## Contents

Context, the decision, the alternatives considered and rejected, the consequences, and
evidence. Evidence carries a provenance line: what was run, with which tool versions, at
which commit, and the conclusion.
