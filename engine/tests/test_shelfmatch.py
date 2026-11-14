"""The pure core of the shelf matcher (`kb/shelfmatch.py`, Increment A of the plan `2026-11-14-measure-the-shelf-matcher`).

The module ranks the shelves of the schema by cosine closeness to a vector and scores a placement against the true shelf at each level; these tests use a small schema and small vectors,
and need no network, no model, no library and no config. Run them with `python3 -m unittest engine.tests.test_shelfmatch`."""
import copy
import math
import unittest

from kb import KbError, shelfmatch

SHA = "a" * 64


def schema_data():
    """Two domains, three fields, three subfields, eight topics and one custom shelf (the eight topics and the custom shelf are the home shelves)."""
    def shelf(slug, name, level, parent, openalex, lcc=None):
        return {"slug": slug, "name": name, "level": level, "parent": parent, "openalex": openalex, "lcc": lcc, "scope": "Works on %s." % name}
    shelves = [
        shelf("physical-sciences", "Physical Sciences", "domain", None, "domains/3"),
        shelf("life-sciences", "Life Sciences", "domain", None, "domains/1"),
        shelf("engineering", "Engineering", "field", "physical-sciences", "fields/22"),
        shelf("chemistry", "Chemistry", "field", "physical-sciences", "fields/16"),
        shelf("biology", "Biology", "field", "life-sciences", "fields/11"),
        shelf("industrial", "Industrial", "subfield", "engineering", "subfields/2209"),
        shelf("control", "Control", "subfield", "engineering", "subfields/2207"),
        shelf("genetics", "Genetics", "subfield", "biology", "subfields/1311"),
        shelf("additive", "Additive Manufacturing", "topic", "industrial", "T1"),
        shelf("process-control", "Process Control", "topic", "control", "T2"),
        shelf("robot-control", "Robot Control", "topic", "control", "T3"),
        shelf("gene-editing", "Gene Editing", "topic", "genetics", "T4"),
        shelf("genome-maps", "Genome Maps", "topic", "genetics", "T5"),
        shelf("lean", "Lean Production", "topic", "industrial", "T6"),
        shelf("pid", "PID Tuning", "topic", "control", "T7"),
        shelf("cloning", "Cloning", "topic", "genetics", "T8"),
        shelf("handicrafts", "Handicrafts", "custom", None, None, lcc="TT"),
    ]
    return {"format": 1, "snapshot": {"openalex": {"url": "https://example.org/oa", "retrieved": "2026-11-14", "sha256": SHA},
                                      "lcc": {"url": "https://example.org/lcc", "retrieved": "2026-11-14", "sha256": SHA}, "custom": {"sha256": SHA}},
            "shelves": shelves}


# the vectors have three numbers; the fixture is made so that the cases the figures tell apart actually occur
VECTORS = {
    # topics
    "additive": (1, 0, 0), "process-control": (0, 1, 0), "robot-control": (0, 0.9, 0.1), "gene-editing": (0, 0, 1), "genome-maps": (0.1, 0.1, 0.9),
    "lean": (0.9, 0.1, 0), "pid": (0, 1, 0.2), "cloning": (0.1, 0, 0.8),
    # the custom shelf
    "handicrafts": (-1, -1, 0),
    # subfields
    "industrial": (1, 0.1, 0), "control": (0, 1, 0.05), "genetics": (0, 0.1, 1),
    # fields: Engineering points where Genetics' topics are, Biology does not (so a topic can be nearest while its field is not)
    "engineering": (0.1, 0.2, 0.95), "chemistry": (-1, 0, 0), "biology": (0.7, 0.1, 0.4),
    # domains
    "physical-sciences": (1, 0, 0.5), "life-sciences": (0, 1, 0),
}
Q_GENE = (0, 0.1, 1)       # nearest home shelf: gene-editing; then genome-maps, robot-control, ...


def build(vectors=None, data=None):
    schema = shelfmatch.schema_from_data(data or schema_data())
    return schema, shelfmatch.build_space(schema, vectors or VECTORS)


