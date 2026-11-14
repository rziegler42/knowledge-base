"""The builder of the shelf schema file (`kb/shelfbuild.py`, Increment D of the plan `2026-11-14-build-the-shelf-schema`).

The builder reads three inputs by path (the saved OpenAlex lists with their report, the saved Library of Congress outline with its report and extract, and the tracked file of custom
shelves) and makes the schema file from them. These tests use a small fixture of the three inputs in a temporary folder; they need no network, no library and no model, and use only
the standard library. Run them with `python3 -m unittest engine.tests.test_shelfschema engine.tests.test_shelfbuild`."""
import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest

from kb import KbError, shelfbuild, shelfschema
from kb import __main__ as kbmain

OA = "https://openalex.org/"
INDEX_URL = "https://www.loc.gov/catdir/cpso/lcco/"
PDF_URL = "https://www.loc.gov/aba/cataloging/classification/lcco/lcco_%s.pdf"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(kind, number, name, description, parents=()):
    out = {"id": OA + kind + number, "display_name": name, "description": description, "ids": {}, "updated_date": "2026-11-14T03:00:00"}
    for key, ident, parent_name in parents:
        out[key] = {"id": ident, "display_name": parent_name}
    return out


def oa_results():
    """Two domains, two fields (one named as its domain), three subfields (one with no topic) and four topics."""
    d3, d2 = OA + "domains/3", OA + "domains/2"
    f22, f33 = OA + "fields/22", OA + "fields/33"
    s2209, s3312, s3614 = OA + "subfields/2209", OA + "subfields/3312", OA + "subfields/3614"
    domains = [record("domains/", "3", "Physical Sciences", "branch of natural science that studies non-living systems"),
               record("domains/", "2", "Social Sciences", "study of society and the relationships of people in it")]
    fields = [record("fields/", "22", "Engineering", "application of science to the design of things", [("domain", d3, "Physical Sciences")]),
              record("fields/", "33", "Social Sciences", "academic disciplines concerned with society", [("domain", d2, "Social Sciences")])]
    subfields = [record("subfields/", "2209", "Industrial and Manufacturing Engineering", "making goods at scale", [("field", f22, "Engineering"), ("domain", d3, "Physical Sciences")]),
                 record("subfields/", "3312", "Sociology", "study of social behaviour", [("field", f33, "Social Sciences"), ("domain", d2, "Social Sciences")]),
                 record("subfields/", "3614", "Radiological Technology", "images of the body", [("field", f22, "Engineering"), ("domain", d3, "Physical Sciences")])]
    chain = lambda s, sn, f, fn, d, dn: [("subfield", s, sn), ("field", f, fn), ("domain", d, dn)]
    topics = [record("", "T10001", "Additive Manufacturing", "This cluster of papers covers 3D printing. It spans many methods.", chain(s2209, "Industrial and Manufacturing Engineering", f22, "Engineering", d3, "Physical Sciences")),
              record("", "T10002", "Qur’anic Studies in the U.S.", "This cluster of papers studies texts, e.g. in the U.S. and elsewhere. Another sentence.", chain(s3312, "Sociology", f33, "Social Sciences", d2, "Social Sciences")),
              record("", "T10003", "Social Sciences", "", chain(s3312, "Sociology", f33, "Social Sciences", d2, "Social Sciences")),
              record("", "T10004", "Sociology of Behçet", "This cluster of papers " + "x" * 600, chain(s3312, "Sociology", f33, "Social Sciences", d2, "Social Sciences"))]
    return {"domains": domains, "fields": fields, "subfields": subfields, "topics": topics}


