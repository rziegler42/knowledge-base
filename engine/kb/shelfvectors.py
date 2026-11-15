"""The vectors of the shelves of the schema: one SQLite file in the index root with a vector for each shelf of the tracked schema file, made by the
embedding model that the owner's config names for the task `place-embed` (`docs/specs/shelf.md`, "Placement when more than one shelf fits";
the plan `2026-11-15-propose-a-shelf-for-each-book`, Increment A).

    shelf-vectors.sqlite
      meta      the format, the model as the bridge named it, the name the config gave the model, the dimension, the hash of the document prefix
                the vectors were made with (that of an empty text), the SHA-256 of the schema file they were made from, the date of the build
      shelves   one row per shelf: its slug, the SHA-256 of the text the vector was made from, and the vector as little-endian 32-bit floats

A shelf's text is its name, a full stop, a space and its scope sentence, in the order of the schema file. That is the text the matcher was measured with
(`2026-11-14-measure-the-shelf-matcher`); the vectors of the coarser levels (domain, field, subfield) are kept too, because the matcher rolls counts up through them.

The file is derived from the schema and the model and can be thrown away. `build` keeps the vector of a row whose text has not changed and sends the others
to the embedding model, and writes a new file in a folder of its own that it renames into place under the writers' lock of the catalog. The placement was
measured with one embedding model and no document prefix, so a build refuses an entry that names another model or has a prefix: another model is a new
measurement and a new plan. `load` returns the vectors only for a file that was made for the entry that is set, from the schema file as it is now, with every
shelf of the schema once and no other; a stale or foreign file is refused.

Vectors are model output, so they are checked when they are made and again when they are read: the right length, finite numbers and not all zeros."""
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import KbError, catalog, models, shelfmatch, textutil
from .vectors import _identity, _remove, pack, unpack

