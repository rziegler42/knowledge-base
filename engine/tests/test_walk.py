"""The selection of the walk (`kb/walk.py`, Increment A of the plan `2026-11-13-let-an-agent-walk-from-themes-along-the-links`).

The selection is pure functions of plain data, so these tests need no numpy and no file: cases small enough to work out by hand, and a comparison with a slow reference written here (`reference_walk`) on
hundreds of random graphs. Run them with `engine/.venv/bin/python -m unittest engine.tests.test_walk`."""
import functools
import itertools
import math
import random
import unittest

from kb import KbError, walk

SCALE = 10 ** 9


_ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"      # the letters of a book id, in order
TAGS = {}                                      # book id -> the short name the test gave it


def K(tag, n=1):
    """A theme key: a book with a valid id made from `tag` (the order of tags is the order of ids), version v1, theme `t<n>`."""
    body = "".join(_ALPHA[ord(c) // 32] + _ALPHA[ord(c) % 32] for c in tag)
    book = ("0" + body)[:26].ljust(26, "0")
    TAGS[book] = tag
    return (book, "v1", "t%d" % n)


def link(a, b, closeness, band, wording=0.4):
    """A row of a weave: `(a, b, closeness, wording, band)` with the numbers in billionths."""
    return (a, b, int(round(closeness * SCALE)), int(round(wording * SCALE)), band)


def refs(leads):
    return [lead["ref"] for lead in leads]


def everything(result):
    """The whole of a result as plain comparable data, the leads reduced to what the rules decide."""
    def lead(l):
        return (l["ref"], tuple((walk.ref_of(r["theme"]), r["closeness"], r["band"]) for r in l["route"]), l["weakest"], l["weakest_band"], l["last_band"], l["ordinary_rank"], l["book_in_ordinary"], l["reached_by"])
    return {"follow": [lead(l) for l in result["follow_through"]], "explore": [lead(l) for l in result["exploration"]], "held": result["held_back"],
            "levels": result["reached_by_level"], "shares": result["lane_shares"], "counts": result["lane_counts"], "notes": result["notes"], "starts": result["starts"],
            "without": result["starts_without_links"]}


class RefTest(unittest.TestCase):
    def test_a_ref_is_three_identifiers_and_round_trips(self):
        key = K("a", 3)
        self.assertEqual(walk.key_of(walk.ref_of(key)), key)
        self.assertEqual(walk.ref_of(key), key[0] + "/v1/t3")

    def test_a_ref_that_is_anything_else_is_refused(self):
        good = walk.ref_of(K("a", 1))
        bad = ["", "a", good + "/x", "../" + good, "/" + good, good.replace("/v1/", "/../"), good + "\n", " " + good, good.replace("/t1", "/T1"), good.replace("/t1", "/-t"), good.replace("/t1", "/" + "t" * 40), good.replace("v1", "v"), good.replace("/v1/", "/v1 /"),
               "a/v1/t1", good[:5] + "/v1/t1", "x" * 300, good.replace("/", "\\"), good + "\x00", None, 7, ["a", "b", "c"], ("a", "v1", "t1")]
        for ref in bad:
            with self.assertRaises(KbError, msg=repr(ref)[:40]):
                walk.key_of(ref)


class GraphTest(unittest.TestCase):
    def test_links_are_two_way(self):
        a, b = K("a"), K("b")
        g = walk.build_graph([link(a, b, 0.7, 3)])
        self.assertEqual(g[a][b], g[b][a])
        self.assertEqual(g[a][b], (700_000_000, 3, 400_000_000))

    def test_a_link_inside_one_book_and_a_link_to_itself_are_left_out(self):
        a, a2, b = K("a", 1), K("a", 2), K("b")
        g = walk.build_graph([link(a, a2, 0.9, 3), link(a, a, 0.9, 3), link(a, b, 0.5, 2)])
        self.assertEqual(set(g[a]), {b})
        self.assertNotIn(a2, g)

    def test_a_link_with_a_hidden_end_is_left_out(self):
        a, b, c = K("a"), K("b"), K("c")
        g = walk.build_graph([link(a, b, 0.7, 3), link(b, c, 0.7, 3)], visible={a, b})
        self.assertEqual(set(g), {a, b})
        self.assertEqual(set(g[b]), {a})

    def test_a_pair_given_twice_keeps_its_first_numbers(self):
        a, b = K("a"), K("b")
        g = walk.build_graph([link(a, b, 0.7, 3), link(b, a, 0.2, 0)])
        self.assertEqual(g[a][b][0], 700_000_000)


def star(n_per_band=3):
    """A start `S` linked to `n_per_band` themes of other books in each band, with closeness that differs: band b, index i has closeness 0.5 + 0.01 * (b * 3 + i)."""
    s = K("s")
    rows, partners = [], {}
    for band in range(4):
        for i in range(n_per_band):
            p = K("p%d%d" % (band, i))
            partners[(band, i)] = p
            rows.append(link(s, p, 0.5 + 0.01 * (band * 3 + i), band))
    return s, rows, partners


class LevelTest(unittest.TestCase):
    """The routes of each level, before any cap on the leads (`walk.routes`)."""

    def ends(self, found):
        return sorted((len(r[1]), walk.ref_of(r[0][-1])) for r in found)

    def test_narrow_follows_the_two_nearest_bands_the_strongest_three_one_step(self):
        s, rows, p = star()
        found = walk.routes(walk.build_graph(rows), [s], "narrow", 1, {s})
        # bands 2 and 3 hold closeness 0.56 0.57 0.58 and 0.59 0.60 0.61: the three strongest are band 3
        self.assertEqual([walk.ref_of(r[0][-1]) for r in found], [walk.ref_of(p[(3, 2)]), walk.ref_of(p[(3, 1)]), walk.ref_of(p[(3, 0)])])
        self.assertTrue(all(len(r[1]) == 1 for r in found))

    def test_narrow_takes_a_band_2_link_when_band_3_has_fewer_than_three(self):
        s = K("s")
        rows = [link(s, K("a"), 0.9, 3), link(s, K("b"), 0.6, 2), link(s, K("c"), 0.7, 2), link(s, K("d"), 0.99, 1), link(s, K("e"), 0.99, 0)]
        found = walk.routes(walk.build_graph(rows), [s], "narrow", 1, {s})
        self.assertEqual(sorted(walk.ref_of(r[0][-1]) for r in found), sorted(walk.ref_of(K(x)) for x in "acb"))    # never a link of band 1 or 0

    def test_medium_follows_every_band_the_strongest_three_then_two(self):
        s = K("s")
        rows = [link(s, K(x), c, b) for x, c, b in (("a", 0.9, 0), ("b", 0.8, 3), ("c", 0.7, 1), ("d", 0.6, 2))]
        rows += [link(K("a"), K(x), c, b) for x, c, b in (("e", 0.95, 3), ("f", 0.94, 3), ("g", 0.93, 3))]       # a's links
        rows += [link(K("b"), K("h"), 0.5, 0), link(K("b"), K("i"), 0.51, 0), link(K("b"), K("j"), 0.52, 0)]
        found = walk.routes(walk.build_graph(rows), [s], "medium", 2, {s})
        first = sorted(walk.ref_of(r[0][-1]) for r in found if len(r[1]) == 1)
        self.assertEqual(first, sorted(walk.ref_of(K(x)) for x in "abc"))                    # the strongest three: 0.9 0.8 0.7, any band; d is not followed
        second = sorted(walk.ref_of(r[0][-1]) for r in found if len(r[1]) == 2)
        # from a: the strongest two of e f g; from b: the strongest two of h i j; from c: nothing
        self.assertEqual(second, sorted(walk.ref_of(K(x)) for x in "efij"))
        self.assertFalse(any(len(r[1]) == 3 for r in found))

    def test_wide_follows_all_twelve_then_the_farthest_two_twice(self):
        s, rows, p = star()
        # each partner of the start has three more links: one in each of bands 3, 0, 1 (to themes of new books)
        for (band, i), partner in p.items():
            tag = "%d%d" % (band, i)
            rows += [link(partner, K("x" + tag), 0.80, 3), link(partner, K("y" + tag), 0.55, 0), link(partner, K("z" + tag), 0.70, 1), link(K("y" + tag), K("w" + tag), 0.60, 2)]
        found = walk.routes(walk.build_graph(rows), [s], "wide", 3, {s})
        one = [r for r in found if len(r[1]) == 1]
        two = [r for r in found if len(r[1]) == 2]
        self.assertEqual(len(one), 12)
        # two steps: from each partner, two links, the farthest band first: y (band 0) and then z (band 1); never x (band 3)
        self.assertEqual(len(two), 24)
        self.assertEqual(sorted({TAGS[r[0][-1][0]][0] for r in two}), ["y", "z"])
        three = [r for r in found if len(r[1]) == 3]
        self.assertEqual(len(three), 12)                                               # y to w, and nothing from z, which has no other link
        self.assertTrue(all(TAGS[r[0][-1][0]][0] == "w" for r in three))
        self.assertTrue(all(len(r[1]) <= 3 for r in found))

    def test_steps_lowers_the_distance(self):
        s, rows, p = star()
        for partner in p.values():
            rows.append(link(partner, K("x" + TAGS[partner[0]]), 0.8, 3))
        g = walk.build_graph(rows)
        self.assertEqual({len(r[1]) for r in walk.routes(g, [s], "wide", 1, {s})}, {1})
        self.assertEqual({len(r[1]) for r in walk.routes(g, [s], "wide", 2, {s})}, {1, 2})

    def test_a_route_never_visits_a_theme_twice(self):
        a, b, c = K("a"), K("b"), K("c")
        rows = [link(a, b, 0.7, 3), link(b, c, 0.7, 3), link(c, a, 0.7, 3)]
        found = walk.routes(walk.build_graph(rows), [a], "wide", 3, {a})
        for themes, _ in found:
            self.assertEqual(len(themes), len(set(themes)))
        self.assertEqual(sorted(len(r[1]) for r in found), [1, 1, 2, 2])

    def test_no_route_passes_through_a_blocked_theme_and_blocked_themes_do_not_use_a_place(self):
        s = K("s")
        rows = [link(s, K(x), 0.9 - 0.01 * i, 3) for i, x in enumerate("abcde")]
        blocked = {s, K("a"), K("b")}                    # the two strongest are seen
        found = walk.routes(walk.build_graph(rows), [s], "narrow", 1, blocked)
        self.assertEqual(sorted(walk.ref_of(r[0][-1]) for r in found), sorted(walk.ref_of(K(x)) for x in "cde"))     # three places, taken by the next three

    def test_ties_in_closeness_go_to_the_key(self):
        s = K("s")
        rows = [link(s, K(x), 0.7, 3) for x in "dcba"]
        found = walk.routes(walk.build_graph(rows), [s], "narrow", 1, {s})
        self.assertEqual([walk.ref_of(r[0][-1]) for r in found], [walk.ref_of(K(x)) for x in "abc"])


class BestRouteTest(unittest.TestCase):
    def test_the_highest_weakest_link_wins_then_the_fewest_steps_then_the_smallest_refs(self):
        s, a, b, d = K("s"), K("a"), K("b"), K("d")
        # s-a-d: 0.9 and 0.5 (weakest 0.5); s-b-d: 0.6 and 0.6 (weakest 0.6): b wins
        rows = [link(s, a, 0.9, 3), link(a, d, 0.5, 3), link(s, b, 0.6, 3), link(b, d, 0.6, 3)]
        r = walk.select(rows, [s], level="wide")
        lead = [l for l in r["follow_through"] + r["exploration"] if l["key"] == d][0]
        self.assertEqual([x["theme"] for x in lead["route"]], [s, b, d])
        self.assertEqual(lead["weakest"], 600_000_000)

    def test_equal_weakest_prefers_fewer_steps(self):
        s, a, d = K("s"), K("a"), K("d")
        rows = [link(s, d, 0.7, 3), link(s, a, 0.9, 3), link(a, d, 0.7, 3)]
        r = walk.select(rows, [s], level="wide")
        lead = [l for l in r["follow_through"] if l["key"] == d][0]
        self.assertEqual(lead["steps"], 1)
        self.assertEqual(lead["reached_by"], 2)

    def test_a_full_tie_is_decided_by_the_refs_and_not_by_the_order_in_which_routes_are_found(self):
        s, a, b, d = K("s"), K("a"), K("b"), K("d")
        # the first step is taken strongest first, so the route through b is found before the route through a; both have the weakest link 0.7 and two steps
        rows = [link(s, b, 0.9, 3), link(b, d, 0.7, 3), link(s, a, 0.7, 3), link(a, d, 0.7, 3)]
        r = walk.select(rows, [s], level="medium")
        lead = [l for l in r["follow_through"] if l["key"] == d][0]
        self.assertEqual([x["theme"] for x in lead["route"]], [s, a, d])

    def test_a_full_tie_goes_to_the_smallest_ref_sequence_whatever_the_order_of_the_links(self):
        s, a, b, d = K("s"), K("a"), K("b"), K("d")
        rows = [link(s, a, 0.7, 3), link(a, d, 0.7, 3), link(s, b, 0.7, 3), link(b, d, 0.7, 3)]
        for order in itertools.permutations(rows):
            r = walk.select(list(order), [s], level="wide")
            lead = [l for l in r["follow_through"] if l["key"] == d][0]
            self.assertEqual([x["theme"] for x in lead["route"]], [s, a, d])         # a sorts before b
            self.assertEqual(lead["reached_by"], 2)


class LaneTest(unittest.TestCase):
    def one(self, closeness, band=3, ordinary=None):
        s, d = K("s"), K("d")
        return walk.select([link(s, d, closeness, band)], [s], level="wide", ordinary=ordinary)

    def test_the_threshold_is_at_or_above(self):
        self.assertEqual(len(self.one(0.66)["follow_through"]), 1)
        self.assertEqual(len(self.one(0.66)["exploration"]), 0)
        r = self.one(0.659999999)
        self.assertEqual((len(r["follow_through"]), len(r["exploration"])), (0, 1))

    def test_the_lane_is_decided_by_the_weakest_link_of_the_route(self):
        s, a, d = K("s"), K("a"), K("d")
        r = walk.select([link(s, a, 0.9, 3), link(a, d, 0.5, 3)], [s], level="wide")
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(a)])
        self.assertEqual(refs(r["exploration"]), [walk.ref_of(d)])

    def fan(self, spec, **kw):
        """Each lead has a start of its own (so that the cap on the leads of one start does not decide the order): `spec` is `(name, closeness, band)`."""
        rows = [link(K("s" + name), K(name), closeness, band) for name, closeness, band in spec]
        return walk.select(rows, [K("s" + name) for name, _, _ in spec], level="wide", **kw)

    def test_follow_through_orders_by_the_weakest_link_then_ref(self):
        r = self.fan([("a", 0.70, 3), ("b", 0.90, 0), ("c", 0.80, 1), ("d", 0.80, 2)])
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(K(x)) for x in "bcda"])

    def test_exploration_orders_by_the_last_band_farthest_first_then_the_weakest_link(self):
        r = self.fan([("a", 0.60, 3), ("b", 0.55, 0), ("c", 0.58, 0), ("d", 0.65, 2), ("e", 0.50, 1)])
        self.assertEqual(refs(r["exploration"]), [walk.ref_of(K(x)) for x in "cbeda"])

    def test_leads_not_in_the_ordinary_set_come_first_in_each_lane(self):
        s = K("s")
        rows = [link(s, K("a"), 0.90, 3), link(s, K("b"), 0.80, 3), link(s, K("c"), 0.70, 3), link(s, K("d"), 0.60, 3), link(s, K("e"), 0.50, 3)]
        r = walk.select(rows, [s], level="wide", ordinary={K("a"): 1, K("d"): 4})
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(K(x)) for x in "bca"])
        self.assertEqual(refs(r["exploration"]), [walk.ref_of(K(x)) for x in "ed"])
        got = {l["ref"]: l["ordinary_rank"] for l in r["follow_through"] + r["exploration"]}
        self.assertEqual((got[walk.ref_of(K("a"))], got[walk.ref_of(K("d"))], got[walk.ref_of(K("b"))]), (1, 4, None))

    def test_the_book_flag(self):
        s = K("s")
        rows = [link(s, K("a", 1), 0.9, 3), link(s, K("b", 1), 0.8, 3)]
        r = walk.select(rows, [s], level="wide", ordinary={K("a", 2): 3})            # another theme of book a is in the ordinary set
        flags = {l["ref"]: l["book_in_ordinary"] for l in r["follow_through"]}
        self.assertEqual(flags, {walk.ref_of(K("a", 1)): True, walk.ref_of(K("b", 1)): False})


