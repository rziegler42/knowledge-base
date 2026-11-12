"""The vectors of the themes: one SQLite file in the index root that holds, for every theme of the library, what a search result shows and
a vector for each of up to seven of its texts (`docs/specs/theme.md`, "Search and reading"; the plan `2026-11-12-search-the-themes-by-meaning`).

    theme-vectors.sqlite
      meta      the format, the model as the bridge named it, the name the config gave the model, the dimension, the hash of the document
                prefix the vectors were made with, the date of the build
      themes    one row per theme: its book, version and id, the generation of its card and of its themes, the title of the book (from the
                card), the citation line, the whole theme as JSON (its anchor with its start, end, path and excerpt hash, its parts with
                their marks, its confidence and flags) and the hash of each embedded text
      vectors   one row per (theme, text): the hash of the text the vector was made from, and the vector as little-endian 32-bit floats

The texts embedded for a theme are its summary (in the book's own words), its whole description of five parts as one text (the parts that
have text, in their order, each led by its name), and each of the five parts as a text of its own (problem, method, needs, provides and
limits): up to seven. A part with no text has none, and a theme with no part has no whole description. The needs and the limits are
embedded because the spec agrees that an embedding is dropped only if a test shows that doing so loses nothing.

The file is built from the cards and the themes alone: the store gives the list of active books, their current version and their state,
and for each book `card.read` gives its newest card (a book whose newest card is damaged has no card that can be read, as in the catalog)
and `theme.read` its newest valid generation of themes. No book text, conversion or manifest is opened. A book that is not active, has no
card that can be read, has no themes, or whose themes cannot be read is left out and counted. It is derived and can be thrown away. `build` keeps the vector of a text whose hash, model and document prefix have not
changed, sends every other text (once, however many themes hold it) to the embedding model that the config names for `card-embed`, and
writes a new file in a folder of its own which it renames into place under a lock. A build does not reuse a file that this engine did not
make, that is damaged or of another format, or that was made for another model, dimension or document prefix: it makes every vector and
replaces the file when it is whole, and says so (`replaced`). A search refuses such a file.

Vectors are model output, so they are checked when they are made (`models.embed`) and again when they are read: the right length, finite
numbers and not all zeros. A theme read from the file is checked as a theme is (`theme.check_theme`), anchor included.

The citation line is the card's (`catalog.citation_of`) with the section of the theme's anchor and the language, which no card or theme
records, so it says `Language: not recorded`."""
import fcntl
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import struct
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import KbError, card, catalog, ids, models, textutil, theme, vectors
from . import read as reading
from . import search as fulltext  # the limits of a result and the marker of untrusted text: the same as the search of the text

INDEX_FILE = "theme-vectors.sqlite"
LOCK_FILE = "theme-vectors.lock"
BUILD_PREFIX = ".theme-vectors-build-"   # the folders in which a build is made; a killed build leaves one, and the next removes it
FORMAT = 1
COMMAND = "python3 -m kb theme-vectors"
FIELDS = ("summary", "description", "problem", "method", "needs", "provides", "limits")
LANGUAGE = "Language: not recorded"
MAX_SECTIONS, MAX_SECTION_CHARS, MAX_CITATION = 8, 100, 4000
_META_KEYS = ("format", "model", "configured", "dimension", "built", "document_prefix_sha256")
_THEME_COLUMNS = ["book_id", "version_id", "theme_id", "card_generation", "theme_generation", "book_title", "citation", "theme", "hashes"]
_VECTOR_COLUMNS = ["book_id", "version_id", "theme_id", "field", "text_sha256", "vector"]
_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE themes (book_id TEXT NOT NULL, version_id TEXT NOT NULL, theme_id TEXT NOT NULL, card_generation INTEGER NOT NULL, "
    "theme_generation INTEGER NOT NULL, book_title TEXT NOT NULL, citation TEXT NOT NULL, theme TEXT NOT NULL, hashes TEXT NOT NULL, "
    "PRIMARY KEY (book_id, version_id, theme_id))",
    "CREATE TABLE vectors (book_id TEXT NOT NULL, version_id TEXT NOT NULL, theme_id TEXT NOT NULL, field TEXT NOT NULL, "
    "text_sha256 TEXT NOT NULL, vector BLOB NOT NULL, PRIMARY KEY (book_id, version_id, theme_id, field))",
)
_HEX = set("0123456789abcdef")
_DIMENSION = re.compile(r"[0-9]{1,4}")
_VERSION = re.compile(r"v[1-9][0-9]{0,5}")
_THEME_ID = theme._ID   # the ids a theme may have, as the form of a theme says (the engine makes t1, t2 and so on)
_SECTION_DROP = str.maketrans("", "", '"[]>\\')   # the characters with which a heading could close the brackets or the quotation marks of a line
_AGAIN = f"run `{COMMAND}` to build it again"


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