class Inputs:
    """The three inputs of the builder as files in a temporary folder, with the pieces a test changes."""

    def __init__(self, test):
        self.root = tempfile.mkdtemp()
        test.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.openalex = os.path.join(self.root, "openalex")
        self.lcc = os.path.join(self.root, "lcc")
        self.custom = os.path.join(self.root, "shelf-custom.json")
        os.mkdir(self.openalex)
        os.mkdir(self.lcc)
        self.write_openalex(oa_results())
        self.write_lcc()
        self.write_custom()

    # --- OpenAlex
    def write_openalex(self, results, page_size=2, mutate=None):
        files, levels = [], {}
        for level, rows in results.items():
            pages = [rows[i:i + page_size] for i in range(0, len(rows), page_size)] or [[]]
            for number, page in enumerate(pages, 1):
                name = "%s-%03d.json" % (level, number)
                raw = json.dumps({"results": page}).encode("utf-8")
                with open(os.path.join(self.openalex, name), "wb") as f:
                    f.write(raw)
                files.append({"file": name, "level": level, "page": number, "url": "https://api.openalex.org/%s?page=%d" % (level, number), "status": 200,
                              "bytes": len(raw), "sha256": sha(raw), "seconds": 0.1, "count": len(rows), "results": len(page)})
            levels[level] = {"count": len(rows), "pages": len(pages), "received": len(rows), "unique_ids": len(rows), "irregularities": []}
        self.oa_report = {"format": 1, "source": "https://api.openalex.org", "started": "2026-11-14T17:19:36Z", "status": "done", "files": files, "levels": levels, "finished": "2026-11-14T17:20:03Z", "requests": len(files)}
        if mutate:
            mutate(self.oa_report)
        self.save_json(os.path.join(self.openalex, shelfbuild.OPENALEX_REPORT), self.oa_report)

    def oa_manifest(self):
        return shelfbuild.manifest_sha256([(e["file"], e["sha256"]) for e in self.oa_report["files"]])

    # --- the Library of Congress
    def write_lcc(self, mutate_report=None, mutate_extract=None):
        names = {"index.html": (INDEX_URL, b"<html>index</html>"), "lcco_g.pdf": (PDF_URL % "g", b"%PDF-g"), "lcco_t.pdf": (PDF_URL % "t", b"%PDF-t")}
        files = []
        for name, (url, raw) in names.items():
            with open(os.path.join(self.lcc, name), "wb") as f:
                f.write(raw)
            files.append({"file": name, "url": url, "type": "text/html" if name.endswith(".html") else "application/pdf", "status": 200, "bytes": len(raw), "sha256": sha(raw), "seconds": 0.1})
        self.lcc_report = {"format": 1, "source": "https://www.loc.gov", "started": "2026-11-14T18:17:26Z", "status": "done", "files": files, "finished": "2026-11-14T18:17:42Z", "requests": 3}
        if mutate_report:
            mutate_report(self.lcc_report)
        report_bytes = self.save_json(os.path.join(self.lcc, shelfbuild.LCC_REPORT), self.lcc_report)
        self.extract = {"format": 1, "source": "https://www.loc.gov", "report_sha256": sha(report_bytes), "classes": [],
                        "subclasses": [{"code": "GV", "caption": "Recreation. Leisure", "file": "lcco_g.pdf", "class": "G"},
                                       {"code": "TT", "caption": "Handicrafts. Arts and crafts", "file": "lcco_t.pdf", "class": "T"},
                                       {"code": "TR", "caption": "Photography", "file": "lcco_t.pdf", "class": "T"}],
                        "ranges": [], "counts": {"files": 3, "subclasses": 3, "ranges": 0}, "irregularities": []}
        if mutate_extract:
            mutate_extract(self.extract)
        self.save_json(os.path.join(self.lcc, shelfbuild.LCC_EXTRACT), self.extract)

    def lcc_manifest(self):
        return shelfbuild.manifest_sha256([(e["file"], e["sha256"]) for e in self.lcc_report["files"]])

    # --- the custom shelves
    def write_custom(self, mutate=None, source_sha=None):
        self.custom_data = {"format": 1, "source": {"url": INDEX_URL, "retrieved": "2026-11-14", "sha256": source_sha or self.lcc_manifest()},
                            "shelves": [{"code": "TT", "name": "Handicrafts. Arts and crafts", "parent": None, "scope": "Handicrafts and the arts and crafts: making things by hand.",
                                         "reason": "OpenAlex has no subfield named for handicrafts.", "page": PDF_URL % "t", "retrieved": "2026-11-14"},
                                        {"code": "GV", "name": "Recreation. Leisure", "parent": None, "scope": "Recreation and leisure: sports, games and dance.",
                                         "reason": "OpenAlex has no subfield named for recreation.", "page": PDF_URL % "g", "retrieved": "2026-11-14"}]}
        if mutate:
            mutate(self.custom_data)
        self.save_json(self.custom, self.custom_data)

    def save_json(self, path, data):
        raw = json.dumps(data, indent=1).encode("utf-8")
        with open(path, "wb") as f:
            f.write(raw)
        return raw

    def build(self):
        return shelfbuild.build(self.openalex, self.lcc, self.custom)


def shelves_of(result):
    return json.loads(result["bytes"].decode("utf-8"))["shelves"]


def by_name(result, name, level=None):
    found = [s for s in shelves_of(result) if s["name"] == name and (level is None or s["level"] == level)]
    assert len(found) == 1, (name, level, len(found))
    return found[0]


