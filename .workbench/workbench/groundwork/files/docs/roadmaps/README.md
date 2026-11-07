# Roadmaps

A roadmap lists candidates, each sized to be one unit of work, with no required order. It
expresses direction. It does not authorize work and does not change work in progress. A
roadmap is a tracked, committed document, kept with the project's documentation.

## Naming

A roadmap is named by its scope in lowercase kebab-case, with no number or date, for
example `first-release.md`. There may be several roadmaps.

A scope is a body of work with its own finish line: one the owner can call finished, or pause, without
that deciding anything about other scopes. New work that shares the finish line of the roadmap it
would join becomes a candidate of that roadmap, once the owner has seen it and said to write it;
otherwise a new roadmap is proposed to the owner, with its
scope and its finish line, and written once the owner accepts or renames it. An agent never adds to the
nearest roadmap because it is nearest. A candidate is bounded new
work that advances the finish line of its roadmap; work too small to need roadmap direction is a plan
with `Candidate: none`. At about 15 candidates an agent asks the owner whether the roadmap has outgrown
its scope; this is a question, not a limit.

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
and changing direction needs the owner. Any change to a roadmap other than correcting a typo is a
change of direction: adding, dropping or rewording a candidate, changing a roadmap's purpose, scope
or status, or creating, retiring or replacing a roadmap. It is the `change-direction` checkpoint,
which always stops for the owner. The agent checks that the candidate shares the finish line of the
roadmap it would join, shows the owner the candidate it would add, and writes it only on the owner's
word; the owner's request to add a candidate is that word.

## Retiring a roadmap

Retire a roadmap by setting its status to `Archived`, as a plan is archived by status. Never
move or rename the file: a candidate is cited as `<roadmap>#<id>`, so the name stays. Keep
one roadmap that is not archived for each scope, each with its own finish line, and update it in place on the owner's word; a replacement takes a
new name, and the old one is archived when it is written. Retiring or replacing a roadmap
changes direction, so it needs the owner.
