"""The selection of the links of a weave of "same mechanism" (`kb/weave.py`, Increment B of the plan `2026-11-13-link-themes-that-work-the-same-way`).

The selection is checked three ways: by cases small enough to work out by hand, against a plain-Python reference written here from the rule of the spec (random themes, several
block sizes), and, for the exact median and edges, against `numpy.median` and `numpy.quantile`. The tests need numpy, so run them with the pinned environment:
`engine/.venv/bin/python -m unittest engine.tests.test_weave`."""
import contextlib
import datetime
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

from engine.tests.test_themevectors import HOSTILE_HEADING, PerBookCase, strings_of, with_embedding
from kb import KbError, card, catalog, models, read as reading, search as fulltext, textutil, theme, themevectors, weave
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
        self.vectorize()

    def vectorize(self):
        """Make the file of vectors so that each theme has the summary vector and the method vector that `self.SPEC` names."""
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

    def add_books(self, extra):
        """Books that come after a weave was built: their themes, and the file of vectors made again with the vectors that `extra` names."""
        self.SPEC = {**self.SPEC, **extra}
        for name, themes in extra.items():
            self.books[name] = self.themed(self.themes_of(name, len(themes)))[0]
        self.vectorize()

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

    def test_a_weave_with_a_generation_of_ten_digits_goes_on_and_one_at_the_limit_is_refused_before_any_file_is_made(self):
        self.build_weave()
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '5000000000' WHERE key = 'generation'")
        self.assertEqual(self.build_weave()["generation"], 5000000001)
        self.assertEqual(weave.read(self.weave_path())["meta"]["generation"], 5000000001)
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '999999999998' WHERE key = 'generation'")
        self.assertEqual(self.build_weave()["generation"], 999999999999)
        before = file_sha256(self.weave_path())
        with unittest.mock.patch.object(weave, "select", side_effect=AssertionError("the work was started")), self.assertRaises(KbError) as cm:
            self.build_weave()                    # refused at the start, before the links are worked out
        self.assertIn("remove", str(cm.exception))
        self.assertIn(weave.INDEX_FILE, str(cm.exception))
        self.assertIn(weave.PREVIOUS_FILE, str(cm.exception))        # the generation before holds the number too: removing the one alone would not help
        self.assertEqual((file_sha256(self.weave_path()), self.leftovers()), (before, []))

    def test_the_last_generation_in_the_generation_before_alone_is_refused_too_and_the_message_says_what_to_remove(self):
        self.build_weave()
        self.build_weave()
        with closing_sqlite(os.path.join(self.index_root(), weave.PREVIOUS_FILE)) as conn:
            conn.execute("UPDATE meta SET value = '999999999999' WHERE key = 'generation'")
        os.remove(self.weave_path())
        with unittest.mock.patch.object(weave, "select", side_effect=AssertionError("the work was started")), self.assertRaises(KbError) as cm:
            self.build_weave()
        self.assertIn(weave.PREVIOUS_FILE, str(cm.exception))

    def test_a_weave_in_place_that_is_swapped_for_a_link_after_the_check_is_not_copied_when_a_link_to_it_cannot_be_made(self):
        self.build_weave()
        secret = os.path.join(self.base_dir(), "secret.txt")
        with open(secret, "wb") as f:
            f.write(b"not a weave, but the owner's")
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        held = os.path.join(self.base_dir(), "held")

        def link_that_swaps(src, dst, **kw):          # the weave is swapped for a link to the secret between the check and the copy
            os.remove(src)
            os.symlink(secret, src)
            raise OSError(1, "operation not permitted")

        with unittest.mock.patch("kb.weave.os.link", link_that_swaps), self.assertRaises(KbError):
            weave._keep_previous(self.weave_path(), held, previous)
        self.assertFalse(os.path.exists(previous))
        self.assertFalse(os.path.exists(held))
        with open(secret, "rb") as f:
            self.assertEqual(f.read(), b"not a weave, but the owner's")
        # swapped for a folder instead: it is opened, and it is not a regular file, which the descriptor says
        os.remove(self.weave_path())
        self.build_weave()

        def link_that_swaps_for_a_folder(src, dst, **kw):
            os.remove(src)
            os.mkdir(src)
            raise OSError(1, "operation not permitted")

        with unittest.mock.patch("kb.weave.os.link", link_that_swaps_for_a_folder), self.assertRaises(KbError):
            weave._keep_previous(self.weave_path(), held, previous)
        self.assertFalse(os.path.exists(previous))
        self.assertFalse(os.path.exists(held))
        # swapped for a link and the hard link is made of the link itself (as some systems do with follow_symlinks=False): what is at `held` is a link, which is not kept
        os.rmdir(self.weave_path())
        self.build_weave()

        def link_of_a_link(src, dst, **kw):
            os.symlink(secret, dst)

        with unittest.mock.patch("kb.weave.os.link", link_of_a_link), self.assertRaises(KbError):
            weave._keep_previous(self.weave_path(), held, previous)
        self.assertFalse(os.path.lexists(previous))
        self.assertFalse(os.path.lexists(held))
        with open(secret, "rb") as f:
            self.assertEqual(f.read(), b"not a weave, but the owner's")

    def test_a_weave_in_place_that_is_swapped_for_a_pipe_is_refused_and_does_not_wait_for_a_writer(self):
        import signal
        self.build_weave()
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        held = os.path.join(self.base_dir(), "held")

        def link_that_swaps_for_a_pipe(src, dst, **kw):
            os.remove(src)
            os.mkfifo(src)
            raise OSError(1, "operation not permitted")

        class WaitedForAWriter(Exception):        # not an OSError, which the copy turns into a refusal
            pass

        def too_long(*a):
            raise WaitedForAWriter("the copy waited for a writer of the pipe")

        old_handler = signal.signal(signal.SIGALRM, too_long)
        signal.alarm(10)
        try:
            with unittest.mock.patch("kb.weave.os.link", link_that_swaps_for_a_pipe), self.assertRaises(KbError):
                weave._keep_previous(self.weave_path(), held, previous)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        self.assertFalse(os.path.lexists(previous))
        self.assertFalse(os.path.lexists(held))

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

    def test_a_median_written_as_a_list_or_edges_as_one_number_or_a_boolean_are_refused_and_not_a_traceback(self):
        for statement in ("UPDATE meta SET value = '[5]' WHERE key = 'median'", "UPDATE meta SET value = '[1, 2, 3]' WHERE key = 'median'",
                          "UPDATE meta SET value = '5' WHERE key = 'edges'", "UPDATE meta SET value = 'true' WHERE key = 'median'",
                          "UPDATE meta SET value = '[true, 2, 3]' WHERE key = 'edges'", "UPDATE meta SET value = '\"5\"' WHERE key = 'median'",
                          f"UPDATE meta SET value = '{'1' + '0' * 400}' WHERE key = 'median'", f"UPDATE meta SET value = '[1, 2, {'1' + '0' * 400}]' WHERE key = 'edges'",
                          f"UPDATE meta SET value = '-{'1' + '0' * 400}' WHERE key = 'median'"):
            with self.subTest(statement=statement), self.assertRaises(KbError):
                weave.read(self.damaged(statement))

    def test_check_rows_refuses_a_median_or_an_edge_that_is_not_a_number_even_when_there_are_no_links(self):
        themes = [{"key": ("b1", "v1", "t1"), "links": 0}]
        good = {"slots": 3, "median": 1e8, "edges": [1e8, 2e8, 3e8], "bands": 4}
        weave.check_rows(good, themes, [])
        weave.check_rows({**good, "median": 100000000, "edges": [1, 2, 3]}, themes, [])
        for bad in ({"median": 10 ** 400}, {"median": -10 ** 400}, {"edges": [1, 2, 10 ** 400]}, {"median": [5]}, {"median": True}, {"median": "5"}, {"median": None, "edges": [1, 2, 3]}, {"edges": [1, 2]}, {"edges": [True, 2, 3]}, {"edges": 5},
                    {"edges": ["1", 2, 3]}, {"median": float("nan")}, {"edges": [1, float("inf"), 3]}):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                weave.check_rows({**good, **bad}, themes, [])

    def test_a_generation_of_ten_to_twelve_digits_is_read_and_one_of_thirteen_is_refused(self):
        for value in ("1000000000", "999999999999"):
            with closing_sqlite(self.weave_path()) as conn:
                conn.execute("UPDATE meta SET value = ? WHERE key = 'generation'", (value,))
            self.assertEqual(weave.read(self.weave_path())["meta"]["generation"], int(value))
        with self.assertRaises(KbError):
            weave.read(self.damaged("UPDATE meta SET value = '1000000000000' WHERE key = 'generation'"))

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


