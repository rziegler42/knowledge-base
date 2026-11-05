# Engine

The knowledge-base engine, a standalone Python program. It holds the library on disk. It does not depend on the project
workbench except for model calls, which this first slice does not make. The design is in
[`docs/specs/`](../docs/specs/README.md) and the build plan is
[`docs/plans/2026-11-05-first-slice-capture-search-read.md`](../docs/plans/2026-11-05-first-slice-capture-search-read.md).

The engine sets up a library, captures web pages and arXiv papers, scans them, and converts them to text. Search and reading come
next. Requirements: Python 3.15 (the version it was written and tested with); the engine itself uses only the standard library. Two
of the converters need more, and the conversion section below says what: the pinned packages in `engine/.venv` for the article
extractor, and poppler for PDFs.

## Run the tests

From the repository root:

```sh
python3 -m unittest engine.tests.test_setup engine.tests.test_store engine.tests.test_stages
engine/.venv/bin/python -m unittest engine.tests.test_convert     # the conversion tests, which use the pinned environment
```

## Set up a library

A library has two roots, chosen once: a bulk root for books and an index root for the search index. The owner-only config goes
to `~/.config/knowledge-base/config.json` (mode 600), outside both roots. Set the environment variable `KB_CONFIG_DIR` to use
another folder, as the tests do.

```sh
cd engine
python3 -m kb setup /absolute/path/to/bulk /absolute/path/to/index
python3 -m kb check
```

- `setup` prints `{"library_id": "..."}`. It writes a marker file with the id into the bulk root, records the bulk root's
  device in the config, and creates the index root. Running it again with the same roots changes nothing.
- It refuses, with `refused: <reason>` and exit code 2: a relative path, a symlink in a root's path, the same folder for both
  roots, a bulk root that holds another library's marker, a second library with other roots, and a bulk root on the main disk
  unless you pass `--allow-main-disk`.
- The first setup that creates a library also prints a one-line notice on the error stream that rights and legality are the
  owner's responsibility. The tool does not judge them. A repeated setup, a refusal and `check` print no notice.
- Roots that differ only in letter case count as the same folder. If setup fails part way, it removes the files it wrote, so
  running it again works. A system error such as a permission failure prints `failed: <reason>` and exits with code 1.
- `check` is the guard that runs before any later write. It refuses when the bulk root or index root is not reachable or has
  become a symlink, the marker is missing or holds another id, the bulk root is on a different device than at setup, or it is on
  the main disk and setup did not allow that.
- The config is read only if it is a plain file (never a symlink) owned by you with mode 600, in a directory that others cannot
  write.

## The book store

`kb.store.Store.open()` opens the library named by the config; opening to write runs the write guard first. A book is stored
under the bulk root as `books/<last two characters of its id>/<id>/`:

| Path | Contents |
|---|---|
| `book.json` | The root file: id, library id, title, authors, year, kind, language, identity keys, shelf, date added, state, current version |
| `v/<version>/version.json`, `stages.json` | Small mutable files, rewritten with a temporary file and a rename |
| `v/<version>/original/` | The source as captured: its files and a `payload.json` with the sha256 and size of each |
| `v/<version>/derived/<tool>/<n>/` | A tool's output, one folder per generation |

- A book id is a ULID: 26 characters that sort by time. The shelf is a field of the root file, so a reshelve moves no bytes.
- A payload is built in `incoming/` inside the bulk root, re-read from disk and checked against its hash list, renamed into
  place in one step and marked read-only. A folder left in `incoming/` by a crash is never read as a book or a payload.
  Filing a payload that already exists is refused.
- `stages.json` holds the stages found, fetched, scanned, converted and indexed, each pending, done, failed or skipped. A stage
  cannot be done before its inputs are, a failure needs a reason, and a done stage is not run or changed again.
  `stages.reconcile` handles a stop between filing a payload and marking its stage. It calls `Store.adopt_payload`, which checks
  the filed payload against its hash list, marks it read-only if the stop came before that, and brings the version file (the
  payload list and the primary file, both kept in the hash list) up to date. Then the stage is marked done. A payload that
  fails its check marks the stage failed with the reason, and a payload whose stage inputs are not ready is left alone
  (`blocked`). Nothing here overwrites a payload.
