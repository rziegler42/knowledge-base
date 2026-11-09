"""The vectors of the cards: one SQLite file in the index root with a vector for each of three neutral fields of each card (what the
book is about, its approach, what it provides), made by the embedding model that the owner's config names (`docs/specs/card.md`,
"Where it is stored"; `docs/specs/models.md`, "The embedding model").

    vectors.sqlite
      meta      the format, the model as the bridge named it, the name the config gave the model, the dimension, the date of the build
      vectors   one row per (book, version, field): the generation of the card, the SHA-256 of the text the vector was made from, and
                the vector as little-endian 32-bit floats

The file is derived from the cards and can be thrown away: `build` reads each card through `card.read`, keeps the vector of a row whose
text and model have not changed, sends every other text to the embedding model and writes a new file beside the old one, which it
renames into place under the writers' lock of the catalog. The needs and the limits of a card are not embedded: a sample found most of
their sentences not in the book (the plan `2026-11-09-search-the-neutral-descriptions-by-meaning`, Increment A). A file that this
engine did not make, or that was made for another model or dimension, is not reused: a build replaces it. A search never mixes the
vectors of two models: it refuses such a file (`connect`, `check_entry`).

Vectors are model output, so they are checked when they are made and again when they are read: the right length, finite numbers and
not all zeros."""
import hashlib
import math
import os
import re
import sqlite3
import struct
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import KbError, card, catalog, models, textutil

INDEX_FILE = "vectors.sqlite"
FORMAT = 1
COMMAND = "python3 -m kb card-vectors"
FIELDS = ("neutral_problem", "neutral_approach", "neutral_provides")  # the fields of a card's model part that are embedded
_META_KEYS = ("format", "model", "configured", "dimension", "built")
_COLUMNS = ["book_id", "version_id", "generation", "field", "text_sha256", "vector"]
_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE vectors (book_id TEXT NOT NULL, version_id TEXT NOT NULL, generation INTEGER NOT NULL, field TEXT NOT NULL, "
    "text_sha256 TEXT NOT NULL, vector BLOB NOT NULL, PRIMARY KEY (book_id, version_id, field))",
)
_HEX = set("0123456789abcdef")
_DIMENSION = re.compile(r"[0-9]{1,4}")


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pack(vector):
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob, dimension):
    """The numbers of a stored vector, or a refusal if it is not a vector of `dimension` finite numbers that are not all zero."""
    if not isinstance(blob, bytes) or len(blob) != 4 * dimension:
        raise KbError(f"the file of vectors holds a vector that is not of the dimension {dimension}: run `{COMMAND}` to build it again")
    numbers = list(struct.unpack(f"<{dimension}f", blob))
    if not all(math.isfinite(x) for x in numbers) or not any(numbers):
        raise KbError(f"the file of vectors holds a vector that is not finite or is all zeros: run `{COMMAND}` to build it again")
    return numbers


