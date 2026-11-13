"""The selection of the links of a weave of "same mechanism" (`kb/weave.py`, Increment B of the plan `2026-11-13-link-themes-that-work-the-same-way`).

The selection is checked three ways: by cases small enough to work out by hand, against a plain-Python reference written here from the rule of the spec (random themes, several
block sizes), and, for the exact median and edges, against `numpy.median` and `numpy.quantile`. The tests need numpy, so run them with the pinned environment:
`engine/.venv/bin/python -m unittest engine.tests.test_weave`."""
import contextlib
import fcntl
import hashlib
import io
import itertools
import json
import math
import os
import random
import shutil
import sqlite3
import stat
import subprocess
import sys
import tracemalloc
import unittest
import unittest.mock

try:
    import numpy as np
except ImportError:   # run with the standard library alone, these tests are skipped and say why
    np = None

from engine.tests.test_themevectors import PerBookCase, with_embedding
from kb import KbError, catalog, models, themevectors, weave
from kb import __main__ as kbmain
from kb import config as kbconfig

SCALE = 10 ** 9
needs_numpy = unittest.skipUnless(np is not None, "numpy is not installed: run with engine/.venv/bin/python")


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def angle(deg):
    return [math.cos(math.radians(deg)), math.sin(math.radians(deg))]


def closeness(a, b):
    """The closeness of two unit vectors in billionths, rounded as `numpy.rint` rounds (half to even)."""
    return int(round(sum(x * y for x, y in zip(a, b)) * SCALE))


def quantile_of(values, q):
    """The value at the quantile q by linear interpolation, written out as `numpy.quantile` does it."""
    xs = sorted(values)
    n = len(xs)
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    t = pos - lo
    a, b = float(xs[lo]), float(xs[hi])
    diff = b - a
    r = a + diff * t
    if t >= 0.5:
        r = b - diff * (1 - t)
    return r


def reference(keys, books, summaries, methods, slots=3, top=300, use_floor=True):
    """The rule of the spec, in plain Python and in the plainest order: the quarters of the summary closeness over the pairs of themes of different books give the edges of four
    bands; the median of the method closeness of those pairs is the floor; each theme puts forward its `top` closest partners in each band (those above the floor); the links are
    taken strongest first, each theme keeping at most `slots` in each band and at most one to one book in a band."""
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    keys = [keys[i] for i in order]
    books = [books[i] for i in order]
    S = [unit(summaries[i]) for i in order]
    M = [unit(methods[i]) for i in order]
    n = len(keys)
    pairs = [(a, b) for a, b in itertools.combinations(range(n), 2) if books[a] != books[b]]
    if not pairs:
        return None, None, []
    cm = {p: closeness(M[p[0]], M[p[1]]) for p in pairs}
    cs = {p: closeness(S[p[0]], S[p[1]]) for p in pairs}
    edges = [quantile_of(list(cs.values()), q) for q in (0.25, 0.5, 0.75)]
    median = quantile_of(list(cm.values()), 0.5)

    def band(w):
        return sum(1 for e in edges if w >= e)

    def partner_pairs(t):
        return [p for p in pairs if t in p and (not use_floor or cm[p] > median)]

    cand = set()
    for t in range(n):
        for b in range(4):
            mine = sorted((p for p in partner_pairs(t) if band(cs[p]) == b), key=lambda p: (-cm[p], p[1] if p[0] == t else p[0]))
            cand.update(mine[:top])
    count, taken, links = {}, set(), []
    for p in sorted(cand, key=lambda p: (-cm[p], p)):
        a, c = p
        b = band(cs[p])
        if count.get((a, b), 0) >= slots or count.get((c, b), 0) >= slots or (a, b, books[c]) in taken or (c, b, books[a]) in taken:
            continue
        count[(a, b)] = count.get((a, b), 0) + 1
        count[(c, b)] = count.get((c, b), 0) + 1
        taken.add((a, b, books[c]))
        taken.add((c, b, books[a]))
        links.append((keys[a], keys[c], cm[p], cs[p], b))
    return edges, median, links


def random_themes(seed, n=30, books=5, dim=3):
    rng = random.Random(seed)
    keys = [("b%d" % rng.randrange(books), "v1", "t%d" % i) for i in range(n)]
    book = [k[0] for k in keys]
    S = [[rng.gauss(0, 1) for _ in range(dim)] for _ in range(n)]
    M = [[rng.gauss(0, 1) for _ in range(dim)] for _ in range(n)]
    return keys, book, S, M


def with_gram(gram):
    """Unit vectors whose dot products are the given (symmetric, positive definite) matrix."""
    return np.linalg.cholesky(np.array(gram, dtype=float)).tolist()


def passes_of(values, size):
    values = list(values)
    return lambda: iter(np.array(values[i:i + size], dtype=np.int64) for i in range(0, len(values), size))