- Nothing here takes a lock. Two programs changing the same book at the same time are not supported yet.

## Capturing a web page

```sh
cd engine
python3 -m kb capture-url https://example.org/some/page
```

It prints one JSON line with a `status`: `filed` (fetched and stored), `held` (the library already holds that address, so
nothing was downloaded), `duplicate` (fetched, but the same final address or the same bytes are already held, so a sighting
is added to the existing book) or `failed` (the reason is recorded; running the command again retries into the same book and
exits with code 1 on failure).

- One plain GET: an honest user agent, no cookies or credentials, the page asked for unencoded, at most 5 redirects, only to
  http and https, a size cap (`--max-bytes`, default 20 MB), a timeout for each read (`--timeout`) and a deadline for the
  whole fetch (`--total-timeout`, which also covers connecting and the headers). Only HTML pages are taken: another content
  type is refused, and so is a response that arrives encoded (gzip and the like, in any of its headers), because none was
  asked for. A page that ends before its declared length is refused too, and so is a `Content-Length` that is not plain digits
  or that conflicts with another, and a body that is compressed or binary under a page's name.
- The page is stored unchanged in `original/page.html`. The version file records the address asked for, the final address
  after redirects, the retrieval date, the HTTP status, a short list of response headers (never cookies) and the sha256.
- An address with a user name or password is refused, so no secret is stored, and so is a host written with percent escapes
  (urllib decodes them when it connects, so a check on the written form would not see what they spell). Addresses on this
  machine or a private network are refused too, and so are redirects to them, unless you pass `--allow-private`. The check and
  the connection are one step: the name is looked up by the connection itself, every answer must be a public address, and the
  connection goes to one of the addresses that was checked, so a name that answers differently the second time cannot send it
  elsewhere, and a name that cannot be looked up is not fetched. An IPv6 address that carries an IPv4 one (mapped, compatible,
  NAT64 or 6to4) is judged by the address inside it, and Teredo, site-local and NAT64-local ranges are refused. Public hosts on
  any port are allowed.
- A book's identity keys are its address (`url`), other addresses it has been seen at (`url_alias`) and the hashes of its raw
  bytes (`sha256`). An index of them in the index root (`identity.sqlite`) is looked up before a download and can be rebuilt
  from the books. A book's `events.jsonl` is its append-only log (`found`, `filed`, `sighting`).
- A capture that stopped half way is resumed by the next call for the same address, from the filed copy if there is one,
  without downloading it again. The overall deadline runs the fetch in a thread and, when time is up, closes the sockets it
  opened, so a server that trickles its answer cannot keep the thread alive. A name lookup that is stuck in the system resolver
  cannot be cut and ends when the resolver gives up. The reason recorded for a failed fetch is cleaned of control and direction
  characters, because it can carry text the server chose.
- A page that turns out to be one the library holds is a sighting on that book. A different page at a held address is also
  recorded as a sighting, not as a new version: comparing the text of versions comes later.
- Nothing downloaded is parsed here. Conversion comes later.

## Capturing an arXiv paper

```sh
cd engine
python3 -m kb capture-arxiv 2101.00001v2     # one version
python3 -m kb capture-arxiv 2101.00001       # the latest version
```

An id is the new form (`2101.00001`, with an optional `v2`) or the old form (`cs/0112017`, `math.GT/0309136v2`), with an
optional `arXiv:` in front. Whitespace and anything else is refused before any request. The output has the same `status` as
`capture-url`: `filed`, `held` or `failed`.

- A paper is a book and each arXiv version is a version of it. The file is stored unchanged as `original/paper.pdf`. The
  book's title, authors and year come from arXiv's own record and follow the current version, which is the newest label that
  was fetched (not the last one filed). The arXiv id and the hash of each file are identity keys.
- A version already stored is held without any request at all. With no version in the id, the metadata is asked for first to
  learn the latest label, and the file is downloaded only if that version is not stored.
- The metadata answer is untrusted text: it is size-capped, refused unless it is plain UTF-8 (a UTF-16 answer could hide an
  entity declaration from the check), refused if it declares entities (`DOCTYPE` or `ENTITY`), and then parsed with the
  standard library. Its title, authors, abstract, categories and DOI are cleaned (whitespace collapsed; control,
  direction-mark and zero-width characters removed), bounded and checked before they are stored in the version file. Digits
  from other scripts are not accepted in ids, years or DOIs. The file must have a PDF content type and start with `%PDF-`.