class CapTest(unittest.TestCase):
    def test_at_most_two_leads_of_one_book_in_a_lane(self):
        s = K("s")
        rows = [link(s, K("a", i), 0.9 - 0.01 * i, 3) for i in range(1, 4)] + [link(s, K("b"), 0.5, 3)]
        r = walk.select(rows, [s], level="wide")
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(K("a", 1)), walk.ref_of(K("a", 2))])
        self.assertEqual(r["held_back"], {"book": 1, "start": 0, "limit": 0, "seen": 0, "drop": 0})
        self.assertEqual(refs(r["exploration"]), [walk.ref_of(K("b"))])

    def test_the_book_cap_is_for_each_lane(self):
        s = K("s")
        rows = [link(s, K("a", 1), 0.9, 3), link(s, K("a", 2), 0.8, 3), link(s, K("a", 3), 0.55, 3), link(s, K("a", 4), 0.54, 3)]
        r = walk.select(rows, [s], level="wide")
        self.assertEqual((len(r["follow_through"]), len(r["exploration"]), r["held_back"]["book"]), (2, 2, 0))

    def test_at_most_three_leads_from_one_starting_theme_in_a_lane(self):
        s = K("s")
        rows = [link(s, K(x), 0.9 - 0.01 * i, 3) for i, x in enumerate("abcd")]
        r = walk.select(rows, [s], level="wide")
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(K(x)) for x in "abc"])
        self.assertEqual(r["held_back"], {"book": 0, "start": 1, "limit": 0, "seen": 0, "drop": 0})

    def test_the_start_of_a_lead_is_the_start_of_its_best_route(self):
        s1, s2 = K("s1"), K("s2")
        rows = [link(s1, K("a"), 0.9, 3), link(s2, K("a"), 0.95, 3)]
        r = walk.select(rows, [s1, s2], level="wide")
        self.assertEqual(r["follow_through"][0]["start"], s2)
        self.assertEqual(r["follow_through"][0]["reached_by"], 2)


