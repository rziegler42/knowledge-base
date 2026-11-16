"""The search queries of the unattended crawl, made from a topic (`kb/crawlqueries.py`). The model is a fake here: no test calls a server."""

import unittest

from kb import KbError, crawlqueries

VERSION = crawlqueries.PROMPT_VERSION


class FakeChat:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def make(topic="Control theory", n=3, chat=None, cache=None, version=VERSION):
    return crawlqueries.make_queries(topic, n, chat, {} if cache is None else cache, version)


class PromptTest(unittest.TestCase):
    def test_the_prompt_is_a_fixed_text_that_holds_the_topic_and_the_number_and_nothing_else(self):
        one = crawlqueries.build_prompt("Control theory", 3)
        other = crawlqueries.build_prompt("Category theory", 3)
        self.assertIn("Control theory", one)
        self.assertEqual(one.replace("Control theory", "@"), other.replace("Category theory", "@"))
        self.assertEqual(one.count("Control theory"), 1)
        self.assertNotEqual(crawlqueries.build_prompt("Control theory", 3), crawlqueries.build_prompt("Control theory", 4))

    def test_the_prompt_is_not_built_for_a_topic_or_a_number_that_is_not_one(self):
        for topic, n in (("", 3), ("a\x00b c", 3), (5, 3), ("Control theory", 0), ("Control theory", 11), ("Control theory", True)):
            with self.subTest(topic=topic, n=n):
                with self.assertRaises(KbError):
                    crawlqueries.build_prompt(topic, n)

    def test_the_prompt_asks_for_one_query_a_line_with_no_numbering_and_no_comment(self):
        prompt = crawlqueries.build_prompt("Control theory", 3).lower()
        for word in ("one", "line", "number", "comment"):
            self.assertIn(word, prompt)

    def test_the_model_is_given_exactly_that_prompt(self):
        chat = FakeChat("a b c")
        make(chat=chat)
        self.assertEqual(chat.prompts, [crawlqueries.build_prompt("Control theory", 3)])

    def test_the_prompt_version_is_a_short_name(self):
        self.assertRegex(VERSION, r"^[a-z0-9][a-z0-9.-]{0,39}$")