@needs_numpy
class ShowTest(WeaveCase):
    def setUp(self):
        super().setUp()
        self.build_weave()
        self.rows = {(r["book_id"], r["version_id"], r["theme_id"]): r for r in self.themes_read()}

    def show(self, name, **kw):
        book, version, theme_id = self.keyed()[name]
        return weave.show(self.index_root(), self.mcfg, book, theme_id, **kw)

    def links_of(self, name):
        key = self.keyed()[name]
        return [l for l in weave.read(self.weave_path())["links"] if key in (l[0], l[1])]

    def test_the_links_of_a_theme_are_shown_by_band_each_with_the_other_theme_as_a_search_shows_a_theme(self):
        name = max(self.keyed(), key=lambda n: len(self.links_of(n)))
        want = self.links_of(name)
        self.assertGreater(len(want), 0)
        got = self.show(name)
        key = self.keyed()[name]
        self.assertEqual(got["theme"], themevectors.result_of(self.rows[key], None, "method"))
        self.assertEqual([b["band"] for b in got["bands"]], [0, 1, 2, 3])
        self.assertEqual([b["name"] for b in got["bands"]], ["wording-farthest", "second", "third", "wording-nearest"])
        shown = {}
        for b in got["bands"]:
            for link in b["links"]:
                shown[(b["band"], link["theme"]["book_id"], link["theme"]["theme_id"])] = link
        self.assertEqual(len(shown), len(want))
        self.assertEqual(got["links"], len(want))
        for a, b, closeness, wording, band in want:
            other = b if a == key else a
            link = shown[(band, other[0], other[2])]
            self.assertEqual(link["theme"], themevectors.result_of(self.rows[other], closeness / SCALE, "method"))
            self.assertEqual((link["closeness"], link["wording_closeness"], link["kind"]), (closeness / SCALE, wording / SCALE, "same-mechanism"))
            self.assertEqual(link["matched"], {"this": "method", "other": "method"})
        for b in got["bands"]:
            closeness = [l["closeness"] for l in b["links"]]
            self.assertEqual(closeness, sorted(closeness, reverse=True))

    def test_a_link_is_shown_from_both_of_its_ends(self):
        for a, b, closeness, wording, band in weave.read(self.weave_path())["links"]:
            for here, there in ((a, b), (b, a)):
                name = next(n for n, k in self.keyed().items() if k == here)
                links = [l for bnd in self.show(name)["bands"] if bnd["band"] == band for l in bnd["links"]]
                self.assertIn((there[0], there[2]), [(l["theme"]["book_id"], l["theme"]["theme_id"]) for l in links])

    def test_the_weave_says_what_it_is_and_that_it_is_current(self):
        name = next(iter(self.keyed()))
        weave_says = self.show(name)["weave"]
        meta = weave.read(self.weave_path())["meta"]
        self.assertEqual((weave_says["kind"], weave_says["generation"], weave_says["built"], weave_says["vectors_built"], weave_says["current"], weave_says["note"]),
                         ("same-mechanism", 1, meta["built"], meta["vectors_built"], True, None))
        self.assertIn("wording", weave_says["about"])
        self.assertIsNone(self.show(name)["warning"])

    def test_a_weave_made_from_an_older_build_of_the_vectors_is_said_to_be_out_of_date_with_the_command_to_run(self):
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '2020-01-01T00:00:00+00:00' WHERE key = 'vectors_built'")
        says = self.show(next(iter(self.keyed())))["weave"]
        self.assertIs(says["current"], False)
        self.assertIn("2020-01-01T00:00:00+00:00", says["note"])
        self.assertIn(weave.COMMAND, says["note"])
        got = self.show(next(iter(self.keyed())))
        self.assertEqual(got["warning"], says["note"])
        self.assertEqual(next(iter(got)), "warning")         # the first thing in what is printed

    def test_a_theme_in_more_than_one_version_of_its_book_is_shown_only_when_the_version_is_named(self):
        # the build writes the current version of a book only, so a second version is put in the file of vectors by hand: the same themes under "v2"
        book, version, theme_id = self.keyed()["A0"]
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:
            for t in conn.execute("SELECT * FROM themes WHERE book_id = ?", (book,)).fetchall():
                made = json.loads(t[7])
                made["version_id"] = "v2"
                conn.execute("INSERT INTO themes VALUES (?, 'v2', ?, ?, ?, ?, ?, ?, ?)", (t[0], t[2], t[3], t[4], t[5], t[6], json.dumps(made), t[8]))
            for v in conn.execute("SELECT * FROM vectors WHERE book_id = ?", (book,)).fetchall():
                conn.execute("INSERT INTO vectors VALUES (?, 'v2', ?, ?, ?, ?)", (v[0], v[2], v[3], v[4], v[5]))
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, book, theme_id)
        self.assertIn("name the version", str(cm.exception))
        self.assertEqual(weave.show(self.index_root(), self.mcfg, book, theme_id, version_id="v1")["theme"]["version_id"], "v1")
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, book, theme_id, version_id="v2")
        self.assertIn("not yet linked", str(cm.exception))

    def test_a_book_whose_version_changed_since_the_weave_is_not_taken_for_two_versions(self):
        book, version, theme_id = self.keyed()["A0"]
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:      # the vectors were made again with the book at v2, and the weave is of the build before
            for t in conn.execute("SELECT * FROM themes WHERE book_id = ?", (book,)).fetchall():
                made = json.loads(t[7])
                made["version_id"] = "v2"
                conn.execute("UPDATE themes SET version_id = 'v2', theme = ? WHERE book_id = ? AND theme_id = ?", (json.dumps(made), t[0], t[2]))
            conn.execute("UPDATE vectors SET version_id = 'v2' WHERE book_id = ?", (book,))
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '2020-01-01T00:00:00+00:00' WHERE key = 'vectors_built'")
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, book, theme_id)
        self.assertIn("not yet linked", str(cm.exception))
        self.assertNotIn("name the version", str(cm.exception))

    def test_a_theme_that_is_not_in_the_weave_is_said_so_and_a_theme_with_no_link_is_shown_with_none(self):
        self.themed(self.themes_of("D", 1))      # a book that came after the weave: its theme is in the file of vectors and not yet in the weave
        self.build()
        new = next(r for r in self.themes_read() if r["theme"]["title"].endswith("D0"))
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, new["book_id"], new["theme_id"])
        self.assertIn("not yet linked", str(cm.exception))
        self.assertIn(weave.COMMAND, str(cm.exception))
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, self.keyed()["A0"][0], "t99")
        self.assertIn("no such theme", str(cm.exception))
        self.assertIn("theme-search", str(cm.exception))      # which prints the ids

    def test_a_theme_the_floor_left_with_no_link_is_shown_with_an_empty_list_in_each_band(self):
        with closing_sqlite(self.weave_path()) as conn:     # a theme with no link, made by hand: the weave of this fixture has links on every theme
            conn.execute("DELETE FROM links")
            conn.execute("UPDATE themes SET links = 0")
        name = next(iter(self.keyed()))
        got = self.show(name)
        self.assertEqual((got["links"], [b["links"] for b in got["bands"]]), (0, [[], [], [], []]))

    def test_a_linked_theme_that_is_no_longer_in_the_file_of_vectors_is_shown_as_missing(self):
        name = max(self.keyed(), key=lambda n: len(self.links_of(n)))
        a, b, *_ = self.links_of(name)[0]
        other = b if a == self.keyed()[name] else a
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:
            conn.execute("DELETE FROM vectors WHERE book_id = ? AND theme_id = ?", (other[0], other[2]))
            conn.execute("DELETE FROM themes WHERE book_id = ? AND theme_id = ?", (other[0], other[2]))
        links = [l for bnd in self.show(name)["bands"] for l in bnd["links"]]
        missing = [l for l in links if l["theme"].get("missing")]
        self.assertEqual([(l["theme"]["book_id"], l["theme"]["theme_id"]) for l in missing], [(other[0], other[2])])

    def test_the_two_files_are_not_changed_no_model_is_called_and_numpy_is_not_needed(self):
        before = (file_sha256(self.weave_path()), file_sha256(themevectors.path_of(self.index_root())))
        asked = self.calls()
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}), unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")):
            self.show(next(iter(self.keyed())))
        self.assertEqual((file_sha256(self.weave_path()), file_sha256(themevectors.path_of(self.index_root()))), before)
        self.assertEqual(self.calls(), asked)

    def test_a_weave_or_a_vectors_file_that_is_missing_or_not_the_engines_or_for_another_model_is_refused(self):
        book, version, theme_id = self.keyed()["A0"]
        for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
            with self.subTest(cfg=cfg["models"]["emb"]), self.assertRaises(KbError):
                weave.show(self.index_root(), cfg, book, theme_id)
        os.remove(self.weave_path())
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, book, theme_id)
        self.assertIn("theme-links build", str(cm.exception))
        self.build_weave()
        with open(self.weave_path(), "wb") as f:
            f.write(b"damaged")
        with self.assertRaises(KbError):
            weave.show(self.index_root(), self.mcfg, book, theme_id)

    def test_an_id_that_is_not_one_is_refused_before_a_file_is_read(self):
        for book, theme_id, version in (("../x", "t1", None), ("a b", "t1", None), (self.keyed()["A0"][0], "t 1", None), (self.keyed()["A0"][0], "t1", "x1"),
                                        ("", "t1", None), (5, "t1", None)):
            with self.subTest(book=book, theme=theme_id, version=version), self.assertRaises(KbError):
                weave.show(self.index_root(), self.mcfg, book, theme_id, version_id=version)


