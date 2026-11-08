"""The catalog of cards: one SQLite file in the index root, with a row for the newest card of each version of each active book and a
full-text table over the text of the cards (`docs/specs/card.md`, "Where it is stored").

    cards.sqlite
      cards      one row per card: its book and version, the generation, whether the version is the book's current one, the date the
                 book was added, the citation line, and the whole card as JSON (so a search can show it with the bulk root away)
      cards_fts  the text fields of the card, one column each: title, summary, uses, topics, adjacent topics, key ideas, the five
                 neutral fields and caveats; its rowid is the id of the row in `cards`

The file is derived from the book folders and can be thrown away: `rebuild` reads each card through `card.read` (the payload's hashes
are checked and the card is validated), writes a new file beside the old one and renames it into place, and gives the same result
each time. A card that fails its checks, and a book that cannot be read, are left out and counted. It is separate from the full-text
index (`search.sqlite`), which it does not read or change. A file that has anything in it this engine did not put there (a trigger, a
view) or another format number is refused, read or written, and a rebuild replaces it. Writers take a lock on `cards.lock` in the index
root and wait for each other; a search is not a writer and does not wait.

Everything in the catalog came through `card.read`, so it is checked and clean, and it is model output or text from a book: it is shown
only as the rendered card between the untrusted-text markers, or as an excerpt behind the marker."""
import fcntl
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from . import KbError, card, ids, textutil
from . import read as citation  # the form of a citation line that a read gives
from . import search as fulltext  # the words of a query and the excerpt: the same rules as the search of the text

INDEX_FILE = "cards.sqlite"
LOCK_FILE = "cards.lock"
LOCK_WAIT = 120  # seconds a writer waits for another before it gives up
FORMAT = 1
COMMAND = "python3 -m kb card-index"
SEARCH_SECONDS = fulltext.SEARCH_SECONDS
PROGRESS_STEPS = fulltext.PROGRESS_STEPS
DEFAULT_LIMIT = fulltext.DEFAULT_LIMIT
MAX_LIMIT = fulltext.MAX_LIMIT
FIELDS = ("title", "summary", "uses", "topics", "adjacent", "ideas", "n_problem", "n_approach", "n_needs", "n_provides", "n_limits", "caveats")
SUMMARY_SIDE = ("title", "summary", "uses", "topics", "adjacent", "ideas", "caveats")  # the card in the vocabulary of its source
NEUTRAL_SIDE = ("n_problem", "n_approach", "n_needs", "n_provides", "n_limits")        # the five neutral fields

SIDES = {"all": FIELDS, "summary": SUMMARY_SIDE, "neutral": NEUTRAL_SIDE}
_COLUMNS = ["id", "book_id", "version_id", "generation", "is_current", "added", "citation", "card"]
_SCHEMA = (
    "CREATE TABLE cards (id INTEGER PRIMARY KEY, book_id TEXT NOT NULL, version_id TEXT NOT NULL, generation INTEGER NOT NULL, "
    "is_current INTEGER NOT NULL, added TEXT NOT NULL, citation TEXT NOT NULL, card TEXT NOT NULL)",
    "CREATE UNIQUE INDEX cards_by_version ON cards (book_id, version_id)",
    f"CREATE VIRTUAL TABLE cards_fts USING fts5({', '.join(FIELDS)}, tokenize = 'unicode61 remove_diacritics 2')",
)


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


@contextmanager
def lock(index_root):
    """Hold the writers' lock on the catalog. Waits up to LOCK_WAIT seconds for another writer, then refuses."""
    path = os.path.join(index_root, LOCK_FILE)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise KbError(f"the catalog lock cannot be opened ({e.strerror})") from None
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise KbError("the catalog is being written by another process; try again when it has finished") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing it lets go of the lock


