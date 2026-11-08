import unittest

from kb import quotes


PIECE = ("The stopping rule is proved optimal for independent observations.\n"
         "A well-\nknown bound holds when the variance is finite. The e\N{SOFT HYPHEN}fficient method uses the \N{LATIN SMALL LIGATURE FI}rst  moment only.")


class NormalizeTest(unittest.TestCase):
    def test_case_ligatures_soft_hyphens_and_white_space_are_made_one_form(self):
        self.assertEqual(quotes.normalize("The  \N{LATIN SMALL LIGATURE FI}rst\tmoment \n only"), "the first moment only")
        self.assertEqual(quotes.normalize("e\N{SOFT HYPHEN}fficient"), "efficient")
        self.assertEqual(quotes.normalize("  A\N{NO-BREAK SPACE}B  "), "a b")  # NFKC makes a no-break space a space

    def test_letters_of_other_forms_are_the_plain_letters(self):
        self.assertEqual(quotes.normalize("\N{FULLWIDTH LATIN SMALL LETTER S}top\N{SUPERSCRIPT TWO}"), "stop2")

    def test_the_hyphens_of_other_scripts_are_one_hyphen(self):
        self.assertEqual(quotes.normalize("well\N{HYPHEN}known well\N{NON-BREAKING HYPHEN}known well\N{FIGURE DASH}known"), "well-known well-known well-known")

    def test_a_hyphen_at_the_end_of_a_line_is_joined_by_default_and_kept_on_request(self):
        self.assertEqual(quotes.normalize("a well-\nknown bound"), "a wellknown bound")
        self.assertEqual(quotes.normalize("a well-\n  known bound", join=False), "a well-known bound")
        self.assertEqual(quotes.normalize("a well- known"), "a wellknown")  # a reply has its line breaks turned into spaces
        self.assertEqual(quotes.normalize("a well- known", join=False), "a well-known")
        self.assertEqual(quotes.normalize("a - b and x -y"), "a - b and x -y")  # a dash between spaces, or a hyphen before a letter, is not a break

    def test_the_result_is_stable(self):
        once = quotes.normalize(PIECE)
        self.assertEqual(quotes.normalize(once), once)


class OccursTest(unittest.TestCase):
    def test_a_quote_that_is_in_the_piece_occurs(self):
        self.assertTrue(quotes.occurs("is proved optimal for independent observations", PIECE))

    def test_differences_of_case_ligature_soft_hyphen_and_white_space_are_accepted(self):
        for quote in ("THE STOPPING RULE IS PROVED OPTIMAL", "the \N{LATIN SMALL LIGATURE FI}rst moment only", "The efficient   method uses", "uses the first\nmoment only"):
            with self.subTest(quote):
                self.assertTrue(quotes.occurs(quote, PIECE))

    def test_a_hyphen_at_a_line_end_may_be_quoted_with_or_without_the_hyphen(self):
        self.assertTrue(quotes.occurs("a well-known bound holds when", PIECE))   # the hyphen kept
        self.assertTrue(quotes.occurs("a wellknown bound holds when", PIECE))    # the word joined

    def test_a_quote_copied_across_a_line_break_whose_newline_became_a_space_still_occurs(self):
        self.assertTrue(quotes.occurs("A well- known bound holds when the variance", PIECE))  # as a cleaned reply has it
        self.assertTrue(quotes.occurs("a wellknown bound holds when the variance", PIECE))
        self.assertFalse(quotes.occurs("a well- unknown bound holds when the variance", PIECE))

    def test_a_quote_of_punctuation_or_too_few_letters_does_not_occur_even_in_a_piece_that_has_it(self):
        piece = "Contents ............ 12\n\n------------\n\n3 + 4 = 7 and 1 2 3 4 5"
        for quote in ("............", "------------", "3 + 4 = 7 and", ".... 12 ...."):
            with self.subTest(quote):
                self.assertFalse(quotes.occurs(quote, piece))
        self.assertTrue(quotes.occurs("Contents ............ 12", piece))  # eight letters and digits in it
        edge = "see ab.cd.ef.g..... and ab.cd.ef.gh.... here"
        self.assertFalse(quotes.occurs("ab.cd.ef.g.....", edge))  # 15 characters but seven letters
        self.assertTrue(quotes.occurs("ab.cd.ef.gh....", edge))   # eight letters

    def test_a_quote_that_is_not_in_the_piece_does_not_occur(self):
        self.assertFalse(quotes.occurs("the rule is proved optimal for dependent observations", PIECE))
        self.assertFalse(quotes.occurs("an unrelated sentence about something else entirely", PIECE))

    def test_a_quote_under_twelve_characters_after_normalising_is_refused(self):
        self.assertTrue(quotes.occurs("stopping rule", PIECE))        # 13 characters
        self.assertFalse(quotes.occurs("stopping ru", PIECE))         # 11 characters: in the piece but too short
        self.assertFalse(quotes.occurs("the   rule", PIECE))          # 8 after the spaces are made one
        self.assertFalse(quotes.occurs("", PIECE))

    def test_a_quote_over_240_characters_is_refused_even_if_it_occurs(self):
        long = "word " * 80
        self.assertTrue(quotes.occurs(long[:240], long * 2))
        self.assertFalse(quotes.occurs(long[:241], long * 2))

    def test_a_quote_made_of_the_words_of_two_pieces_occurs_in_neither(self):
        first, second = "the first piece ends with this sentence", "the second piece begins with these words"
        quote = "ends with this sentence the second piece begins"
        self.assertFalse(quotes.occurs(quote, first))
        self.assertFalse(quotes.occurs(quote, second))
        self.assertTrue(quotes.occurs(quote, first + " " + second))  # only if the pieces were one text

    def test_the_title_or_a_heading_is_not_part_of_the_piece(self):
        self.assertFalse(quotes.occurs("On the optimal stopping of observations", PIECE))

    def test_text_that_is_not_text_is_not_a_quote(self):
        for bad in (None, 5, ["stopping rule"]):
            with self.subTest(bad):
                self.assertFalse(quotes.occurs(bad, PIECE))
        self.assertFalse(quotes.occurs("stopping rule", None))


if __name__ == "__main__":
    unittest.main()
