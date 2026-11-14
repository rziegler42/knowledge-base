# knowledge-base

A personal library of outside information (papers, web pages and later other kinds of source) that AI agents in other projects
search while they brainstorm and write specs, decisions, roadmaps and plans, to find ideas and analogies from other fields that
they would not otherwise reach.

> **Status:** experimental, built in small reviewed steps. The engine can capture a web page or an arXiv paper, scan and convert
> it, search it by keyword and read a passage back, from the command line. Models you name write a card for each book, with a
> description of its problem and approach in words of no field, and each point of a card is marked as found in the book or as the
> model's own inference. The cards can be searched by keyword and by meaning. A workbench package, `kb`, lets an agent in another
> project search by keyword, read a passage, and put a problem to the library by meaning, with a skill that says how (see
> [Where the work stands](#where-the-work-stands)). Themes (the ideas of a book, each described in words of no field) are made for
> each book with `themes-run`, but cannot be searched yet. Not built yet: a trial on problems you choose that shows how often it
> finds a source from another field, the search and links between themes, and the program that adds sources by itself.

**The library is not in this repository.** The books, cards, themes and indexes it holds are the owner's local data, kept outside this
clone (`docs/specs/knowledge-base.md`, "Where things live"). A clone of this repository has none of them. Where a document here gives a
figure about the library's contents, or names a book or a result from it, that is the owner's figure, measured on the owner's library on
the date the document gives, and nothing in the repository holds the data behind it.

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
  and date (`python3 -m kb models` and `model-try`; see [engine/README.md](engine/README.md)). Which model does which kind of work
  is a setting of the config, not a preference of the engine.
- **Writes cards, on command.** `python3 -m kb cards --book ID` has the models your config names write a card for each named
  book: a short, plain-English entry of what the book is about and useful for, and a description of its problem and approach in
  words of no field. A long book is read in pieces. A card is kept in the book's folder as a generation that is never overwritten;
  `card-show` prints it between the untrusted-text markers. Book text goes to the models you name. If a model's answer is refused
  for its shape, no card is made and the answer is kept in a file for you to read. `card-index` builds a catalog of the cards and
  `card-search` finds them by keyword; the catalog is not updated as cards are made.
- **Grounds a card in its book.** A card is made from notes that each carry a short quote the engine has checked against the
  book, and a second model confirms that a note supports the point that cites it. Each topic, key idea, caveat and neutral limit is
  marked `stated` (found in the book) or `inferred` (the model's own inference), and a point with no support is dropped, not
  padded. How accurate the cards are was measured on blind samples, and the numbers are in the plans' Results: the card is a
  model's description of a book and can be wrong, which is why a result shows its marks.
- **Searches the cards by meaning.** `card-vectors` turns three neutral fields of each card (what the book is about, its approach
  and what it provides) into vectors with the embedding model your config names for `card-embed`, and `card-search QUERY --meaning`
  ranks the cards by closeness to a sentence or two about a problem. The library uses `qwen3-embedding:4b`, chosen over two others on
  eight searches, with an instruction put before the query. A vector is used only while its text is unchanged. **The text of the
  fields, and each query, go to the embedding model's server.**
- **Takes a problem in sub-problems.** `python3 -m kb problem-search -- 'sub-problem' ...` takes one to five sub-problems, which the
  caller has put in general terms, and prints each one's ranked books and one list of the books found. The engine does not set
  aside the books of the problem's own field, because no card says which field a book belongs to: the caller does.
- **Gives an agent in another project a way in.** The workbench package `kb` offers `wb run kb search`, `read`, `problem-search` and
  `theme-walk` to an agent in a project you install it into, and a skill, `pose-a-problem`, that tells the agent how to put a problem in general
  terms, split it, set aside its own field, give a reason from the matched text and read the book before relying on it. The
  package finds the engine only through `~/.config/knowledge-base/helper.json`, which you make. `problem-search` and `theme-walk` are the two
  arguments that send anything out: the sub-problems or questions an agent wrote go, in the clear, to your embedding model's server and
  nowhere else. `problem-search` was run once through the package, from a scratch project; `theme-walk` has not been.

Planned, not built: a trial on problems you choose that compares keyword search, search by meaning and the problem search, judging
pairs of ideas that a search returned, search and links between themes, and a scheduled program that adds sources while
the owner is away. The roadmaps are in [docs/roadmaps/](docs/roadmaps/).

The design and its reasons are in [docs/specs/knowledge-base.md](docs/specs/knowledge-base.md).

## Quick start

Requirements: macOS (the sandbox is `sandbox-exec`) and Python 3.15, the version the engine was written and tested with. The
engine's own code uses only the standard library, except that building a weave uses numpy, as the decision
[the engine may use numpy](docs/decisions/2026-11-13-the-engine-may-use-numpy.md) allows; every other command runs without it.
Two of the converters need more:

- the article extractor needs a virtual environment built from hashes: `python3 -m venv engine/.venv`, then
  `engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock`. The same lock pins numpy, which
  `python3 -m kb theme-links build` and `theme-links repair` need (run them with `engine/.venv/bin/python`); no other command needs it, `theme-walk` included;
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
python3 -m kb cards --book BOOK_ID   # write a card; the book text goes to the models in your config
python3 -m kb card-index             # build the catalog of cards
python3 -m kb card-vectors           # vectors of the neutral fields; their text goes to your embedding model
python3 -m kb card-search 'a problem in a few sentences' --meaning
python3 -m kb problem-search -- 'first sub-problem' 'second sub-problem'
```

The model commands need a model registry in the config (`python3 -m kb models` lists it and makes no call); the section "Calling a
model" of [engine/README.md](engine/README.md) says how.

A tool runs only if you have put it on the approved list yourself; the engine prints what to put there and never does it for
you. The full description of each command, its refusals and what it does not cover is in [engine/README.md](engine/README.md).
An index written by an older version of the engine is refused, and the search says to run `python3 -m kb index` to build it again.

## Where the work stands

| Plan | What it covers | State |
|---|---|---|
| [First slice](docs/plans/2026-11-05-first-slice-capture-search-read.md) | setup, the book store, capture, scan, conversion, search and read, then the workbench package and a live walk-through | everything up to read by locator is built; the workbench package `kb` was built and installed in a scratch project (it has since gained `problem-search`, see the last row); the walk-through has had two batches (nine web pages and three papers in all) |
| [Fixes from the first walk-through](docs/plans/2026-11-06-first-walk-through-fixes.md) | page encoding, page titles, long pages indexed in pieces, large images in a PDF, converting a book again, and applying the fixes to the first four books | completed: all six fixes are committed and applied to the first four books |
| [Hardening the PDF scan](docs/plans/2026-11-06-scan-hardening.md) | no way to hide an object stream from the scan without saying so: streams behind a predictor are decoded, objects are read forward with strings and comments known, and bytes after a stream's data are reported | completed: all five increments are committed and the four books were scanned again |
| [Title safety](docs/plans/2026-11-06-title-safety.md) | one rule for a title where it is stored and where it is shown, and a citation line that a title cannot imitate | completed: all four increments are committed and the index was rebuilt |
| [Model calls](docs/plans/2026-11-07-model-calls.md) | a registry of models in the owner's config, one call through the Ollama bridge, a checked answer with a record of how it was made, and two commands | completed: all three increments are committed and one live call was made |
| [The card of a book](docs/plans/2026-11-07-card-stage.md) | the model for each kind of work set in the config, the card file kept as generations, reading a book in pieces, the `cards` and `card-show` commands, and cards for three real books | completed: all five increments are committed and cards were made for three books |
| [Two fixes from the first live run of cards](docs/plans/2026-11-07-card-live-run-fixes.md) | a flat conversion no longer makes a card partial, and a model answer refused for its shape is kept aside in a file | completed: both increments are committed |
| [Searching the cards by keyword](docs/plans/2026-11-07-card-catalog.md) | a catalog of the cards built from the book folders, a keyword search of it with a summary side, a neutral side and a named book, and the `card-index` and `card-search` commands | completed: all three increments are committed and the three real cards were indexed and searched |
| [Scan false alarms](docs/plans/2026-11-06-scan-false-alarms.md) | ordinary figure-heavy PDFs no longer get a false "scripts" or "incomplete" alarm | completed |
| [Close the deferred items of the PDF scan](docs/plans/2026-11-07-scan-deferred-items.md) | a bound on memory for hostile name escapes, the file-attachment caveat, one ceiling for match counts, and no false "incomplete" for data that only looks compressed | completed |
| [Making the cards accurate](docs/plans/2026-11-07-card-grounding.md) | notes with verified quotes, items marked stated or inferred, a second model that confirms support, and a measured accuracy | completed |
| [A trial of whether the cards help](docs/plans/2026-11-07-card-trial.md) | the search of the cards compared with the search of the full text on questions you chose, and a report on the cards themselves | completed |
| [Card lists that follow the book](docs/plans/2026-11-08-card-lists-that-follow-the-book.md) | one more round by a second model for a list that was cut off or lost most of its items, and reading a long book in every piece | completed |
| [Cards for the library, one model at a time](docs/plans/2026-11-08-cards-for-the-library-one-model-at-a-time.md) | one run that makes a grounded card with a neutral description for every book without one, works through the models one at a time, and can be stopped and started again | completed: 79 books have a card |
| [Ground the summary and the neutral fields](docs/plans/2026-11-09-ground-the-summary-and-neutral-fields.md) | the summary and the neutral fields as sentences that each cite and carry a mark | built and measured on nine books; the supported share did not rise enough, so the old form was not replaced and the library was not carded again |
| [Check each clause of a sentence](docs/plans/2026-11-09-check-each-clause-of-a-sentence.md) | cut a sentence back to the clauses its notes support | stopped after the first increment: the check cut or dropped more supported sentences than the plan allowed |
| [Search the neutral descriptions by meaning](docs/plans/2026-11-09-search-the-neutral-descriptions-by-meaning.md) | vectors of three neutral fields, `card-vectors` and `card-search --meaning`, a security review, and a comparison of three embedding models | completed; the library keeps `qwen3-embedding:4b` |
| [A query prefix for embedding models](docs/plans/2026-11-09-query-prefix-for-embedding-models.md) | an instruction before the query, recorded with the vectors | completed: on eight searches 12 of 18 expected books ranked higher, 5 the same and 1 lower |
| [Pose a problem to the search by meaning](docs/plans/2026-11-10-pose-a-problem-to-the-search-by-meaning.md) | `problem-search` in the engine and in the `kb` package, the `pose-a-problem` skill, and one live run | completed: all four increments are committed and the helper ran once, in 3.2 seconds |

Each increment of a plan is one verified, reviewed local commit. A plan needs the owner's approval before anything is built, and
the plan, not the conversation, is the record of what was done and checked.

## Development

Tests are run from the repository root. The conversion, search and read tests use the pinned environment:

```sh
python3 -m unittest engine.tests.test_setup engine.tests.test_store engine.tests.test_stages engine.tests.test_textutil \
    engine.tests.test_capture_url engine.tests.test_capture_arxiv engine.tests.test_scan engine.tests.test_convert_run
engine/.venv/bin/python -m unittest engine.tests.test_convert engine.tests.test_search engine.tests.test_read
python3 -W error::ResourceWarning -m unittest engine.tests.test_card engine.tests.test_catalog engine.tests.test_models \
    engine.tests.test_vectors engine.tests.test_problem
KB_WORKBENCH_CHECKOUT=/path/to/a/workbench/checkout python3 -m unittest engine.tests.test_package   # skipped without the variable
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
  plan's Result;
- an agent in another project is allowed only reads, and only `problem-search` and `theme-walk` send anything out: the sub-problems
  or questions it wrote go, over plain HTTP, to the embedding model that your config names (on your network, in the clear), and the
  helper finds the engine and the workbench launcher only in a settings file that is yours alone. Nothing checks those texts for
  private text, and the server is trusted.

Limits that are known and documented in [engine/README.md](engine/README.md): the sandbox is macOS only, and `sandbox-exec` is
deprecated by Apple; memory is not limited; a title or a text can still carry misleading words that no cleaning removes, which is
why a result is flagged untrusted as a whole. Rights and legality of what you capture are yours; the tool does not judge them.

## License

MIT. See [LICENSE](LICENSE).
