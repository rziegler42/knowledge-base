"""The links of a weave of "same mechanism": which links a theme keeps (`docs/specs/weave.md`, "Keeping the graph sparse without losing novelty"; the plan
`2026-11-13-link-themes-that-work-the-same-way`). The selection (`select`, `exact_ranks`, `exact_quantiles`) is pure functions of vectors and reads no file;
the file of the weave, its checked reading and its build (`build`, `read`) follow it.

The rule, as the owner agreed it:

  * A link joins two themes of different books. Links are two-way and counted once.
  * The closeness of two themes is the dot product of their unit vectors, worked out in double precision and kept as an integer in billionths (rounded half to even), so
    that the same pair gives the same number whatever the block it was worked out in (a product within about 1e-16 of a half billionth is the one case where it could not).
  * Every pair of themes of different books falls in one of four bands of wording distance: the quarters of the closeness of their summary vectors, with the edges at the
    25th, 50th and 75th percentile of all such pairs (band 0 is the farthest in wording, band 3 the nearest).
  * The floor: a link is kept only if the closeness of the method vectors is greater than the median of all such pairs. A pair exactly at the median is not linked.
  * The slot rule: each theme has `slots` (3) in each band, so at most 12 links; a link takes one slot at each end; a theme links to at most one theme of one book in a band;
    links are taken from the strongest closeness down, a tie going to the keys of the themes. A pair exactly on an edge is in the band above it.
  * A bound that the plan and the spec do not state: each theme puts forward only its `top` (300) closest partners in each band, so that memory grows with the number of
    themes and not with its square. A theme whose candidates in a band are all taken, or all of books it already links to in that band, gets no further link there even if
    other partners are free. The rule without the cut is `top` at least the number of themes. How often the cut changes a result is for the real library to say.

The median and the edges are exact (the value at the rank, by linear interpolation between the two nearest values, as `numpy.median` and `numpy.quantile` give it), found in
memory that does not depend on how the values are spread: a radix selection over the blocks. One pass counts the values in 65,536 bins of the top 16 of their 31 bits, and a
second counts the next 15 bits of the bins that hold the ranks, so a rank is pinned to one integer in two passes and equal values are only counts.

numpy is imported where it is needed and not at the top, so that the commands that do not build a weave run without it."""
import fcntl
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from . import KbError, catalog, ids, models, themevectors, vectors

INDEX_FILE = "weave-same-mechanism.sqlite"
PREVIOUS_FILE = "weave-same-mechanism.previous.sqlite"   # the generation before, kept as it was
LOCK_FILE = "weave.lock"
BUILD_PREFIX = ".weave-build-"       # the folders in which a build is made; a killed build leaves one, and the next removes it
FORMAT = 1
KIND = "same-mechanism"
COMMAND = "python3 -m kb theme-links build"
BANDS = 4
SLOTS = 3
TOP = 300
BLOCK = 256
SCALE = 10 ** 9          # a closeness is an integer in billionths
_LOW_BITS = 15           # a value is shifted to 0 to 2e9, which is below 2**31: 16 top bits and 15 low bits
_TOP_BINS = 1 << 16
_LOW_BINS = 1 << _LOW_BITS
_INSTALL = ("numpy is needed to build a weave and it is not installed here: install it from the pinned list with "
            "`engine/.venv/bin/python -m pip install --require-hashes --no-deps -r engine/requirements.lock` and run the command with `engine/.venv/bin/python`")


def _np():
    try:
        import numpy
    except ImportError:
        raise KbError(_INSTALL) from None
    return numpy


def _unsigned(np, values):
    """The values of one block (integers in billionths from -1e9 to 1e9) shifted to 0 to 2e9, or a refusal."""
    arr = np.asarray(values)
    if arr.dtype.kind not in "iu":
        raise KbError("the values to select from are not integers")
    if arr.size and (int(arr.min()) < -SCALE or int(arr.max()) > SCALE):
        raise KbError("a value is outside the closeness of two unit vectors")
    return arr.astype(np.int64) + SCALE


def _first_pass(np, passes):
    counts = np.zeros(_TOP_BINS, dtype=np.int64)
    for block in passes():
        counts += np.bincount(_unsigned(np, block) >> _LOW_BITS, minlength=_TOP_BINS)
    return counts


def _second_pass(np, passes, counts, ranks):
    cum = np.cumsum(counts)
    total = int(cum[-1])
    where = []
    for r in ranks:
        if type(r) is not int or not 0 <= r < total:
            raise KbError(f"a rank must be a whole number from 0 to {total - 1}")
        top = int(np.searchsorted(cum, r, side="right"))
        where.append((top, r - int(cum[top] - counts[top])))
    needed = sorted({top for top, _ in where})
    lut = np.full(_TOP_BINS, -1, dtype=np.int64)
    lut[needed] = np.arange(len(needed))
    acc = np.zeros(len(needed) * _LOW_BINS, dtype=np.int64)
    for block in passes():
        u = _unsigned(np, block)
        slot = lut[u >> _LOW_BITS]
        hit = slot >= 0
        if hit.any():
            acc += np.bincount(slot[hit] * _LOW_BINS + (u[hit] & (_LOW_BINS - 1)), minlength=len(acc))
    out = []
    for top, inner in where:
        row = np.cumsum(acc[needed.index(top) * _LOW_BINS:(needed.index(top) + 1) * _LOW_BINS])
        low = int(np.searchsorted(row, inner, side="right"))
        out.append(((top << _LOW_BITS) | low) - SCALE)
    return out


def exact_ranks(passes, ranks):
    """The values at the given ranks (0 is the least) of all the values that `passes()` yields, a block at a time, each pass the same blocks in the same order. The values are
    integers in billionths from -1e9 to 1e9. Two passes, and memory fixed by the bins whatever the values are."""
    np = _np()
    ranks = list(ranks)
    return _second_pass(np, passes, _first_pass(np, passes), ranks)


def _lerp(a, b, t):
    """numpy's linear interpolation, in its own arithmetic."""
    diff = b - a
    result = a + diff * t
    if t >= 0.5:
        result = b - diff * (1 - t)
    return result


def exact_quantiles(passes, qs):
    """The values at the quantiles qs (0 to 1) of all the values that `passes()` yields, by linear interpolation between the two nearest, as `numpy.quantile` gives them (a list
    of floats in billionths), or `None` when there are no values."""
    np = _np()
    qs = list(qs)
    for q in qs:
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0 <= q <= 1:
            raise KbError("a quantile must be a number from 0 to 1")
    counts = _first_pass(np, passes)
    total = int(counts.sum())
    if total == 0:
        return None
    spots = []
    for q in qs:
        pos = (total - 1) * q
        lo = int(math.floor(pos))
        hi = min(lo + 1, total - 1)
        if lo >= total - 1:
            lo = hi = total - 1
        spots.append((lo, hi, pos - lo))
    wanted = sorted({r for lo, hi, _ in spots for r in (lo, hi)})
    value = dict(zip(wanted, _second_pass(np, passes, counts, wanted)))
    return [float(_lerp(np.float64(value[lo]), np.float64(value[hi]), t)) for lo, hi, t in spots]