class Slugs(unittest.TestCase):
    def test_a_slug_is_the_name_in_lowercase_words_joined_by_hyphens(self):
        self.assertEqual(shelfbuild.slug_base("Industrial and Manufacturing Engineering"), "industrial-and-manufacturing-engineering")

    def test_accents_lose_their_marks_and_other_characters_become_one_hyphen(self):
        self.assertEqual(shelfbuild.slug_base("Ocular Diseases and Behçet’s Syndrome"), "ocular-diseases-and-behcets-syndrome")
        self.assertEqual(shelfbuild.slug_base("Recreation. Leisure"), "recreation-leisure")
        self.assertEqual(shelfbuild.slug_base("Pb(II)   in  water!"), "pb-ii-in-water")

    def test_an_apostrophe_is_dropped_and_does_not_break_the_word(self):
        for name, want in (("Zygmunt Bauman's Sociology", "zygmunt-baumans-sociology"), ("Zygmunt Bauman’s Sociology", "zygmunt-baumans-sociology"),
                           ("Qur’anic Studies", "quranic-studies"), ("Benford‘s law", "benfords-law"), ("aʼb", "ab")):
            self.assertEqual(shelfbuild.slug_base(name), want)

    def test_a_greek_letter_is_written_as_its_name_and_other_letters_that_do_not_decompose_are_spelled(self):
        for name, want in (("TGF-β signaling   in diseases!", "tgf-beta-signaling-in-diseases"), ("NF-κB signaling", "nf-kappa-b-signaling"),
                           ("Wnt/β-catenin", "wnt-beta-catenin"), ("Δ and ς", "delta-and-sigma"), ("µ-opioid", "mu-opioid"),
                           ("Ørsted Straße", "orsted-strasse"), ("Ægir and Łódź", "aegir-and-lodz")):
            self.assertEqual(shelfbuild.slug_base(name), want)

    def test_two_names_that_differ_only_in_a_greek_letter_have_two_slugs(self):
        self.assertNotEqual(shelfbuild.slug_base("α-synuclein"), shelfbuild.slug_base("β-synuclein"))

    def test_a_name_with_no_letter_or_digit_has_no_slug(self):
        for name in ("", "...", "中文", "\u0001"):
            with self.assertRaises(KbError):
                shelfbuild.slug_base(name)

    def test_a_long_name_gives_a_slug_of_at_most_a_hundred_characters_that_does_not_end_in_a_hyphen(self):
        slug = shelfbuild.slug_base("word " * 60)
        self.assertLessEqual(len(slug), 100)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(shelfschema.SLUG.fullmatch(slug))

    def test_a_clash_is_resolved_by_the_level_and_then_by_a_number_in_the_order_of_the_file(self):
        slugs = shelfbuild.assign_slugs([("domain", "Social Sciences"), ("field", "Social Sciences"), ("topic", "Social Sciences"), ("topic", "Social sciences")])
        self.assertEqual(slugs, ["social-sciences", "social-sciences-field", "social-sciences-topic", "social-sciences-topic-2"])

    def test_the_slugs_do_not_depend_on_anything_but_the_names_and_their_order(self):
        names = [("domain", "A b"), ("field", "A b"), ("subfield", "a-b")]
        self.assertEqual(shelfbuild.assign_slugs(names), shelfbuild.assign_slugs(list(names)))
        self.assertEqual(shelfbuild.assign_slugs(names), ["a-b", "a-b-field", "a-b-subfield"])

    def test_a_derived_slug_is_never_taken_by_a_later_name_that_is_the_same_text(self):
        slugs = shelfbuild.assign_slugs([("domain", "X"), ("field", "X"), ("field", "X field")])
        self.assertEqual(len(set(slugs)), 3)
        self.assertEqual(slugs[:2], ["x", "x-field"])


class Scope(unittest.TestCase):
    def scope(self, description, name="Additive Manufacturing", level="topic", parent="Industrial Engineering"):
        return shelfbuild.scope_sentence(description, name, level, parent)

    def test_the_scope_is_the_first_sentence_of_a_description_that_is_one(self):
        self.assertEqual(self.scope("This cluster of papers covers 3D printing. It spans many methods."), "This cluster of papers covers 3D printing.")

    def test_a_description_with_one_sentence_and_no_full_stop_gets_one(self):
        self.assertEqual(self.scope("This cluster of papers covers 3D printing"), "This cluster of papers covers 3D printing.")

    def test_a_lowercase_phrase_becomes_a_sentence_that_names_the_shelf(self):
        self.assertEqual(self.scope("physics of elementary particles at high energies", name="Nuclear and High Energy Physics", level="subfield", parent="Physics and Astronomy"),
                         "Nuclear and High Energy Physics: physics of elementary particles at high energies.")
        self.assertEqual(self.scope("branch of natural science.", name="Physical Sciences", level="domain", parent=None), "Physical Sciences: branch of natural science.")

    def test_an_abbreviation_does_not_end_the_sentence(self):
        self.assertEqual(self.scope("This cluster of papers studies texts, e.g. Foo and the U.S. Army. Next one."), "This cluster of papers studies texts, e.g. Foo and the U.S. Army.")

    def test_white_space_is_made_single_spaces(self):
        self.assertEqual(self.scope("This  cluster\n of\tpapers.  Next."), "This cluster of papers.")

    def test_a_sentence_longer_than_the_limit_is_cut_at_a_word_and_ends_with_three_dots(self):
        text = "This cluster of papers " + "word " * 200
        scope = self.scope(text)
        self.assertLessEqual(len(scope), shelfschema.SCOPE_MAX)
        self.assertTrue(scope.endswith("..."))
        self.assertFalse(scope[:-3].endswith(" "))

    def test_no_description_gives_the_fixed_sentence(self):
        self.assertEqual(self.scope("", name="Bioengineering", level="subfield", parent="Engineering"), "Works on Bioengineering, a subfield of Engineering.")
        self.assertEqual(self.scope("  ", name="Zebras", level="topic", parent="Animals"), "Works on Zebras, a topic of Animals.")
        self.assertEqual(self.scope(None, name="Arts", level="field", parent="Humanities"), "Works on Arts, a field of Humanities.")
        self.assertEqual(self.scope("", name="Humanities", level="domain", parent=None), "Works on Humanities, a domain of OpenAlex.")

    def test_a_description_that_is_not_text_is_refused(self):
        for bad in (5, ["x"], {"a": 1}):
            with self.assertRaises(KbError):
                self.scope(bad)