def crowd(starts_strong, starts_weak, per_start=3):
    """Starts each linked to `per_start` themes of their own books: strong (0.7) for the first group, weak (0.5) for the second."""
    rows, starts = [], []
    for g, (count, closeness) in enumerate(((starts_strong, 0.7), (starts_weak, 0.5))):
        for i in range(count):
            s = K("s%d%d" % (g, i))
            starts.append(s)
            rows += [link(s, K("p%d%d%d" % (g, i, j)), closeness, 3) for j in range(per_start)]
    return rows, starts


class PlacesTest(unittest.TestCase):
    def test_two_thirds_and_one_third_of_the_limit_rounded_up(self):
        rows, starts = crowd(8, 8)           # 24 leads in each lane, so that neither lane is short
        for limit, follow, explore in ((12, 8, 4), (3, 2, 1), (1, 1, 0), (20, 14, 6), (7, 5, 2)):
            r = walk.select(rows, starts, level="wide", limit=limit)
            self.assertEqual((len(r["follow_through"]), len(r["exploration"])), (follow, explore), limit)
            self.assertEqual(r["lane_shares"], {"follow-through": follow, "exploration": limit - follow})
            self.assertEqual(r["lane_counts"], {"follow-through": follow, "exploration": limit - follow})

    def test_a_short_lane_gives_its_places_to_the_other(self):
        rows, starts = crowd(4, 1)             # 12 strong leads and 3 weak ones
        r = walk.select(rows, starts, level="wide", limit=12)
        self.assertEqual((len(r["follow_through"]), len(r["exploration"])), (9, 3))
        self.assertEqual(r["held_back"]["limit"], 3)
        self.assertEqual(r["lane_shares"], {"follow-through": 8, "exploration": 4})                 # the shares before a short lane gives its places away
        self.assertEqual(r["lane_counts"], {"follow-through": 9, "exploration": 3})                # what each lane shows
        rows, starts = crowd(1, 4)             # 3 strong and 12 weak
        r = walk.select(rows, starts, level="wide", limit=12)
        self.assertEqual((len(r["follow_through"]), len(r["exploration"])), (3, 9))

    def test_the_lanes_are_never_blended_into_one_ranking(self):
        rows, starts = crowd(2, 2)
        r = walk.select(rows, starts, level="wide")
        self.assertTrue(all(l["weakest"] >= walk.THRESHOLD for l in r["follow_through"]))
        self.assertTrue(all(l["weakest"] < walk.THRESHOLD for l in r["exploration"]))

    def test_the_limit_and_the_steps_and_the_level_are_checked(self):
        rows, starts = crowd(1, 1)
        for bad in (0, -1, 21, True, 1.5, "12", None):
            with self.assertRaises(KbError, msg=repr(bad)):
                walk.select(rows, starts, limit=bad)
        for bad in (0, 4, True, 1.0, "1"):
            with self.assertRaises(KbError, msg=repr(bad)):
                walk.select(rows, starts, level="wide", steps=bad)
        with self.assertRaises(KbError):
            walk.select(rows, starts, level="narrow", steps=2)          # never above the level's
        with self.assertRaises(KbError):
            walk.select(rows, starts, level="wider")
        walk.select(rows, starts, level="medium", steps=1)