class ReaderTest(unittest.TestCase):
    def queries(self, reply, n=5):
        return make(n=n, chat=FakeChat(reply))

    def test_one_query_to_a_line(self):
        self.assertEqual(self.queries("optimal control survey\nfeedback stability textbook\nPID tuning methods"),
                         ["optimal control survey", "feedback stability textbook", "PID tuning methods"])

    def test_numbering_and_bullets_are_taken_off(self):
        self.assertEqual(self.queries("1. optimal control\n2) feedback stability\n- PID tuning\n* lqr regulator\n3. state space"),
                         ["optimal control", "feedback stability", "PID tuning", "lqr regulator", "state space"])

    def test_surrounding_quotes_are_taken_off(self):
        self.assertEqual(self.queries('"optimal control"\n\u201cfeedback stability\u201d\n\'pid tuning\''),
                         ["optimal control", "feedback stability", "pid tuning"])

    def test_blank_lines_and_extra_white_space_are_ignored_and_the_text_is_cleaned(self):
        self.assertEqual(self.queries("\n\n  optimal   control \t methods \n\n\u200bfeedback\u202e stability\n"),
                         ["optimal control methods", "feedback stability"])

    def test_at_most_n_are_kept_in_order(self):
        self.assertEqual(self.queries("one aaa\ntwo bbb\nthree ccc\nfour ddd", n=2), ["one aaa", "two bbb"])

    def test_duplicates_are_taken_once_whatever_their_case_or_spacing(self):
        self.assertEqual(self.queries("optimal control\nOptimal  Control\nfeedback"), ["optimal control", "feedback"])

    def test_a_line_of_fewer_than_3_or_more_than_120_characters_is_dropped(self):
        self.assertEqual(self.queries("ab\nabc\n" + "w" * 121 + "\n" + "w" * 120), ["abc", "w" * 120])

    def test_a_line_with_a_mark_that_a_query_does_not_need_is_dropped_and_not_repaired(self):
        bad = ["a;b", "a|b", "a<b>", "a`b`", "a$b", "a{b}", "a\\b", "a=b", "a#b", "a@b", "a%b", "a^b", "a~b", "a[b]", "a*b", "a\x00b",
               "http://evil.example/x", "see https://x.org", "a\"b"]
        good = "optimal control"
        for line in bad:
            with self.subTest(line=line):
                self.assertEqual(self.queries(f"{line}\n{good}"), [good])

    def test_the_marks_a_query_may_have(self):
        self.assertEqual(self.queries("signal-to-noise ratio\nk-means (clustering)\nstate/space models\nR&D policy\nO'Neill, 1999: a note.\n"
                                      "c++ templates", n=10),
                         ["signal-to-noise ratio", "k-means (clustering)", "state/space models", "R&D policy",
                          "O'Neill, 1999: a note.", "c++ templates"])

    def test_numbering_is_taken_off_the_start_of_a_line_only_and_only_when_it_is_numbering(self):
        self.assertEqual(self.queries("optimal - control\nversion 2. release notes\n3.5 inch floppy\n2D convolution\n"
                                      "4) fourier - laplace", n=10),
                         ["optimal - control", "version 2. release notes", "3.5 inch floppy", "2D convolution",
                          "fourier - laplace"])

    def test_a_word_that_a_search_source_would_read_as_syntax_drops_the_line(self):
        bad = ["-k means", "k means -clustering", "+required term", "site:evil.example malware", "filetype:pdf control theory",
               "au:smith control theory", "ti:control AND abs:theory", "a:b c"]
        good = ["k-means clustering", "c++ templates", "optimal - control", "a - b + c", "ratio: 1999 note", "note: see 1999:"]
        for line in bad:
            with self.subTest(line=line):
                self.assertEqual(self.queries(f"{line}\nreal query"), ["real query"])
        self.assertEqual(self.queries("\n".join(good), n=10), good[:-1])  # a line that ends with a colon is a heading

    def test_only_a_number_of_one_or_two_digits_is_numbering(self):
        self.assertEqual(self.queries("100. big query\n12. twelfth query\n7) seventh query", n=10),
                         ["100. big query", "twelfth query", "seventh query"])

    def test_a_line_with_a_control_character_inside_is_dropped_and_not_repaired(self):
        self.assertEqual(self.queries("ab\x07cd\nreal query\nab\x1bcd ef"), ["real query"])

    def test_a_line_with_a_web_address_in_it_is_dropped(self):
        self.assertEqual(self.queries("www.example.org guide\nsee www.example.org\nreal query"), ["real query"])

    def test_letters_of_other_alphabets_and_digits_are_taken(self):
        self.assertEqual(self.queries("régulation optimale\nуправление системами\n制御理論 入門\nlog4 base 2"),
                         ["régulation optimale", "управление системами", "制御理論 入門", "log4 base 2"])

    def test_a_line_that_introduces_a_list_is_dropped(self):
        self.assertEqual(self.queries("Here are three queries:\noptimal control\nfeedback stability"),
                         ["optimal control", "feedback stability"])

    def test_a_line_of_more_than_12_words_is_dropped(self):
        long = " ".join(["word"] * 13)
        self.assertEqual(self.queries(long + "\n" + " ".join(["word"] * 12)), [" ".join(["word"] * 12)])

    def test_a_reply_with_no_readable_line_gives_the_fallback(self):
        fallback = make(chat=None)
        for reply in ("", "\n\n", "ab", ";;;\n|||", "x" * 5000, "a;b\nc|d"):
            with self.subTest(reply=reply[:20]):
                self.assertEqual(self.queries(reply), fallback[:5])

    def test_a_reply_that_is_not_text_gives_the_fallback(self):
        fallback = make(chat=None)
        for reply in (None, 5, b"optimal control", ["optimal control"], {"a": "b"}):
            with self.subTest(reply=reply):
                self.assertEqual(self.queries(reply), fallback)

    def test_a_reply_over_4096_characters_is_not_read_at_all(self):
        reply = "optimal control\n" + "feedback stability\n" * 400
        self.assertGreater(len(reply), 4096)
        self.assertEqual(self.queries(reply), make(chat=None))

    def test_a_model_that_is_down_gives_the_fallback_and_is_not_remembered(self):
        cache = {}
        chat = FakeChat(KbError("the model server does not answer"), "optimal control\nfeedback stability")
        self.assertEqual(make(chat=chat, cache=cache), make(chat=None))
        self.assertEqual(cache, {})
        self.assertEqual(make(chat=chat, cache=cache), ["optimal control", "feedback stability"])
        self.assertEqual(len(chat.prompts), 2)

    def test_any_other_error_of_the_model_call_is_not_hidden(self):
        with self.assertRaises(ZeroDivisionError):
            make(chat=FakeChat(ZeroDivisionError()))


