# Specs

A spec states what is true now. It is a living document, edited in place as the project
is learned and redesigned. It is not a work log.

## Naming

One spec per topic, named by the topic in lowercase kebab-case with no date, for example
`power-supply.md`.

## Status

The first lines carry one status line, `Status: <value>`, before the first `##` heading. The
values are `Draft`, `Current` and `Superseded`. A superseded spec names its successor with a
line `Superseded by <name>` beside the status line.

## Contents

Every spec has a status line, scope, non-goals, assumptions and constraints, the
interfaces or behavior it specifies, acceptance criteria, and references to the decisions
and external material that govern it. A number, dimension or tolerance carries its
source: a decision, a reference or an evidence note.

Changing what a spec says about direction needs the owner. Correcting a typo or recording
evidence does not.