@needs_numpy
class ExactRanksTest(unittest.TestCase):
    def check(self, values, ranks, size=7):
        got = weave.exact_ranks(passes_of(values, size), ranks)
        self.assertEqual(got, [sorted(values)[r] for r in ranks])

    def test_the_value_at_a_rank_of_values_spread_over_the_whole_range(self):
        rng = random.Random(1)
        values = [rng.randint(-SCALE, SCALE) for _ in range(500)]
        self.check(values, [0, 1, 249, 250, 498, 499])
        self.check(values, sorted(rng.sample(range(500), 40)), size=64)

    def test_the_extremes_and_a_single_value(self):
        self.check([-SCALE, SCALE, 0, SCALE, -SCALE], [0, 1, 2, 3, 4])
        self.check([123], [0])

    def test_equal_values_are_counts_and_so_are_values_that_differ_only_a_little(self):
        self.check([500_000_000] * 300, [0, 150, 299])
        rng = random.Random(2)
        self.check([123_456_789 + rng.randint(-1000, 1000) for _ in range(700)], [0, 100, 349, 350, 699])
        self.check([-SCALE] * 100 + [SCALE] * 100, [99, 100])

    def test_the_same_rank_asked_twice_and_ranks_in_any_order(self):
        values = [5, 3, 9, 3, 3, 1, 7]
        self.check(values, [3, 3, 0, 6])
        self.assertEqual(weave.exact_ranks(passes_of(values, 2), [6, 0, 3]), [9, 1, 3])

    def test_a_rank_outside_the_values_is_refused(self):
        with self.assertRaises(KbError):
            weave.exact_ranks(passes_of([1, 2, 3], 2), [3])
        with self.assertRaises(KbError):
            weave.exact_ranks(passes_of([1, 2, 3], 2), [-1])

    def test_a_value_outside_one_to_minus_one_is_refused(self):
        with self.assertRaises(KbError):
            weave.exact_ranks(passes_of([SCALE + 1], 2), [0])

    def test_the_memory_it_holds_does_not_grow_with_the_number_of_values_even_when_all_are_alike(self):
        block = np.full(10_000, 7, dtype=np.int64)
        peaks = []
        for k in (10, 1000):
            tracemalloc.start()
            self.assertEqual(weave.exact_ranks(lambda: (block for _ in range(k)), [k * 5000]), [7])
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
        self.assertLess(abs(peaks[1] - peaks[0]), 500_000)    # 100 times as many values, the same few arrays
        self.assertLess(peaks[1], 8_000_000)


@needs_numpy
class ExactQuantilesTest(unittest.TestCase):
    QS = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)

    def test_the_same_numbers_as_numpy_quantile_and_median_for_odd_and_even_counts_and_repeated_values(self):
        rng = random.Random(3)
        for n in (1, 2, 3, 4, 5, 10, 11, 100, 101, 1000):
            for spread in (SCALE, 5, 1):
                values = [rng.randint(-spread, spread) for _ in range(n)]
                with self.subTest(n=n, spread=spread):
                    got = weave.exact_quantiles(passes_of(values, 13), self.QS)
                    want = np.quantile(np.array(values, dtype=np.int64), self.QS).tolist()
                    self.assertEqual(got, want)
                    self.assertEqual(weave.exact_quantiles(passes_of(values, 13), [0.5])[0], float(np.median(np.array(values, dtype=np.int64))))

    def test_no_values_give_none(self):
        self.assertIsNone(weave.exact_quantiles(passes_of([], 4), [0.5]))

    def test_all_alike_and_nearly_alike(self):
        self.assertEqual(weave.exact_quantiles(passes_of([42] * 50, 8), [0.25, 0.5]), [42.0, 42.0])
        values = [1_000_000 + i % 3 for i in range(90)]
        self.assertEqual(weave.exact_quantiles(passes_of(values, 8), self.QS), np.quantile(np.array(values, dtype=np.int64), self.QS).tolist())


