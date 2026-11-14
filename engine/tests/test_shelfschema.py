"""The checker of the shelf schema file (`kb/shelfschema.py`, Increment A of the plan `2026-11-14-build-the-shelf-schema`).

The checker reads one JSON file as data and finds problems in it; these tests need no library, no network and no model, and use only the standard library.
Run them with `python3 -m unittest engine.tests.test_shelfschema`."""
import contextlib
import copy
import io
import json
import os
import tempfile
import threading
import unittest
import unittest.mock

from kb import KbError, shelfschema
from kb import __main__ as kbmain

SHA = "a" * 64


def fixture():
    """A small valid schema: two domains, a field, two subfields, three topics and a custom shelf."""
    def shelf(slug, name, level, parent, openalex, lcc=None, scope=None):
        return {"slug": slug, "name": name, "level": level, "parent": parent, "openalex": openalex, "lcc": lcc,
                "scope": scope or "Works on %s." % name}
    return {
        "format": 1,
        "snapshot": {"openalex": {"url": "https://example.org/openalex", "retrieved": "2026-11-14", "sha256": SHA},
                     "lcc": {"url": "https://example.org/lcc", "retrieved": "2026-11-14", "sha256": SHA},
                     "custom": {"sha256": SHA}},
        "shelves": [
            shelf("physical-sciences", "Physical Sciences", "domain", None, "D3"),
            shelf("life-sciences", "Life Sciences", "domain", None, "D1"),
            shelf("engineering", "Engineering", "field", "physical-sciences", "F22"),
            shelf("industrial-engineering", "Industrial Engineering", "subfield", "engineering", "S2209"),
            shelf("control-engineering", "Control Engineering", "subfield", "engineering", "S2207"),
            shelf("additive-manufacturing", "Additive Manufacturing", "topic", "industrial-engineering", "T10001"),
            shelf("process-control", "Process Control", "topic", "control-engineering", "T10002"),
            shelf("robot-control", "Robot Control", "topic", "control-engineering", "T10003"),
            shelf("handicrafts", "Handicrafts", "custom", None, None, lcc="TT", scope="Handwork and crafts."),
        ],
    }


def custom_fixture():
    return {"format": 1,
            "source": {"url": "https://example.org/lcc", "retrieved": "2026-11-14", "sha256": SHA},
            "shelves": [{"code": "TT", "name": "Handicrafts. Arts and crafts", "parent": None, "scope": "Handwork and crafts.",
                         "reason": "OpenAlex has no subfield for crafts.", "page": "https://example.org/lcc/T", "retrieved": "2026-11-14"},
                        {"code": "GV", "name": "Recreation. Leisure", "parent": "social-sciences", "scope": "Sports, games and leisure.",
                         "reason": "Recreation fits no subfield.", "page": "https://example.org/lcc/G", "retrieved": "2026-11-14"}]}


def mutate(change):
    data = fixture()
    change(data)
    return data


def one(data, slug):
    return next(s for s in data["shelves"] if s["slug"] == slug)


class SchemaCase(unittest.TestCase):
    def problems(self, data):
        return shelfschema.check_schema(data)

    def assertProblem(self, data, *words):
        found = self.problems(data)
        self.assertTrue(found, "no problem was found")
        text = " | ".join(found).lower()
        for word in words:
            self.assertIn(word.lower(), text, found)


class ValidSchema(SchemaCase):
    def test_a_valid_file_has_no_problem(self):
        self.assertEqual(self.problems(fixture()), [])

    def test_counts_by_level(self):
        self.assertEqual(shelfschema.counts(fixture()), {"domain": 2, "field": 1, "subfield": 2, "topic": 3, "custom": 1})

    def test_a_custom_shelf_may_sit_under_a_domain(self):
        data = mutate(lambda d: one(d, "handicrafts").update(parent="life-sciences"))
        self.assertEqual(self.problems(data), [])