class IterationTest(unittest.TestCase):
    def graph(self):
        s, a, b, c, d, x = (K(n) for n in "sabcdx")
        rows = [link(s, a, 0.9, 3), link(s, b, 0.8, 3), link(a, c, 0.85, 3), link(b, d, 0.75, 3), link(d, x, 0.7, 3)]
        return rows, (s, a, b, c, d, x)

    def test_seen_themes_are_never_offered_and_never_walked_through(self):
        rows, (s, a, b, c, d, x) = self.graph()
        r = walk.select(rows, [s], level="wide", seen=[a])
        got = set(refs(r["follow_through"] + r["exploration"]))
        self.assertEqual(got, {walk.ref_of(t) for t in (b, d, x)})              # a is not offered, and c is reached only through a

    def test_a_seen_theme_given_as_a_start_is_still_walked_from(self):
        rows, (s, a, b, c, d, x) = self.graph()
        r = walk.select(rows, [a], level="wide", seen=[a, s])
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(c)])           # s is seen and blocked

    def test_drop_removes_the_theme_and_what_is_reached_only_through_it(self):
        rows, (s, a, b, c, d, x) = self.graph()
        r = walk.select(rows, [s], level="wide", drop=[b])
        self.assertEqual(set(refs(r["follow_through"] + r["exploration"])), {walk.ref_of(t) for t in (a, c)})

    def test_what_is_reached_another_way_stays_when_one_way_is_dropped(self):
        s, a, b, d = K("s"), K("a"), K("b"), K("d")
        rows = [link(s, a, 0.9, 3), link(s, b, 0.8, 3), link(a, d, 0.7, 3), link(b, d, 0.7, 3)]
        r = walk.select(rows, [s], level="wide", drop=[a])
        lead = [l for l in r["follow_through"] if l["key"] == d][0]
        self.assertEqual(lead["reached_by"], 1)

    def test_the_other_starting_themes_are_never_offered_or_passed_through(self):
        s1, s2, a = K("s1"), K("s2"), K("a")
        rows = [link(s1, s2, 0.9, 3), link(s2, a, 0.8, 3), link(s1, a, 0.7, 3)]
        r = walk.select(rows, [s1, s2], level="wide")
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(a)])
        self.assertEqual([x["theme"] for x in r["follow_through"][0]["route"]], [s2, a])

    def test_a_second_round_with_what_was_seen_offers_none_of_it_again(self):
        rows, starts = crowd(3, 3)
        first = walk.select(rows, starts, level="wide", limit=6)
        shown = [l["key"] for l in first["follow_through"] + first["exploration"]]
        second = walk.select(rows, starts, level="wide", limit=6, seen=shown)
        again = [l["key"] for l in second["follow_through"] + second["exploration"]]
        self.assertTrue(again)
        self.assertFalse(set(again) & set(shown))

    def test_the_themes_of_a_route_passed_back_as_seen_are_not_offered(self):
        rows, (s, a, b, c, d, x) = self.graph()
        first = walk.select(rows, [s], level="wide", limit=20, drop=[a])             # the route to d is s, b, d
        lead = [l for l in first["follow_through"] + first["exploration"] if l["key"] == d][0]
        route = [r["theme"] for r in lead["route"]]
        self.assertEqual(route, [s, b, d])
        second = walk.select(rows, [d], level="wide", seen=route)
        self.assertEqual(refs(second["follow_through"] + second["exploration"]), [walk.ref_of(x)])