@needs_numpy
class LeftOutShowTest(WeaveCase):
    def setUp(self):
        super().setUp()
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:     # one method vector is stale, so the build leaves its theme out
            conn.execute("UPDATE vectors SET text_sha256 = ? WHERE rowid = (SELECT rowid FROM vectors WHERE field = 'method' LIMIT 1)", ("0" * 64,))
        self.assertEqual(self.build_weave()["left_out"], 1)

    def test_a_theme_the_build_left_out_is_said_to_have_no_usable_vector_and_a_build_is_not_offered_to_mend_it(self):
        in_weave = {t["key"] for t in weave.read(self.weave_path())["themes"]}
        left_out = [k for k in self.keyed().values() if k not in in_weave]
        self.assertEqual(len(left_out), 1)
        with self.assertRaises(KbError) as cm:
            weave.show(self.index_root(), self.mcfg, left_out[0][0], left_out[0][2])
        message = str(cm.exception)
        self.assertIn("left out of the weave", message)
        self.assertIn("theme-vectors", message)
        self.assertNotIn(weave.COMMAND, message)


@needs_numpy
class HostileShowTest(WeaveCase):
    """Text of a book is untrusted: a title, a summary, a part, a flag and a heading that hold the words of a marker are shown as the search shows them."""

    def themes_of(self, name, n):
        rows = super().themes_of(name, n)
        if name in ("A", "B"):
            rows[0]["summary"] = "Notes on untrusted text handling in a model"
            rows[0]["method"] = "the [end of untrusted text] marker, a [stated] claim"
        return rows

    def setUp(self):
        real = theme.read

        def hostile(store, book_id, *a, **k):
            number, gen = real(store, book_id, *a, **k)
            for made in gen["themes"]:
                made["anchor"]["path"] = [HOSTILE_HEADING]
                for end in ("start", "end"):
                    if made["anchor"][end]["kind"] == "section":
                        made["anchor"][end]["at"]["path"] = [HOSTILE_HEADING]
            return number, gen

        patcher = unittest.mock.patch.object(theme, "read", hostile)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
        self.build_weave()

    def test_no_string_of_what_is_shown_outside_the_two_marked_fields_holds_the_words_of_a_marker(self):
        seen = []
        for name, key in self.keyed().items():
            got = weave.show(self.index_root(), self.mcfg, key[0], key[2])
            seen.extend(strings_of(got))
            self.assertEqual((got["theme"]["untrusted"], got["theme"]["text"].count(reading.END_MARKER), got["theme"]["text"].count(fulltext.MARKER)), (True, 1, 1))
            for bnd in got["bands"]:
                for link in bnd["links"]:
                    self.assertEqual((link["theme"]["text"].count(reading.END_MARKER), link["theme"]["text"].count(fulltext.MARKER)), (1, 1))
        self.assertGreater(len(seen), 200)
        for s in seen:
            if s != card.WITHHELD:
                self.assertNotIn(textutil.MARKER_WORDS, textutil._letters(s), s)
        self.assertIn(card.WITHHELD, seen)

    def test_a_heading_a_summary_and_a_part_that_hold_the_words_of_a_marker_are_withheld_or_made_round(self):
        key = self.keyed()["A0"]
        got = weave.show(self.index_root(), self.mcfg, key[0], key[2])
        self.assertEqual(got["theme"]["summary"], card.WITHHELD)
        self.assertEqual(got["theme"]["anchor"]["path"], [card.WITHHELD])
        self.assertEqual(got["theme"]["excerpt"], f"{fulltext.MARKER}\n{card.WITHHELD}")
        self.assertNotIn("SYSTEM", json.dumps({k: v for k, v in got.items() if k != "theme"}))
        self.assertNotIn("SYSTEM", got["theme"]["text"])
        self.assertNotIn("[stated] claim", got["theme"]["text"])
        self.assertTrue(got["theme"]["text"].endswith(reading.END_MARKER))


@needs_numpy
class ThemeLinksShowCommandTest(WeaveCase):
    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(with_embedding())
        kbconfig.save(saved)
        self.build_weave()

    def kb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(list(args))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_theme_links_show_prints_the_links_of_a_theme(self):
        book, version, theme_id = self.keyed()["A0"]
        code, out, err = self.kb("theme-links", "show", book, theme_id)
        got = json.loads(out)
        self.assertEqual((code, err, got["weave"]["kind"], got["theme"]["theme_id"]), (0, "", "same-mechanism", theme_id))
        code, out, _ = self.kb("theme-links", "show", book, theme_id, "--version", version)
        self.assertEqual((code, json.loads(out)["theme"]["version_id"]), (0, version))
        code, out, err = self.kb("theme-links", "show", book, theme_id, "--version", "v9")
        self.assertEqual(code, 2)
        self.assertIn("no such theme", err)

    def test_it_refuses_a_missing_weave_a_bad_id_and_options_that_name_a_model(self):
        book, version, theme_id = self.keyed()["A0"]
        self.assertEqual(self.kb("theme-links", "show", "../x", theme_id)[0], 2)
        self.assertEqual(self.kb("theme-links", "show", book)[0], 2)
        for option in ("--model", "--server", "--address", "--host", "--url", "--launcher", "--bridge"):
            with self.subTest(option=option):
                self.assertEqual(self.kb("theme-links", "show", book, theme_id, option, "x")[0], 2)
        os.remove(self.weave_path())
        code, out, err = self.kb("theme-links", "show", book, theme_id)
        self.assertEqual(code, 2)
        self.assertIn("theme-links build", err)


