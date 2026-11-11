import json
import math
import os
import stat
import unittest
import unittest.mock

from engine.tests.test_store import StoreCase, make_writable, read_json

from kb import KbError, theme

CONV = {"tool": "pdftotext", "version": "1.0", "generation": 1}


def locator(paragraph=1, kind="section", conversion=None):
    at = {"section": {"path": ["Introduction"], "paragraph": paragraph}, "page": {"page": 1, "block": paragraph},
          "offset": {"offset": paragraph}}[kind]
    return {"v": 1, "kind": kind, "at": at, "conversion": dict(conversion or CONV), "excerpt": {"words": 3, "sha256": "a" * 64}}


def good_theme(number=1):
    return {"id": f"t{number}", "book_id": None, "version_id": None, "conversion": dict(CONV),
            "anchor": {"start": locator(number), "end": locator(number + 1), "path": ["Introduction"], "excerpt_sha256": "b" * 64},
            "title": "Stopping a stream of tests early", "type": "method",
            "summary": "The authors compare a running score with a threshold and stop when it is crossed.",
            "neutral": {"problem": {"text": "deciding when enough evidence has arrived", "mark": "stated"},
                        "method": {"text": "compare a running score with a threshold", "mark": "stated"},
                        "needs": {"text": "a stream of independent observations", "mark": "inferred"},
                        "provides": {"text": "a stopping time with a bounded error rate", "mark": "inferred"},
                        "limits": {"text": "", "mark": None}},
            "confidence": 0.8,
            "made": {"model": "m1:latest", "prompt_version": "v1", "date": "2026-11-11T10:00:00+00:00"},
            "flags": []}


class ThemeCase(StoreCase):
    def version(self):
        book = self.store.create_book(title="A paper on stopping", kind="preprint")
        version = self.store.add_version(book, label="v1")
        self.store.file_payload(book, version, "original", {"page.html": b"<html>x</html>"}, primary="page.html")
        return book, version

    def themes(self, book, version, count=2):
        out = []
        for n in range(1, count + 1):
            t = good_theme(n)
            t["book_id"], t["version_id"] = book, version
            out.append(t)
        return out

    def good(self, book, version, count=2):
        return theme.make(book, version, self.themes(book, version, count))