class Cosine(unittest.TestCase):
    def test_a_vector_is_scaled_to_length_one(self):
        v = shelfmatch.unit((3, 4))
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0)
        self.assertEqual([round(x, 6) for x in v], [0.6, 0.8])

    def test_the_closeness_does_not_depend_on_the_length_of_the_vectors(self):
        a = shelfmatch.rank(shelfmatch.unit((0, 0.1, 1)), ["x"], [shelfmatch.unit((0, 0, 1))], 1)
        b = shelfmatch.rank(shelfmatch.unit((0, 10, 100)), ["x"], [shelfmatch.unit((0, 0, 7))], 1)
        self.assertAlmostEqual(a[0][1], b[0][1])

    def test_the_closeness_is_the_cosine(self):
        got = shelfmatch.rank(shelfmatch.unit((1, 0)), ["same", "right", "back", "half"], [shelfmatch.unit(v) for v in ((2, 0), (0, 3), (-1, 0), (1, 1))], 4)
        self.assertEqual([(s, round(c, 6)) for s, c in got], [("same", 1.0), ("half", round(math.sqrt(0.5), 6)), ("right", 0.0), ("back", -1.0)])

    def test_the_shelves_come_out_nearest_first_and_only_k_of_them(self):
        got = shelfmatch.rank(shelfmatch.unit((0, 0.1, 1)), list(VECTORS), [shelfmatch.unit(VECTORS[s]) for s in VECTORS], 3)
        self.assertEqual(len(got), 3)
        self.assertEqual([s for s, _ in got], ["genetics", "gene-editing", "genome-maps"])
        self.assertTrue(got[0][1] >= got[1][1] >= got[2][1])

    def test_k_larger_than_the_number_of_shelves_gives_all_of_them(self):
        self.assertEqual(len(shelfmatch.rank(shelfmatch.unit((1, 0)), ["a", "b"], [shelfmatch.unit((1, 0)), shelfmatch.unit((0, 1))], 10)), 2)

    def test_a_tie_goes_to_the_shelf_that_comes_first_in_the_file_and_the_same_every_time(self):
        vecs = [shelfmatch.unit((1, 0)), shelfmatch.unit((0, 1)), shelfmatch.unit((1, 0)), shelfmatch.unit((1, 0))]
        first = shelfmatch.rank(shelfmatch.unit((1, 0)), ["a", "b", "c", "d"], vecs, 4)
        self.assertEqual([s for s, _ in first], ["a", "c", "d", "b"])
        self.assertEqual(first, shelfmatch.rank(shelfmatch.unit((1, 0)), ["a", "b", "c", "d"], vecs, 4))

    def test_a_bad_k_is_refused(self):
        for k in (0, -1, 1.5, True, "3", None):
            with self.assertRaises(KbError):
                shelfmatch.rank(shelfmatch.unit((1, 0)), ["a"], [shelfmatch.unit((1, 0))], k)

    def test_vectors_that_are_not_usable_are_refused(self):
        bad = [(), (0, 0), (0.0, 0.0, 0.0), (1e-31, 0), (float("nan"), 1), (float("inf"), 1), (1e7, 1), ("a", 1), (True, 1), (None, 1), ([1], 1)]
        for v in bad:
            with self.assertRaises(KbError, msg=repr(v)):
                shelfmatch.unit(v)
        for v in (None, "ab", 5, {"a": 1}):
            with self.assertRaises(KbError):
                shelfmatch.unit(v)

    def test_a_whole_number_too_large_for_a_float_is_refused_like_any_other_bad_number(self):
        for v in ([10 ** 400, 1], [-10 ** 400, 1], [10 ** 7, 1], [1e7, 1]):
            with self.assertRaises(KbError, msg=repr(v)):
                shelfmatch.unit(v)

    def test_the_size_limit_is_a_million_and_a_million_is_allowed(self):
        shelfmatch.unit([1000000, 1])
        shelfmatch.unit([1e6, 1])
        for v in ([1000001, 1], [1000000.5, 1]):
            with self.assertRaises(KbError, msg=repr(v)):
                shelfmatch.unit(v)

    def test_a_query_that_is_not_a_unit_vector_is_refused_and_not_ranked_wrongly(self):
        with self.assertRaises(KbError):
            shelfmatch.rank([2.0, 0.0], ["a", "b"], [shelfmatch.unit((1, 0)), shelfmatch.unit((1, 1))], 2)
        with self.assertRaises(KbError):
            shelfmatch.rank([0.0, 0.0], ["a"], [shelfmatch.unit((1, 0))], 1)

    def test_a_closeness_never_goes_beyond_one(self):
        # the self-product of this unit vector is 1.0000000000000002 without the clamp
        v = shelfmatch.unit([0.7887233511355132, 0.0938595867742349, 0.02834747652200631, 0.8357651039198697, 0.43276706790505337])
        self.assertGreater(sum(a * b for a, b in zip(v, v)), 1.0)
        self.assertEqual(shelfmatch.rank(v, ["x"], [v], 1)[0][1], 1.0)

    def test_a_vector_longer_than_the_models_longest_is_refused_and_the_longest_is_not(self):
        shelfmatch.unit([1.0] * shelfmatch.MAX_DIM)
        with self.assertRaises(KbError):
            shelfmatch.unit([1.0] * (shelfmatch.MAX_DIM + 1))

    def test_a_query_of_another_length_than_the_shelves_is_refused(self):
        with self.assertRaises(KbError):
            shelfmatch.rank(shelfmatch.unit((1, 0, 0)), ["a"], [shelfmatch.unit((1, 0))], 1)

    def test_the_slugs_and_the_vectors_must_be_as_many(self):
        with self.assertRaises(KbError):
            shelfmatch.rank(shelfmatch.unit((1, 0)), ["a", "b"], [shelfmatch.unit((1, 0))], 1)


