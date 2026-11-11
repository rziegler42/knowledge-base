import hashlib
import json
import math
import os
import re
import stat
import unittest
import unittest.mock

from engine.tests.test_store import StoreCase, make_writable, read_json

from kb import KbError, convert, theme
from kb import locator as locators   # the helper `locator` below builds a locator by hand

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


def words_hash(text):
    """The hash of a whole excerpt as the plan defines it: its words, lower-cased, without punctuation, joined by single spaces."""
    return hashlib.sha256(" ".join(re.findall(r"\w+", text.lower())).encode()).hexdigest()


def heading(text, level=1):
    return {"kind": "heading", "level": level, "text": text}


def para(text, page=None):
    item = {"kind": "paragraph", "level": None, "text": text}
    if page is not None:
        item["page"] = page
    return item


INTRO_1 = "Annealing cools a system slowly so that it settles into a state of low energy."
INTRO_2 = "A random search accepts worse moves with a probability that falls as the temperature falls."
METHOD_1 = "The schedule lowers the temperature by a fixed factor at each step of the search."
METHOD_2 = "The search stops when no move has been accepted for a long while and the system is cold."
SECTION_ITEMS = [heading("Introduction"), para(INTRO_1), para(INTRO_2), heading("Method"), para(METHOD_1), para(METHOD_2)]
# blocks: 0 heading Introduction, 1 and 2 its paragraphs 1 and 2, 3 heading Method, 4 and 5 its paragraphs 1 and 2


def section(path, paragraph):
    return {"path": path, "paragraph": paragraph}


def pointer(kind, start, end):
    return {"kind": kind, "start": start, "end": end}