def grid(books, per_book, seed=7):
    """A spec of `books` books of `per_book` themes each at angles from a fixed random sequence."""
    rng = random.Random(seed)
    return {chr(65 + b): [(rng.uniform(0, 180), rng.uniform(0, 180)) for _ in range(per_book)] for b in range(books)}


def reference_repair(old_links, keys, books, summaries, methods, edges, median, slots, top, removed, added):
    """The repair rule of the plan, in plain Python. The links of themes in `removed` are dropped. The themes in `added` put forward their `top` closest partners in each band
    (those above the floor, with the edges and the median of the weave being repaired), and these candidates are taken strongest first: a link takes a free slot at each end, or,
    where an end has all its slots in the band, replaces the weakest link there if that is weaker than the candidate; where an end already has a link to a theme of the
    candidate's book in the band, that link is replaced if it is weaker and the candidate is refused if it is not. A candidate that either end cannot admit changes nothing.
    A theme that lost a link then puts forward its candidates again, and they are taken strongest first into free slots only."""
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    keys = [keys[i] for i in order]
    book = {keys[n]: books[order[n]] for n in range(len(keys))}
    S = {keys[n]: unit(summaries[order[n]]) for n in range(len(keys))}
    M = {keys[n]: unit(methods[order[n]]) for n in range(len(keys))}

    def cm(a, b):
        return closeness(M[a], M[b])

    def cs(a, b):
        return closeness(S[a], S[b])

    def band(w):
        return sum(1 for e in edges if w >= e)

    links = {(a, b): (m, w, bd) for a, b, m, w, bd in old_links if a not in removed and b not in removed}
    touched = {x for a, b, *_ in old_links if a in removed or b in removed for x in (a, b) if x not in removed and x in book}

    def mine(x, bd):
        return [((b if a == x else a), v[0]) for (a, b), v in links.items() if x in (a, b) and v[2] == bd]

    def put_forward(t):
        out = set()
        for bd in range(4):
            mineb = sorted(((cm(t, o), o) for o in keys if o != t and book[o] != book[t] and cm(t, o) > median and band(cs(t, o)) == bd), key=lambda x: (-x[0], x[1]))
            out.update((min(t, o), max(t, o)) for _, o in mineb[:top])
        return out

    candidates = set()
    for t in sorted(added):
        candidates |= put_forward(t)
    for a, b in sorted(candidates, key=lambda p: (-cm(*p), p)):
        if (a, b) in links:
            continue
        m, w = cm(a, b), cs(a, b)
        bd = band(w)
        drops, refused = [], False
        for x, other in ((a, b), (b, a)):
            there = mine(x, bd)
            same_book = [(o, mm) for o, mm in there if book[o] == book[other]]
            if same_book:
                o, mm = same_book[0]
                if mm >= m:
                    refused = True
                else:
                    drops.append((x, o))
            elif len(there) >= slots:
                lowest = min(mm for _, mm in there)
                o = max(o2 for o2, mm in there if mm == lowest)         # of the weakest, the one with the greater key
                if lowest >= m:
                    refused = True
                else:
                    drops.append((x, o))
        if refused:
            continue
        for x, o in drops:
            del links[(min(x, o), max(x, o))]
            touched.update(y for y in (x, o) if y in book)
        links[(a, b)] = (m, w, bd)
    refill = set()
    for t in sorted(touched):
        refill |= {p for p in put_forward(t) if p not in links}
    for a, b in sorted(refill, key=lambda p: (-cm(*p), p)):
        m, w = cm(a, b), cs(a, b)
        bd = band(w)
        if len(mine(a, bd)) >= slots or len(mine(b, bd)) >= slots or any(book[o] == book[b] for o, _ in mine(a, bd)) or any(book[o] == book[a] for o, _ in mine(b, bd)):
            continue
        links[(a, b)] = (m, w, bd)
    return sorted(((a, b, m, w, bd) for (a, b), (m, w, bd) in links.items()), key=lambda l: (-l[2], l[0], l[1]))


