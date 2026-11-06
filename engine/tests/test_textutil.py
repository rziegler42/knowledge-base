import time
import unittest

from kb import KbError, textutil


class CleanTest(unittest.TestCase):
    def test_control_direction_zero_width_and_tag_characters_are_removed(self):
        text = "a\x1b[31mb‮c​d\x07e\U000e0041f g"
        self.assertEqual(textutil.clean(text, 100), "a[31mbcdef g")

    def test_characters_that_show_as_nothing_are_removed_too(self):
        for ch in ("ㅤ", "ᅟ", "ᅠ", "ﾠ", "⠀", "͏", "️", "\U000e0100"):
            self.assertEqual(textutil.clean(f"a{ch}b", 100), "ab", repr(ch))

    def test_ordinary_text_in_other_scripts_is_kept(self):
        for text in ("café", "日本語", "مرحبا", "αβγ ≠ x²", "naïve résumé"):
            self.assertEqual(textutil.clean(text, 100), text)

    def test_whitespace_is_collapsed_and_the_result_is_cut_from_the_start_or_the_end(self):
        self.assertEqual(textutil.clean("  a \n\n b\t\tc  ", 100), "a b c")
        self.assertEqual(textutil.clean("abcdef", 3), "abc")
        self.assertEqual(textutil.clean("abcdef", 3, tail=True), "def")
        self.assertEqual(textutil.clean(None, 5), "")

    def test_a_name_is_shown_as_a_quoted_ascii_literal_cut_to_a_length(self):
        self.assertEqual(textutil.literal("a\nb\x1b‮"), "'a\\nb\\x1b\\u202e'")
        self.assertLessEqual(len(textutil.literal("x" * 500, 40)), 40)
        self.assertTrue(textutil.literal("x" * 500, 40).endswith("..."))


# the code points Unicode calls default-ignorable: they show as nothing, so they can carry a hidden message
IGNORABLE = ([0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFEFF, 0xFFA0]
             + list(range(0x180B, 0x1810)) + list(range(0x200B, 0x2010)) + list(range(0x202A, 0x202F))
             + list(range(0x2060, 0x2070)) + list(range(0xFE00, 0xFE10)) + list(range(0xFFF0, 0xFFF9))
             + list(range(0x1BCA0, 0x1BCA4)) + list(range(0x1D173, 0x1D17B)) + list(range(0xE0000, 0xE1000)))


class CleanIsStableTest(unittest.TestCase):
    """What clean() returns is its own cleaned form, however it was cut, because other code compares a stored string with it."""

    def test_a_hidden_character_between_spaces_leaves_one_space_and_a_cut_leaves_no_trailing_space(self):
        self.assertEqual(textutil.clean("a ​ b", 100), "a b")
        self.assertEqual(textutil.clean("word " * 100, 5), "word")
        self.assertEqual(textutil.clean("x" + " word" * 100, 5, tail=True), "word")
        self.assertEqual(textutil.clean("  ", 5), "")

    def test_cleaning_what_was_cleaned_changes_nothing_whatever_the_cut(self):
        samples = ["a ​ b c", "word " * 20, "x​ ‮ y z", " lead and trail ", "​ a ​", "one  two\tthree\nfour", "ㅤ a ㅤ b"]
        for text in samples:
            for limit in range(1, 30):
                for tail in (False, True):
                    once = textutil.clean(text, limit, tail=tail)
                    self.assertEqual(textutil.clean(once, limit, tail=tail), once, (text, limit, tail))
                    self.assertEqual(once, once.strip())


class HiddenCharactersTest(unittest.TestCase):
    def test_every_default_ignorable_code_point_is_removed_from_a_message_and_from_a_block(self):
        survivors = [hex(cp) for cp in IGNORABLE
                     if textutil.clean(f"a{chr(cp)}b", 100) != "ab" or textutil.block_text(f"a{chr(cp)}b") != "ab"]
        self.assertEqual(survivors, [])

    def test_the_vowels_of_scripts_that_use_combining_marks_are_kept(self):
        for word in ("हिन्दी", "ខ្មែរ", "ᠮᠣᠩᠭᠣᠯ", "বাংলা", "العربية"):
            self.assertEqual(textutil.block_text(word), word)


