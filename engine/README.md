# Engine

The knowledge-base engine, a standalone Python program. It holds the library on disk. It does not depend on the project
workbench except for model calls, which this first slice does not make. The design is in
[`docs/specs/`](../docs/specs/README.md) and the build plan is
[`docs/plans/2026-11-05-first-slice-capture-search-read.md`](../docs/plans/2026-11-05-first-slice-capture-search-read.md).

Only library setup exists so far. Requirements: Python 3.15 (the version the first increment was written and tested with) and no
other package.

## Run the tests

From the repository root:

```sh
python3 -m unittest engine.tests.test_setup engine.tests.test_store engine.tests.test_stages
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
  type is refused, and so is a response that arrives encoded (gzip and the like), because none was asked for. A page that
  ends before its declared length is refused too, and is not stored as a complete page.
- The page is stored unchanged in `original/page.html`. The version file records the address asked for, the final address
  after redirects, the retrieval date, the HTTP status, a short list of response headers (never cookies) and the sha256.
- An address with a user name or password is refused, so no secret is stored. Addresses on this machine or a private network
  are refused too, and so are redirects to them, unless you pass `--allow-private`. The name is resolved once to check it and
  again to connect, so a name that changes its answer between the two is not caught.
- A book's identity keys are its address (`url`), other addresses it has been seen at (`url_alias`) and the hashes of its raw
  bytes (`sha256`). An index of them in the index root (`identity.sqlite`) is looked up before a download and can be rebuilt
  from the books. A book's `events.jsonl` is its append-only log (`found`, `filed`, `sighting`).
- A capture that stopped half way is resumed by the next call for the same address, from the filed copy if there is one,
  without downloading it again. The overall deadline runs the fetch in a thread that cannot be stopped, so a server that
  trickles its answer can keep an abandoned thread alive until the network gives up on it.
- A page that turns out to be one the library holds is a sighting on that book. A different page at a held address is also
  recorded as a sighting, not as a new version: comparing the text of versions comes later.
- Nothing downloaded is parsed here. Conversion comes later.