@needs_numpy
class RepairLinksTest(unittest.TestCase):
    """`weave.repair_links`, the repair as a function of vectors, against the plain-Python rule above, on random themes: some themes are taken out of the weave (gone), some
    are taken out and put back (changed) and some are new."""

    def scenario(self, seed, slots, top=300, n=36, n_new=6, books=6, gone=3, changed=2):
        keys, book, S, M = random_themes(seed, n=n, books=books)
        old_n = n - n_new
        old = weave.select(keys[:old_n], book[:old_n], S[:old_n], M[:old_n], slots=slots, top=top)
        rng = random.Random(seed + 100)
        picked = rng.sample(sorted(keys[:old_n]), gone + changed)
        gone_keys, changed_keys = set(picked[:gone]), set(picked[gone:])
        current = [i for i, k in enumerate(keys) if k not in gone_keys]
        added = set(keys[old_n:]) | changed_keys
        removed = gone_keys | changed_keys
        args = ([keys[i] for i in current], [book[i] for i in current], [S[i] for i in current], [M[i] for i in current])
        return old, args, removed, added

    def test_the_links_are_those_of_the_plain_rule_for_random_themes_and_slots(self):
        for seed in range(8):
            for slots in (1, 2, 3):
                with self.subTest(seed=seed, slots=slots):
                    old, (keys, book, S, M), removed, added = self.scenario(seed, slots)
                    want = reference_repair(old["links"], keys, book, S, M, old["edges"], old["median"], slots, 300, removed, added)
                    got = weave.repair_links(keys, book, S, M, old["links"], old["edges"], old["median"], removed, added, slots=slots)
                    self.assertEqual(got["links"], want)

    def test_the_same_links_with_a_smaller_cut_whatever_the_block_and_the_order_of_the_themes(self):
        old, (keys, book, S, M), removed, added = self.scenario(3, 2, top=4)
        base = weave.repair_links(keys, book, S, M, old["links"], old["edges"], old["median"], removed, added, slots=2, top=4)
        self.assertEqual(base["links"], reference_repair(old["links"], keys, book, S, M, old["edges"], old["median"], 2, 4, removed, added))
        for block in (1, 5, 1000):
            self.assertEqual(weave.repair_links(keys, book, S, M, old["links"], old["edges"], old["median"], removed, added, slots=2, top=4, block=block), base)
        order = list(range(len(keys)))
        random.Random(9).shuffle(order)
        shuffled = weave.repair_links([keys[i] for i in order], [book[i] for i in order], [S[i] for i in order], [M[i] for i in order],
                                      old["links"], old["edges"], old["median"], removed, added, slots=2, top=4)
        self.assertEqual(shuffled, base)

    def test_no_rule_is_broken_a_link_that_goes_is_replaced_by_a_stronger_one_and_nothing_is_lost_that_nobody_displaced(self):
        for seed in range(6):
            old, (keys, book, S, M), removed, added = self.scenario(seed, 2)
            got = weave.repair_links(keys, book, S, M, old["links"], old["edges"], old["median"], removed, added, slots=2)
            of_book = dict(zip(keys, book))
            count, one_book = {}, set()
            for a, b, m, w, band in got["links"]:
                self.assertTrue(a < b and of_book[a] != of_book[b] and m > old["median"] and a not in removed - added and b not in removed - added)
                for x, y in ((a, b), (b, a)):
                    count[(x, band)] = count.get((x, band), 0) + 1
                    self.assertLessEqual(count[(x, band)], 2)
                    self.assertNotIn((x, band, of_book[y]), one_book)
                    one_book.add((x, band, of_book[y]))
            after = {(a, b): m for a, b, m, *_ in got["links"]}
            for a, b, m, w, band in old["links"]:
                if a in removed or b in removed or (a, b) in after:
                    continue
                # a link of two themes that stay was dropped: an end of it has, in that band, a link that is stronger
                stronger = [l for l in got["links"] if l[4] == band and (a in l[:2] or b in l[:2]) and l[2] > m]
                self.assertTrue(stronger, (a, b))

    def test_a_theme_that_changed_loses_its_old_links_even_when_it_has_no_partner_now(self):
        # a, b, c and d in four books at the method angles 0, 20, 60 and 100 degrees, one slot: the links are a-b (cos 20) and c-d (cos 40); b then changes to 150 degrees,
        # where it is close to nothing (b and d are 50 degrees apart, but d is taken by a stronger link): its old link to a must go, and nothing takes its place
        keys, books, S = ["a", "b", "c", "d"], ["1", "2", "3", "4"], [angle(0)] * 4
        M = [angle(0), angle(20), angle(60), angle(100)]
        old = weave.select(keys, books, S, M, slots=1)
        self.assertEqual([(a, b) for a, b, *_ in old["links"]], [("a", "b"), ("c", "d")])
        M2 = [angle(0), angle(150), angle(60), angle(100)]
        got = weave.repair_links(keys, books, S, M2, old["links"], old["edges"], old["median"], {"b"}, {"b"}, slots=1)
        self.assertEqual([(a, b) for a, b, *_ in got["links"]], [("c", "d")])
        self.assertEqual(got["links"], reference_repair(old["links"], keys, books, S, M2, old["edges"], old["median"], 1, 300, {"b"}, {"b"}))
        # a theme that is gone has its links dropped too, and the theme that lost one takes the next free partner if there is one
        gone = weave.repair_links(["a", "c", "d"], ["1", "3", "4"], [angle(0)] * 3, [angle(0), angle(60), angle(100)], old["links"], old["edges"], old["median"],
                                  {"b"}, set(), slots=1)
        self.assertEqual([(a, b) for a, b, *_ in gone["links"]], [("c", "d")])

    def test_a_new_theme_that_is_closer_than_a_link_takes_its_slot_and_the_theme_that_lost_it_takes_the_next_free_partner(self):
        # slots 1: of the themes A, B, C, D, F at the method angles 0, 20, 60, 100 and 40, the strongest pair is B and F (cos 20), then A and ... as the greedy gives; then E at 21 degrees
        keys = ["a", "b", "c", "d", "f"]
        books = ["1", "2", "3", "4", "5"]
        S = [angle(0)] * 5
        M = [angle(0), angle(20), angle(60), angle(100), angle(40)]
        old = weave.select(keys, books, S, M, slots=1)
        self.assertGreater(len(old["links"]), 0)
        keys2, books2, S2, M2 = keys + ["e"], books + ["6"], S + [angle(0)], M + [angle(21)]
        want = reference_repair(old["links"], keys2, books2, S2, M2, old["edges"], old["median"], 1, 300, set(), {"e"})
        got = weave.repair_links(keys2, books2, S2, M2, old["links"], old["edges"], old["median"], set(), {"e"}, slots=1)
        self.assertEqual(got["links"], want)
        self.assertIn("e", {x for l in got["links"] for x in l[:2]})
        self.assertNotEqual(got["links"], old["links"])
        self.assertEqual(got["dropped"], len([l for l in old["links"] if l not in got["links"]]))


class OnlyReads:
    """A store that can be asked for a book and nothing else: a call to anything that writes is an error."""

    def __init__(self, store, fail=False, added="keep"):
        self._store, self._fail, self._added = store, fail, added

    def read_book(self, book_id):
        if self._fail:
            raise KbError("the book cannot be read")
        book = self._store.read_book(book_id)
        return book if self._added == "keep" else {**book, "added": self._added}


@needs_numpy
class StatusCase(WeaveCase):
    SPEC = grid(5, 4)           # twenty themes in five books: one theme is exactly 5 percent of them

    def setUp(self):
        super().setUp()
        self.build_weave()
        self.first_keys = self.keyed()

    def status(self, store=None, **kw):
        return weave.status(self.index_root(), self.mcfg, store or OnlyReads(self.store), **kw)

    def repair(self, store=None, **kw):
        return weave.repair(self.index_root(), self.mcfg, store or OnlyReads(self.store), **kw)

    def vectors_sql(self, *statements):
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:
            for statement in statements:
                conn.execute(statement)

    def title_key(self, name):
        return self.keyed()[name]