def connect(path, create=False, readonly=False):
    """The file of vectors at `path`, checked: a database of this engine's shape that holds nothing else, and not a link. A file that
    is not, or is missing, is a refusal that says what to do. `readonly` opens it so that nothing can be written or replayed."""
    if not create and (not os.path.lexists(path) or os.path.islink(path) or not os.path.isfile(path)):
        raise KbError(f"there is no file of vectors yet: run `{COMMAND}` to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError("the path of the file of vectors cannot be opened as a file") from None
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
        raise KbError(f"the file of vectors cannot be opened ({e}): run `{COMMAND}` to build it again") from None


def _check_shape(conn):
    again = f"run `{COMMAND}` to build it again"
    if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
        raise KbError(f"the file of vectors is not in the shape this version of the engine writes: {again}")
    objects = conn.execute("SELECT type, name FROM sqlite_master").fetchall()
    if any(kind in ("trigger", "view") for kind, _ in objects):
        raise KbError(f"the file of vectors holds a trigger or a view this engine did not put there: {again}")
    names = {name for kind, name in objects if kind == "table"}
    if names != {"meta", "vectors"}:
        raise KbError(f"the tables of the file of vectors are not the ones this version of the engine writes: {again}")
    if [r[1] for r in conn.execute("PRAGMA table_info(vectors)")] != _COLUMNS or [r[1] for r in conn.execute("PRAGMA table_info(meta)")] != ["key", "value"]:
        raise KbError(f"the tables of the file of vectors are not the ones this version of the engine writes: {again}")


def _meta(conn):
    rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    if (set(rows) != set(_META_KEYS) or not all(isinstance(v, str) for v in rows.values()) or rows["format"] != str(FORMAT)
            or not _DIMENSION.fullmatch(rows["dimension"]) or not 1 <= int(rows["dimension"]) <= models.MAX_DIMENSION
            or not models._valid_model(rows["model"]) or not models._valid_model(rows["configured"]) or len(rows["built"]) > 40):
        raise KbError(f"the file of vectors does not say which model made it: run `{COMMAND}` to build it again")
    return rows


def check_entry(conn, entry):
    """Refuse a file made for another model or dimension than the embedding entry that is set (`entry` as `models.registry` gives it).
    Returns the meta of the file."""
    rows = _meta(conn)
    if rows["configured"] != entry["model"] or int(rows["dimension"]) != entry["dimension"]:
        raise KbError(f"the file of vectors was made for another model or dimension than the one set in the config: run `{COMMAND}` to build it again")
    return rows


def read_rows(conn, dimension):
    """The rows of the file, each checked: `[{book_id, version_id, generation, field, text_sha256, vector}]`, vector as a list of floats.
    A row that is not what this engine writes (a field that is not embedded, a hash that is not a hash, a vector that is not a vector of
    `dimension` finite numbers that are not all zero) is a refusal."""
    again = f"run `{COMMAND}` to build it again"
    out = []
    try:
        rows = conn.execute("SELECT book_id, version_id, generation, field, text_sha256, vector FROM vectors "
                            "ORDER BY book_id, version_id, field").fetchall()
    except sqlite3.Error as e:
        raise KbError(f"the file of vectors cannot be read ({e}): {again}") from None
    for book_id, version_id, generation, field, sha, blob in rows:
        if (not isinstance(book_id, str) or not isinstance(version_id, str) or type(generation) is not int or generation < 1
                or field not in FIELDS or not isinstance(sha, str) or len(sha) != 64 or set(sha) - _HEX):
            raise KbError(f"the file of vectors holds a row that is not what this engine writes: {again}")
        out.append({"book_id": book_id, "version_id": version_id, "generation": generation, "field": field, "text_sha256": sha,
                    "vector": unpack(blob, dimension)})
    return out


def _cards(store):
    """`(texts, counts)`: the text of each embedded field of the newest card of each version of each active book, as
    `[(book_id, version_id, generation, field, text)]` in a fixed order, and the counts of the cards read."""
    counts = {"cards": 0, "no_model": 0, "left_out": 0}
    texts = []
    for book_id in store.list_books():
        try:
            book = store.read_book(book_id)
            versions = store.version_ids(book_id)
        except KbError:
            counts["left_out"] += 1
            continue
        if book.get("state") != "active":
            continue
        for version_id in versions:
            try:
                if not card.generations(store, book_id, version_id):
                    continue
                number, made = card.read(store, book_id, version_id)
            except KbError:
                counts["left_out"] += 1
                continue
            fields = []
            for field in FIELDS if made["model"] is not None else ():
                text = made["model"].get(field, "")
                if isinstance(text, str) and text.strip():
                    try:
                        text.encode("utf-8")
                    except UnicodeEncodeError:
                        fields = None  # a text that cannot be sent: the card is left out and counted, and the others go on
                        break
                    fields.append((book_id, version_id, number, field, text))
            if fields is None:
                counts["left_out"] += 1
                continue
            counts["cards"] += 1
            if made["model"] is None:
                counts["no_model"] += 1
            texts += fields
    return texts, counts


def _old_rows(path, entry):
    """`(rows, model, reason)`: the rows of the existing file that may be kept, as `{(book_id, version_id, field): (sha, vector)}`, the
    model the file says made them, and why there are none (`None` when there is no file, or the file is good). A file that is not this
    engine's, or is for another model or dimension, gives no rows and a reason: the build replaces it."""
    if not os.path.lexists(path):
        return {}, None, None
    try:
        with closing(connect(path, readonly=True)) as conn:
            meta = check_entry(conn, entry)
            kept = {}
            for row in conn.execute("SELECT book_id, version_id, field, text_sha256, vector FROM vectors").fetchall():
                book_id, version_id, field, sha, blob = row
                try:
                    kept[(book_id, version_id, field)] = (sha, unpack(blob, entry["dimension"]))
                except KbError:
                    continue  # a damaged vector is not kept; it is made again
            return kept, meta["model"], None
    except (KbError, sqlite3.Error) as e:
        return {}, None, textutil.clean(str(e), 160) or "the file cannot be used"


def _insert(conn, meta, rows):
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items()))
    conn.executemany("INSERT INTO vectors (book_id, version_id, generation, field, text_sha256, vector) VALUES (?, ?, ?, ?, ?, ?)",
                     [(b, v, g, f, h, pack(vec)) for b, v, g, f, h, vec in rows])