class CacheTest(unittest.TestCase):
    def test_the_same_topic_number_and_version_are_served_from_the_cache_and_the_model_is_not_asked_again(self):
        cache = {}
        chat = FakeChat("optimal control\nfeedback stability")
        first = make(chat=chat, cache=cache)
        second = make(chat=chat, cache=cache)
        self.assertEqual(first, second)
        self.assertEqual(len(chat.prompts), 1)

    def test_the_cache_is_served_to_a_run_that_has_no_model(self):
        cache = {}
        first = make(chat=FakeChat("optimal control\nfeedback stability"), cache=cache)
        self.assertEqual(make(chat=None, cache=cache), first)

    def test_another_topic_number_or_version_asks_again(self):
        cache = {}
        chat = FakeChat("optimal control\nfeedback stability")
        make(chat=chat, cache=cache)
        make(topic="Category theory", chat=chat, cache=cache)
        make(n=4, chat=chat, cache=cache)
        make(version="crawl-query-other", chat=chat, cache=cache)
        self.assertEqual(len(chat.prompts), 4)

    def test_a_fallback_is_never_put_in_the_cache(self):
        cache = {}
        make(chat=None, cache=cache)
        make(chat=FakeChat("ab"), cache=cache)
        self.assertEqual(cache, {})

    def test_what_comes_out_of_the_cache_is_read_again_and_a_poisoned_cache_is_not_trusted(self):
        for poison in ("optimal control", None, 5, [], [5], ["a;b"], ["ok query", "ok query"], ["x" * 500], ["optimal  control"],
                       ["optimal\u200bcontrol"], [" optimal control"], ["optimal control "],
                       ["fine query"] * 2 + ["a" * 130], ["fine one", "fine two", "fine three", "fine four"]):
            with self.subTest(poison=poison):
                cache = {}
                chat = FakeChat("optimal control\nfeedback stability")
                make(chat=chat, cache=cache)
                (key,) = cache
                cache[key] = poison
                got = make(chat=chat, cache=cache)
                self.assertEqual(got, ["optimal control", "feedback stability"])  # asked again

    def test_what_is_stored_is_never_longer_than_n(self):
        cache = {}
        make(n=2, chat=FakeChat("one aaa\ntwo bbb\nthree ccc"), cache=cache)
        (key,) = cache
        self.assertEqual(cache[key], ["one aaa", "two bbb"])

    def test_the_cache_must_be_a_mapping_that_can_be_written(self):
        for cache in (None, [], "x", 5, frozenset()):
            with self.subTest(cache=cache):
                with self.assertRaises(KbError):
                    crawlqueries.make_queries("Control theory", 3, None, cache, VERSION)

    def test_the_cache_key_names_the_version_the_topic_and_the_number(self):
        cache = {}
        make(chat=FakeChat("optimal control"), cache=cache)
        (key,) = cache
        self.assertIn(VERSION, key)
        self.assertIn("Control theory", key)
        self.assertIn("3", key)