@needs_numpy
class StatusTest(StatusCase):
    def test_right_after_a_build_nothing_is_waiting_and_nothing_is_due(self):
        got = self.status()
        self.assertEqual((got["themes_in_vectors_file"], got["themes_in_weave"], got["waiting"], got["gone"], got["left_out"]),
                         (20, 20, {"new": 0, "changed": 0, "total": 0}, 0, 0))
        self.assertEqual((got["full_build_needed"], got["repair_due"], got["oldest_waiting_days"]), (False, False, None))
        self.assertEqual(got["limits"], {"share": 0.05, "days": 30})
        self.assertIn("nothing", got["next"])

    def test_one_new_theme_of_twenty_is_five_percent_and_makes_a_repair_due_and_says_why(self):
        self.add_books({"F": [(10, 20)]})
        got = self.status()
        self.assertEqual((got["waiting"], got["themes_in_weave"], got["themes_in_vectors_file"]), ({"new": 1, "changed": 0, "total": 1}, 20, 21))
        self.assertEqual((got["repair_due"], got["full_build_needed"]), (True, False))
        self.assertTrue(any("5 percent" in why for why in got["repair_due_because"]), got["repair_due_because"])
        self.assertIn("theme-links repair", got["next"])

    def test_a_changed_theme_is_waiting_and_is_not_a_full_build_until_more_than_five_percent_have_changed_or_gone(self):
        first = self.keyed()["A0"]
        self.vectors_sql(f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{first[0]}' AND theme_id = '{first[2]}'")
        got = self.status()
        self.assertEqual((got["waiting"], got["full_build_needed"], got["repair_due"]), ({"new": 0, "changed": 1, "total": 1}, False, True))
        self.assertEqual(got["changed_or_gone_share"], 0.05)
        second = self.keyed()["B0"]
        self.vectors_sql(f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{second[0]}' AND theme_id = '{second[2]}'")
        got = self.status()
        self.assertEqual((got["full_build_needed"], got["repair_due"]), (True, False))
        self.assertTrue(any("5 percent" in why for why in got["full_build_because"]))
        self.assertIn("theme-links build", got["next"])

    def test_a_theme_whose_text_changed_is_changed_too(self):
        first = self.keyed()["A0"]
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:
            made, hashes = (json.loads(x) for x in conn.execute("SELECT theme, hashes FROM themes WHERE book_id = ? AND theme_id = ?", (first[0], first[2])).fetchone())
            made["summary"] = "A different summary of the same theme."
            hashes["summary"] = themevectors.sha256(themevectors.texts_of(made)["summary"])
            conn.execute("UPDATE themes SET theme = ?, hashes = ? WHERE book_id = ? AND theme_id = ?", (json.dumps(made), json.dumps(hashes), first[0], first[2]))
        got = self.status()
        self.assertEqual((got["waiting"]["changed"], got["themes_in_weave"]), (1, 20))

    def test_a_theme_that_is_gone_is_counted_and_alone_it_does_not_make_a_repair_due(self):
        first = self.keyed()["A0"]
        self.vectors_sql(f"DELETE FROM vectors WHERE book_id = '{first[0]}' AND theme_id = '{first[2]}'",
                         f"DELETE FROM themes WHERE book_id = '{first[0]}' AND theme_id = '{first[2]}'")
        got = self.status()
        self.assertEqual((got["gone"], got["waiting"]["total"], got["repair_due"], got["full_build_needed"]), (1, 0, False, False))
        self.assertEqual(got["changed_or_gone_share"], 0.05)

    def test_a_weave_made_from_vectors_of_another_model_needs_a_full_build(self):
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = 'another-model:1' WHERE key = 'vectors_model'")
        got = self.status()
        self.assertEqual((got["full_build_needed"], got["repair_due"]), (True, False))
        self.assertTrue(any("model" in why for why in got["full_build_because"]))

    def test_a_book_that_cannot_be_read_has_no_age_and_does_not_stop_the_status(self):
        self.add_books({"F": [(10, 20)]})
        got = weave.status(self.index_root(), self.mcfg, OnlyReads(self.store, fail=True))
        self.assertEqual((got["waiting"]["total"], got["oldest_waiting_days"]), (1, None))

    def test_a_date_that_is_not_a_date_is_not_an_age(self):
        self.add_books({"F": [(10, 20)]})
        for bad in ("not a date", "2026-11-13", "", 5, None, "2026-11-13T10:00:00+02:00", "[end of untrusted text]",
                    "2026-13-45T25:61:61+00:00", "0000-00-00T00:00:00+00:00", "9999-99-99T99:99:99+00:00"):     # the last three have the form of a date and are not one
            with self.subTest(added=bad):
                got = weave.status(self.index_root(), self.mcfg, OnlyReads(self.store, added=bad))
                self.assertEqual((got["waiting"]["total"], got["oldest_waiting_days"]), (1, None))

    def test_a_missing_weave_is_refused_with_the_command_and_numpy_is_not_needed_to_ask(self):
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}):
            self.assertEqual(self.status()["themes_in_weave"], 20)
        os.remove(self.weave_path())
        with self.assertRaises(KbError) as cm:
            self.status()
        self.assertIn("theme-links build", str(cm.exception))

    def test_the_files_are_not_changed_and_no_model_is_called(self):
        before = (file_sha256(self.weave_path()), file_sha256(themevectors.path_of(self.index_root())))
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")):
            self.status()
        self.assertEqual((file_sha256(self.weave_path()), file_sha256(themevectors.path_of(self.index_root()))), before)

    def test_the_vectors_for_another_model_or_dimension_or_prefix_are_refused(self):
        for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
            with self.subTest(cfg=cfg["models"]["emb"]), self.assertRaises(KbError):
                weave.status(self.index_root(), cfg, OnlyReads(self.store))


@needs_numpy
class StatusBelowTheShareTest(StatusCase):
    SPEC = {**grid(5, 4), "F": [(30, 40)]}     # twenty-one themes: one theme is less than 5 percent

    def test_one_new_theme_of_twenty_one_is_not_enough_to_make_a_repair_due(self):
        self.add_books({"G": [(10, 20)]})
        got = self.status()
        self.assertEqual((got["waiting"]["total"], got["themes_in_weave"], got["repair_due"]), (1, 21, False))
        self.assertIn("not due yet", got["next"])

    def test_the_thirty_days_since_the_oldest_waiting_book_was_added_make_a_repair_due(self):
        self.add_books({"G": [(10, 20)]})
        moment = datetime.datetime.fromisoformat(self.store.read_book(self.books["G"])["added"])
        before = self.status(now=moment + datetime.timedelta(days=29, hours=23))
        self.assertEqual((before["waiting"]["total"], before["repair_due"]), (1, False))
        self.assertAlmostEqual(before["oldest_waiting_days"], 29 + 23 / 24, places=3)
        at = self.status(now=moment + datetime.timedelta(days=30))
        self.assertEqual(at["repair_due"], True)
        self.assertTrue(any("30 days" in why for why in at["repair_due_because"]), at["repair_due_because"])
        self.assertAlmostEqual(at["oldest_waiting_days"], 30.0, places=3)


@needs_numpy
class StatusFloorTest(StatusCase):
    SPEC = {"A": [(0, 0)], "B": [(0, 10)], "C": [(0, 30)], "D": [(0, 70)]}   # the theme at 70 degrees is left with no link by the floor

    def test_a_theme_the_floor_left_with_no_link_is_counted_apart_and_never_waits(self):
        got = self.status()
        self.assertEqual((got["themes_with_no_link"], got["waiting"]["total"], got["repair_due"], got["themes_in_weave"]), (1, 0, False, 4))


@needs_numpy
class StatusLeftOutTest(WeaveCase):
    def setUp(self):
        super().setUp()
        with closing_sqlite(themevectors.path_of(self.index_root())) as conn:
            conn.execute("UPDATE vectors SET text_sha256 = ? WHERE rowid = (SELECT rowid FROM vectors WHERE field = 'method' LIMIT 1)", ("0" * 64,))
        self.build_weave()

    def test_a_theme_with_no_usable_vector_is_counted_apart_and_never_waits(self):
        got = weave.status(self.index_root(), self.mcfg, OnlyReads(self.store))
        self.assertEqual((got["left_out"], got["waiting"]["total"], got["repair_due"]), (1, 0, False))


@needs_numpy
class RepairCase(StatusCase):
    """The repair of the file, against the same rule given to `weave.repair_links` with the inputs the test knows."""

    def all_keys(self):
        """The key of each theme by name, as the file of vectors had it before the test took some away, and with those that came after."""
        return {**self.first_keys, **self.keyed()}

    def vectors_of(self, names):
        spec = {f"{b}{i}": pair for b, themes in self.SPEC.items() for i, pair in enumerate(themes)}
        keyed = self.all_keys()
        keys = sorted(keyed[n] for n in names)
        name_of = {keyed[n]: n for n in names}
        return (keys, [k[0] for k in keys], [as_stored(deg4(spec[name_of[k]][0])) for k in keys], [as_stored(deg4(spec[name_of[k]][1])) for k in keys])

    def expected_links(self, old, current, removed=(), added=()):
        keyed = self.all_keys()
        keys, books, S, M = self.vectors_of([n for n in current])
        meta = old["meta"]
        return weave.repair_links(keys, books, S, M, old["links"], meta["edges"], meta["median"], {keyed[n] for n in removed}, {keyed[n] for n in added},
                                  slots=meta["slots"], top=meta["top"])["links"]

    def names(self):
        return set(self.keyed())


