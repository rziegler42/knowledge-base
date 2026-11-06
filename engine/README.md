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

`python3 -m kb process` runs the scan (`scan.scan_version(store, book, version)`) for every book, with conversion and indexing after it.

## Process, index and search

```sh
cd engine
python3 -m kb process                 # every version of every active book through scan, convert and index (or --book ID)
python3 -m kb search 'ocelot habits'  # keyword search; every word must match; --limit 1 to 50
python3 -m kb index                   # build the whole search index again from the books
python3 -m kb read BOOK_ID 'LOCATOR_JSON' --version V1 --chars 2000   # the text at a locator a search returned
```

`process` (`kb/process.py`) takes each version through the stages it has not finished, in order, and prints what it did. A
stage that is done is not run again; a result filed just before a stop (a scan, a conversion, the index rows) is adopted on
the next run and not made again; a stage that failed is tried again. A failed scan does not stop conversion, a failed
conversion stops that version only, and a system error in one book, or a book whose files are damaged, is reported and the
others go on. A version that has not been fetched, and a book that is not active (removed, weeded or a duplicate), are left alone.
Writing to the index takes a lock (`search.lock` in the index root) that other writers wait for, so a rebuild and a `process`
can run at the same time; the rest of `process` has no locks, so do not run two of them at once.

The index (`kb/index.py`) is one SQLite file in the index root, `search.sqlite`, with a row for each block of the conversion in
use of each converted version (a block longer than 2,000 characters has a row for each piece of it, cut at a word, each with an
`offset` locator for its own start, so a hit in a long page is read from there and not from the top of it), and everything a result shows copied in, so a search needs the index root and nothing else (the
bulk drive can be away). It can be thrown away: `index` writes a new one beside the old and renames it into place, and gives the
same results; a rebuild that fails to write leaves the old one, so does a library that is not there (the library's marker is
checked first), and a book or version that cannot be read is left out and counted as `failed` (the command then exits with 1).
A block, or a piece of one, whose text grows too much when normalised has no locator and is not indexed (it is counted, for each
piece). The counts of a rebuild name the `blocks` indexed and the `rows` written. An index file that holds
a trigger, a view or anything else this engine did not put there is refused when read or written, and a rebuild replaces it; an
empty file, which a crash can leave, is treated as no index. The index is derived and not a book format: one written by an older
version of the engine (the format number is in the file) is refused, searching or writing, with the instruction to run
`python3 -m kb index`, which builds it again. Every word of a query must be in one row, so for a block longer than a piece, in one
piece of it: two words 3,000 characters apart in the same long block do not match together. A piece is cut at a space or a line
break; a run of text with none (a very long word or address, or Chinese or Japanese written without spaces) is cut at 2,000
characters wherever that falls, so a query for a run that crosses the cut does not match.

`search` (`kb/search.py`) treats a query as text, never as syntax: it takes the words (letters and digits in any script, at most
20 of 100 characters each), puts each in quotes and passes the result as a bound parameter, so `OR`, `NEAR`, `col:word`, a quote
or SQL in a query is only a word to look for. Case, accents and compatibility forms do not matter. Results are ranked best first
with a fixed tie order, at most 50. The index is opened read-only and a search is stopped after 10 seconds. Each result is one
block, with the book id, title, version, the locator to find it again, an excerpt that begins with the untrusted marker (and
`untrusted: true`), the date the book was added, whether this is the book's current
version, the scan caveats of the version, how complete its conversion was (`structure` full, partial or flat, and `partial`, `compared`
and `reasons` from the extractor-size rule, so a partial extraction never looks complete), and the conversion it came from.

The excerpt is cut by the engine from the stored text: at most 400 characters on one line, around the first place a word of the
query is spelled (or from the start of the block), so a block of any size gives a short result and cannot put a line of its own
after the marker. The title is cleaned when it is indexed.

