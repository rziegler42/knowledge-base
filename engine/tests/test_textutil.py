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