def _whole(value, name, least=1):
    if type(value) is not int or value < least:
        raise KbError(f"{name} must be a whole number of at least {least}")
    return value


def _prepare(np, keys, books, summaries, methods):
    """The usable themes in the order of their keys, as unit vectors, and the keys of those left out (no vector, a vector that has no length or is not finite)."""
    if not (len(keys) == len(books) == len(summaries) == len(methods)):
        raise KbError("the keys, the books and the vectors must be of the same number")
    try:
        if len(set(keys)) != len(keys):
            raise KbError("two themes have the same key")
        order = sorted(range(len(keys)), key=lambda i: keys[i])
    except TypeError:
        raise KbError("the keys of the themes cannot be put in an order") from None
    kept, left_out, rows_s, rows_m = [], [], [], []
    for i in order:
        pair = []
        for vector in (summaries[i], methods[i]):
            if vector is None:
                pair = None
                break
            try:
                arr = np.asarray(vector, dtype=np.float64)
            except (TypeError, ValueError):
                pair = None
                break
            if arr.ndim != 1 or not arr.size or not np.isfinite(arr).all():
                pair = None
                break
            largest = float(np.abs(arr).max())       # scaled by it first, so that entries near 1e200 or 1e-200 do not overflow or vanish in the length
            if not largest > 0:
                pair = None
                break
            scaled = arr / largest
            pair.append(scaled / float(np.sqrt((scaled * scaled).sum())))
        if pair is None:
            left_out.append(keys[i])
        else:
            kept.append(i)
            rows_s.append(pair[0])
            rows_m.append(pair[1])
    if len({len(r) for r in rows_s} | {len(r) for r in rows_m}) > 1:
        raise KbError("the vectors are not all of one length")
    return kept, order, left_out, rows_s, rows_m



def _closeness_of_rows(np, A, rows):
    """The closeness, in billionths, of each theme of `rows` (indexes) to every theme."""
    return np.clip(np.rint((A[rows] @ A.T) * SCALE), -SCALE, SCALE).astype(np.int64)


def _candidates(np, S, M, book, sources, edges, floor, top, block):
    """The pairs that the themes `sources` (indexes, in order) put forward: each puts forward its `top` closest partners in each band, of other books and, if `floor` is
    not `None`, above it, the closest first and a tie to the lower index. Returns `(a, b, closeness, wording, band)` as arrays, a pair once, a before b."""
    found = ([], [], [], [], [])
    n = len(book)
    sources = np.asarray(sources, dtype=np.int64)
    for start in range(0, len(sources), block):
        rows = sources[start:start + block]
        cm, cs = _closeness_of_rows(np, M, rows), _closeness_of_rows(np, S, rows)
        band = np.digitize(cs, edges)
        for r, i in enumerate(rows.tolist()):
            row_cm = cm[r]
            allowed = book != book[i]
            if floor is not None:
                allowed = allowed & (row_cm > floor)
            for b in range(BANDS):
                idx = np.nonzero(allowed & (band[r] == b))[0]
                if not len(idx):
                    continue
                idx = idx[np.lexsort((idx, -row_cm[idx]))[:top]]
                found[0].append(np.minimum(idx, i))
                found[1].append(np.maximum(idx, i))
                found[2].append(row_cm[idx])
                found[3].append(cs[r][idx])
                found[4].append(np.full(len(idx), b, dtype=np.int64))
    if not found[0]:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, empty, empty, empty
    a, b = np.concatenate(found[0]), np.concatenate(found[1])
    m, s, bd = np.concatenate(found[2]), np.concatenate(found[3]), np.concatenate(found[4])
    _, first = np.unique(a * n + b, return_index=True)      # a pair put forward from both ends is one
    return a[first], b[first], m[first], s[first], bd[first]


def select(keys, books, summaries, methods, slots=SLOTS, top=TOP, block=BLOCK, use_floor=True):
    """The links of the weave of "same mechanism" for the themes `keys` (each theme has a key that can be put in an order, a book, a summary vector and a method vector; a
    theme with a missing, zero or not finite vector is left out and named). Returns `{"links", "edges", "median", "pairs", "left_out", "slots", "top"}`: `links` is a list of
    `(key_a, key_b, closeness, wording, band)`, key_a before key_b, strongest first and then by the keys, the closeness of the method vectors and the wording distance (the
    closeness of the summary vectors) in billionths, `edges` the three edges of the bands and `median` the floor (both `None` when no two themes of different books are left),
    `pairs` the number of pairs of themes of different books. With `use_floor` false the floor is not applied, for the comparison of what it removes."""
    slots, top, block = _whole(slots, "the number of slots"), _whole(top, "the number of candidates"), _whole(block, "the size of a block")
    np = _np()
    kept, order, left_out, rows_s, rows_m = _prepare(np, keys, books, summaries, methods)
    n = len(kept)
    result = {"links": [], "edges": None, "median": None, "pairs": 0, "left_out": left_out, "slots": slots, "top": top}
    if n < 2:
        return result
    K = [keys[i] for i in kept]
    ids = {}
    try:
        book = np.array([ids.setdefault(books[i], len(ids)) for i in kept], dtype=np.int64)
    except TypeError:
        raise KbError("the books of the themes must be values that can be compared for equality, such as text") from None
    S, M = np.stack(rows_s), np.stack(rows_m)
    per_book = np.bincount(book)
    result["pairs"] = pairs = (n * n - int((per_book * per_book).sum())) // 2
    if pairs == 0:
        return result
    cols = np.arange(n)

    def closeness(A, start, stop):
        return np.clip(np.rint((A[start:stop] @ A.T) * SCALE), -SCALE, SCALE).astype(np.int64)

    def pair_values(A):
        def passes():
            for start in range(0, n, block):
                stop = min(start + block, n)
                eligible = (cols[None, :] > np.arange(start, stop)[:, None]) & (book[start:stop, None] != book[None, :])
                yield closeness(A, start, stop)[eligible]
        return passes

    edges = exact_quantiles(pair_values(S), (0.25, 0.5, 0.75))
    median = exact_quantiles(pair_values(M), (0.5,))[0]
    result["edges"], result["median"] = edges, median
    floor = median if use_floor else None
    a, b, m, s, bd = _candidates(np, S, M, book, np.arange(n), edges, floor, top, block)
    if not len(a):
        return result
    strongest = np.lexsort((b, a, -m))
    count = [[0] * BANDS for _ in range(n)]
    taken = set()
    links = []
    for x, y, closer, wording, where in zip(a[strongest].tolist(), b[strongest].tolist(), m[strongest].tolist(), s[strongest].tolist(), bd[strongest].tolist()):
        bx, by = int(book[x]), int(book[y])
        if count[x][where] >= slots or count[y][where] >= slots or (x, where, by) in taken or (y, where, bx) in taken:
            continue
        count[x][where] += 1
        count[y][where] += 1
        taken.add((x, where, by))
        taken.add((y, where, bx))
        links.append((K[x], K[y], closer, wording, where))
    result["links"] = links
    return result