class Schema(unittest.TestCase):
    def test_the_home_shelves_are_the_topics_and_the_custom_shelves_in_the_order_of_the_file(self):
        schema = shelfmatch.schema_from_data(schema_data())
        self.assertEqual(schema.home, ["additive", "process-control", "robot-control", "gene-editing", "genome-maps", "lean", "pid", "cloning", "handicrafts"])

    def test_the_ancestors_of_a_topic_are_its_subfield_field_and_domain_and_a_custom_shelf_has_none(self):
        schema = shelfmatch.schema_from_data(schema_data())
        self.assertEqual(schema.ancestors["gene-editing"], {"subfield": "genetics", "field": "biology", "domain": "life-sciences"})
        self.assertEqual(schema.ancestors["robot-control"], {"subfield": "control", "field": "engineering", "domain": "physical-sciences"})
        self.assertIsNone(schema.ancestors["handicrafts"])

    def test_the_shelves_of_each_level_are_listed_in_the_order_of_the_file(self):
        schema = shelfmatch.schema_from_data(schema_data())
        self.assertEqual(schema.levels["field"], ["engineering", "chemistry", "biology"])
        self.assertEqual(schema.levels["subfield"], ["industrial", "control", "genetics"])
        self.assertEqual(schema.levels["domain"], ["physical-sciences", "life-sciences"])

    def test_a_schema_the_checker_refuses_is_refused(self):
        data = schema_data()
        data["shelves"][8]["parent"] = "no-such-shelf"
        with self.assertRaises(KbError):
            shelfmatch.schema_from_data(data)
        with self.assertRaises(KbError):
            shelfmatch.schema_from_data([])

    def test_the_real_schema_file_is_read_by_its_path(self):
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(shelfmatch.__file__)), "data", "shelf-schema.json")
        schema = shelfmatch.load_schema(path)
        self.assertEqual((len(schema.levels["domain"]), len(schema.levels["field"]), len(schema.levels["subfield"]), len(schema.home)), (4, 26, 252, 4534))
        self.assertEqual(sum(1 for s in schema.home if schema.ancestors[s] is None), 18)

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(KbError):
            shelfmatch.load_schema("/no/such/file.json")