@needs_numpy
class SelectByHandTest(unittest.TestCase):
    def run_select(self, keys, books, S, M, **kw):
        return weave.select(keys, books, S, M, **kw)

    def test_a_link_between_two_themes_of_one_book_is_never_made(self):
        got = self.run_select(["a", "b", "c"], ["x", "x", "x"], [angle(0)] * 3, [angle(0)] * 3, use_floor=False)
        self.assertEqual((got["links"], got["pairs"], got["edges"], got["median"]), ([], 0, None, None))

    def test_the_floor_is_the_median_of_the_pairs_of_different_books_and_a_pair_at_it_is_not_linked(self):
        # four themes in four books, the method vectors at 0, 10, 30 and 70 degrees: the six closenesses are, from the lowest,
        # cos 70, cos 60, cos 40, cos 30, cos 20 and cos 10 degrees; the median is the mean of cos 40 and cos 30, and three pairs are above it
        keys, books = ["a", "b", "c", "d"], ["1", "2", "3", "4"]
        M = [angle(0), angle(10), angle(30), angle(70)]
        got = self.run_select(keys, books, [angle(0)] * 4, M)
        self.assertEqual(sorted((a, b) for a, b, *_ in got["links"]), [("a", "b"), ("a", "c"), ("b", "c")])
        self.assertEqual([c for *_, c, w, b in got["links"]], sorted([closeness(unit(M[0]), unit(M[1])), closeness(unit(M[0]), unit(M[2])),
                                                                       closeness(unit(M[1]), unit(M[2]))], reverse=True))
        self.assertEqual(got["median"], quantile_of([closeness(unit(x), unit(y)) for x, y in itertools.combinations(M, 2)], 0.5))
        # three themes, three pairs: the median is the middle one, which is not linked; only the closest is
        got = self.run_select(["a", "b", "c"], ["1", "2", "3"], [angle(0)] * 3, [angle(0), angle(10), angle(40)])
        self.assertEqual([(a, b) for a, b, *_ in got["links"]], [("a", "b")])

    def test_a_value_that_a_coarse_estimate_would_put_on_the_wrong_side_of_the_floor(self):
        # the three pairs of three themes have the closenesses m - 0.0004, m and m + 0.0004: the median is m, and only the pair above it is linked
        m = 0.60
        gram = [[1, m - 0.0004, m], [m - 0.0004, 1, m + 0.0004], [m, m + 0.0004, 1]]
        M = with_gram(gram)
        S = [[1.0, 0.0, 0.0]] * 3
        got = self.run_select(["a", "b", "c"], ["1", "2", "3"], S, M)
        self.assertEqual([(a, b) for a, b, *_ in got["links"]], [("b", "c")])
        self.assertAlmostEqual(got["median"] / SCALE, m, places=8)
        got = self.run_select(["a", "b", "c"], ["1", "2", "3"], S, M, use_floor=False)
        self.assertEqual(len(got["links"]), 3)

    def test_the_edges_are_the_quarters_of_the_summary_closeness_and_a_link_carries_its_band(self):
        keys, books = ["a", "b", "c", "d", "e"], ["1", "2", "3", "4", "5"]
        S = [angle(0), angle(20), angle(50), angle(100), angle(170)]
        got = self.run_select(keys, books, S, [angle(0)] * 5, use_floor=False)
        values = [closeness(unit(x), unit(y)) for x, y in itertools.combinations(S, 2)]
        self.assertEqual(got["edges"], [quantile_of(values, q) for q in (0.25, 0.5, 0.75)])
        self.assertEqual(got["edges"], np.quantile(np.array(values, dtype=np.int64), [0.25, 0.5, 0.75]).tolist())
        for a, b, c, w, band in got["links"]:
            self.assertEqual(band, sum(1 for e in got["edges"] if w >= e))
            self.assertIn(band, (0, 1, 2, 3))

    def test_a_pair_exactly_at_an_edge_is_in_the_band_above_it(self):
        # five themes in four books (two in one): nine pairs, so the three edges fall exactly on the third, fifth and seventh closeness from the lowest;
        # the angles are such that every one of the nine pairs becomes a link (a and b are of one book, and no theme is put forward by both to one other in a band)
        keys, books = ["a", "b", "c", "d", "e"], ["1", "1", "2", "3", "4"]
        S = [angle(d) for d in (16, 83, 56, 145, 48)]
        got = self.run_select(keys, books, S, [angle(0)] * 5, use_floor=False, slots=10)
        self.assertEqual(len(got["links"]), 9)
        wordings = sorted(w for *_, w, band in got["links"])
        self.assertEqual(got["edges"], [float(wordings[2]), float(wordings[4]), float(wordings[6])])
        by_value = {w: band for *_, w, band in got["links"]}
        self.assertEqual([by_value[wordings[i]] for i in (1, 2, 3, 4, 5, 6, 7)], [0, 1, 1, 2, 2, 3, 3])

    def test_pairs_within_a_few_ten_thousandths_of_an_edge_fall_on_the_right_side_of_it(self):
        # three pairs with the summary closenesses s - 0.0004, s and s + 0.0004: the middle edge is exactly s, the first is s - 0.0002 and the last s + 0.0002,
        # so the pair at s is in band 2 (not band 1) and the others in bands 0 and 3
        s = 0.55
        S = with_gram([[1, s - 0.0004, s], [s - 0.0004, 1, s + 0.0004], [s, s + 0.0004, 1]])
        got = self.run_select(["a", "b", "c"], ["1", "2", "3"], S, [[1.0, 0.0, 0.0]] * 3, use_floor=False)
        by_pair = {(a, b): band for a, b, c, w, band in got["links"]}
        self.assertEqual(by_pair, {("a", "b"): 0, ("a", "c"): 2, ("b", "c"): 3})

    def test_a_vector_with_huge_or_tiny_entries_is_as_usable_as_any_other(self):
        keys, books = ["a", "b", "c", "d"], ["1", "2", "3", "4"]
        S, M = [angle(0), angle(20), angle(50), angle(100)], [angle(0), angle(8), angle(30), angle(70)]
        base = self.run_select(keys, books, S, M)
        for factor in (1e200, 1e-200):
            with self.subTest(factor=factor):
                got = self.run_select(keys, books, [[x * factor for x in v] for v in S], [[x * factor for x in v] for v in M])
                self.assertEqual(got, base)
                self.assertEqual(got["left_out"], [])

    def test_books_that_cannot_be_compared_are_refused(self):
        with self.assertRaises(KbError):
            self.run_select(["a", "b"], [[1], [2]], [angle(0)] * 2, [angle(0)] * 2)

    def test_a_tie_in_what_a_theme_puts_forward_goes_to_the_first_key(self):
        keys = ["t%d" % i for i in range(7)]
        got = self.run_select(keys, keys, [angle(0)] * 7, [angle(0)] * 7, use_floor=False, top=1)
        self.assertEqual([(a, b) for a, b, *_ in got["links"]], [("t0", "t1"), ("t0", "t2"), ("t0", "t3")])

    def test_each_theme_keeps_three_links_in_a_band_at_most_and_the_strongest_first(self):
        # seven themes in seven books, all alike: every pair has the same closeness and the same band, so the links go in the order of the keys
        keys = ["t%d" % i for i in range(7)]
        got = self.run_select(keys, keys, [angle(0)] * 7, [angle(0)] * 7, use_floor=False)
        self.assertEqual([(a, b) for a, b, *_ in got["links"]],
                         [("t0", "t1"), ("t0", "t2"), ("t0", "t3"), ("t1", "t2"), ("t1", "t3"), ("t2", "t3"), ("t4", "t5"), ("t4", "t6"), ("t5", "t6")])
        degree = {}
        for a, b, *_ in got["links"]:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        self.assertEqual(max(degree.values()), 3)
        # with the floor, equal values are all at the median and none is above it
        self.assertEqual(self.run_select(keys, keys, [angle(0)] * 7, [angle(0)] * 7)["links"], [])

    def test_a_theme_links_to_one_theme_of_a_book_in_a_band(self):
        keys, books = ["a0", "b0", "b1", "c0"], ["a", "b", "b", "c"]
        got = self.run_select(keys, books, [angle(0)] * 4, [angle(0)] * 4, use_floor=False)
        pairs = [(a, b) for a, b, *_ in got["links"]]
        # all alike, so the links go by the keys: a0 takes b0 (the first of book b) and c0; b0 takes c0; and then
        #   a0 and b1: a0 has a link to book b in the band already; b0 and b1: the same book; b1 and c0: c0 has a link to book b already
        self.assertEqual(pairs, [("a0", "b0"), ("a0", "c0"), ("b0", "c0")])

    def test_a_stronger_link_takes_the_slot_before_a_weaker_one(self):
        # a has candidates in four books but a slot for three: the weakest of its four is the one left out
        keys = ["a", "b", "c", "d", "e"]
        M = [angle(0), angle(5), angle(15), angle(30), angle(60)]
        got = self.run_select(keys, keys, [angle(0)] * 5, M, use_floor=False, slots=3)
        mine = [(a, b) for a, b, *_ in got["links"] if "a" in (a, b)]
        self.assertEqual(mine, [("a", "b"), ("a", "c"), ("a", "d")])

    def test_the_number_of_slots_and_of_candidates_can_be_changed(self):
        keys = ["t%d" % i for i in range(7)]
        one = self.run_select(keys, keys, [angle(0)] * 7, [angle(0)] * 7, use_floor=False, slots=1)
        self.assertEqual([(a, b) for a, b, *_ in one["links"]], [("t0", "t1"), ("t2", "t3"), ("t4", "t5")])
        few = self.run_select(keys, keys, [angle(0)] * 7, [angle(0)] * 7, use_floor=False, top=1)
        self.assertEqual(len(few["links"]), 3)       # every theme puts forward one partner, and nearly all put forward t0, which has three slots

    def test_a_theme_with_no_usable_vector_is_left_out_and_counted(self):
        keys, books = ["a", "b", "c", "d", "e"], ["1", "2", "3", "4", "5"]
        S = [angle(0), angle(0), None, angle(0), [0.0, 0.0]]
        M = [angle(0), angle(0), angle(0), [float("nan"), 1.0], angle(0)]
        got = self.run_select(keys, books, S, M, use_floor=False)
        self.assertEqual(got["left_out"], ["c", "d", "e"])
        self.assertEqual([(a, b) for a, b, *_ in got["links"]], [("a", "b")])

    def test_keys_that_are_not_alike_and_inputs_that_do_not_fit_are_refused(self):
        with self.assertRaises(KbError):
            self.run_select(["a", "a"], ["1", "2"], [angle(0)] * 2, [angle(0)] * 2)
        with self.assertRaises(KbError):
            self.run_select(["a", "b"], ["1"], [angle(0)] * 2, [angle(0)] * 2)
        with self.assertRaises(KbError):
            self.run_select(["a", "b"], ["1", "2"], [angle(0)] * 2, [angle(0)] * 2, slots=0)
        with self.assertRaises(KbError):
            self.run_select(["a", "b"], ["1", "2"], [angle(0)] * 2, [angle(0)] * 2, top=True)
        with self.assertRaises(KbError):
            self.run_select(["a", "b"], ["1", "2"], [angle(0)] * 2, [angle(0)] * 2, block=0)

    def test_without_numpy_it_says_what_to_install(self):
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}):
            with self.assertRaises(KbError) as cm:
                self.run_select(["a", "b"], ["1", "2"], [angle(0)] * 2, [angle(0)] * 2)
        self.assertIn("numpy", str(cm.exception))
        self.assertIn("requirements.lock", str(cm.exception))