def repair_links(keys, books, summaries, methods, old_links, edges, median, removed, added, slots=SLOTS, top=TOP, block=BLOCK):
    """The links of a weave repaired for themes that were added, changed or taken out, from the links it had and with its band edges and its median kept. `keys` (with their
    books and vectors, as for `select`) are the themes now; `removed` are keys whose links are dropped (themes that changed, which are also in `added`, and themes that are gone,
    which are not in `keys`), and `added` are keys that are linked anew (new themes, and changed themes). The rule: the links of themes in `removed`, or no longer in `keys`, are
    dropped. The themes in `added` put forward their closest partners in each band (above the median), and these candidates are taken strongest first: a link takes a free slot
    at each end, or replaces the weakest link of a slot that is full if that is weaker than the candidate (of the weakest, the one to the greater key); where an end already has a
    link to a theme of the candidate's book in the band, that link is replaced if it is weaker and the candidate is refused if it is not; a candidate that either end cannot admit
    changes nothing. Then each theme that lost a link puts forward its candidates again, and these are taken strongest first into free slots only. Returns `{"links", "dropped",
    "added", "touched"}`: the links in the form `select` gives them, the number of old links that are not there any more, the number of links there that were not, and the number
    of themes that lost a link and were offered new ones."""
    slots, top, block = _whole(slots, "the number of slots"), _whole(top, "the number of candidates"), _whole(block, "the size of a block")
    np = _np()
    if edges is None or median is None:
        raise KbError("the weave has no edges or median to repair with: it needs a full build")
    kept, order, left_out, rows_s, rows_m = _prepare(np, keys, books, summaries, methods)
    removed, added = set(removed), set(added)
    K = [keys[i] for i in kept]
    index = {k: i for i, k in enumerate(K)}
    try:
        ids = {}
        book = np.array([ids.setdefault(books[i], len(ids)) for i in kept], dtype=np.int64)
    except TypeError:
        raise KbError("the books of the themes must be values that can be compared for equality, such as text") from None
    old_pairs = {(a, b) for a, b, *_ in old_links}
    links, slot, touched = {}, {}, set()

    def put(a, b, m, w, band):
        links[(a, b)] = (m, w, band)
        slot.setdefault((a, band), {})[b] = m
        slot.setdefault((b, band), {})[a] = m

    def drop(x, o, band):
        del links[(min(x, o), max(x, o))]
        del slot[(x, band)][o]
        del slot[(o, band)][x]
        touched.update(y for y in (x, o))

    for a, b, m, w, band in old_links:
        if a in removed or b in removed or a not in index or b not in index:
            touched.update(index[x] for x in (a, b) if x in index and x not in removed)
        else:
            put(index[a], index[b], m, w, band)
    n = len(K)
    if n >= 2:
        S, M = np.stack(rows_s), np.stack(rows_m)
        news = sorted(index[k] for k in added if k in index)
        if news:
            a, b, m, s_, bd = _candidates(np, S, M, book, news, edges, median, top, block)
            for x, y, closer, wording, where in zip(*(v[np.lexsort((b, a, -m))].tolist() for v in (a, b, m, s_, bd))):
                if (x, y) in links:
                    continue
                drops, refused = [], False
                for end, other in ((x, y), (y, x)):
                    there = slot.get((end, where), {})
                    same = [(o, mm) for o, mm in there.items() if book[o] == book[other]]
                    if same:
                        o, mm = same[0]
                        if mm >= closer:
                            refused = True
                        else:
                            drops.append((end, o))
                    elif len(there) >= slots:
                        lowest = min(there.values())
                        o = max(o2 for o2, mm in there.items() if mm == lowest)
                        if lowest >= closer:
                            refused = True
                        else:
                            drops.append((end, o))
                if refused:
                    continue
                for end, o in drops:
                    drop(end, o, where)
                put(x, y, closer, wording, where)
        again = sorted(touched)
        if again:
            a, b, m, s_, bd = _candidates(np, S, M, book, again, edges, median, top, block)
            for x, y, closer, wording, where in zip(*(v[np.lexsort((b, a, -m))].tolist() for v in (a, b, m, s_, bd))):
                if (x, y) in links:
                    continue
                if (len(slot.get((x, where), {})) >= slots or len(slot.get((y, where), {})) >= slots
                        or any(book[o] == book[y] for o in slot.get((x, where), {})) or any(book[o] == book[x] for o in slot.get((y, where), {}))):
                    continue
                put(x, y, closer, wording, where)
    out = sorted(((K[a], K[b], m, w, band) for (a, b), (m, w, band) in links.items()), key=lambda link: (-link[2], link[0], link[1]))
    now = {(a, b) for a, b, *_ in out}
    return {"links": out, "dropped": len(old_pairs - now), "added": len(now - old_pairs), "touched": len(touched)}

# --- the file of the weave

_AGAIN = f"run `{COMMAND}` to build it again"
_META_KEYS = ("format", "kind", "generation", "vectors_model", "vectors_configured", "vectors_dimension", "vectors_built", "vectors_document_prefix_sha256",
              "edges", "median", "pairs", "slots", "top", "bands", "built", "numpy")
_THEME_COLUMNS = ["book_id", "version_id", "theme_id", "theme_generation", "method_sha256", "summary_sha256", "links"]
_LINK_COLUMNS = ["a_book", "a_version", "a_theme", "b_book", "b_version", "b_theme", "closeness", "wording", "band"]
_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE themes (book_id TEXT NOT NULL, version_id TEXT NOT NULL, theme_id TEXT NOT NULL, theme_generation INTEGER NOT NULL, "
    "method_sha256 TEXT NOT NULL, summary_sha256 TEXT NOT NULL, links INTEGER NOT NULL, PRIMARY KEY (book_id, version_id, theme_id))",
    "CREATE TABLE links (a_book TEXT NOT NULL, a_version TEXT NOT NULL, a_theme TEXT NOT NULL, b_book TEXT NOT NULL, b_version TEXT NOT NULL, "
    "b_theme TEXT NOT NULL, closeness INTEGER NOT NULL, wording INTEGER NOT NULL, band INTEGER NOT NULL, "
    "PRIMARY KEY (a_book, a_version, a_theme, b_book, b_version, b_theme))",
)
_COUNT = re.compile(r"[0-9]{1,15}")   # the number of pairs of themes of different books: about the square of the number of themes
_NUMPY_VERSION = re.compile(r"[0-9][0-9A-Za-z.+_-]{0,31}")


def path_of(index_root):
    return os.path.join(index_root, INDEX_FILE)


def _bad(what):
    return KbError(f"the file of the weave {what}: {_AGAIN}")