class BrokenSchema(SchemaCase):
    def test_a_duplicate_slug(self):
        def change(d):
            twin = copy.deepcopy(one(d, "robot-control"))
            twin["openalex"] = "T99999"
            d["shelves"].append(twin)
        found = self.problems(mutate(change))
        self.assertEqual(len(found), 1, found)
        self.assertIn("duplicate slug", found[0])
        self.assertIn("robot-control", found[0])

    def test_a_duplicate_openalex_identifier(self):
        data = mutate(lambda d: one(d, "robot-control").update(openalex="T10002"))
        self.assertProblem(data, "duplicate", "T10002")

    def test_a_duplicate_lcc_code(self):
        def change(d):
            d["shelves"].append({"slug": "crafts-two", "name": "Crafts Two", "level": "custom", "parent": None, "openalex": None, "lcc": "TT", "scope": "Crafts."})
        self.assertProblem(mutate(change), "duplicate", "TT")

    def test_a_missing_parent(self):
        data = mutate(lambda d: one(d, "robot-control").update(parent="no-such-shelf"))
        self.assertProblem(data, "robot-control", "parent", "no-such-shelf")

    def test_a_topic_under_a_field(self):
        data = mutate(lambda d: one(d, "robot-control").update(parent="engineering"))
        self.assertProblem(data, "robot-control", "level")

    def test_a_subfield_under_a_domain(self):
        data = mutate(lambda d: one(d, "control-engineering").update(parent="physical-sciences"))
        self.assertProblem(data, "control-engineering", "level")

    def test_a_domain_with_a_parent(self):
        data = mutate(lambda d: one(d, "life-sciences").update(parent="physical-sciences"))
        self.assertProblem(data, "life-sciences", "parent")

    def test_a_topic_with_no_parent(self):
        data = mutate(lambda d: one(d, "robot-control").update(parent=None))
        self.assertProblem(data, "robot-control", "parent")

    def test_a_cycle(self):
        def change(d):
            one(d, "process-control").update(parent="robot-control")
            one(d, "robot-control").update(parent="process-control")
        self.assertProblem(mutate(change), "cycle")

    def test_a_custom_shelf_under_a_topic(self):
        data = mutate(lambda d: one(d, "handicrafts").update(parent="robot-control"))
        self.assertProblem(data, "handicrafts", "custom")

    def test_a_custom_shelf_under_a_field(self):
        data = mutate(lambda d: one(d, "handicrafts").update(parent="engineering"))
        self.assertProblem(data, "handicrafts", "custom")

    def test_a_missing_field_of_a_shelf(self):
        def change(d):
            del one(d, "robot-control")["scope"]
        self.assertProblem(mutate(change), "robot-control", "scope")

    def test_a_field_the_schema_does_not_know(self):
        for extra in ("state", "priority", "count", "scout"):
            with self.subTest(extra=extra):
                data = mutate(lambda d: one(d, "robot-control").update({extra: 1}))
                self.assertProblem(data, "robot-control", extra)

    def test_a_top_level_field_it_does_not_know(self):
        data = mutate(lambda d: d.update(state={}))
        self.assertProblem(data, "state")

    def test_a_slug_with_capitals_or_spaces_or_other_marks(self):
        for bad in ("Robot-Control", "robot control", "robot_control", "robot--control", "-robot", "robot-", "", "roöbot"):
            with self.subTest(slug=bad):
                data = mutate(lambda d: one(d, "robot-control").update(slug=bad))
                self.assertProblem(data, "slug")

    def test_an_unknown_level(self):
        data = mutate(lambda d: one(d, "robot-control").update(level="subtopic"))
        self.assertProblem(data, "robot-control", "level")

    def test_an_unknown_format_number(self):
        for bad in (2, 0, "1", True, None, 1.0):
            with self.subTest(format=bad):
                data = mutate(lambda d: d.update(format=bad))
                self.assertProblem(data, "format")

    def test_a_value_of_the_wrong_type(self):
        for key, bad in (("name", 5), ("scope", None), ("openalex", 7), ("slug", ["a"]), ("level", 3)):
            with self.subTest(key=key):
                data = mutate(lambda d: one(d, "robot-control").update({key: bad}))
                self.assertTrue(self.problems(data))

    def test_text_with_control_characters_or_too_long(self):
        data = mutate(lambda d: one(d, "robot-control").update(name="Robot\nControl"))
        self.assertProblem(data, "robot-control", "name")
        data = mutate(lambda d: one(d, "robot-control").update(scope="x" * 600))
        self.assertProblem(data, "robot-control", "scope")

    def test_a_non_custom_shelf_needs_an_openalex_identifier_and_no_lcc_code(self):
        data = mutate(lambda d: one(d, "robot-control").update(openalex=None))
        self.assertProblem(data, "robot-control", "openalex")
        found = self.problems(mutate(lambda d: one(d, "robot-control").update(lcc="ZZ")))
        self.assertEqual(len(found), 1, found)
        self.assertIn("lcc", found[0])
        self.assertIn("robot-control", found[0])

    def test_a_custom_shelf_needs_an_lcc_code_and_no_openalex_identifier(self):
        data = mutate(lambda d: one(d, "handicrafts").update(lcc=None))
        self.assertProblem(data, "handicrafts", "lcc")
        data = mutate(lambda d: one(d, "handicrafts").update(openalex="D9"))
        self.assertProblem(data, "handicrafts", "openalex")

    def test_a_bad_snapshot(self):
        data = mutate(lambda d: d["snapshot"]["openalex"].update(sha256="xyz"))
        self.assertProblem(data, "snapshot", "sha256")
        data = mutate(lambda d: d["snapshot"]["lcc"].update(retrieved="14 Nov 2026"))
        self.assertProblem(data, "snapshot", "retrieved")
        data = mutate(lambda d: d["snapshot"]["lcc"].update(retrieved="2026-13-45"))
        self.assertProblem(data, "snapshot", "retrieved")
        for odd in ("20261114", "2026-W46-5", "2026-11-14T00:00:00", " 2026-11-14"):
            with self.subTest(retrieved=odd):
                data = mutate(lambda d: d["snapshot"]["lcc"].update(retrieved=odd))
                self.assertProblem(data, "snapshot", "retrieved")
        data = mutate(lambda d: d["snapshot"].pop("custom"))
        self.assertProblem(data, "snapshot", "custom")
        data = mutate(lambda d: d["snapshot"]["openalex"].update(url="file:///etc/passwd"))
        self.assertProblem(data, "snapshot", "url")

    def test_an_unknown_snapshot_source_or_field(self):
        data = mutate(lambda d: d["snapshot"].update(weave={"sha256": SHA}))
        self.assertProblem(data, "snapshot", "weave")
        data = mutate(lambda d: d["snapshot"]["openalex"].update(count=4516))
        self.assertProblem(data, "snapshot", "count")
        data = mutate(lambda d: d["snapshot"]["custom"].update(url="https://example.org/x"))
        self.assertProblem(data, "snapshot", "url")

    def test_no_shelf_at_all(self):
        self.assertProblem(mutate(lambda d: d.update(shelves=[])), "shelves")
        self.assertProblem(mutate(lambda d: d.update(shelves="none")), "shelves")

    def test_a_shelf_that_is_not_an_object(self):
        self.assertProblem(mutate(lambda d: d["shelves"].append("a shelf")), "shelf")

    def test_the_top_of_the_file_is_not_an_object(self):
        self.assertTrue(shelfschema.check_schema([]))
        self.assertTrue(shelfschema.check_schema("x"))

    def test_each_problem_names_the_shelf(self):
        data = mutate(lambda d: one(d, "robot-control").update(parent="no-such-shelf"))
        self.assertTrue(any("robot-control" in p for p in self.problems(data)))

    def test_many_problems_are_cut_and_the_cut_is_said(self):
        data = mutate(lambda d: d["shelves"].extend({"slug": "BAD %d" % i} for i in range(400)))
        found = self.problems(data)
        self.assertLessEqual(len(found), shelfschema.MAX_PROBLEMS + 1)
        self.assertIn("more", found[-1])


