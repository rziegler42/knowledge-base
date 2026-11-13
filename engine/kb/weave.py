"""The links of a weave of "same mechanism": which links a theme keeps (`docs/specs/weave.md`, "Keeping the graph sparse without losing novelty"; the plan
`2026-11-13-link-themes-that-work-the-same-way`). This module is the selection only, as pure functions of vectors: it reads no file and no store.

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
import math

from . import KbError

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
    found_a, found_b, found_m, found_s, found_band = [], [], [], [], []
    for start in range(0, n, block):
        stop = min(start + block, n)
        cm, cs = closeness(M, start, stop), closeness(S, start, stop)
        band = np.digitize(cs, edges)
        for i in range(start, stop):
            row_cm = cm[i - start]
            allowed = book != book[i]
            if use_floor:
                allowed = allowed & (row_cm > median)
            for b in range(BANDS):
                idx = np.nonzero(allowed & (band[i - start] == b))[0]
                if not len(idx):
                    continue
                idx = idx[np.lexsort((idx, -row_cm[idx]))[:top]]
                found_a.append(np.minimum(idx, i))
                found_b.append(np.maximum(idx, i))
                found_m.append(row_cm[idx])
                found_s.append(cs[i - start][idx])
                found_band.append(np.full(len(idx), b, dtype=np.int64))
    if not found_a:
        return result
    a, b = np.concatenate(found_a), np.concatenate(found_b)
    m, s, bd = np.concatenate(found_m), np.concatenate(found_s), np.concatenate(found_band)
    _, first = np.unique(a * n + b, return_index=True)      # a pair put forward from both ends is one
    a, b, m, s, bd = a[first], b[first], m[first], s[first], bd[first]
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