class ReachedByTest(unittest.TestCase):
    def test_two_routes_on_a_diamond_and_three_routes(self):
        s, a, b, c, d = K("s"), K("a"), K("b"), K("c"), K("d")
        rows = [link(s, a, 0.8, 3), link(s, b, 0.8, 3), link(a, d, 0.7, 3), link(b, d, 0.7, 3)]
        r = walk.select(rows, [s], level="medium")          # two steps: d is reached through a and through b, and a is not reached again through d
        self.assertEqual({l["ref"]: l["reached_by"] for l in r["follow_through"]}, {walk.ref_of(a): 1, walk.ref_of(b): 1, walk.ref_of(d): 2})
        wide = walk.select(rows, [s], level="wide")         # three steps: a is also reached by s, b, d, a
        self.assertEqual({l["ref"]: l["reached_by"] for l in wide["follow_through"]}, {walk.ref_of(a): 2, walk.ref_of(b): 2, walk.ref_of(d): 2})
        s2 = K("t")
        rows += [link(s2, c, 0.8, 3), link(c, d, 0.7, 3)]            # a third route, from a second starting theme
        r = walk.select(rows, [s, s2], level="medium")
        self.assertEqual([l for l in r["follow_through"] if l["key"] == d][0]["reached_by"], 3)

    def test_routes_from_two_starting_themes_count(self):
        s1, s2, d = K("s1"), K("s2"), K("d")
        r = walk.select([link(s1, d, 0.7, 3), link(s2, d, 0.7, 3)], [s1, s2], level="wide")
        self.assertEqual(r["follow_through"][0]["reached_by"], 2)

    def test_the_count_is_of_routes_within_the_level(self):
        s, a, d = K("s"), K("a"), K("d")
        rows = [link(s, a, 0.8, 3), link(a, d, 0.8, 3)]
        self.assertEqual([l for l in walk.select(rows, [s], level="medium")["follow_through"] if l["key"] == d][0]["reached_by"], 1)
        self.assertNotIn(d, [l["key"] for l in walk.select(rows, [s], level="narrow")["follow_through"]])