- A DOI comes from that untrusted answer, so it is kept in the version's source record as a claim and is not an identity key
  or an index entry: a hostile answer could otherwise claim a DOI before the real paper does. The arXiv id decides which book a
  paper belongs to.
- The book's title, authors and year are copied from the current version once, and the version they came from is noted in
  the root file, so an edit of them is not undone by a later request; a newer version replaces them. The default API
  address is https, which has not been tried against the real service.
- The two address prefixes are settings (`--api-base`, `--pdf-base`), so a mirror or a test server can be used. They get the
  same checks as any address: http or https only, no credentials, and no private or local host unless `--allow-private`.
- A withdrawal flag is not read yet.

## Approved tools, the sandbox and the scan

The engine runs a program on a captured file only if you have put it on the list. The list is `approved_tools` in your config
(`~/.config/knowledge-base/config.json`, mode 600). Nothing in the engine writes to it, and a config that is not owner-only is
refused. An entry names a tool and its exact version, the program (by its real path, not a link), the sha256 of that program and
of every script it runs, the folders it may read besides its input, the formats it may be used on, and its time and output limits.
A program or script that differs from its recorded hash is refused.

To put the scan tool that ships with the engine on the list:

```sh
cd engine
python3 -m kb describe-tool     # prints the entry; read it, in particular the program path and the readable folder,
                                # then paste it into the approved_tools list in the config
python3 -m kb tools             # lists what is on the list and whether each entry still matches its hashes
```

`describe-tool` and `tools` only read. A tool on the list runs like this (`kb/convert_run.py`):

- It is started under `sandbox-exec` with a profile that denies everything and then allows only: running that one program,
  reading system libraries, its runtime folders, its pinned scripts and its input folder, and writing in its own output folder.
  It has no network, cannot start or signal another program, and cannot read the config, the library or your home folder.
  Tests run hostile tools under this profile and check each of those, and they fail when the profile is replaced by an allow-all one.
- It runs with an empty environment, no standard input, a time limit, a file-size limit and an output limit (bytes, 200 files,
  100 folders, 8 levels deep), in its own process group that is killed whole when it overruns. Its output folder is inventoried
  without following links while it runs, so a tool cannot hide data by locking its own folders: a folder that cannot be listed
  stops it, and removal restores the modes and clears the file flags first (the profile also denies setting flags). Its output
  must be plain files with plain names (letters, digits, dot, dash and underscore); a link, a pipe or any other name is refused.
  What it wrote to standard error, and any name it chose, is cleaned or quoted before it appears in a message, and called
  untrusted.
- A small watchdog process, outside the sandbox, is started beside the tool. If the engine dies, however it dies, or the tool is
  still running ten seconds after its limit, the watchdog kills the tool's process group, so a tool cannot outlive the engine.
- Its output is read back, filed as a derived payload through the incoming area (`derived/<tool>/<n>/`) and marked untrusted.
- Not covered: memory is not limited (macOS does not enforce it); the profile lets a tool see whether a path exists, though not
  read it; `sandbox-exec` is deprecated by Apple but ships with macOS; a program could be swapped between the hash check and the
  start of the run by someone who can already write where it lives, and the runtime folder (the Python install) is not pinned,
  only the program and the scripts are. `reads` and pinned files are your decision: the engine refuses one that covers or lies
  inside the config, the library or your home folder, or is the whole disk, comparing paths without regard to letter case or
  Unicode form, because the default macOS volume ignores both.

The scan (`kb/scan.py`, `kb/scan_tool.py`) is the first tool. It runs under `python -I -S`, so nothing in the runtime folder runs
at start-up. It looks at the stored original and not at what it says: in a PDF for encryption, scripts, embedded files, launch
actions and XFA forms (also inside compressed streams, and for names written with `#xx` escapes), in a page for script elements,
event-handler attributes, `javascript:`, `vbscript:` and `data:text/html` addresses, a meta refresh, frames and objects, and text
hidden by the `hidden` attribute or an inline style. It records counts and fixed sentences as caveats on the version, never text
from the file. They never stop a book being filed. A scan that cannot run marks the stage failed with the reason.