class FormTest(ThemeCase):
    def setUp(self):
        super().setUp()
        self.book, self.version = self.version()

    def refused(self, mutate, where=None):
        made = self.good(self.book, self.version)
        target = made["themes"][0] if where is None else where(made)
        mutate(target)
        with self.assertRaises(KbError):
            theme.validate(made)

    def test_a_good_generation_is_accepted_and_returned_as_it_is(self):
        made = self.good(self.book, self.version)
        self.assertIs(theme.validate(made), made)
        self.assertEqual(len(made["themes"]), 2)

    def test_a_generation_with_no_themes_is_valid(self):
        theme.validate(theme.make(self.book, self.version, []))

    def test_the_generation_must_have_exactly_its_keys(self):
        for change in (lambda g: g.pop("themes"), lambda g: g.pop("format"), lambda g: g.update(extra=1),
                       lambda g: g.update(format=2), lambda g: g.update(format=True), lambda g: g.update(themes={}),
                       lambda g: g.update(book_id="not a book id"), lambda g: g.update(version_id="1")):
            with self.subTest(change=change):
                made = self.good(self.book, self.version)
                change(made)
                with self.assertRaises(KbError):
                    theme.validate(made)

    def test_a_generation_with_too_many_themes_is_refused(self):
        with unittest.mock.patch.object(theme, "MAX_THEMES", 1), self.assertRaises(KbError):
            theme.validate(self.good(self.book, self.version, 2))

    def test_a_theme_must_have_exactly_its_keys(self):
        for key in list(good_theme()):
            with self.subTest(missing=key):
                self.refused(lambda t, k=key: t.pop(k))
        self.refused(lambda t: t.update(extra="x"))
        self.refused(lambda t: t.__setitem__("not-text", 1))

    def test_a_theme_must_belong_to_the_book_and_version_of_its_generation(self):
        self.refused(lambda t: t.update(book_id=self.store.create_book(title="Another", kind="preprint")))
        self.refused(lambda t: t.update(version_id="v2"))

    def test_the_id(self):
        for value in ("", "T1", "a b", "t" * 33, "-t", 1, None):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(id=v))

    def test_two_themes_may_not_share_an_id(self):
        self.refused(lambda t: t.update(id="t2"))

    def test_the_conversion(self):
        for value in (None, "pdftotext", {}, dict(CONV, extra=1), {"tool": "pdftotext", "version": "1.0"},
                      dict(CONV, tool="PDF"), dict(CONV, version=""), dict(CONV, generation=0), dict(CONV, generation="1"),
                      dict(CONV, generation=True)):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(conversion=v))

    def test_the_anchor_has_exactly_its_keys(self):
        for key in ("start", "end", "path", "excerpt_sha256"):
            with self.subTest(missing=key):
                self.refused(lambda t, k=key: t["anchor"].pop(k))
        self.refused(lambda t: t["anchor"].update(extra=1))
        self.refused(lambda t: t.update(anchor=None))
        self.refused(lambda t: t.update(anchor=[]))

    def test_the_ends_of_the_anchor_are_locators(self):
        for end in ("start", "end"):
            for value in (None, "x", {}, dict(locator(), v=2), dict(locator(), kind="line"), dict(locator(), extra=1),
                          dict(locator(), excerpt={"words": 3, "sha256": "zz"}), dict(locator(), excerpt={"words": 99, "sha256": "a" * 64})):
                with self.subTest(end=end, value=value):
                    self.refused(lambda t, e=end, v=value: t["anchor"].update({e: v}))

    def test_the_ends_of_the_anchor_are_of_one_kind_and_of_the_conversion_of_the_theme(self):
        self.refused(lambda t: t["anchor"].update(end=locator(2, kind="page")))
        self.refused(lambda t: t["anchor"].update(start=locator(1, conversion=dict(CONV, generation=2))))
        self.refused(lambda t: t["anchor"].update(end=locator(2, conversion=dict(CONV, version="2.0"))))

    def test_the_end_of_an_anchor_does_not_come_before_its_start_where_that_can_be_told_from_the_places(self):
        self.refused(lambda t: t["anchor"].update(start=locator(9, kind="offset"), end=locator(3, kind="offset")))
        self.refused(lambda t: t["anchor"].update(start=locator(9, kind="page"), end=locator(3, kind="page")))
        page = lambda page, block: dict(locator(kind="page"), at={"page": page, "block": block})
        self.refused(lambda t: t["anchor"].update(start=page(2, 1), end=page(1, 5)))
        made = self.good(self.book, self.version)
        for start, end in ((locator(3, kind="offset"), locator(3, kind="offset")), (locator(3, kind="offset"), locator(9, kind="offset")),
                           (page(1, 5), page(2, 1)), (page(2, 1), page(2, 1)), (locator(5), locator(2))):  # a section is not ordered here
            with self.subTest(start=start["at"], end=end["at"]):
                made["themes"][0]["anchor"].update(start=start, end=end)
                theme.validate(made)

    def test_the_heading_path_of_the_anchor(self):
        for value in (None, "Introduction", ["a"] * 7, [""], [1], ["x" * 500], ["bad\x1b[31m"]):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t["anchor"].update(path=v))
        made = self.good(self.book, self.version)
        made["themes"][0]["anchor"]["path"] = []  # a page with no headings has none
        theme.validate(made)

    def test_the_hash_of_the_excerpt(self):
        for value in (None, "", "b" * 63, "b" * 65, "B" * 64, "g" * 64, 5):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t["anchor"].update(excerpt_sha256=v))

    def test_the_title(self):
        for value in ("", "x" * 121, "a\x1b[31mb", " padded ", None, 5, "the untrusted text marker end"):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(title=v))
        made = self.good(self.book, self.version)
        made["themes"][0]["title"] = "x" * 120
        theme.validate(made)

    def test_the_type_is_one_of_five(self):
        for value in ("problem", "method", "finding", "concept", "other"):
            with self.subTest(value=value):
                made = self.good(self.book, self.version)
                made["themes"][0]["type"] = value
                theme.validate(made)
        for value in ("", "Method", "idea", None, 3, ["method"]):
            with self.subTest(bad=value):
                self.refused(lambda t, v=value: t.update(type=v))

    def test_the_summary(self):
        for value in ("", "x" * 601, "a\x00b", "  x", None, 5):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(summary=v))
        made = self.good(self.book, self.version)
        made["themes"][0]["summary"] = "x" * 600
        theme.validate(made)

    def test_the_neutral_description_has_exactly_five_parts(self):
        for part in ("problem", "method", "needs", "provides", "limits"):
            with self.subTest(missing=part):
                self.refused(lambda t, p=part: t["neutral"].pop(p))
        self.refused(lambda t: t["neutral"].update(extra={"text": "x", "mark": "stated"}))
        self.refused(lambda t: t.update(neutral=None))
        self.refused(lambda t: t.update(neutral=[]))

    def test_a_part_of_the_neutral_description(self):
        for value in (None, "text", {}, {"text": "x"}, {"mark": None}, {"text": "x", "mark": "stated", "extra": 1}, {"text": 5, "mark": "stated"},
                      {"text": "x" * 301, "mark": "stated"}, {"text": "a\x1b[31m", "mark": "stated"}, {"text": " x", "mark": "stated"}):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t["neutral"].update(problem=v))
        made = self.good(self.book, self.version)
        made["themes"][0]["neutral"]["problem"] = {"text": "x" * 300, "mark": "inferred"}
        theme.validate(made)

    def test_every_part_with_text_has_a_mark_and_no_part_without_text_has_one(self):
        for value in ({"text": "something", "mark": None}, {"text": "something", "mark": "unknown"}, {"text": "something", "mark": "Stated"},
                      {"text": "something", "mark": True}, {"text": "", "mark": "stated"}, {"text": "", "mark": "inferred"}):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t["neutral"].update(limits=v))

    def test_the_confidence(self):
        for value in (-0.01, 1.01, True, False, "0.5", None, math.nan, math.inf, -math.inf, [0.5]):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(confidence=v))
        for value in (0, 1, 0.0, 0.5, 1.0):
            with self.subTest(good=value):
                made = self.good(self.book, self.version)
                made["themes"][0]["confidence"] = value
                theme.validate(made)

    def test_how_the_theme_was_made(self):
        for value in (None, {}, {"model": "m1:latest"}, dict(good_theme()["made"], extra=1), dict(good_theme()["made"], model=""),
                      dict(good_theme()["made"], model="bad model"), dict(good_theme()["made"], prompt_version=""),
                      dict(good_theme()["made"], prompt_version="v 1"), dict(good_theme()["made"], date="yesterday"),
                      dict(good_theme()["made"], date=5)):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(made=v))

    def test_the_flags(self):
        for value in (None, "x", {}, [1], [{}], [{"kind": "field_words"}], [{"kind": "field_words", "detail": "x", "extra": 1}],
                      [{"kind": "", "detail": "x"}], [{"kind": "k" * 41, "detail": "x"}], [{"kind": "k", "detail": "d" * 301}],
                      [{"kind": "k", "detail": "a\x1b[31m"}], [{"kind": "k", "detail": "x"}] * 11):
            with self.subTest(value=value):
                self.refused(lambda t, v=value: t.update(flags=v))
        made = self.good(self.book, self.version)
        made["themes"][0]["flags"] = [{"kind": "field_words", "detail": "annealing, temperature"}]
        theme.validate(made)