`read` (`kb/read.py`) gives the text at a locator, as a search result's `locator` and `version_id` name it (the version defaults
to the book's current one). The text is a window of at most `--chars` characters (100 to 20,000, default 2,000) of the converted
text, from the start of the block found, cut at a word, between a first line that is the untrusted marker and a last line that
is an end marker; a page can print those words itself, so the first and last lines are the ones that count. `next` is a locator
for where the following piece begins (`null` at the end), so reading on is following `next`; each is a locator of kind `offset`.
`status` says how it was found: `found` (the conversion the locator names is still recorded for the version, and its place
holds), `found_by_text` (the place no longer holds, or that conversion is gone: the passage was looked for by the words the
locator carries, in the conversion it names if that is still recorded and otherwise, or if it is not there, in the conversion now
in use, and `locator` is then a new one for the conversion read; a recorded conversion whose files have changed since it was
filed is a refusal and is not passed over), `not_found` (no text is given) or
`unknown_kind` (a locator of a kind this reader does not know: its raw value is shown, cleaned and cut to 500 characters, and
nothing is guessed). `citation` is one line: the title, the source address (or `arXiv:` and the id), the date retrieved, and the
sha256 of the file that was captured, from the version's records and cleaned; where a record is missing it says so, and an
address that is not a web address is shown as "non-web address", so a path on this machine cannot get into a citation. The result
also carries `caveats` (what the scan found) and `completeness` (`structure`, `partial`, `compared`, `reasons`), as a search
result does, so a partial extraction or a scan finding is not lost between a search and a read. The title and the citation are
text from outside, outside the marker lines: treat them as data, as the excerpt. Nothing it returns, and no message of a refusal,
holds a path to the library or any other path (library folders become `<library>`; absolute, `file:`, drive and home paths in a
message become `<path>`). The command exits 0 when it read, 1 when the passage was not found or the kind is not known, and 2 when
it refuses (a book that is not there or not active, a version not converted, records the engine did not write, something that
is not a locator). A refusal printed by the command before it reaches the book (no config, no library) is the engine's own and
can name the config path. A block built to grow under normalisation (text that is slow to compare) has no words for a locator, so
the place that goes on from it is named by its position only, and a reader following `next` reads through it. Each read loads
and checks the whole conversion of the version, so following `next` through a very large book costs the size of the book for each
piece.

A book that is removed, weeded or a duplicate leaves the search at the next `process` (or `index`), which takes out its rows
and puts its versions' `indexed` stage back to pending, so it is indexed again if it becomes active again; a book whose state
cannot be read, or is not one of those, keeps its rows, so a bulk drive that is away does not empty the index.

Not covered. A new title after a book was indexed shows in search only after `index` (`process` does this for a title taken from a page, because it indexes after it converts). A new version updates the current-version
flag of the book's other versions when it is indexed. `process` does not notice that the index file was deleted while the stage
says done: run `index`. The index is not in the book folders, so back it up with the index
root. Search reads text the tools produced and nothing checks that a passage is true; the marker is a prefix, so a consumer
must treat the whole excerpt and the title as data. The scan has no limit on how often a version that fails it is tried again
(each try is bounded by the tool's own limits).

## Converting what is captured

A version that has been fetched and scanned (or whose scan failed or was skipped) is converted to text by `kb/convert.py`
(`convert.convert_version(store, book, version)`, run for every book by `python3 -m kb process`). The converters are approved tools like the scan, run by the same sandboxed runner, on the stored original:

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
joined by blank lines. A web page's tool may also hand back the page's own `<title>` (the plain extractor does: the first one outside
an SVG, read to at most 2,000 characters). It is cleaned and cut to 300 characters like other text from outside, and when the
book has no title the conversion stage sets the book's title from it, preferring the conversion in use and then the other,
once. A title that was never closed is no title, and a title whose letters contain "untrustedtext" (it would imitate the
markers around text from outside; case, spacing, joiners, accents and compatibility forms such as fullwidth letters are folded away, a
look-alike letter from another alphabet is not) is dropped. This is a partial protection: the result is flagged `untrusted` as a whole. A title the book already has is never replaced, and the version it came from is noted in `metadata_source`. Each conversion is filed as a derived payload (`derived/<tool>/<n>/`) and recorded on the version
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
case, no punctuation, compatibility forms folded), looked for in the next 16,384 characters at most: a place with fewer words in
that stretch (a ruler of dots, a very long word) has the words that are there, or none, and is then named by its first 64 characters. The place holds only against the same conversion; against another, the words
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
  ISO-8859, Windows, KOI8, GB, Big5, EUC and Shift-JIS families); any other name is ignored. A page with no usable declaration is
  read as UTF-8 if it is valid UTF-8 (a page cut by the read limit inside its last character still is) and as Windows-1252 if it
  is not, the way a browser reads an old page; the five bytes Windows-1252 leaves undefined become the replacement character. The
  rule cannot tell a page cut by the read limit from a complete one, so an undeclared Windows-1252 page whose only non-ASCII byte is
  its last byte is read as UTF-8 and ends in a replacement character; and a UTF-8 page with one stray bad byte and no declaration
  is read wholly as Windows-1252.
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