@needs_numpy
class SelectAgainstTheReferenceTest(unittest.TestCase):
    def test_the_links_are_those_of_the_plain_rule_for_random_themes_with_and_without_the_floor(self):
        for seed in range(6):
            keys, books, S, M = random_themes(seed)
            for use_floor in (True, False):
                for top in (300, 4):
                    with self.subTest(seed=seed, use_floor=use_floor, top=top):
                        edges, median, links = reference(keys, books, S, M, top=top, use_floor=use_floor)
                        got = weave.select(keys, books, S, M, top=top, use_floor=use_floor)
                        self.assertEqual(got["edges"], edges)
                        self.assertEqual(got["median"], median)
                        self.assertEqual(got["links"], links)

    def test_no_link_breaks_a_rule(self):
        for seed in range(6):
            keys, books, S, M = random_themes(seed, n=40, books=6)
            got = weave.select(keys, books, S, M)
            book = dict(zip(keys, books))
            count, one_book = {}, set()
            for a, b, c, w, band in got["links"]:
                self.assertNotEqual(book[a], book[b])
                self.assertGreater(c, got["median"])
                for x, y in ((a, b), (b, a)):
                    count[(x, band)] = count.get((x, band), 0) + 1
                    self.assertLessEqual(count[(x, band)], weave.SLOTS)
                    self.assertNotIn((x, band, book[y]), one_book)
                    one_book.add((x, band, book[y]))
            per_theme = {}
            for a, b, *_ in got["links"]:
                per_theme[a] = per_theme.get(a, 0) + 1
                per_theme[b] = per_theme.get(b, 0) + 1
            self.assertLessEqual(max(per_theme.values()), 4 * weave.SLOTS)
            self.assertEqual([x[2] for x in got["links"]], sorted((x[2] for x in got["links"]), reverse=True))

    def test_the_same_links_whatever_the_size_of_the_blocks(self):
        keys, books, S, M = random_themes(11, n=37, books=5)
        base = weave.select(keys, books, S, M, block=1000)
        for block in (1, 2, 5, 36, 37, 38):
            with self.subTest(block=block):
                self.assertEqual(weave.select(keys, books, S, M, block=block), base)

    def test_the_same_links_whatever_the_order_in_which_the_themes_are_given(self):
        keys, books, S, M = random_themes(12, n=33, books=6)
        base = weave.select(keys, books, S, M)
        order = list(range(len(keys)))
        random.Random(5).shuffle(order)
        shuffled = weave.select([keys[i] for i in order], [books[i] for i in order], [S[i] for i in order], [M[i] for i in order])
        self.assertEqual(shuffled, base)

    def test_ties_are_broken_by_the_keys_of_the_themes(self):
        keys = ["t%d" % i for i in range(9)]
        books = ["b%d" % (i % 4) for i in range(9)]
        S, M = [angle(0)] * 9, [angle(0)] * 9
        base = weave.select(keys, books, S, M, use_floor=False)
        order = list(range(9))
        random.Random(1).shuffle(order)
        self.assertEqual(weave.select([keys[i] for i in order], [books[i] for i in order], S, M, use_floor=False), base)

    def test_without_the_floor_the_links_are_those_with_it_and_more(self):
        keys, books, S, M = random_themes(13, n=40, books=6)
        with_floor = weave.select(keys, books, S, M)
        without = weave.select(keys, books, S, M, use_floor=False)
        self.assertEqual((with_floor["median"], with_floor["edges"]), (without["median"], without["edges"]))
        self.assertGreater(len(without["links"]), len(with_floor["links"]))
        self.assertTrue(all(link[2] > with_floor["median"] for link in with_floor["links"]))