HOSTILE = (None, True, False, 0, -1, 1.5, 10 ** 400, "", "x", "x" * 1000, [], ["x"], [["x"]], {}, {"a": 1}, {"a": {"b": ["c"]}})


class HostileValues(unittest.TestCase):
    """A value of any JSON type in any place must give a problem and never a crash (the file may be hostile)."""

    def write(self, data):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, "schema.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def everything(self, path, custom):
        return shelfschema.report(path, custom=custom)

    def test_a_list_or_a_dict_as_the_level_is_reported_and_does_not_crash(self):
        for bad in (["x"], {"a": 1}, [], None, 5, True):
            with self.subTest(level=bad):
                found = self.everything(self.write(mutate(lambda d: one(d, "robot-control").update(level=bad))), False)
                self.assertTrue(any("robot-control" in p and "level" in p for p in found["problems"]), found["problems"])

    def test_the_command_reports_a_hostile_level_and_exits_one(self):
        out, err = io.StringIO(), io.StringIO()
        path = self.write(mutate(lambda d: one(d, "robot-control").update(level=["x"])))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kbmain.main(["shelf-schema-check", path])
        self.assertEqual(code, 1)
        self.assertTrue(any("robot-control" in p for p in json.loads(out.getvalue())["problems"]))

    def test_no_value_in_any_place_of_the_schema_crashes_the_checker(self):
        def places():
            base = fixture()
            for key in base:
                yield (key,)
            for key in base["snapshot"]:
                yield ("snapshot", key)
                for inner in base["snapshot"][key]:
                    yield ("snapshot", key, inner)
            for index, shelf in enumerate(base["shelves"]):
                yield ("shelves", index)
                for key in shelf:
                    yield ("shelves", index, key)
        for place in places():
            for bad in HOSTILE:
                with self.subTest(place=place, value=repr(bad)[:30]):
                    data = fixture()
                    target = data
                    for step in place[:-1]:
                        target = target[step]
                    target[place[-1]] = bad
                    found = self.everything(self.write(data), False)
                    self.assertIsInstance(found["problems"], list)

    def test_no_value_in_any_place_of_the_custom_file_crashes_the_checker(self):
        base = custom_fixture()
        places = [(k,) for k in base] + [("source", k) for k in base["source"]] + [("shelves", 0)] + [("shelves", 0, k) for k in base["shelves"][0]]
        for place in places:
            for bad in HOSTILE:
                with self.subTest(place=place, value=repr(bad)[:30]):
                    data = custom_fixture()
                    target = data
                    for step in place[:-1]:
                        target = target[step]
                    target[place[-1]] = bad
                    found = self.everything(self.write(data), True)
                    self.assertIsInstance(found["problems"], list)

    def test_a_file_that_is_not_an_object_has_no_counts_and_does_not_crash(self):
        for content in ([], "x", 5, None, [1, 2]):
            with self.subTest(content=content):
                found = self.everything(self.write(content), False)
                self.assertTrue(found["problems"])
                self.assertEqual(found["shelves"], 0)