class Space(unittest.TestCase):
    def test_a_vector_is_needed_for_every_home_shelf_and_every_shelf_of_the_coarser_levels(self):
        for slug in ("gene-editing", "handicrafts", "genetics", "biology", "life-sciences"):
            vectors = dict(VECTORS)
            del vectors[slug]
            with self.assertRaises(KbError, msg=slug):
                build(vectors)

    def test_vectors_of_different_lengths_are_refused(self):
        vectors = dict(VECTORS)
        vectors["lean"] = (1, 0)
        with self.assertRaises(KbError):
            build(vectors)

    def test_a_vector_for_a_shelf_that_is_not_in_the_schema_is_refused(self):
        vectors = dict(VECTORS)
        vectors["no-such-shelf"] = (1, 0, 0)
        with self.assertRaises(KbError):
            build(vectors)

    def test_a_vector_that_is_not_usable_is_refused(self):
        vectors = dict(VECTORS)
        vectors["lean"] = (0, 0, 0)
        with self.assertRaises(KbError):
            build(vectors)

    def test_vectors_that_are_not_a_dictionary_are_refused(self):
        for bad in (None, list(VECTORS), list(VECTORS.items()), 5, "abc"):
            with self.assertRaises(KbError, msg=repr(bad)):
                shelfmatch.build_space(shelfmatch.schema_from_data(schema_data()), bad)


class Placing(unittest.TestCase):
    def setUp(self):
        self.schema, self.space = build()

    def test_the_home_shelves_are_ranked_without_the_shelves_of_the_coarser_levels(self):
        placement = shelfmatch.place(self.space, Q_GENE, 9)
        self.assertEqual([s for s, _ in placement["home"]], ["gene-editing", "genome-maps", "cloning", "pid", "robot-control", "process-control", "lean", "additive", "handicrafts"])
        self.assertNotIn("genetics", [s for s, _ in placement["home"]])

    def test_each_level_is_ranked_by_itself(self):
        placement = shelfmatch.place(self.space, Q_GENE, 3)
        self.assertEqual([s for s, _ in placement["subfield"]], ["genetics", "control", "industrial"])
        self.assertEqual([s for s, _ in placement["field"]][0], "engineering")          # Engineering is nearer to this query than Biology is
        self.assertEqual([s for s, _ in placement["domain"]], ["physical-sciences", "life-sciences"])   # only two domains

    def test_the_query_of_another_length_is_refused(self):
        with self.assertRaises(KbError):
            shelfmatch.place(self.space, (1, 0), 3)

    def test_the_same_query_gives_the_same_placement(self):
        self.assertEqual(shelfmatch.place(self.space, Q_GENE, 5), shelfmatch.place(self.space, Q_GENE, 5))