**No caveat does not mean the file is safe.** It is a pattern scan and not a PDF reader, and it says only what it found. It reads
the stream markers in one pass and the whole dictionary of each stream, decodes deflate, ASCII85 and hex filters (also layered),
and reports `scan_incomplete` for anything it could not read: a filter it does not decode (LZW, run-length, crypt), a prediction
filter outside cross-reference streams and images, deflate data that is damaged, cut short or compressed again inside, a filter
declared that it did not tie to a stream it read, or a file or page larger than its limits. A page's hidden text is found only
when it is hidden by the `hidden` attribute or an inline style, not by a stylesheet, by position or by colour.

There is no command that runs the scan yet. `scan.scan_version(store, book, version)` does it, and the command that advances every
book through its stages comes with the search index.

## Converting what is captured

A version that has been fetched and scanned (or whose scan failed or was skipped) is converted to text by `kb/convert.py`
(`convert.convert_version(store, book, version)`; there is no command yet, and the one that advances every book comes with the
search index). The converters are approved tools like the scan, run by the same sandboxed runner, on the stored original:

| Tool name | What it is | Kind of file | Output |
| --- | --- | --- | --- |
| `trafilatura` | an article extractor, run with the packages pinned in `requirements.lock` (`kb/extract_traf.py`) | web page | `blocks.json` |
| `kb-html-std` | the plain extractor, the Python standard library with a tag skip list (`kb/extract_std.py`) | web page | `blocks.json` |
| `pdftotext` | poppler's text extractor | PDF | `text.txt` |

**Set up the tools.** The article extractor needs its environment, built from the hashes in the lock file (a package whose file
differs from its hash is refused, and nothing outside the list is installed). The PDF tool needs poppler (`brew install poppler`).
Then, as for the scan, print the entries, read them, and paste them into `approved_tools` in your config:

```sh
python3 -m venv engine/.venv
engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock
cd engine
python3 -m kb describe-tool all        # or one of: kb-scan, kb-html-std, trafilatura, pdftotext
python3 -m kb tools                    # whether each approved entry still matches
```