class BlockTextTest(unittest.TestCase):
    """The text of a converted block: line structure is kept, everything that could hide or reorder is not."""

    def test_lines_are_kept_but_spaces_and_empty_lines_are_not(self):
        self.assertEqual(textutil.block_text("  a   b \n\n\n  c\t\td  \r\n"), "a b\nc d")
        self.assertEqual(textutil.block_text("one\x0bTwo three\x85four"), "one\nTwo\nthree\nfour")

    def test_hidden_and_reordering_characters_are_removed_inside_a_line_and_do_not_join_lines(self):
        text = "a\x1b[31mb‮c​d\U000e0041e\nf⠀g"
        self.assertEqual(textutil.block_text(text), "a[31mbcde\nfg")

    def test_text_in_other_scripts_is_kept(self):
        for text in ("café au lait", "日本語 の 文", "مرحبا بالعالم", "αβγ ≠ x²"):
            self.assertEqual(textutil.block_text(text), text)

    def test_nothing_but_hidden_characters_is_empty(self):
        self.assertEqual(textutil.block_text("​‮ \n ️"), "")
        self.assertEqual(textutil.block_text(None), "")
        self.assertEqual(textutil.block_text(""), "")


if __name__ == "__main__":
    unittest.main()


class WindowTest(unittest.TestCase):
    """Where a piece ends and the next begins, on texts made for it."""

    def test_a_text_that_fits_is_one_piece_with_nothing_after_it(self):
        text = "alpha beta gamma delta"
        self.assertEqual(textutil.window(text, 0, 22), (22, None))
        self.assertEqual(textutil.window(text, 0, 100), (22, None))
        self.assertEqual(textutil.window(text, 6, 16), (22, None))  # from the middle, exactly to the end

    def test_a_text_that_does_not_fit_is_cut_at_the_last_break_in_the_later_half(self):
        text = "aaaa bbbb cccc dddd eeee ffff"  # spaces at 4, 9, 14, 19, 24
        self.assertEqual(textutil.window(text, 0, 17), (14, 15))
        self.assertEqual(textutil.window(text, 0, 12), (9, 10))
        self.assertEqual(textutil.window(text, 5, 12), (14, 15))

    def test_a_line_break_is_a_break_too(self):
        text = "a" * 60 + "\n" + "b" * 60
        self.assertEqual(textutil.window(text, 0, 100), (60, 61))

    def test_a_text_with_no_break_in_the_later_half_is_cut_at_the_amount(self):
        text = "aaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"  # the only space is in the first half
        self.assertEqual(textutil.window(text, 0, 40), (40, 40))
        self.assertEqual(textutil.window("a" * 300, 0, 100), (100, 100))

    def test_what_is_left_after_a_cut_is_not_just_space(self):
        self.assertEqual(textutil.window("aaaa bbbb      ", 0, 9), (15, None))  # nothing but space follows, so it is the end

    def test_the_next_piece_begins_at_the_first_character_that_is_not_space(self):
        self.assertEqual(textutil.window("aaaa bbbb \n\n   cccc dddd", 0, 12), (12, 15))  # the piece "aaaa bbbb", then the next word


class PiecesTest(unittest.TestCase):
    def test_a_short_text_is_one_piece_and_an_empty_one_has_none(self):
        self.assertEqual(textutil.pieces("alpha beta", 100), [(0, 10)])
        self.assertEqual(textutil.pieces("", 100), [])

    def test_the_pieces_are_in_order_none_is_longer_than_the_size_and_together_they_hold_every_word_once(self):
        words = [f"w{n:05d}" for n in range(3000)]
        text = " ".join(words)
        found = textutil.pieces(text, 500)
        self.assertGreater(len(found), 30)
        previous = 0
        for start, end in found:
            self.assertGreaterEqual(start, previous)
            self.assertLessEqual(end - start, 500)
            self.assertGreater(end, start)
            self.assertFalse(text[start].isspace() or text[end - 1].isspace(), (start, end))  # each begins and ends at a word
            previous = end
        self.assertEqual(" ".join(text[s:e] for s, e in found).split(), words)  # no gap and no repeat

    def test_a_piece_starts_at_the_first_character_that_is_not_space_and_a_text_with_no_break_is_cut_at_the_size(self):
        text = "aaaa bbbb \n\n   cccc dddd"
        self.assertEqual([text[s:e].strip() for s, e in textutil.pieces(text, 12)], ["aaaa bbbb", "cccc dddd"])
        self.assertEqual(textutil.pieces("x" * 5000, 2000), [(0, 2000), (2000, 4000), (4000, 5000)])

    def test_a_great_text_is_cut_in_a_time_that_grows_with_its_size_alone(self):
        text = ("lorem ipsum dolor " * 300_000)  # 5.4 million characters
        started = time.monotonic()
        found = textutil.pieces(text, 2000)
        self.assertLess(time.monotonic() - started, 5)
        self.assertGreater(len(found), 2700)
        started = time.monotonic()
        textutil.pieces("x" * 5_000_000, 2000)
        self.assertLess(time.monotonic() - started, 5)
