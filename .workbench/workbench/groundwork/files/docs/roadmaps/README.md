# Roadmaps

A roadmap lists candidates, each sized to be one unit of work, with no required order. It
expresses direction. It does not authorize work and does not change work in progress. A
roadmap is a tracked, committed document, kept with the project's documentation.

## Naming

A roadmap is named by its scope in lowercase kebab-case, with no number or date, for
example `first-release.md`. There may be several.

## Contents

A roadmap states its status, the date it was updated, its purpose, the current state, its
candidates, deferred work, and the decisions that bear on it. The status is one line,
`Status: <value>`, before the first `##` heading, and the values are `Draft`, `Active` and
`Archived`.

Candidates are the `###` headings under a `## Candidates` heading, written `### <id>: <title>`.
A candidate has an ID, a title, the outcome wanted, dependency hints, a boundary and the
trigger for starting it. The ID is a short topic slug in lowercase kebab-case, fixed when
the candidate is created and unique within the roadmap. It is never reused, renumbered or
changed when the title is reworded. Refer to a candidate as `<roadmap>#<id>`, for example
`first-release#pick-a-board`. An abandoned candidate is marked dropped with a reason and
stays in the file.

A roadmap keeps no implementation file lists, detailed acceptance criteria or executable
commands; they belong in the plan written when a candidate is promoted.

Completion is never written into a roadmap. The file changes only when direction changes,
and changing direction needs the owner.

## Retiring a roadmap

Retire a roadmap by setting its status to `Archived`, as a plan is archived by status. Never
move or rename the file: a candidate is cited as `<roadmap>#<id>`, so the name stays. Keep
one roadmap that is not archived for each scope and update it in place; a replacement takes a
new name, and the old one is archived when it is written. Retiring or replacing a roadmap
changes direction, so it needs the owner.