class WhatWideningAddsTest(unittest.TestCase):
    def test_the_themes_reached_at_each_level(self):
        s, a, b, c = K("s"), K("a"), K("b"), K("c")
        rows = [link(s, a, 0.8, 3), link(s, b, 0.8, 0), link(a, c, 0.8, 3)]
        r = walk.select(rows, [s], level="narrow")
        self.assertEqual(r["reached_by_level"], {"narrow": 1, "medium": 3, "wide": 3})
        self.assertEqual(walk.select(rows, [s], level="wide")["reached_by_level"], r["reached_by_level"])           # not decided by the level asked for


class NotesTest(unittest.TestCase):
    def test_no_start(self):
        self.assertEqual(walk.select([link(K("a"), K("b"), 0.7, 3)], [])["notes"], ["no_starting_theme"])

    def test_a_start_with_no_link(self):
        r = walk.select([link(K("a"), K("b"), 0.7, 3)], [K("z")])
        self.assertEqual(r["notes"], ["no_starting_theme_has_a_link", "nothing_reached"])
        self.assertEqual(r["starts_without_links"], [walk.ref_of(K("z"))])

    def test_everything_reached_is_in_the_ordinary_set(self):
        s, a = K("s"), K("a")
        r = walk.select([link(s, a, 0.7, 3)], [s], ordinary={a: 2})
        self.assertEqual(r["notes"], ["everything_reached_is_in_the_ordinary_set"])
        self.assertEqual(len(r["follow_through"]), 1)

    def test_nothing_reached_because_everything_is_seen_or_dropped_is_said_apart_from_nothing_to_reach(self):
        s, a, b = K("s"), K("a"), K("b")
        self.assertEqual(walk.select([link(s, a, 0.7, 3)], [s], seen=[a])["notes"], ["everything_reached_is_seen_or_dropped"])
        self.assertEqual(walk.select([link(s, a, 0.7, 3)], [s], drop=[a])["notes"], ["everything_reached_is_seen_or_dropped"])
        self.assertEqual(walk.select([link(a, b, 0.7, 3)], [s])["notes"], ["no_starting_theme_has_a_link", "nothing_reached"])

    def test_the_themes_held_back_for_being_seen_or_dropped_are_counted(self):
        s, a, b, c, d = K("s"), K("a"), K("b"), K("c"), K("d")
        rows = [link(s, a, 0.9, 3), link(s, b, 0.8, 3), link(s, c, 0.7, 3), link(a, d, 0.7, 3)]
        r = walk.select(rows, [s], level="wide", seen=[a, K("zz")], drop=[b, a])           # a is both seen and dropped: counted once, as seen; zz is not in the weave
        self.assertEqual((r["held_back"]["seen"], r["held_back"]["drop"]), (1, 1))
        self.assertEqual(refs(r["follow_through"]), [walk.ref_of(c)])
        none = walk.select(rows, [s], level="wide")
        self.assertEqual((none["held_back"]["seen"], none["held_back"]["drop"]), (0, 0))

    def test_wide_never_follows_more_than_twelve_links_of_a_theme(self):
        s = K("s")
        rows = [link(s, K("p%02d" % i), 0.5 + 0.01 * i, i % 4) for i in range(13)]
        found = walk.routes(walk.build_graph(rows), [s], "wide", 1, {s})
        self.assertEqual(len(found), 12)
        self.assertNotIn(K("p00"), [r[0][-1] for r in found])           # the weakest of the thirteen is the one left out

    def test_a_good_call_has_no_note(self):
        s, a = K("s"), K("a")
        self.assertEqual(walk.select([link(s, a, 0.7, 3)], [s])["notes"], [])


class VisibleTest(unittest.TestCase):
    def world(self):
        s, a, b, h, g = K("s"), K("a"), K("b"), K("h"), K("g")
        rows = [link(s, a, 0.9, 3), link(s, h, 0.95, 3), link(h, g, 0.9, 3), link(a, b, 0.8, 3), link(s, g, 0.6, 1)]
        return rows, (s, a, b, h, g)

    def test_a_hidden_theme_changes_nothing_visible(self):
        rows, (s, a, b, h, g) = self.world()
        visible = {s, a, b, g}
        seen_world = walk.select(rows, [s], level="wide", ordinary={h: 1, a: 2}, seen=[h], drop=[h], visible=visible)
        without = walk.select([r for r in rows if h not in r[:2]], [s], level="wide", ordinary={a: 2}, visible=visible)
        self.assertEqual(everything(seen_world), everything(without))

    def test_a_hidden_start_and_a_hidden_book_flag_and_a_hidden_route_leave_no_trace(self):
        rows, (s, a, b, h, g) = self.world()
        visible = {s, a, b, g}
        r = walk.select(rows, [s, h], level="wide", ordinary={h: 1}, visible=visible)
        self.assertEqual(r["starts"], [walk.ref_of(s)])
        self.assertFalse(any(l["book_in_ordinary"] for l in r["follow_through"] + r["exploration"]))
        self.assertNotIn(walk.ref_of(h), str(r))
        g_lead = [l for l in r["follow_through"] + r["exploration"] if l["key"] == g][0]
        self.assertEqual([x["theme"] for x in g_lead["route"]], [s, g])              # the route through the hidden theme does not exist
        self.assertEqual(g_lead["reached_by"], 1)

    def test_every_count_is_over_the_visible_set(self):
        rows, (s, a, b, h, g) = self.world()
        everyone = walk.select(rows, [s], level="wide", limit=20)
        some = walk.select(rows, [s], level="wide", limit=20, visible={s, a, b, g})
        self.assertGreater(everyone["reached_by_level"]["wide"], some["reached_by_level"]["wide"])
        self.assertEqual(some["reached_by_level"], {"narrow": 1, "medium": 3, "wide": 3})      # narrow follows bands 2 and 3 only: a, and not g (band 1)

    def test_no_visible_set_means_everything(self):
        rows, (s, a, b, h, g) = self.world()
        self.assertEqual(everything(walk.select(rows, [s])), everything(walk.select(rows, [s], visible={s, a, b, h, g})))


