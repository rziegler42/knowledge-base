# knowledge-base

A personal library of outside information (papers, web pages and later other kinds of source) that AI agents in other projects
search while they brainstorm and write specs, decisions, roadmaps and plans, to find ideas and analogies from other fields that
they would not otherwise reach.

> **Status:** experimental, in design. The design is written as draft specs, one decision is accepted and the first build plan
> is approved. No engine code exists yet, and nothing can be run.

## What it is meant to do

- **Hold sources as books.** A book keeps the original bytes unchanged with a manifest (where it came from, when, and its hash),
  so everything else can be rebuilt from it.
- **Convert and search them.** Text is extracted, kept with locators, and found by keyword. Cards, themes and a search across
  fields come later and use a local or cloud model through the workbench's model bridges.
- **Be read through a governed command.** A thin package for the project workbench lets an agent in another project search and
  read the library. Everything it returns is marked as untrusted data.
- **Grow on its own.** A scheduled program, started later, is meant to add sources while the owner is away.

The design and its reasons are in [docs/specs/knowledge-base.md](docs/specs/knowledge-base.md). The first piece to be built is
[the first-slice plan](docs/plans/2026-11-05-first-slice-capture-search-read.md): capture a web page and an arXiv paper, convert
them, search them by keyword and read a passage back.

## Quick start

Requirements: none yet. There is nothing to install or run until the first slice is built.

## Development

There is no code or test suite yet. The documents are checked with the workbench:

```sh
wb check
wb run code-work check
```

The first reports on the workbench installation and the second on the plan files. Project conventions for people and coding
agents are in [AGENTS.md](AGENTS.md).

| Path | Contents |
|---|---|
| `docs/` | Project documents, indexed in [docs/README.md](docs/README.md): specs, decisions, plans, roadmaps and references |
| `.workbench/` | The project workbench's modules and records for this project, managed by the workbench and not edited by hand |
| `engine/` | The engine and its tests. Planned in the first-slice plan, and not created yet |

## Documentation

All project documents are indexed in [docs/README.md](docs/README.md). The decision that the knowledge base is a standalone
project with a thin workbench package is
[docs/decisions/2026-11-04-knowledge-base-is-a-standalone-package.md](docs/decisions/2026-11-04-knowledge-base-is-a-standalone-package.md).

## Contributing

This is a personal project. Changes follow [AGENTS.md](AGENTS.md): small and reviewable, with a plan approved by the owner before
implementation.

## Security

Not yet defined. The library holds and parses untrusted content, so a security review of the conversion step is planned before
it is used on real material.

## License

MIT. See [LICENSE](LICENSE).