class FallbackTest(unittest.TestCase):
    def test_with_no_model_the_queries_are_the_topic_and_a_plain_variant_or_two(self):
        got = make(n=3, chat=None)
        self.assertEqual(got[0], "Control theory")
        self.assertEqual(len(got), 3)
        self.assertEqual(len(set(got)), 3)
        for q in got[1:]:
            self.assertTrue(q.startswith("Control theory "), q)

    def test_n_cuts_the_fallback(self):
        self.assertEqual(make(n=1, chat=None), ["Control theory"])
        self.assertEqual(len(make(n=2, chat=None)), 2)
        self.assertEqual(len(make(n=9, chat=None)), 3)

    def test_a_long_topic_is_cut_to_a_query_and_every_variant_fits(self):
        got = make(topic=" ".join(["word"] * 60), n=3, chat=None)  # 299 characters, a topic the file reader takes
        self.assertTrue(all(3 <= len(q) <= 120 for q in got), got)
        self.assertEqual(len(set(got)), 3)
        for q in got:  # cut at a word, never in the middle of one
            self.assertLessEqual(set(q.split()), {"word", "survey", "introduction"}, q)

    def test_a_topic_of_exactly_120_characters_is_the_first_query_and_the_variants_are_cut_to_fit(self):
        topic = " ".join(["abcdefghi"] * 12)[:119] + "z"
        self.assertEqual(len(topic), 120)
        got = make(topic=topic, n=3, chat=None)
        self.assertEqual(got[0], topic)
        self.assertTrue(all(len(q) <= 120 for q in got), got)
        self.assertEqual(got[1:], [topic[: 120 - len(" survey")].rsplit(" ", 1)[0] + " survey",
                                   topic[: 120 - len(" introduction")].rsplit(" ", 1)[0] + " introduction"])

    def test_the_fallback_keeps_the_owners_words_as_written(self):
        self.assertEqual(make(topic="C# programming", chat=None)[0], "C# programming")
        self.assertEqual(make(topic="Q&A; systems | design", chat=None)[0], "Q&A; systems | design")

    def test_the_fallback_is_the_same_every_time(self):
        self.assertEqual(make(chat=None), make(chat=None))


class InputTest(unittest.TestCase):
    def test_n_must_be_from_1_to_10(self):
        for n in (0, -1, 11, 1.5, True, "3", None):
            with self.subTest(n=n):
                with self.assertRaises(KbError):
                    make(n=n)
        for n in (1, 10):
            self.assertTrue(make(n=n, chat=None))

    def test_a_topic_of_one_character_is_taken_as_the_topics_file_reader_takes_it(self):
        for topic in ("R", "C", "AI", "Go", "x" * 300):
            with self.subTest(topic=topic):
                self.assertEqual(make(topic=topic, chat=None)[0], topic[:120])  # a topic over 120 characters is cut for a query
                self.assertEqual(make(topic=topic, chat=FakeChat("optimal control")), ["optimal control"])

    def test_every_topic_the_file_reader_takes_is_taken_here(self):
        import os
        import tempfile

        from kb import crawltopics

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "topics.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[core weight=3]\nR\nC#\nAI\n" + "y" * 300 + "\nControl theory\n")
            for topic, _, _ in crawltopics.read_topics(path):
                with self.subTest(topic=topic[:20]):
                    self.assertTrue(make(topic=topic, chat=None))
                    self.assertTrue(make(topic=topic, chat=FakeChat("optimal control")))

    def test_the_topic_must_be_a_clean_text_of_1_to_300_characters(self):
        for topic in ("", "x" * 301, 5, None, "a\x00b", "line\nbreak", "a\u202eb", " padded "):
            with self.subTest(topic=topic):
                with self.assertRaises(KbError):
                    make(topic=topic)

    def test_the_version_must_be_a_short_name(self):
        for version in ("", "x" * 41, "a b", "a/b", None, 5, "Upper"):
            with self.subTest(version=version):
                with self.assertRaises(KbError):
                    make(version=version)

    def test_the_model_must_be_a_function_or_none(self):
        for chat in ("chat", 5, [], {}):
            with self.subTest(chat=chat):
                with self.assertRaises(KbError):
                    make(chat=chat)

    def test_nothing_but_the_topic_reaches_the_model(self):
        chat = FakeChat("optimal control")
        make(topic="Control theory", chat=chat)
        (prompt,) = chat.prompts
        self.assertEqual(prompt, crawlqueries.build_prompt("Control theory", 3))


if __name__ == "__main__":
    unittest.main()