def deg4(d):
    """A vector of the dimension 4 (the dimension of the tests of the vectors) at the angle d degrees."""
    return [math.cos(math.radians(d)), math.sin(math.radians(d)), 0.0, 0.0]


def as_stored(v):
    """A vector as the file of the vectors keeps it: little-endian 32-bit floats, read back as doubles."""
    return np.array(v, dtype=np.float32).astype(np.float64).tolist()


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@needs_numpy
class WeaveCase(PerBookCase):
    """Books with themes whose summary vector and method vector are at the angles the test names, built into a file of theme vectors of the dimension 4."""

    SPEC = {"A": [(0, 0), (40, 10)], "B": [(10, 30), (80, 70)], "C": [(20, 5), (60, 50)]}   # book: [(summary degrees, method degrees) of each theme]

    def setUp(self):
        super().setUp()
        self.books = {name: self.themed(self.themes_of(name, len(themes)))[0] for name, themes in self.SPEC.items()}
        self.build()
        away, table = [0.0, 0.0, 1.0, 0.0], {}
        for r in self.themes_read():
            texts = themevectors.texts_of(r["theme"])
            for text in texts.values():
                table[text] = away
            name = r["theme"]["title"].split()[-1]
            summary, method = self.SPEC[name[0]][int(name[1:])]
            table[texts["summary"]], table[texts["method"]] = deg4(summary), deg4(method)
        self.plan(table=table)
        self.build(again=True)

    def index_root(self):
        return self.store.cfg["index_root"]

    def weave_path(self):
        return weave.path_of(self.index_root())

    def build_weave(self, cfg=None, **kw):
        return weave.build(self.index_root(), cfg or self.mcfg, **kw)

    def keyed(self):
        return {r["theme"]["title"].split()[-1]: (r["book_id"], r["version_id"], r["theme_id"]) for r in self.themes_read()}

    def expected(self, **kw):
        keyed = self.keyed()
        names = sorted(keyed, key=keyed.get)
        spec = {f"{b}{i}": pair for b, themes in self.SPEC.items() for i, pair in enumerate(themes)}
        return weave.select([keyed[n] for n in names], [keyed[n][0] for n in names], [as_stored(deg4(spec[n][0])) for n in names],
                            [as_stored(deg4(spec[n][1])) for n in names], **kw)

    def leftovers(self):
        return [n for n in os.listdir(self.index_root()) if n.startswith(weave.BUILD_PREFIX)]