INDEX_FILE = "shelf-vectors.sqlite"
BUILD_PREFIX = ".shelf-vectors-build-"  # the folders in which a build is made; a killed build leaves one, and the next removes it
FORMAT = 1
COMMAND = "python3 -m kb shelf-vectors"
TASK = "place-embed"
MEASURED_MODEL = "qwen3-embedding:4b"  # the embedding model the placement was measured with (`2026-11-14-measure-the-shelf-matcher`)
DEFAULT_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "shelf-schema.json")
_META_KEYS = ("format", "model", "configured", "dimension", "built", "document_prefix_sha256", "schema_sha256")
_COLUMNS = ["slug", "text_sha256", "vector"]
_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE shelves (slug TEXT PRIMARY KEY, text_sha256 TEXT NOT NULL, vector BLOB NOT NULL)",
)
_HEX = set("0123456789abcdef")
_DIMENSION = re.compile(r"[0-9]{1,4}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path):
    """The SHA-256 of the bytes of a file (the schema file), read through a plain open."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError as e:
        raise KbError(f"the schema file cannot be read ({e.strerror}): {textutil.clean(str(path), 120)}") from None


def texts(schema):
    """[(slug, text)] for every shelf of a schema (as `shelfmatch.schema_from_data` gives it), in the order of the file."""
    return [(s["slug"], s["name"] + ". " + s["scope"]) for s in schema.shelves]


def entry_for(cfg):
    """`(name, entry)` of the embedding entry that is set for the task `place-embed`: refused when none is set, when model work is off, and
    when the entry is not the measured configuration (the model `qwen3-embedding:4b`, no document prefix)."""
    name, _ = models.choose(cfg, TASK)
    entry = models.registry(cfg)[name]
    if entry["model"] != MEASURED_MODEL:
        raise KbError(f"tasks.{TASK} names the entry {name}, which uses {textutil.clean(entry['model'], 60)}; placement was measured with "
                      f"{MEASURED_MODEL} only, and another model needs a new measurement and a new plan")
    if entry.get("document_prefix"):
        raise KbError(f"the entry {name} has a document prefix; placement was measured with no prefix, and a vector depends on the prefix its text was sent with")
    return name, entry


def prefix_hash(entry):
    return sha256(entry.get("document_prefix", ""))


def connect(path, create=False, readonly=False):
    """The file of shelf vectors at `path`, checked: a database of this engine's shape that holds nothing else, and not a link. A file that
    is not, or is missing, is a refusal that says what to do. `readonly` opens it so that nothing can be written or replayed."""
    if not create and (not os.path.lexists(path) or os.path.islink(path) or not os.path.isfile(path)):
        raise KbError(f"there is no file of shelf vectors yet: run `{COMMAND}` to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError("the path of the file of shelf vectors cannot be opened as a file") from None
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
        raise KbError(f"the file of shelf vectors cannot be opened ({e}): run `{COMMAND}` to build it again") from None


def _check_shape(conn):
    again = f"run `{COMMAND}` to build it again"
    if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
        raise KbError(f"the file of shelf vectors is not in the shape this version of the engine writes: {again}")
    objects = conn.execute("SELECT type, name FROM sqlite_master").fetchall()
    if any(kind in ("trigger", "view") for kind, _ in objects):
        raise KbError(f"the file of shelf vectors holds a trigger or a view this engine did not put there: {again}")
    names = {name for kind, name in objects if kind == "table"}
    if names != {"meta", "shelves"}:
        raise KbError(f"the tables of the file of shelf vectors are not the ones this version of the engine writes: {again}")
    if [r[1] for r in conn.execute("PRAGMA table_info(shelves)")] != _COLUMNS or [r[1] for r in conn.execute("PRAGMA table_info(meta)")] != ["key", "value"]:
        raise KbError(f"the tables of the file of shelf vectors are not the ones this version of the engine writes: {again}")


def _meta(conn):
    try:
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as e:
        raise KbError(f"the file of shelf vectors cannot be read ({e}): run `{COMMAND}` to build it again") from None
    if (set(rows) != set(_META_KEYS) or not all(isinstance(v, str) for v in rows.values()) or rows["format"] != str(FORMAT)
            or not _DIMENSION.fullmatch(rows["dimension"]) or not 1 <= int(rows["dimension"]) <= models.MAX_DIMENSION
            or not models._valid_model(rows["model"]) or not models._valid_model(rows["configured"]) or len(rows["built"]) > 40
            or len(rows["document_prefix_sha256"]) != 64 or set(rows["document_prefix_sha256"]) - _HEX
            or len(rows["schema_sha256"]) != 64 or set(rows["schema_sha256"]) - _HEX):
        raise KbError(f"the file of shelf vectors does not say which model and schema made it: run `{COMMAND}` to build it again")
    return rows


def check_entry(conn, entry):
    """Refuse a file made for another model or dimension, or with another document prefix, than the embedding entry that is set. Returns its meta."""
    rows = _meta(conn)
    if (rows["configured"] != entry["model"] or int(rows["dimension"]) != entry["dimension"] or rows["document_prefix_sha256"] != prefix_hash(entry)):
        raise KbError(f"the file of shelf vectors was made for another model, dimension or document prefix than the ones set in the config: run `{COMMAND}` to build it again")
    return rows


def read_rows(conn, dimension, lenient=False):
    """`{slug: (text_sha256, vector)}` of the file, each row checked; a vector that is not a vector of `dimension` finite numbers that are not all zero is
    a refusal, or, with `lenient`, a row that is left out (the caller counts it)."""
    again = f"run `{COMMAND}` to build it again"
    try:
        rows = conn.execute("SELECT slug, text_sha256, vector FROM shelves ORDER BY slug").fetchall()
    except sqlite3.Error as e:
        raise KbError(f"the file of shelf vectors cannot be read ({e}): {again}") from None
    out = {}
    for slug, digest, blob in rows:
        if not isinstance(slug, str) or not _SLUG.fullmatch(slug) or not isinstance(digest, str) or len(digest) != 64 or set(digest) - _HEX:
            raise KbError(f"the file of shelf vectors holds a row that is not what this engine writes: {again}")
        try:
            vector = unpack(blob, dimension)
        except KbError:
            if not lenient:
                raise KbError(f"the file of shelf vectors holds a vector that is not of the dimension {dimension}, not finite or all zeros: {again}") from None
            continue
        out[slug] = (digest, vector)
    return out


def _check_made_by_the_measured_model(meta):
    """The model the bridge reported when the file was made must be the measured one: the configured name alone does not say what answered."""
    if meta["model"] != MEASURED_MODEL:
        raise KbError(f"the file of shelf vectors was made by {textutil.clean(meta['model'], 60)}, not by the measured model {MEASURED_MODEL}: run `{COMMAND}` to build it again")


def _old_rows(final, entry):
    """`({slug: (text_sha256, vector)}, model, reason)` of the file in place, for the rows a build may keep; `reason` says why it cannot be used (and is
    None when there is no file or it is usable)."""
    if not os.path.lexists(final):
        return {}, None, None
    try:
        with closing(connect(final, readonly=True)) as conn:
            meta = check_entry(conn, entry)
            _check_made_by_the_measured_model(meta)
            return read_rows(conn, entry["dimension"], lenient=True), meta["model"], None
    except KbError as e:
        return {}, None, str(e)


def _read_schema(schema_path):
    """`(schema, SHA-256 of the file)`: the file is read as data by the checker, and its hash is taken before and after so that a file changed while it was read is refused."""
    first = file_sha256(schema_path)
    schema = shelfmatch.load_schema(schema_path)
    if file_sha256(schema_path) != first:
        raise KbError("the schema file changed while it was being read")
    return schema, first


def describe(cfg, schema_path=None, index_root=None, again=False):
    """What a build would send, as words, and nothing sent: the entry, the number and the size of the texts and how many of them are not already in the
    file at `index_root` (all of them when no `index_root` is given, there is no usable file, or `again` is true, as for `build`)."""
    name, entry = entry_for(cfg)
    schema, _ = _read_schema(schema_path or DEFAULT_SCHEMA)
    items = texts(schema)
    old = _old_rows(path_of(index_root), entry)[0] if index_root and not again else {}
    todo = [t for slug, t in items if slug not in old or old[slug][0] != sha256(t)]
    sizes = [len(t.encode("utf-8")) for _, t in items]
    return "\n".join([
        f"Entry {name}: model {entry['model']}, dimension {entry['dimension']}, kind embedding, no document prefix is used.",
        "Would send, as plain documents, to the entry's model server on your network (plain unauthenticated http, in the clear), through kb.models.embed:",
        f"  {len(items)} shelf texts (name, a full stop, scope sentence): {sum(sizes)} bytes in all; the longest is {max(sizes)} bytes; the first is: {textutil.clean(items[0][1], 120)}",
        f"  {len(todo)} of them are not in the file and would be sent ({sum(len(t.encode('utf-8')) for t in todo)} bytes); the rest would be kept.",
        "The shelf texts are public (OpenAlex topic descriptions and the names of Library of Congress subclasses); nothing of the library, the notes or the questions is sent.",
    ])


def build(store, cfg, schema_path=None, again=False, launcher=None, root=None):
    """Build the file of shelf vectors again from the schema file and put it in place of the old one. Returns the counts: the shelves, the vectors `kept`
    from the old file and `made` now, the texts sent (`texts_sent`), the model the bridge reported, the dimension, the schema's hash and whether the old
    file was not usable (another format, model, dimension or document prefix, or damaged) and so `replaced`. With `again`, every vector is made again.
    Refused: model work off, no `place-embed` set in the config or an entry that is not the measured one, a schema the checker refuses, a model that
    the bridge reports as another than the one that made the vectors that are kept, a library that is not there. A failure leaves the old file as it was."""
    if type(again) is not bool:
        raise KbError("again is true or false")
    name, entry = entry_for(cfg)
    schema, schema_hash = _read_schema(schema_path or DEFAULT_SCHEMA)
    store._guard()  # the library's marker and device: an unmounted drive must not give an empty file
    index_root = store.cfg["index_root"]
    final = path_of(index_root)
    items = texts(schema)
    old, old_model, reason = _old_rows(final, entry)
    if again:
        old = {}  # every vector is made again
    rows, todo = [], []
    for slug, text in items:
        digest = sha256(text)
        kept = old.get(slug)
        if kept is not None and kept[0] == digest:
            rows.append((slug, digest, kept[1]))
        else:
            todo.append((slug, digest, text))
    made, made_model = [], None
    per = max(1, models.MAX_EMBED_NUMBERS // entry["dimension"])  # as many texts at a time as their vectors can be held in memory
    for start in range(0, len(todo), per):
        group = todo[start:start + per]
        got = models.embed(cfg, name, [t[2] for t in group], launcher=launcher, root=root, kind="document")
        if rows and got["model"] != old_model:
            raise KbError(f"the model the bridge reports ({textutil.clean(got['model'], 60)}) is not the one that made the vectors that are kept "
                          f"({textutil.clean(old_model, 60)}); run `{COMMAND} --again` to make every vector again")
        if made_model is not None and got["model"] != made_model:
            raise KbError("the model that the bridge reported changed between the chunks of one build")
        if got["model"] != MEASURED_MODEL:
            raise KbError(f"the model the bridge reports ({textutil.clean(got['model'], 60)}) is not the measured one ({MEASURED_MODEL}); nothing was written")
        made_model = got["model"]
        made += [(s, h, vec) for (s, h, _), vec in zip(group, got["vectors"])]
    rows += made
    order = {slug: i for i, (slug, _) in enumerate(items)}
    rows.sort(key=lambda r: order[r[0]])
    model = made_model or old_model or entry["model"]
    meta = {"format": str(FORMAT), "model": model, "configured": entry["model"], "dimension": str(entry["dimension"]),
            "document_prefix_sha256": prefix_hash(entry), "schema_sha256": schema_hash, "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with catalog.lock(index_root):
        folder = None
        try:
            _clean_leftovers(index_root)
            # the file is built in a folder of its own, private to the owner and with a name no one can know before it is made, so that nothing at a name
            # that could be guessed is opened or made private; it is then renamed into place
            folder = tempfile.mkdtemp(prefix=BUILD_PREFIX, dir=index_root)
            identity = _identity(folder)
            fresh = os.path.join(folder, INDEX_FILE)
            connect(fresh, create=True).close()
            os.chmod(fresh, 0o600)
            with closing(connect(fresh)) as conn:
                conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items()))
                conn.executemany("INSERT INTO shelves (slug, text_sha256, vector) VALUES (?, ?, ?)", [(s, h, pack(vec)) for s, h, vec in rows])
                conn.commit()
            store._guard()
            if _identity(folder) != identity:
                raise KbError("the folder in which the file of shelf vectors was built is not the one that was made; nothing was put in place")
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                _remove(stale, "a file of the old shelf vectors")
            os.replace(fresh, final)
        except sqlite3.Error as e:
            raise KbError(f"the file of shelf vectors could not be written ({e})") from None
        finally:
            if folder is not None:  # whatever went wrong, the old file is as it was and no folder of the build is left
                shutil.rmtree(folder, ignore_errors=True)
    return {"shelves": len(rows), "kept": len(rows) - len(made), "made": len(made), "texts_sent": len(todo), "model": model, "dimension": entry["dimension"],
            "schema_sha256": schema_hash, "replaced": reason is not None}


def _clean_leftovers(index_root):
    """Remove what an earlier build that was killed left, under the lock: a folder, a file or a link whose name begins with BUILD_PREFIX. A link is removed as a
    link, and its target is never entered or removed; nothing else in the index root is touched."""
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


def load(index_root, cfg, schema_path=None):
    """The shelf vectors for the placement: `{"meta", "vectors": {slug: [floats]}, "schema", "identity"}`. Refused: no file, a file made for another model,
    dimension or prefix than the entry that is set, a file made from another version of the schema file than the one in place now, a shelf of the schema with
    no row or with a row whose text is not its text now, a row for a shelf that is not in the schema, and any vector that is not a vector."""
    name, entry = entry_for(cfg)
    schema, schema_hash = _read_schema(schema_path or DEFAULT_SCHEMA)
    again = f"run `{COMMAND}` to build it again"
    with closing(connect(path_of(index_root), readonly=True)) as conn:
        meta = check_entry(conn, entry)
        _check_made_by_the_measured_model(meta)
        if meta["schema_sha256"] != schema_hash:
            raise KbError(f"the file of shelf vectors was made from another version of the schema file than the one in place: {again}")
        rows = read_rows(conn, entry["dimension"])
    want = {slug: sha256(text) for slug, text in texts(schema)}
    if set(rows) != set(want):
        raise KbError(f"the file of shelf vectors does not hold exactly the shelves of the schema: {again}")
    if any(rows[slug][0] != digest for slug, digest in want.items()):
        raise KbError(f"the file of shelf vectors holds a vector made from another text than the shelf's text now: {again}")
    identity = sha256("|".join((meta["built"], meta["schema_sha256"], meta["model"], meta["dimension"], meta["document_prefix_sha256"])))
    return {"meta": meta, "vectors": {slug: vector for slug, (_, vector) in rows.items()}, "schema": schema, "identity": identity}
