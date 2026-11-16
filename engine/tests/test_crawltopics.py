"""The owner's topics file of the unattended crawl (`kb/crawltopics.py`; `docs/specs/population.md`, "The crawl plan"). No test reads the
owner's file: every file here is made in a temporary folder."""

import os
import tempfile
import unittest
from collections import Counter

from kb import KbError, crawltopics

GOOD = """# the owner's topics
[core weight=10]
Control theory
Signal processing   # the words after a hash in a topic line are part of it

[exploratory weight=5]
C# programming
Category theory

[low weight=1]
SystemVerilog
"""


class FileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text, name="topics.txt", mode=0o600, raw=False):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb" if raw else "w", **({} if raw else {"encoding": "utf-8"})) as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def read(self, text, **kw):
        return crawltopics.read_topics(self.write(text, **kw))

    def refused(self, text, fragment=None, **kw):
        with self.assertRaises(KbError) as cm:
            self.read(text, **kw)
        if fragment:
            self.assertIn(fragment, str(cm.exception))
        return str(cm.exception)


class ReadTest(FileCase):
    def test_sections_weights_comments_and_topics_are_read_in_order(self):
        self.assertEqual(self.read(GOOD), [
            ("Control theory", 10, "core"),
            ("Signal processing # the words after a hash in a topic line are part of it", 10, "core"),
            ("C# programming", 5, "exploratory"),
            ("Category theory", 5, "exploratory"),
            ("SystemVerilog", 1, "low"),
        ])

    def test_only_a_line_that_starts_with_a_hash_is_a_comment(self):
        got = self.read("[core weight=2]\n# a comment\n   # an indented comment\nF# and C#\n")
        self.assertEqual(got, [("F# and C#", 2, "core")])

    def test_blank_lines_and_surrounding_white_space_are_ignored(self):
        self.assertEqual(self.read("\n\n[a weight=3]\n\n  Topic one  \n\t\nTopic two\r\n"),
                         [("Topic one", 3, "a"), ("Topic two", 3, "a")])

    def test_the_same_weight_in_two_sections_and_the_same_section_twice_are_taken(self):
        got = self.read("[core weight=4]\nA\n[core weight=6]\nB\n")
        self.assertEqual(got, [("A", 4, "core"), ("B", 6, "core")])

    def test_a_byte_order_mark_at_the_start_is_ignored(self):
        self.assertEqual(self.read("\ufeff[core weight=2]\nA topic\n"), [("A topic", 2, "core")])

    def test_each_kind_of_line_end_ends_a_line_and_the_line_numbers_are_those_of_an_editor(self):
        for end in ("\n", "\r\n", "\r"):
            with self.subTest(end=repr(end)):
                self.assertEqual(self.read(f"[a weight=1]{end}One{end}Two{end}"), [("One", 1, "a"), ("Two", 1, "a")])
                self.refused(f"[a weight=1]{end}One{end}[b weight=0]{end}", "line 3")

    def test_exactly_5000_topics_are_taken_and_5001_are_not(self):
        head = "[a weight=1]\n"
        self.assertEqual(len(self.read(head + "".join(f"t{i}\n" for i in range(5000)))), 5000)
        self.refused(head + "".join(f"t{i}\n" for i in range(5001)), "5000")

    def test_a_topic_before_any_section_is_refused(self):
        self.refused("A topic\n[core weight=1]\nB\n", "line 1")

    def test_a_weight_that_is_not_a_positive_whole_number_is_refused(self):
        for weight in ("0", "-1", "1.5", "abc", "", "01", "1_000", "٣", "10000000", "+5", " 5", "5 "):
            with self.subTest(weight=weight):
                self.refused(f"[core weight={weight}]\nA\n")

    def test_a_malformed_section_line_is_refused(self):
        for line in ("[core]", "[core weight]", "[weight=5]", "[core weight=5", "core weight=5]", "[core weight=5] extra",
                     "[core  weight=5 x]", "[]", "[core weight=5][low weight=1]", "[co/re weight=5]", "[" + "a" * 41 + " weight=5]"):
            with self.subTest(line=line):
                self.refused(f"{line}\nA\n")

    def test_a_section_with_no_topic_is_taken_and_a_file_with_no_topic_is_refused(self):
        self.assertEqual(self.read("[core weight=5]\n[low weight=1]\nA\n"), [("A", 1, "low")])
        self.refused("[core weight=5]\n", "no topic")
        self.refused("", "no topic")
        self.refused("# only a comment\n\n", "no topic")

    def test_a_repeated_topic_is_refused_even_in_another_section_or_case(self):
        self.refused("[a weight=1]\nControl theory\n[b weight=2]\nControl theory\n", "line 4")
        self.refused("[a weight=1]\nControl theory\ncontrol   THEORY\n", "line 3")

    def test_a_topic_over_300_characters_is_refused_and_300_is_taken(self):
        self.refused("[a weight=1]\n" + "x" * 301 + "\n", "300")
        self.assertEqual(self.read("[a weight=1]\n" + "x" * 300 + "\n"), [("x" * 300, 1, "a")])

    def test_control_format_and_bidirectional_characters_are_removed_from_a_topic(self):
        got = self.read("[a weight=1]\nCon\u202etrol\u200b the\x07ory\u2066\n")
        self.assertEqual(got, [("Control theory", 1, "a")])

    def test_a_topic_of_only_hidden_characters_is_refused(self):
        self.refused("[a weight=1]\n\u200b\u202e\n", "line 2")

    def test_a_section_name_with_hidden_characters_is_refused(self):
        self.refused("[co\u200bre weight=1]\nA\n")

    def test_white_space_inside_a_topic_is_made_single(self):
        self.assertEqual(self.read("[a weight=1]\nControl \t  theory\n"), [("Control theory", 1, "a")])

    def test_a_file_over_256_kilobytes_is_refused_and_one_under_is_read(self):
        line = "Topic number %06d with some more words to fill the line out\n"
        many = "[a weight=1]\n" + "".join(line % i for i in range(3500))
        self.assertLess(len(many.encode()), 256 * 1024)
        self.assertEqual(len(self.read(many)), 3500)
        self.refused(many + "x" * (256 * 1024), "256")

    def test_a_file_that_is_not_utf_8_is_refused(self):
        with self.assertRaises(KbError):
            crawltopics.read_topics(self.write(b"[a weight=1]\nCaf\xe9\n", raw=True))

    def test_a_nul_byte_is_refused(self):
        with self.assertRaises(KbError):
            crawltopics.read_topics(self.write(b"[a weight=1]\nA\x00B\n", raw=True))

    def test_a_link_a_folder_a_pipe_and_a_missing_file_are_refused(self):
        real = self.write(GOOD)
        link = os.path.join(self.tmp.name, "link.txt")
        os.symlink(real, link)
        folder = os.path.join(self.tmp.name, "folder")
        os.mkdir(folder)
        pipe = os.path.join(self.tmp.name, "pipe")
        os.mkfifo(pipe)
        for path in (link, folder, pipe, os.path.join(self.tmp.name, "missing.txt")):
            with self.subTest(path=os.path.basename(path)):
                with self.assertRaises(KbError):
                    crawltopics.read_topics(path)

    def test_a_path_with_a_nul_character_is_a_refusal_of_ours(self):
        with self.assertRaises(KbError):
            crawltopics.read_topics(os.path.join(self.tmp.name, "a\x00b"))

    def test_a_path_that_is_not_a_path_is_refused(self):
        for path in (None, 5, "", b"x"):
            with self.subTest(path=path):
                with self.assertRaises(KbError):
                    crawltopics.read_topics(path)

    def test_more_than_the_largest_number_of_topics_is_refused(self):
        text = "[a weight=1]\n" + "".join(f"t{i}\n" for i in range(crawltopics.MAX_TOPICS + 1))
        self.refused(text, str(crawltopics.MAX_TOPICS))

    def test_the_refusal_names_the_line_and_never_quotes_the_text(self):
        message = self.refused("[a weight=1]\nfine\n[b weight=zero]\n", "line 3")
        self.assertNotIn("zero", message)

    def test_the_file_is_not_changed(self):
        path = self.write(GOOD)
        before = (open(path, "rb").read(), os.stat(path).st_mtime_ns)
        crawltopics.read_topics(path)
        self.assertEqual((open(path, "rb").read(), os.stat(path).st_mtime_ns), before)