def connect(path, create=False, readonly=False):
    """The catalog at `path`, checked: it must be a database of this engine's shape and hold nothing else. A file that is not, or is
    missing, is a refusal that says what to do. `readonly` opens it so that nothing can be written or replayed."""
    if not create and not os.path.isfile(path):
        raise KbError(f"there is no catalog of cards yet: run `{COMMAND}` to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError(f"the catalog path cannot be opened as a file: {textutil.literal(path)}") from None
    try:
        conn = sqlite3.connect(target, timeout=5 if readonly else 30, uri=readonly)
        try:
            if create:
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {FORMAT}")
                conn.commit()
            elif conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT or {"cards", "cards_fts"} - {
                    r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
                raise KbError(f"the catalog is not in the shape this version of the engine writes: run `{COMMAND}`")
            elif [r[1] for r in conn.execute("PRAGMA table_info(cards)")] != _COLUMNS or "fts5" not in (
                    conn.execute("SELECT sql FROM sqlite_master WHERE name = 'cards_fts'").fetchone() or [""])[0].lower():
                raise KbError(f"the tables of the catalog are not the ones this version of the engine writes: run `{COMMAND}`")
            elif conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
                raise KbError(f"the catalog holds a trigger or a view this engine did not put there: run `{COMMAND}` to build it again")
        except BaseException:
            conn.close()
            raise
        return conn
    except sqlite3.Error as e:
        raise KbError(f"the catalog cannot be opened ({e}): run `{COMMAND}` to build it again") from None


def citation_of(made):
    """The citation line of a card, in the form a read gives, from the source facts the card holds. It is the same as a read's line
    except where a card holds less than the source record: a card keeps no PDF address, which a read adds for an arXiv paper; it keeps
    only a web address with no user name (a read says `non-web address` for another, and takes the address finally reached before the
    one asked for even if the card dropped it); and it keeps an address to 300 characters (a read, to 500)."""
    source = made["source"]
    title = textutil.title(made["title"], 200) or "untitled"
    title = title.replace('"', "'").rstrip("\\")  # shown between quotation marks that it cannot close, or escape with a last backslash
    if "arxiv_id" in source:
        where = f"arXiv:{source['arxiv_id']}{source.get('label', '')}"
    elif source.get("address_final") or source.get("address_asked"):
        where = (source.get("address_final") or source.get("address_asked")).replace('"', "%22").replace(" ", "%20")  # as a read does
    else:
        where = "no source address recorded"
    retrieved = source.get("retrieved")
    date = retrieved[:10] if isinstance(retrieved, str) and citation._DATE.fullmatch(retrieved[:10]) else "date not recorded"
    return f'"{title}". {where}. Retrieved {date}. sha256 {source.get("sha256") or "hash not recorded"}'


def _fields(made):
    """The text of each searchable column of a card. A card with no model part has only its title."""
    model = made["model"] or {}
    joined = lambda key: " ; ".join(model.get(key, []))
    return (made["title"], model.get("summary", ""), joined("useful_for"), joined("topics"), joined("adjacent_topics"),
            joined("key_ideas"), model.get("neutral_problem", ""), model.get("neutral_approach", ""), model.get("neutral_needs", ""),
            model.get("neutral_provides", ""), model.get("neutral_limits", ""), joined("caveats"))


def _insert(conn, book, version_id, number, made):
    added = str(book.get("added") or "")
    added = added if card._ISO.fullmatch(added) else ""  # a date, or nothing: it is shown as a fact outside the markers
    cursor = conn.execute(
        "INSERT INTO cards (book_id, version_id, generation, is_current, added, citation, card) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (made["book_id"], version_id, number, 1 if book.get("current_version") == version_id else 0,
         added, citation_of(made), json.dumps(made)))
    conn.execute(f"INSERT INTO cards_fts (rowid, {', '.join(FIELDS)}) VALUES (?, {', '.join('?' for _ in FIELDS)})",
                 (cursor.lastrowid, *_fields(made)))


def rebuild(store):
    """Build the catalog again from the book folders and put it in place of the old one. Returns the counts: the active books, the
    books left out because they are not active, the versions that have a card, the cards in the catalog, and `failed` for the books
    and cards that could not be read and so are not in it. A failure to write leaves the old catalog as it was, and so does a library
    that is not there at the start or when the new catalog is ready to be put in place."""
    store._guard()  # the library's marker and device: an unmounted drive must not give an empty catalog
    root = store.cfg["index_root"]
    final = path_of(root)
    fresh = final + ".new"
    counts = {"books": 0, "inactive": 0, "versions": 0, "cards": 0, "failed": 0}

    def remove(path, what):
        if os.path.lexists(path):
            try:
                os.remove(path)
            except OSError as e:
                raise KbError(f"{what} is in the way and cannot be removed ({e.strerror}): {path}") from None

    with lock(root):
        in_place = False
        try:
            remove(fresh, "a half-built catalog")
            remove(fresh + "-journal", "a half-built catalog's journal")
            connect(fresh, create=True).close()
            with closing(connect(fresh)) as conn:
                for book_id in store.list_books():
                    try:
                        book = store.read_book(book_id)
                        versions = store.version_ids(book_id)
                    except KbError:
                        counts["failed"] += 1
                        continue
                    if book.get("state") != "active":
                        counts["inactive"] += 1
                        continue
                    counts["books"] += 1
                    for version_id in versions:
                        try:
                            if not card.generations(store, book_id, version_id):
                                continue
                            number, made = card.read(store, book_id, version_id)
                        except KbError:
                            counts["failed"] += 1  # a card that fails its checks is left out and counted; the rest are built
                            continue
                        _insert(conn, book, version_id, number, made)
                        counts["versions"] += 1
                        counts["cards"] += 1
                conn.commit()
            store._guard()  # and the library is still there: if it went away part way, most of it was counted as unreadable
            os.chmod(fresh, 0o600)  # the cards are the owner's: the file is private to the owner, as the lock file is
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                remove(stale, "a file of the old catalog")  # a journal of the old file must not be replayed into the new one
            os.replace(fresh, final)
            in_place = True
        except sqlite3.Error as e:
            raise KbError(f"the catalog could not be written ({e})") from None
        finally:
            if not in_place:  # whatever went wrong, the old catalog is as it was and no half-built file is left
                for leftover in (fresh, fresh + "-journal"):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
    return counts


def _expression(words, columns):
    """The words as the full-text table's query language: each in quotes (a word is letters and digits only), all of them to match, and
    for a side of the card only the columns named in a filter. The columns are constants of this module, never taken from a query."""
    quoted = fulltext.quote_words(words)
    return quoted if columns == FIELDS else "{" + " ".join(columns) + "} : (" + quoted + ")"


def _matched(conn, row_id, words, columns):
    """The fields of one card, among `columns` (the side that was searched), in which at least one word of the query is, in the order of
    the card."""
    any_word = " OR ".join(f'"{w}"' for w in words)
    return [field for field in FIELDS if field in columns
            and conn.execute("SELECT 1 FROM cards_fts WHERE cards_fts MATCH ? AND rowid = ?", ("{" + field + "} : (" + any_word + ")", row_id)).fetchone()]


def search(index_root, query, limit=DEFAULT_LIMIT, book_id=None, within="all"):
    """Ranked results for a query, at most `limit` (1 to 50): the cards whose text holds every word. `within` is `all`, `summary` (the card
    in the vocabulary of its source: title, summary, uses, topics, adjacent topics, key ideas, caveats) or `neutral` (the five neutral
    fields); `book_id` names one book. Each result carries the card, rendered as `card-show` renders it, between the untrusted-text
    markers, and the facts that hold no free text. A search reads the catalog file and nothing else."""
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise KbError(f"the limit must be a whole number from 1 to {MAX_LIMIT}")
    if not isinstance(within, str) or within not in SIDES:
        raise KbError(f"a search is within {', '.join(SIDES)}")
    if book_id is not None:
        ids.check_id(book_id)
    words = fulltext.words_of(query)
    sql = ("SELECT c.id, c.book_id, c.version_id, c.generation, c.is_current, c.added, c.citation, c.card, bm25(cards_fts) "
           "FROM cards_fts JOIN cards c ON c.id = cards_fts.rowid WHERE cards_fts MATCH ?"
           + (" AND c.book_id = ?" if book_id is not None else "") + " ORDER BY bm25(cards_fts), c.book_id, c.version_id LIMIT ?")
    params = [_expression(words, SIDES[within])] + ([book_id] if book_id is not None else []) + [limit]
    end = time.monotonic() + SEARCH_SECONDS
    try:
        with closing(connect(path_of(index_root), readonly=True)) as conn:
            conn.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, PROGRESS_STEPS)
            rows = conn.execute(sql, params).fetchall()
            matched = {row[0]: _matched(conn, row[0], words, SIDES[within]) for row in rows}
    except sqlite3.Error as e:
        if time.monotonic() > end:
            raise KbError(f"the search took too long (more than {SEARCH_SECONDS} seconds) and was stopped") from None
        raise KbError(f"the catalog cannot be read ({e}): run `{COMMAND}` to build it again") from None
    damaged = KbError(f"the catalog holds a card that is not valid or does not belong to its row: run `{COMMAND}` to build it again")
    results = []
    for row_id, row_book, row_version, generation, current, added, cite, stored, rank in rows:
        try:
            made = json.loads(stored)
            card.validate(made)
            # everything printed comes from the checked card, or is checked against it: a row altered after the build is refused
            if (made["book_id"] != row_book or made["version_id"] != row_version or cite != citation_of(made)
                    or not (added == "" or card._ISO.fullmatch(added)) or type(generation) is not int or generation < 1
                    or current not in (0, 1)):
                raise damaged
            fields = matched[row_id]
            excerpt = card._shown(fulltext.excerpt_of(_fields(made)[FIELDS.index(fields[0])], words)) if fields else ""
            results.append({"book_id": row_book, "version_id": row_version, "generation": generation, "is_current": bool(current),
                            "added": added, "score": float(rank),  # the score is computed by the query, not stored: nothing to check
                            "matched": fields, "excerpt_field": fields[0] if fields else None,
                            "partial": made["partial"], "grounding": card.grounding_counts(made), "citation": cite, "untrusted": True,
                            "excerpt": f"{fulltext.MARKER}\n{excerpt}",
                            "text": f"{fulltext.MARKER}\n{card.render(made)}\n{citation.END_MARKER}"})
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, KbError):
            raise damaged from None
    return results