class DeterminismTest(unittest.TestCase):
    def test_the_order_of_everything_given_does_not_matter(self):
        rng = random.Random(5)
        rows, starts = random_world(rng, 25)
        base = everything(walk.select(rows, starts, level="wide", seen=starts[:0], limit=20))
        for _ in range(20):
            rows2, starts2 = list(rows), list(starts)
            rng.shuffle(rows2)
            rng.shuffle(starts2)
            rows2 = [(b, a, c, w, band) if rng.random() < 0.5 else (a, b, c, w, band) for a, b, c, w, band in rows2]       # either end first
            self.assertEqual(everything(walk.select(rows2, starts2, level="wide", limit=20)), base)

    def test_a_route_never_joins_two_themes_of_one_book(self):
        rng = random.Random(6)
        rows, starts = random_world(rng, 30)
        rows.append(link(K("a", 1), K("a", 2), 0.99, 3))
        r = walk.select(rows, starts, level="wide", limit=20)
        for lead in r["follow_through"] + r["exploration"]:
            books = [x["theme"][0] for x in lead["route"]]
            self.assertTrue(all(x != y for x, y in zip(books, books[1:])))


def random_world(rng, n_themes=30, n_books=8, density=0.12):
    """Random themes of several books, links in four bands with random closeness (some equal on purpose), at most one link between a pair."""
    keys = [K("b%d" % rng.randrange(n_books), i) for i in range(n_themes)]
    rows = []
    for a, b in itertools.combinations(keys, 2):
        if a[0] != b[0] and rng.random() < density:
            rows.append(link(a, b, rng.choice([0.5, 0.55, 0.6, 0.66, 0.66, 0.7, 0.8, round(rng.uniform(0.49, 0.9), 3)]), rng.randrange(4)))
    starts = rng.sample(keys, rng.randint(1, 4))
    return rows, starts