@needs_numpy
class WeaveBuildTest(WeaveCase):
    def test_a_build_makes_the_links_of_the_selection_and_says_what_it_was_made_from(self):
        counts = self.build_weave()
        want = self.expected()
        self.assertGreater(len(want["links"]), 0)
        got = weave.read(self.weave_path())
        self.assertEqual(got["links"], want["links"])
        meta, vmeta = got["meta"], self.meta()
        self.assertEqual((meta["kind"], meta["generation"], meta["slots"], meta["top"], meta["bands"]), ("same-mechanism", 1, 3, 300, 4))
        self.assertEqual((meta["vectors_model"], meta["vectors_configured"], meta["vectors_dimension"], meta["vectors_built"], meta["vectors_document_prefix_sha256"]),
                         (vmeta["model"], vmeta["configured"], int(vmeta["dimension"]), vmeta["built"], vmeta["document_prefix_sha256"]))
        self.assertEqual((meta["edges"], meta["median"], meta["pairs"]), (want["edges"], want["median"], want["pairs"]))
        self.assertRegex(meta["built"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(meta["numpy"], np.__version__)
        self.assertEqual([t["theme_generation"] for t in got["themes"]], [1] * 6)
        self.assertEqual((counts["links"], counts["generation"], counts["replaced"], counts["themes_in_vectors_file"], counts["themes_processed"]), (len(want["links"]), 1, False, 6, 6))

    def test_the_counts_say_what_was_done(self):
        counts = self.build_weave()
        want, without = self.expected(), self.expected(use_floor=False)
        degree = {}
        for a, b, *_ in want["links"]:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        self.assertEqual(counts["links_without_floor"], len(without["links"]))
        self.assertEqual((counts["themes_with_links"], counts["themes_with_no_link"]), (len(degree), 6 - len(degree)))
        self.assertEqual((counts["left_out"], counts["left_out_reasons"]), (0, {"no_text": 0, "no_usable_vector": 0}))
        far = {x for a, b, c, w, band in want["links"] if band == 0 for x in (a, b)}
        self.assertEqual(counts["no_link_in_farthest_band"], 6 - len(far))
        self.assertEqual((counts["edges"], counts["median"], counts["pairs"]), (want["edges"], want["median"], want["pairs"]))

    def test_a_second_build_is_a_new_generation_and_the_one_before_is_kept_as_it_was(self):
        self.build_weave()
        first = file_sha256(self.weave_path())
        again = self.build_weave()
        self.assertEqual(again["generation"], 2)
        self.assertEqual(weave.read(self.weave_path())["links"], self.expected()["links"])
        self.assertEqual(file_sha256(os.path.join(self.index_root(), weave.PREVIOUS_FILE)), first)
        self.assertEqual(weave.read(os.path.join(self.index_root(), weave.PREVIOUS_FILE))["meta"]["generation"], 1)
        second = file_sha256(self.weave_path())
        self.assertEqual(self.build_weave()["generation"], 3)
        self.assertEqual(file_sha256(os.path.join(self.index_root(), weave.PREVIOUS_FILE)), second)    # only one before is kept

    def test_the_generation_before_is_kept_by_a_copy_if_a_link_to_the_file_cannot_be_made(self):
        self.build_weave()
        first = file_sha256(self.weave_path())
        with unittest.mock.patch("kb.weave.os.link", side_effect=OSError(1, "operation not permitted")):
            self.assertEqual(self.build_weave()["generation"], 2)
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        self.assertEqual(file_sha256(previous), first)
        self.assertEqual(stat.S_IMODE(os.stat(previous).st_mode), 0o600)
        self.assertNotEqual(os.stat(previous).st_ino, os.stat(self.weave_path()).st_ino)

    def test_a_name_for_the_generation_before_that_is_a_link_is_replaced_and_its_target_left_alone(self):
        self.build_weave()
        target = os.path.join(self.base_dir(), "other.sqlite")
        with open(target, "wb") as f:
            f.write(b"somebody's file")
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        os.symlink(target, previous)
        self.build_weave()
        self.assertFalse(os.path.islink(previous))
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"somebody's file")
        self.assertEqual(weave.read(previous)["meta"]["generation"], 1)

    def test_a_weave_in_place_that_has_become_a_link_is_not_followed_to_keep_it_as_the_generation_before(self):
        self.build_weave()
        elsewhere = os.path.join(self.base_dir(), "secret.txt")
        with open(elsewhere, "wb") as f:
            f.write(b"not a weave")
        os.remove(self.weave_path())
        os.symlink(elsewhere, self.weave_path())
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        with self.assertRaises(KbError):
            weave._keep_previous(self.weave_path(), os.path.join(self.base_dir(), "held"), previous)
        self.assertFalse(os.path.exists(previous))
        self.assertFalse(os.path.exists(os.path.join(self.base_dir(), "held")))

    def test_a_failure_at_the_second_rename_leaves_the_weave_in_place_and_the_next_build_goes_on(self):
        self.build_weave()
        self.build_weave()
        before = file_sha256(self.weave_path())
        real, calls = os.replace, []

        def second_fails(src, dst, *a, **k):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError(5, "input/output error")
            return real(src, dst, *a, **k)

        with unittest.mock.patch("kb.weave.os.replace", second_fails), self.assertRaises(KbError):
            self.build_weave()
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        self.assertEqual((file_sha256(self.weave_path()), file_sha256(previous)), (before, before))    # both names hold the generation in place; nothing is damaged
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.build_weave()["generation"], 3)
        self.assertEqual(file_sha256(previous), before)

    def test_a_weave_file_that_is_damaged_goes_on_from_the_generation_before_and_leaves_it_as_it_was(self):
        self.build_weave()
        self.build_weave()
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        kept = file_sha256(previous)
        with open(self.weave_path(), "wb") as f:
            f.write(b"not a database")
        again = self.build_weave()
        self.assertEqual((again["replaced"], again["generation"]), (True, 2))
        self.assertEqual(file_sha256(previous), kept)

    def test_the_count_of_the_links_at_or_under_the_floor_is_of_those_the_slot_rule_makes_without_it(self):
        counts = self.build_weave()
        without = self.expected(use_floor=False)
        self.assertEqual(counts["links_at_or_under_the_floor"], sum(1 for link in without["links"] if link[2] <= without["median"]))
        self.assertGreater(counts["links_at_or_under_the_floor"], 0)

    def test_the_file_is_private_and_a_folder_of_a_build_that_was_killed_is_removed(self):
        os.mkdir(os.path.join(self.index_root(), weave.BUILD_PREFIX + "leftover"))
        self.build_weave()
        self.build_weave()
        self.assertEqual(self.leftovers(), [])
        for name in (weave.INDEX_FILE, weave.PREVIOUS_FILE, weave.LOCK_FILE):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.index_root(), name)).st_mode), 0o600, name)

    def test_the_vectors_file_is_not_changed_and_no_model_is_called(self):
        before, asked = file_sha256(themevectors.path_of(self.index_root())), self.calls()
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")), \
                unittest.mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")):
            self.build_weave()
        self.assertEqual(file_sha256(themevectors.path_of(self.index_root())), before)
        self.assertEqual(self.calls(), asked)    # the bridge of the tests was not asked again

    def test_a_rename_that_fails_leaves_the_old_file_as_it_was_and_no_folder(self):
        self.build_weave()
        before = file_sha256(self.weave_path())
        with unittest.mock.patch("kb.weave.os.replace", side_effect=OSError(5, "input/output error")):
            with self.assertRaises(KbError):
                self.build_weave()
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.build_weave()["generation"], 2)

    def test_another_writer_holds_the_lock(self):
        fd = os.open(os.path.join(self.index_root(), weave.LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with unittest.mock.patch.object(catalog, "LOCK_WAIT", 0.2), self.assertRaises(KbError) as cm:
                self.build_weave()
            self.assertIn("another process", str(cm.exception))
        finally:
            os.close(fd)
        self.assertFalse(os.path.exists(self.weave_path()))

    def test_a_lock_file_that_is_a_link_is_not_followed(self):
        target = os.path.join(self.base_dir(), "elsewhere")
        open(target, "w").close()
        os.symlink(target, os.path.join(self.index_root(), weave.LOCK_FILE))
        with self.assertRaises(KbError):
            self.build_weave()
        self.assertFalse(os.path.exists(self.weave_path()))

    def test_a_weave_file_that_is_a_link_is_replaced_and_its_target_is_left_alone(self):
        self.build_weave()
        target = os.path.join(self.base_dir(), "moved.sqlite")
        os.replace(self.weave_path(), target)
        os.symlink(target, self.weave_path())
        kept = file_sha256(target)
        again = self.build_weave()
        self.assertTrue(again["replaced"])
        self.assertEqual((again["generation"], file_sha256(target)), (1, kept))
        self.assertFalse(os.path.islink(self.weave_path()))
        self.assertEqual(weave.read(self.weave_path())["links"], self.expected()["links"])

    def test_a_weave_file_that_is_damaged_is_replaced_and_not_kept_as_the_one_before(self):
        self.build_weave()
        with open(self.weave_path(), "wb") as f:
            f.write(b"not a database")
        again = self.build_weave()
        self.assertEqual((again["replaced"], again["generation"]), (True, 1))
        self.assertFalse(os.path.exists(os.path.join(self.index_root(), weave.PREVIOUS_FILE)))

    def test_no_file_of_vectors_or_one_for_another_model_dimension_or_prefix_or_not_the_engines_is_refused_and_nothing_is_written(self):
        for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
            with self.subTest(cfg=cfg["models"]["emb"]), self.assertRaises(KbError):
                self.build_weave(cfg)
        path = themevectors.path_of(self.index_root())
        with open(path, "rb") as f:
            good = f.read()
        with open(path, "wb") as f:
            f.write(b"damaged")
        with self.assertRaises(KbError):
            self.build_weave()
        os.remove(path)
        with self.assertRaises(KbError) as cm:
            self.build_weave()
        self.assertIn("theme-vectors", str(cm.exception))
        with closing_sqlite(path) as conn:
            conn.execute("CREATE TABLE other (x)")
        with self.assertRaises(KbError):
            self.build_weave()
        self.assertFalse(os.path.exists(self.weave_path()))
        self.assertEqual(self.leftovers(), [])
        with open(path, "wb") as f:
            f.write(good)

    def test_without_numpy_the_build_says_what_to_install_and_writes_nothing(self):
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}), self.assertRaises(KbError) as cm:
            self.build_weave()
        self.assertIn("requirements.lock", str(cm.exception))
        self.assertFalse(os.path.exists(self.weave_path()))
        self.assertEqual(self.leftovers(), [])

    def test_a_value_of_a_theme_that_is_stale_is_left_out_and_counted(self):
        path = themevectors.path_of(self.index_root())
        with closing_sqlite(path) as conn:
            conn.execute("UPDATE vectors SET text_sha256 = ? WHERE rowid = (SELECT rowid FROM vectors WHERE field = 'method' LIMIT 1)", ("0" * 64,))
        counts = self.build_weave()
        self.assertEqual((counts["themes_processed"], counts["left_out"]), (5, 1))
        self.assertEqual(counts["left_out_reasons"], {"no_text": 0, "no_usable_vector": 1})