@contextmanager
def lock(index_root):
    """Hold the writers' lock on the weave. Waits up to the catalog's wait for another writer, then refuses. A lock file that is a link is not followed."""
    path = os.path.join(index_root, LOCK_FILE)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise KbError(f"the lock of the weave cannot be opened ({e.strerror})") from None
    try:
        deadline = time.monotonic() + catalog.LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise KbError("the weave is being written by another process; try again when it has finished") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing it lets go of the lock


def _clean_leftovers(index_root):
    """Remove what an earlier build that was killed left, under the lock: a folder, a file or a link whose name begins with BUILD_PREFIX. A link is removed as a
    link and its target is never entered; nothing else in the index root is touched."""
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


def _connect(path, create=False, readonly=False):
    """The file at `path`, checked: a database of this engine's shape that holds nothing else, and not a link. `readonly` opens it so that nothing can be written."""
    if not create and (not os.path.lexists(path) or os.path.islink(path) or not os.path.isfile(path)):
        raise KbError(f"there is no file of the weave yet: run `{COMMAND}` to build one")
    try:
        target = Path(path).as_uri() + "?mode=ro" if readonly else path
    except (ValueError, UnicodeError):
        raise KbError("the path of the file of the weave cannot be opened as a file") from None
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
        raise KbError(f"the file of the weave cannot be opened ({e}): {_AGAIN}") from None


def _check_shape(conn):
    if conn.execute("PRAGMA user_version").fetchone()[0] != FORMAT:
        raise _bad("is not in the shape this version of the engine writes")
    objects = conn.execute("SELECT type, name FROM sqlite_master").fetchall()
    if any(kind in ("trigger", "view") for kind, _ in objects):
        raise _bad("holds a trigger or a view this engine did not put there")
    if {name for kind, name in objects if kind == "table"} != {"meta", "themes", "links"}:
        raise _bad("has tables that are not the ones this version of the engine writes")
    for table, columns in (("themes", _THEME_COLUMNS), ("links", _LINK_COLUMNS), ("meta", ["key", "value"])):
        if [r[1] for r in conn.execute(f"PRAGMA table_info({table})")] != columns:
            raise _bad("has tables that are not the ones this version of the engine writes")


def _no_constant(name):
    raise ValueError(name)


def _json_numbers(text, how_many):
    """`how_many` finite numbers in billionths in order, or `None` if the text is `null`; any other form is a refusal."""
    if text == "null":
        return None
    try:
        value = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise _bad("holds a number that is not a number") from None
    values = value if isinstance(value, list) else [value]
    if (not isinstance(value, (list, int, float)) or isinstance(value, bool) or len(values) != how_many
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and -SCALE <= x <= SCALE for x in values) or values != sorted(values)):
        raise _bad("holds edges or a median that are not what the build writes")
    return values if isinstance(value, list) else values[0]


def _read_meta(conn):
    try:
        rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as e:
        raise KbError(f"the file of the weave cannot be read ({e}): {_AGAIN}") from None
    if set(rows) != set(_META_KEYS) or not all(isinstance(v, str) for v in rows.values()):
        raise _bad("does not say what it was made from")
    hexset = themevectors._HEX
    if (rows["format"] != str(FORMAT) or rows["kind"] != KIND or not re.fullmatch(r"[1-9][0-9]{0,8}", rows["generation"])
            or not models._valid_model(rows["vectors_model"]) or not models._valid_model(rows["vectors_configured"])
            or not themevectors._DIMENSION.fullmatch(rows["vectors_dimension"]) or not 1 <= int(rows["vectors_dimension"]) <= models.MAX_DIMENSION
            or not themevectors._BUILT.fullmatch(rows["vectors_built"]) or not themevectors._BUILT.fullmatch(rows["built"])
            or len(rows["vectors_document_prefix_sha256"]) != 64 or set(rows["vectors_document_prefix_sha256"]) - hexset
            or not _COUNT.fullmatch(rows["pairs"]) or not re.fullmatch(r"[1-9][0-9]{0,2}", rows["slots"]) or not re.fullmatch(r"[1-9][0-9]{0,6}", rows["top"])
            or rows["bands"] != str(BANDS) or not _NUMPY_VERSION.fullmatch(rows["numpy"])):
        raise _bad("does not say what it was made from")
    edges, median = _json_numbers(rows["edges"], 3), _json_numbers(rows["median"], 1)
    if (edges is None) != (median is None):
        raise _bad("holds edges without a median or a median without edges")
    return {"format": FORMAT, "kind": KIND, "generation": int(rows["generation"]), "vectors_model": rows["vectors_model"],
            "vectors_configured": rows["vectors_configured"], "vectors_dimension": int(rows["vectors_dimension"]), "vectors_built": rows["vectors_built"],
            "vectors_document_prefix_sha256": rows["vectors_document_prefix_sha256"], "edges": edges, "median": median, "pairs": int(rows["pairs"]),
            "slots": int(rows["slots"]), "top": int(rows["top"]), "bands": BANDS, "built": rows["built"], "numpy": rows["numpy"]}


def _key(book, version, theme_id):
    if (not isinstance(book, str) or not ids._ID.fullmatch(book) or not isinstance(version, str) or not themevectors._VERSION.fullmatch(version)
            or not isinstance(theme_id, str) or not themevectors._THEME_ID.fullmatch(theme_id)):
        raise _bad("holds a row that is not what this engine writes")
    return book, version, theme_id


def _whole_number(value, least, most):
    if type(value) is not int or not least <= value <= most:
        raise _bad("holds a row that is not what this engine writes")
    return value


def check_rows(meta, themes, links):
    """Refuse rows that are not what a build writes: `themes` as `[{"key", "links", ...}]`, `links` as `[(key_a, key_b, closeness, wording, band)]`. Every link joins
    two themes of the file, of different books, in the order of their keys, once; its closeness is above the median and its band is the one its wording and the edges
    give; no theme has more links in a band than the slots, or two to one book in a band; and the number of links of a theme is the number it has. (`meta` needs
    `slots`, `median`, `edges` and `bands`.) The slots are those the file records: a build is given the number of slots, 3 by default, and a file says which it used."""
    have = {}
    for t in themes:
        if t["key"] in have:
            raise _bad("holds a theme twice")
        have[t["key"]] = t["links"]
    count, taken, degree = {}, set(), {}
    seen = set()
    if links and (meta["median"] is None or meta["edges"] is None):
        raise _bad("holds links but no edges or median")
    for a, b, closeness, wording, band in links:
        if a not in have or b not in have or not a < b or a[0] == b[0] or (a, b) in seen:
            raise _bad("holds a link that is not between two different themes of different books, in order, once")
        seen.add((a, b))
        _whole_number(closeness, -SCALE, SCALE)
        _whole_number(wording, -SCALE, SCALE)
        if closeness <= meta["median"] or band != sum(1 for e in meta["edges"] if wording >= e) or type(band) is not int:
            raise _bad("holds a link that is not above the floor or is in the wrong band")
        for x, y in ((a, b), (b, a)):
            degree[x] = degree.get(x, 0) + 1
            count[(x, band)] = count.get((x, band), 0) + 1
            if count[(x, band)] > meta["slots"] or (x, band, y[0]) in taken:
                raise _bad("holds more links of a theme in a band than the slots allow, or two to one book")
            taken.add((x, band, y[0]))
    for key, n in have.items():
        if n != degree.get(key, 0):
            raise _bad("holds a theme whose number of links is not the number it has")


