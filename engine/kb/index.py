"""The keyword index: one SQLite file in the index root, with a row for each block of each converted version, or, for a block
longer than CHUNK_CHARS, a row for each piece of it.

    search.sqlite
      versions     one row per indexed version: its book, title, date added, scan caveats, how complete its conversion
                   was, the conversion the rows come from, and a signature of all that
      blocks       one row per block, or per piece of a long block: the book, the version, the number of the block it is in
                   and its locator (JSON). A short block has the locator of its section or page; a piece of a long block has an
                   `offset` locator for its own start, so a hit in a long page is read from there and not from the top of it
      blocks_fts   the text of each row, in an FTS5 table whose rowid is the row in `blocks`

Everything a search result shows is copied into the file when it is written, so a search reads this file and nothing else:
the bulk root can be away. The file is derived from the books and can be thrown away: `rebuild` writes a new one beside the old
and renames it into place, and gives the same results. Only versions whose conversion is done are indexed, only for a book that
is active, and a block (or a piece of a long one) that cannot have a locator (its text grows too much when normalised) is left
out and counted.

A file that has anything in it this engine did not put there (a trigger, a view) is refused, read or written, and a rebuild
replaces it. Writers (a version written, a rebuild, taking out the books put away) take a lock on `search.lock` in the index
root and wait for each other; a search is not a writer and does not wait.

`index_version` is the stage `indexed`. A stop after the rows are written and before the stage is marked is resumed by a
signature: rows that match the book as it is now are adopted, and anything else is written again."""
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from . import KbError, __version__, convert, locator, stages, textutil

INDEX_FILE = "search.sqlite"
LOCK_FILE = "search.lock"
LOCK_WAIT = 120  # seconds a writer waits for another before it gives up
FORMAT = 2  # 2: a long block is in pieces (1 had one row for each block)
CHUNK_CHARS = 2000  # a block longer than this is indexed in pieces of at most this many characters, cut at a word
TOOL = f"kb-index {__version__}"
INACTIVE = ("weeded", "removed", "duplicate")  # the book states that keep a book out of the search

_SCHEMA = (
    "CREATE TABLE versions (book_id TEXT NOT NULL, version_id TEXT NOT NULL, title TEXT NOT NULL, added TEXT NOT NULL, "
    "is_current INTEGER NOT NULL, caveats TEXT NOT NULL, structure TEXT NOT NULL, partial INTEGER NOT NULL, "
    "compared INTEGER NOT NULL, reasons TEXT NOT NULL, conv_tool TEXT NOT NULL, conv_version TEXT NOT NULL, "
    "conv_generation INTEGER NOT NULL, blocks INTEGER NOT NULL, skipped INTEGER NOT NULL, signature TEXT NOT NULL, "
    "PRIMARY KEY (book_id, version_id))",
    "CREATE TABLE blocks (id INTEGER PRIMARY KEY, book_id TEXT NOT NULL, version_id TEXT NOT NULL, block INTEGER NOT NULL, "
    "locator TEXT NOT NULL)",
    "CREATE INDEX blocks_by_version ON blocks (book_id, version_id)",
    "CREATE VIRTUAL TABLE blocks_fts USING fts5(text, tokenize = 'unicode61 remove_diacritics 2')",
)


class IndexWriteError(KbError):
    """The index file could not be written (a full disk, a locked or damaged file), as against a book that cannot be read."""


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


@contextmanager
def lock(index_root):
    """Hold the writers' lock on the index. Waits up to LOCK_WAIT seconds for another writer, then refuses."""
    path = os.path.join(index_root, LOCK_FILE)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise KbError(f"the index lock cannot be opened ({e.strerror})") from None
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise KbError("the index is being written by another process; try again when it has finished") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing it lets go of the lock