class CustomFile(unittest.TestCase):
    def test_a_valid_file(self):
        self.assertEqual(shelfschema.check_custom(custom_fixture()), [])

    def test_counts(self):
        self.assertEqual(shelfschema.custom_counts(custom_fixture()), {"custom": 2})

    def test_a_duplicate_code(self):
        data = custom_fixture()
        data["shelves"][1]["code"] = "TT"
        self.assertTrue(any("duplicate" in p.lower() for p in shelfschema.check_custom(data)))

    def test_a_bad_code(self):
        for bad in ("tt", "T1", "", "TTTT", 5, None):
            with self.subTest(code=bad):
                data = custom_fixture()
                data["shelves"][0]["code"] = bad
                self.assertTrue(shelfschema.check_custom(data))

    def test_a_field_it_does_not_know(self):
        data = custom_fixture()
        data["shelves"][0]["priority"] = 3
        self.assertTrue(any("priority" in p for p in shelfschema.check_custom(data)))

    def test_a_top_level_field_it_does_not_know(self):
        data = custom_fixture()
        data["state"] = {}
        self.assertTrue(any("state" in p for p in shelfschema.check_custom(data)))

    def test_an_empty_list_and_a_file_that_is_not_an_object(self):
        data = custom_fixture()
        data["shelves"] = []
        self.assertTrue(shelfschema.check_custom(data))
        self.assertTrue(shelfschema.check_custom([]))

    def test_a_missing_field(self):
        for key in ("name", "scope", "reason", "page", "retrieved", "parent"):
            with self.subTest(key=key):
                data = custom_fixture()
                del data["shelves"][0][key]
                self.assertTrue(shelfschema.check_custom(data))

    def test_a_bad_source_page_or_date_or_parent(self):
        data = custom_fixture()
        data["shelves"][0]["page"] = "ftp://example.org/x"
        self.assertTrue(shelfschema.check_custom(data))
        data = custom_fixture()
        data["shelves"][0]["retrieved"] = "yesterday"
        self.assertTrue(shelfschema.check_custom(data))
        data = custom_fixture()
        data["shelves"][0]["parent"] = "Not A Slug"
        self.assertTrue(shelfschema.check_custom(data))

    def test_a_bad_format_number_or_source(self):
        data = custom_fixture()
        data["format"] = 2
        self.assertTrue(shelfschema.check_custom(data))
        data = custom_fixture()
        data["source"]["sha256"] = "nope"
        self.assertTrue(shelfschema.check_custom(data))

    def test_the_source_has_exactly_its_three_fields(self):
        data = custom_fixture()
        data["source"]["count"] = 2
        self.assertTrue(any("count" in p for p in shelfschema.check_custom(data)))
        data = custom_fixture()
        del data["source"]["url"]
        self.assertTrue(any("url" in p for p in shelfschema.check_custom(data)))
        data = custom_fixture()
        data["source"] = "the lcc"
        self.assertTrue(shelfschema.check_custom(data))