class Scoring(unittest.TestCase):
    def setUp(self):
        self.schema, self.space = build()

    def score(self, query, true, k=5, field_k=3, **kw):
        return shelfmatch.score(self.schema, shelfmatch.place(self.space, query, max(k, field_k)), true, k=k, field_k=field_k)

    def test_the_nearest_home_shelf_is_the_true_one(self):
        s = self.score(Q_GENE, "gene-editing")
        self.assertTrue(s["home_top1"] and s["home_topk"])
        self.assertEqual(s["true"], "gene-editing")

    def test_the_true_shelf_is_among_the_nearest_k_and_not_the_nearest(self):
        # the order is gene-editing, genome-maps, cloning, pid, robot-control, ...
        s2 = self.score(Q_GENE, "genome-maps", k=2)
        self.assertFalse(s2["home_top1"])
        self.assertTrue(s2["home_topk"])
        s1 = self.score(Q_GENE, "cloning", k=2)
        self.assertFalse(s1["home_topk"])
        s3 = self.score(Q_GENE, "cloning", k=3)
        self.assertTrue(s3["home_topk"])

    def test_the_fifth_shelf_counts_for_k_five_and_the_sixth_does_not(self):
        # the order is gene-editing, genome-maps, cloning, pid, robot-control, process-control, lean, additive, handicrafts
        self.assertTrue(self.score(Q_GENE, "robot-control", k=5)["home_topk"])
        self.assertFalse(self.score(Q_GENE, "process-control", k=5)["home_topk"])
        self.assertFalse(self.score(Q_GENE, "robot-control", k=4)["home_topk"])

    def test_a_nearest_shelf_of_the_true_subfield_rolls_up_to_a_hit_though_it_is_not_the_true_shelf(self):
        s = self.score(Q_GENE, "genome-maps")      # nearest is gene-editing: the same subfield, field and domain
        self.assertFalse(s["home_top1"])
        self.assertTrue(s["rolled_subfield"] and s["rolled_field"] and s["rolled_domain"])

    def test_the_rolled_up_field_and_the_field_ranking_can_disagree(self):
        # the nearest home shelf is gene-editing, so the rolled-up field is Biology; but Engineering is the nearer field shelf to this query
        s = self.score(Q_GENE, "gene-editing", field_k=1)
        self.assertTrue(s["rolled_field"])
        self.assertFalse(s["level_field_top1"])
        self.assertEqual(self.score(Q_GENE, "gene-editing", field_k=2)["level_field_topk"], True)

    def test_the_rolled_up_hit_is_false_when_the_nearest_shelf_is_in_another_subfield_field_or_domain(self):
        s = self.score(Q_GENE, "robot-control")     # true: Control / Engineering / Physical Sciences; nearest: Gene Editing
        self.assertFalse(s["rolled_subfield"] or s["rolled_field"] or s["rolled_domain"])
        s = self.score((0, 1, 0.1), "lean")         # nearest: process-control or robot-control: Control / Engineering, true: Industrial / Engineering
        self.assertFalse(s["rolled_subfield"])
        self.assertTrue(s["rolled_field"] and s["rolled_domain"])

    def test_the_candidate_recall_is_met_by_the_nearest_k_not_by_the_nearest_alone(self):
        # query nearest: gene-editing, genome-maps, cloning (all Genetics / Biology), then pid (Control / Engineering), ...; true: robot-control (Control / Engineering)
        self.assertFalse(self.score(Q_GENE, "robot-control", k=3)["recall_subfield"])
        self.assertTrue(self.score(Q_GENE, "robot-control", k=4)["recall_subfield"])
        self.assertFalse(self.score(Q_GENE, "robot-control", k=3)["recall_field"])
        self.assertTrue(self.score(Q_GENE, "robot-control", k=4)["recall_field"])

    def test_the_level_rankings_are_scored_at_their_own_k(self):
        s = self.score(Q_GENE, "gene-editing", k=5, field_k=3)
        self.assertTrue(s["level_subfield_top1"] and s["level_subfield_topk"] and s["level_domain_top1"] is False)
        self.assertEqual(self.score(Q_GENE, "gene-editing")["level_domain_top1"], False)       # the domain shelves put Physical Sciences first for this query
        s = self.score((0, 1, 0), "process-control")
        self.assertTrue(s["level_subfield_top1"] and s["level_field_top1"])

    def test_a_true_custom_shelf_has_no_ancestors_so_the_rolled_up_and_level_figures_are_not_defined(self):
        s = self.score((-1, -1, 0), "handicrafts")
        self.assertTrue(s["home_top1"])
        self.assertTrue(s["custom_true"])
        for key in ("rolled_subfield", "rolled_field", "rolled_domain", "recall_subfield", "recall_field", "level_subfield_top1", "level_subfield_topk", "level_field_top1", "level_field_topk", "level_domain_top1"):
            self.assertIsNone(s[key], key)
        self.assertIsNone(s["true_field"])

    def test_a_nearest_custom_shelf_is_never_a_rolled_up_hit(self):
        s = self.score((-1, -1, 0), "additive")
        self.assertFalse(s["home_top1"])
        self.assertFalse(s["rolled_subfield"] or s["rolled_field"] or s["rolled_domain"])
        self.assertTrue(s["nearest_custom"])
        # a custom shelf among the nearest shelves is not a candidate in any subfield or field (additive is in Industrial / Engineering; the others near this query are in Control)
        s = self.score((-1, -1, 0), "additive", k=1)       # the one nearest shelf is the custom one
        self.assertFalse(s["recall_subfield"])
        self.assertFalse(s["recall_field"])
        # for this query the shelves run handicrafts (custom), gene-editing, cloning, genome-maps, ...: a custom shelf first does not stop a later shelf from being the candidate
        s = self.score((-1, -1, 0), "gene-editing", k=1)
        self.assertFalse(s["recall_subfield"] or s["recall_field"])
        s = self.score((-1, -1, 0), "gene-editing", k=2)
        self.assertTrue(s["recall_subfield"] and s["recall_field"])

    def test_the_domain_ranking_is_scored_against_the_true_domain(self):
        s = self.score((1, 0, 0.5), "additive")       # the nearest domain shelf is Physical Sciences, the domain of additive
        self.assertTrue(s["level_domain_top1"])
        self.assertFalse(self.score((0, 1, 0), "additive")["level_domain_top1"])      # Life Sciences is nearer to this query

    def test_a_custom_shelf_among_the_nearest_is_flagged_so_that_the_misses_it_causes_can_be_traced(self):
        s = self.score((-1, -1, 0), "additive", k=2)
        self.assertTrue(s["nearest_custom"] and s["custom_in_topk"])
        s = self.score((-1, -1, 0), "additive", k=2)
        self.assertEqual((s["nearest_custom"], s["custom_in_topk"]), (True, True))
        s = self.score(Q_GENE, "gene-editing", k=5)
        self.assertEqual((s["nearest_custom"], s["custom_in_topk"]), (False, False))
        s = self.score(Q_GENE, "gene-editing", k=9)          # the custom shelf is the ninth, the last
        self.assertEqual((s["nearest_custom"], s["custom_in_topk"]), (False, True))
        s = self.score((-1, -1, 0), "handicrafts")
        self.assertTrue(s["nearest_custom"] and s["custom_in_topk"])       # defined for a true custom shelf too

    def test_the_k_of_a_score_is_recorded(self):
        s = self.score(Q_GENE, "gene-editing", k=4, field_k=2)
        self.assertEqual((s["k"], s["field_k"]), (4, 2))

    def test_a_placement_from_another_schema_is_refused_and_not_a_key_error(self):
        placement = shelfmatch.place(self.space, Q_GENE, 5)
        for key in ("home", "subfield", "field", "domain"):
            other = copy.deepcopy(placement)
            other[key][0] = ("some-other-shelf", 0.5)
            with self.assertRaises(KbError, msg=key):
                shelfmatch.score(self.schema, other, "gene-editing", k=5, field_k=3)
        other = copy.deepcopy(placement)
        other["home"][2] = ("biology", 0.5)           # a shelf of the schema, but not a home shelf
        with self.assertRaises(KbError):
            shelfmatch.score(self.schema, other, "gene-editing", k=5, field_k=3)

    def test_the_true_field_is_recorded_for_the_per_field_figures(self):
        self.assertEqual(self.score(Q_GENE, "gene-editing")["true_field"], "biology")
        self.assertEqual(self.score(Q_GENE, "robot-control")["true_field"], "engineering")

    def test_a_k_that_is_not_a_whole_number_of_at_least_one_is_refused(self):
        placement = shelfmatch.place(self.space, Q_GENE, 5)
        for bad in (0, -1, 1.5, True, "3", None):
            with self.assertRaises(KbError, msg=repr(bad)):
                shelfmatch.score(self.schema, placement, "gene-editing", k=bad, field_k=3)
            with self.assertRaises(KbError, msg=repr(bad)):
                shelfmatch.score(self.schema, placement, "gene-editing", k=5, field_k=bad)

    def test_the_field_ranking_is_cut_at_the_fields_own_k_and_the_subfield_ranking_at_k(self):
        self.assertFalse(self.score(Q_GENE, "gene-editing", k=5, field_k=1)["level_field_topk"])
        self.assertTrue(self.score(Q_GENE, "gene-editing", k=5, field_k=2)["level_field_topk"])
        # the true subfield (Control, for pid) is the second subfield shelf for this query
        s = self.score(Q_GENE, "pid", k=2)
        self.assertFalse(s["level_subfield_top1"])
        self.assertTrue(s["level_subfield_topk"])
        # Industrial (the subfield of lean) is the third subfield shelf for this query: outside the nearest two
        self.assertFalse(self.score(Q_GENE, "lean", k=2)["level_subfield_topk"])

    def test_a_true_shelf_that_is_not_a_home_shelf_is_refused(self):
        for bad in ("genetics", "biology", "life-sciences", "no-such-shelf", "", None, 5):
            with self.assertRaises(KbError, msg=repr(bad)):
                self.score(Q_GENE, bad)

    def test_a_placement_with_fewer_shelves_than_the_scoring_asks_for_is_refused(self):
        with self.assertRaises(KbError):
            shelfmatch.score(self.schema, shelfmatch.place(self.space, Q_GENE, 2), "gene-editing", k=5, field_k=3)

    def test_a_placement_that_is_not_a_placement_is_refused(self):
        with self.assertRaises(KbError):
            shelfmatch.score(self.schema, {"home": []}, "gene-editing", k=5, field_k=3)
        with self.assertRaises(KbError):
            shelfmatch.score(self.schema, None, "gene-editing", k=5, field_k=3)


