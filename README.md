# knowledge-base

A personal library of outside information (papers, web pages and later other kinds of source) that AI agents in other projects
search while they brainstorm and write specs, decisions, roadmaps and plans, to find ideas and analogies from other fields that
they would not otherwise reach.

> **Status:** experimental, built in small reviewed steps. The engine can capture a web page or an arXiv paper, scan and convert
> it, search it by keyword and read a passage back, from the command line. Two walk-throughs on real pages and papers found
> problems, and three plans have fixed them: the first walk-through's fixes, a hardening of the PDF scan, and one rule for titles
> (see [Where the work stands](#where-the-work-stands)). The workbench package that lets an agent in
> another project call the library is not built yet, and neither are cards, themes or the program that adds sources by itself.

## What it does now

- **Holds sources as books.** A book keeps the original bytes unchanged with a manifest (where it came from, when, and its
  hash), so everything else can be rebuilt from it. Web pages and arXiv papers (with their versions) can be captured.
- **Scans and converts.** Each capture is scanned for things a reader should know about (scripts, hidden text, links that run
  code, a PDF it could not read to the end), then converted to text by tools you have approved, run in a macOS sandbox with
  no network. A web page goes through two extractors and the results are compared, so a page that one of them read badly is
  marked partial. A PDF goes through `pdftotext`.
- **Searches by keyword.** A local SQLite index finds the blocks of text that hold every word of a query. A long block is
  indexed in pieces, so a hit in a long page leads to the passage and not to the top of the page.
- **Reads by locator.** A locator names a place (a section, a page, or an offset) and carries a hash of the words there, so it
  is found again even if the text is converted another way. A read returns a bounded passage with a citation line.
- **Marks everything from outside as untrusted.** Search results and reads are flagged, their text sits between markers, and
  titles and other fields are cleaned of hidden and control characters. The text is data, never instructions.

- **Calls a model you list.** The engine can send one prompt to a model in your config through the workbench's Ollama bridge and
  take back one answer checked against the shape a job expects, marked as untrusted, with a record of the model, prompt version
  and date. No stage uses it yet (`python3 -m kb models` and `model-try`; see [engine/README.md](engine/README.md)).

Planned, not built: the thin workbench package that gives an agent `search` and `read` in a project, cards and themes made with a
local or cloud model, a search across fields, and a scheduled program that adds sources while the owner is away.

The design and its reasons are in [docs/specs/knowledge-base.md](docs/specs/knowledge-base.md).

## Quick start

Requirements: macOS (the sandbox is `sandbox-exec`) and Python 3.15, the version the engine was written and tested with. The
engine's own code uses only the standard library. Two of the converters need more:

- the article extractor needs a virtual environment built from hashes: `python3 -m venv engine/.venv`, then
  `engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock`;
- PDFs need poppler: `brew install poppler`.

Then, from `engine/`:

```sh
python3 -m kb setup /absolute/path/to/bulk /absolute/path/to/index   # once: two roots, one for books, one for the index
python3 -m kb describe-tool all      # print the entries of the tools; read them, then paste them into approved_tools in the config
python3 -m kb tools                  # whether each approved entry still matches its hashes
python3 -m kb capture-url https://example.org/some/page
python3 -m kb capture-arxiv 1706.03762
python3 -m kb process                # scan, convert and index everything that is not done
python3 -m kb search 'attention heads'
python3 -m kb read BOOK_ID 'LOCATOR_JSON' --version v1    # the text at a locator a search returned
```

A tool runs only if you have put it on the approved list yourself; the engine prints what to put there and never does it for
you. The full description of each command, its refusals and what it does not cover is in [engine/README.md](engine/README.md).
An index written by an older version of the engine is refused, and the search says to run `python3 -m kb index` to build it again.

## Where the work stands

| Plan | What it covers | State |
|---|---|---|
| [First slice](docs/plans/2026-11-05-first-slice-capture-search-read.md) | setup, the book store, capture, scan, conversion, search and read, then the workbench package and a live walk-through | everything up to read by locator is built; the workbench package is deferred; the walk-through has had two batches (nine web pages and three papers in all) |
| [Fixes from the first walk-through](docs/plans/2026-11-06-first-walk-through-fixes.md) | page encoding, page titles, long pages indexed in pieces, large images in a PDF, converting a book again, and applying the fixes to the first four books | completed: all six fixes are committed and applied to the first four books |
| [Hardening the PDF scan](docs/plans/2026-11-06-scan-hardening.md) | no way to hide an object stream from the scan without saying so: streams behind a predictor are decoded, objects are read forward with strings and comments known, and bytes after a stream's data are reported | completed: all five increments are committed and the four books were scanned again |
| [Title safety](docs/plans/2026-11-06-title-safety.md) | one rule for a title where it is stored and where it is shown, and a citation line that a title cannot imitate | completed: all four increments are committed and the index was rebuilt |
| [Model calls](docs/plans/2026-11-07-model-calls.md) | a registry of models in the owner's config, one call through the Ollama bridge, a checked answer with a record of how it was made, and two commands | completed: all three increments are committed and one live call was made |

Each increment of a plan is one verified, reviewed local commit. A plan needs the owner's approval before anything is built, and
the plan, not the conversation, is the record of what was done and checked.

## Development

Tests are run from the repository root. The conversion, search and read tests use the pinned environment:

```sh
python3 -m unittest engine.tests.test_setup engine.tests.test_store engine.tests.test_stages engine.tests.test_textutil \
    engine.tests.test_capture_url engine.tests.test_capture_arxiv engine.tests.test_scan engine.tests.test_convert_run
engine/.venv/bin/python -m unittest engine.tests.test_convert engine.tests.test_search engine.tests.test_read
```

The documents and plans are checked with the workbench:

```sh
wb check
wb run code-work check
```

Project conventions for people and coding agents are in [AGENTS.md](AGENTS.md).

| Path | Contents |
|---|---|
| `engine/` | The engine (`engine/kb/`), its tests (`engine/tests/`) and its own README with every command |
| `docs/` | Project documents, indexed in [docs/README.md](docs/README.md): specs, decisions, plans, roadmaps and references |
| `.workbench/` | The project workbench's modules and records for this project, managed by the workbench and not edited by hand |

## Documentation

All project documents are indexed in [docs/README.md](docs/README.md). The decision that the knowledge base is a standalone
project with a thin workbench package is
[docs/decisions/2026-11-04-knowledge-base-is-a-standalone-package.md](docs/decisions/2026-11-04-knowledge-base-is-a-standalone-package.md).

## Contributing

This is a personal project. Changes follow [AGENTS.md](AGENTS.md): small and reviewable, with a plan approved by the owner before
implementation.

## Security

The library holds and parses untrusted content, and the engine is built on that assumption:

- a captured file is never changed, and every tool that reads it runs only if you approved its exact program and scripts by hash,
  inside a sandbox with no network and no access to your config, library or home folder;
- what a tool hands back is checked in full before it is used, and text from outside is cleaned of control, direction and hidden
  characters and is flagged as untrusted wherever it is shown;
- each increment is reviewed independently before it is committed, and the parts that take untrusted input (capture, the tool
  runner and scan, conversion, search and read) have each had a security review whose findings and fixes are recorded in the
  plan's Result.

Limits that are known and documented in [engine/README.md](engine/README.md): the sandbox is macOS only, and `sandbox-exec` is
deprecated by Apple; memory is not limited; a title or a text can still carry misleading words that no cleaning removes, which is
why a result is flagged untrusted as a whole. Rights and legality of what you capture are yours; the tool does not judge them.

## License

MIT. See [LICENSE](LICENSE).