class Manifest(unittest.TestCase):
    def test_it_is_the_hash_of_the_lines_name_space_hash_sorted_by_name(self):
        one, two = "a" * 64, "b" * 64
        want = hashlib.sha256(("a.json %s\nb.json %s\n" % (one, two)).encode("utf-8")).hexdigest()
        self.assertEqual(shelfbuild.manifest_sha256([("b.json", two), ("a.json", one)]), want)

    def test_a_line_is_the_name_a_space_the_hash_and_a_newline(self):
        # the format fixed by Increments B and C, seen on a small case (the real read has 51 and 21 lines)
        self.assertEqual(shelfbuild.manifest_sha256([("x", "0" * 64)]), hashlib.sha256(("x " + "0" * 64 + "\n").encode()).hexdigest())


class Building(unittest.TestCase):
    def setUp(self):
        self.inputs = Inputs(self)
        self.result = self.inputs.build()
        self.data = json.loads(self.result["bytes"].decode("utf-8"))

    def test_the_file_passes_the_checker_and_has_the_counts_of_the_inputs(self):
        self.assertEqual(shelfschema.check_schema(self.data), [])
        self.assertEqual(shelfschema.counts(self.data), {"domain": 2, "field": 2, "subfield": 3, "topic": 4, "custom": 2})
        self.assertEqual(self.result["counts"], {"domain": 2, "field": 2, "subfield": 3, "topic": 4, "custom": 2})

    def test_every_record_of_the_saved_lists_is_a_shelf_and_every_identifier_is_the_short_form(self):
        identifiers = sorted(s["openalex"] for s in self.data["shelves"] if s["openalex"])
        self.assertEqual(identifiers, sorted(["domains/2", "domains/3", "fields/22", "fields/33", "subfields/2209", "subfields/3312", "subfields/3614", "T10001", "T10002", "T10003", "T10004"]))

    def test_the_parents_are_the_slugs_of_the_parent_records(self):
        topic = by_name(self.result, "Additive Manufacturing")
        sub = by_name(self.result, "Industrial and Manufacturing Engineering")
        field = by_name(self.result, "Engineering")
        domain = by_name(self.result, "Physical Sciences")
        self.assertEqual((topic["parent"], sub["parent"], field["parent"], domain["parent"]), (sub["slug"], field["slug"], domain["slug"], None))

    def test_two_records_with_one_name_get_two_slugs_the_same_way_each_time(self):
        domain, field, topic = by_name(self.result, "Social Sciences", "domain"), by_name(self.result, "Social Sciences", "field"), by_name(self.result, "Social Sciences", "topic")
        self.assertEqual((domain["slug"], field["slug"], topic["slug"]), ("social-sciences", "social-sciences-field", "social-sciences-topic"))
        self.assertEqual(self.inputs.build()["bytes"], self.result["bytes"])

    def test_a_subfield_with_no_topic_is_a_shelf(self):
        self.assertEqual(by_name(self.result, "Radiological Technology")["level"], "subfield")

    def test_a_custom_shelf_has_its_code_its_name_its_scope_and_no_parent_and_no_openalex_identifier(self):
        shelf = by_name(self.result, "Handicrafts. Arts and crafts")
        self.assertEqual((shelf["level"], shelf["lcc"], shelf["openalex"], shelf["parent"], shelf["slug"]), ("custom", "TT", None, None, "handicrafts-arts-and-crafts"))
        self.assertEqual(shelf["scope"], "Handicrafts and the arts and crafts: making things by hand.")

    def test_a_custom_parent_is_the_slug_of_a_domain_when_the_custom_file_names_one(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(parent="physical-sciences"))
        shelf = by_name(self.inputs.build(), "Handicrafts. Arts and crafts")
        self.assertEqual(shelf["parent"], "physical-sciences")

    def test_the_scope_of_an_openalex_shelf_follows_the_rule(self):
        self.assertEqual(by_name(self.result, "Additive Manufacturing")["scope"], "This cluster of papers covers 3D printing.")
        self.assertEqual(by_name(self.result, "Physical Sciences")["scope"], "Physical Sciences: branch of natural science that studies non-living systems.")
        self.assertEqual(by_name(self.result, "Social Sciences", "topic")["scope"], "Works on Social Sciences, a topic of Sociology.")
        self.assertEqual(by_name(self.result, "Qur’anic Studies in the U.S.")["scope"], "This cluster of papers studies texts, e.g. in the U.S. and elsewhere.")
        self.assertLessEqual(len(by_name(self.result, "Sociology of Behçet")["scope"]), shelfschema.SCOPE_MAX)

    def test_the_order_is_by_level_then_name_then_identifier_and_the_custom_shelves_come_last_by_code(self):
        levels = [s["level"] for s in self.data["shelves"]]
        self.assertEqual(levels, ["domain"] * 2 + ["field"] * 2 + ["subfield"] * 3 + ["topic"] * 4 + ["custom"] * 2)
        self.assertEqual([s["name"] for s in self.data["shelves"] if s["level"] == "domain"], ["Physical Sciences", "Social Sciences"])
        self.assertEqual([s["lcc"] for s in self.data["shelves"] if s["level"] == "custom"], ["GV", "TT"])

    def test_the_order_of_the_records_in_the_saved_lists_does_not_change_the_file(self):
        shuffled = {level: list(reversed(rows)) for level, rows in oa_results().items()}
        self.inputs.write_openalex(shuffled, page_size=3)
        # the pages differ, so the hash of the source in the snapshot does too; the shelves do not
        self.assertEqual(shelves_of(self.inputs.build()), self.data["shelves"])

    def test_two_records_with_one_name_are_ordered_by_the_exact_name_and_then_the_identifier_as_text(self):
        results = oa_results()
        link = [("subfield", OA + "subfields/3312", "Sociology"), ("field", OA + "fields/33", "Social Sciences"), ("domain", OA + "domains/2", "Social Sciences")]
        results["topics"] += [record("", "T9", "Twin", "This cluster of papers is the one.", link), record("", "T10", "Twin", "This cluster of papers is the other.", link),
                              record("", "T11", "twin", "This cluster of papers is a third.", link)]
        self.inputs.write_openalex(results)
        built = {s["openalex"]: s["slug"] for s in shelves_of(self.inputs.build()) if s["openalex"] in ("T9", "T10", "T11")}
        # name case-folded, then the exact name ("Twin" before "twin"), then the identifier as text ("T10" before "T9")
        self.assertEqual(built, {"T10": "twin", "T9": "twin-topic", "T11": "twin-topic-2"})

    def test_the_order_of_the_custom_shelves_does_not_change_the_file(self):
        self.inputs.write_custom(lambda d: d["shelves"].reverse())
        self.assertEqual(shelves_of(self.inputs.build()), self.data["shelves"])

    def test_the_snapshot_names_each_source_with_its_hash(self):
        snap = self.data["snapshot"]
        self.assertEqual(snap["openalex"], {"url": "https://api.openalex.org", "retrieved": "2026-11-14", "sha256": self.inputs.oa_manifest()})
        self.assertEqual(snap["lcc"], {"url": INDEX_URL, "retrieved": "2026-11-14", "sha256": self.inputs.lcc_manifest()})
        with open(self.inputs.custom, "rb") as f:
            self.assertEqual(snap["custom"], {"sha256": sha(f.read())})

    def test_the_file_is_one_line_per_shelf_in_utf_8_and_ends_with_one_newline(self):
        text = self.result["bytes"].decode("utf-8")
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        shelf_lines = [l for l in text.splitlines() if l.lstrip().startswith('{"slug"')]
        self.assertEqual(len(shelf_lines), len(self.data["shelves"]))
        self.assertIn("Qur’anic", text)

    def test_the_same_inputs_give_the_same_bytes(self):
        self.assertEqual(self.inputs.build()["bytes"], self.result["bytes"])

    def test_it_reads_by_the_paths_it_is_given(self):
        other = Inputs(self)
        self.assertEqual(shelfbuild.build(other.openalex, other.lcc, other.custom)["bytes"], self.result["bytes"])