def reference_walk(rows, starts, level, steps, seen, drop, ordinary, limit, visible):
    """The same rules, written the slow way and apart from `walk`: adjacency lists, a recursive search of every simple route, the best route by a loop, the lanes by a comparison function."""
    visible = None if visible is None else set(visible)
    ok = (lambda k: True) if visible is None else (lambda k: k in visible)
    adj = {}
    for a, b, c, w, band in rows:
        if a == b or a[0] == b[0] or not (ok(a) and ok(b)):
            continue
        for x, y in ((a, b), (b, a)):
            if not any(p == y for p, _, _ in adj.get(x, [])):
                adj.setdefault(x, []).append((y, c, band))
    starts = sorted({s for s in starts if ok(s)})
    seen = {k for k in seen if ok(k)}
    drop = {k for k in drop if ok(k)}
    ordinary = {k: r for k, r in ordinary.items() if ok(k)}
    blocked = seen | drop | set(starts)
    caps = {"narrow": [3], "medium": [3, 2], "wide": [12, 2, 2]}
    depth_of = {"narrow": 1, "medium": 2, "wide": 3}

    def followed(key, lev, step, on_route, blk):
        out = []
        for p, c, band in adj.get(key, []):
            if p in blk or p in on_route:
                continue
            if lev == "narrow" and band < 2:
                continue
            out.append((p, c, band))
        if lev == "wide" and step > 0:
            out.sort(key=lambda t: (t[2], -t[1], t[0]))
        else:
            out.sort(key=lambda t: (-t[1], t[0]))
        return out[:caps[lev][step]]

    def search(lev, depth, blk):
        found = []

        def go(themes, links, step):
            if step == depth:
                return
            for p, c, band in followed(themes[-1], lev, step, set(themes), blk):
                found.append((themes + [p], links + [(c, band)]))
                go(themes + [p], links + [(c, band)], step + 1)
        for s in starts:
            go([s], [], 0)
        return found

    dests = {}
    for themes, links in search(level, min(steps, depth_of[level]), blocked):
        dests.setdefault(themes[-1], []).append((themes, links))
    levels = {}
    for lev in ("narrow", "medium", "wide"):
        levels[lev] = len({t[-1] for t, _ in search(lev, depth_of[lev], blocked)})
    would = {t[-1] for t, _ in search(level, min(steps, depth_of[level]), set(starts))}          # reached if nothing were seen or dropped
    seen_held = len([d for d in would if d in seen])
    drop_held = len([d for d in would if d in drop and d not in seen])

    def better(r1, r2):          # a negative number when r1 is the better route
        w1, w2 = min(c for c, _ in r1[1]), min(c for c, _ in r2[1])
        if w1 != w2:
            return -1 if w1 > w2 else 1
        if len(r1[1]) != len(r2[1]):
            return -1 if len(r1[1]) < len(r2[1]) else 1
        s1, s2 = [walk.ref_of(k) for k in r1[0]], [walk.ref_of(k) for k in r2[0]]
        return -1 if s1 < s2 else (1 if s1 > s2 else 0)
    leads = {"follow": [], "explore": []}
    books_of_ord = {k[0] for k in ordinary}
    for dest, routes_to in dests.items():
        best = routes_to[0]
        for r in routes_to[1:]:
            if better(r, best) < 0:
                best = r
        weakest = min(c for c, _ in best[1])
        lead = {"ref": walk.ref_of(dest), "key": dest, "start": best[0][0], "weakest": weakest, "last": best[1][-1][1], "rank": ordinary.get(dest), "reached_by": len(routes_to),
                "route": [walk.ref_of(k) for k in best[0]], "book_flag": dest[0] in books_of_ord, "weakest_band": [b for c, b in best[1] if c == weakest][0]}
        leads["follow" if weakest >= 660_000_000 else "explore"].append(lead)

    def cmp_follow(x, y):
        kx = (x["rank"] is not None, -x["weakest"], x["ref"])
        ky = (y["rank"] is not None, -y["weakest"], y["ref"])
        return (kx > ky) - (kx < ky)

    def cmp_explore(x, y):
        kx = (x["rank"] is not None, x["last"], -x["weakest"], x["ref"])
        ky = (y["rank"] is not None, y["last"], -y["weakest"], y["ref"])
        return (kx > ky) - (kx < ky)
    held = {"book": 0, "start": 0, "limit": 0}
    lanes = {}
    for name, cmp in (("follow", cmp_follow), ("explore", cmp_explore)):
        taken, per_book, per_start = [], {}, {}
        for lead in sorted(leads[name], key=functools.cmp_to_key(cmp)):
            if per_book.get(lead["key"][0], 0) >= 2:
                held["book"] += 1
            elif per_start.get(lead["start"], 0) >= 3:
                held["start"] += 1
            else:
                per_book[lead["key"][0]] = per_book.get(lead["key"][0], 0) + 1
                per_start[lead["start"]] = per_start.get(lead["start"], 0) + 1
                taken.append(lead)
        lanes[name] = taken
    f_share = math.ceil(2 * limit / 3)
    f_places = min(len(lanes["follow"]), f_share)
    e_places = min(len(lanes["explore"]), limit - f_share)
    free = limit - f_places - e_places
    extra_f = min(free, len(lanes["follow"]) - f_places)
    f_places += extra_f
    free -= extra_f
    e_places += min(free, len(lanes["explore"]) - e_places)
    held["limit"] = (len(lanes["follow"]) - f_places) + (len(lanes["explore"]) - e_places)
    held["seen"], held["drop"] = seen_held, drop_held
    return {"follow": [(l["ref"], tuple(l["route"]), l["weakest"], l["last"], l["rank"], l["reached_by"], l["book_flag"], l["weakest_band"]) for l in lanes["follow"][:f_places]],
            "explore": [(l["ref"], tuple(l["route"]), l["weakest"], l["last"], l["rank"], l["reached_by"], l["book_flag"], l["weakest_band"]) for l in lanes["explore"][:e_places]],
            "held": held, "levels": levels}


def projected(result):
    def lead(l):
        return (l["ref"], tuple(walk.ref_of(r["theme"]) for r in l["route"]), l["weakest"], l["last_band"], l["ordinary_rank"], l["reached_by"], l["book_in_ordinary"], l["weakest_band"])
    return {"follow": [lead(l) for l in result["follow_through"]], "explore": [lead(l) for l in result["exploration"]], "held": result["held_back"], "levels": result["reached_by_level"]}


class AgainstTheReferenceTest(unittest.TestCase):
    def test_random_worlds_at_every_level_with_seen_dropped_ordinary_and_visible_sets(self):
        rng = random.Random(20261113)
        cases = 0
        for trial in range(300):
            rows, starts = random_world(rng, rng.randint(6, 40), rng.randint(3, 10), rng.choice([0.05, 0.12, 0.3]))
            keys = sorted({k for r in rows for k in r[:2]} | set(starts))
            seen = rng.sample(keys, rng.randint(0, min(3, len(keys))))
            drop = rng.sample(keys, rng.randint(0, min(2, len(keys))))
            ordinary = {k: i + 1 for i, k in enumerate(rng.sample(keys, rng.randint(0, min(6, len(keys)))))}
            visible = None if rng.random() < 0.5 else set(rng.sample(keys, max(1, int(len(keys) * 0.8))))
            level = rng.choice(["narrow", "medium", "wide"])
            steps = rng.randint(1, walk.LEVELS[level]["steps"])
            limit = rng.choice([1, 2, 3, 5, 12, 20])
            got = projected(walk.select(rows, starts, level=level, steps=steps, seen=seen, drop=drop, ordinary=ordinary, limit=limit, visible=visible))
            want = reference_walk(rows, starts, level, steps, set(seen), set(drop), ordinary, limit, visible)
            self.assertEqual(got, want, (trial, level, steps, limit))
            cases += 1
        self.assertEqual(cases, 300)

    def test_the_reference_finds_leads_in_most_worlds(self):
        rng = random.Random(1)
        with_leads = 0
        for _ in range(100):
            rows, starts = random_world(rng, 30, 8, 0.2)
            r = walk.select(rows, starts, level="wide", limit=20)
            with_leads += bool(r["follow_through"] or r["exploration"])
        self.assertGreater(with_leads, 80)


if __name__ == "__main__":
    unittest.main()