class AnchorTest(unittest.TestCase):
    def setUp(self):
        self.sec = convert.build(SECTION_ITEMS)

    def span(self, conversion, first, last):
        return conversion.text[conversion.blocks[first].start:conversion.blocks[last].end]

    def test_a_pointer_to_one_paragraph(self):
        got = theme.anchor_of(CONV, self.sec, pointer("section", section(["Introduction"], 1), section(["Introduction"], 1)))
        self.assertEqual(got, {"start": locators.make(CONV, self.sec, 1), "end": locators.make(CONV, self.sec, 1),
                               "path": ["Introduction"], "excerpt_sha256": words_hash(INTRO_1)})

    def test_a_pointer_to_several_paragraphs_covers_them_whole(self):
        got = theme.anchor_of(CONV, self.sec, pointer("section", section(["Introduction"], 1), section(["Introduction"], 2)))
        self.assertEqual(got["start"], locators.make(CONV, self.sec, 1))
        self.assertEqual(got["end"], locators.make(CONV, self.sec, 2))
        self.assertEqual(got["excerpt_sha256"], words_hash(INTRO_1 + " " + INTRO_2))

    def test_a_pointer_may_run_across_sections_and_the_path_is_that_of_the_start(self):
        got = theme.anchor_of(CONV, self.sec, pointer("section", section(["Introduction"], 2), section(["Method"], 1)))
        self.assertEqual(got["path"], ["Introduction"])
        self.assertEqual(got["end"], locators.make(CONV, self.sec, 4))
        self.assertEqual(got["excerpt_sha256"], words_hash(INTRO_2 + " Method " + METHOD_1))

    def test_the_heading_is_paragraph_zero_of_its_section(self):
        got = theme.anchor_of(CONV, self.sec, pointer("section", section(["Method"], 0), section(["Method"], 1)))
        self.assertEqual((got["start"], got["end"]), (locators.make(CONV, self.sec, 3), locators.make(CONV, self.sec, 4)))
        self.assertEqual(got["excerpt_sha256"], words_hash("Method " + METHOD_1))

    def test_a_pointer_in_a_pdf_names_pages_and_blocks(self):
        pages = convert.build([para("First page, first block, with some words in it.", 1), para("First page, second block, with other words.", 1),
                               para("Second page, first block, with yet more words.", 2)], pages=2)
        got = theme.anchor_of(CONV, pages, pointer("page", {"page": 1, "block": 2}, {"page": 2, "block": 1}))
        self.assertEqual((got["start"], got["end"], got["path"]), (locators.make(CONV, pages, 1), locators.make(CONV, pages, 2), []))
        self.assertEqual(got["excerpt_sha256"], words_hash("First page, second block, with other words. Second page, first block, with yet more words."))

    def test_a_pointer_in_a_flat_text_names_offsets_and_takes_the_blocks_they_are_in(self):
        flat = convert.build([para("The first block has a few words."), para("The second block has a few more words."), para("A third one.")])
        second, third = flat.blocks[1], flat.blocks[2]
        got = theme.anchor_of(CONV, flat, pointer("offset", {"offset": second.start + 4}, {"offset": third.start}))
        self.assertEqual((got["start"], got["end"]), (locators.make(CONV, flat, 1), locators.make(CONV, flat, 2)))
        self.assertEqual(got["excerpt_sha256"], words_hash("The second block has a few more words. A third one."))

    def test_the_anchor_made_is_one_the_form_check_accepts(self):
        got = theme.anchor_of(CONV, self.sec, pointer("section", section(["Introduction"], 1), section(["Method"], 2)))
        t = good_theme()
        t["book_id"], t["version_id"], t["anchor"] = "b", "v1", got
        theme.check_theme(t, "b", "v1")

    def refused(self, conversion, bad, message=None):
        with self.assertRaises(KbError) as cm:
            theme.anchor_of(CONV, conversion, bad)
        if message:
            self.assertIn(message, str(cm.exception))

    def test_a_pointer_that_is_not_a_pointer(self):
        ok = pointer("section", section(["Introduction"], 1), section(["Introduction"], 2))
        for bad in (None, "x", [], {}, dict(ok, extra=1), {k: v for k, v in ok.items() if k != "end"}, dict(ok, start=None),
                    dict(ok, start=[]), dict(ok, kind=None), dict(ok, kind="line")):
            with self.subTest(bad=bad):
                self.refused(self.sec, bad)

    def test_a_pointer_of_another_kind_than_the_conversion(self):
        self.refused(self.sec, pointer("page", {"page": 1, "block": 1}, {"page": 1, "block": 1}), "kind")
        self.refused(self.sec, pointer("offset", {"offset": 1}, {"offset": 2}), "kind")
        pages = convert.build([para("Some words on a page.", 1)], pages=1)
        self.refused(pages, pointer("section", section(["Introduction"], 1), section(["Introduction"], 1)), "kind")

    def test_the_places_of_a_section_pointer(self):
        good = section(["Introduction"], 1)
        for bad in (section(["Nowhere"], 1), section(["Introduction"], 9), section([], 1), section("Introduction", 1), section(["Introduction"] * 7, 1),
                    section([1], 1), section(["Introduction"], True), section(["Introduction"], -1), section(["Introduction"], "1"),
                    {"path": ["Introduction"]}, dict(good, extra=1), {"page": 1, "block": 1}):
            with self.subTest(bad=bad):
                self.refused(self.sec, pointer("section", bad, good))
                self.refused(self.sec, pointer("section", good, bad))

    def test_a_heading_with_no_such_paragraph(self):
        self.refused(self.sec, pointer("section", section(["Method"], 3), section(["Method"], 3)), "no block")

    def test_the_end_may_not_come_before_the_start(self):
        self.refused(self.sec, pointer("section", section(["Introduction"], 2), section(["Introduction"], 1)), "before")
        self.refused(self.sec, pointer("section", section(["Method"], 1), section(["Introduction"], 1)), "before")

    def test_the_places_of_a_page_pointer(self):
        pages = convert.build([para("First block on the first page.", 1), para("Only block on the second page.", 2)], pages=2)
        good = {"page": 1, "block": 1}
        for bad in ({"page": 3, "block": 1}, {"page": 1, "block": 2}, {"page": 0, "block": 1}, {"page": 1, "block": 0}, {"page": True, "block": 1},
                    {"page": 1}, {"page": "1", "block": 1}, {"offset": 1}):
            with self.subTest(bad=bad):
                self.refused(pages, pointer("page", bad, good))
                self.refused(pages, pointer("page", good, bad))
        self.refused(pages, pointer("page", {"page": 2, "block": 1}, {"page": 1, "block": 1}), "before")

    def test_the_places_of_an_offset_pointer(self):
        flat = convert.build([para("The first block."), para("The second block.")])
        first, second = flat.blocks
        good = {"offset": first.start}
        for bad in ({"offset": flat.chars}, {"offset": flat.chars + 100}, {"offset": first.end}, {"offset": -1}, {"offset": True},
                    {"offset": "1"}, {"offset": 1.0}, {}, {"block": 1}):
            with self.subTest(bad=bad):
                self.refused(flat, pointer("offset", bad, good))
                self.refused(flat, pointer("offset", good, bad))  # first.end is in the blank line between the blocks
        self.refused(flat, pointer("offset", {"offset": second.start}, {"offset": first.start}), "before")

    def test_a_conversion_with_no_text_has_nothing_to_point_to(self):
        self.refused(convert.build([]), pointer("offset", {"offset": 0}, {"offset": 0}))

    def test_a_place_that_more_than_one_block_has_is_refused(self):
        twice = convert.build([heading("Notes"), para("First notes with several words in them."), heading("Notes"), para("Second notes with other words.")])
        self.refused(twice, pointer("section", section(["Notes"], 1), section(["Notes"], 1)), "more than one")

    def test_an_excerpt_over_the_limit_is_refused_and_one_at_the_limit_is_not(self):
        ok = pointer("section", section(["Introduction"], 1), section(["Introduction"], 1))
        with unittest.mock.patch.object(theme, "MAX_EXCERPT", len(INTRO_1) - 1):
            self.refused(self.sec, ok, "characters")
        with unittest.mock.patch.object(theme, "MAX_EXCERPT", len(INTRO_1)):
            theme.anchor_of(CONV, self.sec, ok)
        self.assertEqual(theme.MAX_EXCERPT, 6000)

    def test_the_size_of_the_excerpt_is_known_before_the_text_is_copied(self):
        class Untouched(str):
            def __getitem__(self, key):
                raise AssertionError("the text was copied before the size was checked")

        self.sec.text = Untouched(self.sec.text)
        ok = pointer("section", section(["Introduction"], 1), section(["Method"], 2))
        with unittest.mock.patch.object(theme, "MAX_EXCERPT", 50):
            self.refused(self.sec, ok, "characters")

    def test_an_excerpt_with_no_words_is_refused(self):
        empty = convert.build([heading("Symbols"), para("* * * - - -")])
        self.refused(empty, pointer("section", section(["Symbols"], 1), section(["Symbols"], 1)), "no words")