class Refusals(unittest.TestCase):
    def setUp(self):
        self.inputs = Inputs(self)

    def refused(self, text=None):
        with self.assertRaises(KbError) as caught:
            self.inputs.build()
        if text:
            self.assertIn(text, str(caught.exception))

    # --- the custom shelves against the outline
    def test_a_custom_entry_whose_code_is_not_in_the_outline_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(code="ZZ"))
        self.refused("ZZ")

    def test_a_custom_entry_whose_name_is_not_the_caption_of_its_code_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(name="Handicrafts"))
        self.refused("TT")

    def test_a_custom_entry_whose_page_is_not_the_file_that_holds_its_code_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(page=PDF_URL % "g"))
        self.refused("TT")

    def test_a_custom_file_made_from_another_read_of_the_outline_is_refused(self):
        self.inputs.write_custom(source_sha="e" * 64)
        self.refused("outline")

    def test_a_custom_file_that_the_checker_refuses_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].pop("reason"))
        self.refused("checker")
        self.inputs.write_custom(lambda d: d.update(extra=1))
        self.refused("checker")

    def test_a_custom_file_with_a_repeated_key_is_refused(self):
        with open(self.inputs.custom, "rb") as f:
            text = f.read().decode("utf-8")
        with open(self.inputs.custom, "wb") as f:
            f.write(text.replace('"format": 1,', '"format": 1, "format": 1,', 1).encode("utf-8"))
        self.refused("custom shelves")

    def test_a_page_with_a_repeated_key_is_refused(self):
        def change(report):
            raw = b'{"results": [], "results": []}'
            with open(os.path.join(self.inputs.openalex, "domains-001.json"), "wb") as f:
                f.write(raw)
            report["files"][0].update(sha256=sha(raw), bytes=len(raw), results=0)
        self.inputs.write_openalex(oa_results(), mutate=change)
        self.refused("domains-001.json")

    def test_a_custom_shelf_with_the_name_of_an_openalex_shelf_gets_the_level_in_its_slug(self):
        results = oa_results()
        results["topics"].append(record("", "T10005", "Photography", "This cluster of papers covers cameras.",
                                        [("subfield", OA + "subfields/3312", "Sociology"), ("field", OA + "fields/33", "Social Sciences"), ("domain", OA + "domains/2", "Social Sciences")]))
        self.inputs.write_openalex(results)
        self.inputs.write_custom(lambda d: d["shelves"].append({"code": "TR", "name": "Photography", "parent": None, "scope": "Photography: the making of photographs.",
                                                                "reason": "r", "page": PDF_URL % "t", "retrieved": "2026-11-14"}))
        built = self.inputs.build()
        self.assertEqual(by_name(built, "Photography", "topic")["slug"], "photography")
        self.assertEqual(by_name(built, "Photography", "custom")["slug"], "photography-custom")

    def test_two_custom_entries_with_one_code_are_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"].append(copy.deepcopy(d["shelves"][0])))
        self.refused()

    # --- the saved files against their reports
    def test_a_saved_page_that_does_not_match_its_recorded_hash_is_refused(self):
        with open(os.path.join(self.inputs.openalex, "topics-001.json"), "ab") as f:
            f.write(b" ")
        self.refused("topics-001.json")

    def test_a_saved_page_of_the_outline_that_does_not_match_its_recorded_hash_is_refused(self):
        with open(os.path.join(self.inputs.lcc, "lcco_t.pdf"), "ab") as f:
            f.write(b" ")
        self.refused("lcco_t.pdf")

    def test_a_missing_saved_page_is_refused(self):
        os.remove(os.path.join(self.inputs.openalex, "fields-001.json"))
        self.refused("fields-001.json")

    def test_a_file_name_in_a_report_that_could_leave_the_folder_is_refused(self):
        for bad in ("../x.json", "/etc/passwd", "a/b.json", ".hidden", "", "a b.json", "x" * 80):
            self.inputs.write_openalex(oa_results(), mutate=lambda r, bad=bad: r["files"][0].update(file=bad))
            self.refused()

    def test_a_file_name_that_names_a_real_file_outside_the_folder_is_refused_for_its_name(self):
        # the file exists and matches its recorded hash, so only the rule about the name can refuse it
        def change(report):
            with open(os.path.join(self.inputs.openalex, "domains-001.json"), "rb") as f:
                raw = f.read()
            with open(os.path.join(self.inputs.root, "outside.json"), "wb") as f:
                f.write(raw)
            report["files"][0].update(file="../outside.json")
        self.inputs.write_openalex(oa_results(), mutate=change)
        self.refused("plain file name")

    def test_a_count_of_a_page_that_is_not_the_number_of_its_results_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r["files"][0].update(results=99))
        self.refused("results")

    def test_a_report_of_a_read_that_did_not_finish_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r.update(status="failed"))
        self.refused("status")

    def test_a_report_whose_level_count_does_not_match_the_pages_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r["levels"]["topics"].update(count=5))
        self.refused("topics")

    def test_a_report_with_no_page_of_a_level_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r.update(files=[e for e in r["files"] if e["level"] != "topics"]))
        self.refused("topics")

    def test_a_page_of_an_unknown_level_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r["files"][0].update(level="authors"))
        self.refused()

    def test_an_extract_made_from_another_report_is_refused(self):
        self.inputs.write_lcc(mutate_extract=lambda e: e.update(report_sha256="c" * 64))
        self.refused("extract")

    def test_a_file_that_is_a_link_or_not_a_regular_file_is_refused(self):
        target = os.path.join(self.inputs.openalex, "topics-001.json")
        os.rename(target, target + ".real")
        os.mkdir(target)
        self.refused("topics-001.json")

    def test_a_report_of_another_source_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r.update(source="https://example.org"))
        self.refused("source")
        self.inputs.write_openalex(oa_results())
        self.inputs.write_lcc(mutate_report=lambda r: r.update(source="https://example.org"))
        self.refused("source")

    def test_a_report_with_no_start_time_or_a_bad_one_is_refused(self):
        for bad in (None, 5, "", "yesterday", "2026-13-40T00:00:00Z"):
            self.inputs.write_openalex(oa_results(), mutate=lambda r, bad=bad: r.update(started=bad))
            self.refused("started")

    def test_a_file_named_twice_in_a_report_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r["files"].append(dict(r["files"][0])))
        self.refused("twice")

    def test_a_report_with_a_hash_that_is_not_a_hash_is_refused(self):
        self.inputs.write_openalex(oa_results(), mutate=lambda r: r["files"][0].update(sha256="A" * 64))
        self.refused("lowercase hex")

    def test_a_report_of_the_outline_with_no_index_page_is_refused(self):
        self.inputs.write_lcc(mutate_report=lambda r: r.update(files=[e for e in r["files"] if e["file"] != "index.html"]))
        self.refused("index")

    def test_an_extract_that_holds_a_code_twice_or_a_malformed_subclass_is_refused(self):
        self.inputs.write_lcc(mutate_extract=lambda e: e["subclasses"].append(dict(e["subclasses"][0])))
        self.refused("twice")
        self.inputs.write_lcc(mutate_extract=lambda e: e["subclasses"].append({"code": "ZZ"}))
        self.refused("subclass")
        self.inputs.write_lcc(mutate_extract=lambda e: e.update(subclasses=None))
        self.refused("no list")

    def test_a_custom_file_made_from_another_address_of_the_outline_is_refused(self):
        self.inputs.write_custom(lambda d: d["source"].update(url="https://example.org/other"))
        self.refused("outline")

    def test_a_custom_parent_that_is_not_a_domain_of_the_file_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(parent="no-such-shelf"))
        self.refused("checker")
        self.inputs.write_custom(lambda d: d["shelves"][0].update(parent="engineering"))
        self.refused("checker")

    def test_a_saved_page_that_is_a_link_is_refused(self):
        target = os.path.join(self.inputs.openalex, "topics-001.json")
        os.rename(target, target + ".real")
        os.symlink(target + ".real", target)
        self.refused("topics-001.json")

    def test_a_saved_page_that_is_a_named_pipe_is_refused_without_waiting(self):
        import threading
        target = os.path.join(self.inputs.openalex, "topics-001.json")
        os.rename(target, target + ".real")
        os.mkfifo(target)
        outcome = []

        def attempt():
            try:
                self.inputs.build()
                outcome.append("built")
            except KbError as e:
                outcome.append("refused")
        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(5)
        if worker.is_alive():
            fd = os.open(target, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            worker.join(5)
            self.fail("the builder waited for a pipe")
        self.assertEqual(outcome, ["refused"])

    def test_a_file_over_the_size_limit_is_refused(self):
        import unittest.mock
        with unittest.mock.patch.object(shelfbuild, "MAX_FILE", 100):
            self.refused("larger")

    def test_a_custom_file_that_is_missing_is_refused(self):
        os.remove(self.inputs.custom)
        self.refused("custom")

    # --- the content of the lists
    def rebuild_with(self, change):
        results = oa_results()
        change(results)
        self.inputs.write_openalex(results)
        self.refused()

    def test_a_duplicate_identifier_is_refused(self):
        self.rebuild_with(lambda r: r["topics"].append(copy.deepcopy(r["topics"][0])))

    def test_a_topic_with_an_unknown_subfield_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0]["subfield"].update(id=OA + "subfields/1"))

    def test_a_topic_whose_field_is_not_the_field_of_its_subfield_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0]["field"].update(id=OA + "fields/33"))

    def test_a_topic_whose_domain_is_not_the_domain_of_its_subfield_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0]["domain"].update(id=OA + "domains/2"))

    def test_a_subfield_with_no_field_or_an_unknown_one_is_refused(self):
        self.rebuild_with(lambda r: r["subfields"][0].pop("field"))
        self.rebuild_with(lambda r: r["subfields"][0]["field"].update(id=OA + "fields/1"))

    def test_a_field_with_an_unknown_domain_is_refused(self):
        self.rebuild_with(lambda r: r["fields"][0]["domain"].update(id=OA + "domains/9"))

    def test_a_record_with_no_name_or_a_name_that_is_not_text_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0].pop("display_name"))
        self.rebuild_with(lambda r: r["topics"][0].update(display_name=5))

    def test_an_identifier_of_another_kind_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0].update(id="https://example.org/T10001"))
        self.rebuild_with(lambda r: r["subfields"][0].update(id=OA + "fields/2209"))
        self.rebuild_with(lambda r: r["topics"][0].update(id=OA + "T1/../x"))

    def test_a_name_with_no_slug_is_refused(self):
        self.rebuild_with(lambda r: r["topics"][0].update(display_name="中文"))

    def test_a_level_that_is_not_text_is_refused_and_not_a_crash(self):
        for bad in ([1], {"a": 1}, None, 5):
            self.inputs.write_openalex(oa_results(), mutate=lambda r, bad=bad: r["files"][0].update(level=bad))
            self.refused("unknown level")

    def test_a_report_that_lists_too_many_files_or_too_many_bytes_is_refused(self):
        import unittest.mock
        with unittest.mock.patch.object(shelfbuild, "MAX_FILES", 3):
            self.refused("entries")
        with unittest.mock.patch.object(shelfbuild, "MAX_TOTAL", 200):
            self.refused("together")

    def test_a_page_that_is_not_a_list_of_results_is_refused(self):
        raw = json.dumps({"results": "no"}).encode()
        name = os.path.join(self.inputs.openalex, "domains-001.json")
        with open(name, "wb") as f:
            f.write(raw)
        self.refused("domains-001.json")  # the report still names the old hash, so this is refused first as a changed file

    def test_a_page_that_is_not_a_list_of_results_is_refused_even_when_the_report_names_its_hash(self):
        def change(report):
            raw = json.dumps({"results": "no"}).encode()
            with open(os.path.join(self.inputs.openalex, "domains-001.json"), "wb") as f:
                f.write(raw)
            report["files"][0].update(sha256=sha(raw), bytes=len(raw))
        self.inputs.write_openalex(oa_results(), mutate=change)
        self.refused("domains-001.json")

    def test_nothing_is_written_when_the_build_is_refused(self):
        self.inputs.write_custom(lambda d: d["shelves"][0].update(code="ZZ"))
        out = os.path.join(self.inputs.root, "schema.json")
        with self.assertRaises(KbError):
            shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, out)
        self.assertFalse(os.path.exists(out))