class FileTest(ThemeCase):
    def test_a_generation_is_filed_as_a_read_only_untrusted_payload(self):
        book, version = self.version()
        number = theme.file(self.store, self.good(book, version))
        self.assertEqual(number, 1)
        path = self.store.payload_path(book, version, "derived/theme/1")
        self.assertEqual(sorted(os.listdir(path)), ["payload.json", "themes.json"])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(path, "themes.json")).st_mode), 0o444)
        manifest = read_json(os.path.join(path, "payload.json"))
        self.assertIs(manifest["untrusted"], True)
        self.assertEqual(set(manifest["files"]), {"themes.json"})
        self.assertIn("derived/theme/1", self.store.read_version(book, version)["payloads"])

    def test_a_second_generation_leaves_the_first_byte_for_byte(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version))
        first = self.store.verify_payload(book, version, "derived/theme/1")
        with open(os.path.join(self.store.payload_path(book, version, "derived/theme/1"), "themes.json"), "rb") as f:
            first_bytes = f.read()
        again = self.good(book, version, 3)
        self.assertEqual(theme.file(self.store, again), 2)
        self.assertEqual(self.store.verify_payload(book, version, "derived/theme/1"), first)
        with open(os.path.join(self.store.payload_path(book, version, "derived/theme/1"), "themes.json"), "rb") as f:
            self.assertEqual(f.read(), first_bytes)
        self.assertEqual(theme.generations(self.store, book, version), [1, 2])
        self.assertEqual(len(theme.read(self.store, book, version)[1]["themes"]), 3)
        self.assertEqual(len(theme.read(self.store, book, version, generation=1)[1]["themes"]), 2)

    def test_what_is_read_back_equals_what_was_filed(self):
        book, version = self.version()
        made = self.good(book, version)
        theme.file(self.store, made)
        self.assertEqual(theme.read(self.store, book, version), (1, made))

    def test_an_invalid_generation_is_refused_and_nothing_is_filed(self):
        book, version = self.version()
        bad = self.good(book, version)
        bad["themes"][0]["type"] = "idea"
        with self.assertRaises(KbError):
            theme.file(self.store, bad)
        self.assertEqual(theme.generations(self.store, book, version), [])
        self.assertFalse(os.path.exists(os.path.join(self.store.version_dir(book, version), "derived", "theme")))

    def test_a_generation_is_filed_for_the_version_it_names(self):
        book, version = self.version()
        made = self.good(book, version)
        made["version_id"] = "v9"
        for t in made["themes"]:
            t["version_id"] = "v9"
        with self.assertRaises(KbError):
            theme.file(self.store, made)

    def test_a_generation_larger_than_it_may_be_is_not_filed(self):
        book, version = self.version()
        made = self.good(book, version)
        with unittest.mock.patch.object(theme, "MAX_FILE", 100), self.assertRaises(KbError):
            theme.file(self.store, made)
        self.assertEqual(theme.generations(self.store, book, version), [])

    def test_the_numbers_ignore_folders_that_are_not_numbers_and_links(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version))
        folder = os.path.join(self.store.version_dir(book, version), "derived", "theme")
        os.chmod(folder, 0o700)
        os.mkdir(os.path.join(folder, "notes"))
        os.mkdir(os.path.join(folder, "007x"))
        os.symlink(os.path.join(folder, "1"), os.path.join(folder, "5"))
        self.assertEqual(theme.generations(self.store, book, version), [1])
        self.assertEqual(theme.file(self.store, self.good(book, version)), 2)

    def test_a_version_with_no_themes(self):
        book, version = self.version()
        self.assertEqual(theme.generations(self.store, book, version), [])
        with self.assertRaises(KbError) as cm:
            theme.read(self.store, book, version)
        self.assertIn("no themes", str(cm.exception))
        with self.assertRaises(KbError):
            theme.read(self.store, book, version, generation=3)

    def test_a_generation_is_asked_for_by_a_whole_number_that_exists(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version))
        for value in (0, 2, -1, "1", 1.0, True):
            with self.subTest(value=value), self.assertRaises(KbError) as cm:
                theme.read(self.store, book, version, generation=value)
            self.assertIn("no themes of generation", str(cm.exception))