def connect(path, create=False, readonly=False):
    """The index at `path`, checked: it must be a database of this engine's shape and hold nothing else. A file that is not,
    or is missing, is a refusal that says what to do. `readonly` opens it so that nothing can be written or replayed."""
    if not create and not os.path.isfile(path):
        raise KbError("there is no search index yet: run `python3 -m kb index` (or `process`) to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError(f"the index path cannot be opened as a file: {textutil.literal(path)}") from None
    try:
        conn = sqlite3.connect(target, timeout=5 if readonly else 30, uri=readonly)
        try:
            if create:
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {FORMAT}")
                conn.commit()
            elif conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT or {"versions", "blocks", "blocks_fts"} - {
                    r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
                raise KbError("the search index is not in the shape this version of the engine writes: run `python3 -m kb index`")
            elif conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
                raise KbError("the search index holds a trigger or a view this engine did not put there: "
                              "run `python3 -m kb index` to build it again")
        except BaseException:
            conn.close()
            raise
        return conn
    except sqlite3.Error as e:
        raise KbError(f"the search index cannot be opened ({e}): run `python3 -m kb index` to build it again") from None


def _indexable(store, book_id, version_id):
    """What would be indexed for a version now: the facts about the version and the rows for its blocks. Raises KbError if the
    version has no finished conversion."""
    state = stages.read(store, book_id, version_id)["stages"]["converted"]["status"]
    if state != "done":
        raise KbError("the version has not been converted yet, so there is nothing to index")
    root = store.read_book(book_id)
    version = store.read_version(book_id, version_id)
    loaded = convert.load_in_use(store, book_id, version_id)
    if loaded is None:
        raise KbError("the version has no conversion to index")
    ref, conversion, record = loaded
    check = version.get("conversion_check") or {}
    rows, skipped, blocks = [], 0, 0
    for block in conversion.blocks:
        if len(block.text) <= CHUNK_CHARS:
            places = [(None, block.text)]
        else:
            places = [(block.start + start, block.text[start:end]) for start, end in textutil.pieces(block.text, CHUNK_CHARS)]
        added = 0
        for offset, text in places:
            try:
                loc = locator.make(ref, conversion, block.index) if offset is None else locator.in_block(ref, conversion, block.index, offset)
            except KbError:
                skipped += 1  # text built to grow when normalised has no locator and is not indexed (counted for each piece)
                continue
            rows.append((block.index, json.dumps(loc, sort_keys=True, separators=(",", ":")), text))
            added += 1
        blocks += 1 if added else 0
    facts = {
        "title": textutil.clean(root.get("title") or "", 300), "added": root.get("added") or "",
        "caveats": version.get("caveats", []), "structure": record["quality"], "partial": bool(check.get("partial")),
        "compared": bool(check.get("compared")), "reasons": check.get("reasons", []), "conversion": ref,
        "blocks": blocks, "rows": len(rows), "skipped": skipped, "chunk": CHUNK_CHARS,  # the size of a piece is part of what the rows are
    }
    facts["signature"] = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    return root.get("state"), root.get("current_version"), facts, rows


def _insert_block(conn, book_id, version_id, number, loc, text):
    cursor = conn.execute("INSERT INTO blocks (book_id, version_id, block, locator) VALUES (?, ?, ?, ?)",
                          (book_id, version_id, number, loc))
    conn.execute("INSERT INTO blocks_fts (rowid, text) VALUES (?, ?)", (cursor.lastrowid, text))


def _remove(conn, book_id, version_id):
    conn.execute("DELETE FROM blocks_fts WHERE rowid IN (SELECT id FROM blocks WHERE book_id = ? AND version_id = ?)",
                 (book_id, version_id))
    conn.execute("DELETE FROM blocks WHERE book_id = ? AND version_id = ?", (book_id, version_id))
    conn.execute("DELETE FROM versions WHERE book_id = ? AND version_id = ?", (book_id, version_id))


def _write(store, book_id, version_id, path):
    state, current, facts, rows = _indexable(store, book_id, version_id)
    with closing(connect(path, create=not os.path.isfile(path) or os.path.getsize(path) == 0)) as conn:
        try:
            with conn:
                _remove(conn, book_id, version_id)
                if state != "active":
                    return {"blocks": 0, "rows": 0, "skipped": 0}
                for number, loc, text in rows:
                    _insert_block(conn, book_id, version_id, number, loc, text)
                ref = facts["conversion"]
                conn.execute("INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    book_id, version_id, facts["title"], facts["added"], int(current == version_id),
                    json.dumps(facts["caveats"], sort_keys=True), facts["structure"], int(facts["partial"]),
                    int(facts["compared"]), json.dumps(facts["reasons"]), ref["tool"], ref["version"], ref["generation"],
                    facts["blocks"], facts["skipped"], facts["signature"]))
                # which version is the current one is a fact about the book: the rows of its other versions follow it
                conn.execute("UPDATE versions SET is_current = CASE WHEN version_id = ? THEN 1 ELSE 0 END WHERE book_id = ?",
                             (current, book_id))
        except sqlite3.Error as e:
            raise IndexWriteError(f"the search index could not be written ({e})") from None
    return {"blocks": facts["blocks"], "rows": facts["rows"], "skipped": facts["skipped"]}


def write_version(store, book_id, version_id, path=None):
    """Write the rows of a version, replacing any it had, in one transaction: a failure part way leaves the old rows. A book
    that is not active has none. Returns {"blocks": the blocks indexed, "rows": the rows written, "skipped": the places left out}. Into the live index it takes the writers' lock."""
    if path is not None:
        return _write(store, book_id, version_id, path)  # a file being built by `rebuild`, which holds the lock
    root = store.cfg["index_root"]
    with lock(root):
        return _write(store, book_id, version_id, path_of(root))


def _current(index_root, book_id, version_id, facts):
    """Whether the index already holds exactly this version as it is now: the same signature and every row."""
    path = path_of(index_root)
    if not os.path.isfile(path):
        return False
    try:
        with closing(connect(path, readonly=True)) as conn:
            row = conn.execute("SELECT signature FROM versions WHERE book_id = ? AND version_id = ?", (book_id, version_id)).fetchone()
            held = conn.execute("SELECT COUNT(*) FROM blocks WHERE book_id = ? AND version_id = ?", (book_id, version_id)).fetchone()[0]
    except (KbError, sqlite3.Error):
        return False
    return row is not None and row[0] == facts["signature"] and held == facts["rows"]


def index_version(store, book_id, version_id):
    """The stage `indexed` for one version. Returns {"status": "done"} or {"status": "skipped", "reason": ...} (the book is
    not active, so it is not indexed and its rows are taken out); raises KbError if the version is not converted yet."""
    state = stages.read(store, book_id, version_id)["stages"]["indexed"]["status"]
    if state == "done":
        return {"status": "done"}
    book_state, _current_version, facts, _rows = _indexable(store, book_id, version_id)
    if book_state != "active":
        write_version(store, book_id, version_id)  # takes out any rows it has
        return {"status": "skipped", "reason": f"the book is not active ({book_state})"}
    if not _current(store.cfg["index_root"], book_id, version_id, facts):
        write_version(store, book_id, version_id)
    stages.mark(store, book_id, version_id, "indexed", "done", tool=TOOL)
    return {"status": "done"}


def _put_back(store, book_id, state):
    """The versions of a book that has left the index are no longer indexed: put their stage back to pending, so they are
    indexed again if the book becomes active again. One that cannot be put back does not stop the others."""
    try:
        versions = store.version_ids(book_id)
    except (KbError, OSError):
        return
    for version_id in versions:
        try:
            stages.reset(store, book_id, version_id, "indexed", f"the book left the index ({state})")
        except (KbError, OSError):
            continue


def forget_inactive(store):
    """Take out of the index the rows of every book that is removed, weeded or a duplicate, so a book the owner has put away
    leaves the search without waiting for a rebuild, and put its versions' `indexed` stage back to pending, so that it is
    indexed again if it becomes active again. A book whose state cannot be read, or is not one of those, keeps its rows: if
    the bulk drive is away every book is unreadable, and that must not empty the index. A missing, damaged or locked index is
    not an error here. Returns how many books were taken out."""
    root = store.cfg["index_root"]
    path = path_of(root)
    if not os.path.isfile(path):
        return 0
    try:
        with lock(root), closing(connect(path)) as conn:
            books = [r[0] for r in conn.execute("SELECT DISTINCT book_id FROM versions")]
            gone = 0
            for book_id in books:
                try:
                    state = store.read_book(book_id).get("state")
                except KbError:
                    continue
                if state not in INACTIVE:
                    continue
                with conn:
                    conn.execute("DELETE FROM blocks_fts WHERE rowid IN (SELECT id FROM blocks WHERE book_id = ?)", (book_id,))
                    conn.execute("DELETE FROM blocks WHERE book_id = ?", (book_id,))
                    conn.execute("DELETE FROM versions WHERE book_id = ?", (book_id,))
                gone += 1
                _put_back(store, book_id, state)
            return gone
    except (KbError, sqlite3.Error, OSError):
        return 0


def rebuild(store):
    """Build the whole index again from the books and put it in place of the old one. Returns the counts, with `failed` for
    the books and versions that could not be read and so are not in it. A failure to write leaves the old index as it was,
    and so does a library that is not there, at the start or when the new index is ready to be put in place. A book that is put
    away is not indexed and its versions' `indexed` stage is put back to pending."""
    store._guard()  # the library's marker and device: an unmounted drive must not give an empty index
    root = store.cfg["index_root"]
    final, fresh = path_of(root), path_of(root) + ".new"
    counts = {"books": 0, "versions": 0, "blocks": 0, "rows": 0, "skipped": 0, "failed": 0}

    def remove(path, what):
        if os.path.lexists(path):
            try:
                os.remove(path)
            except OSError as e:
                raise KbError(f"{what} is in the way and cannot be removed ({e.strerror}): {path}") from None
    with lock(root):
        try:
            remove(fresh, "a half-built index")
            remove(fresh + "-journal", "a half-built index's journal")
            connect(fresh, create=True).close()
            for book_id in store.list_books():
                try:
                    state = store.read_book(book_id).get("state")
                    versions = store.version_ids(book_id)
                except KbError:
                    counts["failed"] += 1
                    continue
                if state != "active":
                    if state in INACTIVE:
                        _put_back(store, book_id, state)
                    continue
                counts["books"] += 1
                for version_id in versions:
                    try:
                        if stages.read(store, book_id, version_id)["stages"]["converted"]["status"] != "done":
                            continue
                        done = write_version(store, book_id, version_id, path=fresh)
                    except IndexWriteError:
                        raise
                    except KbError:
                        counts["failed"] += 1  # a version that cannot be read is left out and counted; the rest are built
                        continue
                    counts["versions"] += 1
                    counts["blocks"] += done["blocks"]
                    counts["rows"] += done["rows"]
                    counts["skipped"] += done["skipped"]
            store._guard()  # and the library is still there: if it went away part way, most of it was counted as unreadable
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                remove(stale, "a file of the old index")  # a journal of the old file must not be replayed into the new one
            os.replace(fresh, final)
        except BaseException:
            for leftover in (fresh, fresh + "-journal"):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            raise
    return counts