class FindTest(unittest.TestCase):
    A = "Annealing cools a system slowly so that it settles into a state of low energy."
    B = "A random search accepts worse moves with a probability that falls as the temperature falls."
    C = "The schedule lowers the temperature by a fixed factor at each step of the search until it is cold."

    def setUp(self):
        self.one = convert.build([heading("Introduction"), para(self.A), para(self.B), para(self.C)])
        self.anchor = theme.anchor_of(CONV, self.one, pointer("section", section(["Introduction"], 1), section(["Introduction"], 3)))
        self.ref2 = dict(CONV, generation=2)

    def test_an_anchor_is_found_in_the_conversion_it_was_made_against(self):
        got = theme.find(CONV, self.one, self.anchor)
        self.assertEqual((got["status"], got["anchor"]), ("found", self.anchor))
        theme.check_against(CONV, self.one, self.anchor)

    def test_a_stored_hash_that_does_not_match_the_text_is_not_found_and_is_refused(self):
        wrong = dict(self.anchor, excerpt_sha256="c" * 64)
        got = theme.find(CONV, self.one, wrong)
        self.assertEqual((got["status"], got["anchor"]), ("not_found", None))
        self.assertTrue(got["reason"])
        with self.assertRaises(KbError):
            theme.check_against(CONV, self.one, wrong)

    def test_text_that_has_changed_is_not_found(self):
        changed = convert.build([heading("Introduction"), para(self.A), para("Something else entirely is said in this paragraph now."), para(self.C)])
        self.assertEqual(theme.find(CONV, changed, self.anchor)["status"], "not_found")
        with self.assertRaises(KbError):
            theme.check_against(CONV, changed, self.anchor)

    def test_a_conversion_that_splits_the_text_differently_finds_the_same_excerpt_by_its_hash(self):
        merged = convert.build([heading("Introduction"), para(self.A), para(self.B + " " + self.C)])
        got = theme.find(self.ref2, merged, self.anchor)
        self.assertEqual(got["status"], "found_by_text")
        new = got["anchor"]
        self.assertEqual(new["excerpt_sha256"], self.anchor["excerpt_sha256"])
        self.assertEqual((new["start"], new["end"]), (locators.make(self.ref2, merged, 1), locators.make(self.ref2, merged, 2)))
        theme.check_against(self.ref2, merged, new)  # and the new anchor holds in the new conversion as it stands

    def test_a_conversion_whose_blocks_hold_more_text_than_the_excerpt_is_not_found(self):
        longer = convert.build([heading("Introduction"), para(self.A), para(self.B + " " + self.C + " And a good deal more is said after it.")])
        got = theme.find(self.ref2, longer, self.anchor)
        self.assertEqual((got["status"], got["anchor"]), ("not_found", None))

    def test_an_end_that_is_not_in_the_text_is_not_found(self):
        other = convert.build([heading("Introduction"), para("Nothing like the first one is written here at all, so it cannot be found.")])
        self.assertEqual(theme.find(self.ref2, other, self.anchor)["status"], "not_found")

    def test_an_end_found_before_the_start_is_not_found(self):
        flipped = convert.build([heading("Introduction"), para(self.C), para(self.B), para(self.A)])
        got = theme.find(self.ref2, flipped, self.anchor)
        self.assertEqual(got["status"], "not_found")
        self.assertIn("before its start", got["reason"])

    def test_an_anchor_with_a_false_heading_path_does_not_hold_even_if_the_text_is_right(self):
        false = dict(self.anchor, path=["Nowhere"])
        theme._anchor(false, CONV)  # it is well formed
        got = theme.find(CONV, self.one, false)
        self.assertEqual((got["status"], got["anchor"]), ("not_found", None))
        self.assertIn("path or places", got["reason"])
        with self.assertRaises(KbError):
            theme.check_against(CONV, self.one, false)

    def test_an_end_that_is_not_where_its_block_starts_does_not_hold_in_a_flat_text(self):
        flat = convert.build([para("The first block has a few words in it."), para("The second block has a few more words."),
                              para("The third block closes the text with some words.")])
        made = theme.anchor_of(CONV, flat, pointer("offset", {"offset": flat.blocks[0].start}, {"offset": flat.blocks[2].start}))
        self.assertEqual(theme.find(CONV, flat, made)["status"], "found")
        inside = dict(made, start=locators.at_offset(CONV, flat, flat.blocks[0].start + 4))  # a place in the middle of the first block
        got = theme.find(CONV, flat, inside)
        self.assertEqual(got["status"], "not_found")
        with self.assertRaises(KbError):
            theme.check_against(CONV, flat, inside)

    def test_an_anchor_is_found_again_in_a_pdf_and_in_a_flat_text(self):
        pages = convert.build([para("First page, first block, with some words in it.", 1), para("First page, second block, with other words.", 1),
                               para("Second page, first block, with yet more words.", 2)], pages=2)
        flat = convert.build([para("The first block has a few words in it."), para("The second block has a few more words.")])
        for conversion, ptr in ((pages, pointer("page", {"page": 1, "block": 2}, {"page": 2, "block": 1})),
                                (flat, pointer("offset", {"offset": 0}, {"offset": flat.blocks[1].start}))):
            with self.subTest(kind=ptr["kind"]):
                made = theme.anchor_of(CONV, conversion, ptr)
                got = theme.find(CONV, conversion, made)
                self.assertEqual((got["status"], got["anchor"]), ("found", made))

    def test_an_anchor_found_only_by_its_words_does_not_hold_as_it_is_stored(self):
        merged = convert.build([heading("Introduction"), para(self.A), para(self.B + " " + self.C)])
        self.assertEqual(theme.find(self.ref2, merged, self.anchor)["status"], "found_by_text")
        with self.assertRaises(KbError) as cm:
            theme.check_against(self.ref2, merged, self.anchor)  # the stored locators were made against the first conversion
        self.assertIn("only by its words", str(cm.exception))

    def test_an_anchor_that_is_not_an_anchor_is_refused(self):
        for bad in (None, {}, dict(self.anchor, extra=1), dict(self.anchor, start="x"), dict(self.anchor, excerpt_sha256="no")):
            with self.subTest(bad=bad), self.assertRaises(KbError):
                theme.find(CONV, self.one, bad)


if __name__ == "__main__":
    unittest.main()