def closing_sqlite(path):
    return contextlib.closing(sqlite3.connect(path, isolation_level=None))


@needs_numpy
class WeaveFloorTest(WeaveCase):
    SPEC = {"A": [(0, 0)], "B": [(0, 10)], "C": [(0, 30)], "D": [(0, 70)]}   # one theme in each of four books; the floor leaves the theme at 70 degrees with no link

    def test_a_theme_left_with_no_link_by_the_floor_is_in_the_weave_with_none(self):
        counts = self.build_weave()
        got = weave.read(self.weave_path())
        by_name = {name: key for name, key in self.keyed().items()}
        self.assertEqual({t["key"]: t["links"] for t in got["themes"]}, {by_name["A0"]: 2, by_name["B0"]: 2, by_name["C0"]: 2, by_name["D0"]: 0})
        self.assertEqual((counts["themes_processed"], counts["themes_with_no_link"], counts["links"]), (4, 1, 3))


@needs_numpy
class ReadingTheWeaveFileTest(WeaveCase):
    def setUp(self):
        super().setUp()
        self.build_weave()
        self.copy = os.path.join(self.base_dir(), "copy.sqlite")

    def damaged(self, statement):
        shutil.copyfile(self.weave_path(), self.copy)
        with closing_sqlite(self.copy) as conn:
            conn.execute(statement)
        return self.copy

    def test_a_good_file_is_read_and_a_missing_one_or_a_link_is_refused(self):
        self.assertEqual(len(weave.read(self.weave_path())["themes"]), 6)
        with self.assertRaises(KbError) as cm:
            weave.read(os.path.join(self.base_dir(), "none.sqlite"))
        self.assertIn("theme-links build", str(cm.exception))
        os.symlink(self.weave_path(), os.path.join(self.base_dir(), "link.sqlite"))
        with self.assertRaises(KbError):
            weave.read(os.path.join(self.base_dir(), "link.sqlite"))

    def test_a_number_of_pairs_of_more_than_nine_digits_is_read(self):
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '12345678901' WHERE key = 'pairs'")
        self.assertEqual(weave.read(self.weave_path())["meta"]["pairs"], 12345678901)

    def test_a_row_or_a_value_that_is_not_what_the_engine_writes_is_refused(self):
        a_link = "(SELECT rowid FROM links LIMIT 1)"
        statements = [
            "INSERT INTO meta (key, value) VALUES ('extra', 'x')",
            "DELETE FROM meta WHERE key = 'kind'",
            "UPDATE meta SET value = '2' WHERE key = 'format'",
            "UPDATE meta SET value = 'other' WHERE key = 'kind'",
            "UPDATE meta SET value = '0' WHERE key = 'generation'",
            "UPDATE meta SET value = '[1, 2]' WHERE key = 'edges'",
            "UPDATE meta SET value = '[3.0, 2.0, 1.0]' WHERE key = 'edges'",
            "UPDATE meta SET value = '[NaN, 1.0, 2.0]' WHERE key = 'edges'",
            "UPDATE meta SET value = 'null' WHERE key = 'median'",
            "UPDATE meta SET value = '5' WHERE key = 'bands'",
            "UPDATE meta SET value = 'a long time ago' WHERE key = 'built'",
            "UPDATE meta SET value = 'x' WHERE key = 'vectors_dimension'",
            "UPDATE meta SET value = 'x' WHERE key = 'vectors_document_prefix_sha256'",
            "CREATE TABLE extra (x)",
            "CREATE TRIGGER t AFTER INSERT ON meta BEGIN SELECT 1; END",
            "CREATE VIEW v AS SELECT 1",
            "UPDATE themes SET book_id = 'a bad id' WHERE rowid = 1",
            "UPDATE themes SET method_sha256 = 'zz' WHERE rowid = 1",
            "UPDATE themes SET theme_generation = 0 WHERE rowid = 1",
            "UPDATE themes SET links = links + 1 WHERE rowid = 1",
            "DELETE FROM themes WHERE rowid = 1",
            f"UPDATE links SET b_book = a_book WHERE rowid = {a_link}",
            f"UPDATE links SET closeness = -5 WHERE rowid = {a_link}",
            f"UPDATE links SET closeness = 2000000000 WHERE rowid = {a_link}",
            f"UPDATE links SET band = (band + 1) % 4 WHERE rowid = {a_link}",
            f"UPDATE links SET wording = 'x' WHERE rowid = {a_link}",
            f"UPDATE links SET a_theme = 'zz' WHERE rowid = {a_link}",
            "UPDATE links SET a_book = b_book, a_version = b_version, a_theme = b_theme, b_book = a_book, b_version = a_version, b_theme = a_theme WHERE rowid = (SELECT rowid FROM links LIMIT 1)",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(KbError):
                    weave.read(self.damaged(statement))

    def test_more_links_than_the_slot_rule_allows_are_refused_and_a_file_that_keeps_it_is_not(self):
        # rows made by hand: themes t0 to t4 in books b0 to b4, and a link of t0 to each of the others in one band (wording 0.9, band 3), each above the median 0.1
        def rows(links, slots=3):
            meta = {"slots": slots, "median": 1e8, "edges": [1e8, 2e8, 3e8], "bands": 4}
            keys = [(f"b{i}", "v1", "t1") for i in range(5)]
            themes = [{"key": k, "links": sum(1 for a, b in links if i in (a, b))} for i, k in enumerate(keys)]
            return meta, themes, [(keys[a], keys[b], 5 * 10 ** 8, 9 * 10 ** 8, 3) for a, b in links]
        weave.check_rows(*rows([(0, 1), (0, 2), (0, 3)]))                  # three in a band is the rule
        with self.assertRaises(KbError):
            weave.check_rows(*rows([(0, 1), (0, 2), (0, 3), (0, 4)]))      # four are not
        weave.check_rows(*rows([(0, 1), (0, 2), (0, 3), (0, 4)], slots=4))
        meta, themes, links = rows([(0, 1)])
        links.append((links[0][0], links[0][1], 6 * 10 ** 8, 9 * 10 ** 8, 3))
        with self.assertRaises(KbError):
            weave.check_rows(meta, themes, links)                          # the same pair twice
        # two links of one theme to one book in a band: t0 to a theme of book b9 and another theme of book b9
        keys = [("b0", "v1", "t1"), ("b9", "v1", "t1"), ("b9", "v1", "t2")]
        meta = {"slots": 3, "median": 1e8, "edges": [1e8, 2e8, 3e8], "bands": 4}
        themes = [{"key": keys[0], "links": 2}, {"key": keys[1], "links": 1}, {"key": keys[2], "links": 1}]
        links = [(keys[0], keys[1], 5 * 10 ** 8, 9 * 10 ** 8, 3), (keys[0], keys[2], 4 * 10 ** 8, 9 * 10 ** 8, 3)]
        with self.assertRaises(KbError):
            weave.check_rows(meta, themes, links)


@needs_numpy
class ThemeLinksCommandTest(WeaveCase):
    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(with_embedding())
        kbconfig.save(saved)

    def kb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_theme_links_build_prints_the_counts_and_a_second_build_is_the_next_generation(self):
        code, out, err = self.kb("theme-links", "build")
        counts = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((counts["generation"], counts["themes_processed"], counts["links"] > 0), (1, 6, True))
        code, out, _ = self.kb("theme-links", "build")
        self.assertEqual((code, json.loads(out)["generation"]), (0, 2))

    def test_without_the_file_of_vectors_it_refuses_and_names_the_command_to_run(self):
        os.remove(themevectors.path_of(self.index_root()))
        code, out, err = self.kb("theme-links", "build")
        self.assertEqual(code, 2)
        self.assertIn("theme-vectors", err)
        self.assertEqual(out, "")

    def test_it_takes_no_model_server_address_or_launcher_and_needs_a_sub_command(self):
        for option in ("--model", "--server", "--address", "--host", "--url", "--launcher", "--bridge"):
            with self.subTest(option=option):
                self.assertEqual(self.kb("theme-links", "build", option, "x")[0], 2)
        self.assertEqual(self.kb("theme-links")[0], 2)

    def test_without_numpy_the_command_refuses_and_every_other_module_still_imports(self):
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}):
            code, out, err = self.kb("theme-links", "build")
        self.assertEqual(code, 2)
        self.assertIn("numpy", err)
        engine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        program = ("import sys; sys.modules['numpy'] = None; sys.path.insert(0, %r); import pkgutil, importlib, kb; "
                   "[importlib.import_module('kb.' + m.name) for m in pkgutil.iter_modules(kb.__path__)]; print('imported')" % engine)
        done = subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, text=True, timeout=120)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "imported"), done.stderr)


if __name__ == "__main__":
    unittest.main()