def build(store, cfg, again=False, launcher=None, root=None):
    """Build the file of vectors again from the cards and put it in place of the old one. Returns the counts: the cards read, the cards
    with no model part, the cards and books that could not be read (`left_out`), the vectors in the file, the vectors `kept` from the old
    file and `made` now, the texts sent (`texts_sent`), the model the bridge reported, the dimension and whether the old file was not
    usable and so `replaced`. With `again`, every vector is made again. Refused: model work off, no `card-embed` set in the config,
    a model that the bridge reports as another than the one that made the vectors that are kept, a library that is not there. A failure
    leaves the old file as it was. Only the text of the embedded fields is sent. The cards and the old file are read before the models are
    called, and the lock is taken only to write: a card made, or a second build, while the texts are with the model gives a file that
    is valid for the cards that were read, and a search treats a vector whose text no longer matches its card as stale."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    store._guard()  # the library's marker and device: an unmounted drive must not give an empty file
    index_root = store.cfg["index_root"]
    final = path_of(index_root)
    texts, counts = _cards(store)
    old, old_model, reason = _old_rows(final, entry)
    if again:
        old = {}  # every vector is made again
    rows, todo = [], []
    for book_id, version_id, number, field, text in texts:
        sha = sha256(text)
        kept = old.get((book_id, version_id, field))
        if kept is not None and kept[0] == sha:
            rows.append((book_id, version_id, number, field, sha, kept[1]))
        else:
            todo.append((book_id, version_id, number, field, sha, text))
    made, made_model = [], None
    per = max(1, models.MAX_EMBED_NUMBERS // entry["dimension"])  # as many texts at a time as their vectors can be held in memory
    for start in range(0, len(todo), per):
        group = todo[start:start + per]
        got = models.embed(cfg, name, [t[5] for t in group], launcher=launcher, root=root)
        if rows and got["model"] != old_model:
            raise KbError(f"the model the bridge reports ({textutil.clean(got['model'], 60)}) is not the one that made the vectors that "
                          f"are kept ({textutil.clean(old_model, 60)}); run `{COMMAND} --again` to make every vector again")
        if made_model is not None and got["model"] != made_model:
            raise KbError("the model that the bridge reported changed between the chunks of one build")
        made_model = got["model"]
        made += [(b, v, g, f, h, vec) for (b, v, g, f, h, _), vec in zip(group, got["vectors"])]
    rows += made
    rows.sort(key=lambda r: (r[0], r[1], r[3]))
    model = made_model or (old_model if rows else None) or entry["model"]
    meta = {"format": str(FORMAT), "model": model, "configured": entry["model"], "dimension": str(entry["dimension"]),
            "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    fresh = final + ".new"
    with catalog.lock(index_root):
        in_place = False
        try:
            for leftover in (fresh, fresh + "-journal"):
                _remove(leftover, "a half-built file of vectors")
            connect(fresh, create=True).close()
            os.chmod(fresh, 0o600)  # the cards are the owner's, and so are the vectors made from them: private before it holds any
            with closing(connect(fresh)) as conn:
                _insert(conn, meta, rows)
                conn.commit()
            store._guard()  # and the library is still there: if it went away part way, most of it was counted as unreadable
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                _remove(stale, "a file of the old vectors")
            os.replace(fresh, final)
            in_place = True
        except sqlite3.Error as e:
            raise KbError(f"the file of vectors could not be written ({e})") from None
        finally:
            if not in_place:  # whatever went wrong, the old file is as it was and no half-built file is left
                for leftover in (fresh, fresh + "-journal"):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
    return {**counts, "vectors": len(rows), "kept": len(rows) - len(made), "made": len(made), "texts_sent": len(todo), "model": model,
            "dimension": entry["dimension"], "replaced": reason is not None}


def _remove(path, what):
    if os.path.lexists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise KbError(f"{what} is in the way and cannot be removed ({e.strerror}): {path}") from None