def sha256(text):
    return vectors.sha256(text)


@contextmanager
def lock(index_root):
    """Hold the writers' lock on the file of theme vectors. Waits up to the catalog's wait for another writer, then refuses."""
    path = os.path.join(index_root, LOCK_FILE)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise KbError(f"the lock of the theme vectors cannot be opened ({e.strerror})") from None
    try:
        deadline = time.monotonic() + catalog.LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise KbError("the theme vectors are being written by another process; try again when it has finished") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing it lets go of the lock


def unpack(blob, dimension):
    """The numbers of a stored vector, or a refusal if it is not a vector of `dimension` finite numbers that are not all zero."""
    if not isinstance(blob, bytes) or len(blob) != 4 * dimension:
        raise KbError(f"the file of theme vectors holds a vector that is not of the dimension {dimension}: {_AGAIN}")
    numbers = list(struct.unpack(f"<{dimension}f", blob))
    if not all(x == x and abs(x) != float("inf") for x in numbers) or not any(numbers):
        raise KbError(f"the file of theme vectors holds a vector that is not finite or is all zeros: {_AGAIN}")
    return numbers


def connect(path, create=False, readonly=False):
    """The file at `path`, checked: a database of this engine's shape that holds nothing else, and not a link. A file that is not, or is
    missing, is a refusal that says what to do. `readonly` opens it so that nothing can be written or replayed."""
    if not create and (not os.path.lexists(path) or os.path.islink(path) or not os.path.isfile(path)):
        raise KbError(f"there is no file of theme vectors yet: run `{COMMAND}` to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError("the path of the file of theme vectors cannot be opened as a file") from None
    try:
        conn = sqlite3.connect(target, timeout=5 if readonly else 30, uri=readonly)
        try:
            if create:
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {FORMAT}")
                conn.commit()
            else:
                _check_shape(conn)
        except BaseException:
            conn.close()
            raise
        return conn
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be opened ({e}): {_AGAIN}") from None


def _check_shape(conn):
    if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
        raise KbError(f"the file of theme vectors is not in the shape this version of the engine writes: {_AGAIN}")
    objects = conn.execute("SELECT type, name FROM sqlite_master").fetchall()
    if any(kind in ("trigger", "view") for kind, _ in objects):
        raise KbError(f"the file of theme vectors holds a trigger or a view this engine did not put there: {_AGAIN}")
    if {name for kind, name in objects if kind == "table"} != {"meta", "themes", "vectors"}:
        raise KbError(f"the tables of the file of theme vectors are not the ones this version of the engine writes: {_AGAIN}")
    for table, columns in (("themes", _THEME_COLUMNS), ("vectors", _VECTOR_COLUMNS), ("meta", ["key", "value"])):
        if [r[1] for r in conn.execute(f"PRAGMA table_info({table})")] != columns:
            raise KbError(f"the tables of the file of theme vectors are not the ones this version of the engine writes: {_AGAIN}")


def _meta(conn):
    try:
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be read ({e}): {_AGAIN}") from None
    if (set(rows) != set(_META_KEYS) or not all(isinstance(v, str) for v in rows.values()) or rows["format"] != str(FORMAT)
            or not _DIMENSION.fullmatch(rows["dimension"]) or not 1 <= int(rows["dimension"]) <= models.MAX_DIMENSION
            or not models._valid_model(rows["model"]) or not models._valid_model(rows["configured"]) or len(rows["built"]) > 40
            or len(rows["document_prefix_sha256"]) != 64 or set(rows["document_prefix_sha256"]) - _HEX):
        raise KbError(f"the file of theme vectors does not say which model made it: {_AGAIN}")
    return rows


def check_entry(conn, entry):
    """Refuse a file made for another model or dimension, or with another document prefix, than the embedding entry that is set (`entry`
    as `models.registry` gives it). Returns the meta of the file."""
    rows = _meta(conn)
    if (rows["configured"] != entry["model"] or int(rows["dimension"]) != entry["dimension"]
            or rows["document_prefix_sha256"] != vectors.prefix_hash(entry)):
        raise KbError(f"the file of theme vectors was made for another model, dimension or document prefix than the ones set in the config: "
                      f"{_AGAIN}")
    return rows


def read_themes(conn):
    """The themes of the file, each checked: `[{book_id, version_id, theme_id, card_generation, theme_generation, book_title, citation, theme,
    hashes}]`, `theme` as the theme was filed (checked as a theme is, its anchor included) and `hashes` the sha256 of each embedded text by field.
    A row that is not what this engine writes is a refusal."""
    out = []
    try:
        rows = conn.execute("SELECT book_id, version_id, theme_id, card_generation, theme_generation, book_title, citation, theme, hashes "
                            "FROM themes ORDER BY book_id, version_id, theme_id").fetchall()
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be read ({e}): {_AGAIN}") from None
    bad = KbError(f"the file of theme vectors holds a row that is not what this engine writes: {_AGAIN}")
    for book_id, version_id, theme_id, cg, tg, title, citation, blob, hashes in rows:
        try:
            ids.check_id(book_id)
        except KbError:
            raise bad from None
        if (not isinstance(version_id, str) or not _VERSION.fullmatch(version_id) or not isinstance(theme_id, str) or not _THEME_ID.fullmatch(theme_id)
                or type(cg) is not int or cg < 1 or type(tg) is not int or tg < 1 or not isinstance(title, str) or not title or len(title) > 400
                or not isinstance(citation, str) or not citation or len(citation) > MAX_CITATION or not isinstance(blob, str)
                or not isinstance(hashes, str)
                or textutil.title(title, len(title)) != title or textutil.clean(citation, len(citation)) != citation):
            raise bad   # a title that is not clean or holds the words of a marker, or a line that is not clean, is not what the engine wrote
        try:
            made = json.loads(blob)
            by_field = json.loads(hashes)
            theme.check_theme(made, book_id, version_id)
        except (ValueError, RecursionError, KbError):
            raise bad from None
        if (made["id"] != theme_id or not isinstance(by_field, dict) or not by_field or set(by_field) - set(FIELDS)
                or not all(isinstance(h, str) and len(h) == 64 and not set(h) - _HEX for h in by_field.values())
                or by_field != {field: sha256(text) for field, text in texts_of(made).items()}):
            raise bad   # the hashes of the row are those of the texts of the theme it holds
        out.append({"book_id": book_id, "version_id": version_id, "theme_id": theme_id, "card_generation": cg, "theme_generation": tg,
                    "book_title": title, "citation": citation, "theme": made, "hashes": by_field})
    return out


def _check_vector_key(book_id, version_id, theme_id, field, sha):
    """Refuse a row of vectors whose key or hash is not what this engine writes."""
    if (not isinstance(book_id, str) or not ids._ID.fullmatch(book_id) or not isinstance(version_id, str) or not _VERSION.fullmatch(version_id)
            or not isinstance(theme_id, str) or not _THEME_ID.fullmatch(theme_id) or field not in FIELDS
            or not isinstance(sha, str) or len(sha) != 64 or set(sha) - _HEX):
        raise KbError(f"the file of theme vectors holds a row that is not what this engine writes: {_AGAIN}")


def check_vector_rows(conn):
    """Refuse the file if a row of its vectors is not what this engine writes, reading no vector (only the key and the hash of each row)."""
    try:
        for book_id, version_id, theme_id, field, sha in conn.execute("SELECT book_id, version_id, theme_id, field, text_sha256 FROM vectors"):
            _check_vector_key(book_id, version_id, theme_id, field, sha)
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be read ({e}): {_AGAIN}") from None


def iter_vectors(conn, dimension, lenient=False, ordered=True):
    """The vectors of the file one at a time, each checked: `{book_id, version_id, theme_id, field, text_sha256, vector}`, vector as a list of
    floats that lives only until the next row is asked for. A row that is not what this engine writes is a refusal. So is a vector that is not
    of `dimension` finite numbers that are not all zero, unless `lenient`: then its `vector` is `None`, and the caller leaves the row out and
    counts it. The rows come by key, unless `ordered` is false (then in the order the file holds them). The connection stays in use until the
    last row is taken."""
    order = " ORDER BY book_id, version_id, theme_id, field" if ordered else ""
    try:
        for book_id, version_id, theme_id, field, sha, blob in conn.execute(
                f"SELECT book_id, version_id, theme_id, field, text_sha256, vector FROM vectors{order}"):
            _check_vector_key(book_id, version_id, theme_id, field, sha)
            try:
                vector = unpack(blob, dimension)
            except KbError:
                if not lenient:
                    raise
                vector = None
            yield {"book_id": book_id, "version_id": version_id, "theme_id": theme_id, "field": field, "text_sha256": sha, "vector": vector}
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be read ({e}): {_AGAIN}") from None


def read_vectors(conn, dimension, lenient=False):
    """Every vector of the file as a list (`iter_vectors` taken whole): it holds all of them in memory, which the search does not."""
    return list(iter_vectors(conn, dimension, lenient=lenient))


def citation_line(base, path):
    """The citation line of a theme: the card's line (`base`), the section of the theme's anchor, and the language. A heading is untrusted
    text: it is cleaned, cut, and has the characters that could close the brackets or the quotation marks taken out, so that it cannot
    imitate the rest of the line or a level of its own (`>` joins the headings); at most MAX_SECTIONS headings are named. What is left of a
    heading is text between brackets, and a reader of the line must take it as such."""
    names = []
    for part in list(path)[:MAX_SECTIONS]:
        name = textutil.clean(textutil.title(part, MAX_SECTION_CHARS).translate(_SECTION_DROP), MAX_SECTION_CHARS) if isinstance(part, str) else ""
        if name:
            names.append(name)
    joined = " > ".join(names)
    if joined and not textutil.title(joined, len(joined)):   # headings that are clean on their own can hold the words of a marker together
        joined = card.WITHHELD
    section = f" Section [{joined}]." if names else ""
    return textutil.clean(f"{base}.{section} {LANGUAGE}", MAX_CITATION)   # the line is clean as a whole, as `read_themes` requires of it


def texts_of(made):
    """`{field: text}` for the texts of a theme that are embedded: the summary, the whole description (the parts that have text, in their
    order, each led by its name) and each part that has text."""
    out = {}
    if made["summary"].strip():
        out["summary"] = made["summary"]
    parts = {name: made["neutral"][name]["text"] for name in theme.PARTS if made["neutral"][name]["text"].strip()}
    if parts:
        out["description"] = "\n".join(f"{name}: {parts[name]}" for name in theme.PARTS if name in parts)
    out.update(parts)
    return out


def _library(store):
    """`(books, counts)`: for each active book that has a card and themes that can be read, the card's title and generation, its citation line
    base, and the newest valid generation of themes; and the counts of what was left out. Only the list of books, their state and current
    version, the newest card and the newest generation of themes are read."""
    counts = {"books": 0, "inactive": 0, "no_card": 0, "no_themes": 0, "unreadable": 0}
    books = []
    for book_id in store.list_books():
        counts["books"] += 1
        try:
            book = store.read_book(book_id)
        except KbError:
            counts["unreadable"] += 1
            continue
        if book.get("state") != "active":
            counts["inactive"] += 1
            continue
        version_id = book.get("current_version")
        if not isinstance(version_id, str):
            counts["no_card"] += 1   # a book with no version has no card
            continue
        try:
            card_generation, made_card = card.read(store, book_id, version_id)
        except KbError:
            counts["no_card"] += 1
            continue
        try:
            if not theme.generations(store, book_id, version_id):
                counts["no_themes"] += 1
                continue
            theme_generation, generation = theme.read(store, book_id, version_id)
        except KbError:
            counts["unreadable"] += 1
            continue
        title = textutil.title(made_card["title"], 200) or "untitled"
        base = catalog.citation_of(made_card)
        kept = [(made, texts_of(made)) for made in generation["themes"]]   # a text is clean (no lone surrogate): theme.read refused a theme that is not
        books.append({"book_id": book_id, "version_id": version_id, "card_generation": card_generation, "theme_generation": theme_generation,
                      "title": title, "citation_base": base, "themes": kept})
    return books, counts


def _old_vectors(path, entry):
    """`(vectors, model, reason)`: the vectors of the existing file that may be kept, as `{sha256 of the text: the bytes of the vector as stored}` (checked, and not held as numbers), the model the file says
    made them, and why there are none (`None` when there is no file, or the file is good). A file that is not this engine's, is damaged, or is
    for another model, dimension or prefix gives no vectors and a reason: the build replaces it."""
    if not os.path.lexists(path):
        return {}, None, None
    try:
        with closing(connect(path, readonly=True)) as conn:
            meta = check_entry(conn, entry)
            kept = {}
            for sha, blob in conn.execute("SELECT text_sha256, vector FROM vectors"):
                try:
                    unpack(blob, entry["dimension"])   # checked, and its numbers let go: what is kept is the bytes it is stored in
                except KbError:
                    continue  # a damaged vector is not kept; it is made again
                kept[sha] = blob
            return kept, meta["model"], None
    except (KbError, sqlite3.Error) as e:
        return {}, None, textutil.clean(str(e), 160) or "the file cannot be used"


def _clean_leftovers(index_root):
    """Remove what an earlier build that was killed left, under the lock: a folder, a file or a link whose name begins with BUILD_PREFIX.
    A link is removed as a link, and its target is never entered or removed; nothing else in the index root is touched."""
    try:
        names = os.listdir(index_root)
    except OSError as e:
        raise KbError(f"the index folder cannot be read ({e.strerror})") from None
    for name in names:
        if not name.startswith(BUILD_PREFIX):
            continue
        path = os.path.join(index_root, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as e:
            raise KbError(f"a leftover of an earlier build is in the way and cannot be removed ({e.strerror}): {path}") from None


def build(store, cfg, again=False, launcher=None, root=None):
    """Build the file of theme vectors again from the cards and the themes and put it in place of the old one. Returns the counts: the books
    listed (`books`), those left out (`inactive`, `no_card`, `no_themes`, `unreadable`) and built (`built`, so that `books` is their sum), the themes built (`themes`),
    the vectors in the file, the vectors `kept` from the old file and `made` now, the texts sent (`texts_sent`, each once), the model the
    bridge reported, the dimension and whether the old file was not usable (another format, model, dimension or document prefix, or damaged)
    and so `replaced`. With `again`, every vector is made again. Refused: model work off, no `card-embed` set in the config, a model that the
    bridge reports as another than the one that made the vectors that are kept, a library that is not there. A failure leaves the old file
    as it was. Only the text of the embedded fields is sent. The cards and themes and the old file are read before the models are called,
    and the lock is taken only to write."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    store._guard()  # the library's marker and device: an unmounted drive must not give an empty file
    index_root = store.cfg["index_root"]
    final = path_of(index_root)
    books, counts = _library(store)
    old, old_model, reason = _old_vectors(final, entry)
    if again:
        old = {}  # every vector is made again
    todo, keeps = {}, False   # sha256 -> text, in the order the texts first come; whether any vector of the old file is kept
    for book in books:
        for made, texts in book["themes"]:
            for text in texts.values():
                sha = sha256(text)
                if sha in old:
                    keeps = True
                elif sha not in todo:
                    todo[sha] = text
    made_vectors, made_model = {}, None
    items = list(todo.items())
    per = max(1, models.MAX_EMBED_NUMBERS // entry["dimension"])  # as many texts at a time as their vectors can be held in memory
    for start in range(0, len(items), per):
        group = items[start:start + per]
        got = models.embed(cfg, name, [t for _, t in group], launcher=launcher, root=root, kind="document")
        if keeps and got["model"] != old_model:
            raise KbError(f"the model the bridge reports ({textutil.clean(got['model'], 60)}) is not the one that made the vectors that "
                          f"are kept ({textutil.clean(old_model, 60)}); run `{COMMAND} --again` to make every vector again")
        if made_model is not None and got["model"] != made_model:
            raise KbError("the model that the bridge reported changed between the chunks of one build")
        made_model = got["model"]
        made_vectors.update({sha: vectors.pack(vec) for (sha, _), vec in zip(group, got["vectors"])})   # at once: no list of the numbers is kept
    theme_rows, vector_rows, kept, made = [], [], 0, 0
    for book in books:
        for made_theme, texts in book["themes"]:
            hashes = {field: sha256(text) for field, text in texts.items()}
            theme_rows.append((book["book_id"], book["version_id"], made_theme["id"], book["card_generation"], book["theme_generation"], book["title"],
                               citation_line(book["citation_base"], made_theme["anchor"]["path"]), json.dumps(made_theme, sort_keys=True),
                               json.dumps(hashes, sort_keys=True)))
            for field, sha in hashes.items():
                if sha in old:
                    blob, kept = old[sha], kept + 1
                else:
                    blob, made = made_vectors[sha], made + 1
                vector_rows.append((book["book_id"], book["version_id"], made_theme["id"], field, sha, blob))
    counts["themes"], counts["built"] = len(theme_rows), len(books)
    model = made_model or (old_model if keeps else None) or entry["model"]
    meta = {"format": str(FORMAT), "model": model, "configured": entry["model"], "dimension": str(entry["dimension"]),
            "document_prefix_sha256": vectors.prefix_hash(entry), "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with lock(index_root):
        folder = None
        try:
            _clean_leftovers(index_root)
            # the file is built in a folder of its own, private to the owner and with a name no one can know before it is made, so that
            # nothing at a name that could be guessed is opened or made private; it is then renamed into place
            folder = tempfile.mkdtemp(prefix=BUILD_PREFIX, dir=index_root)
            identity = vectors._identity(folder)
            fresh = os.path.join(folder, INDEX_FILE)
            connect(fresh, create=True).close()
            os.chmod(fresh, 0o600)  # the themes are about the owner's books, and so are the vectors made from them
            with closing(connect(fresh)) as conn:
                conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items()))
                conn.executemany("INSERT INTO themes (book_id, version_id, theme_id, card_generation, theme_generation, book_title, citation, theme, hashes) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", theme_rows)
                conn.executemany("INSERT INTO vectors (book_id, version_id, theme_id, field, text_sha256, vector) VALUES (?, ?, ?, ?, ?, ?)", vector_rows)
                conn.commit()
            store._guard()  # and the library is still there: if it went away part way, most of it was counted as unreadable
            if vectors._identity(folder) != identity:
                raise KbError("the folder in which the file of theme vectors was built is not the one that was made; nothing was put in place")
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                vectors._remove(stale, "a file of the old theme vectors")
            os.replace(fresh, final)
        except sqlite3.Error as e:
            raise KbError(f"the file of theme vectors could not be written ({e})") from None
        except OSError as e:
            raise KbError(f"the file of theme vectors could not be written ({e.strerror or 'error'})") from None
        finally:
            if folder is not None:  # whatever went wrong, the old file is as it was and no folder of the build is left
                shutil.rmtree(folder, ignore_errors=True)
    return {**counts, "vectors": len(vector_rows), "kept": kept, "made": made, "texts_sent": len(todo), "model": model,
            "dimension": entry["dimension"], "replaced": reason is not None}


def _shown(value):
    """A text of the file as it is shown: cleaned, and withheld if its letters hold the words of an untrusted-text marker (as a card is shown)."""
    return card._shown(value)


def render(row):
    """The theme of a row as text for a reader, without a marker: its title and type, its summary, and each part that has text with its
    mark. Everything in it is model output or text of a book, so it is shown only between the untrusted-text markers."""
    made = row["theme"]
    lines = [f"{_shown(made['title'])} ({made['type']})", f"Summary: {_shown(made['summary'])}"]
    for name in theme.PARTS:
        part = made["neutral"][name]
        if part["text"]:
            lines.append(f"{name} [{part['mark']}]: {_shown(part['text'])}")
    return "\n".join(lines)


def result_of(row, score, field):
    """One result from a theme read from the file (`read_themes`): the theme's id and place, its whole anchor, its summary, the text that
    matched (`field`) as the excerpt with the mark of that part (`stated` or `inferred`, or `None` for the summary and the whole
    description), the citation, the flags and the generations. The mark is one of two fixed words, never text of the theme."""
    made = row["theme"]
    text = texts_of(made)[field]
    mark = made["neutral"][field]["mark"] if field in theme.PARTS else None
    return {"book_id": row["book_id"], "version_id": row["version_id"], "theme_id": row["theme_id"], "theme_generation": row["theme_generation"],
            "card_generation": row["card_generation"], "book_title": _shown(row["book_title"]), "theme_title": _shown(made["title"]), "type": made["type"],
            "summary": _shown(made["summary"]), "confidence": made["confidence"], "anchor": made["anchor"], "score": score, "matched": [field],
            "excerpt_field": field, "excerpt_mark": mark, "flags": [{"kind": _shown(f["kind"]), "detail": _shown(f["detail"])} for f in made["flags"]],
            "citation": row["citation"], "untrusted": True, "excerpt": f"{fulltext.MARKER}\n{_shown(fulltext.excerpt_of(text, []))}",
            "text": f"{fulltext.MARKER}\n{render(row)}\n{reading.END_MARKER}"}


def search(index_root, cfg, query, limit=fulltext.DEFAULT_LIMIT, launcher=None, root=None):
    """Search by meaning. The query is turned into a vector by the embedding model that the config sets for `card-embed` (with the entry's
    query prefix, if it has one), and each theme is ranked by the cosine between it and the closest of the theme's vectors, larger being
    closer. Returns `{"meaning", "model", "query_prefix", "built", "themes_searched", "stale", "without_vector", "results"}`: one result for
    each theme, at most `limit`. A vector is used only if it is a vector of the entry's dimension that is finite and not all zeros, its theme
    is in the file, and its text still hashes to the hash the theme row holds for that text: any other is left out and counted in `stale`,
    and a theme with no vector that can be used is counted in `without_vector`. Refused before the query is sent: a query that is not text,
    a limit out of range, no file or a file that is not the engine's, a file for another model, dimension or document prefix, a row that is
    not what the engine writes. Refused after it: a reply for the query from another model than the one that made the vectors, or a vector
    for the query with no length. Reads the file read-only and writes nothing; only the query goes to the model. The file shows the themes
    as of its build."""
    if type(limit) is not int or not 1 <= limit <= fulltext.MAX_LIMIT:
        raise KbError(f"the limit must be a whole number from 1 to {fulltext.MAX_LIMIT}")
    query = vectors._query(query)
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    with closing(connect(path_of(index_root), readonly=True)) as conn:   # one connection to the end, so that the themes and the vectors are of one file
        meta = check_entry(conn, entry)
        rows = read_themes(conn)
        check_vector_rows(conn)   # a row that is not the engine's is refused here, before the query is sent
        got = models.embed(cfg, name, [query], launcher=launcher, root=root, kind="query")
        if got["model"] != meta["model"]:
            raise KbError(f"the model that answered for the query ({textutil.clean(got['model'], 60)}) is not the one that made the vectors; "
                          f"run `{COMMAND}` to build them again")
        q = vectors._unit(got["vectors"][0])
        if q is None:
            raise KbError("the vector for the query has no length")
        by_theme = {(r["book_id"], r["version_id"], r["theme_id"]): r for r in rows}
        best, stale = {}, 0   # for each theme: the closest of its vectors so far, and the text it is the vector of
        for v in iter_vectors(conn, entry["dimension"], lenient=True, ordered=False):   # one vector at a time: none is kept
            key = (v["book_id"], v["version_id"], v["theme_id"])
            row = by_theme.get(key)
            unit = None
            if row is not None and v["vector"] is not None and row["hashes"].get(v["field"]) == v["text_sha256"]:
                unit = vectors._unit(v["vector"])
            if unit is None:
                stale += 1
                continue
            cosine = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(q, unit))))
            held = best.get(key)
            # a tie goes to the first text in the order of FIELDS, whatever the order in which the rows come
            if held is None or cosine > held[0] or (cosine == held[0] and FIELDS.index(v["field"]) < FIELDS.index(held[1])):
                best[key] = (cosine, v["field"])
    ranked = sorted(((round(cosine, 12), key, field) for key, (cosine, field) in best.items()), key=lambda r: (-r[0], r[1]))
    return {"meaning": True, "model": meta["model"], "query_prefix": "query_prefix" in entry, "built": meta["built"], "themes_searched": len(best),
            "stale": stale, "without_vector": sum(1 for key in by_theme if key not in best),
            "results": [result_of(by_theme[key], score, field) for score, key, field in ranked[:limit]]}