Read each entry before you approve it. For `trafilatura` look at the two folders it may read (the Python install and the
environment's packages). For `pdftotext` look at the list of folders: it is the program's own package and every package it loads
a library from (found by reading its load commands, about two dozen under Homebrew). A Homebrew upgrade of poppler or of any library it uses changes those paths, and the entry then
fails closed until you describe and approve it again, which is the intent. The version of each entry ends in `-kb1`: the number
is the revision of our command line or wrapper, raised when its options change.

**What a conversion is.** Each tool writes one file, which is read back as untrusted data and checked in full (`convert.py`).
The text is a list of blocks (heading, paragraph, list item, quote, code, table row; for a PDF, the paragraphs of each page),
cleaned of control, direction, zero-width and other hidden characters, with line breaks kept. The converted text is the blocks
joined by blank lines. Each conversion is filed as a derived payload (`derived/<tool>/<n>/`) and recorded on the version
(`conversions`, `conversion_in_use`, `conversion_check` in `version.json`) with its tool, version, generation, structure quality,
block and character counts, and page count. The structure quality is **full** (headings, and the text starts under one),
**partial** (headings, but some text lies before the first) or **flat** (no headings; a PDF is text with page marks only, and a
page with no heading or paragraph tags is one block that keeps its line breaks).

**The extractor-size rule.** For a web page both extractors run and their sizes are compared; the book is marked partial when
one returns more than twice the characters of the other, when what they found is under 200 characters for a file of 3,000 bytes
or more (a page built by scripts, or a scan of images), or when an extractor stopped at the limit of what it reads (10 MB). The
reasons are recorded in `conversion_check`, and a partial book uses the conversion with the most text; otherwise the article
extractor's is used. With only one extractor approved, or one failing, the book is converted by the other and `compared` is false,
so an unchecked extraction does not look checked. The ratio can be set in the config as `partial_ratio` (a number above 1, at most
1000); the first values rest on a test of ten pages, so they will give false alarms and misses: on that test a thread of 71
comments gave 3.7k against 28k characters (flagged), a repository page 1.5k against 2.6k (a ratio of 1.7, not flagged), and a
page built by scripts 22 and 29 characters (flagged by the second rule).

**Locators** (`kb/locator.py`). A locator names the conversion it was made against (tool, version, generation) and a place by
the structure of that conversion: a heading path and a paragraph number (`section`), a page and the block on it (`page`), or a
character offset (`offset`, for a page with no headings). It also carries a hash of the first twelve words at the place (lower
case, no punctuation, compatibility forms folded). The place holds only against the same conversion; against another, the words
find the passage again inside any block, and a different split into blocks does not matter. A passage in more than one block is
reported with how many, and the first is named. A passage that is gone is "not found"; nothing is guessed.

**Not covered.**
- The article extractor is set to leave comments out (the setting of the ten-page test); a discussion thread's comments therefore
  come from the plain extractor, which is what the size rule is for.
- The packages of the environment are fixed by the hashes when it is built, not checked file by file each time a page is
  converted (the scripts and the Python program are pinned, as for every tool). The same is true of poppler's libraries.
- `trafilatura` loads `dateutil`, which imports `ctypes`, which asks the system for its name and release; the sandbox refuses
  that, so `extract_traf.py` gives a fixed answer when it is refused rather than allowing it for every tool. Nothing else it
  needed was refused.
- A PDF is read for its text and nothing else: a scan of images gives almost no text and is marked partial, there is no OCR, and
  paragraphs are where poppler puts blank lines. Hyphenated words at a line end stay as they are.
- The plain extractor leaves out content that is hidden by the `hidden` attribute, `aria-hidden` or an inline style, as well as
  navigation, forms and scripts; the raw capture still has it, and the scan reports hidden text.
- The article extractor's time and memory grow with the number of tags, not the bytes (about 5 s and 275 MB for 125,000 tags, 31 s
  and 1.6 GB for a million), and the sandbox does not limit memory. Its wrapper therefore reads a page only up to 200,000 tags and
  10 MB, and says when it cut (which marks the book partial); the plain extractor still reads up to 10 MB. A page with more tags
  than that, or one nested more than 10,000 deep (the plain extractor then stops reading, since it could no longer tell which
  element a closing tag ends), is converted only as far as that.
- The plain extractor reads a page in the character set it declares only if that is a common text encoding (UTF-8, Latin-1 and the
  ISO-8859, Windows, KOI8, GB, Big5, EUC and Shift-JIS families); any other name is ignored and the page is read as UTF-8.
- `describe-tool pdftotext` runs the `pdftotext` that is first on your path (`-v`) and `otool` on it, outside the sandbox, to
  find its version and libraries. It first refuses any program that is not in a Homebrew package folder
  (`<prefix>/Cellar/<package>/<version>`), so nothing else is run, and it lists only whole package folders. Read the printed
  folders all the same.
- Locator search is bounded: text that grows more than four times when normalised, or more than 100 million normalised characters
  in one search, is refused with a reason and not searched, so text built to make the search slow cannot.
- If a tool's output keeps failing its checks, each try is kept as its own generation; after five from one version of a tool it is
  not run again on that version (a different version of the tool is, and so is the same version once you delete its failed
  outputs under `v/<version>/derived/<tool>/`; they are read-only, so `chmod -R u+w` first). Failures that file nothing (a tool that
  exits with an error or runs out of time) are not counted, and can be retried each time.
- Python's HTML parser holds every attribute of a tag in memory at once, so a page that is one enormous tag with millions of
  attributes can take about 300 times its size (10 MB gave 2 to 3 GB) in the plain extractor and in the scan, and the sandbox
  does not limit memory; the tool is killed or fails and the stage notes it. A page that hides text by a style sheet, a class,
  `font-size:0`, `opacity:0` or a position is not recognised by the plain extractor (the scan reports some of those); text hidden
  by an inline `display:none` or `visibility:hidden` is left out, and so is a style longer than 64 KB. An unclosed `<nav>`, `<form>`
  or `<aside>` hides the rest of the page from the plain extractor, as the HTML rules put the rest of the page inside it.
- The text match of a locator looks inside one block at a time, so a passage that a different conversion splits across two blocks
  is not found by text.