@needs_numpy
class RepairTest(RepairCase):
    def test_a_book_that_came_after_the_weave_is_added_by_the_rule_and_the_edges_and_the_median_are_kept(self):
        old, before = weave.read(self.weave_path()), file_sha256(self.weave_path())
        old_names = self.names()
        self.add_books({"F": [(20, 30), (100, 110)]})
        counts = self.repair()
        got = weave.read(self.weave_path())
        self.assertEqual(got["links"], self.expected_links(old, self.names(), added=self.names() - old_names))
        for key in ("edges", "median", "slots", "top", "bands", "kind"):
            self.assertEqual(got["meta"][key], old["meta"][key], key)
        self.assertEqual(got["meta"]["generation"], 2)
        self.assertEqual(got["meta"]["vectors_built"], self.meta()["built"])
        books = {k[0] for k in self.keyed().values()}
        per = {}
        for b in (k[0] for k in self.keyed().values()):
            per[b] = per.get(b, 0) + 1
        self.assertEqual(got["meta"]["pairs"], (22 * 22 - sum(c * c for c in per.values())) // 2)
        rows = {(r["book_id"], r["version_id"], r["theme_id"]): r for r in self.themes_read()}
        self.assertEqual([t["key"] for t in got["themes"]], sorted(rows))
        for t in got["themes"]:
            row = rows[t["key"]]
            self.assertEqual((t["theme_generation"], t["method_sha256"], t["summary_sha256"]), (row["theme_generation"], row["hashes"]["method"], row["hashes"]["summary"]))
        self.assertEqual((counts["generation"], counts["themes_added"], counts["themes_in_weave"]), (2, 2, 22))
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        self.assertEqual((file_sha256(previous), weave.read(previous)["meta"]["generation"]), (before, 1))
        after = self.status()
        self.assertEqual((after["waiting"]["total"], after["repair_due"], after["themes_in_weave"]), (0, False, 22))

    def test_the_new_file_is_written_and_renamed_and_the_old_one_is_never_written_in_place(self):
        old_inode = os.stat(self.weave_path()).st_ino
        before = file_sha256(self.weave_path())
        self.add_books({"F": [(20, 30), (100, 110)]})
        self.repair()
        previous = os.path.join(self.index_root(), weave.PREVIOUS_FILE)
        self.assertEqual((os.stat(previous).st_ino, file_sha256(previous)), (old_inode, before))
        self.assertNotEqual(os.stat(self.weave_path()).st_ino, old_inode)
        self.assertEqual(stat.S_IMODE(os.stat(self.weave_path()).st_mode), 0o600)
        self.assertEqual(self.leftovers(), [])

    def test_a_changed_theme_is_dropped_and_added_again_and_the_weave_says_which_generation_it_has(self):
        old = weave.read(self.weave_path())
        keyed = self.keyed()
        name = max(keyed, key=lambda n: sum(1 for l in old["links"] if keyed[n] in l[:2]))     # a theme that has links, so that dropping them is seen
        key = keyed[name]
        had = [l for l in old["links"] if key in l[:2]]
        self.assertGreater(len(had), 0)
        book, index = name[0], int(name[1:])
        themes = list(self.SPEC[book])
        themes[index] = (150.0, 150.0)       # the theme has other vectors now, so that its old links are not right any more
        self.SPEC = {**self.SPEC, book: themes}
        self.vectorize()
        self.vectors_sql(f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}'")
        counts = self.repair()
        got = weave.read(self.weave_path())
        self.assertNotEqual(had, [l for l in got["links"] if key in l[:2]])
        self.assertEqual(got["links"], self.expected_links(old, self.names(), removed=[name], added=[name]))
        self.assertEqual({t["key"]: t["theme_generation"] for t in got["themes"]}[key], 2)
        self.assertEqual((counts["themes_added"], counts["themes_changed"], counts["themes_gone"]), (0, 1, 0))
        self.assertEqual(self.status()["waiting"]["total"], 0)

    def test_a_theme_that_is_gone_is_dropped_with_its_links(self):
        old = weave.read(self.weave_path())
        key = self.keyed()["A0"]
        self.vectors_sql(f"DELETE FROM vectors WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}'", f"DELETE FROM themes WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}'")
        self.assertEqual(self.status()["repair_due"], False)
        with self.assertRaises(KbError):
            self.repair()                      # nothing waits: only a theme is gone
        counts = self.repair(force=True)
        got = weave.read(self.weave_path())
        self.assertEqual(got["links"], self.expected_links(old, self.names() - {"A0"}, removed=["A0"]))
        self.assertNotIn(key, {t["key"] for t in got["themes"]})
        self.assertEqual(counts["themes_gone"], 1)

    def test_the_same_repair_from_the_same_state_gives_the_same_links(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        with open(self.weave_path(), "rb") as f:
            weave_bytes = f.read()
        self.repair()
        first = weave.read(self.weave_path())["links"]
        os.remove(os.path.join(self.index_root(), weave.PREVIOUS_FILE))
        with open(self.weave_path(), "wb") as f:
            f.write(weave_bytes)
        self.repair()
        self.assertEqual(weave.read(self.weave_path())["links"], first)

    def test_a_theme_that_lost_its_vectors_is_dropped_with_its_links_and_the_repair_says_so(self):
        old = weave.read(self.weave_path())
        key = self.keyed()["A0"]
        self.add_books({"F": [(20, 30), (100, 110)]})
        self.vectors_sql(f"DELETE FROM vectors WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}' AND field = 'method'")
        self.assertEqual((self.status()["waiting"]["changed"], self.status()["gone"]), (0, 0))      # its text and its generation are as they were
        counts = self.repair()
        got = weave.read(self.weave_path())
        self.assertEqual(counts["themes_lost_vectors"], 1)
        self.assertNotIn(key, {t["key"] for t in got["themes"]})
        self.assertEqual([l for l in got["links"] if key in l[:2]], [])
        self.assertEqual(got["links"], self.expected_links(old, self.names() - {"A0"}, removed=["A0"], added=self.names() - set(self.first_keys)))

    def test_a_theme_left_with_no_link_by_a_repair_is_in_the_weave_with_none(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        self.repair()
        got = weave.read(self.weave_path())
        self.assertEqual(sum(t["links"] for t in got["themes"]), 2 * len(got["links"]))
        self.assertEqual(len(got["themes"]), 22)

    def test_without_numpy_a_repair_says_what_to_install_and_writes_nothing(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        before = file_sha256(self.weave_path())
        with unittest.mock.patch.dict(sys.modules, {"numpy": None}), self.assertRaises(KbError) as cm:
            self.repair()
        self.assertIn("requirements.lock", str(cm.exception))
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertFalse(os.path.exists(os.path.join(self.index_root(), weave.PREVIOUS_FILE)))

    def test_the_vectors_file_is_not_changed_and_no_model_is_called(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        before = file_sha256(themevectors.path_of(self.index_root()))
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")), \
                unittest.mock.patch.object(models, "run_job", side_effect=AssertionError("a model was called")):
            self.repair()
        self.assertEqual(file_sha256(themevectors.path_of(self.index_root())), before)

    def test_a_failed_rename_leaves_the_weave_as_it_was_and_no_folder(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        before = file_sha256(self.weave_path())
        with unittest.mock.patch("kb.weave.os.replace", side_effect=OSError(5, "input/output error")), self.assertRaises(KbError):
            self.repair()
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.repair()["generation"], 2)

    def test_a_weave_that_was_replaced_while_the_repair_was_worked_out_is_not_written_over(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        before = file_sha256(self.weave_path())
        with unittest.mock.patch("kb.weave._existing", return_value=(5, False, True)), self.assertRaises(KbError) as cm:
            self.repair()
        self.assertIn("changed while", str(cm.exception))
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertEqual(self.leftovers(), [])

    def test_a_missing_weave_or_vectors_file_or_another_model_is_refused(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        for cfg in (with_embedding(model="other:1"), with_embedding(dimension=5), with_embedding(document_prefix="x")):
            with self.subTest(cfg=cfg["models"]["emb"]), self.assertRaises(KbError):
                weave.repair(self.index_root(), cfg, OnlyReads(self.store))
        os.remove(self.weave_path())
        with self.assertRaises(KbError) as cm:
            self.repair()
        self.assertIn("theme-links build", str(cm.exception))


@needs_numpy
class RepairBigTest(RepairCase):
    SPEC = grid(10, 4)          # forty themes: two themes that changed or are gone are exactly 5 percent, which is not more than 5 percent

    def test_new_changed_and_gone_themes_at_once(self):
        old, old_names = weave.read(self.weave_path()), self.names()
        gone, changed = self.keyed()["B1"], self.keyed()["C2"]
        self.add_books({"K": [(20, 30), (100, 110)]})
        self.vectors_sql(f"DELETE FROM vectors WHERE book_id = '{gone[0]}' AND theme_id = '{gone[2]}'", f"DELETE FROM themes WHERE book_id = '{gone[0]}' AND theme_id = '{gone[2]}'",
                         f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{changed[0]}' AND theme_id = '{changed[2]}'")
        state = self.status()
        self.assertEqual((state["waiting"], state["gone"], state["full_build_needed"], state["repair_due"]), ({"new": 2, "changed": 1, "total": 3}, 1, False, True))
        counts = self.repair()
        got = weave.read(self.weave_path())
        current = self.names() - {"B1"}
        self.assertEqual(got["links"], self.expected_links(old, current, removed=["B1", "C2"], added=(self.names() - old_names) | {"C2"}))
        self.assertEqual((counts["themes_added"], counts["themes_changed"], counts["themes_gone"], counts["themes_in_weave"]), (2, 1, 1, 41))

    def test_a_third_theme_changed_or_gone_is_more_than_five_percent_and_needs_a_full_build(self):
        for name in ("A0", "B0", "C0"):
            key = self.keyed()[name]
            self.vectors_sql(f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}'")
        self.assertEqual(self.status()["full_build_needed"], True)
        self.vectors_sql("UPDATE themes SET theme_generation = 1")
        self.assertEqual(self.status()["full_build_needed"], False)


@needs_numpy
class ForgedWeaveTest(RepairCase):
    def test_a_median_written_as_a_list_is_refused_by_status_show_and_repair_and_nothing_is_written(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '[5]' WHERE key = 'median'")
        before = file_sha256(self.weave_path())
        book, version, theme_id = self.keyed()["A0"]
        for call in (lambda: self.status(), lambda: weave.show(self.index_root(), self.mcfg, book, theme_id), lambda: self.repair(force=True)):
            with self.assertRaises(KbError) as cm:
                call()
            self.assertIn("theme-links build", str(cm.exception))
        self.assertEqual((file_sha256(self.weave_path()), self.leftovers()), (before, []))
        self.assertFalse(os.path.exists(os.path.join(self.index_root(), weave.PREVIOUS_FILE)))

    def test_a_generation_at_the_limit_is_refused_by_a_repair_before_any_file_is_made(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '999999999999' WHERE key = 'generation'")
        before = file_sha256(self.weave_path())
        with unittest.mock.patch.object(weave, "repair_links", side_effect=AssertionError("the work was started")), self.assertRaises(KbError) as cm:
            self.repair()
        self.assertIn("remove", str(cm.exception))
        self.assertEqual((file_sha256(self.weave_path()), self.leftovers()), (before, []))
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = '999999999998' WHERE key = 'generation'")
        self.assertEqual(self.repair()["generation"], 999999999999)


@needs_numpy
class RepairIsRefusedTest(RepairCase):
    def test_nothing_waiting_is_refused_even_when_told_to_go_on(self):
        for force in (False, True):
            with self.subTest(force=force), self.assertRaises(KbError) as cm:
                self.repair(force=force)
            self.assertIn("nothing is waiting", str(cm.exception))
        self.assertEqual(weave.read(self.weave_path())["meta"]["generation"], 1)

    def test_a_full_build_needed_is_refused_even_when_told_to_go_on_and_nothing_is_written(self):
        for name in ("A0", "B0"):
            key = self.keyed()[name]
            self.vectors_sql(f"UPDATE themes SET theme_generation = 2 WHERE book_id = '{key[0]}' AND theme_id = '{key[2]}'")
        before = file_sha256(self.weave_path())
        for force in (False, True):
            with self.subTest(force=force), self.assertRaises(KbError) as cm:
                self.repair(force=force)
            self.assertIn("theme-links build", str(cm.exception))
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertFalse(os.path.exists(os.path.join(self.index_root(), weave.PREVIOUS_FILE)))

    def test_a_weave_of_another_model_is_a_full_build_even_when_told_to_go_on(self):
        self.add_books({"F": [(20, 30), (100, 110)]})
        with closing_sqlite(self.weave_path()) as conn:
            conn.execute("UPDATE meta SET value = 'another-model:1' WHERE key = 'vectors_model'")
        with self.assertRaises(KbError) as cm:
            self.repair(force=True)
        self.assertIn("theme-links build", str(cm.exception))


@needs_numpy
class RepairBelowTheShareTest(RepairCase):
    SPEC = {**grid(5, 4), "F": [(30, 40)]}

    def test_a_repair_that_is_not_due_is_refused_and_goes_on_when_told_to(self):
        self.add_books({"G": [(10, 20)]})
        before = file_sha256(self.weave_path())
        with self.assertRaises(KbError) as cm:
            self.repair()
        self.assertIn("no repair is due", str(cm.exception))
        self.assertEqual(file_sha256(self.weave_path()), before)
        self.assertEqual(self.repair(force=True)["generation"], 2)

    def test_the_thirty_days_make_it_due(self):
        self.add_books({"G": [(10, 20)]})
        moment = datetime.datetime.fromisoformat(self.store.read_book(self.books["G"])["added"])
        with self.assertRaises(KbError):
            self.repair(now=moment + datetime.timedelta(days=29))
        self.assertEqual(self.repair(now=moment + datetime.timedelta(days=30))["generation"], 2)


@needs_numpy
class ThemeLinksRepairCommandTest(StatusCase):
    def setUp(self):
        super().setUp()
        saved = kbconfig.load()
        saved.update(with_embedding())
        kbconfig.save(saved)

    def kb(self, *args):
        out, err, opened = io.StringIO(), io.StringIO(), []
        real = kbmain.Store.open
        with unittest.mock.patch.object(models, "embed", side_effect=AssertionError("a model was called")), \
                unittest.mock.patch.object(kbmain.Store, "open", side_effect=lambda *a, **k: opened.append((a, k)) or real(*a, **k)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = kbmain.main(list(args))
            except SystemExit as e:
                code = e.code
        self.opened = opened
        return code, out.getvalue(), err.getvalue()

    def test_status_prints_what_is_waiting_and_opens_the_store_to_read_only(self):
        code, out, err = self.kb("theme-links", "status")
        got = json.loads(out)
        self.assertEqual((code, err, got["waiting"]["total"], got["repair_due"]), (0, "", 0, False))
        self.assertEqual([k.get("write") for a, k in self.opened], [False])

    def test_repair_prints_the_counts_and_opens_the_store_to_read_only_and_now_goes_on_when_it_is_not_due(self):
        code, out, err = self.kb("theme-links", "repair")
        self.assertEqual(code, 2)
        self.assertIn("nothing is waiting", err)
        self.add_books({"F": [(20, 30), (100, 110)]})
        code, out, err = self.kb("theme-links", "repair")
        got = json.loads(out)
        self.assertEqual((code, err, got["generation"], got["themes_added"]), (0, "", 2, 2))
        self.assertEqual([k.get("write") for a, k in self.opened], [False])
        self.assertEqual(self.kb("theme-links", "repair", "--now")[0], 2)      # nothing waits any more

    def test_they_take_no_model_server_address_or_launcher(self):
        for command in ("status", "repair"):
            for option in ("--model", "--server", "--address", "--host", "--url", "--launcher", "--bridge"):
                with self.subTest(command=command, option=option):
                    self.assertEqual(self.kb("theme-links", command, option, "x")[0], 2)


if __name__ == "__main__":
    unittest.main()