class Writing(unittest.TestCase):
    def setUp(self):
        self.inputs = Inputs(self)
        self.out = os.path.join(self.inputs.root, "schema.json")

    def test_it_writes_the_bytes_it_built_and_the_file_passes_the_checker(self):
        summary = shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        with open(self.out, "rb") as f:
            written = f.read()
        self.assertEqual(written, self.inputs.build()["bytes"])
        self.assertEqual(shelfschema.report(self.out)["problems"], [])
        self.assertEqual(summary["sha256"], sha(written))
        self.assertEqual(summary["counts"]["topic"], 4)

    def test_it_refuses_to_replace_a_file_that_exists_and_leaves_it_as_it_was(self):
        with open(self.out, "wb") as f:
            f.write(b"old")
        with self.assertRaises(KbError):
            shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_it_does_not_write_through_a_link(self):
        target = os.path.join(self.inputs.root, "elsewhere.json")
        with open(target, "wb") as f:
            f.write(b"keep")
        os.symlink(target, self.out)
        with self.assertRaises(KbError):
            shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"keep")

    def test_the_folder_of_the_output_must_exist(self):
        with self.assertRaises(KbError):
            shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, os.path.join(self.inputs.root, "no-such-folder", "schema.json"))

    def test_a_failed_write_leaves_no_file(self):
        import unittest.mock
        with unittest.mock.patch("os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        self.assertFalse(os.path.exists(self.out))

    def test_the_mode_does_not_depend_on_the_umask(self):
        old = os.umask(0o077)
        try:
            shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o644)

    def test_it_changes_none_of_its_inputs(self):
        def state():
            out = {}
            for folder in (self.inputs.openalex, self.inputs.lcc):
                for name in sorted(os.listdir(folder)):
                    with open(os.path.join(folder, name), "rb") as f:
                        out[(folder, name)] = (os.stat(os.path.join(folder, name)).st_mtime_ns, f.read())
            with open(self.inputs.custom, "rb") as f:
                out["custom"] = (os.stat(self.inputs.custom).st_mtime_ns, f.read())
            return out
        before = state()
        shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        self.assertEqual(state(), before)

    def test_the_file_is_readable_by_everyone_and_writable_by_the_owner_only(self):
        shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o644)

    def test_a_second_build_into_another_file_gives_the_same_bytes(self):
        second = os.path.join(self.inputs.root, "second.json")
        shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, self.out)
        shelfbuild.run(self.inputs.openalex, self.inputs.lcc, self.inputs.custom, second)
        with open(self.out, "rb") as a, open(second, "rb") as b:
            self.assertEqual(a.read(), b.read())