class ReadRefusalTest(ThemeCase):
    def filed(self, content, extra=None):
        book, version = self.version()
        files = {"themes.json": content}
        files.update(extra or {})
        self.store.file_payload(book, version, "derived/theme/1", files, tool="kb-theme 1", untrusted=True)
        return book, version

    def refuses(self, content, extra=None):
        book, version = self.filed(content, extra)
        with self.assertRaises(KbError):
            theme.read(self.store, book, version)

    def test_text_that_is_not_json_or_not_an_object(self):
        for content in (b"", b"not json", b"[1]", b"null", b"\xff\xfe", b'{"a": 1, "a": 2}', b"[" * 5000):
            with self.subTest(content=content[:20]):
                self.refuses(content)

    def test_a_payload_with_another_file_in_it(self):
        book, version = self.version()
        content = json.dumps(self.good(book, version)).encode()
        self.store.file_payload(book, version, "derived/theme/1", {"themes.json": content, "notes.txt": b"x"}, tool="kb-theme 1", untrusted=True)
        with self.assertRaises(KbError) as cm:
            theme.read(self.store, book, version)
        self.assertIn("nothing else", str(cm.exception))

    def test_a_payload_that_was_changed_after_filing(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version))
        path = os.path.join(self.store.payload_path(book, version, "derived/theme/1"), "themes.json")
        make_writable(os.path.dirname(path))
        with open(path, "ab") as f:
            f.write(b" ")
        with self.assertRaises(KbError):
            theme.read(self.store, book, version)

    def test_a_file_that_is_too_large(self):
        self.refuses(b'{"x": "' + b"a" * theme.MAX_FILE + b'"}')

    def test_a_good_generation_larger_than_one_may_be_is_refused_on_reading(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version))
        with unittest.mock.patch.object(theme, "MAX_FILE", 100), self.assertRaises(KbError) as cm:
            theme.read(self.store, book, version, generation=1)
        self.assertIn("larger", str(cm.exception))

    def test_the_damaged_generations_are_listed_with_their_reasons(self):
        book, version = self.version()
        self.assertEqual(theme.damaged(self.store, book, version), [])
        theme.file(self.store, self.good(book, version))
        self.assertEqual(theme.damaged(self.store, book, version), [])
        bad = self.good(book, version)
        bad["themes"][0]["confidence"] = 7
        self.store.file_payload(book, version, "derived/theme/2", {"themes.json": json.dumps(bad).encode()}, tool="kb-theme 1", untrusted=True)
        listed = theme.damaged(self.store, book, version)
        self.assertEqual([n for n, _ in listed], [2])
        self.assertIn("confidence", listed[0][1])
        self.assertEqual(theme.read(self.store, book, version)[0], 1)  # the read still returns the earlier one, and the list says why

    def test_a_generation_that_belongs_to_another_book_or_version(self):
        other_book, other_version = self.version()
        self.refuses(json.dumps(self.good(other_book, other_version)).encode())
        book, version = self.version()
        wrong = self.good(book, version)
        wrong["version_id"] = "v2"
        for t in wrong["themes"]:
            t["version_id"] = "v2"
        self.store.file_payload(book, version, "derived/theme/1", {"themes.json": json.dumps(wrong).encode()}, tool="kb-theme 1", untrusted=True)
        with self.assertRaises(KbError):
            theme.read(self.store, book, version)

    def test_a_generation_that_is_not_valid_is_refused_on_reading(self):
        book, version = self.version()
        bad = self.good(book, version)
        bad["themes"][0]["anchor"]["excerpt_sha256"] = "nope"
        self.store.file_payload(book, version, "derived/theme/1", {"themes.json": json.dumps(bad).encode()}, tool="kb-theme 1", untrusted=True)
        with self.assertRaises(KbError):
            theme.read(self.store, book, version)

    def test_without_a_number_the_newest_generation_that_passes_its_check_is_read(self):
        book, version = self.version()
        theme.file(self.store, self.good(book, version, 2))
        bad = self.good(book, version, 3)
        bad["themes"][0]["confidence"] = 7
        self.store.file_payload(book, version, "derived/theme/2", {"themes.json": json.dumps(bad).encode()}, tool="kb-theme 1", untrusted=True)
        self.assertEqual(theme.generations(self.store, book, version), [1, 2])
        number, got = theme.read(self.store, book, version)
        self.assertEqual((number, len(got["themes"])), (1, 2))
        with self.assertRaises(KbError):  # the number asked for is read as it is, and a generation that fails its check is refused
            theme.read(self.store, book, version, generation=2)

    def test_when_no_generation_passes_its_check_the_read_is_refused(self):
        book, version = self.filed(b"not json")
        with self.assertRaises(KbError) as cm:
            theme.read(self.store, book, version)
        self.assertIn("check", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