def read(path):
    """The file of the weave at `path`, every row checked as the build writes it. Returns `{"meta", "themes", "links"}`: `themes` as `[{"key": (book, version, theme),
    "theme_generation", "method_sha256", "summary_sha256", "links"}]` by key, `links` as `[(key_a, key_b, closeness, wording, band)]`, strongest first. A file that is
    missing, is a link, or is not what a build writes is a refusal that names the command to run."""
    with closing(_connect(path, readonly=True)) as conn:
        meta = _read_meta(conn)
        try:
            theme_rows = conn.execute("SELECT book_id, version_id, theme_id, theme_generation, method_sha256, summary_sha256, links FROM themes "
                                      "ORDER BY book_id, version_id, theme_id").fetchall()
            link_rows = conn.execute("SELECT a_book, a_version, a_theme, b_book, b_version, b_theme, closeness, wording, band FROM links").fetchall()
        except sqlite3.Error as e:
            raise KbError(f"the file of the weave cannot be read ({e}): {_AGAIN}") from None
    hexset = themevectors._HEX
    themes = []
    for book, version, theme_id, generation, method_sha, summary_sha, n in theme_rows:
        if (not isinstance(method_sha, str) or len(method_sha) != 64 or set(method_sha) - hexset or not isinstance(summary_sha, str) or len(summary_sha) != 64
                or set(summary_sha) - hexset):
            raise _bad("holds a row that is not what this engine writes")
        themes.append({"key": _key(book, version, theme_id), "theme_generation": _whole_number(generation, 1, 10 ** 9), "method_sha256": method_sha,
                       "summary_sha256": summary_sha, "links": _whole_number(n, 0, 10 ** 6)})
    links = [(_key(*row[0:3]), _key(*row[3:6]), row[6], row[7], row[8]) for row in link_rows]
    check_rows(meta, themes, links)
    links.sort(key=lambda link: (-link[2], link[0], link[1]))
    return {"meta": meta, "themes": themes, "links": links}


# --- the build

def _existing(final, previous):
    """`(generation to go on from, whether a file is in the way at `final` that is not a weave, whether the file at `final` is a weave)`. When the file in place is a weave
    its generation is the one to go on from. When it is missing or is not one, the generation goes on from the generation before if that is a weave, so that the numbers do
    not start again under a file that holds a higher one."""
    here = None
    if os.path.lexists(final):
        try:
            here = read(final)["meta"]["generation"]
        except KbError:
            here = None
    if here is not None:
        return here, False, True
    before = 0
    if os.path.lexists(previous):
        try:
            before = read(previous)["meta"]["generation"]
        except KbError:
            before = 0
    return before, os.path.lexists(final), False


def _keep_previous(final, held, previous):
    """Keep the weave in place as the generation before, as it is: a second name for the same file (or, where a link cannot be made, a copy), put in place before the new
    file is. The file must be a regular file of this user's own, which is not followed if it has become a link."""
    info = os.lstat(final)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise KbError("the weave in place is not a file of this user's own; nothing was changed")
    try:
        os.link(final, held, follow_symlinks=False)
    except (OSError, NotImplementedError):
        shutil.copyfile(final, held)
        os.chmod(held, 0o600)
    os.replace(held, previous)


@contextmanager
def _vectors_file(index_root, cfg):
    """The file of the theme vectors open read-only and checked as the search checks it: yields `(conn, entry, vmeta, by_theme)`, with `by_theme` as `{key: row}` for the
    themes of the file. A file for another model, dimension or document prefix than the config sets, a missing one and one that is not the engine's is a refusal."""
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    with closing(themevectors.connect(themevectors.path_of(index_root), readonly=True)) as conn:
        vmeta = themevectors.check_entry(conn, entry)
        rows = themevectors.read_themes(conn)
        themevectors.check_vector_rows(conn)
        yield conn, entry, vmeta, {(r["book_id"], r["version_id"], r["theme_id"]): r for r in rows}


def _usable_vectors(np, conn, entry, by_theme):
    """`{(key, field): vector}` for the summary and the method vector of each theme whose text is the text the theme still has and whose vector is of the right length."""
    wanted = {}
    for v in themevectors.iter_vectors(conn, entry["dimension"], lenient=True, ordered=False):
        if v["field"] not in ("summary", "method") or v["vector"] is None:
            continue
        key = (v["book_id"], v["version_id"], v["theme_id"])
        row = by_theme.get(key)
        if row is not None and row["hashes"].get(v["field"]) == v["text_sha256"]:   # a vector counts only if its text is the text the theme still has
            wanted[(key, v["field"])] = np.array(v["vector"], dtype=np.float32)
    return wanted


def _publish(index_root, meta, theme_rows, link_rows, expect_generation=None):
    """Write the weave from its rows and put it in place under the lock, keeping the generation before as it was. The file is made in a folder of its own and renamed; it is never
    written in place, which would change the generation before (a second name for the same file). With `expect_generation`, a weave in place of another generation than that is a
    refusal that writes nothing. Returns `(generation, replaced)`."""
    final, previous = path_of(index_root), os.path.join(index_root, PREVIOUS_FILE)
    with lock(index_root):
        folder = None
        try:
            _clean_leftovers(index_root)
            old_generation, replaced, in_place = _existing(final, previous)
            if expect_generation is not None and (not in_place or old_generation != expect_generation):
                raise KbError("the weave in place changed while the repair was worked out, so nothing was written; run it again")
            meta = {**meta, "generation": str(old_generation + 1)}
            # the file is built in a folder of its own, private to the owner and with a name no one can know before it is made, and renamed into place
            folder = tempfile.mkdtemp(prefix=BUILD_PREFIX, dir=index_root)
            identity = vectors._identity(folder)
            fresh = os.path.join(folder, INDEX_FILE)
            _connect(fresh, create=True).close()
            os.chmod(fresh, 0o600)  # the links are about the owner's books
            with closing(_connect(fresh)) as conn:
                conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items()))
                conn.executemany("INSERT INTO themes (book_id, version_id, theme_id, theme_generation, method_sha256, summary_sha256, links) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?)", theme_rows)
                conn.executemany("INSERT INTO links (a_book, a_version, a_theme, b_book, b_version, b_theme, closeness, wording, band) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", link_rows)
                conn.commit()
            read(fresh)    # what is about to be put in place is a file that can be read back
            if vectors._identity(folder) != identity:
                raise KbError("the folder in which the weave was built is not the one that was made; nothing was put in place")
            for stale in (final + "-journal", final + "-wal", final + "-shm"):
                vectors._remove(stale, "a file of the old weave")
            if in_place:        # the generation before is kept as it was, put in place before the new one
                _keep_previous(final, os.path.join(folder, "previous"), previous)
            os.replace(fresh, final)
        except sqlite3.Error as e:
            raise KbError(f"the file of the weave could not be written ({e})") from None
        except OSError as e:
            raise KbError(f"the file of the weave could not be written ({e.strerror or 'error'})") from None
        finally:
            if folder is not None:  # whatever went wrong, the old file is as it was and no folder of the build is left
                shutil.rmtree(folder, ignore_errors=True)
    return old_generation + 1, replaced


