# Engine

The knowledge-base engine, a standalone Python program. It holds the library on disk. It does not depend on the project
workbench except for model calls, which this first slice does not make. The design is in
[`docs/specs/`](../docs/specs/README.md) and the build plan is
[`docs/plans/2026-11-05-first-slice-capture-search-read.md`](../docs/plans/2026-11-05-first-slice-capture-search-read.md).

The engine sets up a library, captures web pages and arXiv papers, scans them, converts them to text, indexes the text, searches
it by keyword and reads a passage back by locator. Requirements: Python 3.15 (the version it was written and tested with); the engine itself uses only the standard library. Two
of the converters need more, and the conversion section below says what: the pinned packages in `engine/.venv` for the article
extractor, and poppler for PDFs.

## Run the tests

From the repository root:

```sh
python3 -m unittest engine.tests.test_setup engine.tests.test_store engine.tests.test_stages engine.tests.test_textutil \
    engine.tests.test_capture_url engine.tests.test_capture_arxiv engine.tests.test_scan engine.tests.test_convert_run
engine/.venv/bin/python -m unittest engine.tests.test_convert engine.tests.test_search engine.tests.test_read   # these use the pinned environment
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
- Every title the store files, from any source (an arXiv record, a page, a later import), is made by one rule, `textutil.title`: it
  is cleaned and cut to 500 characters like other text from outside, and it is empty when its letters hold the words of an
  untrusted-text marker (see the page title under Conversion for what is folded and what is not). `Store.create_book` and
  `Store.set_metadata` apply it, and so does the arXiv parser, so the book's title and the version's `source` record agree. A true title that holds both words side by side (a paper about "untrusted text") is stored empty too,
  because the guard cannot tell it from an imitation; an arXiv book has no second source to fill it, a web page does.
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
from the file. They never stop a book being filed. A count is written up to 1,000,000: a file with more matches gives 1,000,000, which
means "at least that many", and the reader of the scan's output takes no larger number. A scan that cannot run marks the stage failed with the reason.

**No caveat does not mean the file is safe.** It is a pattern scan and not a PDF reader, and it says only what it found. It reads
the file forward, object by object (below), takes the whole dictionary of each stream, decodes deflate, ASCII85 and hex filters (also layered),
and reports `scan_incomplete` for anything it could not read: a filter it does not decode (LZW, run-length, crypt), a predictor
it does not undo or parameters it cannot read with certainty (below), deflate data that is damaged, cut short or compressed again inside (what comes out begins like a zlib stream of any window size and a trial decode of its first 16 bytes does not fail: random pixels or a font that only begin like a header are not that), a filter
declared that it did not tie to a stream it read, or a file or page larger than its limits. A deflate image stream that says it
is an image (its dictionary holds `/Subtype /Image`, and `/Type /XObject` wherever a type is given and at least once, and none of
the keys that an object stream or a cross-reference stream cannot be read without: `/N`, `/First`, `/Extends`, `/W`, `/Size`,
`/Index`; the scan does not parse dictionaries, so the words may sit in a string or a nested dictionary, and a dictionary can say
what it likes, but a real container cannot leave those keys out) and holds more than two million bytes once decoded
is not called incomplete, because a large figure is not where a script is: it is counted as `large_image_streams`, and the first
two million bytes of it are scanned like any stream. Only when deflate is the one and last of its filters, so that nothing after
it was left undone, when the dictionary names a filter once (a second `/Filter` might be the real list), and when what comes out
does not begin like deflate data of any window size, and when its bytes do not hold the word `stream` (an honest compressed image
never does; a file that hides a stream marker in a string, so that the scan takes the bytes of two streams for one, does). An
object stream or a cross-reference stream cannot pass as an image, by carrying the words or by forging its type; an image may leave out
its `/Type` (the format makes it optional), and one that gives a type other than `/XObject` is not an image. **What this leaves:** a script placed after the
first two million bytes of a stream that only claims to be an image (an XObject with `/Subtype /Image`) is reported as a large
image and not as a script, which is why the caveat says that code after the first part would not be found. A damaged image, one
in a filter the scan does not read, one with other filters after deflate, one that is compressed again inside, and images beyond
the limit on the work the scan does on what it decodes (see below), are still `scan_incomplete`. **Limits.** The scan decodes at most 2,000,000 bytes of one stream, 500,000 streams and 2,500 million units of work on what it
decodes in all, reads through at most 8 filters on one stream (each layer is a decode, and only the last one's output is charged: a
longer chain is `scan_incomplete`), and undoes a predictor over at most 20 million bytes in a file (that work is slow Python: 0.15 s a
megabyte with Paeth rows). Every filter that comes after a deflate costs 20 units for each byte it reads, because its output may be nothing (a
layer of two million bytes of empty deflate blocks takes 0.1 s and gives no bytes; ASCII85 or hex first, as in old files, is not
charged: it is bounded by the stream), and the scan stops between streams after 25
seconds, as `scan_incomplete` (the sandbox ends it at 60). A unit is a byte, a `#` costs 135 units more and a `/` 35 more: a piece of nothing but escapes takes thirty
times as long to unescape as ordinary text, and one that is all matches ten times as long to collect, so the limit holds the time to
some ten seconds whatever the content (the worst of the pieces measured took 3.8 ns a unit; a 50 MB file of escapes, of matches, of
Paeth-predicted figures, of large images, of tiny streams and of expanding streams was measured at 12 s at most and 180 MB at most). A
file past the limit on streams or work is `scan_incomplete`. When the predictor budget is spent, a picture is not an incomplete scan
(pictures with PNG predictors are common): what was decoded before the predictor is read, and the picture is counted in
`large_image_streams`, of which only the first part was checked; a stream that is not a picture (an object stream behind a
predictor) is `scan_incomplete`. What each piece matches is counted as the matches come and the piece is dropped, so memory does not
grow with the number of figures or of matches.
**Predictors.** A stream is
decoded whatever its dictionary says it is, and its predictor is undone before it is read: the PNG predictors (10 to 15; each row
says its own filter, so the number does not matter) and the TIFF predictor (2, at 8 bits), with the colours, bits and columns in the
parameters (the defaults where they are not given). A real viewer reads an object stream through a predictor, so a dictionary that
says `/Type /XRef` or `/Subtype /Image` is not taken at its word and its stream skipped, as it was before. Anything else is
`scan_incomplete`, never a skip and never a guess: another predictor, bits or colours that make no sense, a row type that is no PNG
filter, a row longer than four million bytes, more than two million passes over rows of predicted data in a file (a row is charged one for each byte of a pixel, so that wide
pixels cannot make a cheap file slow), and parameters that are a
reference, given twice, not a whole number, not direct, or more entries than filters. What was decoded before a predictor that could not
be undone is still read for the patterns, and so are the bytes from before a predictor that was undone, because the scan reads a
dictionary as text and a decoy `/DecodeParms` in a string would otherwise make it undo a predictor that a viewer never applies. The structure of a dictionary is read from its text with `#xx` read as the letter it spells, except where that letter is white
space, a delimiter, `%` or `#` itself: `/A#3E#3E` is one name, not a name and the end of a dictionary, and a reader that turned it
into the brackets would see a structure no viewer sees. A comment (`%`) in the parameters is
`scan_incomplete`, because a comment can hold the brackets that end the dictionary or sit between a number and `0 R`, and a number that
runs into letters or a hash is not a number; and a list of filters that holds anything but names (a comment, a string, an array, a
number, an escaped bracket) is `scan_incomplete` too, because the list read ends at the first bracket the text shows, which any of
those can put before the real end. A dictionary with more than one `/Filter` key is `scan_incomplete` too: the text is read without knowing strings, so a decoy
in a string could say an image codec, which the scan does not look into, ahead of the real filter. A picture with a predictor counts against the scan's limits on streams, work and bytes undone, as any stream does (a test builds twenty
figures of 950,000 bytes and 1,500 and 2,500 small ones that give no caveat).
**Where a match sits.** The patterns (`/JS`, `/JavaScript`, `/Launch` and the others) are three to eleven bytes, and in the compressed
bytes and the pixels of a large file they turn up by chance, or are spelled by a flat patch of one colour (#2F4A53 is `/JS`). So a
match is named by where it sits. The **binary places** are the raw and the decoded bytes of an image (a stream with `/Subtype
/Image` and none of the keys of a container, whatever its `/Type`), the raw bytes of a stream with an image codec (`DCTDecode`,
`JPXDecode`, `CCITTFaxDecode`, `JBIG2Decode`), and the raw bytes of a stream the scan decoded (to its end, or as far as its limits
allowed); every other place (the file outside streams, a stream dictionary, an unfiltered stream, the decoded content of a stream
that is not a picture, such as an object stream, and the bytes of a stream the scan could not decode or did not reach) is a **text
place**. A match in a text place is reported as its own kind. A match in a binary place is too if it has **the
shape of a use**: the twelve bytes before it (after escapes are undone) are printable ASCII or white space other than a null, as in a dictionary, and the
byte after it is white space, `(` or `<` (the start of its value; a digit cannot follow, it would continue the name; a slash, `>` or `[`
does not count, which is what keeps a flat patch of the colour that spells `/JS` weak). Any other match in a binary place is
counted in **`pattern_in_binary_data`**: "usually a coincidence, and not read as a viewer would". Nothing is dropped: the two
counts together are what the scan counted before. The start of the data counts as printable and the end of it is not a value start;
neighbouring streams do not lend each other a shape. What this leaves: a real action placed in image bytes behind bytes that are
not syntax (a stream extent that a viewer does not see the way the scan does), or written compactly with no white space after the
name (`<</S/Launch/F(x)>>`), is reported under the weaker name, never as nothing;
and a flat patch of the colour that spells a pattern, followed by a byte that begins a value, keeps its own kind (the end of such a
patch is a space or a black pixel only by luck).
**How it finds a stream.** The scan reads the file forward. In the space between objects it looks for an `N G obj` header (and for
`trailer`); from a header it reads the object's value with a reader that knows literal strings (nesting, escapes, octal), hex
strings, comments, names, arrays and dictionaries, takes the exact text of the dictionary, and, if the word `stream` and a line end
follow, the data up to the first `endstream`. So a bracket, the word `stream` or `endstream`, or text that looks like an object
inside a string or a comment of a dictionary is part of that string and no longer steers the scan (it used to: a string holding a
fake `>>`, `stream` and a small deflate stream made the scan read the fake one and take the real stream for part of it, and an
object stream with a script in it gave no caveat at all). It is `scan_incomplete` when the scan cannot account for something: the
word `stream` and a line end where no object it read is (in the space between objects, not in a string or in data); an object it
cannot read to its end, or whose brackets nest more than 100 deep, or whose value is the next object's header; an object value or
stream dictionary that holds the word `obj` or `endobj` (every object header holds `obj`, however its numbers are written, and a
viewer does not need an `endobj`: this is what a real object swallowed into a string looks like); a stream dictionary longer than
16,384 bytes; a stream with no `endstream` or with the word `stream` and no line end after it; a `/Filter` key that is not in a
dictionary it read; more than a million objects; or more than twelve million steps in all. It stops reading after 20 objects it
could not finish, and says so (a file of broken objects would otherwise have it read the same long stretch again and again: 4 MB of
them took 44 seconds). A real compressed stream swallowed into the data of a fake one is found by the check on `/Filter` keys.
**What this leaves:** the scan does not follow the cross-reference table or `/Length` as a viewer does; a viewer that finds an object
by its offset and the scan that reads the file in order can disagree about where an object is in a file written to make them
disagree, and the cases found are the ones above. The data of a stream ends at the first `endstream`, so a stream that holds that
word in its middle, with its real end after it, is cut there: a deflate stream cut there is `scan_incomplete`, and so is an
ASCII85 stream with no `~>` or a hex stream with no `>` in what the scan has (the letters of the word are ASCII85 digits). A stream whose data goes on after its end (after the end of
the deflate data, after `~>`, after `>`) with anything but white space is `scan_incomplete` too: its length is not what the scan took it
to be. A stream needs an `N G obj` header: a dictionary and `stream`
without one is `scan_incomplete`.
A page's hidden text is found only when it is hidden by the `hidden` attribute or an inline style, not by a stylesheet, by
position or by colour.

`python3 -m kb process` runs the scan (`scan.scan_version(store, book, version)`) for every book, with conversion and indexing after it.

## Process, index and search

```sh
cd engine
python3 -m kb process                 # every version of every active book through scan, convert and index (or --book ID)
python3 -m kb search 'ocelot habits'  # keyword search; every word must match; --limit 1 to 50
python3 -m kb index                   # build the whole search index again from the books
python3 -m kb reconvert [--book ID] [--scan]   # make the conversion (and the index) of books again at the next `process`
python3 -m kb read BOOK_ID 'LOCATOR_JSON' --version V1 --chars 2000   # the text at a locator a search returned
```

`process` (`kb/process.py`) takes each version through the stages it has not finished, in order, and prints what it did. A
stage that is done is not run again; a result filed just before a stop (a scan, a conversion, the index rows) is adopted on
the next run and not made again; a stage that failed is tried again. A failed scan does not stop conversion, a failed
conversion stops that version only, and a system error in one book, or a book whose files are damaged, is reported and the
others go on. A version that has not been fetched, and a book that is not active (removed, weeded or a duplicate), are left alone.
Writing to the index takes a lock (`search.lock` in the index root) that other writers wait for, so a rebuild and a `process`
can run at the same time; the rest of `process` has no locks, so do not run two of them at once.

**Making a book again** (`python3 -m kb reconvert [--book ID ...] [--scan]`, `stages.redo_books`). A stage that is done is not run
again, so after a tool was changed and you approved the new entry, the books already in the library keep what the old tool made.
`reconvert` puts the conversion and the index of the active books named (all, if none is named) back to pending, with `--scan`
the scan as well (and so all three), and prints what it put back, version by version. It deletes nothing: the next `process` makes
the conversion again, and each tool is run again only if its **version** is not the one that made the output already filed; the
output of another version is not adopted, it is kept beside the new one as the next generation (`derived/<tool>/2`), and a tool
whose version did not change is not run again. So a tool whose script changes must carry a new version: the plain extractor carries
the engine's version (`kb.__version__`, now 0.0.2), the scan tool a label of its own (`approvals.SCAN_VERSION`, now 0.0.5, so that
changing the scan does not re-label and re-convert the extractor), the article extractor's wrapper the number after `kb` in its
version, and a test fails when a script's text changes without a new label. A version that has not been fetched, and a book that is
not active, are left alone; a book named that is not there is a refusal before anything is changed; a version whose state cannot
be read is reported (exit code 1) and the others go on. Every version of a book is put back, not only the current one. **Put the new
tool entries in the config first** (`describe-tool all`, then `tools`), and replace the list rather than add to it: the conversion
uses the first entry of that name that handles the kind of file, so an old entry listed first would be used and fail. `reconvert`
warns on the error stream when the first `kb-html-std` entry is not at this engine's version (or, with `--scan`, when `kb-scan` is
not approved at the scan tool's own version), because `process` would then finish the stage with the other extractor alone, as it does with any tool that
is not approved, and you would have to run `reconvert` again. If the new conversion cannot be made (the tool is not approved, or
it fails), `process` marks the stage failed and says so in its report, the old conversion stays the one in use and its rows stay
searchable until a rebuild (`index`) takes the version out of the index; read the report. Not covered: the old outputs stay on disk (the cost is their size); between
`reconvert` and `process` the search still answers from the old rows, which name the old conversion (a read from one of their
locators finds the passage by its words in the new one), but a rebuild (`index`) leaves the books put back out of the index until
`process` has run; the locators of the old conversion are found again by their words in the new one
(`found_by_text`), not by their place.

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
after the marker. The title is made by the title rule (`textutil.title`) when it is indexed, with the library's folders taken out
of it before and after cleaning, and again when a result is built, so a title already in an older index, or one in a book file that
was edited by hand, shows empty if it holds the words of a marker; the folders are taken out of an indexed title when it is
indexed, so an older index shows one after `python3 -m kb index`.

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
nothing is guessed). `citation` is one line, `"<title>". <address>. Retrieved <date>. sha256 <digest>`: the title between ASCII quotation marks (a
quotation mark in the title becomes an apostrophe, so the title ends at the next quotation mark whatever it says, and what follows is
the engine's own fields; a book with no title shows `"untitled"`), the source address (or `arXiv:` and the id), the date retrieved, and the
sha256 of the file that was captured, from the version's records and cleaned; where a record is missing it says so, and an
address that is not a web address is shown as "non-web address", so a path on this machine cannot get into a citation; a quotation mark or a space in a web address is written `%22` or `%20`, so an address cannot start fields of its own. A backslash at the end of a title is left out of the citation (a closing quotation mark after it would look escaped to a reader that honours backslash escapes); the title in the result keeps it. The result
also carries `caveats` (what the scan found) and `completeness` (`structure`, `partial`, `compared`, `reasons`), as a search
result does, so a partial extraction or a scan finding is not lost between a search and a read. The title (made by the same
rule, cut to 200 characters) and the citation are text from outside, outside the marker lines: treat them as data, as the excerpt. Nothing it returns, and no message of a refusal,
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

## Calling a model

The engine can send one prompt to a model you have listed and take back one checked answer. It does this through the workbench's
Ollama bridge (`wb run ask-ollama ask`), which it starts as a separate program with an argument list and no shell; the prompt goes
in on standard input and never as an argument. The bridge, not the engine, holds the server's address, in the workbench's own
endpoint file. The engine prefers no model: which entry does which kind of work is the `tasks` setting of the config (see
[Cards](#cards)). Nothing here retries, batches or makes embeddings, and no stage calls a model on its own; only the `cards` command
and `model-try` do.

The registry is the keys `models` and `models_on` of the owner-only config (and `tasks`, described under Cards). Edit the file by
hand; nothing in the engine writes it:

```json
"models_on": true,
"models": {"local": {"bridge": "ask-ollama", "server": "<server name>", "model": "<model name>",
                     "max_output": 500, "thinking": "off", "timeout": 120}}
```

- A name is lower-case letters, digits, `_` and `-`. `server` and `model` are the names the bridge's endpoint file knows (a model
  name may have `/`-joined parts, up to 128 characters). `max_output`, `thinking` (`on` or `off`) and `timeout` (1 to 3600
  seconds) are optional. Every value is checked against a strict pattern before it reaches the command line, and one wrong entry
  refuses the whole registry. With `models_on` missing or anything but `true`, model work is off.
- `python3 -m kb models` lists the names, the options, the switch and whether the `wb` launcher is found. It makes no call and
  prints no server or model name.
- `printf '<prompt>' | python3 -m kb model-try <name>` sends the prompt (at most 256 KB of UTF-8) and prints the answer. The answer
  is the model's text, so it is printed between the untrusted-text markers, with a record of the model the server reported, the
  registry name, the prompt version, the UTC date and the token counts. If the answer holds the words of a marker it is withheld.
  `model-try` asks for one JSON object with one text key, using the schema `engine/kb/schemas/model-try.json`.
- In code, `kb.models.run_job` takes a `Job`: a name, a prompt version, the shape of the JSON object it expects (each key a
  `string`, `strings`, `integer` or `boolean` with its limits) and optionally a schema file name. An answer is refused unless it
  is one JSON object with exactly those keys; its text is cleaned of control and hidden characters, and a value that is too long
  is refused and not cut. A schema is a tracked file in `engine/kb/schemas/`, passed to the bridge by its path relative to the
  project root; the bridge reads that one file and nothing else, and refuses a path with a link in it.
- A call that runs past its time limit (the entry's `timeout`, 600 s by default, plus 15 s), or prints more than 2 MB, is killed
  with whatever it started. A reply must be bridge contract version 2: `contract` the integer 2, `ok` a real boolean, `vendor`
  `ollama`, a valid model name, non-empty text and both token counts.

Not covered. Starting the bridge costs about a tenth of a second, and a call is dominated by the server loading and running the
model. A server on plain HTTP without authentication gets the prompt in the clear over your network; the bridge warns of such a server
(`wb run ask-ollama check` prints the warning and makes no connection). Text between the markers is still the model's text: a program that shows it must keep the markers
around it. The check of a schema file and the bridge's read of it are two steps, so a file swapped between them is checked
again only by the bridge.

## Cards

A card is a short entry for one book, written by a model: what the book is about, what it is useful for, key ideas, and a
description of the problem it addresses and its approach in words of no field. The engine makes one on command, for the books you
name. It does not make one when a book is filed, and `process` does not make one. They can be searched by keyword (below).

```sh
cd engine
python3 -m kb cards --book BOOK_ID [--book BOOK_ID ...] [--again]
python3 -m kb card-show BOOK_ID [--version v1] [--generation 1]
```

- **Which model does which work is your setting.** The config key `tasks` names, for each kind of work the engine knows, the
  entry of `models` that does it. The kinds are `card-notes` (the notes on one piece of a book), `card` (the card itself) and
  `card-check` (whether the note an item cites supports it). The engine names no model and has no default: a kind of work with no
  setting, a setting that names an unlisted entry, or the switch `models_on` off is refused before anything is sent, with the key
  to set in the message. Another user sets other models, or one model for all. There is no option on the command line to name a
  model, a server or a class.

  ```json
  "tasks": {"card-notes": "<name of an entry of models>", "card": "<name of an entry of models>", "card-check": "<name of an entry of models>"}
  ```

- **What is sent.** The text of each named book goes to the models you set, over the link the registry names, which for an
  unauthenticated server on plain HTTP is in the clear on your network. Nothing is sent for a book that is skipped or that gets a
  card from its metadata. `cards` needs at least one `--book`; there is no way to cover the whole library with one command.
- **Reading a book.** The converted text is cut into pieces of at most 20,000 bytes that end at a block boundary. Every piece,
  of a book of one piece too, gets notes from the `card-notes` task, and then the `card` task makes the card from the title, the
  outline of the headings and the notes (a book of one piece is also given its text). A book of more than 12 pieces is sampled
  (12 evenly spaced ones, always the first and last) and the card says so. The number is the config key `card_pieces`, a whole
  number from 1 to 20 (default 12, which this setting does not change; with 1 only the first piece is read, with more the first and the
  last always are); a larger number reads more pieces of a long book and costs one notes call for each piece more. The card call is
  given all the notes (at most about 1.6 KB for a piece), so 20 is the largest number that keeps the card prompt, at its worst about
  32 KB with the rules and the outline, inside the window of a model of 16,384 tokens; with a smaller window the bridge may refuse
  the call and the book is reported as failed. `cards` refuses a wrong value before it tries any book. The report has `pieces`
  (read) and `book_pieces` (the book has), and a card that did not read every piece says so in its reasons. A block larger than a piece is cut into pieces of 5,000
  characters, so a page that converts to one very large block makes more calls than its size needs.
- **Notes with quotes.** The notes on a piece are up to four points, each with a quote of the piece that supports it: two lists
  of the same length (a reply with lists of unequal length is refused like any other badly shaped reply). The engine checks each
  quote against the piece it names (`kb/quotes.py`): both are put in one form (Unicode compatibility form, case folded, the soft
  hyphen taken out, other hyphens made the plain hyphen, white space made one space), a word broken at the end of a line (a hyphen
  between two letters followed by white space, which is how a reply shows a line break) may be joined or kept, and the quote must
  be at least 12 characters in that form with at least 8 letters or digits in it (so a run of dots or dashes proves nothing), at
  most 240 as written, and occur in that piece and no other. A point whose quote occurs is marked `verified`, any other
  `unverified` (a quote longer than 240 characters, up to 600, makes its point unverified and does not refuse the reply; an empty
  quote does refuse it), and the card call is given the points with these marks and their numbers (`[2.1 verified]`) and not the
  quotes. The prompt tells the model not to quote the title or a heading, but a heading is a block of the piece, so a quote of a
  heading occurs. A verified quote shows that a point is in the book, not that it is right.
  The report of `cards` gives `points` and `verified`, the counts over the notes of the book (none for a card made from the
  metadata).
- **Marks on the card (format 2).** The card call is told the kind of source (paper, page, book) and uses its word, and is asked
  for a support for each topic, key idea and caveat: the one or two notes that best state it (such as
  `1.1 3.2`), or `inferred` if it is the model's own inference, or `none`. The summary and the five neutral fields are asked for as
  sentences, in three lists of the same length: the part each belongs to (`summary`, `problem`, `approach`, `needs`, `provides` or
  `limits`), the sentence, and the notes that state it. The prompt asks for at most 5 sentences of the summary and 2 of each other
  part, a reply with more than 8 and 4 is refused, and only the first 5 and 3 are put to the check (the card call is version `v5`,
  so a journal made with the earlier prompt is stale). Only a sentence of `limits` may say `inferred`; every other sentence must cite
  notes, and `none` for a sentence is refused, except for `limits`, where it is accepted and the sentence is dropped. A support in any other form refuses the answer, and so does a list of supports or
  of sentences of the wrong length. The engine then marks each item: `stated` if its checks confirmed it (the next
  bullet; the card keeps the confirmed note and its quote, up to 240 characters), which the model's word alone cannot make it;
  `inferred` if the model said so, which is its own word and is not checked; and an item with neither is dropped (a dropped limit
  leaves its field empty). A sentence is kept when its check confirmed it and it does not repeat a sentence kept before it in its
  part (the same rule as the second round's) and the part still fits the limit of its length; the sentences kept for a part, joined
  with a space, are the part, and a part that keeps none is empty, which the card says in its reasons and so is partial. The
  report of `cards` gives, for each of the six parts, the sentences asked for and kept and why the rest were dropped (cut past the
  first few, `none`, no pair, not confirmed, a repeat, or too long), and `empty`, the parts that kept none. The prompts ask for at most 7 key ideas and 12 topics (the limits are 8 and 20). A card with fewer than
  three key ideas left is marked partial and says why, and nothing is added to make up the number. The card holds a `grounding`
  record with a mark, the notes and the quote for each kept item and the number dropped for each field, and its generation records
  carry the counts of points and verified points of each piece's notes, and of items checked and supported by each check call.
  `card-show` prints the mark after each topic, key idea, caveat and limit (`[stated]` or `[inferred]`), and the quote of a stated
  key idea, caveat or limit under its item, as untrusted text. A card of format 1, made before this, is read, searched and shown as
  it was, with one line saying `grounding: not checked`.
  A card may also carry `grounding.sentences`, a record for the summary and the five neutral fields: for each, the sentences kept
  (the text, the mark, the notes and the quote of a stated one) and the number dropped, so that the sentences joined with a space are
  exactly the field. With it, the limit has no entry of its own, any of the six fields may be empty (a card with no summary is
  partial and says why), `card-show` prints a mark after each sentence and the quote of a stated one under it, a result counts the
  marks of the sentences with the others, and `card-sample` takes a sentence as an item. The card call makes this form.
- **Is the note about the item? The check (task `card-check`).** A verified quote shows that a claim is in the book, not that the
  note it belongs to supports the item that cites it: in the first live run one note was cited for nearly every item. So each item
  that cites notes is paired (a sentence of the summary or a neutral field is paired with the first verified note it cites, with no
  word in common required, since a neutral description is written without the words of a field; the rest of this paragraph is the
  pairing of a topic, key idea or caveat) with the verified note it cites that shares most content words with it (words of four letters or
  more, compared by their first five letters; the first cited on a tie; an item with no content word of its own is paired with the
  first verified note and left to the model). An item with no such note is dropped. The pairs go ten to a call to the model that
  the config names for `card-check`, as the item, the note's point and its quote in a section of data; it answers `supports`,
  `partly` or `no` for each, and any other word, or a list of a different length, refuses the answer (kept aside, as the others).
  Only `supports` makes the item stated; `partly` and `no` drop it. An item the model calls an inference is not checked, and a
  card with no item that cites a note makes no check call. The check model should not be the one that writes the card. Set it
  with the others:

  ```json
  "tasks": {"card-notes": "<name>", "card": "<name>", "card-check": "<name>"}
  ```

  `cards` refuses before it tries any book, and sends nothing, if any of the three tasks has no setting. The report of `cards` has,
  for each book, `checked` (items put to the check), `supported`, `partly`, `no`, and `unpaired` (items that cite notes but had no
  pair, so were dropped without a model being asked). Aliases of a topic that share no four-letter word with the note it cites are
  among those dropped; expect fewer topics than before.
- **A second round for a list that was cut off or lost most of its items (task `card-more`, optional).** Some cards fill a list to
  the number asked, so there may have been more; some lose most of a list to the check. If the config sets `card-more`, a card is
  offered one more call, to that model, for its topics and key ideas when (`full`) the card model gave as many items as were
  asked (12 topics, 7 key ideas), or (`lost`) the checks kept fewer than half of the items it gave and dropped at least two, or
  (`thin`, key ideas only) fewer than three key ideas were kept, and the list has a free place (the ceilings are 20 and 8). The
  call is given the title, the outline, the notes and the items already kept, and asks for at most 8 more topics or 4 more key
  ideas, each citing the notes that state it. An item the round adds is kept only as a `stated` item: it goes through the same pairing
  and the same check as every item of the card call, it must not repeat a kept item (three quarters of its content words, counted as
  the pairing counts them, are in the other, whichever has fewer) and it must fit in the free places. The round asks for no
  `inferred` item and refuses a reply that marks one. A card is offered one round at most. If the call fails, or its reply is
  refused, the card is made as the first round left it, and the report says so (the reply is not kept aside, as a card's is). The
  grounding record of a card names the items the round added (`added`: the positions in the topics and in the key ideas), so that
  `card-sample` can draw them. Without a setting for `card-more` the card is made as before and the report says the round was off; a
  name that is not in the registry refuses `cards` before anything is sent. The report has `more`: `status` (`off`, `not needed`,
  `ran`, `refused` or `failed`), a `reason`, and for each list offered the round why, how many items the model gave and the checks
  kept, the free places, how many were asked, how many were added and how many were dropped (`unpaired`, `repeat`, `not_confirmed`,
  `over`; a reply with more items than were asked is cut at the number asked before the check, and the cut ones count as `over`).
  The book's `checked`, `supported`, `partly`, `no` and `unpaired` include the round's items; the per-list counts of `more` show the
  round's share.

  ```json
  "tasks": {"card-notes": "<name>", "card": "<name>", "card-check": "<name>", "card-more": "<name>"}
  ```

- **A card in the making can be stopped and taken up again (`kb/cardstate.py`).** A card is made by a fixed sequence of calls (the notes
  of each piece, the card, the checks, a second round and its checks), and what it is depends only on the answers and on the book. A
  *journal* keeps the answer to each call that has succeeded: the job, the model entry, the checked answer and the record of how it was
  made. `cardmake.make_model_part` can be given a journal (`cardmake.new_journal`): it adds each call as it is made, and a call that is
  already in the journal is not made again, its saved answer being checked again as a reply would be, so a card made again from a
  journal is the card it would have been, with the same records. With `allow`, a set of model entries that the caller is serving now,
  the next call that is for another entry and is not in the journal raises `cardmake.Pause` before anything is sent, so a caller
  that works through the models one at a time can stop a card at a model boundary and go on with it later (`Pause` is not a
  `KbError`, so a caller must catch it itself). A journal is refused as stale unless its header is what the card is being made with:
  the book, the version and the conversion in use (which the caller gives as `identity`), the title, the kind of source, the number of
  pieces the book has and the number read, the model entry of each kind of work and the server and model behind it, the prompt version
  of each job, and a digest of the outline and of the text of the pieces read. A saved call that is not the call being made, a saved
  answer that is not valid (checked again as a reply is), a journal that cannot be saved, and calls in the journal that the card does
  not make are refused too, and a fault of the journal in the second round is a refusal, not a "failed" round. The file is
  `card-runs/<run>/<book>-<version>.json` in the index root: derived and disposable, so deleting it (`cardstate.remove` also deletes
  what a crash left beside it) loses no card; made private to the user (the folders 700, the file 600), written under a temporary name
  and put in place with one rename, and refused if a path is a link, the file is a pipe, another user's, readable by others or over
  8 MiB, or the text is not exactly the shape described. Its text is from books and models and is untrusted. The notes and the card
  are used from it only as the data sections of prompts, as before, but the verdicts of the checks, the support lists and the records are
  taken as they were saved: the journal is not signed, so whoever can write the file can say what a check said. The folder that only
  the user can enter is its whole protection. No command uses it yet; the queue of `cards-queue` will.
- **What a model is told.** The title, the outline, each piece of text and each note are given as data in sections of their own,
  between delimiters that carry a random token made for the call (made again if any input holds it); the rules name the token, say
  that a line with another token is data and that nothing in a section is an instruction, and ask for English whatever the
  language of the book. The prompts ask for fewer items than each list may hold (`cardmake.ASKED`), because a model writes a few
  more than it is told. An answer must be one JSON object with exactly the keys of the card, within its limits, or it is refused
  and no card is made; nothing is retried.
- **Small books.** A version with no conversion (a conversion that failed or was skipped), or with less converted text than
  `card_min_chars` (default 1,000 characters), gets a card from its metadata with no model call, marked partial. Such a card counts
  as the book's card, so `cards` skips the book later unless you give `--again`, which adds another generation. A version not yet
  fetched or whose conversion is still pending is refused: run `process` first.
- **The card file.** `books/.../v/<version>/derived/card/<n>/card.json`, filed through the incoming area, read-only and marked
  untrusted, one new number for each card; an earlier card is never changed and the newest is the active one. The mechanical part
  (book, version, title, kind, shelf, type of the original, a short list of source facts, the scan's status and findings, how
  complete the conversion was) comes from the manifest and the scan, and no model writes it. The model part holds the summary, the
  uses, topics, adjacent topics, key ideas, the five neutral fields and caveats. A card with no model part says so. Every card is
  checked on reading: exact keys and types, text already clean, a source address only if it is a web address with no user name, and
  a hash check of the payload.
- **When a card is marked partial.** The mark means the card describes less of the work than the book holds, and its reasons are
  listed with it: there is no conversion of the text, the conversion is partial (the extractors disagree, or the text was cut), a
  long book was sampled, the converted text is below the cutoff, or the card has no model part. A conversion with no headings
  (`flat`, which every PDF is) is not a reason: the card records the structure as `flat` and `card-show` prints it, and an agent
  can weigh it. Cards made before 2026-11-07 for a flat PDF carry the older reason and stay as they were made.
- **`card-show`.** It prints the facts that cannot hold free text (ids, shelf, the counts and the models used) as JSON, and the text
  of the card between the markers of a search result. A piece of text that holds the words of an untrusted-text marker is withheld.
- **`cards` reports** one line of JSON for each book: carded, skipped or failed, the generation, whether the card is partial, the
  pieces and calls, the model of each kind of work, the reason, and `kept` (see below). It never prints card text. One book failing
  does not stop the others, and the exit code is 1 if any failed.
- **A refused answer is kept aside.** When a model answers and the answer is refused for its shape (a list longer than its limit, a
  missing key, text that is not JSON), no card is made, and the answer is written to a file in the folder `refused` of the index
  root, so you can read what the model wrote. The failed report names the file in `kept` (the name, not the folder). The file is
  JSON with the book, version, job, the model entry and prompt version, the date, the reason and the answer; everything outside
  ASCII is escaped, so a control or escape character in the answer cannot reach your terminal when you read the file with `cat`; and
  an answer is cut at 256 K characters. It is written with mode 600 in a folder with mode 700, never over a file that exists, and
  without following a link at the last step of the path to the index root and to `refused` (the library's roots are checked for
  links when it is set up). The folder must be yours with no access for group or others in its mode bits; an access list that macOS
  can add is not looked at. A file that cannot be written whole (the disk is full) is removed. At most 200 files are kept and
  nothing deletes them; delete them as you like. If the answer cannot be kept (the folder is a link, others can enter it, it is
  full, the write failed), the report says so in its reason and the refusal stands. Only a refused shape keeps an answer: a failed
  call, a missing setting or a skipped book keeps nothing.

### Cards for many books: a queue that works through the models one at a time

`cards` goes through every model for one book before it starts the next. For many books that loads each model again and again.
`cards-queue` makes the cards of many books by visiting each model once for all the books that are waiting for it.

```sh
cd engine
python3 -m kb cards-queue plan [--book BOOK_ID ...] [--again]
python3 -m kb cards-queue run RUN [--passes N]
python3 -m kb cards-queue status RUN
```

- **`plan`** takes a snapshot: the active books whose version is converted and has no card (with `--again`, those that have one too;
  with `--book`, only the books named) and writes it as a *run* in the index root (`card-runs/<run>/manifest.json`). It makes no call
  and sends nothing. It prints the name of the run, the number of books, how many were left out and why, the order of the models by
  their entries in your config (no server or address), and the calls that can be counted before the answers are known. A book that
  arrives later is not in the run; the next `plan` has it. Two plans are two runs with their own state.
- **`run`** works through the run in passes (at most `--passes`, 1 to 10, default 3). A pass visits the models in the order of the
  stages (the notes, the card, the checks, and, if `card-more` is set, the second round and its checks). At each visit it takes every
  waiting book as far as the calls of the model it is serving go, using the journal of the book (see "A card in the making can be
  stopped and taken up again"), and a book that comes to a call for another model waits for that model's visit. The visits are
  grouped by the server and model your config names for the stages, not by entry: two entries that name the same server and model are
  one visit, and each call keeps the options of its own entry. So the number of times a model is changed does not depend on the number
  of books. A model stays loaded between its calls only if the `keep_alive` of its record in the workbench's endpoint file (see
  "Calling a model") is more than 0; the queue sets none of its own.
  A card is filed as a new generation as soon as its last call is made, so a run that is stopped leaves the cards already made. A
  call that fails, an answer that is refused (which is kept aside as `cards` keeps it) and a card that cannot be filed are tried again
  in the next pass, and the book is reported as failed after one more try; the other books go on. (The second round is an addition: if
  its call fails or is refused the card is filed without it, as with `cards`, and it is not tried again.) A book is dropped and
  reported if it is no longer active, if the conversion in use is not the one the plan saw (or has gone, or has less text than the
  cutoff now), if the book has a newer version than the plan saw, if its saved state cannot be read (it is left as it is, for you to look
  at), or if its saved state was made with other settings (another model, a prompt of another version, another number of pieces); to
  make its card, plan again. An error the program did not expect in one book fails that book and shows only the kind of error, and
  the other books go on; a failure to keep the manifest of the run stops the run. `run` exits with 1 when a book failed. A book whose card was filed after the plan (a run that was stopped as the card was filed, or a
  `cards` run) is marked done and no second card is made. At the end the catalog is rebuilt if a card was made now; if none was, but
  the run has cards from before, the report says so in `catalog_note`. The report has the counts (`done`, `failed`, `dropped`,
  `waiting`), each book with its status, generation, reason (cut at 200 characters) and number of tries, the passes made and the result
  of rebuilding the catalog. A small book gets a card from its metadata with no call, as with `cards`. A run holds at most 10,000 books.
- **A run can be stopped at any point** (an interrupt, a crash, the machine going off) **and run again**: the saved calls are not
  made again. One run works at a time, whatever its name: `run` takes the lock `card-runs/queue.lock`, a second `run` of any run is
  refused, and the lock is released when the holder ends or is killed. A run that is finished does nothing when run again. Nothing
  deletes a run's folder; it holds only disposable state (the manifest and, for a book that failed, its journal) and can be deleted
  whenever you like. A `cards` run at the same time is not stopped by the lock; the card it files is noticed by the queue.
- **`status`** prints the counts and, for each book, its status, and for the waiting books how far their calls have got (not started,
  notes, card, check, round, round check). It prints no text of any book.
- Book text, notes and items go to the models your `tasks` setting names, as with `cards`, and only when you start a `run`. No option
  names a model, a server or an address.

### Searching the cards

```sh
python3 -m kb card-index                       # build the catalog from the book folders
python3 -m kb card-search 'stopping rule' [--in all|summary|neutral] [--book BOOK_ID] [--limit N]
```

- **The catalog.** `cards.sqlite` in the index root holds the newest card of each version of each active book, the whole card as
  JSON, and a full-text table with a column for each text field of the card (title, summary, uses, topics, adjacent topics, key
  ideas, the five neutral fields, caveats). It is separate from the search index of the text, which it does not touch. It is built
  from the book folders alone, by `card-index`, which reads every card with its hashes checked and leaves out and counts any that
  fail; the file is private to you, can be deleted, and a rebuild gives the same catalog. **It is not updated when a card is made**:
  run `card-index` again after `cards` (a card made after the last `card-index` is not found). A search does not say how old the
  catalog is.
- **A search** is words, never syntax, like `search`: put the query in quotes as one argument; each word is quoted for the
  full-text table and bound as a parameter, so an operator, a column name, a quote or SQL in a query is only a word. Every word must
  match in one card, in any field, without regard to case or accents. `--in summary` looks at the card in the words of its source
  (title, summary, uses, topics, adjacent topics, key ideas, caveats), `--in neutral` only at the five neutral fields, and
  `--book` at one book's cards. At most 50 results (10 by default), ranked by the table's measure and then by book and version, so the
  same library gives the same order after a rebuild. A search reads only the catalog, so it works with the bulk root away, and it is
  stopped after ten seconds.
- **A result** gives the card: its text, rendered as `card-show` renders it, between the untrusted-text markers (a field that holds
  the words of a marker is withheld); an excerpt of the first field that matched, on one line behind the marker; which fields
  matched (on the side that was searched); the facts that hold no free text: the book and version, the generation of the card,
  whether it is for the book's current version, the date the book was added, the score (smaller is better), whether the card is
  partial, and `grounding`: how many of its items are `stated` and how many `inferred` (`{"stated": 4, "inferred": 6}`), or
  `"not checked"` for a card of format 1. The marks are shown and never used: they are not indexed, so a search for the word
  `stated` finds nothing, and they change neither the score nor the order. Card text that looks like a mark (`[stated]`, `[inferred]`,
  with or without spaces or capitals) is shown with round brackets, so that only the engine's marks read as marks. A result also has
  a citation line, which does hold text from the book, its title and its source address, cleaned, the title blanked if
  it holds the words of a marker, and printed outside the markers. Every search checks each row against the card it holds (the
  citation, the date, the generation and the version flag must be what that card gives), and a card with no model part is found by
  its title only.
- **The citation line** is built when the catalog is written, from the facts the card holds, in the form a read gives. It is the
  same as a read's line except where a card holds less than the source record: for an arXiv paper it lacks the PDF address that a read
  adds; a card keeps only a web address with no user name (a read says `non-web address` for another); and it keeps an address to 300
  characters, a read to 500.
- **A damaged catalog.** A file of another format, with other tables, a trigger or a view, a stored card that is not a valid card
  (or is nested too deeply to read), or a row whose citation, date, generation or version flag is not what its card gives, is
  refused with the command to run (`card-index`). Nothing in the catalog is run.

### The trial: do the cards help?

```sh
python3 -m kb trial CORPUS REPORT [--replace]
```

`trial` compares what a search of the cards finds with what a search of the full text finds, on questions you choose. You start it;
it reads the library and the two indexes and nothing else, calls no model, sends nothing anywhere and changes nothing. Both files
are held **outside the repository**: it refuses a corpus or a report path inside the project's folder (links followed), because
questions from your own projects must not be committed. It reports numbers and never decides.

- **The corpus** is a JSON file you write: `{"format": 1, "questions": [{"id": "q1", "text": "...", "queries": ["short plain words", ...],
  "right": ["<book id>", ...]}], "field_words": ["optional", ...]}`. A question has 1 to 10 queries, and 1 to 50 right books, named by
  you. The queries are plain words, as an agent would write them (a search of the cards needs every word to match, as spelled), and
  both searches get the same queries. Write the queries before the first run and do not change them after seeing results; a change is
  a new corpus file, and the report records the file's sha256.
- **The searches.** Each query is run four ways: the cards (all fields), the summary side of the cards, the neutral side, and the
  full text (the first 50 blocks, taken to books in the order of their first appearance; for a common word the limit is reached and the
  books are a lower bound, which the report says for each query).
- **The rules of the numbers.** A book's *place* in one search of one query is counted from 1 by its first appearance. For a question
  the books found are the union over its queries; a book's place is the smallest it has in any query, and books of the same place are
  ordered by book id. A right book is *found* if any query found it. The unit is a (question, right book) pair. A right book with no
  card is *uncovered* and is left out of the card measures and of the comparison (it counts only in the full-text recall over all
  pairs), so a missing card is never read as a search that missed. *Recall* is the share of covered pairs found; *cards-only,
  text-only, both, neither* count covered pairs, "cards" meaning the search of all fields; the *hit rate* is the share of questions
  with a covered right book in which some right book was found; a question's *reciprocal rank* is one over the place of its best
  right book (zero if none), and the mean is over the same questions; *noise* is the number of distinct books found that are not
  right. Every number is given with its count. The *place* is the best place a book has in any query, not its position in the merged
  list: a book at place 2 in one query is at place 2 even if three other books are at place 1 elsewhere. The report also holds, for
  each query, the right books it found with their places and its noise, and for each question and search its hit and reciprocal rank.
  The full-text search is scored on all right books, the card searches on the covered ones. Limits: 200 questions, a corpus of 1 MB,
  question text of 1,000 characters, 500 field words; the card search returns at most 50 cards a query.
- **The cards.** For each card the number of words of each field and in all, and the *leaked* words: words of four or more letters of
  its title and topics that its neutral fields repeat, less a short list of common words, plus every word of `field_words` (of any
  length, matched without regard to case) that they repeat; and the share of cards that leak. This is a rough measure of whether
  the neutral description keeps the book's field out; it is a word list, not a judgment.
- **Uncovered books.** A right book left out of the card measures is listed with its reason: `no card`, `card cannot be read` (its
  newest card fails its checks, which `card-index` also leaves out) or `book is not active`. Right books that the text index does not
  hold are listed apart as `text_uncovered`, since the full-text search could not find them; `index` is not checked for freshness
  beyond its presence, and `trial` refuses if the catalog or the text index changes while it runs.
- **The report** (JSON, mode 600, never over a file that exists unless `--replace`) holds the queries and the books each search found
  in order, the numbers above, the uncovered books, the corpus hash and the date, and an **input manifest**: the library, each card's
  book, version, generation and hash, and the sha256 of the catalog file and of the text index, so that a later reader knows which cards
  gave the result. `trial` refuses a catalog that is not the one the cards make (a card made after the last `card-index`) and a
  missing text index. It prints the numbers and the corpus hash, not the questions.
- **What it cannot show.** A small library and a few questions make a finding for you to weigh, not a measure of how well the library
  serves your real use.

### How accurate are the cards? A sample to label

```sh
python3 -m kb card-sample OUTDIR [--items 80] [--calibration 15] [--seed N] [--generation G ...] [--book BOOK_ID ...] [--added N]
python3 -m kb card-accuracy ITEMS KEY
python3 -m kb card-agreement FIRST SECOND
```

These three measure whether the claims on a card are in the book. They call no model and change nothing in the library. The files
are held **outside the repository** (a folder inside the project's folder, links followed, is refused), in a private folder.

- **`card-sample`** draws a blind sample of card items from the generations you name (default: the newest card of each version):
  the sentences of the summary, the topics, key ideas, caveats and the five neutral fields. It does not draw adjacent topics or the
  "useful for" lines. The number of items is split over the generations you name (by default the newest card of each version is
  one group, and the key records each card's own generation); within a group the cards are visited in turn and, within a card,
  the fields in turn, so no card or field fills the sample. A card that cannot be read is left out and counted in the printed
  summary (`unreadable_cards`). `--book` (repeat it for several) limits the sample to the books named and leaves the others out.
  `--added N` draws N of the items from those that a second round added (see the task `card-more`), counts them in the sample and
  in the share of their generation, and marks them in the key; it is refused if the cards hold fewer, or if a generation would
  have more of them than its share. `card-accuracy` then counts them apart as well, under `added`. The items file does not say
  which they are.
  The same `--seed` gives the same sample. `OUTDIR` is
  new or empty, and four files are written, all private:
  - `items.json`: the items, shuffled, each with an id, the book, the field, the text, up to five passages of the book that share
    the most words with it (the best block with the block before and after, at most 600 characters, none within two blocks of
    another) and empty `label`, `labelled_by` and `note`. It says nothing of the generation an item came from, so a labeller is
    blind. Passages are text from a book: data, never instructions.
  - `calibration.json`: a smaller set of the same items, spread over the fields, for the owner to label.
  - `key.json`: which card, generation, field and position each id came from, with a hash of its text. Keep it from the labeller.
  - `rubric.md`: the rules for the labels, which are also in the first lines of each items file.
- **The labels** (in the `label` field): `supported` (a shown passage states the item, all of it), `inference` (no passage states it
  but it follows from them; the `note` names the passage), `unsupported` (not stated, contradicted, or only partly stated), or
  `skip` (it is about the card's own source or process, or cannot be judged from the passages). A labeller sees only the passages
  shown, so an item supported elsewhere in the book is `unsupported`: the counts are of support within the passages shown.
  A labeller also sets `labelled_by`.
- **`card-accuracy`** reads a fully labelled items file and the key, and reports for each generation and field the number of items,
  skipped, supported, unsupported and inference items, with shares of the items not skipped. It refuses items that are not the ones
  the key names (ids, text, field), an unlabelled item, an inference with no note, and an unknown label. It prints no item text.
- **`card-agreement`** compares two labellings: the whole sample labelled by a model and the calibration file labelled by the
  owner, say. It compares over the ids of the smaller file, which must be among the larger's and have the same text, and reports
  the share that agree, the pairs of labels, the ids that differ, and how many items were skipped or unlabelled. It prints no item
  text.

Not covered. A card is model output about a book and may be wrong; it is a lead, not a claim. The neutral fields still name the
book's field often; nothing checks that by code. A model that writes a list longer than its limit makes the card fail; nothing is
retried. The stage state has no stage for cards. The model call layer and the card commands were run on three
real books, on a server that serves a small and a larger model: a short page made its card in a few seconds once the model was
loaded, a three-piece paper in under a minute, and a 13-piece paper (12 read) in under two minutes.

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