def topics(*weights):
    return [(f"t{i}", w, "s") for i, w in enumerate(weights)]


class SharesTest(unittest.TestCase):
    def test_each_topic_gets_its_weight_over_the_sum(self):
        got = crawltopics.shares(topics(10, 5, 1))
        self.assertEqual([t for t, _ in got], ["t0", "t1", "t2"])
        for (_, share), want in zip(got, (10 / 16, 5 / 16, 1 / 16)):
            self.assertAlmostEqual(share, want)
        self.assertAlmostEqual(sum(s for _, s in got), 1.0)

    def test_no_topics_give_no_shares(self):
        self.assertEqual(crawltopics.shares([]), [])

    def test_a_topic_that_is_not_a_triple_with_a_positive_weight_is_refused(self):
        for bad in ([("a", 0, "s")], [("a", -1, "s")], [("a", 1.5, "s")], [("a", True, "s")], [("a", 1)], ["a"], "a", None,
                    [(5, 1, "s")], [(None, 1, "s")]):
            with self.subTest(bad=bad):
                with self.assertRaises(KbError):
                    crawltopics.shares(bad)


class QuotaTest(unittest.TestCase):
    def test_the_quotas_sum_to_n_for_every_day_and_every_n(self):
        t = topics(10, 5, 1, 7, 3)
        for n in (0, 1, 2, 7, 20, 100):
            for day in (0, 1, 2, 17, 365):
                with self.subTest(n=n, day=day):
                    got = crawltopics.quota(t, n, day)
                    self.assertEqual(len(got), len(t))
                    self.assertEqual(sum(got), n)
                    self.assertTrue(all(type(q) is int and q >= 0 for q in got))

    def test_it_is_deterministic(self):
        t = topics(10, 5, 1)
        self.assertEqual(crawltopics.quota(t, 12, 3), crawltopics.quota(t, 12, 3))

    def test_the_values_are_pinned_so_that_every_machine_and_every_version_gives_the_same_days(self):
        t = topics(10, 5, 1)
        self.assertEqual([crawltopics.quota(t, 8, d) for d in (0, 1, 7)], [[5, 2, 1], [5, 3, 0], [5, 3, 0]])
        five = topics(3, 3, 3, 3, 3)
        self.assertEqual([crawltopics.quota(five, 6, d) for d in (0, 3)], [[1, 1, 1, 2, 1], [0, 2, 1, 1, 2]])

    def test_it_follows_the_weights_over_many_days(self):
        t = topics(10, 5, 1)
        total = Counter()
        days = 400
        for day in range(days):
            for i, q in enumerate(crawltopics.quota(t, 8, day)):
                total[i] += q
        everything = days * 8
        for i, w in enumerate((10, 5, 1)):
            self.assertAlmostEqual(total[i] / everything, w / 16, delta=0.01)

    def test_every_topic_is_reached_over_the_days_even_when_a_day_is_small(self):
        t = topics(*([10] * 74 + [5] * 43 + [1]))  # the shape of the owner's approved list
        seen = set()
        for day in range(200):
            for i, q in enumerate(crawltopics.quota(t, 20, day)):
                if q:
                    seen.add(i)
        self.assertEqual(seen, set(range(len(t))))

    def test_the_quotas_change_from_day_to_day(self):
        t = topics(*([3] * 30))
        days = {tuple(crawltopics.quota(t, 5, d)) for d in range(10)}
        self.assertGreater(len(days), 5)

    def test_the_days_are_slices_of_one_endless_sequence_whatever_n_is(self):
        t = topics(10, 5, 1, 7)

        def total(n, days):
            made = [0] * len(t)
            for day in days:
                made = [a + b for a, b in zip(made, crawltopics.quota(t, n, day))]
            return made

        whole = total(24, [0])
        self.assertEqual(total(1, range(24)), whole)
        self.assertEqual(total(2, range(12)), whole)
        self.assertEqual(total(8, range(3)), whole)
        self.assertEqual(total(24, [1]), [a - b for a, b in zip(total(48, [0]), whole)])  # and the next slice follows it

    def test_a_single_topic_gets_all_of_it_and_no_topics_get_none(self):
        self.assertEqual(crawltopics.quota(topics(3), 7, 4), [7])
        self.assertEqual(crawltopics.quota([], 7, 4), [])

    def test_n_and_day_must_be_whole_numbers(self):
        for n, day in ((-1, 0), (1.5, 0), (True, 0), ("3", 0), (3, -1), (3, 1.5), (3, None), (10**9 + 1, 0), (3, 10**9 + 1)):
            with self.subTest(n=n, day=day):
                with self.assertRaises(KbError):
                    crawltopics.quota(topics(1, 2), n, day)

    def test_it_does_not_depend_on_the_names_or_sections(self):
        a = [("x", 3, "one"), ("y", 4, "two")]
        b = [("p", 3, "three"), ("q", 4, "four")]
        self.assertEqual(crawltopics.quota(a, 6, 2), crawltopics.quota(b, 6, 2))


if __name__ == "__main__":
    unittest.main()