def build(index_root, cfg, slots=SLOTS, top=TOP, block=BLOCK):
    """Build the weave of "same mechanism" from the file of the theme vectors and put it in place of the old one, keeping the generation before. Reads the file of the
    vectors read-only and nothing else, sends nothing to any model, and refuses (before it writes anything) a file for another model, dimension or document prefix than
    the config sets, or one that is missing or not the engine's (it needs the model work of the config to be on, to find the embedding entry, though nothing is sent). Returns the counts: the themes of the vectors file (`themes_in_vectors_file`), those the build processed
    (`themes_processed`, of which `themes_with_links` and `themes_with_no_link`), those left out (`left_out` and its `left_out_reasons`), the `links`, the `links_without_floor`
    (what the slot rule makes without the floor, from a second selection) of which `links_at_or_under_the_floor` are no closer than the median, the processed themes with no link in the farthest band (`no_link_in_farthest_band`), the `edges`, the `median` and the number of
    `pairs`, the `generation` and whether a file that was not a weave was `replaced`."""
    np = _np()
    with _vectors_file(index_root, cfg) as (conn, entry, vmeta, by_theme):
        wanted = _usable_vectors(np, conn, entry, by_theme)
    keys = sorted(by_theme)
    reasons = {"no_text": 0, "no_usable_vector": 0}
    for key in keys:
        if "summary" not in by_theme[key]["hashes"] or "method" not in by_theme[key]["hashes"]:
            reasons["no_text"] += 1
        elif (key, "summary") not in wanted or (key, "method") not in wanted:
            reasons["no_usable_vector"] += 1
    summaries = [wanted.get((k, "summary")) for k in keys]
    methods = [wanted.get((k, "method")) for k in keys]
    chosen = select(keys, [k[0] for k in keys], summaries, methods, slots=slots, top=top, block=block)
    without = select(keys, [k[0] for k in keys], summaries, methods, slots=slots, top=top, block=block, use_floor=False)
    left_out = set(chosen["left_out"])
    processed = [k for k in keys if k not in left_out]
    degree, farthest = {}, set()
    for a, b, closeness, wording, band in chosen["links"]:
        for x in (a, b):
            degree[x] = degree.get(x, 0) + 1
            if band == 0:
                farthest.add(x)
    meta = {"format": str(FORMAT), "kind": KIND, "vectors_model": vmeta["model"], "vectors_configured": vmeta["configured"],
            "vectors_dimension": vmeta["dimension"], "vectors_built": vmeta["built"], "vectors_document_prefix_sha256": vmeta["document_prefix_sha256"],
            "edges": json.dumps(chosen["edges"]), "median": json.dumps(chosen["median"]), "pairs": str(chosen["pairs"]), "slots": str(slots), "top": str(top),
            "bands": str(BANDS), "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "numpy": np.__version__}
    theme_rows = [(k[0], k[1], k[2], by_theme[k]["theme_generation"], by_theme[k]["hashes"]["method"], by_theme[k]["hashes"]["summary"], degree.get(k, 0))
                  for k in processed]
    link_rows = [(*a, *b, closeness, wording, band) for a, b, closeness, wording, band in chosen["links"]]
    generation, replaced = _publish(index_root, meta, theme_rows, link_rows)
    return {"themes_in_vectors_file": len(keys), "themes_processed": len(processed), "themes_with_links": len(degree),
            "themes_with_no_link": len(processed) - len(degree), "left_out": len(left_out), "left_out_reasons": reasons, "links": len(chosen["links"]),
            "links_without_floor": len(without["links"]), "links_at_or_under_the_floor": sum(1 for link in without["links"] if link[2] <= without["median"]),
            "no_link_in_farthest_band": len(processed) - len(farthest), "edges": chosen["edges"], "median": chosen["median"], "pairs": chosen["pairs"],
            "generation": generation, "replaced": replaced}


# --- what is waiting, and the repair

REPAIR_SHARE = Fraction(1, 20)   # a repair is due when the themes waiting reach this share of the themes in the weave, and a full build is needed when more than this share changed
REPAIR_DAYS = 30                 # or when the oldest waiting book was added this many days ago


def _same_theme(row, recorded):
    """Whether the theme of the vectors file is the one the weave recorded: its generation and the hashes of the two texts."""
    return ((row["theme_generation"], row["hashes"].get("method"), row["hashes"].get("summary"))
            == (recorded["theme_generation"], recorded["method_sha256"], recorded["summary_sha256"]))


def _age_in_days(store, books, now):
    """The age in days of the oldest of the books (when it was added, from the store, read only), or `None` if no age can be had."""
    oldest = None
    for book in sorted(books):
        try:
            added = store.read_book(book).get("added")
        except KbError:
            continue
        if not isinstance(added, str) or not themevectors._BUILT.fullmatch(added):
            continue
        try:
            age = (now - datetime.fromisoformat(added)).total_seconds() / 86400
        except (ValueError, OverflowError):      # it has the form of a date and is not one (month 13, year 0)
            continue
        oldest = age if oldest is None else max(oldest, age)
    return oldest


def _inspect(index_root, cfg, store, now, np=None):
    """What the weave in place and the file of vectors say about each other: `{"made", "vmeta", "entry", "by_theme", "wanted", "new", "changed", "gone", "left_out", "status"}`.
    `new` are the themes of the vectors file that the weave did not process and that have a summary vector and a method vector that count, `left_out` those it did not process and
    that have not, `changed` those it processed whose generation or text is not what it recorded, `gone` those it processed that are no longer in the file. `wanted` is the
    vectors, only if `np` is given (for a repair). The numbers of the status are worked out from these."""
    now = now if now is not None else datetime.now(timezone.utc)
    with _vectors_file(index_root, cfg) as (conn, entry, vmeta, by_theme):
        made = read(path_of(index_root))
        in_weave = {t["key"]: t for t in made["themes"]}
        wanted = _usable_vectors(np, conn, entry, by_theme) if np is not None else None
        new, left_out = [], []
        for key in sorted(by_theme):
            if key in in_weave:
                continue
            usable = ((key, "summary") in wanted and (key, "method") in wanted) if wanted is not None else _has_usable_vectors(conn, by_theme[key], entry["dimension"])
            (new if usable else left_out).append(key)
    changed = [k for k, t in sorted(in_weave.items()) if k in by_theme and not _same_theme(by_theme[k], t)]
    gone = [k for k in sorted(in_weave) if k not in by_theme]
    wmeta = made["meta"]
    processed = len(in_weave)
    full, why_full = False, []
    if (wmeta["vectors_model"], wmeta["vectors_configured"], wmeta["vectors_dimension"], wmeta["vectors_document_prefix_sha256"]) != (
            vmeta["model"], vmeta["configured"], int(vmeta["dimension"]), vmeta["document_prefix_sha256"]):
        full, why_full = True, why_full + ["the weave was made from vectors of another model, dimension or document prefix than the file of vectors now holds"]
    if wmeta["edges"] is None or wmeta["median"] is None:
        full, why_full = True, why_full + ["the weave has no edges or median to repair with"]
    moved = len(changed) + len(gone)
    if processed and Fraction(moved, processed) > REPAIR_SHARE:
        full, why_full = True, why_full + [f"{moved} of the {processed} themes of the weave changed or are gone, more than {float(REPAIR_SHARE) * 100:g} percent"]
    waiting = len(new) + len(changed)
    age = _age_in_days(store, {k[0] for k in new + changed}, now) if waiting else None
    due, why_due = False, []
    if not full and waiting:
        if not processed or Fraction(waiting, processed) >= REPAIR_SHARE:
            due, why_due = True, why_due + [f"{waiting} themes are waiting, {float(REPAIR_SHARE) * 100:g} percent or more of the {processed} of the weave"]
        if age is not None and age >= REPAIR_DAYS:
            due, why_due = True, why_due + [f"the oldest waiting book was added {age:.1f} days ago, {REPAIR_DAYS} days or more"]
    degree_zero = sum(1 for t in made["themes"] if t["links"] == 0)
    status = {"weave": {"generation": wmeta["generation"], "built": wmeta["built"], "vectors_built": wmeta["vectors_built"]},
              "themes_in_vectors_file": len(by_theme), "themes_in_weave": processed, "themes_with_no_link": degree_zero,
              "waiting": {"new": len(new), "changed": len(changed), "total": waiting}, "left_out": len(left_out), "gone": len(gone),
              "changed_or_gone_share": (moved / processed) if processed else 0.0, "full_build_needed": full, "full_build_because": why_full,
              "repair_due": due, "repair_due_because": why_due, "oldest_waiting_days": age,
              "limits": {"share": float(REPAIR_SHARE), "days": REPAIR_DAYS},
              "next": (f"a full build is needed: run `{COMMAND}`" if full else
                       "a repair is due: run `python3 -m kb theme-links repair`" if due else
                       "nothing is due" if not waiting else "themes are waiting, but a repair is not due yet (`repair --now` goes on)")}
    return {"made": made, "vmeta": vmeta, "entry": entry, "by_theme": by_theme, "wanted": wanted, "new": new, "changed": changed, "gone": gone,
            "left_out": left_out, "status": status}


def status(index_root, cfg, store, now=None):
    """What is waiting to be linked, and whether a repair is due or a full build is needed. Reads the file of the vectors, the weave and (for the age of a book, which it
    asks of `store`: `read_book` only) the library, all read-only; sends nothing to any model and needs no numpy. A theme the weave processed that ended with no link is counted
    apart (`themes_with_no_link`) and never waits; a theme it could not link because it has no usable summary or method vector is counted apart too (`left_out`) and never waits.
    The themes that wait are the new ones and those whose generation or text changed (a changed book is removed and added again); the themes that are gone are counted and
    alone make nothing due. A repair is due when the waiting themes are 5 percent or more of the themes of the weave, or the oldest waiting book was added 30 days ago or more;
    a full build is needed instead when more than 5 percent of the themes of the weave changed or are gone, or the vectors are of another model, dimension or prefix."""
    return _inspect(index_root, cfg, store, now)["status"]


def repair(index_root, cfg, store, now=None, force=False):
    """Add the themes that wait to the weave in place (`repair_links`: new themes and changed ones are linked, the links of changed and gone themes are dropped, the band edges
    and the median and the slots are the weave's own) and put the result in place as the next generation, keeping the generation before as it was. The new file is written and
    renamed and the old one is never written in place. Refused, with nothing written: when a full build is needed (even if `force`), when nothing is waiting and nothing is
    gone, when no repair is due unless `force`, and when the weave in place changed while the repair was worked out. Needs numpy. Returns the counts."""
    np = _np()
    info = _inspect(index_root, cfg, store, now, np=np)
    state = info["status"]
    if state["full_build_needed"]:
        raise KbError("a full build is needed, not a repair (" + "; ".join(state["full_build_because"]) + f"): run `{COMMAND}`")
    if not state["waiting"]["total"] and not state["gone"]:
        raise KbError("nothing is waiting to be linked and no theme is gone, so there is nothing to repair")
    if not state["repair_due"] and not force:
        raise KbError("no repair is due (" + state["next"] + "); `python3 -m kb theme-links repair --now` goes on")
    made, by_theme, wanted = info["made"], info["by_theme"], info["wanted"]
    meta = made["meta"]
    keys = [k for k in sorted(by_theme) if (k, "summary") in wanted and (k, "method") in wanted]
    unusable_changed = [k for k in info["changed"] if k not in set(keys)]
    old_keys = {t["key"] for t in made["themes"]}
    lost_vectors = [k for k in sorted(old_keys) if k in by_theme and k not in set(keys) and k not in set(info["changed"])]   # unchanged, but no summary or method vector counts now
    removed = set(info["changed"]) | set(info["gone"])      # a theme that lost its vectors is not in `keys`, so its links are dropped with the others
    added = set(info["new"]) | {k for k in info["changed"] if k in set(keys)}
    result = repair_links(keys, [k[0] for k in keys], [wanted[(k, "summary")] for k in keys], [wanted[(k, "method")] for k in keys], made["links"],
                          meta["edges"], meta["median"], removed, added, slots=meta["slots"], top=meta["top"])
    degree = {}
    for a, b, *_ in result["links"]:
        for x in (a, b):
            degree[x] = degree.get(x, 0) + 1
    per_book = {}
    for k in keys:
        per_book[k[0]] = per_book.get(k[0], 0) + 1
    vmeta = info["vmeta"]
    new_meta = {"format": str(FORMAT), "kind": KIND, "vectors_model": vmeta["model"], "vectors_configured": vmeta["configured"], "vectors_dimension": vmeta["dimension"],
                "vectors_built": vmeta["built"], "vectors_document_prefix_sha256": vmeta["document_prefix_sha256"], "edges": json.dumps(meta["edges"]),
                "median": json.dumps(meta["median"]), "pairs": str((len(keys) ** 2 - sum(c * c for c in per_book.values())) // 2), "slots": str(meta["slots"]),
                "top": str(meta["top"]), "bands": str(BANDS), "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "numpy": np.__version__}
    theme_rows = [(k[0], k[1], k[2], by_theme[k]["theme_generation"], by_theme[k]["hashes"]["method"], by_theme[k]["hashes"]["summary"], degree.get(k, 0)) for k in keys]
    link_rows = [(*a, *b, closeness, wording, band) for a, b, closeness, wording, band in result["links"]]
    generation, _ = _publish(index_root, new_meta, theme_rows, link_rows, expect_generation=meta["generation"])
    return {"generation": generation, "themes_in_weave": len(keys), "themes_added": len(info["new"]), "themes_changed": len(info["changed"]),
            "themes_gone": len(info["gone"]), "themes_left_out_now": len(info["left_out"]) + len(unusable_changed), "themes_lost_vectors": len(lost_vectors), "links_before": len(made["links"]),
            "links": len(result["links"]), "links_dropped": result["dropped"], "links_added": result["added"], "themes_that_lost_a_link": result["touched"],
            "repair_due_because": state["repair_due_because"] or ["told to go on"]}


# --- looking at the links of a theme

BAND_NAMES = ("wording-farthest", "second", "third", "wording-nearest")
ABOUT = ("closeness is how close the method texts of the two themes are (1 is the same direction); wording_closeness is how close their summaries, the book's own words, "
         "are (so a low number means far apart in wording), and a link with a high closeness and a low wording_closeness is a theme that works the same way and is said in other words. A link is a lead, not a finding; the numbers "
         "say how the pair was found and are not a judgement of whether it is useful.")


def _theme_result(row, score):
    """A theme as the search shows it (`themevectors.result_of`: every text of the file cleaned, the marked fields between the untrusted-text markers), with the method text
    as the matched text, or the summary if the theme has no method text any more."""
    texts = themevectors.texts_of(row["theme"])
    for field in ("method", "summary"):
        if field in texts:
            return themevectors.result_of(row, score, field)
    return {"book_id": row["book_id"], "version_id": row["version_id"], "theme_id": row["theme_id"], "missing": True, "reason": "the theme has no method or summary text"}


def _has_usable_vectors(conn, row, dimension):
    """Whether the file of theme vectors holds, for this theme, a summary vector and a method vector that count: of the text the theme still has, and of the right length."""
    have = set()
    try:
        for field, sha, blob in conn.execute("SELECT field, text_sha256, vector FROM vectors WHERE book_id = ? AND version_id = ? AND theme_id = ? "
                                             "AND field IN ('summary', 'method')", (row["book_id"], row["version_id"], row["theme_id"])):
            if row["hashes"].get(field) == sha:
                try:
                    themevectors.unpack(blob, dimension)
                    have.add(field)
                except KbError:
                    pass
    except sqlite3.Error as e:
        raise KbError(f"the file of theme vectors cannot be read ({e})") from None
    return have == {"summary", "method"}


def show(index_root, cfg, book_id, theme_id, version_id=None):
    """The links of one theme in the weave, by band, each with the other theme as the search shows a theme and what the link is (its kind, the method closeness, the wording
    closeness and the texts that were matched). Reads the file of the theme vectors and the weave read-only, sends nothing to any model and needs no numpy. A theme that is not
    in the weave, or not in the file of vectors, is a refusal that says which: no such theme (the ids are those `theme-search` prints), one that came after the weave (not yet
    linked: build again), one the build left out because it has no usable summary or method vector (a build cannot help: the vectors must be made), or one that is no longer in
    the file of vectors. A weave made from an older build of the vectors is shown, with a `warning` first in what is printed and `weave.current` false. The numbers of the weave
    are not worked out again from the vectors here. The theme is named by its book and its id (and its version if the file holds more than one)."""
    if (not isinstance(book_id, str) or not ids._ID.fullmatch(book_id) or not isinstance(theme_id, str) or not themevectors._THEME_ID.fullmatch(theme_id)
            or (version_id is not None and (not isinstance(version_id, str) or not themevectors._VERSION.fullmatch(version_id)))):
        raise KbError("a theme is named by the id of its book and its own id (and its version, if the book has more than one): these are not ids")
    name, _ = models.choose(cfg, "card-embed")
    entry = models.registry(cfg)[name]
    with closing(themevectors.connect(themevectors.path_of(index_root), readonly=True)) as conn:
        vmeta = themevectors.check_entry(conn, entry)
        rows = themevectors.read_themes(conn)
        themevectors.check_vector_rows(conn)
        made = read(path_of(index_root))
        by_key = {(r["book_id"], r["version_id"], r["theme_id"]): r for r in rows}
        in_weave = {t["key"]: t for t in made["themes"]}

        def named(keys):
            return [k for k in keys if k[0] == book_id and k[2] == theme_id and (version_id is None or k[1] == version_id)]

        in_file, in_links = named(by_key), named(in_weave)
        if len(in_file) > 1 or (not in_file and len(in_links) > 1):
            raise KbError("the theme is in more than one version of its book: name the version")
        if not in_file and not in_links:
            raise KbError("no such theme in the file of theme vectors or in the weave (the ids are those `python3 -m kb theme-search` prints)")
        key = (in_file or in_links)[0]
        if key not in by_key:
            raise KbError(f"the theme is in the weave but no longer in the file of theme vectors: {_AGAIN}")
        if key not in in_weave:
            if not _has_usable_vectors(conn, by_key[key], entry["dimension"]):
                raise KbError("the theme was left out of the weave: it has no usable summary vector or method vector (its text is missing, or its vector is stale or not "
                              "usable), and building the weave again does not change that; the vectors are made by `python3 -m kb theme-vectors`")
            raise KbError(f"the theme is not yet linked: the weave was made before it was in the file of theme vectors: {_AGAIN}")
    wmeta = made["meta"]
    current = (wmeta["vectors_built"], wmeta["vectors_model"]) == (vmeta["built"], vmeta["model"])
    note = None if current else (f"out of date: the file of theme vectors was built on {vmeta['built']}, after this weave was made from the build of "
                                 f"{wmeta['vectors_built']}; {_AGAIN}")
    centre = _theme_result(by_key[key], None)
    bands = [{"band": b, "name": BAND_NAMES[b], "links": []} for b in range(BANDS)]
    total = 0
    for a, b, closeness, wording, band in made["links"]:
        if key not in (a, b):
            continue
        other = b if a == key else a
        row = by_key.get(other)
        shown = _theme_result(row, closeness / SCALE) if row is not None else {
            "book_id": other[0], "version_id": other[1], "theme_id": other[2], "missing": True, "reason": "the theme is no longer in the file of theme vectors"}
        bands[band]["links"].append({"closeness": closeness / SCALE, "wording_closeness": wording / SCALE, "kind": KIND,
                                     "matched": {"this": centre.get("excerpt_field", "method"), "other": shown.get("excerpt_field", "method")}, "theme": shown})
        total += 1
    return {"warning": note, "weave": {"kind": KIND, "generation": wmeta["generation"], "built": wmeta["built"], "vectors_built": wmeta["vectors_built"],
                                       "current": current, "note": note, "about": ABOUT}, "theme": centre, "links": total, "bands": bands}