class Summary(unittest.TestCase):
    def setUp(self):
        self.schema, self.space = build()

    def scored(self, cases, k=5, field_k=3):
        return [shelfmatch.score(self.schema, shelfmatch.place(self.space, q, max(k, field_k)), true, k=k, field_k=field_k) for q, true in cases]

    CASES = [(Q_GENE, "gene-editing"), (Q_GENE, "genome-maps"), (Q_GENE, "robot-control"), ((0, 1, 0), "process-control"), ((0, 1, 0.1), "lean"), ((-1, -1, 0), "handicrafts")]

    def test_the_counts_and_the_shares_of_each_figure(self):
        out = shelfmatch.summarise(self.scored(self.CASES, k=3))
        self.assertEqual(out["n"], 6)
        self.assertEqual(out["n_custom_true"], 1)
        f = out["figures"]
        self.assertEqual(f["home_top1"], {"hits": 3, "of": 6, "share": 0.5})                 # gene-editing, process-control, handicrafts
        self.assertEqual(f["home_topk"]["of"], 6)
        self.assertEqual(f["rolled_field"]["of"], 5)                                           # the custom shelf has none: left out of these figures
        self.assertEqual(f["rolled_field"]["hits"], 4)                                         # all but robot-control
        self.assertEqual(f["rolled_field"]["share"], 0.8)                                      # of the five for which it is defined, not of the six
        self.assertEqual(f["recall_subfield"]["of"], 5)

    def test_how_often_a_custom_shelf_is_the_nearest_or_among_the_nearest_is_counted(self):
        out = shelfmatch.summarise(self.scored(self.CASES, k=3))
        self.assertEqual(out["figures"]["nearest_custom"], {"hits": 1, "of": 6, "share": 1 / 6})
        self.assertEqual(out["figures"]["custom_in_topk"], {"hits": 1, "of": 6, "share": 1 / 6})

    def test_the_k_of_the_scores_is_reported_and_scores_made_with_different_k_are_refused_together(self):
        out = shelfmatch.summarise(self.scored(self.CASES, k=3, field_k=2))
        self.assertEqual((out["k"], out["field_k"]), (3, 2))
        mixed = self.scored(self.CASES[:2], k=3) + self.scored(self.CASES[2:], k=4)
        with self.assertRaises(KbError):
            shelfmatch.summarise(mixed)
        mixed = self.scored(self.CASES[:2], field_k=2) + self.scored(self.CASES[2:], field_k=3)
        with self.assertRaises(KbError):
            shelfmatch.summarise(mixed)

    def test_the_figures_are_counted_over_the_works_for_which_they_are_defined(self):
        out = shelfmatch.summarise(self.scored([(Q_GENE, "handicrafts")]))
        self.assertEqual(out["figures"]["rolled_field"], {"hits": 0, "of": 0, "share": None})
        self.assertEqual(out["figures"]["home_top1"]["of"], 1)

    def test_the_figures_by_field_of_the_true_shelf(self):
        out = shelfmatch.summarise(self.scored(self.CASES, k=3))
        self.assertEqual(sorted(out["per_field"]), ["biology", "engineering"])
        self.assertEqual(out["per_field"]["biology"]["n"], 2)
        self.assertEqual(out["per_field"]["engineering"]["n"], 3)
        self.assertEqual(out["per_field"]["biology"]["figures"]["home_top1"], {"hits": 1, "of": 2, "share": 0.5})

    def test_the_floor_is_the_share_of_the_most_common_true_shelf_subfield_field_and_domain(self):
        cases = [(Q_GENE, "gene-editing"), (Q_GENE, "gene-editing"), (Q_GENE, "genome-maps"), (Q_GENE, "robot-control"), ((0, 1, 0), "lean")]
        floor = shelfmatch.summarise(self.scored(cases))["floor"]
        self.assertEqual(floor["home_top1"], {"shelf": "gene-editing", "share": 0.4})
        self.assertEqual(floor["rolled_subfield"], {"shelf": "genetics", "share": 0.6})
        self.assertEqual(floor["rolled_field"], {"shelf": "biology", "share": 0.6})
        self.assertEqual(floor["rolled_domain"], {"shelf": "life-sciences", "share": 0.6})

    def test_the_floors_of_the_coarser_levels_leave_out_a_true_custom_shelf(self):
        cases = [(Q_GENE, "gene-editing"), (Q_GENE, "gene-editing"), ((-1, -1, 0), "handicrafts"), ((-1, -1, 0), "handicrafts")]
        floor = shelfmatch.summarise(self.scored(cases))["floor"]
        self.assertEqual(floor["home_top1"]["share"], 0.5)         # a tie of two shelves in four placements; the slug that sorts first
        self.assertEqual(floor["home_top1"]["shelf"], "gene-editing")
        self.assertEqual(floor["rolled_field"], {"shelf": "biology", "share": 1.0})

    def test_the_floor_of_only_custom_shelves_is_not_defined(self):
        floor = shelfmatch.summarise(self.scored([((-1, -1, 0), "handicrafts")]))["floor"]
        self.assertEqual(floor["rolled_field"], {"shelf": None, "share": None})

    def test_the_floor_of_a_tie_is_the_slug_that_sorts_first(self):
        floor = shelfmatch.summarise(self.scored([(Q_GENE, "robot-control"), (Q_GENE, "additive")]))["floor"]
        self.assertEqual(floor["home_top1"]["shelf"], "additive")

    def test_no_placements_are_refused(self):
        for bad in ([], None, "x", [None], [{}]):
            with self.assertRaises(KbError, msg=repr(bad)):
                shelfmatch.summarise(bad)

    def test_the_summary_changes_nothing_it_is_given(self):
        scored = self.scored(self.CASES)
        before = copy.deepcopy(scored)
        shelfmatch.summarise(scored)
        self.assertEqual(scored, before)


if __name__ == "__main__":
    unittest.main()