class Loading(unittest.TestCase):
    def write(self, content, name="schema.json"):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def test_it_loads_a_valid_file(self):
        self.assertEqual(shelfschema.load(self.write(json.dumps(fixture())))["format"], 1)

    def test_it_refuses_a_file_over_the_size_limit(self):
        path = self.write(json.dumps(fixture()))
        with unittest.mock.patch.object(shelfschema, "MAX_BYTES", 100):
            with self.assertRaisesRegex(KbError, "larger than"):
                shelfschema.load(path)

    def test_it_refuses_what_is_not_json(self):
        for content in ("{not json", "", b"\xff\xfe\x00", "NaN", "[1, 2"):
            with self.subTest(content=content):
                with self.assertRaises(KbError):
                    shelfschema.load(self.write(content))

    def test_it_refuses_a_repeated_key(self):
        with self.assertRaises(KbError):
            shelfschema.load(self.write('{"format": 1, "format": 2, "shelves": []}'))

    def test_it_refuses_a_missing_file_and_a_folder(self):
        with self.assertRaises(KbError):
            shelfschema.load("/no/such/file.json")
        with self.assertRaisesRegex(KbError, "not a regular file"):
            shelfschema.load(tempfile.gettempdir())

    def test_it_refuses_a_pipe_without_waiting_for_it(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, "pipe.json")
        os.mkfifo(path)
        outcome = []

        def attempt():
            try:
                shelfschema.load(path)
                outcome.append("read")
            except KbError as e:
                outcome.append("refused: " + str(e).split(" is ", 1)[-1] if " is " in str(e) else "other: " + str(e))
        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(5)
        if worker.is_alive():
            # free the blocked open so the thread ends, then fail
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            worker.join(5)
            self.fail("load waited for a pipe")
        self.assertEqual(outcome, ["refused: not a regular file"])

    def test_it_reads_a_file_and_changes_nothing(self):
        path = self.write(json.dumps(fixture()))

        def state():
            with open(path, "rb") as f:
                return os.stat(path).st_mtime_ns, f.read()
        before = state()
        shelfschema.load(path)
        self.assertEqual(state(), before)


class Command(unittest.TestCase):
    def run_command(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kbmain.main(["shelf-schema-check", *argv])
        return code, out.getvalue(), err.getvalue()

    def write(self, data):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, "schema.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_a_valid_file_exits_zero_and_prints_the_counts(self):
        code, out, _ = self.run_command(self.write(fixture()))
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["counts"]["topic"], 3)
        self.assertEqual(report["shelves"], 9)
        self.assertEqual(report["kind"], "schema")

    def test_a_broken_file_exits_one_and_names_the_problem(self):
        code, out, _ = self.run_command(self.write(mutate(lambda d: one(d, "robot-control").update(parent="no-such-shelf"))))
        self.assertEqual(code, 1)
        self.assertTrue(any("robot-control" in p for p in json.loads(out)["problems"]))

    def test_the_custom_file_is_checked_with_the_option(self):
        code, out, _ = self.run_command("--custom", self.write(custom_fixture()))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kind"], "custom")
        code, _, _ = self.run_command(self.write(custom_fixture()))
        self.assertEqual(code, 1)

    def test_a_missing_file_is_refused(self):
        code, out, err = self.run_command("/no/such/file.json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("refused", err)

    def test_it_writes_nothing(self):
        path = self.write(fixture())
        folder = os.path.dirname(path)
        before = sorted(os.listdir(folder))
        self.run_command(path)
        self.assertEqual(sorted(os.listdir(folder)), before)

    def test_it_needs_no_library_and_no_config(self):
        with unittest.mock.patch("kb.config.load", side_effect=AssertionError("the config was read")):
            code, _, _ = self.run_command(self.write(fixture()))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
