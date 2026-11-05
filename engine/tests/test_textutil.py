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


if __name__ == "__main__":
    unittest.main()