class Command(unittest.TestCase):
    def run_command(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kbmain.main(["shelf-schema-build", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_it_builds_the_file_and_prints_the_counts_and_the_hashes(self):
        inputs = Inputs(self)
        out = os.path.join(inputs.root, "schema.json")
        code, text, _ = self.run_command("--openalex", inputs.openalex, "--lcc", inputs.lcc, "--custom", inputs.custom, "--out", out)
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertEqual(report["counts"], {"domain": 2, "field": 2, "subfield": 3, "topic": 4, "custom": 2})
        self.assertEqual(report["snapshot"]["openalex"]["sha256"], inputs.oa_manifest())
        self.assertTrue(os.path.exists(out))

    def test_a_refusal_exits_two_and_writes_nothing(self):
        inputs = Inputs(self)
        inputs.write_custom(lambda d: d["shelves"][0].update(code="ZZ"))
        out = os.path.join(inputs.root, "schema.json")
        code, text, err = self.run_command("--openalex", inputs.openalex, "--lcc", inputs.lcc, "--custom", inputs.custom, "--out", out)
        self.assertEqual((code, text), (2, ""))
        self.assertIn("refused", err)
        self.assertFalse(os.path.exists(out))

    def test_every_argument_is_required_and_none_is_built_in(self):
        for argv in ([], ["--openalex", "a", "--lcc", "b", "--custom", "c"], ["--lcc", "b", "--custom", "c", "--out", "d"]):
            with self.assertRaises(SystemExit):
                self.run_command(*argv)

    def test_it_needs_no_library_and_no_config(self):
        import unittest.mock
        inputs = Inputs(self)
        out = os.path.join(inputs.root, "schema.json")
        with unittest.mock.patch("kb.config.load", side_effect=AssertionError("the config was read")):
            code, _, _ = self.run_command("--openalex", inputs.openalex, "--lcc", inputs.lcc, "--custom", inputs.custom, "--out", out)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
